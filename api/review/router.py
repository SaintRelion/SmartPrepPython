from collections import defaultdict

from fastapi import APIRouter, HTTPException, Depends
from typing import List
from datetime import datetime

from utils.db import db
from .models import (
    DailyExamListGroup,
    ExamListOut,
    ExamOut,
    QuestionOut,
    AnswerIn,
    SubmissionSummary,
    ExamListRequest,
    ExamGetRequest,
    SubmitAnswerRequest,
)

router = APIRouter(prefix="/review", tags=["Reviewee"])


class ReviewController:
    @staticmethod
    @router.get("/list_exams", response_model=List[DailyExamListGroup])
    async def list_exams_GET(
        req: ExamListRequest = Depends(),
    ) -> List[DailyExamListGroup]:
        params = []

        # Base SQL including date for grouping
        sql = """
            SELECT 
                e.id, e.focus, e.difficulty, e.created_at,
                DATE(e.created_at) as session_date,
                COUNT(DISTINCT er.user_id) as reviewee_count
            FROM Examinations e
            LEFT JOIN ExaminationResults er ON e.id = er.examination_id
            WHERE 1=1
        """

        if req.user_id:
            # If filtering for a specific user's history, we ensure they have at least one result
            sql += " AND e.id IN (SELECT examination_id FROM ExaminationResults WHERE user_id = %s)"
            params.append(req.user_id)

        if req.focus:
            sql += " AND focus = %s"
            params.append(req.focus)
        if req.difficulty:
            sql += " AND difficulty = %s"
            params.append(req.difficulty)

        sql += " GROUP BY e.id ORDER BY e.created_at DESC"

        rows = db.select(sql, tuple(params))

        # Grouping Logic
        grouped_data = defaultdict(list)
        for r in rows:
            exam_item = ExamListOut(
                id=r["id"],
                focus=r["focus"],
                difficulty=r["difficulty"],
                created_at=r["created_at"].strftime("%H:%M"),
                reviewee_count=r["reviewee_count"],
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
        exam_rows = db.select("SELECT * FROM Examinations WHERE id=%s", (req.exam_id,))
        if not exam_rows:
            raise HTTPException(status_code=404, detail="Exam not found")
        exam = exam_rows[0]

        # Get User-Specific Attempts
        attempt_rows = db.select(
            "SELECT attempts FROM examination_attempts WHERE examination_id=%s AND user_id=%s",
            (req.exam_id, req.user_id),  # Ensure ExamGetRequest includes user_id
        )
        user_attempts = attempt_rows[0]["attempts"] if attempt_rows else 0

        q_rows = db.select(
            "SELECT id, question_text, choices, correct_answer FROM Questions WHERE examination_id=%s ORDER BY id ASC",
            (req.exam_id,),
        )
        questions = [QuestionOut.model_validate(q) for q in q_rows]

        return ExamOut(
            id=exam["id"],
            focus=exam["focus"],
            difficulty=exam["difficulty"],
            total_items=exam["total_items"],
            questions=questions,
            user_attempts=user_attempts,
        )

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
                INSERT INTO ExaminationResults 
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
