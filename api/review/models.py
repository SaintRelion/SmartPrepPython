import json

from pydantic import BaseModel, field_validator
from typing import Any, Dict, List, Optional
from datetime import datetime


# --- REQUEST MODELS ---
class QuestionOut(BaseModel):
    id: int
    question_text: str
    choices: Dict[str, str]
    correct_answer: str

    @field_validator("choices", mode="before")
    @classmethod
    def parse_choices(cls, v: Any):
        return json.loads(v) if isinstance(v, str) else v


class AdminExamStatusOut(BaseModel):
    id: int
    focus: str
    difficulty: str
    total_items: int
    material_config: Dict[str, int]
    processed_by_ai: int
    created_at: datetime

    generated_count: int = 0
    questions: List[QuestionOut] = []

    @property
    def status_label(self) -> str:
        status_map = {0: "Pending", 1: "Processing", 2: "Completed", 3: "Error"}
        return status_map.get(self.processed_by_ai, "Unknown")

    @field_validator("material_config", mode="before")
    @classmethod
    def parse_json_config(cls, v: Any):
        return json.loads(v) if isinstance(v, str) else v


class ExamListRequest(BaseModel):
    user_id: Optional[int] = (None,)
    focus: Optional[str] = None
    difficulty: Optional[str] = None


class ExamGetRequest(BaseModel):
    user_id: int
    exam_id: int


class AnswerIn(BaseModel):
    user_id: str
    examination_id: int
    question_id: int
    answer_text: str
    correct_answer: str


class SubmitAnswerRequest(BaseModel):
    answers: List[AnswerIn]


# --- RESPONSE MODELS ---


class ExamHistoryItem(BaseModel):
    examination_id: int
    answered_at: datetime
    focus: str
    total_questions: int
    correct_count: int
    score_display: str


class DailyExamGroup(BaseModel):
    exam_date: str
    sessions: List[ExamHistoryItem]


class WeakSection(BaseModel):
    section_id: int
    score: float
    status: str


class AnswerDetail(BaseModel):
    question_id: int
    your_answer: str
    is_correct: bool
    correct_answer: str
    question_text: str
    section_id: int


class SubmissionSummary(BaseModel):
    status: str
    message: str
    examination_id: int
    user_id: str
    score: int  # Added for immediate feedback
    total: int  # Added for immediate feedback
    percentage: float  # Added for immediate feedback


class QuestionOut(BaseModel):
    id: int
    question_text: str
    choices: Dict[str, str]
    correct_answer: str

    @field_validator("choices", mode="before")
    @classmethod
    def validate_choices(cls, v):
        # 1. Parse JSON string if it comes from the DB as text
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return {}

        # 2. If it's a list (e.g., ["Ans1", "Ans2"]), convert to Dict {"0": "Ans1", ...}
        # Or use Alpha keys {"A": "Ans1", "B": "Ans2"} to match Exam UI
        if isinstance(v, list):
            import string

            # Maps index to A, B, C, D...
            return {
                string.ascii_uppercase[i]: str(choice) for i, choice in enumerate(v)
            }

        # 3. If it's already a dict, ensure keys/values are strings
        if isinstance(v, dict):
            return {str(k): str(val) for k, val in v.items()}

        return {}


class ExamListOut(BaseModel):
    id: int
    focus: str
    difficulty: str
    created_at: str
    reviewee_count: int


class DailyExamListGroup(BaseModel):
    exam_date: str
    exams: List[ExamListOut]


class ExamOut(BaseModel):
    id: int
    focus: str
    difficulty: str
    total_items: int
    questions: List[QuestionOut]
    user_attempts: int
