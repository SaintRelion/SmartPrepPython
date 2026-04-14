from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
import os
from typing import List

from tasks import process_material_task

from utils.connection import manager
from .models import (
    GetMaterialsRequest,
    MaterialUploadRequest,
    MaterialUploadResponse,
    MaterialListItem,
    SectionItem,
    GetSectionsRequest,
    SyncPendingResponse,
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
        process_material_task.delay(material_id, file_path)

        return MaterialUploadResponse(
            status="success",
            message=f"Module '{req.file_name}' uploaded. AI indexing is running in background.",
            material_id=material_id,
        )

    @staticmethod
    @router.get("/get_materials", response_model=List[MaterialListItem])
    async def get_materials_GET(
        req: GetMaterialsRequest = Depends(),
    ) -> List[MaterialListItem]:
        query = "SELECT id, document_path, title_content, processed_by_ai, processing_progress, created_at FROM materials"
        params = []

        if req.processed_by_ai >= 0:
            print(req.processed_by_ai)
            query += " WHERE processed_by_ai = %s"
            params.append(req.processed_by_ai)

        query += " ORDER BY created_at DESC"

        rows = db.select(query, tuple(params))
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

    @router.post("/sync_pending_materials", response_model=SyncPendingResponse)
    async def sync_pending_materials_POST() -> SyncPendingResponse:
        rows = db.select(
            "SELECT id, document_path FROM materials WHERE processed_by_ai = 0"
        )

        pending = rows if rows else []

        for item in pending:
            process_material_task.delay(item["id"], item["document_path"])

        # This will now be strictly validated against SyncPendingResponse
        return SyncPendingResponse(
            status="success",
            queued_count=len(pending),
            message=f"Re-queued {len(pending)} pending modules.",
        )
