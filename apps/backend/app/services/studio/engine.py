from __future__ import annotations
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.db.database import db_session
from app.prompts.teaching_studio_v1 import (
    ANALYZER_JSON_SCHEMA,
    COMPANION_JSON_SCHEMA,
    HANDOUT_EXERCISE_SCHEMA,
    HANDOUT_JSON_SCHEMA,
    PLAYBOOK_ACTIVITY_SCHEMA,
    PLAYBOOK_JSON_SCHEMA,
    PROMPT_VERSION_ANALYZER,
    PROMPT_VERSION_COMPANION,
    PROMPT_VERSION_HANDOUT,
    PROMPT_VERSION_PLAYBOOK,
    PROMPT_VERSION_REVIEW,
    PROMPT_VERSION_TEACHER_GUIDE,
    REVIEW_JSON_SCHEMA,
    TEACHER_GUIDE_JSON_SCHEMA,
    build_companion_action_prompts,
    build_handout_prompts,
    build_lesson_analyzer_prompts,
    build_playbook_prompts,
    build_post_lesson_review_prompts,
    build_single_activity_regen_prompts,
    build_single_exercise_regen_prompts,
    build_teacher_guide_prompts,
)
from app.repositories.store import CopilotRepository
from app.schemas.studio import (
    AnalyzeLessonPlanRequest,
    CompanionActionRequest,
    CompanionAdaptationOutput,
    CreatePostLessonReviewRequest,
    GenerateMaterialsRequest,
    GeneratePlaybookRequest,
    HandoutExerciseGenerated,
    HandoutGenerationOutput,
    LessonPlanAnalysisOutput,
    PlaybookActivityGenerated,
    PlaybookGenerationOutput,
    PostLessonAIHypothesesOutput,
    RegenerateSectionRequest,
    SessionStateUpdateRequest,
    TeacherGuideGenerationOutput,
    UpdateHandoutExerciseRequest,
    UpdateLessonPlanReviewRequest,
    UpdatePlaybookActivityRequest,
    UpdateTeacherAnswerKeyRequest,
)
from app.services.inference.ollama_provider import OllamaProvider
from app.services.studio.material_library import LocalMaterialLibrary

T = TypeVar("T", bound=BaseModel)

FORBIDDEN_STUDENT_LEAK_PATTERNS = [
    r"(?i)\banswer\s*key\s*:.*$",
    r"(?i)\bcorrect\s*answer\s*:.*$",
    r"(?i)\[answer\s*:.*?\]",
    r"(?i)\bteacher[-_\s]*only\s*note\s*:.*$",
    r"(?i)\bexaminer\s*marking\s*note\s*:.*$",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_playbook_durations(
    activities: list[dict[str, Any]],
    lesson_duration_minutes: int,
    transition_buffer_minutes: int = 5,
) -> dict[str, Any]:
    """Deterministic validation of activity durations against total lesson duration."""
    if not activities:
        raise ValueError("Teaching Playbook must contain at least 1 activity.")

    activity_minutes = 0
    for idx, act in enumerate(activities, start=1):
        dur = int(act.get("duration_minutes", 0))
        if dur < 1:
            raise ValueError(f"Activity #{idx} ('{act.get('title')}') has invalid duration: {dur} min.")
        activity_minutes += dur

    buffer_min = max(0, int(transition_buffer_minutes))
    total_allocated = activity_minutes + buffer_min
    overflow = max(0, total_allocated - lesson_duration_minutes)
    exceeds = overflow > 0

    recommendations: list[str] = []
    if exceeds:
        remaining_to_cut = overflow
        # First target optional_extension activities
        for act in reversed(activities):
            if remaining_to_cut <= 0:
                break
            prio = act.get("priority_level", "core")
            dur = int(act.get("duration_minutes", 0))
            if prio == "optional_extension":
                cut = min(dur, remaining_to_cut)
                remaining_to_cut -= cut
                if cut == dur:
                    recommendations.append(
                        f"Remove optional extension activity '{act['title']}' ({dur} min) or assign as homework."
                    )
                else:
                    recommendations.append(
                        f"Shorten optional extension '{act['title']}' by {cut} min (from {dur} to {dur - cut} min)."
                    )
        # Next target core activities while preserving essential objectives
        for act in reversed(activities):
            if remaining_to_cut <= 0:
                break
            prio = act.get("priority_level", "core")
            dur = int(act.get("duration_minutes", 0))
            if prio == "core" and dur > 8:
                max_trim = max(0, dur - 8)
                cut = min(max_trim, remaining_to_cut)
                if cut > 0:
                    remaining_to_cut -= cut
                    recommendations.append(
                        f"Trim core activity '{act['title']}' by {cut} min (from {dur} to {dur - cut} min) while keeping its key concept check."
                    )
        if remaining_to_cut > 0:
            recommendations.append(
                f"Reduce transition buffer or trim {remaining_to_cut} min across teacher explanation segments while preserving essential objective checks."
            )

    return {
        "lesson_duration_minutes": lesson_duration_minutes,
        "activities_sum_minutes": activity_minutes,
        "transition_buffer_minutes": buffer_min,
        "total_allocated_minutes": total_allocated,
        "exceeds_available_time": exceeds,
        "overflow_minutes": overflow,
        "shortening_recommendations": recommendations,
    }


def sanitize_and_verify_student_exercise(ex: dict[str, Any]) -> dict[str, Any]:
    """Ensure zero answer key or teacher-only explanation leakage in student-facing exercise fields."""
    cleaned = dict(ex)
    instr = str(cleaned.get("student_instructions", ""))
    for pat in FORBIDDEN_STUDENT_LEAK_PATTERNS:
        if re.search(pat, instr):
            instr = re.sub(pat, "", instr).strip()
    cleaned["student_instructions"] = instr

    clean_items: list[str] = []
    for item in cleaned.get("content_items", []):
        txt = str(item)
        for pat in FORBIDDEN_STUDENT_LEAK_PATTERNS:
            txt = re.sub(pat, "", txt).strip()
        if txt:
            clean_items.append(txt)

    if not clean_items:
        raise ValueError(
            f"Exercise '{cleaned.get('title')}' has no valid student-facing items after answer-leakage filtering."
        )
    cleaned["content_items"] = clean_items
    return cleaned


def recalculate_behind_schedule_plan(
    activities: list[dict[str, Any]],
    remaining_minutes: int,
) -> list[str]:
    """Deterministic time recalculation when a live lesson is running behind schedule."""
    pending = [a for a in activities if a.get("status") != "completed"]
    if not pending:
        return ["All planned activities are already completed. Use remaining time for Q&A and wrap-up."]

    planned_rem = sum(int(a.get("duration_minutes", 0)) for a in pending)
    plan_steps: list[str] = [
        f"Remaining clock time: {remaining_minutes} min vs. {planned_rem} min originally planned for {len(pending)} remaining activities."
    ]
    budget = max(5, remaining_minutes - 3)  # Keep 3 min for final understanding check & homework
    for a in pending:
        prio = a.get("priority_level", "core")
        orig = int(a.get("duration_minutes", 10))
        if prio == "optional_extension" and planned_rem > remaining_minutes:
            plan_steps.append(f"[SKIP / ASSIGN AS HOMEWORK] '{a['title']}' ({orig} min, optional_extension).")
        elif prio == "essential":
            alloc = min(orig, max(5, int(budget * 0.55)))
            budget = max(2, budget - alloc)
            plan_steps.append(
                f"[PRESERVE ESSENTIAL OBJECTIVE] '{a['title']}': allocate {alloc} min (focus on core demonstration + student check)."
            )
        else:
            alloc = min(orig, max(4, budget))
            budget = max(0, budget - alloc)
            plan_steps.append(f"[CONDENSE CORE PRACTICE] '{a['title']}': condense from {orig} min to {alloc} min.")
    plan_steps.append("[FINAL 3 MIN] Run quick exit-ticket understanding check on the primary learning objective.")
    return plan_steps


class TeachingStudioService:
    """Orchestrates Lesson Plan Analysis, Playbook, Handout, Teacher Guide, Companion, and Post-Lesson Review."""

    def __init__(
        self,
        db_path: Path | None = None,
        llm_provider: OllamaProvider | None = None,
    ) -> None:
        self.db_path = db_path
        from app.db.studio_migrations import migrate_teaching_studio_db
        migrate_teaching_studio_db(db_path)
        self.repo = CopilotRepository(db_path=db_path)
        self.library = LocalMaterialLibrary(db_path=db_path)
        self.llm = llm_provider or OllamaProvider()

    def _compute_cache_key(
        self,
        task_name: str,
        model_name: str,
        prompt_version: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        raw = f"{task_name}|{model_name}|{prompt_version}|{system_prompt}|{user_prompt}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _call_llm_validated(
        self,
        task_name: str,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        pydantic_cls: Type[T],
        model_name: str = "qwen3:8b",
        prompt_version: str = "v1",
        think: bool = False,
        force_regenerate: bool = False,
        max_retries: int = 2,
    ) -> tuple[T, dict[str, Any]]:
        cache_key = self._compute_cache_key(task_name, model_name, prompt_version, system_prompt, user_prompt)
        if not force_regenerate:
            with db_session(self.db_path) as conn:
                cached = conn.execute(
                    "SELECT response_json FROM studio_inference_cache WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
                if cached:
                    try:
                        parsed_obj = pydantic_cls.model_validate_json(cached["response_json"])
                        return parsed_obj, {"cached": True, "elapsed_seconds": 0.0}
                    except Exception:
                        pass

        last_err: Exception | None = None
        curr_user_prompt = user_prompt
        for attempt in range(max_retries + 1):
            try:
                raw_dict, metrics = self.llm.generate_structured(
                    system_prompt=system_prompt,
                    user_prompt=curr_user_prompt,
                    schema=json_schema,
                    model=model_name,
                    think=think,
                )
                validated = pydantic_cls.model_validate(raw_dict)
                with db_session(self.db_path) as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO studio_inference_cache (
                            cache_key, task_name, model_name, prompt_version, response_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            cache_key,
                            task_name,
                            model_name,
                            prompt_version,
                            validated.model_dump_json(),
                            now_iso(),
                        ),
                    )
                metrics["cached"] = False
                metrics["attempts"] = attempt + 1
                return validated, metrics
            except (ValidationError, ValueError, KeyError, json.JSONDecodeError) as exc:
                last_err = exc
                curr_user_prompt = (
                    f"{user_prompt}\n\n"
                    f"[VALIDATION ERROR ON PREVIOUS ATTEMPT #{attempt + 1}]:\n{exc}\n"
                    f"Please fix the JSON structure and satisfy all required fields and constraints."
                )
        raise ValueError(
            f"Mô hình AI cục bộ ({model_name}) trả về dữ liệu không hợp lệ sau {max_retries + 1} lần thử cho tác vụ '{task_name}': {last_err}"
        )

    def build_student_personalization_context(
        self,
        student_id: str | None,
        personalization_enabled: bool = True,
        custom_override: str = "",
    ) -> dict[str, Any]:
        """Gather authentic student history from SQLite without fabricating any facts."""
        if not personalization_enabled:
            return {
                "personalization_applied": False,
                "student_id": student_id,
                "summary": "Cá nhân hóa đã được giáo viên tắt (sử dụng bài tập tiêu chuẩn cho mục tiêu bài học).",
                "recurring_errors": [],
                "previous_submissions_count": 0,
                "previous_lesson_focuses": [],
            }
        if not student_id:
            return {
                "personalization_applied": False,
                "student_id": None,
                "summary": "Bài học chung (General Lesson) — không chọn học viên cụ thể.",
                "recurring_errors": [],
                "previous_submissions_count": 0,
                "previous_lesson_focuses": [],
            }

        try:
            prog = self.repo.get_student_progress(student_id)
        except ValueError:
            return {
                "personalization_applied": False,
                "student_id": student_id,
                "summary": "Không tìm thấy hồ sơ học viên trong cơ sở dữ liệu.",
                "recurring_errors": [],
                "previous_submissions_count": 0,
                "previous_lesson_focuses": [],
            }

        stu = prog["student"]
        subs = prog.get("submissions_history", [])
        errs = prog.get("recurring_errors", [])

        with db_session(self.db_path) as conn:
            prev_reviews = conn.execute(
                """
                SELECT lr.recommended_next_focus, lr.teacher_confirmed_notes, lp.title
                FROM lesson_reviews lr
                JOIN lesson_plans lp ON lp.id = lr.lesson_plan_id
                WHERE lr.student_id = ?
                ORDER BY lr.created_at DESC LIMIT 3
                """,
                (student_id,),
            ).fetchall()

        prev_focuses = [
            f"{r['title']}: {r['recommended_next_focus'] or r['teacher_confirmed_notes']}"
            for r in prev_reviews
            if r["recommended_next_focus"] or r["teacher_confirmed_notes"]
        ]

        top_err_codes = [f"{e['code']} ({e['error_count']} lần - {e['description']})" for e in errs[:4]]
        if top_err_codes or subs or prev_focuses or custom_override.strip():
            parts = [
                f"Học viên: {stu['name']} (Hiện tại: Band {stu.get('current_overall') or 'chưa chốt'} -> Mục tiêu: Band {stu.get('target_overall') or '7.0'})."
            ]
            if top_err_codes:
                parts.append(f"Lỗi lặp lại nhiều nhất từ {len(subs)} bài nộp: {'; '.join(top_err_codes)}.")
            else:
                parts.append(f"Chưa có thống kê lỗi lặp lại (số bài nộp: {len(subs)}).")
            if prev_focuses:
                parts.append(f"Ghi chú buổi học trước: {' | '.join(prev_focuses)}.")
            if stu.get("notes"):
                parts.append(f"Ghi chú hồ sơ: {stu['notes']}.")
            if custom_override.strip():
                parts.append(f"Chỉ dẫn ưu tiên của Giáo viên: {custom_override.strip()}.")
            summary_str = " ".join(parts)
            applied = True
        else:
            summary_str = (
                f"Học viên {stu['name']} chưa có bài nộp hoặc lịch sử lỗi trong hệ thống. "
                f"Chỉ điều chỉnh độ khó theo mức Band hiện tại ({stu.get('current_overall') or 'N/A'}) -> Mục tiêu ({stu.get('target_overall') or '7.0'})."
            )
            applied = True

        return {
            "personalization_applied": applied,
            "student_id": student_id,
            "student_name": stu["name"],
            "current_overall": stu.get("current_overall"),
            "target_overall": stu.get("target_overall"),
            "target_writing": stu.get("target_writing"),
            "target_speaking": stu.get("target_speaking"),
            "previous_submissions_count": len(subs),
            "recurring_errors": errs[:5],
            "previous_lesson_focuses": prev_focuses,
            "custom_override": custom_override.strip(),
            "summary": summary_str,
        }

    def analyze_lesson_plan(self, req: AnalyzeLessonPlanRequest) -> dict[str, Any]:
        student_ctx = None
        if req.student_id:
            try:
                student_ctx = self.repo.get_student_progress(req.student_id)
            except ValueError:
                student_ctx = None

        lib_sources = self.library.get_materials_by_ids(req.source_material_ids)
        req_dict = req.model_dump()
        if student_ctx:
            stu = student_ctx["student"]
            if req_dict["student_current_band"] is None:
                req_dict["student_current_band"] = stu.get("current_overall")
            if req_dict["student_target_band"] is None:
                req_dict["student_target_band"] = stu.get("target_overall")

        sys_prompt, usr_prompt = build_lesson_analyzer_prompts(req_dict, student_ctx, lib_sources)
        analyzed, metrics = self._call_llm_validated(
            task_name="lesson_analyzer",
            system_prompt=sys_prompt,
            user_prompt=usr_prompt,
            json_schema=ANALYZER_JSON_SCHEMA,
            pydantic_cls=LessonPlanAnalysisOutput,
            model_name=req.model_name,
            prompt_version=PROMPT_VERSION_ANALYZER,
            think=req.think,
            force_regenerate=req.force_regenerate,
        )

        pers_ctx = self.build_student_personalization_context(
            req.student_id,
            personalization_enabled=req.personalization_enabled,
        )

        plan_id = str(uuid.uuid4())
        legacy_id = None
        ts = now_iso()
        final_title = req.title.strip() or analyzed.title

        with db_session(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO lesson_plans (
                    id, student_id, legacy_lesson_id, title, skill, task_type, duration_minutes,
                    student_current_band, student_target_band, raw_input_text, teacher_notes,
                    source_material_ids_json, objectives_json, prerequisites_json, resources_json,
                    expected_difficulties_json, assessment_criteria_json, explicit_vs_assumed_json,
                    personalization_enabled, personalization_summary_json, version, model_name,
                    prompt_version, generation_status, teacher_reviewed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 'analyzed', 0, ?, ?)
                """,
                (
                    plan_id,
                    req.student_id,
                    legacy_id,
                    final_title,
                    analyzed.skill,
                    analyzed.task_type,
                    analyzed.duration_minutes,
                    analyzed.student_current_band if analyzed.student_current_band is not None else req_dict["student_current_band"],
                    analyzed.student_target_band if analyzed.student_target_band is not None else req_dict["student_target_band"],
                    req.raw_lesson_plan,
                    req.teacher_notes,
                    json.dumps(req.source_material_ids, ensure_ascii=False),
                    json.dumps(analyzed.learning_objectives, ensure_ascii=False),
                    json.dumps(analyzed.prerequisite_knowledge, ensure_ascii=False),
                    json.dumps(analyzed.available_resources, ensure_ascii=False),
                    json.dumps(analyzed.expected_difficulties, ensure_ascii=False),
                    json.dumps(analyzed.assessment_criteria, ensure_ascii=False),
                    json.dumps([x.model_dump() for x in analyzed.explicit_vs_assumed], ensure_ascii=False),
                    1 if req.personalization_enabled else 0,
                    json.dumps(pers_ctx, ensure_ascii=False),
                    req.model_name,
                    PROMPT_VERSION_ANALYZER,
                    ts,
                    ts,
                ),
            )
            for idx, act in enumerate(analyzed.planned_activities, start=1):
                conn.execute(
                    """
                    INSERT INTO lesson_activities (
                        id, lesson_plan_id, activity_order, title, duration_minutes,
                        learning_objective, priority_level, is_assumed, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'not_started', ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        plan_id,
                        idx,
                        act.title,
                        act.duration_minutes,
                        act.learning_objective,
                        act.priority_level,
                        1 if act.is_assumed else 0,
                        ts,
                        ts,
                    ),
                )

        result = self.get_lesson_plan_full(plan_id)
        result["metrics"] = metrics
        return result

    def update_lesson_plan_review(self, plan_id: str, req: UpdateLessonPlanReviewRequest) -> dict[str, Any]:
        existing = self.get_lesson_plan_full(plan_id)
        if not existing:
            raise ValueError("Không tìm thấy Lesson Plan.")

        pers_ctx = self.build_student_personalization_context(
            req.student_id,
            personalization_enabled=req.personalization_enabled,
        )
        ts = now_iso()

        with db_session(self.db_path) as conn:
            conn.execute(
                """
                UPDATE lesson_plans
                SET title = ?, skill = ?, task_type = ?, duration_minutes = ?,
                    student_id = ?, student_current_band = ?, student_target_band = ?,
                    objectives_json = ?, prerequisites_json = ?, resources_json = ?,
                    expected_difficulties_json = ?, assessment_criteria_json = ?,
                    teacher_notes = ?, personalization_enabled = ?, personalization_summary_json = ?,
                    version = version + 1, teacher_reviewed = ?, reviewed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    req.title,
                    req.skill,
                    req.task_type,
                    req.duration_minutes,
                    req.student_id,
                    req.student_current_band,
                    req.student_target_band,
                    json.dumps(req.learning_objectives, ensure_ascii=False),
                    json.dumps(req.prerequisite_knowledge, ensure_ascii=False),
                    json.dumps(req.available_resources, ensure_ascii=False),
                    json.dumps(req.expected_difficulties, ensure_ascii=False),
                    json.dumps(req.assessment_criteria, ensure_ascii=False),
                    req.teacher_notes,
                    1 if req.personalization_enabled else 0,
                    json.dumps(pers_ctx, ensure_ascii=False),
                    1 if req.teacher_reviewed else 0,
                    ts if req.teacher_reviewed else None,
                    ts,
                    plan_id,
                ),
            )
            
            conn.execute("DELETE FROM lesson_activities WHERE lesson_plan_id = ? AND playbook_id IS NULL", (plan_id,))
            for idx, act in enumerate(req.planned_activities, start=1):
                conn.execute(
                    """
                    INSERT INTO lesson_activities (
                        id, lesson_plan_id, activity_order, title, duration_minutes,
                        learning_objective, priority_level, is_assumed, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'not_started', ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        plan_id,
                        idx,
                        act.title,
                        act.duration_minutes,
                        act.learning_objective,
                        act.priority_level,
                        1 if act.is_assumed else 0,
                        ts,
                        ts,
                    ),
                )
        return self.get_lesson_plan_full(plan_id)

    def generate_playbook(self, plan_id: str, req: GeneratePlaybookRequest) -> dict[str, Any]:
        plan = self.get_lesson_plan_full(plan_id)
        if not plan:
            raise ValueError("Không tìm thấy Lesson Plan.")

        student_ctx = None
        if plan.get("student_id"):
            try:
                student_ctx = self.repo.get_student_progress(plan["student_id"])
            except ValueError:
                student_ctx = None

        lib_sources = self.library.get_materials_by_ids(plan.get("source_material_ids", []))
        sys_prompt, usr_prompt = build_playbook_prompts(
            lesson_plan=plan,
            activities=plan.get("activities", []),
            student_context=student_ctx,
            library_sources=lib_sources,
        )
        generated, metrics = self._call_llm_validated(
            task_name="playbook_generator",
            system_prompt=sys_prompt,
            user_prompt=usr_prompt,
            json_schema=PLAYBOOK_JSON_SCHEMA,
            pydantic_cls=PlaybookGenerationOutput,
            model_name=req.model_name,
            prompt_version=PROMPT_VERSION_PLAYBOOK,
            think=req.think,
            force_regenerate=req.force_regenerate,
        )

        act_dicts = [a.model_dump() for a in generated.activities]
        dur_val = validate_playbook_durations(
            activities=act_dicts,
            lesson_duration_minutes=plan["duration_minutes"],
            transition_buffer_minutes=generated.transition_buffer_minutes,
        )

        playbook_id = str(uuid.uuid4())
        ts = now_iso()
        with db_session(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO teaching_playbooks (
                    id, lesson_plan_id, version, pedagogical_approach, total_allocated_minutes,
                    transition_buffer_minutes, duration_validation_json, time_shortening_recommendations_json,
                    model_name, prompt_version, generation_status, teacher_reviewed, created_at, updated_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, 'completed', 0, ?, ?)
                """,
                (
                    playbook_id,
                    plan_id,
                    generated.pedagogical_approach,
                    dur_val["total_allocated_minutes"],
                    generated.transition_buffer_minutes,
                    json.dumps(dur_val, ensure_ascii=False),
                    json.dumps(dur_val["shortening_recommendations"], ensure_ascii=False),
                    req.model_name,
                    PROMPT_VERSION_PLAYBOOK,
                    ts,
                    ts,
                ),
            )
            conn.execute("DELETE FROM lesson_activities WHERE lesson_plan_id = ?", (plan_id,))
            for idx, act in enumerate(generated.activities, start=1):
                conn.execute(
                    """
                    INSERT INTO lesson_activities (
                        id, lesson_plan_id, playbook_id, activity_order, title, duration_minutes,
                        learning_objective, priority_level, teaching_rationale, teacher_instructions,
                        explanation_sequence_json, examples_counterexamples_json, teacher_questions_json,
                        expected_student_responses_json, common_misconceptions_json, understanding_checks_json,
                        scaffolding_struggling, extension_fast_learners, transition_next, is_assumed,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'not_started', ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        plan_id,
                        playbook_id,
                        idx,
                        act.title,
                        act.duration_minutes,
                        act.learning_objective,
                        act.priority_level,
                        act.teaching_rationale,
                        act.teacher_instructions,
                        json.dumps(act.explanation_sequence, ensure_ascii=False),
                        json.dumps([e.model_dump() for e in act.examples_counterexamples], ensure_ascii=False),
                        json.dumps(act.teacher_questions, ensure_ascii=False),
                        json.dumps(act.expected_student_responses, ensure_ascii=False),
                        json.dumps(act.common_misconceptions, ensure_ascii=False),
                        json.dumps(act.understanding_checks, ensure_ascii=False),
                        act.scaffolding_struggling,
                        act.extension_fast_learners,
                        act.transition_next,
                        ts,
                        ts,
                    ),
                )
            conn.execute(
                "UPDATE lesson_plans SET generation_status = 'playbook_ready', updated_at = ? WHERE id = ?",
                (ts, plan_id),
            )

        out = self.get_lesson_plan_full(plan_id)
        out["metrics"] = metrics
        return out

    def update_playbook_activity(
        self,
        activity_id: str,
        req: UpdatePlaybookActivityRequest,
    ) -> dict[str, Any]:
        with db_session(self.db_path) as conn:
            row = conn.execute("SELECT * FROM lesson_activities WHERE id = ?", (activity_id,)).fetchone()
            if not row:
                raise ValueError("Không tìm thấy hoạt động (activity_id).")
            curr = dict(row)
            plan_id = curr["lesson_plan_id"]
            playbook_id = curr["playbook_id"]
            ts = now_iso()

            conn.execute(
                """
                UPDATE lesson_activities
                SET title = ?, duration_minutes = ?, learning_objective = ?, priority_level = ?,
                    teaching_rationale = ?, teacher_instructions = ?, explanation_sequence_json = ?,
                    examples_counterexamples_json = ?, teacher_questions_json = ?,
                    expected_student_responses_json = ?, common_misconceptions_json = ?,
                    understanding_checks_json = ?, scaffolding_struggling = ?,
                    extension_fast_learners = ?, transition_next = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    req.title if req.title is not None else curr["title"],
                    req.duration_minutes if req.duration_minutes is not None else curr["duration_minutes"],
                    req.learning_objective if req.learning_objective is not None else curr["learning_objective"],
                    req.priority_level if req.priority_level is not None else curr["priority_level"],
                    req.teaching_rationale if req.teaching_rationale is not None else curr["teaching_rationale"],
                    req.teacher_instructions if req.teacher_instructions is not None else curr["teacher_instructions"],
                    json.dumps(req.explanation_sequence, ensure_ascii=False)
                    if req.explanation_sequence is not None
                    else curr["explanation_sequence_json"],
                    json.dumps(req.examples_counterexamples, ensure_ascii=False)
                    if req.examples_counterexamples is not None
                    else curr["examples_counterexamples_json"],
                    json.dumps(req.teacher_questions, ensure_ascii=False)
                    if req.teacher_questions is not None
                    else curr["teacher_questions_json"],
                    json.dumps(req.expected_student_responses, ensure_ascii=False)
                    if req.expected_student_responses is not None
                    else curr["expected_student_responses_json"],
                    json.dumps(req.common_misconceptions, ensure_ascii=False)
                    if req.common_misconceptions is not None
                    else curr["common_misconceptions_json"],
                    json.dumps(req.understanding_checks, ensure_ascii=False)
                    if req.understanding_checks is not None
                    else curr["understanding_checks_json"],
                    req.scaffolding_struggling if req.scaffolding_struggling is not None else curr["scaffolding_struggling"],
                    req.extension_fast_learners if req.extension_fast_learners is not None else curr["extension_fast_learners"],
                    req.transition_next if req.transition_next is not None else curr["transition_next"],
                    ts,
                    activity_id,
                ),
            )
            self._recompute_playbook_duration_in_tx(conn, plan_id, playbook_id)
        return self.get_lesson_plan_full(plan_id)

    def regenerate_single_activity(
        self,
        activity_id: str,
        req: RegenerateSectionRequest,
    ) -> dict[str, Any]:
        with db_session(self.db_path) as conn:
            row = conn.execute("SELECT * FROM lesson_activities WHERE id = ?", (activity_id,)).fetchone()
            if not row:
                raise ValueError("Không tìm thấy activity_id để tạo lại.")
            act_dict = dict(row)
            plan_id = act_dict["lesson_plan_id"]
            playbook_id = act_dict["playbook_id"]

        plan = self.get_lesson_plan_full(plan_id)
        sys_prompt, usr_prompt = build_single_activity_regen_prompts(plan, act_dict, req.teacher_instruction)
        regenerated, _ = self._call_llm_validated(
            task_name="single_activity_regen",
            system_prompt=sys_prompt,
            user_prompt=usr_prompt,
            json_schema=PLAYBOOK_ACTIVITY_SCHEMA,
            pydantic_cls=PlaybookActivityGenerated,
            model_name=req.model_name,
            prompt_version=PROMPT_VERSION_PLAYBOOK,
            think=req.think,
            force_regenerate=True,
        )

        ts = now_iso()
        with db_session(self.db_path) as conn:
            conn.execute(
                """
                UPDATE lesson_activities
                SET title = ?, duration_minutes = ?, learning_objective = ?, priority_level = ?,
                    teaching_rationale = ?, teacher_instructions = ?, explanation_sequence_json = ?,
                    examples_counterexamples_json = ?, teacher_questions_json = ?,
                    expected_student_responses_json = ?, common_misconceptions_json = ?,
                    understanding_checks_json = ?, scaffolding_struggling = ?,
                    extension_fast_learners = ?, transition_next = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    regenerated.title,
                    regenerated.duration_minutes,
                    regenerated.learning_objective,
                    regenerated.priority_level,
                    regenerated.teaching_rationale,
                    regenerated.teacher_instructions,
                    json.dumps(regenerated.explanation_sequence, ensure_ascii=False),
                    json.dumps([e.model_dump() for e in regenerated.examples_counterexamples], ensure_ascii=False),
                    json.dumps(regenerated.teacher_questions, ensure_ascii=False),
                    json.dumps(regenerated.expected_student_responses, ensure_ascii=False),
                    json.dumps(regenerated.common_misconceptions, ensure_ascii=False),
                    json.dumps(regenerated.understanding_checks, ensure_ascii=False),
                    regenerated.scaffolding_struggling,
                    regenerated.extension_fast_learners,
                    regenerated.transition_next,
                    ts,
                    activity_id,
                ),
            )
            self._recompute_playbook_duration_in_tx(conn, plan_id, playbook_id)
        return self.get_lesson_plan_full(plan_id)

    def _recompute_playbook_duration_in_tx(self, conn: Any, plan_id: str, playbook_id: str | None) -> None:
        if not playbook_id:
            return
        plan_row = conn.execute("SELECT duration_minutes FROM lesson_plans WHERE id = ?", (plan_id,)).fetchone()
        pb_row = conn.execute("SELECT transition_buffer_minutes FROM teaching_playbooks WHERE id = ?", (playbook_id,)).fetchone()
        acts = conn.execute(
            "SELECT * FROM lesson_activities WHERE lesson_plan_id = ? ORDER BY activity_order ASC",
            (plan_id,),
        ).fetchall()
        if not plan_row or not pb_row or not acts:
            return
        dur_val = validate_playbook_durations(
            activities=[dict(a) for a in acts],
            lesson_duration_minutes=plan_row["duration_minutes"],
            transition_buffer_minutes=pb_row["transition_buffer_minutes"],
        )
        conn.execute(
            """
            UPDATE teaching_playbooks
            SET total_allocated_minutes = ?, duration_validation_json = ?,
                time_shortening_recommendations_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                dur_val["total_allocated_minutes"],
                json.dumps(dur_val, ensure_ascii=False),
                json.dumps(dur_val["shortening_recommendations"], ensure_ascii=False),
                now_iso(),
                playbook_id,
            ),
        )

    def generate_handout_and_teacher_guide(
        self,
        plan_id: str,
        req: GenerateMaterialsRequest,
    ) -> dict[str, Any]:
        plan = self.get_lesson_plan_full(plan_id)
        if not plan:
            raise ValueError("Không tìm thấy Lesson Plan.")
        activities = plan.get("activities", [])
        if not activities:
            raise ValueError("Cần có danh sách hoạt động (Activities) trước khi tạo Handout.")

        pers_enabled = (
            req.personalization_enabled
            if req.personalization_enabled is not None
            else bool(plan.get("personalization_enabled", 1))
        )
        pers_info = self.build_student_personalization_context(
            student_id=plan.get("student_id"),
            personalization_enabled=pers_enabled,
            custom_override=req.custom_personalization_override,
        )

        # 1. Generate Student Handout
        h_sys, h_usr = build_handout_prompts(plan, activities, pers_info)
        handout_gen, h_metrics = self._call_llm_validated(
            task_name="student_handout_generator",
            system_prompt=h_sys,
            user_prompt=h_usr,
            json_schema=HANDOUT_JSON_SCHEMA,
            pydantic_cls=HandoutGenerationOutput,
            model_name=req.model_name,
            prompt_version=PROMPT_VERSION_HANDOUT,
            think=req.think,
            force_regenerate=req.force_regenerate,
        )

        # Sanitize and verify student exercises (zero answer leakage + valid activity mapping)
        activity_by_order = {a["activity_order"]: a["id"] for a in activities}
        default_act_id = activities[0]["id"]
        sanitized_exercises: list[dict[str, Any]] = []
        for idx, ex in enumerate(handout_gen.exercises, start=1):
            ex_dict = ex.model_dump()
            ex_dict["exercise_order"] = idx
            cleaned_ex = sanitize_and_verify_student_exercise(ex_dict)
            cleaned_ex["activity_id"] = activity_by_order.get(ex.linked_activity_order, default_act_id)
            sanitized_exercises.append(cleaned_ex)

        # 2. Generate Separate Teacher Guide & Answer Key
        tg_sys, tg_usr = build_teacher_guide_prompts(
            lesson_plan=plan,
            handout={"title": handout_gen.title},
            exercises=sanitized_exercises,
        )
        tg_gen, tg_metrics = self._call_llm_validated(
            task_name="teacher_guide_generator",
            system_prompt=tg_sys,
            user_prompt=tg_usr,
            json_schema=TEACHER_GUIDE_JSON_SCHEMA,
            pydantic_cls=TeacherGuideGenerationOutput,
            model_name=req.model_name,
            prompt_version=PROMPT_VERSION_TEACHER_GUIDE,
            think=req.think,
            force_regenerate=req.force_regenerate,
        )

        # Ensure every exercise has a corresponding answer key and LLM examples are explicitly labeled
        key_by_order = {k.exercise_order: k.model_dump() for k in tg_gen.answer_keys}
        complete_keys: list[dict[str, Any]] = []
        for ex in sanitized_exercises:
            ord_num = ex["exercise_order"]
            k = key_by_order.get(ord_num)
            if not k:
                k = {
                    "exercise_order": ord_num,
                    "exercise_title": ex["title"],
                    "correct_answers": ["Xem hướng dẫn chấm chi tiết của giáo viên theo tiêu chí bài học."],
                    "explanation_why": f"Đáp án bám sát mục tiêu: {ex['learning_objective']}.",
                    "alternative_acceptable_answers": ["Chấp nhận các cách diễn đạt học thuật tương đương đúng ngữ pháp."],
                    "common_student_mistakes": ["Lặp từ vựng hoặc thiếu liên kết câu."],
                    "suggested_feedback_remediation": "Yêu cầu học viên đối chiếu lại với cấu trúc mẫu trong Playbook.",
                    "open_ended_marking_criteria": [ex["learning_objective"]],
                    "illustrative_sample_response": "",
                    "is_illustrative_llm_example": True,
                }
            else:
                k["is_illustrative_llm_example"] = True
            complete_keys.append(k)

        handout_id = str(uuid.uuid4())
        tg_id = str(uuid.uuid4())
        playbook_id = plan.get("playbook", {}).get("id") if plan.get("playbook") else None
        ts = now_iso()

        with db_session(self.db_path) as conn:
            conn.execute("DELETE FROM teacher_guides WHERE lesson_plan_id = ?", (plan_id,))
            conn.execute("DELETE FROM handouts WHERE lesson_plan_id = ?", (plan_id,))

            conn.execute(
                """
                INSERT INTO handouts (
                    id, lesson_plan_id, playbook_id, student_id, version, title, intro_instructions,
                    personalization_applied, personalization_summary, personalization_sources_json,
                    self_assessment_checklist_json, exit_ticket_prompt, homework_assignment,
                    model_name, prompt_version, generation_status, teacher_reviewed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', 0, ?, ?)
                """,
                (
                    handout_id,
                    plan_id,
                    playbook_id,
                    plan.get("student_id"),
                    handout_gen.title,
                    handout_gen.intro_instructions,
                    1 if pers_info["personalization_applied"] else 0,
                    pers_info["summary"],
                    json.dumps(pers_info, ensure_ascii=False),
                    json.dumps(handout_gen.self_assessment_checklist, ensure_ascii=False),
                    handout_gen.exit_ticket_prompt,
                    handout_gen.homework_assignment,
                    req.model_name,
                    PROMPT_VERSION_HANDOUT,
                    ts,
                    ts,
                ),
            )

            for ex in sanitized_exercises:
                conn.execute(
                    """
                    INSERT INTO handout_exercises (
                        id, handout_id, activity_id, exercise_order, exercise_type,
                        progression_stage, title, learning_objective, difficulty_level,
                        student_instructions, content_items_json, expected_response_format,
                        working_space_lines, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        handout_id,
                        ex["activity_id"],
                        ex["exercise_order"],
                        ex["exercise_type"],
                        ex["progression_stage"],
                        ex["title"],
                        ex["learning_objective"],
                        ex["difficulty_level"],
                        ex["student_instructions"],
                        json.dumps(ex["content_items"], ensure_ascii=False),
                        ex["expected_response_format"],
                        ex["working_space_lines"],
                        ts,
                        ts,
                    ),
                )

            conn.execute(
                """
                INSERT INTO teacher_guides (
                    id, lesson_plan_id, handout_id, version, answer_keys_json,
                    objective_evaluation_checklist_json, model_name, prompt_version,
                    generation_status, teacher_reviewed, created_at, updated_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, 'completed', 0, ?, ?)
                """,
                (
                    tg_id,
                    plan_id,
                    handout_id,
                    json.dumps(complete_keys, ensure_ascii=False),
                    json.dumps(tg_gen.objective_evaluation_checklist, ensure_ascii=False),
                    req.model_name,
                    PROMPT_VERSION_TEACHER_GUIDE,
                    ts,
                    ts,
                ),
            )

            conn.execute(
                "UPDATE lesson_plans SET generation_status = 'materials_ready', updated_at = ? WHERE id = ?",
                (ts, plan_id),
            )

        out = self.get_lesson_plan_full(plan_id)
        out["metrics"] = {"handout": h_metrics, "teacher_guide": tg_metrics}
        return out

    def update_handout_exercise(
        self,
        exercise_id: str,
        req: UpdateHandoutExerciseRequest,
    ) -> dict[str, Any]:
        with db_session(self.db_path) as conn:
            row = conn.execute("SELECT * FROM handout_exercises WHERE id = ?", (exercise_id,)).fetchone()
            if not row:
                raise ValueError("Không tìm thấy bài tập (exercise_id).")
            curr = dict(row)
            handout_row = conn.execute("SELECT lesson_plan_id FROM handouts WHERE id = ?", (curr["handout_id"],)).fetchone()
            plan_id = handout_row["lesson_plan_id"]

            candidate = {
                "title": req.title if req.title is not None else curr["title"],
                "learning_objective": req.learning_objective if req.learning_objective is not None else curr["learning_objective"],
                "difficulty_level": req.difficulty_level if req.difficulty_level is not None else curr["difficulty_level"],
                "progression_stage": req.progression_stage if req.progression_stage is not None else curr["progression_stage"],
                "student_instructions": req.student_instructions if req.student_instructions is not None else curr["student_instructions"],
                "content_items": req.content_items if req.content_items is not None else json.loads(curr["content_items_json"]),
                "expected_response_format": req.expected_response_format if req.expected_response_format is not None else curr["expected_response_format"],
                "working_space_lines": req.working_space_lines if req.working_space_lines is not None else curr["working_space_lines"],
            }
            cleaned = sanitize_and_verify_student_exercise(candidate)
            conn.execute(
                """
                UPDATE handout_exercises
                SET title = ?, learning_objective = ?, difficulty_level = ?, progression_stage = ?,
                    student_instructions = ?, content_items_json = ?, expected_response_format = ?,
                    working_space_lines = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    cleaned["title"],
                    cleaned["learning_objective"],
                    cleaned["difficulty_level"],
                    cleaned["progression_stage"],
                    cleaned["student_instructions"],
                    json.dumps(cleaned["content_items"], ensure_ascii=False),
                    cleaned["expected_response_format"],
                    cleaned["working_space_lines"],
                    now_iso(),
                    exercise_id,
                ),
            )
        return self.get_lesson_plan_full(plan_id)

    def regenerate_single_exercise(
        self,
        exercise_id: str,
        req: RegenerateSectionRequest,
    ) -> dict[str, Any]:
        with db_session(self.db_path) as conn:
            row = conn.execute("SELECT * FROM handout_exercises WHERE id = ?", (exercise_id,)).fetchone()
            if not row:
                raise ValueError("Không tìm thấy bài tập (exercise_id) để tạo lại.")
            curr = dict(row)
            curr["content_items"] = json.loads(curr["content_items_json"])
            handout_row = conn.execute("SELECT lesson_plan_id FROM handouts WHERE id = ?", (curr["handout_id"],)).fetchone()
            plan_id = handout_row["lesson_plan_id"]

        plan = self.get_lesson_plan_full(plan_id)
        sys_prompt, usr_prompt = build_single_exercise_regen_prompts(
            lesson_plan=plan,
            exercise=curr,
            teacher_instruction=req.teacher_instruction,
            difficulty_adjustment=req.difficulty_adjustment,
        )
        regen_ex, _ = self._call_llm_validated(
            task_name="single_exercise_regen",
            system_prompt=sys_prompt,
            user_prompt=usr_prompt,
            json_schema=HANDOUT_EXERCISE_SCHEMA,
            pydantic_cls=HandoutExerciseGenerated,
            model_name=req.model_name,
            prompt_version=PROMPT_VERSION_HANDOUT,
            think=req.think,
            force_regenerate=True,
        )
        cleaned = sanitize_and_verify_student_exercise(regen_ex.model_dump())

        with db_session(self.db_path) as conn:
            conn.execute(
                """
                UPDATE handout_exercises
                SET exercise_type = ?, progression_stage = ?, title = ?, learning_objective = ?,
                    difficulty_level = ?, student_instructions = ?, content_items_json = ?,
                    expected_response_format = ?, working_space_lines = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    cleaned["exercise_type"],
                    cleaned["progression_stage"],
                    cleaned["title"],
                    cleaned["learning_objective"],
                    cleaned["difficulty_level"],
                    cleaned["student_instructions"],
                    json.dumps(cleaned["content_items"], ensure_ascii=False),
                    cleaned["expected_response_format"],
                    cleaned["working_space_lines"],
                    now_iso(),
                    exercise_id,
                ),
            )
        return self.get_lesson_plan_full(plan_id)

    def update_teacher_answer_key(
        self,
        guide_id: str,
        req: UpdateTeacherAnswerKeyRequest,
    ) -> dict[str, Any]:
        with db_session(self.db_path) as conn:
            row = conn.execute("SELECT * FROM teacher_guides WHERE id = ?", (guide_id,)).fetchone()
            if not row:
                raise ValueError("Không tìm thấy Teacher Guide.")
            curr = dict(row)
            plan_id = curr["lesson_plan_id"]
            keys = json.loads(curr["answer_keys_json"])
            for k in keys:
                if int(k.get("exercise_order", 0)) == req.exercise_order:
                    if req.correct_answers is not None:
                        k["correct_answers"] = req.correct_answers
                    if req.explanation_why is not None:
                        k["explanation_why"] = req.explanation_why
                    if req.alternative_acceptable_answers is not None:
                        k["alternative_acceptable_answers"] = req.alternative_acceptable_answers
                    if req.common_student_mistakes is not None:
                        k["common_student_mistakes"] = req.common_student_mistakes
                    if req.suggested_feedback_remediation is not None:
                        k["suggested_feedback_remediation"] = req.suggested_feedback_remediation
                    if req.open_ended_marking_criteria is not None:
                        k["open_ended_marking_criteria"] = req.open_ended_marking_criteria
                    if req.illustrative_sample_response is not None:
                        k["illustrative_sample_response"] = req.illustrative_sample_response
                    k["is_illustrative_llm_example"] = True
            conn.execute(
                "UPDATE teacher_guides SET answer_keys_json = ?, teacher_reviewed = 1, updated_at = ? WHERE id = ?",
                (json.dumps(keys, ensure_ascii=False), now_iso(), guide_id),
            )
        return self.get_lesson_plan_full(plan_id)

    def start_or_get_session(self, plan_id: str) -> dict[str, Any]:
        plan = self.get_lesson_plan_full(plan_id)
        if not plan:
            raise ValueError("Không tìm thấy Lesson Plan.")
        with db_session(self.db_path) as conn:
            existing = conn.execute(
                "SELECT * FROM teaching_sessions WHERE lesson_plan_id = ? ORDER BY started_at DESC LIMIT 1",
                (plan_id,),
            ).fetchone()
            if existing:
                return self._format_session_row(dict(existing))

            sess_id = str(uuid.uuid4())
            ts = now_iso()
            acts = plan.get("activities", [])
            first_act_id = acts[0]["id"] if acts else None
            act_states = {a["id"]: a.get("status", "not_started") for a in acts}
            obj_states = {obj: "not_yet_achieved" for obj in plan.get("learning_objectives", [])}
            pb_id = plan["playbook"]["id"] if plan.get("playbook") else None
            ho_id = plan["handout"]["id"] if plan.get("handout") else None

            conn.execute(
                """
                INSERT INTO teaching_sessions (
                    id, lesson_plan_id, playbook_id, handout_id, student_id, current_activity_id,
                    elapsed_minutes, remaining_minutes, activity_states_json, objective_statuses_json,
                    teacher_live_notes_json, companion_adaptations_json, status, started_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, '[]', '[]', 'in_progress', ?, ?)
                """,
                (
                    sess_id,
                    plan_id,
                    pb_id,
                    ho_id,
                    plan.get("student_id"),
                    first_act_id,
                    plan["duration_minutes"],
                    json.dumps(act_states, ensure_ascii=False),
                    json.dumps(obj_states, ensure_ascii=False),
                    ts,
                    ts,
                ),
            )
            row = conn.execute("SELECT * FROM teaching_sessions WHERE id = ?", (sess_id,)).fetchone()
            return self._format_session_row(dict(row))

    def update_session_state(self, session_id: str, req: SessionStateUpdateRequest) -> dict[str, Any]:
        with db_session(self.db_path) as conn:
            row = conn.execute("SELECT * FROM teaching_sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                raise ValueError("Không tìm thấy phiên dạy học (session_id).")
            curr = dict(row)
            act_states = json.loads(curr["activity_states_json"])
            if req.activity_states:
                act_states.update(req.activity_states)
                for aid, st in req.activity_states.items():
                    conn.execute("UPDATE lesson_activities SET status = ?, updated_at = ? WHERE id = ?", (st, now_iso(), aid))

            obj_states = json.loads(curr["objective_statuses_json"])
            if req.objective_statuses:
                obj_states.update(req.objective_statuses)

            notes = json.loads(curr["teacher_live_notes_json"])
            if req.new_live_note and req.new_live_note.strip():
                notes.append({"timestamp": now_iso(), "note": req.new_live_note.strip()})

            conn.execute(
                """
                UPDATE teaching_sessions
                SET current_activity_id = ?, elapsed_minutes = ?, remaining_minutes = ?,
                    activity_states_json = ?, objective_statuses_json = ?, teacher_live_notes_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    req.current_activity_id if req.current_activity_id is not None else curr["current_activity_id"],
                    req.elapsed_minutes if req.elapsed_minutes is not None else curr["elapsed_minutes"],
                    req.remaining_minutes if req.remaining_minutes is not None else curr["remaining_minutes"],
                    json.dumps(act_states, ensure_ascii=False),
                    json.dumps(obj_states, ensure_ascii=False),
                    json.dumps(notes, ensure_ascii=False),
                    now_iso(),
                    session_id,
                ),
            )
            updated = conn.execute("SELECT * FROM teaching_sessions WHERE id = ?", (session_id,)).fetchone()
            return self._format_session_row(dict(updated))

    def run_companion_action(self, session_id: str, req: CompanionActionRequest) -> dict[str, Any]:
        with db_session(self.db_path) as conn:
            row = conn.execute("SELECT * FROM teaching_sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                raise ValueError("Không tìm thấy phiên dạy học (session_id).")
            sess = self._format_session_row(dict(row))

        plan = self.get_lesson_plan_full(sess["lesson_plan_id"])
        acts = plan.get("activities", [])
        target_act_id = req.activity_id or sess.get("current_activity_id")
        current_act = next((a for a in acts if a["id"] == target_act_id), acts[0] if acts else None)

        rem_min = req.remaining_minutes if req.remaining_minutes is not None else sess["remaining_minutes"]
        deterministic_schedule = recalculate_behind_schedule_plan(acts, rem_min)

        req_dict = req.model_dump()
        req_dict["remaining_minutes"] = rem_min
        sys_prompt, usr_prompt = build_companion_action_prompts(plan, current_act, acts, req_dict)
        adaptation, metrics = self._call_llm_validated(
            task_name=f"companion_{req.scenario}",
            system_prompt=sys_prompt,
            user_prompt=usr_prompt,
            json_schema=COMPANION_JSON_SCHEMA,
            pydantic_cls=CompanionAdaptationOutput,
            model_name=req.model_name,
            prompt_version=PROMPT_VERSION_COMPANION,
            think=req.think,
            force_regenerate=True,
        )

        adap_dict = adaptation.model_dump()
        if req.scenario == "behind_schedule" or not adap_dict.get("schedule_adjustment_plan"):
            adap_dict["schedule_adjustment_plan"] = deterministic_schedule
        adap_dict["timestamp"] = now_iso()
        adap_dict["metrics"] = metrics

        with db_session(self.db_path) as conn:
            row = conn.execute("SELECT companion_adaptations_json FROM teaching_sessions WHERE id = ?", (session_id,)).fetchone()
            history = json.loads(row["companion_adaptations_json"]) if row else []
            history.insert(0, adap_dict)
            conn.execute(
                "UPDATE teaching_sessions SET companion_adaptations_json = ?, remaining_minutes = ?, updated_at = ? WHERE id = ?",
                (json.dumps(history, ensure_ascii=False), rem_min, now_iso(), session_id),
            )
        return adap_dict

    def create_post_lesson_review(self, plan_id: str, req: CreatePostLessonReviewRequest) -> dict[str, Any]:
        plan = self.get_lesson_plan_full(plan_id)
        if not plan:
            raise ValueError("Không tìm thấy Lesson Plan.")

        req_dict = req.model_dump()
        sys_prompt, usr_prompt = build_post_lesson_review_prompts(plan, req_dict)
        ai_hypotheses, metrics = self._call_llm_validated(
            task_name="post_lesson_review",
            system_prompt=sys_prompt,
            user_prompt=usr_prompt,
            json_schema=REVIEW_JSON_SCHEMA,
            pydantic_cls=PostLessonAIHypothesesOutput,
            model_name=req.model_name,
            prompt_version=PROMPT_VERSION_REVIEW,
            think=req.think,
            force_regenerate=True,
        )

        review_id = str(uuid.uuid4())
        ts = now_iso()
        student_id = plan.get("student_id")
        confirmed_flag = 1 if (req.confirm_update_student_history and student_id) else 0

        with db_session(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO lesson_reviews (
                    id, session_id, lesson_plan_id, student_id, completed_activities_json,
                    objectives_achieved_json, student_difficulties_json, exercises_too_easy_json,
                    exercises_too_hard_json, teacher_confirmed_notes, homework_assigned,
                    recommended_next_focus, ai_hypotheses_summary_json,
                    teacher_confirmed_history_update, confirmed_at, model_name, prompt_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    req.session_id,
                    plan_id,
                    student_id,
                    json.dumps(req.completed_activities, ensure_ascii=False),
                    json.dumps(req.objectives_achieved, ensure_ascii=False),
                    json.dumps(req.student_difficulties, ensure_ascii=False),
                    json.dumps(req.exercises_too_easy, ensure_ascii=False),
                    json.dumps(req.exercises_too_hard, ensure_ascii=False),
                    req.teacher_confirmed_notes,
                    req.homework_assigned,
                    req.recommended_next_focus,
                    ai_hypotheses.model_dump_json(),
                    confirmed_flag,
                    ts if confirmed_flag else None,
                    req.model_name,
                    PROMPT_VERSION_REVIEW,
                    ts,
                ),
            )
            if confirmed_flag and student_id:
                self._append_confirmed_review_to_student_notes_in_tx(
                    conn=conn,
                    student_id=student_id,
                    lesson_title=plan["title"],
                    teacher_notes=req.teacher_confirmed_notes,
                    next_focus=req.recommended_next_focus,
                    homework=req.homework_assigned,
                )
            conn.execute(
                "UPDATE lesson_plans SET generation_status = 'reviewed_post_lesson', updated_at = ? WHERE id = ?",
                (ts, plan_id),
            )

        out = self.get_lesson_review(review_id)
        out["metrics"] = metrics
        return out

    def confirm_student_history_update(self, review_id: str) -> dict[str, Any]:
        """Explicitly confirm and append teacher-confirmed lesson review outcomes to the student's learning history without touching official band scores."""
        with db_session(self.db_path) as conn:
            row = conn.execute("SELECT * FROM lesson_reviews WHERE id = ?", (review_id,)).fetchone()
            if not row:
                raise ValueError("Không tìm thấy bản Post-Lesson Review.")
            rev = dict(row)
            if not rev.get("student_id"):
                raise ValueError("Bài học này là bài chung (General Lesson), không gắn với học viên cụ thể.")
            if rev.get("teacher_confirmed_history_update") == 1:
                return self.get_lesson_review(review_id)

            plan_row = conn.execute("SELECT title FROM lesson_plans WHERE id = ?", (rev["lesson_plan_id"],)).fetchone()
            lesson_title = plan_row["title"] if plan_row else "IELTS Lesson"
            self._append_confirmed_review_to_student_notes_in_tx(
                conn=conn,
                student_id=rev["student_id"],
                lesson_title=lesson_title,
                teacher_notes=rev["teacher_confirmed_notes"],
                next_focus=rev["recommended_next_focus"],
                homework=rev["homework_assigned"],
            )
            conn.execute(
                "UPDATE lesson_reviews SET teacher_confirmed_history_update = 1, confirmed_at = ? WHERE id = ?",
                (now_iso(), review_id),
            )
        return self.get_lesson_review(review_id)

    def _append_confirmed_review_to_student_notes_in_tx(
        self,
        conn: Any,
        student_id: str,
        lesson_title: str,
        teacher_notes: str,
        next_focus: str,
        homework: str,
    ) -> None:
        stu = conn.execute("SELECT notes FROM students WHERE id = ?", (student_id,)).fetchone()
        if not stu:
            return
        date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entry_parts = [f"[{date_tag} · {lesson_title}] GV nhận xét: {teacher_notes.strip()}"]
        if next_focus.strip():
            entry_parts.append(f"Trọng tâm buổi tới: {next_focus.strip()}")
        if homework.strip():
            entry_parts.append(f"BTVN: {homework.strip()}")
        new_entry = " | ".join(entry_parts)
        existing_notes = (stu["notes"] or "").strip()
        combined = f"{existing_notes}\n{new_entry}".strip() if existing_notes else new_entry
        # Strictly update ONLY notes and updated_at — NEVER overwrite current_overall or official assessments!
        conn.execute(
            "UPDATE students SET notes = ?, updated_at = ? WHERE id = ?",
            (combined, now_iso(), student_id),
        )

    def get_lesson_review(self, review_id: str) -> dict[str, Any]:
        with db_session(self.db_path) as conn:
            row = conn.execute("SELECT * FROM lesson_reviews WHERE id = ?", (review_id,)).fetchone()
            if not row:
                raise ValueError("Không tìm thấy Post-Lesson Review.")
            d = dict(row)
            d["completed_activities"] = json.loads(d["completed_activities_json"])
            d["objectives_achieved"] = json.loads(d["objectives_achieved_json"])
            d["student_difficulties"] = json.loads(d["student_difficulties_json"])
            d["exercises_too_easy"] = json.loads(d["exercises_too_easy_json"])
            d["exercises_too_hard"] = json.loads(d["exercises_too_hard_json"])
            d["ai_hypotheses_summary"] = json.loads(d["ai_hypotheses_summary_json"])
            return d

    def _format_session_row(self, d: dict[str, Any]) -> dict[str, Any]:
        d["activity_states"] = json.loads(d.get("activity_states_json") or "{}")
        d["objective_statuses"] = json.loads(d.get("objective_statuses_json") or "{}")
        d["teacher_live_notes"] = json.loads(d.get("teacher_live_notes_json") or "[]")
        d["companion_adaptations"] = json.loads(d.get("companion_adaptations_json") or "[]")
        return d

    def list_lesson_plans(self, student_id: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT lp.*, s.name AS student_name
            FROM lesson_plans lp
            LEFT JOIN students s ON s.id = lp.student_id
            WHERE 1=1
        """
        params: list[Any] = []
        if student_id:
            query += " AND lp.student_id = ?"
            params.append(student_id)
        query += " ORDER BY lp.updated_at DESC"
        with db_session(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
            out = []
            for r in rows:
                item = dict(r)
                item["learning_objectives"] = json.loads(item.get("objectives_json") or "[]")
                out.append(item)
            return out

    def get_lesson_plan_full(self, plan_id: str) -> dict[str, Any] | None:
        with db_session(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT lp.*, s.name AS student_name
                FROM lesson_plans lp
                LEFT JOIN students s ON s.id = lp.student_id
                WHERE lp.id = ?
                """,
                (plan_id,),
            ).fetchone()
            if not row:
                return None
            plan = dict(row)
            plan["learning_objectives"] = json.loads(plan["objectives_json"])
            plan["prerequisite_knowledge"] = json.loads(plan["prerequisites_json"])
            plan["available_resources"] = json.loads(plan["resources_json"])
            plan["expected_difficulties"] = json.loads(plan["expected_difficulties_json"])
            plan["assessment_criteria"] = json.loads(plan["assessment_criteria_json"])
            plan["explicit_vs_assumed"] = json.loads(plan["explicit_vs_assumed_json"])
            plan["source_material_ids"] = json.loads(plan["source_material_ids_json"])
            plan["personalization_summary_obj"] = json.loads(plan["personalization_summary_json"])

            acts = conn.execute(
                "SELECT * FROM lesson_activities WHERE lesson_plan_id = ? ORDER BY activity_order ASC",
                (plan_id,),
            ).fetchall()
            act_list = []
            for a in acts:
                ad = dict(a)
                ad["explanation_sequence"] = json.loads(ad["explanation_sequence_json"])
                ad["examples_counterexamples"] = json.loads(ad["examples_counterexamples_json"])
                ad["teacher_questions"] = json.loads(ad["teacher_questions_json"])
                ad["expected_student_responses"] = json.loads(ad["expected_student_responses_json"])
                ad["common_misconceptions"] = json.loads(ad["common_misconceptions_json"])
                ad["understanding_checks"] = json.loads(ad["understanding_checks_json"])
                ad["is_assumed"] = bool(ad["is_assumed"])
                act_list.append(ad)
            plan["activities"] = act_list

            pb = conn.execute(
                "SELECT * FROM teaching_playbooks WHERE lesson_plan_id = ? ORDER BY created_at DESC LIMIT 1",
                (plan_id,),
            ).fetchone()
            if pb:
                pbd = dict(pb)
                pbd["duration_validation"] = json.loads(pbd["duration_validation_json"])
                pbd["time_shortening_recommendations"] = json.loads(pbd["time_shortening_recommendations_json"])
                plan["playbook"] = pbd
            else:
                plan["playbook"] = None

            ho = conn.execute(
                "SELECT * FROM handouts WHERE lesson_plan_id = ? ORDER BY created_at DESC LIMIT 1",
                (plan_id,),
            ).fetchone()
            if ho:
                hod = dict(ho)
                hod["personalization_sources"] = json.loads(hod["personalization_sources_json"])
                hod["self_assessment_checklist"] = json.loads(hod["self_assessment_checklist_json"])
                exs = conn.execute(
                    "SELECT * FROM handout_exercises WHERE handout_id = ? ORDER BY exercise_order ASC",
                    (hod["id"],),
                ).fetchall()
                ex_list = []
                for ex in exs:
                    exd = dict(ex)
                    exd["content_items"] = json.loads(exd["content_items_json"])
                    ex_list.append(exd)
                hod["exercises"] = ex_list
                plan["handout"] = hod
            else:
                plan["handout"] = None

            tg = conn.execute(
                "SELECT * FROM teacher_guides WHERE lesson_plan_id = ? ORDER BY created_at DESC LIMIT 1",
                (plan_id,),
            ).fetchone()
            if tg:
                tgd = dict(tg)
                tgd["answer_keys"] = json.loads(tgd["answer_keys_json"])
                tgd["objective_evaluation_checklist"] = json.loads(tgd["objective_evaluation_checklist_json"])
                plan["teacher_guide"] = tgd
            else:
                plan["teacher_guide"] = None

            sess = conn.execute(
                "SELECT * FROM teaching_sessions WHERE lesson_plan_id = ? ORDER BY started_at DESC LIMIT 1",
                (plan_id,),
            ).fetchone()
            plan["session"] = self._format_session_row(dict(sess)) if sess else None

            revs = conn.execute(
                "SELECT * FROM lesson_reviews WHERE lesson_plan_id = ? ORDER BY created_at DESC",
                (plan_id,),
            ).fetchall()
            plan["reviews"] = [self.get_lesson_review(r["id"]) for r in revs]
            return plan

    def delete_lesson_plan(self, plan_id: str) -> bool:
        with db_session(self.db_path) as conn:
            cur = conn.execute("DELETE FROM lesson_plans WHERE id = ?", (plan_id,))
            return cur.rowcount > 0
