from utils.db import db


def select_sections(focus, difficulty, material):

    if focus == "Weak Areas":
        weak_sections = db.select(
            """
            SELECT q.section_id
            FROM Questions q
            JOIN ExaminationResults r ON q.id = r.question_id
            WHERE q.material_id=%s
            GROUP BY q.section_id
            ORDER BY SUM(CASE WHEN r.is_correct=false THEN 1 ELSE 0 END) DESC
            LIMIT 3
        """,
            (material.material_id,),
        )

        ids = [w["section_id"] for w in weak_sections]

        if not ids:
            query = """
                SELECT id, section_name, content
                FROM SectionVector
                WHERE material_id=%s
            """
            params = (material.material_id,)
        else:
            placeholders = ",".join(["%s"] * len(ids))
            query = f"""
                SELECT id, section_name, content
                FROM SectionVector
                WHERE material_id=%s
                AND id IN ({placeholders})
            """
            params = tuple([material.material_id] + ids)

    else:
        query = """
            SELECT id, section_name, content
            FROM SectionVector
            WHERE material_id=%s
        """
        params = (material.material_id,)

    return db.select(query, params)
