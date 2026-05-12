import json

from api.analytics.helper import get_calculated_exam_stats
from api.analytics.models import (
    AIAnalysisData,
    BasicAttemptLogItem,
    BasicAttemptResponse,
    ComparativeTrendResponse,
    ForensicAttemptRequest,
    ForensicAttemptResponse,
    ForensicLogItem,
    GenerateAnalysisRequest,
    GenerateAnalysisResponse,
    GlobalExcellenceResponse,
    GrowthTrendResponse,
    ItemAnalysisRequest,
    ItemAnalysisResponse,
    LeaderEntry,
    PerformanceMetric,
    QuestionDistribution,
    StatsRequest,
    ExamAnalyticsResponse,
    SubjectLeaderboard,
)
from utils.db import db

from fastapi import APIRouter

from utils.ollama import analyze_overall_examination_ollama

router = APIRouter(prefix="/analytics", tags=["analytics"])


class AnalyticsController:
    @staticmethod
    @router.post("/generate_overall_analysis", response_model=GenerateAnalysisResponse)
    async def generate_overall_analysis_POST(
        req: GenerateAnalysisRequest,
    ) -> GenerateAnalysisResponse:
        try:
            batch_stats = get_calculated_exam_stats(examination_id=req.examination_id)

            if not batch_stats or batch_stats["overall_competency"] == 0:
                return GenerateAnalysisResponse(
                    success=False,
                    message="No data available to analyze. Waiting for student submissions.",
                    data=None,
                )

            topics = batch_stats["topic_breakdown"]
            worst_topics = sorted(topics, key=lambda x: x["percentage"])[:2]

            # 3. Call your specific Ollama function
            ai_response = analyze_overall_examination_ollama(
                overall_accuracy=batch_stats["overall_competency"],
                worst_topics=worst_topics,
                full_breakdown=topics,
            )

            if not ai_response or "summary" not in ai_response:
                print("AI failed to generate a valid response. Please try again.")
                return GenerateAnalysisResponse(
                    success=False,
                    message="AI failed to generate a valid response. Please try again.",
                    data=None,
                )

            db.execute(
                "UPDATE examinations SET analysis = %s WHERE id = %s",
                (json.dumps(ai_response), req.examination_id),
            )

            print("AI generated a valid response.")
            return GenerateAnalysisResponse(
                success=True,
                message="Batch analysis generated successfully.",
                data=AIAnalysisData(**ai_response),
            )

        except Exception as e:
            print(f"Error generating overall analysis: {e}")
            return GenerateAnalysisResponse(
                success=False,
                message=f"An internal error occurred: {str(e)}",
                data=None,
            )

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
        try:
            stats_data = get_calculated_exam_stats(
                examination_id=req.examination_id, user_id=req.user_id
            )

            ai_data_obj = None
            if stats_data.get("ai_analysis"):
                ai_data_obj = AIAnalysisData(**stats_data["ai_analysis"])

            return ExamAnalyticsResponse(
                overall_competency=stats_data["overall_competency"],
                topic_breakdown=[
                    PerformanceMetric(
                        id=topic["id"],
                        label=topic["label"],
                        score=topic["score"],
                        total=topic["total"],
                        percentage=topic["percentage"],
                        slots=topic["slots"],
                    )
                    for topic in stats_data["topic_breakdown"]
                ],
                ai_analysis=ai_data_obj,
            )
        except Exception as e:
            print(f"Error generating analytics: {e}")
            return ExamAnalyticsResponse(overall_competency=0, topic_breakdown=[])

    @staticmethod
    @router.post("/get_comparative_trend", response_model=ComparativeTrendResponse)
    async def get_comparative_trend_POST(req: StatsRequest) -> ComparativeTrendResponse:
        params_inner = [req.examination_id]
        user_filter = ""
        if req.user_id and req.user_id > 0:
            user_filter = "AND user_id = %s"
            params_inner.append(req.user_id)

        # ---------------------------------------------------------------
        # Inner subquery: for each (user, date), pick the highest
        # attempt_index that falls ON OR BEFORE that date (closest-left).
        # This handles gaps from deleted/skipped attempts gracefully.
        # ---------------------------------------------------------------
        sql = f"""
            SELECT
                res.date_recorded,
                AVG(res.accuracy)                                   AS average_accuracy,
                COUNT(DISTINCT res.user_id)                         AS examinee_count,
                GROUP_CONCAT(res.user_id ORDER BY res.user_id)      AS examinee_ids,
                GROUP_CONCAT(res.attempt_index ORDER BY res.user_id) AS attempt_indices,
                ROW_NUMBER() OVER (ORDER BY res.date_recorded ASC)  AS attempt_number
            FROM (
                -- Per (user, date): pick the MAX attempt_index whose DATE(answered_at)
                -- is <= that date — i.e. "closest left" for any gaps.
                SELECT
                    er.user_id,
                    DATE(er.answered_at)                                        AS date_recorded,
                    MAX(er.attempt_index)                                       AS attempt_index,
                    (COUNT(CASE WHEN er.is_correct = 1 THEN 1 END) * 100.0
                    / COUNT(*))                                                AS accuracy
                FROM examination_results er
                WHERE er.examination_id = %s
                {user_filter}
                AND (er.user_id, er.attempt_index) IN (
                    -- For each user+date, find the highest attempt_index
                    -- that was recorded on or before that date (closest-left).
                    SELECT
                        sub.user_id,
                        MAX(sub.attempt_index)
                    FROM examination_results sub
                    WHERE sub.examination_id = %s
                        {user_filter}
                    GROUP BY sub.user_id, DATE(sub.answered_at)
                )
                GROUP BY er.user_id, er.examination_id, DATE(er.answered_at)
            ) res
            GROUP BY res.date_recorded
            ORDER BY res.date_recorded ASC
        """

        # params: outer WHERE needs exam_id [+ user_id], subquery needs same again
        params = params_inner + params_inner
        trends = db.select(sql, tuple(params))

        for row in trends:
            if row.get("date_recorded"):
                row["date_recorded"] = row["date_recorded"].strftime("%b %d")

            raw_ids = row.get("examinee_ids", "") or ""
            raw_idx = row.get("attempt_indices", "") or ""

            id_list = [int(x) for x in raw_ids.split(",") if x]
            idx_list = [int(x) for x in raw_idx.split(",") if x]

            row["examinee_ids"] = id_list
            row["attempt_indices"] = idx_list

            # Paired map: { user_id: attempt_index } — both lists were
            # ORDER BY user_id in GROUP_CONCAT so they are aligned.
            row["attempt_map"] = {uid: aidx for uid, aidx in zip(id_list, idx_list)}

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

    @staticmethod
    @router.post("/get_item_analysis", response_model=ItemAnalysisResponse)
    async def get_item_analysis_POST(req: ItemAnalysisRequest) -> ItemAnalysisResponse:
        rows = db.select(
            """
            SELECT 
                eia.date, 
                eia.question_id, 
                eia.distribution, 
                eia.analysis, 
                eia.calculated_at,
                q.question_text,
                q.correct_answer
            FROM examination_item_analysis eia
            JOIN questionnaire_items q ON q.id = eia.question_id
            WHERE eia.examination_id = %s
            ORDER BY eia.date ASC, eia.question_id ASC
            """,
            (req.examination_id,),
        )

        # Group by date
        batches: dict[str, dict] = {}
        for row in rows:
            date_key = str(row["date"])
            if date_key not in batches:
                batches[date_key] = {
                    "dateBatch": date_key,
                    "questions": {},
                    "analysis": {},
                    "calculated_at": (
                        str(row["calculated_at"]) if row["calculated_at"] else None
                    ),
                }

            batches[date_key]["questions"][str(row["question_id"])] = {
                **json.loads(row["distribution"]),
                "question_text": row["question_text"],
                "correct_answer": row["correct_answer"],
            }
            if row["analysis"]:
                batches[date_key]["analysis"][str(row["question_id"])] = row["analysis"]

        result = {
            "examination_id": req.examination_id,
            "items": list(batches.values()),
        }

        # print(result)
        return result

    @staticmethod
    @router.post("/get_slot_growth_trend", response_model=GrowthTrendResponse)
    async def get_slot_growth_trend_POST(req: StatsRequest) -> GrowthTrendResponse:
        params = []
        user_filter = ""

        if req.user_id and req.user_id > 0:
            user_filter = " AND er.user_id = %s"
            params.append(req.user_id)

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

    @router.post("/get_attempt_basic_comparison", response_model=BasicAttemptResponse)
    async def get_attempt_basic_comparison_POST(
        req: ForensicAttemptRequest,
    ) -> BasicAttemptResponse:
        target_user_id = None if req.user_id == -1 else req.user_id

        if target_user_id:
            # PATH 1: Single user, specific attempt index resolved by caller
            sql = """
                WITH CurrentAttempt AS (
                    SELECT * FROM examination_results
                    WHERE examination_id = %s AND user_id = %s AND attempt_index = %s
                ),
                PrevAttempt AS (
                    SELECT * FROM examination_results
                    WHERE examination_id = %s AND user_id = %s
                    AND attempt_index = (
                        SELECT MAX(attempt_index) FROM examination_results
                        WHERE examination_id = %s AND user_id = %s AND attempt_index < %s
                    )
                )
                SELECT
                    qi.id as question_id,
                    ANY_VALUE(qi.question_text) as question_text,
                    ANY_VALUE(qi.choices) as choices,
                    ANY_VALUE(qi.correct_answer) as correct_answer,
                    ANY_VALUE(c.id) as category_id,
                    ANY_VALUE(c.name) as category_name,
                    ANY_VALUE(sr.slot_name) as slot_name,
                    ANY_VALUE(cur.student_answer) as student_answer,
                    ANY_VALUE(cur.is_correct) as is_correct,
                    ANY_VALUE(prev.student_answer) as prev_ans,
                    ANY_VALUE(prev.is_correct) as prev_cor
                FROM CurrentAttempt cur
                JOIN questionnaire_items qi ON cur.question_id = qi.id
                JOIN source_references sr ON qi.questionnaire_id = sr.id
                JOIN category c ON sr.category_id = c.id
                JOIN examination_questions eq ON eq.questionnaire_item_id = qi.id
                    AND eq.examination_id = %s
                LEFT JOIN PrevAttempt prev ON prev.question_id = cur.question_id
                GROUP BY qi.id, eq.id
                ORDER BY eq.id ASC
            """
            params = [
                req.examination_id,
                target_user_id,
                req.attempt_index,  # CurrentAttempt
                req.examination_id,
                target_user_id,  # PrevAttempt WHERE
                req.examination_id,
                target_user_id,
                req.attempt_index,  # PrevAttempt subquery
                req.examination_id,  # eq JOIN
            ]
        else:
            # PATH 3: Full batch — no specific user, aggregate max attempt per user
            sql = """
                WITH CurrentAttempt AS (
                    SELECT examination_results.*
                    FROM examination_results
                    JOIN (
                        SELECT user_id, MAX(attempt_index) as max_idx
                        FROM examination_results
                        WHERE examination_id = %s
                        GROUP BY user_id
                    ) latest ON examination_results.user_id = latest.user_id
                        AND examination_results.attempt_index = latest.max_idx
                    WHERE examination_results.examination_id = %s
                ),
                PrevAttempt AS (
                    SELECT examination_results.*
                    FROM examination_results
                    JOIN (
                        SELECT er.user_id, MAX(er.attempt_index) as prev_idx
                        FROM examination_results er
                        JOIN (
                            SELECT user_id, MAX(attempt_index) as max_idx
                            FROM examination_results
                            WHERE examination_id = %s
                            GROUP BY user_id
                        ) latest ON er.user_id = latest.user_id
                            AND er.attempt_index < latest.max_idx
                        WHERE er.examination_id = %s
                        GROUP BY er.user_id
                    ) prev_latest ON examination_results.user_id = prev_latest.user_id
                        AND examination_results.attempt_index = prev_latest.prev_idx
                    WHERE examination_results.examination_id = %s
                )
                SELECT
                    qi.id as question_id,
                    ANY_VALUE(qi.question_text) as question_text,
                    ANY_VALUE(qi.choices) as choices,
                    ANY_VALUE(qi.correct_answer) as correct_answer,
                    ANY_VALUE(c.id) as category_id,
                    ANY_VALUE(c.name) as category_name,
                    ANY_VALUE(sr.slot_name) as slot_name,
                    ANY_VALUE(cur.student_answer) as student_answer,
                    ANY_VALUE(cur.is_correct) as is_correct,
                    ANY_VALUE(prev.student_answer) as prev_ans,
                    ANY_VALUE(prev.is_correct) as prev_cor
                FROM CurrentAttempt cur
                JOIN questionnaire_items qi ON cur.question_id = qi.id
                JOIN source_references sr ON qi.questionnaire_id = sr.id
                JOIN category c ON sr.category_id = c.id
                JOIN examination_questions eq ON eq.questionnaire_item_id = qi.id
                    AND eq.examination_id = %s
                LEFT JOIN PrevAttempt prev ON prev.question_id = cur.question_id
                    AND prev.user_id = cur.user_id
                GROUP BY qi.id, eq.id
                ORDER BY eq.id ASC
            """
            params = [
                req.examination_id,  # CurrentAttempt inner subquery
                req.examination_id,  # CurrentAttempt WHERE
                req.examination_id,  # PrevAttempt inner-inner subquery
                req.examination_id,  # PrevAttempt inner WHERE
                req.examination_id,  # PrevAttempt outer WHERE
                req.examination_id,  # eq JOIN
            ]

        rows = db.select(sql, tuple(params))
        basic_items = []
        for r in rows:
            choices = (
                json.loads(r["choices"])
                if isinstance(r["choices"], str)
                else r["choices"]
            )
            s_key = str(r["student_answer"]).strip().upper()
            c_key = str(r["correct_answer"]).strip().upper()
            norm_choices = {str(k).upper(): v for k, v in choices.items()}
            p_val = r.get("prev_ans")
            has_prev = p_val is not None
            p_key = str(p_val).strip().upper() if has_prev else ""
            basic_items.append(
                BasicAttemptLogItem(
                    category_id=r["category_id"],
                    category_name=r["category_name"],
                    slot_name=r["slot_name"],
                    question_text=r["question_text"],
                    correct_answer=f"({c_key}) {norm_choices.get(c_key, 'N/A')}",
                    student_answer=f"({s_key}) {norm_choices.get(s_key, 'N/A')}",
                    is_correct=bool(r["is_correct"]),
                    previous_student_answer=(
                        f"({p_key}) {norm_choices.get(p_key, 'N/A')}"
                        if has_prev
                        else ""
                    ),
                    previous_is_correct=bool(r.get("prev_cor")) if has_prev else False,
                )
            )
        return BasicAttemptResponse(success=True, items=basic_items)

    @router.post("/get_attempt_forensics", response_model=ForensicAttemptResponse)
    async def get_attempt_forensics_POST(
        req: ForensicAttemptRequest,
    ) -> ForensicAttemptResponse:
        target_user_id = None if req.user_id == -1 else req.user_id

        if target_user_id:
            # PATH 1: Single user, specific attempt index resolved by caller
            sql = """
                WITH CurrentAttempt AS (
                    SELECT * FROM examination_results
                    WHERE examination_id = %s AND user_id = %s AND attempt_index = %s
                ),
                PrevAttempt AS (
                    SELECT * FROM examination_results
                    WHERE examination_id = %s AND user_id = %s
                    AND attempt_index = (
                        SELECT MAX(attempt_index) FROM examination_results
                        WHERE examination_id = %s AND user_id = %s AND attempt_index < %s
                    )
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
                    ANY_VALUE(cur.student_answer) as student_answer,
                    ANY_VALUE(cur.is_correct) as is_correct,
                    ANY_VALUE(prev.student_answer) as prev_ans,
                    ANY_VALUE(prev.is_correct) as prev_cor
                FROM CurrentAttempt cur
                JOIN questionnaire_items qi ON cur.question_id = qi.id
                JOIN source_references sr ON qi.questionnaire_id = sr.id
                JOIN category c ON sr.category_id = c.id
                LEFT JOIN item_analysis ia ON qi.id = ia.item_id
                JOIN examination_questions eq ON eq.questionnaire_item_id = qi.id
                    AND eq.examination_id = %s
                LEFT JOIN PrevAttempt prev ON prev.question_id = cur.question_id
                GROUP BY qi.id, eq.id
                ORDER BY eq.id ASC
            """
            params = [
                req.examination_id,
                target_user_id,
                req.attempt_index,  # CurrentAttempt
                req.examination_id,
                target_user_id,  # PrevAttempt WHERE
                req.examination_id,
                target_user_id,
                req.attempt_index,  # PrevAttempt subquery
                req.examination_id,  # eq JOIN
            ]
        else:
            # PATH 2: Full batch — aggregate max attempt per user
            sql = """
                WITH CurrentAttempt AS (
                    SELECT examination_results.*
                    FROM examination_results
                    JOIN (
                        SELECT user_id, MAX(attempt_index) as max_idx
                        FROM examination_results
                        WHERE examination_id = %s
                        GROUP BY user_id
                    ) latest ON examination_results.user_id = latest.user_id
                        AND examination_results.attempt_index = latest.max_idx
                    WHERE examination_results.examination_id = %s
                ),
                PrevAttempt AS (
                    SELECT examination_results.*
                    FROM examination_results
                    JOIN (
                        SELECT er.user_id, MAX(er.attempt_index) as prev_idx
                        FROM examination_results er
                        JOIN (
                            SELECT user_id, MAX(attempt_index) as max_idx
                            FROM examination_results
                            WHERE examination_id = %s
                            GROUP BY user_id
                        ) latest ON er.user_id = latest.user_id
                            AND er.attempt_index < latest.max_idx
                        WHERE er.examination_id = %s
                        GROUP BY er.user_id
                    ) prev_latest ON examination_results.user_id = prev_latest.user_id
                        AND examination_results.attempt_index = prev_latest.prev_idx
                    WHERE examination_results.examination_id = %s
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
                    ANY_VALUE(cur.student_answer) as student_answer,
                    ANY_VALUE(cur.is_correct) as is_correct,
                    ANY_VALUE(prev.student_answer) as prev_ans,
                    ANY_VALUE(prev.is_correct) as prev_cor
                FROM CurrentAttempt cur
                JOIN questionnaire_items qi ON cur.question_id = qi.id
                JOIN source_references sr ON qi.questionnaire_id = sr.id
                JOIN category c ON sr.category_id = c.id
                LEFT JOIN item_analysis ia ON qi.id = ia.item_id
                JOIN examination_questions eq ON eq.questionnaire_item_id = qi.id
                    AND eq.examination_id = %s
                LEFT JOIN PrevAttempt prev ON prev.question_id = cur.question_id
                    AND prev.user_id = cur.user_id
                GROUP BY qi.id, eq.id
                ORDER BY eq.id ASC
            """
            params = [
                req.examination_id,  # CurrentAttempt inner subquery
                req.examination_id,  # CurrentAttempt WHERE
                req.examination_id,  # PrevAttempt inner-inner subquery
                req.examination_id,  # PrevAttempt inner WHERE
                req.examination_id,  # PrevAttempt outer WHERE
                req.examination_id,  # eq JOIN
            ]

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

            def get_ana(key, _ad=analysis_dict):
                return _ad.get(
                    key, f"Technical analysis for Option {key} is unavailable."
                )

            p_val = r.get("prev_ans")
            has_prev = p_val is not None
            p_key = str(p_val).strip().upper() if has_prev else ""
            comparative_items.append(
                ForensicLogItem(
                    category_id=r["category_id"],
                    category_name=r["category_name"],
                    slot_name=r["slot_name"],
                    question_text=r["question_text"],
                    correct_answer=f"({c_key}) {norm_choices.get(c_key, 'N/A')}",
                    student_answer=f"({s_key}) {norm_choices.get(s_key, 'N/A')}",
                    is_correct=bool(r["is_correct"]),
                    previous_student_answer=(
                        f"({p_key}) {norm_choices.get(p_key, 'N/A')}"
                        if has_prev
                        else ""
                    ),
                    previous_is_correct=bool(r.get("prev_cor")) if has_prev else False,
                    option_a_analysis=get_ana("A"),
                    option_b_analysis=get_ana("B"),
                    option_c_analysis=get_ana("C"),
                    option_d_analysis=get_ana("D"),
                )
            )
        return ForensicAttemptResponse(
            success=True, comparative_items=comparative_items
        )
