from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class StudentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    target_overall: float | None = Field(default=7.0, ge=0.0, le=9.0)
    target_writing: float | None = Field(default=6.5, ge=0.0, le=9.0)
    target_speaking: float | None = Field(default=6.5, ge=0.0, le=9.0)
    current_overall: float | None = Field(default=None, ge=0.0, le=9.0)
    notes: str = Field(default="", max_length=5000)
    status: Literal["active", "paused", "completed"] = "active"


class WritingSubmissionCreate(BaseModel):
    student_id: str
    lesson_id: str | None = None
    task_type: Literal["task1", "task2"] = "task2"
    prompt_text: str = Field(..., min_length=10, max_length=4000)
    response_text: str = Field(..., min_length=20, max_length=15000)


class SpeakingSubmissionCreate(BaseModel):
    student_id: str
    lesson_id: str | None = None
    task_type: Literal["part1", "part2", "part3"] = "part2"
    prompt_text: str = Field(..., min_length=5, max_length=4000)
    transcript_text: str = Field(default="", max_length=15000)
    duration_seconds: float = Field(default=90.0, ge=0.0, le=1800.0)


class TranscriptUpdateRequest(BaseModel):
    transcript_text: str = Field(..., min_length=5, max_length=15000)
    duration_seconds: float | None = Field(default=None, ge=0.0, le=1800.0)


class TranscribeRequest(BaseModel):
    whisper_model: Literal["small.en", "medium.en", "base.en"] = "small.en"


class AssessWritingRequest(BaseModel):
    model_name: str = "qwen3:8b"
    think: bool = Field(
        default=False,
        description="Bật/tắt chế độ suy luận sâu của Qwen3.",
    )


class TeacherReviewRequest(BaseModel):
    assessment_id: str | None = None
    teacher_overall: float = Field(..., ge=0.0, le=9.0)
    teacher_feedback: str = Field(default="", max_length=10000)
    updated_feedback_json: dict[str, Any] | None = None
