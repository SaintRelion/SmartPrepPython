from fastapi import APIRouter, Depends, HTTPException
from typing import List
import os
from utils.db import db
from utils.extractor import extract_questionnaire
from .models import (
    CategoryCreateRequest,
    CategoryItem,
    DeleteSlotRequest,
    GenericResponse,
    GetBySlotIdRequest,
    QuestionnaireItem,
    SourceReferenceItem,
    SlotCreateRequest,
    SlotUpdateRequest,
    UnifiedUploadRequest,
    GetByCategoryIdRequest,
)

router = APIRouter(prefix="/slots", tags=["Source References"])


class SlotsController:
    # --- CATEGORY ---
    @router.post("/create_category", response_model=GenericResponse)
    async def create_category_POST(req: CategoryCreateRequest):
        cat_id = db.insert("INSERT INTO category (name) VALUES (%s)", (req.name,))
        return GenericResponse(
            status="success", message="Category created", id=str(cat_id)
        )

    @router.post("/delete_category", response_model=GenericResponse)
    async def delete_category_POST(req: GetByCategoryIdRequest):
        # 1. Check if category has existing slots
        count = db.fetchone(
            "SELECT COUNT(*) as total FROM source_references WHERE category_id = %s",
            (req.category_id,),
        )

        if count and count["total"] > 0:
            return GenericResponse(
                status="error",
                message="Cannot delete: This category still contains active topic slots.",
            )

        # 2. Proceed with deletion
        db.execute("DELETE FROM category WHERE id = %s", (req.category_id,))
        return GenericResponse(
            status="success", message="Category deleted successfully"
        )

    @router.get("/get_categories", response_model=List[CategoryItem])
    async def get_categories_GET() -> List[CategoryItem]:
        sql = "SELECT id, name FROM category ORDER BY name ASC"
        return db.select(sql)

    @router.post("/get_slots_by_category", response_model=List[SourceReferenceItem])
    async def get_slots_by_category_POST(
        req: GetByCategoryIdRequest,
    ) -> List[SourceReferenceItem]:
        query = """
            SELECT 
            s.*, 
            (SELECT COUNT(*) FROM questionnaire_items WHERE questionnaire_id = s.id) as item_count,
            (
                SELECT COUNT(DISTINCT eq.examination_id) 
                FROM examination_questions eq
                JOIN questionnaire_items qi ON eq.questionnaire_item_id = qi.id
                WHERE qi.questionnaire_id = s.id
            ) as active_exam_count
        FROM source_references s
        WHERE s.category_id = %s
        ORDER BY s.created_at DESC
        """
        result = db.select(query, (int(req.category_id),))
        return result

    @router.post("/create_slot", response_model=GenericResponse)
    async def create_slot_POST(req: SlotCreateRequest) -> GenericResponse:
        sql = "INSERT INTO source_references (category_id, slot_name) VALUES (%s, %s)"
        slot_id = db.insert(sql, (req.category_id, req.slot_name))
        return GenericResponse(
            status="success", message="Slot created", id=str(slot_id)
        )

    @router.post("/update_slot_name", response_model=GenericResponse)
    async def update_slot_name_POST(
        req: SlotUpdateRequest,
    ) -> GenericResponse:
        sql = "UPDATE source_references SET slot_name = %s WHERE id = %s"
        db.execute(sql, (req.new_slot_name, req.slot_id))
        return GenericResponse(status="success", message="Slot name updated")

    @router.post("/upload_source_file", response_model=GenericResponse)
    async def upload_source_file_POST(
        req: UnifiedUploadRequest = Depends(UnifiedUploadRequest.as_form),
    ) -> GenericResponse:
        is_quest = req.file_type.lower() == "questionnaire"
        folder = "questionnaires" if is_quest else "materials"
        prefix = "QUEST" if is_quest else "MAT"

        save_name = f"{prefix}_ID{req.slot_id}_{req.file_name}"
        save_path = os.path.join("uploads", folder, save_name)

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        content = await req.file.read()
        with open(save_path, "wb") as f:
            f.write(content)

        if is_quest:
            sql = "UPDATE source_references SET questionnaire_path = %s, is_questionnaire_extracted = 0 WHERE id = %s"
            db.execute(sql, (save_path, req.slot_id))
            extract_questionnaire(req.slot_id, save_path)
        else:
            sql = "UPDATE source_references SET material_path = %s, is_material_uploaded = 1 WHERE id = %s"
            db.execute(sql, (save_path, req.slot_id))

        return GenericResponse(
            status="success", message=f"{req.file_type} uploaded", id=str(req.slot_id)
        )

    @router.post("/delete_slot", response_model=GenericResponse)
    async def delete_slot_POST(req: DeleteSlotRequest) -> GenericResponse:
        db.execute("DELETE FROM source_references WHERE id = %s", (req.slot_id,))
        return GenericResponse(status="success", message="Slot deleted")

    @router.post("/get_items_by_slot", response_model=List[QuestionnaireItem])
    async def get_items_by_slot_POST(
        req: GetBySlotIdRequest,
    ) -> List[QuestionnaireItem]:
        sql = "SELECT * FROM questionnaire_items WHERE questionnaire_id = %s"
        rows = db.select(sql, (req.slot_id,))
        return [QuestionnaireItem.from_db(row) for row in rows]
