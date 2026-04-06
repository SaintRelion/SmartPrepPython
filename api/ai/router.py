from fastapi import APIRouter
import json

from api.ai.models import ExamGenerationRequest, ExamGenerationResponse
from tasks import process_exam_generation_task
from utils.db import db

# Standardized Imports

router = APIRouter(prefix="/ai", tags=["ai"])


class AIController:

    @staticmethod
    @router.post("/generate_exam", response_model=ExamGenerationResponse)
    async def generate_exam_POST(req: ExamGenerationRequest) -> ExamGenerationResponse:
        # 1. Database Induction
        # We store the material requirements as a JSON string for Celery to read
        exam_id = db.insert(
            """INSERT INTO examinations 
            (difficulty, focus, total_items, material_config, processed_by_ai) 
            VALUES (%s, %s, %s, %s, %s)""",
            (
                req.difficulty,
                req.focus,
                req.total_items,
                json.dumps(req.materials),
                0,  # Status: Pending
            ),
        )

        # 2. Dispatch to Celery
        # Offload the heavy AI generation and question insertion
        process_exam_generation_task.delay(exam_id)

        return ExamGenerationResponse(
            status="success",
            message="Exam generation request queued. AI is building your questions.",
            examination_id=exam_id,
        )
