from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
import os
from typing import List

from tasks import process_material_task

from utils.connection import manager
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
        file_path = os.path.join("uploads", req.file_name)

        os.makedirs("uploads", exist_ok=True)

        with open(file_path, "wb") as f:
            f.write(await req.file.read())

        # Database Induction: Create record with processed_by_ai = False
        material_id = db.insert(
            "INSERT INTO materials (document_path, title_content, processed_by_ai) VALUES (%s, %s, %s)",
            (file_path, req.file_name, False),
        )

        # Dispatch to Celery: Offload the heavy AI/Parsing logic
        # We pass use_gpu (Ollama toggle) so Celery knows which engine to use
        process_material_task.delay(material_id, file_path, req.use_gpu)

        return MaterialUploadResponse(
            status="success",
            message=f"Module '{req.file_name}' uploaded. AI indexing is running in background.",
            material_id=material_id,
        )

    @staticmethod
    @router.get("/get_materials", response_model=List[MaterialListItem])
    async def get_materials_GET() -> List[MaterialListItem]:
        rows = db.select(
            "SELECT id, document_path, title_content, processed_by_ai, created_at FROM materials ORDER BY created_at DESC"
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
