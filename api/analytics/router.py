import json

from api.analytics.models import (
    PersonnelAnalyticsResponse,
    PerformanceMetric,
    QuestionForensic,
    StatsRequest,
    ExamAnalyticsResponse,
    PersonnelStat,
)
from utils.db import db

from fastapi import APIRouter, HTTPException, Depends
from typing import List

router = APIRouter(prefix="/analytics", tags=["analytics"])


def calc_avg(metrics: List[PerformanceMetric]) -> float:
    if not metrics:
        return 0.0
    return sum(m.percentage for m in metrics) / len(metrics)


class AnalyticsController:

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
            uid = r["user_id"]
            mid = r["material_id"]

            if not req.user_id:
                if uid not in user_groups:
                    user_groups[uid] = {
                        "label": r["username"],
                        "s": 0,
                        "t": 0,
                        "id": uid,
                        "subjects": {},  # Tracking subjects for the "Critical Fail" filter
                    }

                user_groups[uid]["t"] += 1
                if r["is_correct"]:
                    user_groups[uid]["s"] += 1

                # Track material breakdown per user internally
                if mid not in user_groups[uid]["subjects"]:
                    user_groups[uid]["subjects"][mid] = {"s": 0, "t": 0}
                user_groups[uid]["subjects"][mid]["t"] += 1
                if r["is_correct"]:
                    user_groups[uid]["subjects"][mid]["s"] += 1
            else:
                if mid not in m_map:
                    m_map[mid] = {"label": r["m_name"], "s": 0, "t": 0}
                m_map[mid]["t"] += 1
                if r["is_correct"]:
                    m_map[mid]["s"] += 1

        final_list = []
        if not req.user_id:
            for v in user_groups.values():
                # Generate the material breakdown list for THIS specific user
                m_breakdown = [
                    PerformanceMetric(
                        id=m_id,
                        label="",
                        score=m_data["s"],
                        total=m_data["t"],
                        percentage=(m_data["s"] / m_data["t"] * 100),
                    )
                    for m_id, m_data in v["subjects"].items()
                ]

                final_list.append(
                    PerformanceMetric(
                        id=v["id"],
                        label=v["label"],
                        score=v["s"],
                        total=v["t"],
                        percentage=(v["s"] / v["t"] * 100),
                        material_breakdown=m_breakdown,  # This is what your VB.NET filter needs!
                    )
                )
        else:
            final_list = [
                PerformanceMetric(
                    id=mid,
                    label=v["label"],
                    score=v["s"],
                    total=v["t"],
                    percentage=(v["s"] / v["t"] * 100),
                )
                for mid, v in m_map.items()
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

        # --- 3. NEW: Question Logs Logic (The Forensic Micro-Data) ---
        # Only populate logs if we are looking at a specific user's detail
        logs = []
        if req.user_id:
            for r in rows:
                # Perform the forensic lookup for full text
                full_student_ans = get_full_choice_text(
                    r["student_answer"], r["choices"]
                )
                full_correct_ans = get_full_choice_text(
                    r["correct_answer"], r["choices"]
                )

                logs.append(
                    QuestionForensic(
                        question_text=r["question_text"],
                        student_answer=full_student_ans,
                        correct_answer=full_correct_ans,
                        is_correct=bool(r["is_correct"]),
                        material_id=r["material_id"],
                    )
                )

        # --- 4. Sorting & Final Response ---
        final_list.sort(key=lambda x: x.percentage)
        diff_order = {"Easy": 0, "Medium": 1, "Hard": 2}
        diff_list.sort(key=lambda x: diff_order.get(x.label, 99))

        total_correct = sum(1 for r in rows if r["is_correct"])
        overall_comp = (total_correct / len(rows) * 100) if rows else 0.0

        return ExamAnalyticsResponse(
            overall_competency=overall_comp,
            material_breakdown=final_list,
            difficulty_breakdown=diff_list,
            question_logs=logs,  # Integrated
        )

    @router.post("/get_personnel_stats", response_model=PersonnelAnalyticsResponse)
    async def get_personnel_stats_POST(req: StatsRequest) -> PersonnelAnalyticsResponse:
        # 1. Fetch all Reviewees
        users = db.select("SELECT id, username FROM Users WHERE role = 'Reviewee'")
        if not users:
            return PersonnelAnalyticsResponse(
                avg_proficiency=0,
                total_active=0,
                critical_weakness="STABLE",
                dossiers=[],
            )

        # 2. Base Query (Global - no material_id filter needed)
        sql = """
            SELECT 
                er.user_id, er.is_correct, 
                q.material_id, m.title_content as m_name,
                q.section_id, s.section_name as s_name
            FROM examination_results er
            JOIN questions q ON er.question_id = q.id
            JOIN materials m ON q.material_id = m.id
            LEFT JOIN sections s ON q.section_id = s.id
            JOIN examinations e ON q.examination_id = e.id
            WHERE 1=1
        """
        params = []

        if req.user_id:
            sql += " AND er.user_id = %s"
            params.append(req.user_id)

        # Keep Focus and Difficulty filters as they define the 'context' of the SWOT
        if req.focus:
            sql += " AND e.focus = %s"
            params.append(req.focus)
        if req.difficulty:
            sql += " AND e.difficulty = %s"
            params.append(req.difficulty)

        all_rows = db.select(sql, tuple(params))

        # 3. Process Dossiers
        dossiers = []
        global_material_fail_count = {}

        for user in users:
            u_id = user["id"]
            u_rows = [r for r in all_rows if r["user_id"] == u_id]

            m_map = {}
            s_map = {}

            for r in u_rows:
                # Aggregate Material Stats
                m_id, m_name = r["material_id"], r["m_name"]
                if m_id not in m_map:
                    m_map[m_id] = {"label": m_name, "s": 0, "t": 0}
                m_map[m_id]["t"] += 1
                if r["is_correct"]:
                    m_map[m_id]["s"] += 1

                # Aggregate Section Stats
                s_id, s_name = r["section_id"], r["s_name"] or "Uncategorized"
                if s_id not in s_map:
                    s_map[s_id] = {"label": s_name, "s": 0, "t": 0}
                s_map[s_id]["t"] += 1
                if r["is_correct"]:
                    s_map[s_id]["s"] += 1

            def to_metrics(data_map):
                metrics = [
                    PerformanceMetric(
                        id=k,
                        label=v["label"],
                        score=v["s"],
                        total=v["t"],
                        percentage=(v["s"] / v["t"] * 100) if v["t"] > 0 else 0,
                    )
                    for k, v in data_map.items()
                ]
                return sorted(metrics, key=lambda x: x.percentage)

            m_metrics = to_metrics(m_map)

            # Tracking Critical Weakness for the System-Wide KPI
            if m_metrics:
                weakest = m_metrics[0].label  # First because it's sorted ascending
                global_material_fail_count[weakest] = (
                    global_material_fail_count.get(weakest, 0) + 1
                )

            user_avg = (
                sum(m.percentage for m in m_metrics) / len(m_metrics)
                if m_metrics
                else 0.0
            )

            dossiers.append(
                PersonnelStat(
                    user_id=u_id,
                    username=user["username"],
                    overall_competency=user_avg,
                    material_breakdown=m_metrics,
                    section_breakdown=to_metrics(s_map),
                )
            )

        # 4. Sorting & Tactical Limit
        # Default sort by overall competency descending (Best first)
        dossiers.sort(key=lambda x: x.overall_competency, reverse=True)

        if req.limit and req.limit != -1:
            dossiers = dossiers[: req.limit]

        # 5. Final Aggregates
        total_active = len(dossiers)
        global_avg = (
            sum(d.overall_competency for d in dossiers) / total_active
            if total_active > 0
            else 0.0
        )
        crit_weakness = (
            max(global_material_fail_count, key=global_material_fail_count.get)
            if global_material_fail_count
            else "STABLE"
        )

        return PersonnelAnalyticsResponse(
            avg_proficiency=global_avg,
            total_active=total_active,
            critical_weakness=crit_weakness,
            dossiers=dossiers,
        )
