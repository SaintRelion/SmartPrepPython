import json

from api.analytics.models import (
    ComparativeTrendResponse,
    ForensicAttemptRequest,
    ForensicAttemptResponse,
    ForensicLogItem,
    GlobalExcellenceResponse,
    GrowthTrendResponse,
    LeaderEntry,
    PerformanceMetric,
    SlotMetric,
    StatsRequest,
    ExamAnalyticsResponse,
    SubjectLeaderboard,
)
from utils.db import db

from fastapi import APIRouter

router = APIRouter(prefix="/analytics", tags=["analytics"])


class AnalyticsController:
    @staticmethod
    @router.get("/get_leaderboard", response_model=GlobalExcellenceResponse)
    async def get_leaderboard_GET() -> GlobalExcellenceResponse:
        sql = """
            WITH UserTopicStats AS (
                SELECT 
                    u.username,
                    c.name as topic_name,
                    SUM(CAST(er.is_correct AS UNSIGNED)) as correct_count,
                    COUNT(er.id) as total_count
                FROM examination_results er
                JOIN examination_attempts ea ON er.user_id = ea.user_id 
                    AND er.examination_id = ea.examination_id 
                    AND er.attempt_index = ea.attempts -- Direct filter for latest attempts
                JOIN questionnaire_items qi ON er.question_id = qi.id
                JOIN source_references sr ON qi.questionnaire_id = sr.id
                JOIN category c ON sr.category_id = c.id
                JOIN users u ON er.user_id = u.id
                GROUP BY u.id, c.id
            ),
            CategoryRankings AS (
                SELECT 
                    topic_name as group_title,
                    username,
                    total_count as items_count,
                    (correct_count * 100.0 / total_count) as percentage,
                    ROW_NUMBER() OVER (PARTITION BY topic_name ORDER BY (correct_count / total_count) DESC) as rank_pos
                FROM UserTopicStats
            ),
            OverallStats AS (
                SELECT 
                    username,
                    SUM(correct_count) as total_correct,
                    SUM(total_count) as total_items
                FROM UserTopicStats
                GROUP BY username
            ),
            OverallRankings AS (
                SELECT 
                    'OVERALL' as group_title,
                    username,
                    total_items as items_count,
                    (total_correct * 100.0 / total_items) as percentage,
                    ROW_NUMBER() OVER (ORDER BY (total_correct / total_items) DESC) as rank_pos
                FROM OverallStats
            )
            SELECT * FROM OverallRankings WHERE rank_pos <= 10
            UNION ALL
            SELECT * FROM CategoryRankings WHERE rank_pos <= 5
            ORDER BY CASE WHEN group_title = 'OVERALL' THEN 0 ELSE 1 END, group_title ASC, rank_pos ASC
        """

        rows = db.select(sql)
        if not rows:
            return GlobalExcellenceResponse(success=True, subject_leaderboards=[])

        # 2. Lean Grouping Logic
        # We use a dictionary to group performers by their group_title (Subject or OVERALL)
        grouped_data = {}
        for r in rows:
            title = r["group_title"]
            if title not in grouped_data:
                grouped_data[title] = []

            grouped_data[title].append(
                LeaderEntry(
                    rank=r["rank_pos"],
                    student_name=r["username"],
                    percentage=round(
                        float(r["percentage"]), 2
                    ),  # Cast to float to avoid Decimal errors
                    total_items=int(r["items_count"]),
                )
            )

        # Convert to the final response model list
        return GlobalExcellenceResponse(
            success=True,
            subject_leaderboards=[
                SubjectLeaderboard(topic_name=name, top_performers=leaders)
                for name, leaders in grouped_data.items()
            ],
        )

    @router.post("/get_exam_analytics", response_model=ExamAnalyticsResponse)
    async def get_exam_analytics_POST(req: StatsRequest) -> ExamAnalyticsResponse:
        meta_sql = """
            SELECT 
                (SELECT total_items FROM examinations WHERE id = %s) as total_items,
                (SELECT COUNT(DISTINCT user_id) FROM examination_results WHERE examination_id = %s) as user_count
        """
        meta = db.select(meta_sql, (req.examination_id, req.examination_id))[0]

        official_total_items = float(meta["total_items"] or 0)
        user_count = float(meta["user_count"] if not req.user_id else 1)
        div = user_count if user_count > 0 else 1.0

        # 2. SQL Aggregation: Use examination_questions for the Denominator
        sql = """
            SELECT 
                c.id as category_id,
                c.name as category_name,
                sr.slot_name,
                SUM(CAST(er.is_correct AS UNSIGNED)) as total_correct_in_batch,
                (
                    SELECT COUNT(*) 
                    FROM examination_questions eq2
                    JOIN questionnaire_items qi2 ON eq2.questionnaire_item_id = qi2.id
                    WHERE eq2.examination_id = %s AND qi2.questionnaire_id = sr.id
                ) as exam_slot_total
            FROM examination_results er
            JOIN examination_attempts ea ON er.examination_id = ea.examination_id 
                AND er.user_id = ea.user_id 
                AND er.attempt_index = ea.attempts 
            JOIN questionnaire_items qi ON er.question_id = qi.id
            JOIN source_references sr ON qi.questionnaire_id = sr.id
            JOIN category c ON sr.category_id = c.id
            WHERE er.examination_id = %s
        """

        # We pass the exam_id twice: once for the subquery denominator, once for the results
        params = [req.examination_id, req.examination_id]
        if req.user_id:
            sql += " AND er.user_id = %s"
            params.append(req.user_id)

        sql += " GROUP BY c.id, sr.id"
        rows = db.select(sql, tuple(params))

        topic_map = {}
        running_avg_numerator = 0.0

        for r in rows:
            tid = r["category_id"]
            if tid not in topic_map:
                topic_map[tid] = {
                    "name": r["category_name"],
                    "score": 0.0,
                    "total": 0.0,
                    "slots": [],
                }

            # DENOMINATOR: Only items assigned to THIS exam
            slot_total = float(r["exam_slot_total"] or 0)

            # NUMERATOR: Average score (Batch Sum / User Count)
            avg_score = float(r["total_correct_in_batch"]) / div
            running_avg_numerator += avg_score

            s_perc = round((avg_score / slot_total) * 100, 2) if slot_total > 0 else 0

            topic_map[tid]["slots"].append(
                SlotMetric(
                    slot_name=r["slot_name"],
                    score=round(avg_score, 1),
                    total=slot_total,
                    percentage=s_perc,
                )
            )

            topic_map[tid]["score"] += avg_score
            topic_map[tid]["total"] += slot_total

        # 3. Final Overall Competency
        if official_total_items > 0:
            overall_comp = (running_avg_numerator / official_total_items) * 100
        else:
            overall_comp = 0

        return ExamAnalyticsResponse(
            overall_competency=round(overall_comp, 2),
            topic_breakdown=[
                PerformanceMetric(
                    id=tid,
                    label=data["name"],
                    score=round(data["score"], 1),
                    total=data["total"],
                    percentage=(
                        round((data["score"] / data["total"]) * 100, 2)
                        if data["total"] > 0
                        else 0
                    ),
                    slots=data["slots"],
                )
                for tid, data in topic_map.items()
            ],
        )

    @staticmethod
    @router.post("/get_comparative_trend", response_model=ComparativeTrendResponse)
    async def get_comparative_trend_POST(req: StatsRequest) -> ComparativeTrendResponse:
        params = [req.examination_id]
        user_filter = ""

        # If a user_id is provided, we only look at that student's progression.
        # If not, we look at the entire batch's progression per take number.
        if req.user_id and req.user_id > 0:
            user_filter = " AND user_id = %s"
            params.append(req.user_id)

        sql = f"""
            SELECT 
                res.date_recorded,
                AVG(res.accuracy) as average_accuracy,
                COUNT(DISTINCT res.user_id) as examinee_count,
                ROW_NUMBER() OVER (ORDER BY res.date_recorded ASC) as attempt_number
            FROM (
                SELECT 
                    user_id, 
                    DATE(answered_at) as date_recorded,
                    (COUNT(CASE WHEN is_correct = 1 THEN 1 END) * 100.0 / COUNT(*)) as accuracy
                FROM examination_results
                WHERE (user_id, examination_id, attempt_index) IN (
                    SELECT user_id, examination_id, MAX(attempt_index)
                    FROM examination_results
                    WHERE examination_id = %s {user_filter}
                    GROUP BY user_id, examination_id, DATE(answered_at)
                )
                GROUP BY user_id, examination_id, DATE(answered_at)
            ) res
            GROUP BY res.date_recorded
            ORDER BY res.date_recorded ASC
        """

        trends = db.select(sql, tuple(params))

        # Format dates for the Chart Labels
        for row in trends:
            if row.get("date_recorded"):
                # Format as "Jan 26"
                row["date_recorded"] = row["date_recorded"].strftime("%b %d")

        improvement_score = 0
        status = "Stable"

        if len(trends) >= 2:
            prev = trends[-2]["average_accuracy"]
            curr = trends[-1]["average_accuracy"]
            improvement_score = curr - prev
            if improvement_score > 0:
                status = "Improving"
            elif improvement_score < 0:
                status = "Regressing"

        return {
            "exam_id": req.examination_id,
            "user_id": req.user_id,
            "trend_label": (
                "Individual Progress" if req.user_id else "Batch Daily Performance"
            ),
            "current_status": status,
            "delta": round(improvement_score, 2),
            "history": trends,
        }

    # Though 'slot' but this is grouped by category, didnt bother remaining
    @staticmethod
    @router.post("/get_slot_growth_trend", response_model=GrowthTrendResponse)
    async def get_slot_growth_trend_POST(req: StatsRequest) -> GrowthTrendResponse:
        params = []
        user_filter = ""

        if req.user_id and req.user_id > 0:
            user_filter = " AND er.user_id = %s"
            params.append(req.user_id)

        # UPDATED: Join Category table and Group by Category instead of Slot
        sql = f"""
            SELECT 
                DATE(er.answered_at) as date_recorded,
                c.name as category_group_name, -- This is what we group by now
                (SUM(er.is_correct) * 100.0 / COUNT(er.id)) as accuracy,
                COUNT(DISTINCT er.user_id) as examinee_count
            FROM examination_results er
            JOIN questionnaire_items qi ON er.question_id = qi.id
            JOIN source_references sr ON qi.questionnaire_id = sr.id
            JOIN category c ON sr.category_id = c.id
            WHERE 1=1 {user_filter}
            GROUP BY DATE(er.answered_at), c.id, c.name
            ORDER BY DATE(er.answered_at) ASC, c.name ASC
        """

        rows = db.select(sql, tuple(params))

        unique_slots = sorted(list(set(r["category_group_name"] for r in rows)))

        formatted_history = []
        for r in rows:
            formatted_history.append(
                {
                    "date_recorded": r["date_recorded"].strftime("%b %d"),
                    "slot_name": r[
                        "category_group_name"
                    ],  # Map category name to slot_name key
                    "accuracy": float(r["accuracy"]),
                    "examinee_count": int(r["examinee_count"]),
                }
            )

        result = {
            "trend_label": (
                "Category Mastery Growth"
                if req.user_id
                else "Global Category Performance"
            ),
            "unique_slots": unique_slots,  # This list now acts as the Legend for Categories
            "history": formatted_history,
        }

        return result

    # python
    @router.post("/get_attempt_forensics", response_model=ForensicAttemptResponse)
    async def get_attempt_forensics_POST(
        req: ForensicAttemptRequest,
    ) -> ForensicAttemptResponse:
        target_user_id = None if req.user_id == -1 else req.user_id

        # Store if the user specifically asked for "Latest" (-1)
        is_latest_request = req.attempt_index == -1

        actual_take_num = req.attempt_index
        if is_latest_request:
            # Fetch the max take_num for this context
            latest_sql = "SELECT COUNT(DISTINCT attempt_index) as max_take FROM examination_results WHERE examination_id = %s"
            latest_params = [req.examination_id]
            if target_user_id:
                latest_sql += " AND user_id = %s"
                latest_params.append(target_user_id)

            latest_res = db.select(latest_sql, tuple(latest_params))
            actual_take_num = latest_res[0]["max_take"] if latest_res else 1

        sql = (
            """
            WITH RankedAttempts AS (
                SELECT 
                    er.*,
                    DENSE_RANK() OVER (PARTITION BY er.user_id ORDER BY er.answered_at ASC) as take_num
                FROM examination_results er
                WHERE er.examination_id = %s
                """
            + ("AND er.user_id = %s" if target_user_id else "")
            + """
            ),
            StepAnalysis AS (
                SELECT 
                    ra.*,
                    LAG(ra.student_answer) OVER (PARTITION BY ra.user_id, ra.question_id ORDER BY ra.take_num ASC) as prev_ans,
                    LAG(ra.is_correct) OVER (PARTITION BY ra.user_id, ra.question_id ORDER BY ra.take_num ASC) as prev_cor
                FROM RankedAttempts ra
            )
            SELECT 
                qi.id as question_id, 
                ANY_VALUE(qi.question_text) as question_text, 
                ANY_VALUE(qi.choices) as choices, 
                ANY_VALUE(qi.correct_answer) as correct_answer,
                ANY_VALUE(c.id) as category_id, 
                ANY_VALUE(c.name) as category_name, 
                ANY_VALUE(sr.slot_name) as slot_name, 
                ANY_VALUE(ia.reasoning) as reasoning,
                ANY_VALUE(sa.student_answer) as student_answer, 
                ANY_VALUE(sa.is_correct) as is_correct,
                ANY_VALUE(sa.prev_ans) as prev_ans, 
                ANY_VALUE(sa.prev_cor) as prev_cor
            FROM StepAnalysis sa
            JOIN questionnaire_items qi ON sa.question_id = qi.id
            JOIN source_references sr ON qi.questionnaire_id = sr.id
            JOIN category c ON sr.category_id = c.id
            LEFT JOIN item_analysis ia ON qi.id = ia.item_id
            WHERE sa.take_num = %s
            GROUP BY qi.id
        """
        )

        params = [req.examination_id]
        if target_user_id:
            params.append(target_user_id)
        params.append(actual_take_num)

        rows = db.select(sql, tuple(params))

        comparative_items = []
        for r in rows:
            choices = (
                json.loads(r["choices"])
                if isinstance(r["choices"], str)
                else r["choices"]
            )
            s_key = str(r["student_answer"]).strip().upper()
            c_key = str(r["correct_answer"]).strip().upper()
            norm_choices = {str(k).upper(): v for k, v in choices.items()}

            analysis_dict = json.loads(r["reasoning"]) if r.get("reasoning") else {}

            def get_ana(key):
                return analysis_dict.get(
                    key, f"Technical analysis for Option {key} is unavailable."
                )

            # Logic: If requested via -1, force comparative data to be empty
            p_val = r.get("prev_ans")
            has_prev = (p_val is not None) and (not is_latest_request)
            p_key = str(p_val).strip().upper() if has_prev else ""

            item = ForensicLogItem(
                category_id=r["category_id"],
                category_name=r["category_name"],
                slot_name=r["slot_name"],
                question_text=r["question_text"],
                correct_answer=f"({c_key}) {norm_choices.get(c_key, 'N/A')}",
                student_answer=f"({s_key}) {norm_choices.get(s_key, 'N/A')}",
                is_correct=bool(r["is_correct"]),
                previous_student_answer=(
                    f"({p_key}) {norm_choices.get(p_key, 'N/A')}" if has_prev else ""
                ),
                previous_is_correct=bool(r.get("prev_cor")) if has_prev else False,
                option_a_analysis=get_ana("A"),
                option_b_analysis=get_ana("B"),
                option_c_analysis=get_ana("C"),
                option_d_analysis=get_ana("D"),
            )
            comparative_items.append(item)

        return ForensicAttemptResponse(
            success=True, comparative_items=comparative_items
        )
