from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel as _PydanticBaseModel, Field

class BaseModel(_PydanticBaseModel):
    """Compatibility wrapper supporting both Pydantic v2 and Pydantic v1."""
    _non_empty_list_fields: tuple[str, ...] = ()

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        for fname in getattr(self, "_non_empty_list_fields", ()):
            val = getattr(self, fname, None)
            if isinstance(val, list) and len(val) == 0:
                raise ValueError(f"List field '{fname}' must contain at least 1 item.")
    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if hasattr(super(), "model_dump"):
            return super().model_dump(*args, **kwargs)  # type: ignore[misc]
        return self.dict(*args, **kwargs)

    def model_dump_json(self, *args: Any, **kwargs: Any) -> str:
        if hasattr(super(), "model_dump_json"):
            return super().model_dump_json(*args, **kwargs)  # type: ignore[misc]
        return self.json(*args, **kwargs)

    @classmethod
    def model_validate(cls, obj: Any):
        if hasattr(super(), "model_validate"):
            return super().model_validate(obj)  # type: ignore[misc]
        return cls.parse_obj(obj)

    @classmethod
    def model_validate_json(cls, raw_json: str | bytes):
        if hasattr(super(), "model_validate_json"):
            return super().model_validate_json(raw_json)  # type: ignore[misc]
        return cls.parse_raw(raw_json)


SUPPORTED_EXERCISE_TYPES = {
    "model_analysis",
    "error_correction",
    "sentence_transformation",
    "paraphrasing",
    "vocabulary_collocation",
    "guided_paragraph",
    "independent_writing",
    "speaking_prompt",
    "self_assessment",
    "exit_ticket",
}

SUPPORTED_PROGRESSION_STAGES = {"scaffolded", "guided", "independent"}

class ExplicitOrAssumedField(BaseModel):
    field_name: str
    status: Literal["explicit", "assumed"] = "explicit"
    rationale: str = ""

class PlannedActivityDraft(BaseModel):
    title: str = Field(..., min_length=2)
    duration_minutes: int = Field(..., ge=1, le=180)
    learning_objective: str = Field(..., min_length=2)
    priority_level: Literal["essential", "core", "optional_extension"] = "core"
    is_assumed: bool = False

class LessonPlanAnalysisOutput(BaseModel):
    _non_empty_list_fields = ('learning_objectives', 'planned_activities')
    title: str = Field(..., min_length=2)
    skill: Literal["writing", "speaking", "integrated"] = "writing"
    task_type: str = Field(..., min_length=2)
    duration_minutes: int = Field(default=60, ge=10, le=240)
    student_current_band: float | None = None
    student_target_band: float | None = None
    learning_objectives: list[str] = Field(...)
    prerequisite_knowledge: list[str] = Field(default_factory=list)
    planned_activities: list[PlannedActivityDraft] = Field(...)
    available_resources: list[str] = Field(default_factory=list)
    expected_difficulties: list[str] = Field(default_factory=list)
    assessment_criteria: list[str] = Field(default_factory=list)
    explicit_vs_assumed: list[ExplicitOrAssumedField] = Field(default_factory=list)

class AnalyzeLessonPlanRequest(BaseModel):
    raw_lesson_plan: str = ""
    title: str = ""
    objectives: list[str] = Field(default_factory=list)
    skill: Literal["writing", "speaking", "integrated"] = "writing"
    task_type: str = "task2"
    student_id: str | None = None
    student_current_band: float | None = None
    student_target_band: float | None = None
    duration_minutes: int = Field(default=60, ge=10, le=240)
    teacher_notes: str = ""
    source_material_ids: list[str] = Field(default_factory=list)
    personalization_enabled: bool = True
    model_name: str = "qwen3:8b"
    think: bool = False
    force_regenerate: bool = False

class UpdateLessonPlanReviewRequest(BaseModel):
    _non_empty_list_fields = ('learning_objectives', 'planned_activities')
    title: str = Field(..., min_length=2)
    skill: Literal["writing", "speaking", "integrated"] = "writing"
    task_type: str = Field(..., min_length=2)
    duration_minutes: int = Field(..., ge=10, le=240)
    student_id: str | None = None
    student_current_band: float | None = None
    student_target_band: float | None = None
    learning_objectives: list[str] = Field(...)
    prerequisite_knowledge: list[str] = Field(default_factory=list)
    planned_activities: list[PlannedActivityDraft] = Field(...)
    available_resources: list[str] = Field(default_factory=list)
    expected_difficulties: list[str] = Field(default_factory=list)
    assessment_criteria: list[str] = Field(default_factory=list)
    teacher_notes: str = ""
    personalization_enabled: bool = True
    teacher_reviewed: bool = True

class ExamplePair(BaseModel):
    strong_example: str
    weak_counterexample: str
    comparison_point: str

class PlaybookActivityGenerated(BaseModel):
    _non_empty_list_fields = ('explanation_sequence', 'teacher_questions', 'expected_student_responses', 'common_misconceptions', 'understanding_checks')
    activity_order: int = Field(..., ge=1)
    title: str = Field(..., min_length=2)
    duration_minutes: int = Field(..., ge=1, le=180)
    learning_objective: str = Field(..., min_length=2)
    priority_level: Literal["essential", "core", "optional_extension"] = "core"
    teaching_rationale: str = Field(..., min_length=5)
    teacher_instructions: str = Field(..., min_length=10)
    explanation_sequence: list[str] = Field(...)
    examples_counterexamples: list[ExamplePair] = Field(default_factory=list)
    teacher_questions: list[str] = Field(...)
    expected_student_responses: list[str] = Field(...)
    common_misconceptions: list[str] = Field(...)
    understanding_checks: list[str] = Field(...)
    scaffolding_struggling: str = Field(..., min_length=3)
    extension_fast_learners: str = Field(..., min_length=3)
    transition_next: str = Field(..., min_length=3)

class PlaybookGenerationOutput(BaseModel):
    _non_empty_list_fields = ('activities',)
    pedagogical_approach: str = Field(..., min_length=5)
    transition_buffer_minutes: int = Field(default=5, ge=0, le=30)
    activities: list[PlaybookActivityGenerated] = Field(...)

class GeneratePlaybookRequest(BaseModel):
    model_name: str = "qwen3:8b"
    think: bool = False
    force_regenerate: bool = False

class UpdatePlaybookActivityRequest(BaseModel):
    title: str | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=180)
    learning_objective: str | None = None
    priority_level: Literal["essential", "core", "optional_extension"] | None = None
    teaching_rationale: str | None = None
    teacher_instructions: str | None = None
    explanation_sequence: list[str] | None = None
    examples_counterexamples: list[dict[str, str]] | None = None
    teacher_questions: list[str] | None = None
    expected_student_responses: list[str] | None = None
    common_misconceptions: list[str] | None = None
    understanding_checks: list[str] | None = None
    scaffolding_struggling: str | None = None
    extension_fast_learners: str | None = None
    transition_next: str | None = None

class RegenerateSectionRequest(BaseModel):
    teacher_instruction: str = ""
    difficulty_adjustment: Literal["easier", "same", "harder"] = "same"
    model_name: str = "qwen3:8b"
    think: bool = False

class HandoutExerciseGenerated(BaseModel):
    exercise_order: int = Field(..., ge=1)
    linked_activity_order: int = Field(default=1, ge=1)
    exercise_type: str = Field(..., min_length=2)
    progression_stage: Literal["scaffolded", "guided", "independent"] = "scaffolded"
    title: str = Field(..., min_length=2)
    learning_objective: str = Field(..., min_length=2)
    difficulty_level: str = "Band 6.0 -> 7.0"
    student_instructions: str = Field(..., min_length=5)
    content_items: list[str] = Field(...)
    expected_response_format: str = Field(..., min_length=2)
    working_space_lines: int = Field(default=4, ge=1, le=30)

    def __init__(self, **data: Any) -> None:
        if "exercise_type" in data and isinstance(data["exercise_type"], str):
            norm = data["exercise_type"].strip().lower().replace(" ", "_").replace("-", "_")
            mapping = {
                "grammar_correction": "error_correction",
                "error_identification": "error_correction",
                "vocabulary": "vocabulary_collocation",
                "collocation": "vocabulary_collocation",
                "writing_task": "independent_writing",
                "paragraph_writing": "guided_paragraph",
                "speaking": "speaking_prompt",
                "reflection": "self_assessment",
            }
            norm = mapping.get(norm, norm)
            if norm not in SUPPORTED_EXERCISE_TYPES:
                raise ValueError(f"Unsupported exercise_type '{data['exercise_type']}'. Allowed: {sorted(SUPPORTED_EXERCISE_TYPES)}")
            data["exercise_type"] = norm
        super().__init__(**data)

class HandoutGenerationOutput(BaseModel):
    _non_empty_list_fields = ('exercises', 'self_assessment_checklist')
    title: str = Field(..., min_length=2)
    intro_instructions: str = Field(..., min_length=5)
    exercises: list[HandoutExerciseGenerated] = Field(...)
    self_assessment_checklist: list[str] = Field(...)
    exit_ticket_prompt: str = Field(..., min_length=3)
    homework_assignment: str = Field(..., min_length=3)

class ExerciseAnswerKeyGenerated(BaseModel):
    _non_empty_list_fields = ('correct_answers', 'common_student_mistakes')
    exercise_order: int = Field(..., ge=1)
    exercise_title: str = Field(..., min_length=2)
    correct_answers: list[str] = Field(...)
    explanation_why: str = Field(..., min_length=5)
    alternative_acceptable_answers: list[str] = Field(default_factory=list)
    common_student_mistakes: list[str] = Field(...)
    suggested_feedback_remediation: str = Field(..., min_length=5)
    open_ended_marking_criteria: list[str] = Field(default_factory=list)
    illustrative_sample_response: str = ""
    is_illustrative_llm_example: bool = True

class TeacherGuideGenerationOutput(BaseModel):
    _non_empty_list_fields = ('answer_keys', 'objective_evaluation_checklist')
    answer_keys: list[ExerciseAnswerKeyGenerated] = Field(...)
    objective_evaluation_checklist: list[str] = Field(...)

class GenerateMaterialsRequest(BaseModel):
    personalization_enabled: bool | None = None
    custom_personalization_override: str = ""
    model_name: str = "qwen3:8b"
    think: bool = False
    force_regenerate: bool = False

class UpdateHandoutExerciseRequest(BaseModel):
    title: str | None = None
    learning_objective: str | None = None
    difficulty_level: str | None = None
    progression_stage: Literal["scaffolded", "guided", "independent"] | None = None
    student_instructions: str | None = None
    content_items: list[str] | None = None
    expected_response_format: str | None = None
    working_space_lines: int | None = Field(default=None, ge=1, le=30)

class UpdateTeacherAnswerKeyRequest(BaseModel):
    exercise_order: int
    correct_answers: list[str] | None = None
    explanation_why: str | None = None
    alternative_acceptable_answers: list[str] | None = None
    common_student_mistakes: list[str] | None = None
    suggested_feedback_remediation: str | None = None
    open_ended_marking_criteria: list[str] | None = None
    illustrative_sample_response: str | None = None

class SessionStateUpdateRequest(BaseModel):
    current_activity_id: str | None = None
    elapsed_minutes: int | None = Field(default=None, ge=0, le=300)
    remaining_minutes: int | None = Field(default=None, ge=0, le=300)
    activity_states: dict[str, Literal["not_started", "in_progress", "completed"]] | None = None
    objective_statuses: dict[str, Literal["achieved", "partially_achieved", "not_yet_achieved"]] | None = None
    new_live_note: str | None = None

class CompanionActionRequest(BaseModel):
    scenario: Literal[
        "student_stuck",
        "understands_quickly",
        "answers_incorrectly",
        "behind_schedule",
        "alternative_explanation",
        "adjust_exercise_difficulty",
        "followup_questions",
    ]
    activity_id: str | None = None
    student_response_or_context: str = ""
    remaining_minutes: int | None = None
    difficulty_direction: Literal["easier", "harder"] = "easier"
    model_name: str = "qwen3:8b"
    think: bool = False

class CompanionAdaptationOutput(BaseModel):
    scenario: str
    diagnosis_or_rationale: str = Field(..., min_length=5)
    teacher_script_or_explanation: str = Field(..., min_length=5)
    guided_diagnostic_question: str = Field(..., min_length=5)
    adapted_exercise_or_task: str = Field(..., min_length=5)
    schedule_adjustment_plan: list[str] = Field(default_factory=list)

class CreatePostLessonReviewRequest(BaseModel):
    session_id: str | None = None
    completed_activities: list[str] = Field(default_factory=list)
    objectives_achieved: dict[str, Literal["achieved", "partially_achieved", "not_achieved"]] = Field(default_factory=dict)
    student_difficulties: list[str] = Field(default_factory=list)
    exercises_too_easy: list[str] = Field(default_factory=list)
    exercises_too_hard: list[str] = Field(default_factory=list)
    teacher_confirmed_notes: str = Field(..., min_length=3)
    homework_assigned: str = ""
    recommended_next_focus: str = ""
    confirm_update_student_history: bool = False
    model_name: str = "qwen3:8b"
    think: bool = False

class PostLessonAIHypothesesOutput(BaseModel):
    _non_empty_list_fields = ('hypothesized_root_causes', 'proposed_next_steps')
    concise_lesson_summary: str = Field(..., min_length=10)
    hypothesized_root_causes: list[str] = Field(...)
    proposed_next_steps: list[str] = Field(...)
    suggested_homework_refinement: str = ""
