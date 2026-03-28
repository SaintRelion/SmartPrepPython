from fastapi import APIRouter, HTTPException
import json
from datetime import datetime
from typing import List

from utils.db import db
from utils.generation import select_sections
from utils.gemini import generate_from_section


# Standardized Imports
from .models import GenerateExamRequest, GeneratedQuestion

router = APIRouter(prefix="/ai", tags=["ai"])


class AIController:

    @staticmethod
    @router.post("/generate_exam", response_model=List[GeneratedQuestion])
    def generate_exam_POST(req: GenerateExamRequest) -> List[GeneratedQuestion]:
        focus = req.focus
        difficulty = req.difficulty

        # 1️⃣ Insert Main Exam Record
        total_items = sum(m.items for m in req.materials)
        exam_id = db.insert(
            """
            INSERT INTO examinations (difficulty, focus, total_items, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            (difficulty, focus, total_items, datetime.utcnow()),
        )

        all_saved_questions = []

        # 2️⃣ Loop through materials
        for material in req.materials:
            db.insert(
                """
                INSERT INTO examination_parts (exam_id, material_id, items)
                VALUES (%s, %s, %s)
                """,
                (exam_id, material.material_id, material.items),
            )

            # 3️⃣ Logic for sections and generation
            sections = select_sections(focus, difficulty, material)
            if not sections:
                continue

            questions_per_section = material.items // len(sections)
            remainder = material.items % len(sections)

            material_questions = []
            for i, s in enumerate(sections):
                n = questions_per_section + (1 if i < remainder else 0)

                section_questions = generate_from_section(difficulty, s, n)
                for q in section_questions:
                    q["_section_id"] = s["id"]
                material_questions.extend(section_questions)

            # 4️⃣ Save to DB and map to our Pydantic Model
            for q in material_questions:
                section_id = q["_section_id"]
                question_id = db.insert(
                    """
                    INSERT INTO questions
                    (examination_id, material_id, section_id,
                     question_text, choices, correct_answer, difficulty)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        exam_id,
                        material.material_id,
                        section_id,
                        q.get("question_text"),
                        json.dumps(q.get("choices")),
                        q.get("correct_answer"),
                        difficulty,
                    ),
                )

                all_saved_questions.append(
                    GeneratedQuestion(
                        id=question_id,
                        material_id=material.material_id,
                        question_text=q.get("question_text"),
                        choices=q.get("choices"),
                        correct_answer=q.get("correct_answer"),
                    )
                )

        if not all_saved_questions:
            raise HTTPException(
                status_code=400,
                detail="No questions generated for the given materials.",
            )

        return all_saved_questions
