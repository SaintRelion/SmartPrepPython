from pydantic import BaseModel

from typing import List, Optional


class StatsRequest(BaseModel):
    user_id: Optional[int] = None
    examination_id: Optional[int] = None
    focus: Optional[str] = None
    difficulty: Optional[str] = None
    material_ids: Optional[List[int]] = (
        None  # Changed to List for Cross-Material support
    )
    limit: Optional[int] = None


class PerformanceMetric(BaseModel):
    id: int
    label: str
    score: int
    total: int
    percentage: float

    material_breakdown: Optional[List["PerformanceMetric"]] = None


PerformanceMetric.model_rebuild()


class QuestionForensic(BaseModel):
    question_text: str
    student_answer: str
    correct_answer: str
    is_correct: bool
    material_id: int


class ExamAnalyticsResponse(BaseModel):
    overall_competency: float
    material_breakdown: List[PerformanceMetric]
    difficulty_breakdown: List[PerformanceMetric]
    question_logs: List[QuestionForensic]


# STRENGTH AND WEAKNESS


class PersonnelStat(BaseModel):
    user_id: int
    username: str
    overall_competency: float
    # Nested breakdowns for Tab 2 / Inspection
    material_breakdown: List[PerformanceMetric]
    section_breakdown: List[PerformanceMetric]


class PersonnelAnalyticsResponse(BaseModel):
    avg_proficiency: float
    total_active: int
    critical_weakness: str
    dossiers: List[PersonnelStat]
