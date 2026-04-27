from pydantic import BaseModel

from typing import List, Optional


class ForensicAttemptRequest(BaseModel):
    examination_id: int
    attempt_index: int
    user_id: Optional[int] = None


class StatsRequest(BaseModel):
    user_id: Optional[int] = None
    examination_id: Optional[int] = None
    focus: Optional[str] = None
    material_ids: Optional[List[int]] = (
        None  # Changed to List for Cross-Material support
    )
    limit: Optional[int] = None


class PerformanceMetric(BaseModel):
    id: int  # category_id
    label: str  # category_name
    score: int
    total: int
    percentage: float
    # Nesting allowed for sub-topics (questionnaires) if needed later
    topic_breakdown: Optional[List["PerformanceMetric"]] = None


PerformanceMetric.model_rebuild()


class QuestionForensic(BaseModel):
    category_id: int
    question_text: str
    student_answer: str
    correct_answer: str
    is_correct: bool

    option_a_analysis: str = ""
    option_b_analysis: str = ""
    option_c_analysis: str = ""
    option_d_analysis: str = ""


class ExamAnalyticsResponse(BaseModel):
    overall_competency: float
    topic_breakdown: List[PerformanceMetric]
    question_logs: List[QuestionForensic]


class LeaderEntry(BaseModel):
    rank: int
    student_name: str
    percentage: float
    total_items: int


class SubjectLeaderboard(BaseModel):
    topic_name: str
    top_performers: List[LeaderEntry]


class GlobalExcellenceResponse(BaseModel):
    success: bool
    subject_leaderboards: List[SubjectLeaderboard]


class BatchPerformance(BaseModel):
    attempt_number: int
    average_accuracy: float
    examinee_count: int
    date_recorded: Optional[str] = None


class ComparativeTrendResponse(BaseModel):
    exam_id: int
    user_id: Optional[int] = None
    trend_label: str  # e.g., "Individual Progress" or "Batch Trends"
    current_status: str  # "Improving", "Regressing", or "Stable"
    delta: float  # The difference between the last two attempts
    history: List[BatchPerformance]


class ForensicLogItem(BaseModel):
    category_id: int
    category_name: str
    question_text: str
    correct_answer: str
    student_answer: str
    is_correct: bool
    previous_student_answer: Optional[str] = None
    previous_is_correct: Optional[bool] = None
    # THE CORE DATA: Library of reasonings
    option_a_analysis: str = ""
    option_b_analysis: str = ""
    option_c_analysis: str = ""
    option_d_analysis: str = ""


class ForensicAttemptResponse(BaseModel):
    success: bool
    comparative_items: List[ForensicLogItem]
    message: Optional[str] = None


class SlotHistoryPoint(BaseModel):
    date_recorded: str
    slot_name: str
    accuracy: float
    examinee_count: int


class GrowthTrendResponse(BaseModel):
    trend_label: str
    unique_slots: List[str]  # Legend: ["Criminal Law", "Evidence", etc.]
    history: List[SlotHistoryPoint]
