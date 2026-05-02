from collections import defaultdict
import json
import random

from fastapi import APIRouter, HTTPException, Depends
from typing import List
from datetime import datetime

from utils.db import db
from .models import (
    DailyExamListGroup,
    ExamDeleteRequest,
    ExamDeleteResponse,
    ExamListOut,
    ExamOut,
    ExamRenameRequest,
    ExamRenameResponse,
    QuestionOut,
    RevieweeStatusIn,
    RevieweeStatusOut,
    SubmissionSummary,
    ExamListRequest,
    ExamGetRequest,
    SubmitAnswerRequest,
    ExamGenerationRequest,
    ExamGenerationResponse,
)

router = APIRouter(prefix="/exam", tags=["Exam"])


class ExamController:
    @staticmethod
    @router.post("/generate_exam", response_model=ExamGenerationResponse)
    async def generate_exam_POST(req: ExamGenerationRequest) -> ExamGenerationResponse:
        prefix = "r" if req.is_randomized else ""
        formatted_config = {
            str(k): f"{prefix}{v}" for k, v in req.questionnaires.items()
        }

        exam_id = db.insert(
            """INSERT INTO examinations 
            (exam_name, questionnaire_config, total_items) 
            VALUES (%s, %s, %s)""",
            (req.exam_name, json.dumps(formatted_config), req.total_items),
        )

        all_allocated_ids = []

        for q_id, count in req.questionnaires.items():
            # Fetch IDs for this specific questionnaire
            rows = db.select(
                "SELECT id FROM questionnaire_items WHERE questionnaire_id = %s ORDER BY id ASC",
                (q_id,),
            )
            item_ids = [r["id"] for r in rows]

            if req.is_randomized:
                # Pick 'count' number of random items
                selected = random.sample(item_ids, min(len(item_ids), count))
            else:
                # Pick first 'count' items sequentially
                selected = item_ids[:count]

            all_allocated_ids.extend([(exam_id, i_id) for i_id in selected])

        # 3. Bulk Insert into examination_questions
        if all_allocated_ids:
            db.execute_many(
                "INSERT INTO examination_questions (examination_id, questionnaire_item_id) VALUES (%s, %s)",
                all_allocated_ids,
            )

        return ExamGenerationResponse(
            status="success",
            message="Exam items allocated successfully.",
            examination_id=exam_id,
        )

    @staticmethod
    @router.post("/rename_exam", response_model=ExamRenameResponse)
    async def rename_exam_POST(req: ExamRenameRequest) -> ExamRenameResponse:
        exists = db.select("SELECT id FROM examinations WHERE id=%s", (req.exam_id,))
        if not exists:
            raise HTTPException(status_code=404, detail="Exam not found")

        sql = "UPDATE examinations SET exam_name = %s WHERE id = %s"
        affected_rows = db.execute(sql, (req.new_name, req.exam_id))

        if affected_rows == 0:
            return ExamRenameResponse(success=False, message="No changes applied")

        return ExamRenameResponse(
            success=True, message="Exam renamed successfully", updated_name=req.new_name
        )

    @staticmethod
    @router.post("/delete_exam", response_model=ExamDeleteResponse)
    async def delete_exam_POST(req: ExamDeleteRequest) -> ExamDeleteResponse:
        exists = db.select("SELECT id FROM examinations WHERE id=%s", (req.exam_id,))
        if not exists:
            raise HTTPException(status_code=404, detail="Exam not found")

        try:
            # Delete associated questions first
            db.execute(
                "DELETE FROM examination_questions WHERE examination_id = %s",
                (req.exam_id,),
            )
            # Delete attempt trackers
            db.execute(
                "DELETE FROM examination_attempts WHERE examination_id = %s",
                (req.exam_id,),
            )
            # Delete results
            db.execute(
                "DELETE FROM examination_results WHERE examination_id = %s",
                (req.exam_id,),
            )
            # Finally, delete the master record
            db.execute("DELETE FROM examinations WHERE id = %s", (req.exam_id,))

            return ExamDeleteResponse(
                success=True, message="Exam and associated data deleted"
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

    @staticmethod
    @router.get("/list_exams", response_model=List[DailyExamListGroup])
    async def list_exams_GET(
        req: ExamListRequest = Depends(),
    ) -> List[DailyExamListGroup]:
        current_uid = req.user_id if req.user_id is not None else -1

        # We use JSON_TABLE to turn your config keys into a joinable list of IDs
        sql = """
            SELECT 
                e.id, 
                e.exam_name, 
                e.created_at,
                DATE(e.created_at) as session_date,
                -- Pulling raw time; we'll format in Python to avoid the '%%' string bug
                (
                    SELECT GROUP_CONCAT(DISTINCT c.name SEPARATOR ' / ')
                    FROM JSON_TABLE(JSON_KEYS(e.questionnaire_config), '$[*]' COLUMNS(sr_id INT PATH '$')) jt
                    JOIN source_references sr ON sr.id = jt.sr_id
                    JOIN category c ON sr.category_id = c.id
                ) as category_names,
                CASE 
                    WHEN %s > 0 THEN (
                        SELECT COALESCE(attempts, 0) 
                        FROM examination_attempts 
                        WHERE examination_id = e.id AND user_id = %s
                    )
                    ELSE (SELECT COUNT(DISTINCT user_id) FROM examination_attempts WHERE examination_id = e.id)
                END as calculated_metric
            FROM examinations e
            WHERE 1=1
        """
        params = [current_uid, current_uid]

        if req.user_id and req.user_id >= 0:
            sql += " AND EXISTS (SELECT 1 FROM examination_attempts WHERE examination_id = e.id AND user_id = %s)"
            params.append(req.user_id)

        if req.exam_name and req.exam_name.strip():
            sql += " AND e.exam_name LIKE %s"
            params.append(f"%{req.exam_name}%")

        sql += " ORDER BY e.created_at DESC"

        rows = db.select(sql, tuple(params))

        grouped_data = defaultdict(list)
        for r in rows:
            # FORMAT TIME HERE: This bypasses the MySQL/Python '%%' escaping hell
            time_label = r["created_at"].strftime("%I:%M %p") if r["created_at"] else ""

            exam_item = ExamListOut(
                id=r["id"],
                exam_name=r["exam_name"],
                category_name=r["category_names"] or "General",
                created_at=time_label,
                metric_count=r["calculated_metric"],
            )

            date_key = r["session_date"].strftime("%B %d, %Y")
            grouped_data[date_key].append(exam_item)

        return [
            DailyExamListGroup(exam_date=d, exams=items)
            for d, items in grouped_data.items()
        ]

    @staticmethod
    @router.get("/get_exam", response_model=ExamOut)
    async def get_exam_GET(req: ExamGetRequest = Depends()) -> ExamOut:
        # 1. Fetch the master exam record
        exam_rows = db.select("SELECT * FROM examinations WHERE id=%s", (req.exam_id,))
        if not exam_rows:
            raise HTTPException(status_code=404, detail="Exam not found")
        exam = exam_rows[0]

        # 2. Get User-Specific Attempts
        attempt_rows = db.select(
            "SELECT attempts FROM examination_attempts WHERE examination_id=%s AND user_id=%s",
            (req.exam_id, req.user_id),
        )
        user_attempts = attempt_rows[0]["attempts"] if attempt_rows else 0

        # We JOIN questionnaire_items (qi) and examination_questions (eq)
        # We ORDER BY eq.id ASC to preserve the generated sequence (Randomized or Sequential)
        q_sql = """
                SELECT 
                qi.id, 
                qi.question_text, 
                qi.choices, 
                qi.correct_answer,
                sr.slot_name
            FROM questionnaire_items qi
            INNER JOIN examination_questions eq ON qi.id = eq.questionnaire_item_id
            INNER JOIN source_references sr ON qi.questionnaire_id = sr.id
            WHERE eq.examination_id = %s
            ORDER BY eq.id ASC
        """
        q_rows = db.select(q_sql, (req.exam_id,))

        import json

        questions = []
        unique_topics = set()

        for q in q_rows:
            if q.get("slot_name"):
                unique_topics.add(q["slot_name"])

            # Ensure choices are converted from string to Dict if necessary
            if isinstance(q["choices"], str):
                q["choices"] = json.loads(q["choices"])

            questions.append(QuestionOut.model_validate(q))

        return ExamOut(
            id=exam["id"],
            exam_name=exam["exam_name"],
            total_items=exam["total_items"],
            questions=questions,
            user_attempts=user_attempts,
            topics=sorted(list(unique_topics)),
        )

    @staticmethod
    @router.post("/get_exam_reviewees", response_model=List[RevieweeStatusOut])
    async def get_exam_reviewees_POST(req: RevieweeStatusIn) -> List[RevieweeStatusOut]:
        # Fetch all reviewees and left join with their attempts for THIS specific exam
        sql = """
            SELECT 
                u.id, 
                u.username, 
                u.email,
                CASE WHEN ea.attempts > 0 THEN 1 ELSE 0 END as has_taken
            FROM users u
            LEFT JOIN examination_attempts ea ON u.id = ea.user_id AND ea.examination_id = %s
            WHERE u.role = 'Reviewee'
            ORDER BY has_taken DESC, u.username ASC
        """
        rows = db.select(sql, (req.examination_id,))
        return [RevieweeStatusOut(**r) for r in rows]

    @staticmethod
    @router.post("/submit_answers", response_model=SubmissionSummary)
    async def submit_answers_POST(req: SubmitAnswerRequest) -> SubmissionSummary:
        if not req:
            raise HTTPException(status_code=400, detail="No answers provided")

        exam_id = req.answers[0].examination_id
        user_id = req.answers[0].user_id
        now = datetime.utcnow()

        # --- 1. GET ATTEMPT INDEX ---
        # Check the attempts table to see what the NEXT index should be
        attempt_row = db.select(
            "SELECT attempts FROM examination_attempts WHERE examination_id = %s AND user_id = %s",
            (exam_id, user_id),
        )

        current_attempt_count = attempt_row[0]["attempts"] if attempt_row else 0
        new_attempt_index = current_attempt_count + 1

        correct_count = 0
        total_items = len(req.answers)
        for ans in req.answers:
            is_correct = (
                ans.answer_text.strip().upper() == ans.correct_answer.strip().upper()
            )
            if is_correct:
                correct_count += 1

            db.insert(
                """
                INSERT INTO examination_results 
                (user_id, examination_id, question_id, student_answer, is_correct, answered_at, attempt_index)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    ans.user_id,
                    ans.examination_id,
                    ans.question_id,
                    ans.answer_text,
                    is_correct,
                    now,
                    new_attempt_index,
                ),
            )

        # Increment or Create the Attempt Record
        db.insert(
            """
            INSERT INTO examination_attempts (examination_id, user_id, attempts)
            VALUES (%s, %s, 1)
            ON DUPLICATE KEY UPDATE attempts = attempts + 1
        """,
            (req.answers[0].examination_id, req.answers[0].user_id),
        )

        # Calculate immediate proficiency for the summary
        percentage = (correct_count / total_items * 100) if total_items > 0 else 0

        return SubmissionSummary(
            status="success",
            message=f"Attempt recorded. Proficiency: {percentage:.1f}%",
            examination_id=exam_id,
            user_id=user_id,
            score=correct_count,
            total=total_items,
            percentage=percentage,
        )
