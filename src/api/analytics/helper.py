import json
from utils.db import db


def get_calculated_exam_stats(examination_id: int, user_id: int = None) -> dict:
    meta_sql = """
        SELECT 
            (SELECT total_items FROM examinations WHERE id = %s) as total_items,
            (SELECT COUNT(DISTINCT user_id) FROM examination_results WHERE examination_id = %s) as user_count
    """
    meta = db.select(meta_sql, (examination_id, examination_id))[0]

    official_total_items = float(meta["total_items"] or 0)
    user_count = float(meta["user_count"] if not user_id else 1)
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
    params = [examination_id, examination_id]
    if user_id:
        sql += " AND er.user_id = %s"
        params.append(user_id)

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
            {
                "slot_name": r["slot_name"],
                "score": round(avg_score, 1),
                "total": slot_total,
                "percentage": s_perc,
            }
        )

        topic_map[tid]["score"] += avg_score
        topic_map[tid]["total"] += slot_total

    # 3. Final Overall Competency
    if official_total_items > 0:
        overall_comp = (running_avg_numerator / official_total_items) * 100
    else:
        overall_comp = 0

    ai_analysis_dict = None

    try:
        if user_id:
            # Fetch individual student's latest attempt analysis
            analysis_sql = """
                SELECT analysis FROM examination_attempt_analysis 
                WHERE examination_id = %s AND user_id = %s 
                ORDER BY attempt_index DESC LIMIT 1
            """
            row = db.select(analysis_sql, (examination_id, user_id))
            if row and row[0]["analysis"]:
                raw_json = row[0]["analysis"]
                ai_analysis_dict = (
                    json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                )
        else:
            # Fetch overall batch analysis
            analysis_sql = "SELECT analysis FROM examinations WHERE id = %s"
            row = db.select(analysis_sql, (examination_id,))
            if row and row[0]["analysis"]:
                raw_json = row[0]["analysis"]
                ai_analysis_dict = (
                    json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                )
    except Exception as e:
        print(f"Failed to load AI analysis string: {e}")

    return {
        "overall_competency": round(overall_comp, 2),
        "topic_breakdown": [
            {
                "id": tid,  # Needed for the UI
                "label": data["name"],
                "score": round(data["score"], 1),
                "total": data["total"],
                "percentage": (
                    round((data["score"] / data["total"]) * 100, 2)
                    if data["total"] > 0
                    else 0
                ),
                "slots": data["slots"],  # Keep the slot metrics for the UI details
            }
            for tid, data in topic_map.items()
        ],
        "ai_analysis": ai_analysis_dict,
    }
