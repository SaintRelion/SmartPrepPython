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
    QuestionForensic,
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
        # Updated JOIN: questionnaire -> source_references
        sql = """
            WITH BaseStats AS (
                SELECT 
                    u.id as user_id, u.username,
                    c.id as topic_id, c.name as topic_name,
                    COUNT(er.id) as total_items,
                    SUM(er.is_correct) as correct_items
                FROM examination_results er
                JOIN questionnaire_items qi ON er.question_id = qi.id
                JOIN source_references sr ON qi.questionnaire_id = sr.id
                JOIN category c ON sr.category_id = c.id
                JOIN users u ON er.user_id = u.id
                -- Ensuring we only use the latest attempt per user per question
                WHERE er.attempt_index = (
                    SELECT MAX(attempt_index) FROM examination_results 
                    WHERE user_id = er.user_id AND question_id = er.question_id
                )
                GROUP BY u.id, c.id
            ),
            CategoryRankings AS (
                SELECT 
                    topic_name as group_title,
                    username,
                    (SUM(correct_items) * 100.0 / SUM(total_items)) as percentage,
                    SUM(total_items) as items_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY topic_name 
                        ORDER BY (SUM(correct_items) * 1.0 / SUM(total_items)) DESC
                    ) as rank_pos
                FROM BaseStats
                GROUP BY topic_name, username
            ),
            OverallRankings AS (
                SELECT 
                    'OVERALL' as group_title,
                    username,
                    (SUM(correct_items) * 100.0 / SUM(total_items)) as percentage,
                    SUM(total_items) as items_count,
                    ROW_NUMBER() OVER (
                        ORDER BY (SUM(correct_items) * 1.0 / SUM(total_items)) DESC
                    ) as rank_pos
                FROM BaseStats
                GROUP BY username
            )
            SELECT * FROM OverallRankings WHERE rank_pos <= 10
            UNION ALL
            SELECT * FROM CategoryRankings WHERE rank_pos <= 5
            ORDER BY CASE WHEN group_title = 'OVERALL' THEN 0 ELSE 1 END, group_title ASC, rank_pos ASC
        """

        rows = db.select(sql)

        grouped_data = {}
        for r in rows:
            title = r["group_title"]
            if title not in grouped_data:
                grouped_data[title] = []

            grouped_data[title].append(
                LeaderEntry(
                    rank=r["rank_pos"],
                    student_name=r["username"],
                    percentage=round(r["percentage"], 2),
                    total_items=r["items_count"],
                )
            )

        # Convert grouped dictionary into the expected SubjectLeaderboard list
        leaderboards = [
            SubjectLeaderboard(topic_name=name, top_performers=leaders)
            for name, leaders in grouped_data.items()
        ]

        return GlobalExcellenceResponse(success=True, subject_leaderboards=leaderboards)

    # python
    @router.post("/get_exam_analytics", response_model=ExamAnalyticsResponse)
    async def get_exam_analytics_POST(req: StatsRequest) -> ExamAnalyticsResponse:
        # 1. Fetch total items for the examination context
        exam_info = db.select(
            "SELECT total_items FROM examinations WHERE id = %s", (req.examination_id,)
        )
        total_exam_items = exam_info[0]["total_items"] if exam_info else 0

        # 2. SQL Query joined through source_references using your specific column name
        sql = """
            SELECT 
                er.is_correct,
                er.student_answer,
                qi.question_text,
                qi.choices,
                qi.correct_answer,
                c.id as category_id,
                c.name as category_name,
                sr.slot_name as slot_name,
                ia.reasoning
            FROM examination_results er
            INNER JOIN (
                SELECT user_id, MAX(answered_at) as latest_time
                FROM examination_results
                WHERE examination_id = %s
                GROUP BY user_id
            ) latest_attempts ON er.user_id = latest_attempts.user_id 
                            AND er.answered_at = latest_attempts.latest_time
            JOIN examination_questions eq ON er.question_id = eq.questionnaire_item_id 
                                        AND er.examination_id = eq.examination_id
            JOIN questionnaire_items qi ON eq.questionnaire_item_id = qi.id
            -- CRITICAL FIX: Linking questionnaire_id to source_references.id
            JOIN source_references sr ON qi.questionnaire_id = sr.id
            JOIN category c ON sr.category_id = c.id
            LEFT JOIN item_analysis ia ON qi.id = ia.item_id
            WHERE er.examination_id = %s
        """

        params = [req.examination_id, req.examination_id]
        if req.user_id:
            sql += " AND er.user_id = %s"
            params.append(req.user_id)

        rows = db.select(sql, tuple(params))

        if not rows:
            return ExamAnalyticsResponse(
                overall_competency=0, topic_breakdown=[], question_logs=[]
            )

        topic_map = {}
        question_logs = []
        total_correct = 0

        for r in rows:
            cat_id = r["category_id"]
            slot_name = r["slot_name"]
            is_correct = bool(r["is_correct"])

            if cat_id not in topic_map:
                topic_map[cat_id] = {
                    "name": r["category_name"],
                    "score": 0,
                    "total": 0,
                    "slots": {},
                }

            if slot_name not in topic_map[cat_id]["slots"]:
                topic_map[cat_id]["slots"][slot_name] = {"score": 0, "total": 0}

            topic_map[cat_id]["total"] += 1
            topic_map[cat_id]["slots"][slot_name]["total"] += 1

            if is_correct:
                topic_map[cat_id]["score"] += 1
                topic_map[cat_id]["slots"][slot_name]["score"] += 1
                total_correct += 1  # Track total correct for overall competency

            if req.user_id:
                # Choice normalization and Forensic Logic...
                choices = r["choices"]
                if isinstance(choices, str):
                    choices = json.loads(choices)
                s_key = str(r["student_answer"]).strip().upper()
                c_key = str(r["correct_answer"]).strip().upper()
                norm_choices = {str(k).upper(): v for k, v in choices.items()}

                analysis_dict = {}
                if r.get("reasoning"):
                    try:
                        analysis_dict = json.loads(r["reasoning"])
                    except:
                        analysis_dict = {}

                question_logs.append(
                    QuestionForensic(
                        category_id=cat_id,
                        question_text=r["question_text"],
                        student_answer=f"({s_key}) {norm_choices.get(s_key, 'N/A')}",
                        correct_answer=f"({c_key}) {norm_choices.get(c_key, 'N/A')}",
                        is_correct=is_correct,
                        option_a_analysis=analysis_dict.get("A", "N/A"),
                        option_b_analysis=analysis_dict.get("B", "N/A"),
                        option_c_analysis=analysis_dict.get("C", "N/A"),
                        option_d_analysis=analysis_dict.get("D", "N/A"),
                    )
                )

        print(topic_map)

        # Finalize Performance Metrics
        topic_breakdown = [
            PerformanceMetric(
                id=tid,
                label=data["name"],
                score=data["score"],
                total=data["total"],
                percentage=round((data["score"] / data["total"]) * 100, 2),
                slots=[
                    SlotMetric(
                        slot_name=sname,
                        score=sdata["score"],
                        total=sdata["total"],
                        percentage=round((sdata["score"] / sdata["total"]) * 100, 2),
                    )
                    for sname, sdata in data["slots"].items()
                ],
            )
            for tid, data in topic_map.items()
        ]

        # Calculate overall competency based on the full exam items
        overall_comp = (
            (total_correct / total_exam_items) * 100 if total_exam_items > 0 else 0
        )

        return ExamAnalyticsResponse(
            overall_competency=round(overall_comp, 2),
            topic_breakdown=topic_breakdown,
            question_logs=question_logs,
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

    @router.post("/get_attempt_forensics", response_model=ForensicAttemptResponse)
    async def get_attempt_forensics_POST(
        req: ForensicAttemptRequest,
    ) -> ForensicAttemptResponse:
        target_user_id = None if req.user_id == -1 else req.user_id

        # Updated SQL: JOINS source_references instead of questionnaire
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
                ANY_VALUE(ia.reasoning) as reasoning,
                ANY_VALUE(sa.student_answer) as student_answer, 
                ANY_VALUE(sa.is_correct) as is_correct,
                ANY_VALUE(sa.prev_ans) as prev_ans, 
                ANY_VALUE(sa.prev_cor) as prev_cor
            FROM StepAnalysis sa
            JOIN questionnaire_items qi ON sa.question_id = qi.id
            -- JOIN mapping updated to source_references
            JOIN source_references sr ON qi.questionnaire_id = sr.id
            JOIN category c ON sr.category_id = c.id
            LEFT JOIN item_analysis ia ON qi.id = ia.item_id
            WHERE sa.take_num = %s
            GROUP BY qi.id
        """
        )

        params = [req.examination_id, req.attempt_index]
        if target_user_id:
            params.insert(1, target_user_id)

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

            p_val = r.get("prev_ans")
            has_prev = p_val is not None
            p_key = str(p_val).strip().upper() if has_prev else ""

            item = ForensicLogItem(
                category_id=r["category_id"],
                category_name=r["category_name"],
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
