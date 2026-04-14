import json

from api.analytics.models import (
    GlobalExcellenceResponse,
    LeaderEntry,
    PerformanceMetric,
    QuestionForensic,
    StatsRequest,
    ExamAnalyticsResponse,
    SubjectLeaderboard,
)
from utils.db import db

from fastapi import APIRouter

router = APIRouter(prefix="/analytics", tags=["analytics"])


class AnalyticsController:

    @staticmethod
    @router.get("/get_global_excellence", response_model=GlobalExcellenceResponse)
    async def get_global_excellence_GET() -> GlobalExcellenceResponse:
        sql = """
            WITH UserMaterialStats AS (
                SELECT 
                    u.id as user_id, u.username,
                    m.id as material_id, m.title_content as material_name,
                    COUNT(er.id) as total_items,
                    SUM(er.is_correct) as correct_items,
                    (SUM(er.is_correct) / COUNT(er.id) * 100) as percentage
                FROM examination_results er
                JOIN questions q ON er.question_id = q.id
                JOIN materials m ON q.material_id = m.id
                JOIN users u ON er.user_id = u.id
                WHERE er.attempt_index = (
                    SELECT MAX(attempt_index) FROM examination_results 
                    WHERE examination_id = er.examination_id AND user_id = er.user_id
                )
                GROUP BY u.id, u.username, m.id, m.title_content
                HAVING COUNT(er.id) > 0
            ),
            RankedStats AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY material_id 
                        ORDER BY percentage DESC, total_items DESC
                    ) as `ranking_position`
                FROM UserMaterialStats
            )
            SELECT * FROM RankedStats 
            WHERE `ranking_position` <= 5  -- FETCH TOP 5
            ORDER BY material_name ASC, `ranking_position` ASC
        """

        rows = db.select(sql)

        # Group results by material
        grouped_data = {}
        for r in rows:
            m_name = r["material_name"]
            if m_name not in grouped_data:
                grouped_data[m_name] = []

            grouped_data[m_name].append(
                LeaderEntry(
                    rank=r["ranking_position"],
                    student_name=r["username"],
                    percentage=round(r["percentage"], 2),
                    total_items=r["total_items"],
                )
            )

        leaderboards = [
            SubjectLeaderboard(material_name=name, top_performers=leaders)
            for name, leaders in grouped_data.items()
        ]

        return GlobalExcellenceResponse(success=True, subject_leaderboards=leaderboards)

    @staticmethod
    @router.post("/get_exam_stats", response_model=ExamAnalyticsResponse)
    async def get_exam_stats_POST(req: StatsRequest) -> ExamAnalyticsResponse:
        params = [req.examination_id]

        user_filter = ""
        if req.user_id:
            user_filter = " AND user_id = %s"
            params.append(req.user_id)

        # Base SQL
        sql = f"""
            SELECT 
                er.user_id, u.username, er.is_correct, er.student_answer,
                q.id as q_id, q.question_text, q.correct_answer, q.choices, q.material_id, 
                m.title_content as m_name, e.difficulty
            FROM examination_results er
            JOIN questions q ON er.question_id = q.id
            JOIN materials m ON q.material_id = m.id
            JOIN users u ON er.user_id = u.id
            JOIN examinations e ON er.examination_id = e.id
            WHERE er.examination_id = %s {user_filter}
            AND er.attempt_index = (
                SELECT MAX(attempt_index) 
                FROM examination_results 
                WHERE examination_id = er.examination_id AND user_id = er.user_id
            )
        """

        rows = db.select(sql, tuple(params))

        # Helper function to get full text: "A" -> "A. The Choice Text"
        def get_full_choice_text(letter, choices_raw):
            if not letter or not choices_raw:
                return letter
            try:
                # Parse JSON if it's a string, otherwise use as dict
                choices = (
                    json.loads(choices_raw)
                    if isinstance(choices_raw, str)
                    else choices_raw
                )
                choice_text = choices.get(letter, "")
                return f"{letter}. {choice_text}" if choice_text else letter
            except:
                return letter

        # --- 1. Material/Reviewee Logic ---
        m_map = {}
        user_groups = {}
        for r in rows:
            u_id = r["user_id"]
            m_id = r["material_id"]

            if not req.user_id:
                # AGGREGATE MODE: Group by User
                if u_id not in user_groups:
                    user_groups[u_id] = {
                        "label": r["username"],
                        "s": 0,
                        "t": 0,
                        "id": u_id,
                        "subjects": {},  # Tracking subjects for the "Critical Fail" filter
                    }

                user_groups[u_id]["t"] += 1
                if r["is_correct"]:
                    user_groups[u_id]["s"] += 1

                # Track material breakdown per user internally
                if m_id not in user_groups[u_id]["subjects"]:
                    # FIX: Store the label (m_name) here so m_val["label"] works later!
                    user_groups[u_id]["subjects"][m_id] = {
                        "label": r["m_name"],
                        "s": 0,
                        "t": 0,
                    }

                user_groups[u_id]["subjects"][m_id]["t"] += 1
                if r["is_correct"]:
                    user_groups[u_id]["subjects"][m_id]["s"] += 1
            else:
                # INDIVIDUAL MODE: Group by Material
                if m_id not in m_map:
                    m_map[m_id] = {"label": r["m_name"], "s": 0, "t": 0}

                m_map[m_id]["t"] += 1
                if r["is_correct"]:
                    m_map[m_id]["s"] += 1

        # --- Build the Recursive PerformanceMetric List ---
        final_metrics = []
        if not req.user_id:
            for u_id, v in user_groups.items():
                # Now 'v' is the dictionary, so v["subjects"] will work!
                u_m_breakdown = [
                    PerformanceMetric(
                        id=m_id,
                        label=m_val["label"],
                        score=m_val["s"],
                        total=m_val["t"],
                        percentage=(m_val["s"] / m_val["t"] * 100),
                    )
                    for m_id, m_val in v["subjects"].items()
                ]

                final_metrics.append(
                    PerformanceMetric(
                        id=u_id,
                        label=v["label"],  # username
                        score=v["s"],
                        total=v["t"],
                        percentage=(v["s"] / v["t"] * 100),
                        material_breakdown=u_m_breakdown,
                    )
                )
        else:
            final_metrics = [
                PerformanceMetric(
                    id=m_id,
                    label=v["label"],
                    score=v["s"],
                    total=v["t"],
                    percentage=(v["s"] / v["t"] * 100),
                )
                for m_id, v in m_map.items()
            ]

        # --- 2. Difficulty Breakdown Logic ---
        d_map = {}
        for r in rows:
            diff = r["difficulty"]
            if diff not in d_map:
                d_map[diff] = {"label": diff, "s": 0, "t": 0}
            d_map[diff]["t"] += 1
            if r["is_correct"]:
                d_map[diff]["s"] += 1

        diff_list = [
            PerformanceMetric(
                id=0,
                label=k,
                score=v["s"],
                total=v["t"],
                percentage=(v["s"] / v["t"] * 100),
            )
            for k, v in d_map.items()
        ]

        # --- Question Logs Logic ---
        # Only populate logs if we are looking at a specific user's detail
        question_logs = []
        if req.user_id:
            for r in rows:
                # Perform the forensic lookup for full text
                full_student_ans = get_full_choice_text(
                    r["student_answer"], r["choices"]
                )
                full_correct_ans = get_full_choice_text(
                    r["correct_answer"], r["choices"]
                )

                question_logs.append(
                    QuestionForensic(
                        question_text=r["question_text"],
                        student_answer=full_student_ans,
                        correct_answer=full_correct_ans,
                        is_correct=bool(r["is_correct"]),
                        material_id=r["material_id"],
                    )
                )

        # --- 4. Sorting & Final Response ---
        final_metrics.sort(key=lambda x: x.percentage)
        diff_order = {"Easy": 0, "Medium": 1, "Hard": 2}
        diff_list.sort(key=lambda x: diff_order.get(x.label, 99))

        total_correct = sum(1 for r in rows if r["is_correct"])
        overall_comp = (total_correct / len(rows) * 100) if rows else 0.0

        return ExamAnalyticsResponse(
            overall_competency=overall_comp,
            material_breakdown=final_metrics,
            difficulty_breakdown=diff_list,
            question_logs=question_logs,
        )
