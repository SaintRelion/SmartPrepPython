from fastapi import APIRouter, Depends, HTTPException
import os
import json
import requests
import PyPDF2
from typing import List

from utils.tasks import process_material_task

from .models import (
    MaterialUploadRequest,
    MaterialUploadResponse,
    MaterialListItem,
    SectionItem,
    GetSectionsRequest,
)
from utils.db import db

router = APIRouter(prefix="/materials", tags=["Materials"])


class MaterialsController:
    @staticmethod
    @router.post("/upload_material", response_model=MaterialUploadResponse)
    async def upload_material_POST(
        req: MaterialUploadRequest = Depends(MaterialUploadRequest.as_form),
    ) -> MaterialUploadResponse:

        clean_title = os.path.splitext(req.file.filename)[0]
        file_path = os.path.join("uploads", req.file.filename)

        # 1. Fast IO: Save the file
        with open(file_path, "wb") as f:
            f.write(await req.file.read())

        # Database Induction: Create record with processed_by_ai = False
        material_id = db.insert(
            "INSERT INTO materials (document_path, title_content, processed_by_ai) VALUES (%s, %s, %s)",
            (file_path, clean_title, False),
        )

        # Dispatch to Celery: Offload the heavy AI/Parsing logic
        # We pass use_gpu (Ollama toggle) so Celery knows which engine to use
        process_material_task.delay(material_id, file_path, req.use_gpu)

        return MaterialUploadResponse(
            status="success",
            message="Module uploaded. Intelligence indexing started in background.",
            material_id=material_id,
        )

    @staticmethod
    @router.get("/get_materials_GET", response_model=List[MaterialListItem])
    async def get_materials_GET() -> List[MaterialListItem]:
        rows = db.select(
            "SELECT id, document_path, title_content, created_at FROM materials"
        )
        return [MaterialListItem(**r) for r in rows]

    @staticmethod
    @router.get("/get_sections", response_model=List[SectionItem])
    async def get_sections_GET(
        req: GetSectionsRequest = Depends(),
    ) -> List[SectionItem]:
        rows = db.select(
            """
            SELECT id, section_name
            FROM sections
            WHERE material_id=%s
            """,
            (req.material_id,),
        )
        return [SectionItem(**r) for r in rows]
