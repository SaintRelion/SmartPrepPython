from pydantic import BaseModel
from typing import List, Optional


class GenerateExamRequest(BaseModel):
    document_id: int
    items: int
    difficulty: str
    focus: str
    exam_type: str
    section_names: Optional[List[str]] = None


class QuestionOut(BaseModel):
    id: int
    question_text: str
    choices: List[str] = []

class ExamListOut(BaseModel):
    id: int
    focus: str
    exam_type: str

class ExamOut(BaseModel):
    id: int
    document_id: int
    difficulty: str
    focus: str
    exam_type: str
    total_items: int
    questions: List[QuestionOut]


class AnswerIn(BaseModel):
    examination_id: int
    question_id: int
    answer_text: str
