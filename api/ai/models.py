from pydantic import BaseModel
from typing import List, Optional

# --- REQUEST MODELS ---


class MaterialRequest(BaseModel):
    material_id: int
    items: int


class GenerateExamRequest(BaseModel):
    focus: str
    difficulty: str
    materials: List[MaterialRequest]


# --- RESPONSE MODELS ---


class GeneratedQuestion(BaseModel):
    id: int
    material_id: int
    question_text: str
    choices: List[str]
    correct_answer: str


class AIErrorResponse(BaseModel):
    error: str
