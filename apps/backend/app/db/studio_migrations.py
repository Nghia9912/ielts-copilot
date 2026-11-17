from __future__ import annotations
import sqlite3
from pathlib import Path
from app.db.database import db_session

STUDIO_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS material_library_sources (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    file_format TEXT NOT NULL,
    skill TEXT DEFAULT '',
    sections_json TEXT NOT NULL DEFAULT '[]',
    raw_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lesson_plans (
    id TEXT PRIMARY KEY,
    student_id TEXT REFERENCES students(id) ON DELETE SET NULL,
    legacy_lesson_id TEXT REFERENCES lessons(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    skill TEXT NOT NULL,
    task_type TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    student_current_band REAL,
    student_target_band REAL,
    raw_input_text TEXT DEFAULT '',
    teacher_notes TEXT DEFAULT '',
    source_material_ids_json TEXT DEFAULT '[]',
    objectives_json TEXT NOT NULL DEFAULT '[]',
    prerequisites_json TEXT NOT NULL DEFAULT '[]',
    resources_json TEXT NOT NULL DEFAULT '[]',
    expected_difficulties_json TEXT NOT NULL DEFAULT '[]',
    assessment_criteria_json TEXT NOT NULL DEFAULT '[]',
    explicit_vs_assumed_json TEXT NOT NULL DEFAULT '{}',
    personalization_enabled INTEGER NOT NULL DEFAULT 1,
    personalization_summary_json TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    model_name TEXT NOT NULL DEFAULT 'qwen3:8b',
    prompt_version TEXT NOT NULL DEFAULT 'studio-analyzer-v1',
    generation_status TEXT NOT NULL DEFAULT 'analyzed',
    teacher_reviewed INTEGER NOT NULL DEFAULT 0,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teaching_playbooks (
    id TEXT PRIMARY KEY,
    lesson_plan_id TEXT NOT NULL REFERENCES lesson_plans(id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1,
    pedagogical_approach TEXT NOT NULL DEFAULT '',
    total_allocated_minutes INTEGER NOT NULL DEFAULT 0,
    transition_buffer_minutes INTEGER NOT NULL DEFAULT 5,
    duration_validation_json TEXT NOT NULL DEFAULT '{}',
    time_shortening_recommendations_json TEXT NOT NULL DEFAULT '[]',
    model_name TEXT NOT NULL DEFAULT 'qwen3:8b',
    prompt_version TEXT NOT NULL DEFAULT 'studio-playbook-v1',
    generation_status TEXT NOT NULL DEFAULT 'completed',
    teacher_reviewed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lesson_activities (
    id TEXT PRIMARY KEY,
    lesson_plan_id TEXT NOT NULL REFERENCES lesson_plans(id) ON DELETE CASCADE,
    playbook_id TEXT REFERENCES teaching_playbooks(id) ON DELETE CASCADE,
    activity_order INTEGER NOT NULL,
    title TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    learning_objective TEXT NOT NULL,
    priority_level TEXT NOT NULL DEFAULT 'core',
    teaching_rationale TEXT DEFAULT '',
    teacher_instructions TEXT DEFAULT '',
    explanation_sequence_json TEXT NOT NULL DEFAULT '[]',
    examples_counterexamples_json TEXT NOT NULL DEFAULT '[]',
    teacher_questions_json TEXT NOT NULL DEFAULT '[]',
    expected_student_responses_json TEXT NOT NULL DEFAULT '[]',
    common_misconceptions_json TEXT NOT NULL DEFAULT '[]',
    understanding_checks_json TEXT NOT NULL DEFAULT '[]',
    scaffolding_struggling TEXT DEFAULT '',
    extension_fast_learners TEXT DEFAULT '',
    transition_next TEXT DEFAULT '',
    is_assumed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'not_started',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS handouts (
    id TEXT PRIMARY KEY,
    lesson_plan_id TEXT NOT NULL REFERENCES lesson_plans(id) ON DELETE CASCADE,
    playbook_id TEXT REFERENCES teaching_playbooks(id) ON DELETE SET NULL,
    student_id TEXT REFERENCES students(id) ON DELETE SET NULL,
    version INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    intro_instructions TEXT DEFAULT '',
    personalization_applied INTEGER NOT NULL DEFAULT 0,
    personalization_summary TEXT DEFAULT '',
    personalization_sources_json TEXT NOT NULL DEFAULT '{}',
    self_assessment_checklist_json TEXT NOT NULL DEFAULT '[]',
    exit_ticket_prompt TEXT DEFAULT '',
    homework_assignment TEXT DEFAULT '',
    model_name TEXT NOT NULL DEFAULT 'qwen3:8b',
    prompt_version TEXT NOT NULL DEFAULT 'studio-handout-v1',
    generation_status TEXT NOT NULL DEFAULT 'completed',
    teacher_reviewed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS handout_exercises (
    id TEXT PRIMARY KEY,
    handout_id TEXT NOT NULL REFERENCES handouts(id) ON DELETE CASCADE,
    activity_id TEXT REFERENCES lesson_activities(id) ON DELETE SET NULL,
    exercise_order INTEGER NOT NULL,
    exercise_type TEXT NOT NULL,
    progression_stage TEXT NOT NULL DEFAULT 'scaffolded',
    title TEXT NOT NULL,
    learning_objective TEXT NOT NULL,
    difficulty_level TEXT NOT NULL DEFAULT 'intermediate',
    student_instructions TEXT NOT NULL,
    content_items_json TEXT NOT NULL DEFAULT '[]',
    expected_response_format TEXT NOT NULL DEFAULT 'short_answer',
    working_space_lines INTEGER NOT NULL DEFAULT 4,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teacher_guides (
    id TEXT PRIMARY KEY,
    lesson_plan_id TEXT NOT NULL REFERENCES lesson_plans(id) ON DELETE CASCADE,
    handout_id TEXT NOT NULL REFERENCES handouts(id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1,
    answer_keys_json TEXT NOT NULL DEFAULT '[]',
    objective_evaluation_checklist_json TEXT NOT NULL DEFAULT '[]',
    model_name TEXT NOT NULL DEFAULT 'qwen3:8b',
    prompt_version TEXT NOT NULL DEFAULT 'studio-teacher-guide-v1',
    generation_status TEXT NOT NULL DEFAULT 'completed',
    teacher_reviewed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teaching_sessions (
    id TEXT PRIMARY KEY,
    lesson_plan_id TEXT NOT NULL REFERENCES lesson_plans(id) ON DELETE CASCADE,
    playbook_id TEXT REFERENCES teaching_playbooks(id) ON DELETE SET NULL,
    handout_id TEXT REFERENCES handouts(id) ON DELETE SET NULL,
    student_id TEXT REFERENCES students(id) ON DELETE SET NULL,
    current_activity_id TEXT,
    elapsed_minutes INTEGER NOT NULL DEFAULT 0,
    remaining_minutes INTEGER NOT NULL DEFAULT 60,
    activity_states_json TEXT NOT NULL DEFAULT '{}',
    objective_statuses_json TEXT NOT NULL DEFAULT '{}',
    teacher_live_notes_json TEXT NOT NULL DEFAULT '[]',
    companion_adaptations_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'in_progress',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lesson_reviews (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES teaching_sessions(id) ON DELETE SET NULL,
    lesson_plan_id TEXT NOT NULL REFERENCES lesson_plans(id) ON DELETE CASCADE,
    student_id TEXT REFERENCES students(id) ON DELETE SET NULL,
    completed_activities_json TEXT NOT NULL DEFAULT '[]',
    objectives_achieved_json TEXT NOT NULL DEFAULT '[]',
    student_difficulties_json TEXT NOT NULL DEFAULT '[]',
    exercises_too_easy_json TEXT NOT NULL DEFAULT '[]',
    exercises_too_hard_json TEXT NOT NULL DEFAULT '[]',
    teacher_confirmed_notes TEXT NOT NULL DEFAULT '',
    homework_assigned TEXT DEFAULT '',
    recommended_next_focus TEXT DEFAULT '',
    ai_hypotheses_summary_json TEXT NOT NULL DEFAULT '{}',
    teacher_confirmed_history_update INTEGER NOT NULL DEFAULT 0,
    confirmed_at TEXT,
    model_name TEXT NOT NULL DEFAULT 'qwen3:8b',
    prompt_version TEXT NOT NULL DEFAULT 'studio-review-v1',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS studio_inference_cache (
    cache_key TEXT PRIMARY KEY,
    task_name TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lesson_plans_student ON lesson_plans(student_id);
CREATE INDEX IF NOT EXISTS idx_lesson_activities_plan ON lesson_activities(lesson_plan_id);
CREATE INDEX IF NOT EXISTS idx_handouts_plan ON handouts(lesson_plan_id);
CREATE INDEX IF NOT EXISTS idx_handout_exercises_handout ON handout_exercises(handout_id);
CREATE INDEX IF NOT EXISTS idx_teacher_guides_handout ON teacher_guides(handout_id);
CREATE INDEX IF NOT EXISTS idx_teaching_sessions_plan ON teaching_sessions(lesson_plan_id);
CREATE INDEX IF NOT EXISTS idx_lesson_reviews_plan ON lesson_reviews(lesson_plan_id);
"""

def migrate_teaching_studio_db(custom_path: Path | None = None) -> None:
    """Non-destructive migration adding Teaching Studio tables and indexes to existing SQLite database."""
    with db_session(custom_path) as conn:
        conn.executescript(STUDIO_SCHEMA_SQL)
