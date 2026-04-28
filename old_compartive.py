@staticmethod
@router.post("/get_slot_growth_trend", response_model=GrowthTrendResponse)
async def get_slot_growth_trend_POST(req: StatsRequest) -> GrowthTrendResponse:
    params = []
    user_filter = ""

    if req.user_id and req.user_id > 0:
        user_filter = " AND er.user_id = %s"
        params.append(req.user_id)

    # We join results -> questions -> source_references (Slot)
    sql = f"""
        SELECT 
            DATE(er.answered_at) as date_recorded,
            sr.slot_name as slot_name,
            (SUM(er.is_correct) * 100.0 / COUNT(er.id)) as accuracy,
            COUNT(DISTINCT er.user_id) as examinee_count
        FROM examination_results er
        JOIN questionnaire_items qi ON er.question_id = qi.id
        JOIN source_references sr ON qi.questionnaire_id = sr.id
        WHERE 1=1 {user_filter}
        GROUP BY DATE(er.answered_at), sr.id, sr.slot_name
        ORDER BY DATE(er.answered_at) ASC, sr.slot_name ASC
    """

    rows = db.select(sql, tuple(params))

    unique_slots = sorted(list(set(r["slot_name"] for r in rows)))

    formatted_history = []
    for r in rows:
        formatted_history.append(
            {
                "date_recorded": r["date_recorded"].strftime("%b %d"),
                "slot_name": r["slot_name"],
                "accuracy": float(r["accuracy"]),
                "examinee_count": int(r["examinee_count"]),
            }
        )

    result = {
        "trend_label": (
            "Topic Mastery Growth" if req.user_id else "Global Slot Performance"
        ),
        "unique_slots": unique_slots,
        "history": formatted_history,
    }

    return result
