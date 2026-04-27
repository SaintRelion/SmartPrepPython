import json

from pydantic import BaseModel, field_validator, model_validator
from typing import Any, Dict, List, Optional
from datetime import datetime


# --- REQUEST MODELS ---
class RevieweeStatusIn(BaseModel):
    examination_id: int


class QuestionOut(BaseModel):
    id: int
    question_text: str
    choices: Dict[str, str]
    correct_answer: str

    @field_validator("choices", mode="before")
    @classmethod
    def parse_choices(cls, v: Any):
        return json.loads(v) if isinstance(v, str) else v


class ExamListRequest(BaseModel):
    user_id: Optional[int] = (None,)
    exam_name: Optional[str] = None


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


class ExamGenerationRequest(BaseModel):
    exam_name: str
    total_items: int
    is_randomized: bool  # New toggle
    questionnaires: Dict[str, int]  # { "questionnaire_id": count }


class ExamRenameRequest(BaseModel):
    exam_id: int
    new_name: str


class ExamRenameResponse(BaseModel):
    success: bool
    message: str
    updated_name: Optional[str] = None


# --- RESPONSE MODELS ---


class ExamHistoryItem(BaseModel):
    examination_id: int
    answered_at: datetime
    exam_name: str
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
    option_a: str = ""
    option_b: str = ""
    option_c: str = ""
    option_d: str = ""
    answer: str  # Maps to correct_answer in DB

    @model_validator(mode="before")
    @classmethod
    def flatten_choices(cls, data: Any) -> Any:
        # 1. Parse choices if it's a string
        choices = data.get("choices")
        if isinstance(choices, str):
            choices = json.loads(choices)

        # 2. Map dict keys (A, B, C, D) to flat properties
        if isinstance(choices, dict):
            data["option_a"] = choices.get("A", "")
            data["option_b"] = choices.get("B", "")
            data["option_c"] = choices.get("C", "")
            data["option_d"] = choices.get("D", "")

        # 3. Rename correct_answer to answer to match your VB model
        if "correct_answer" in data:
            data["answer"] = data["correct_answer"]

        return data


class ExamListOut(BaseModel):
    id: int
    exam_name: str
    category_name: str
    created_at: str
    metric_count: int


class DailyExamListGroup(BaseModel):
    exam_date: str
    exams: List[ExamListOut]


class ExamOut(BaseModel):
    id: int
    exam_name: str
    total_items: int
    questions: List[QuestionOut]
    user_attempts: int


class ExamGenerationResponse(BaseModel):
    status: str
    message: str
    examination_id: int


class RevieweeStatusOut(BaseModel):
    id: int
    username: str
    email: str
    has_taken: bool


class ExamDeleteRequest(BaseModel):
    exam_id: int


class ExamDeleteResponse(BaseModel):
    success: bool
    message: str
