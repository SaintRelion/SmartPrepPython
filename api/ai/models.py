from pydantic import BaseModel
from typing import Dict


# --- REQUEST MODELS ---
class ExamGenerationRequest(BaseModel):
    difficulty: str  # e.g., "Easy", "Hard"
    focus: str  # e.g., "Vocabulary", "Concepts"
    total_items: int
    # Dictionary: { "material_id": item_count }
    # e.g., {"101": 5, "102": 10}
    materials: Dict[str, int]


# --- RESPONSE MODELS ---
class ExamGenerationResponse(BaseModel):
    status: str
    message: str
    examination_id: int
