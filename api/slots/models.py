from datetime import datetime
from pydantic import BaseModel, field_validator
from fastapi import UploadFile, File, Form
from typing import Dict, List, Optional

# --- REQUEST MODELS ---


class CategoryCreateRequest(BaseModel):
    name: str


class SlotCreateRequest(BaseModel):
    category_id: int
    slot_name: str


class SlotUpdateRequest(BaseModel):
    slot_id: int
    new_slot_name: str


class DeleteSlotRequest(BaseModel):
    slot_id: int


class UnifiedUploadRequest(BaseModel):
    file: UploadFile
    slot_id: int
    file_name: str
    file_type: str  # "material" or "questionnaire"

    @classmethod
    def as_form(
        cls,
        file: UploadFile = File(...),
        slot_id: int = Form(...),
        file_name: str = Form(...),
        file_type: str = Form(...),
    ):
        return cls(file=file, slot_id=slot_id, file_name=file_name, file_type=file_type)


class GetByCategoryIdRequest(BaseModel):
    category_id: int


class GetBySlotIdRequest(BaseModel):
    slot_id: int


# --- RESPONSE MODELS ---


class CategoryItem(BaseModel):
    id: int
    name: str


class SourceReferenceItem(BaseModel):
    id: int
    category_id: int
    slot_name: str
    material_path: Optional[str] = None
    questionnaire_path: Optional[str] = None
    is_material_uploaded: bool = False
    is_questionnaire_extracted: bool = False
    item_count: int = 0
    active_exam_count: int = 0
    created_at: Optional[str] = None

    @field_validator("created_at", mode="before")
    @classmethod
    def format_date(cls, v):
        if isinstance(v, datetime):
            return v.strftime("%B %d, %Y")
        return v

    @field_validator(
        "is_material_uploaded", "is_questionnaire_extracted", mode="before"
    )
    @classmethod
    def force_bool(cls, v):
        if v is None:
            return False
        return bool(v)


class GenericResponse(BaseModel):
    status: str
    message: str
    id: Optional[str] = None


class QuestionnaireItem(BaseModel):
    id: int
    questionnaire_id: int
    question_text: str
    choices: Dict[str, str]  # Map of A, B, C, D to their text
    correct_answer: str  # E.g., "C"

    @classmethod
    def from_db(cls, row: dict):
        """Helper to parse JSON choices from the DB row"""
        import json

        return cls(
            id=row["id"],
            questionnaire_id=row["questionnaire_id"],
            question_text=row["question_text"],
            choices=(
                json.loads(row["choices"])
                if isinstance(row["choices"], str)
                else row["choices"]
            ),
            correct_answer=row["correct_answer"],
        )
