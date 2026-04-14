from datetime import datetime

from pydantic import BaseModel, field_validator
from fastapi import UploadFile, File, Form
from typing import List, Optional


# --- REQUEST MODELS ---
class MaterialUploadRequest(BaseModel):
    file: UploadFile
    file_name: str

    @classmethod
    def as_form(
        cls,
        file: UploadFile = File(...),
        file_name: str = Form(...),
        use_gpu: bool = Form(False),
    ):
        return cls(file=file, file_name=file_name, use_gpu=use_gpu)


class GetMaterialsRequest(BaseModel):
    processed_by_ai: Optional[int] = None


class GetSectionsRequest(BaseModel):
    material_id: int


# --- RESPONSE MODELS ---
class MaterialListItem(BaseModel):
    id: int
    document_path: str
    title_content: str
    processed_by_ai: int
    processing_progress: Optional[int] = 0
    created_at: str

    @field_validator("processing_progress", mode="before")
    @classmethod
    def handle_null_progress(cls, v):
        # BD AMPL KOS: Forensic null handling
        if v is None:
            return 0
        return v

    @field_validator("created_at", mode="before")
    @classmethod
    def format_date(cls, v):
        if isinstance(v, datetime):
            # Formats to: January 25, 2026 - 10 AM
            # %p provides AM/PM, %I provides 12-hour format
            return v.strftime("%B %d, %Y - %I %p")
        return v


class SectionItem(BaseModel):
    id: int
    section_name: str


class MaterialUploadResponse(BaseModel):
    status: str
    message: str
    material_id: int


class SyncPendingResponse(BaseModel):
    status: str
    queued_count: int
    message: str
