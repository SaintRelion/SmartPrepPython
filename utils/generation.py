from models import GenerateExamRequest
from utils.db import db


def select_sections(req: GenerateExamRequest):

    if req.focus == "Specific Topic" and req.section_names:
        placeholders = ",".join(["%s"] * len(req.section_names))
        query = f"""
            SELECT id, section_name, content
            FROM SectionVector
            WHERE document_id=%s
            AND section_name IN ({placeholders})
        """
        params = tuple([req.document_id] + req.section_names)

    elif req.focus == "Weak Areas":
        weak_sections = db.select(
            """
            SELECT q.section_id
            FROM Questions q
            JOIN ExaminationResults r ON q.id = r.question_id
            WHERE q.document_id=%s
            GROUP BY q.section_id
            ORDER BY SUM(CASE WHEN r.is_correct=false THEN 1 ELSE 0 END) DESC
            LIMIT 3
        """,
            (req.document_id,),
        )

        ids = [w["section_id"] for w in weak_sections]

        if not ids:
            query = """
                SELECT id, section_name, content
                FROM SectionVector
                WHERE document_id=%s
            """
            params = (req.document_id,)
        else:
            placeholders = ",".join(["%s"] * len(ids))
            query = f"""
                SELECT id, section_name, content
                FROM SectionVector
                WHERE document_id=%s
                AND id IN ({placeholders})
            """
            params = tuple([req.document_id] + ids)

    else:
        query = """
            SELECT id, section_name, content
            FROM SectionVector
            WHERE document_id=%s
        """
        params = (req.document_id,)

    return db.select(query, params)
