PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS students (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    target_overall REAL,
    target_writing REAL,
    target_speaking REAL,
    current_overall REAL,
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'completed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    lesson_date TEXT NOT NULL,
    topic TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    homework TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (student_id)
        REFERENCES students(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    lesson_id TEXT,
    skill TEXT NOT NULL
        CHECK (skill IN ('writing', 'speaking')),
    task_type TEXT NOT NULL,
    prompt_text TEXT NOT NULL DEFAULT '',
    response_text TEXT NOT NULL DEFAULT '',
    source_audio_path TEXT,
    transcript_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN (
            'draft', 'processing', 'reviewed', 'failed'
        )),
    created_at TEXT NOT NULL,
    FOREIGN KEY (student_id)
        REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (lesson_id)
        REFERENCES lessons(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS assessments (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL,
    rubric_version TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL DEFAULT '',
    task_response REAL,
    coherence REAL,
    lexical REAL,
    grammar REAL,
    estimated_overall REAL,
    feedback_json TEXT NOT NULL,
    teacher_overall REAL,
    teacher_feedback TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (submission_id)
        REFERENCES submissions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS error_tags (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS submission_errors (
    submission_id TEXT NOT NULL,
    error_tag_id TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    correction TEXT NOT NULL DEFAULT '',
    explanation TEXT NOT NULL DEFAULT '',
    confidence REAL,
    PRIMARY KEY (submission_id, error_tag_id, evidence),
    FOREIGN KEY (submission_id)
        REFERENCES submissions(id) ON DELETE CASCADE,
    FOREIGN KEY (error_tag_id)
        REFERENCES error_tags(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lessons_student_date
    ON lessons(student_id, lesson_date);

CREATE INDEX IF NOT EXISTS idx_submissions_student_skill
    ON submissions(student_id, skill, created_at);

CREATE INDEX IF NOT EXISTS idx_assessments_submission
    ON assessments(submission_id);
