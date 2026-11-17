#!/usr/bin/env python3
"""IELTS Copilot - Trình khởi tạo tự động Mốc 2: FastAPI Backend + SQLite 6 bảng + LLMProvider.

Chạy trực tiếp tại thư mục gốc F:\\ielts-copilot:
    .\\.venv\\Scripts\\python.exe init_backend_mvp.py

Script này sẽ:
1. Tạo toàn bộ các module chuẩn trong apps/backend/ theo đúng thiết kế Modular Monolith.
2. Khởi tạo cơ sở dữ liệu SQLite (data/ielts_copilot.db) với 6 bảng cốt lõi + seed sẵn danh mục lỗi IELTS (error_tags).
3. Tối ưu Ollama LLMProvider với chế độ `think=False` mặc định (giúp giảm thời gian chấm trên RTX 4060 từ ~85s xuống ~12-18s mà vẫn giữ 34+ tokens/s), có tùy chọn bật `think=True` khi cần phân tích sâu.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path.cwd()
BACKEND_DIR = PROJECT_ROOT / "apps" / "backend"
APP_DIR = BACKEND_DIR / "app"
DATA_DIR = PROJECT_ROOT / "data"


SCHEMA_SQL = """PRAGMA foreign_keys = ON;

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
"""


REQUIREMENTS_TXT = """fastapi>=0.115.0
uvicorn[standard]>=0.30.0
pydantic>=2.9.0
pytest>=8.3.0
httpx>=0.27.0
"""


CONFIG_PY = """from __future__ import annotations

import os
from pathlib import Path

# Xác định thư mục gốc của dự án (F:\\ielts-copilot)
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.getenv("IELTS_DB_PATH", str(DATA_DIR / "ielts_copilot.db")))
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "qwen3:8b")
BASELINE_MODEL = os.getenv("OLLAMA_BASELINE_MODEL", "gemma3:4b")
BACKEND_HOST = "127.0.0.1"  # Luôn chỉ bind vào localhost để bảo mật dữ liệu học viên
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
"""


DATABASE_PY = """from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.core.config import DB_PATH

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

DEFAULT_ERROR_TAGS = [
    ("tag-tr-underdeveloped", "TR_UNDERDEVELOPED", "task_response", "Luận điểm chưa được phát triển đầy đủ hoặc thiếu dẫn chứng"),
    ("tag-cc-cohesion", "CC_COHESION", "coherence_cohesion", "Sử dụng từ nối (cohesive devices) chưa tự nhiên hoặc thiếu liên kết câu"),
    ("tag-lr-collocation", "COLLOCATION", "lexical_resource", "Kết hợp từ (collocation) không tự nhiên trong tiếng Anh học thuật"),
    ("tag-lr-word-choice", "WORD_CHOICE", "lexical_resource", "Dùng từ chưa chính xác với ngữ cảnh hoặc sai sắc thái"),
    ("tag-lr-spelling", "SPELLING", "lexical_resource", "Lỗi chính tả"),
    ("tag-gra-article", "ARTICLE", "grammatical_range_accuracy", "Sai hoặc thiếu mạo từ (a, an, the)"),
    ("tag-gra-preposition", "PREPOSITION", "grammatical_range_accuracy", "Sai giới từ"),
    ("tag-gra-sva", "SVA", "grammatical_range_accuracy", "Lỗi hòa hợp chủ ngữ - vị ngữ (Subject-Verb Agreement)"),
    ("tag-gra-tense", "TENSE", "grammatical_range_accuracy", "Chia sai thì của động từ"),
    ("tag-gra-punctuation", "PUNCTUATION", "grammatical_range_accuracy", "Lỗi dấu câu hoặc câu ghép sai (comma splice / run-on sentence)"),
]


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    target = db_path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def db_session(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with db_session(db_path) as conn:
        conn.executescript(schema_sql)
        conn.execute("PRAGMA foreign_keys = ON;")
        for tag_id, code, category, description in DEFAULT_ERROR_TAGS:
            conn.execute(
                \"\"\"
                INSERT OR IGNORE INTO error_tags (id, code, category, description)
                VALUES (?, ?, ?, ?)
                \"\"\",
                (tag_id, code, category, description),
            )
"""


SCHEMAS_PY = """from __future__ import annotations

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


class AssessWritingRequest(BaseModel):
    model_name: str = "qwen3:8b"
    think: bool = Field(
        default=False,
        description="Bật/tắt chế độ suy luận sâu của Qwen3. Tắt (False) giúp phản hồi nhanh ~12-18s; Bật (True) mất ~60-85s.",
    )


class TeacherReviewRequest(BaseModel):
    assessment_id: str | None = None
    teacher_overall: float = Field(..., ge=0.0, le=9.0)
    teacher_feedback: str = Field(default="", max_length=10000)
    updated_feedback_json: dict[str, Any] | None = None
"""


OLLAMA_PROVIDER_PY = """from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from app.core.config import DEFAULT_MODEL, OLLAMA_BASE_URL


class OllamaProvider:
    \"\"\"Lớp giao tiếp độc lập với Ollama Local Runtime (127.0.0.1:11434).\"\"\"

    def __init__(self, base_url: str = OLLAMA_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def health_check(self) -> dict[str, Any]:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in data.get("models", [])]
                return {"ollama_online": True, "installed_models": models}
        except Exception as exc:
            return {"ollama_online": False, "installed_models": [], "error": str(exc)}

    def list_models(self) -> list[dict[str, Any]]:
        req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [
                {
                    "name": m.get("name"),
                    "size_gb": round(m.get("size", 0) / (1024**3), 2),
                    "quantization": m.get("details", {}).get("quantization_level", ""),
                    "family": m.get("details", {}).get("family", ""),
                }
                for m in data.get("models", [])
            ]

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        model: str = DEFAULT_MODEL,
        think: bool = False,
        timeout_sec: int = 180,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": schema,
            "think": think,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_ctx": 8192,
            },
        }

        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Lỗi kết nối Ollama ({self.base_url}): {exc}") from exc

        elapsed = round(time.perf_counter() - start, 2)
        content = body.get("message", {}).get("content", "{}")
        parsed = json.loads(content)

        eval_count = body.get("eval_count", 0)
        eval_dur = body.get("eval_duration", 1)
        tps = round(eval_count / (eval_dur / 1e9), 2) if eval_dur > 0 else 0.0

        metrics = {
            "elapsed_seconds": elapsed,
            "output_tokens": eval_count,
            "tokens_per_second": tps,
            "think_enabled": think,
        }
        return parsed, metrics
"""


EVALUATOR_PY = """from __future__ import annotations

import math
import re
from typing import Any

RUBRIC_VERSION = "ielts-writing-v1"

WRITING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "object",
            "properties": {
                "task_response": {
                    "type": "object",
                    "properties": {
                        "estimated_band": {"type": "number"},
                        "strengths": {"type": "array", "items": {"type": "string"}},
                        "evidence": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "quote": {"type": "string"},
                                    "error_code": {"type": "string"},
                                    "issue": {"type": "string"},
                                    "suggestion": {"type": "string"},
                                },
                                "required": ["quote", "error_code", "issue", "suggestion"],
                            },
                        },
                    },
                    "required": ["estimated_band", "strengths", "evidence"],
                },
                "coherence_cohesion": {
                    "type": "object",
                    "properties": {
                        "estimated_band": {"type": "number"},
                        "strengths": {"type": "array", "items": {"type": "string"}},
                        "evidence": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "quote": {"type": "string"},
                                    "error_code": {"type": "string"},
                                    "issue": {"type": "string"},
                                    "suggestion": {"type": "string"},
                                },
                                "required": ["quote", "error_code", "issue", "suggestion"],
                            },
                        },
                    },
                    "required": ["estimated_band", "strengths", "evidence"],
                },
                "lexical_resource": {
                    "type": "object",
                    "properties": {
                        "estimated_band": {"type": "number"},
                        "strengths": {"type": "array", "items": {"type": "string"}},
                        "evidence": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "quote": {"type": "string"},
                                    "error_code": {"type": "string"},
                                    "issue": {"type": "string"},
                                    "suggestion": {"type": "string"},
                                },
                                "required": ["quote", "error_code", "issue", "suggestion"],
                            },
                        },
                    },
                    "required": ["estimated_band", "strengths", "evidence"],
                },
                "grammatical_range_accuracy": {
                    "type": "object",
                    "properties": {
                        "estimated_band": {"type": "number"},
                        "strengths": {"type": "array", "items": {"type": "string"}},
                        "evidence": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "quote": {"type": "string"},
                                    "error_code": {"type": "string"},
                                    "issue": {"type": "string"},
                                    "suggestion": {"type": "string"},
                                },
                                "required": ["quote", "error_code", "issue", "suggestion"],
                            },
                        },
                    },
                    "required": ["estimated_band", "strengths", "evidence"],
                },
            },
            "required": [
                "task_response",
                "coherence_cohesion",
                "lexical_resource",
                "grammatical_range_accuracy",
            ],
        },
        "priority_actions": {"type": "array", "items": {"type": "string"}},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["criteria", "priority_actions", "uncertainties"],
}


def preprocess_essay(prompt_text: str, essay_text: str, task_type: str = "task2") -> dict[str, Any]:
    words = re.findall(r"\\b[a-zA-Z0-9]+(?:['-][a-zA-Z0-9]+)*\\b", essay_text)
    word_count = len(words)
    min_words = 150 if task_type == "task1" else 250
    paragraphs = [p.strip() for p in essay_text.strip().split("\\n") if p.strip()]
    cleaned = re.sub(r"\\s+", " ", essay_text.strip())
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\\s+", cleaned) if s.strip()] if cleaned else []
    return {
        "task_type": task_type,
        "word_count": word_count,
        "min_words_required": min_words,
        "is_underlength": word_count < min_words,
        "paragraph_count": len(paragraphs),
        "sentence_count": len(sentences),
    }


def build_prompts(prompt_text: str, essay_text: str, meta: dict[str, Any]) -> tuple[str, str]:
    task_label = "IELTS Academic Writing Task 2" if meta["task_type"] == "task2" else "IELTS Academic Writing Task 1"
    system_prompt = (
        f"You are an expert IELTS Writing Examiner Assistant evaluating an {task_label} essay.\\n"
        "RULES:\\n"
        "1. Every 'quote' MUST be copied verbatim from the student's essay.\\n"
        "2. Bands must be between 0.0 and 9.0 in 0.5 steps.\\n"
        "3. Use standard error_code values from: TR_UNDERDEVELOPED, CC_COHESION, COLLOCATION, WORD_CHOICE, SPELLING, ARTICLE, PREPOSITION, SVA, TENSE, PUNCTUATION.\\n"
        "4. Output strict JSON matching the schema."
    )
    user_prompt = (
        f"Task: {task_label}\\n"
        f"Word Count: {meta['word_count']} (Minimum: {meta['min_words_required']})\\n\\n"
        f"Prompt:\\n{prompt_text.strip()}\\n\\n"
        f"Student Essay:\\n{essay_text.strip()}"
    )
    return system_prompt, user_prompt


def calculate_overall_band(tr: float, cc: float, lr: float, gra: float) -> float:
    avg = (tr + cc + lr + gra) / 4.0
    return math.floor(avg * 2 + 0.5) / 2.0


def validate_assessment(
    raw_json: dict[str, Any],
    essay_text: str,
    meta: dict[str, Any],
    model_name: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    norm_essay = re.sub(r"\\s+", " ", essay_text.strip()).lower()
    criteria = raw_json.get("criteria", {})
    warnings: list[str] = []
    extracted_errors: list[dict[str, Any]] = []
    scores: dict[str, float] = {}
    total_quotes = 0
    unverified_quotes = 0

    for key in ("task_response", "coherence_cohesion", "lexical_resource", "grammatical_range_accuracy"):
        c_obj = criteria.get(key, {})
        raw_band = c_obj.get("estimated_band", 0.0)
        try:
            clamped = max(0.0, min(9.0, float(raw_band)))
            band = round(clamped * 2) / 2.0
        except (TypeError, ValueError):
            band = 0.0
        c_obj["estimated_band"] = band
        scores[key] = band

        for ev in c_obj.get("evidence", []):
            total_quotes += 1
            quote = ev.get("quote", "")
            norm_q = re.sub(r"\\s+", " ", quote.strip()).lower()
            is_verified = bool(norm_q and norm_q in norm_essay)
            ev["quote_verified"] = is_verified
            if not is_verified:
                unverified_quotes += 1
                warnings.append(f"[{key}] Quote không khớp nguyên văn: {quote}")
            extracted_errors.append(
                {
                    "error_code": ev.get("error_code", "WORD_CHOICE"),
                    "evidence": quote,
                    "correction": ev.get("suggestion", ""),
                    "explanation": ev.get("issue", ""),
                    "confidence": 1.0 if is_verified else 0.4,
                }
            )

    overall = calculate_overall_band(
        scores["task_response"],
        scores["coherence_cohesion"],
        scores["lexical_resource"],
        scores["grammatical_range_accuracy"],
    )

    uncertainties = list(raw_json.get("uncertainties", []))
    if meta["is_underlength"]:
        uncertainties.append(f"Thiếu từ: {meta['word_count']}/{meta['min_words_required']} từ.")
    uncertainties.extend(warnings)

    enriched = {
        "task_type": meta["task_type"],
        "rubric_version": RUBRIC_VERSION,
        "model_name": model_name,
        "preprocessing": meta,
        "estimated_overall": overall,
        "criteria": criteria,
        "priority_actions": raw_json.get("priority_actions", []),
        "uncertainties": uncertainties,
        "validation_summary": {
            "total_quotes_checked": total_quotes,
            "verified_quotes": total_quotes - unverified_quotes,
            "unverified_quotes": unverified_quotes,
            "all_quotes_verified": unverified_quotes == 0,
        },
        "teacher_review_required": True,
    }
    return enriched, extracted_errors
"""


STORE_PY = """from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db.database import db_session


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CopilotRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    def create_student(self, data: dict[str, Any]) -> dict[str, Any]:
        student_id = str(uuid.uuid4())
        ts = now_iso()
        with db_session(self.db_path) as conn:
            conn.execute(
                \"\"\"
                INSERT INTO students (
                    id, name, target_overall, target_writing, target_speaking,
                    current_overall, notes, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                \"\"\",
                (
                    student_id,
                    data["name"],
                    data.get("target_overall"),
                    data.get("target_writing"),
                    data.get("target_speaking"),
                    data.get("current_overall"),
                    data.get("notes", ""),
                    data.get("status", "active"),
                    ts,
                    ts,
                ),
            )
            row = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
            return dict(row)

    def list_students(self, status: str | None = None, search: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM students WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if search:
            query += " AND name LIKE ?"
            params.append(f"%{search}%")
        query += " ORDER BY created_at DESC"
        with db_session(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_student(self, student_id: str) -> dict[str, Any] | None:
        with db_session(self.db_path) as conn:
            row = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
            return dict(row) if row else None

    def create_writing_submission(self, data: dict[str, Any]) -> dict[str, Any]:
        sub_id = str(uuid.uuid4())
        ts = now_iso()
        with db_session(self.db_path) as conn:
            conn.execute(
                \"\"\"
                INSERT INTO submissions (
                    id, student_id, lesson_id, skill, task_type,
                    prompt_text, response_text, status, created_at
                ) VALUES (?, ?, ?, 'writing', ?, ?, ?, 'draft', ?)
                \"\"\",
                (
                    sub_id,
                    data["student_id"],
                    data.get("lesson_id"),
                    data["task_type"],
                    data["prompt_text"],
                    data["response_text"],
                    ts,
                ),
            )
            row = conn.execute("SELECT * FROM submissions WHERE id = ?", (sub_id,)).fetchone()
            return dict(row)

    def get_submission(self, submission_id: str) -> dict[str, Any] | None:
        with db_session(self.db_path) as conn:
            row = conn.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()
            return dict(row) if row else None

    def update_submission_status(self, submission_id: str, status: str) -> None:
        with db_session(self.db_path) as conn:
            conn.execute("UPDATE submissions SET status = ? WHERE id = ?", (status, submission_id))

    def save_assessment(
        self,
        submission_id: str,
        enriched_feedback: dict[str, Any],
        extracted_errors: list[dict[str, Any]],
        model_name: str,
    ) -> dict[str, Any]:
        assessment_id = str(uuid.uuid4())
        ts = now_iso()
        crit = enriched_feedback.get("criteria", {})
        tr = crit.get("task_response", {}).get("estimated_band")
        cc = crit.get("coherence_cohesion", {}).get("estimated_band")
        lr = crit.get("lexical_resource", {}).get("estimated_band")
        gra = crit.get("grammatical_range_accuracy", {}).get("estimated_band")
        overall = enriched_feedback.get("estimated_overall")

        with db_session(self.db_path) as conn:
            conn.execute(
                \"\"\"
                INSERT INTO assessments (
                    id, submission_id, rubric_version, model_name, model_version,
                    task_response, coherence, lexical, grammar, estimated_overall,
                    feedback_json, created_at
                ) VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?)
                \"\"\",
                (
                    assessment_id,
                    submission_id,
                    enriched_feedback.get("rubric_version", "ielts-writing-v1"),
                    model_name,
                    tr,
                    cc,
                    lr,
                    gra,
                    overall,
                    json.dumps(enriched_feedback, ensure_ascii=False),
                    ts,
                ),
            )

            # Lưu danh sách lỗi vào submission_errors để thống kê lỗi lặp lại của học viên
            conn.execute("DELETE FROM submission_errors WHERE submission_id = ?", (submission_id,))
            for err in extracted_errors:
                code = err.get("error_code", "WORD_CHOICE").upper()
                tag_row = conn.execute("SELECT id FROM error_tags WHERE code = ?", (code,)).fetchone()
                if not tag_row:
                    tag_row = conn.execute("SELECT id FROM error_tags WHERE code = 'WORD_CHOICE'").fetchone()
                if tag_row and err.get("evidence"):
                    conn.execute(
                        \"\"\"
                        INSERT OR IGNORE INTO submission_errors (
                            submission_id, error_tag_id, evidence, correction, explanation, confidence
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        \"\"\",
                        (
                            submission_id,
                            tag_row["id"],
                            err["evidence"],
                            err.get("correction", ""),
                            err.get("explanation", ""),
                            err.get("confidence", 1.0),
                        ),
                    )

            row = conn.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
            return dict(row)

    def save_teacher_review(
        self,
        submission_id: str,
        teacher_overall: float,
        teacher_feedback: str,
        assessment_id: str | None = None,
        updated_feedback_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ts = now_iso()
        with db_session(self.db_path) as conn:
            if assessment_id:
                target = conn.execute(
                    "SELECT * FROM assessments WHERE id = ? AND submission_id = ?",
                    (assessment_id, submission_id),
                ).fetchone()
            else:
                target = conn.execute(
                    "SELECT * FROM assessments WHERE submission_id = ? ORDER BY created_at DESC LIMIT 1",
                    (submission_id,),
                ).fetchone()

            if not target:
                raise ValueError("Chưa có bản đánh giá nào cho bài nộp này để duyệt.")

            new_json = (
                json.dumps(updated_feedback_json, ensure_ascii=False)
                if updated_feedback_json is not None
                else target["feedback_json"]
            )

            conn.execute(
                \"\"\"
                UPDATE assessments
                SET teacher_overall = ?, teacher_feedback = ?, feedback_json = ?, reviewed_at = ?
                WHERE id = ?
                \"\"\",
                (teacher_overall, teacher_feedback, new_json, ts, target["id"]),
            )
            conn.execute("UPDATE submissions SET status = 'reviewed' WHERE id = ?", (submission_id,))

            # Cập nhật current_overall của học viên theo điểm giáo viên vừa xác nhận
            sub = conn.execute("SELECT student_id FROM submissions WHERE id = ?", (submission_id,)).fetchone()
            if sub:
                conn.execute(
                    "UPDATE students SET current_overall = ?, updated_at = ? WHERE id = ?",
                    (teacher_overall, ts, sub["student_id"]),
                )

            updated = conn.execute("SELECT * FROM assessments WHERE id = ?", (target["id"],)).fetchone()
            return dict(updated)

    def get_student_progress(self, student_id: str) -> dict[str, Any]:
        with db_session(self.db_path) as conn:
            student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
            if not student:
                raise ValueError("Không tìm thấy hồ sơ học viên.")

            history_rows = conn.execute(
                \"\"\"
                SELECT
                    s.id AS submission_id,
                    s.skill,
                    s.task_type,
                    s.status,
                    s.created_at,
                    a.id AS assessment_id,
                    a.model_name,
                    a.estimated_overall,
                    a.teacher_overall,
                    a.teacher_feedback,
                    a.reviewed_at
                FROM submissions s
                LEFT JOIN assessments a ON a.submission_id = s.id
                WHERE s.student_id = ?
                ORDER BY s.created_at DESC
                \"\"\",
                (student_id,),
            ).fetchall()

            recurring_errors = conn.execute(
                \"\"\"
                SELECT
                    et.code,
                    et.category,
                    et.description,
                    COUNT(*) AS error_count
                FROM submission_errors se
                JOIN submissions s ON s.id = se.submission_id
                JOIN error_tags et ON et.id = se.error_tag_id
                WHERE s.student_id = ?
                GROUP BY et.id
                ORDER BY error_count DESC
                \"\"\",
                (student_id,),
            ).fetchall()

            return {
                "student": dict(student),
                "submissions_history": [dict(r) for r in history_rows],
                "recurring_errors": [dict(r) for r in recurring_errors],
            }
"""


ROUTES_PY = """from __future__ import annotations

import json
from fastapi import APIRouter, HTTPException

from app.repositories.store import CopilotRepository
from app.schemas.domain import (
    AssessWritingRequest,
    StudentCreate,
    TeacherReviewRequest,
    WritingSubmissionCreate,
)
from app.services.inference.ollama_provider import OllamaProvider
from app.services.writing.evaluator import (
    WRITING_SCHEMA,
    build_prompts,
    preprocess_essay,
    validate_assessment,
)

router = APIRouter(prefix="/api")
repo = CopilotRepository()
llm = OllamaProvider()


@router.get("/health")
def get_health():
    ollama_status = llm.health_check()
    return {
        "status": "ok",
        "backend": "local-fastapi",
        "ollama": ollama_status,
    }


@router.get("/models")
def get_models():
    try:
        return {"models": llm.list_models()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Không lấy được danh sách model từ Ollama: {exc}") from exc


@router.post("/students")
def create_student(payload: StudentCreate):
    return repo.create_student(payload.model_dump())


@router.get("/students")
def list_students(status: str | None = None, search: str | None = None):
    return {"students": repo.list_students(status=status, search=search)}


@router.get("/students/{student_id}/progress")
def get_student_progress(student_id: str):
    try:
        return repo.get_student_progress(student_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/submissions/writing")
def create_writing_submission(payload: WritingSubmissionCreate):
    student = repo.get_student(payload.student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Không tìm thấy student_id.")
    return repo.create_writing_submission(payload.model_dump())


@router.post("/submissions/{submission_id}/assess")
def assess_writing_submission(submission_id: str, req: AssessWritingRequest | None = None):
    options = req or AssessWritingRequest()
    sub = repo.get_submission(submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài nộp (submission_id).")

    repo.update_submission_status(submission_id, "processing")
    try:
        meta = preprocess_essay(sub["prompt_text"], sub["response_text"], sub["task_type"])
        sys_prompt, usr_prompt = build_prompts(sub["prompt_text"], sub["response_text"], meta)
        raw_json, bench = llm.generate_structured(
            system_prompt=sys_prompt,
            user_prompt=usr_prompt,
            schema=WRITING_SCHEMA,
            model=options.model_name,
            think=options.think,
        )
        enriched, extracted_errors = validate_assessment(
            raw_json=raw_json,
            essay_text=sub["response_text"],
            meta=meta,
            model_name=options.model_name,
        )
        enriched["benchmark"] = bench
        saved = repo.save_assessment(
            submission_id=submission_id,
            enriched_feedback=enriched,
            extracted_errors=extracted_errors,
            model_name=options.model_name,
        )
        saved["feedback_parsed"] = json.loads(saved["feedback_json"])
        return saved
    except Exception as exc:
        repo.update_submission_status(submission_id, "failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/submissions/{submission_id}/review")
def review_submission(submission_id: str, payload: TeacherReviewRequest):
    try:
        reviewed = repo.save_teacher_review(
            submission_id=submission_id,
            teacher_overall=payload.teacher_overall,
            teacher_feedback=payload.teacher_feedback,
            assessment_id=payload.assessment_id,
            updated_feedback_json=payload.updated_feedback_json,
        )
        return reviewed
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
"""


MAIN_PY = """from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.db.database import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="IELTS Copilot Local Backend",
    description="Local IELTS Teaching Assistant API (100% Offline - SQLite + Ollama)",
    version="0.1.0",
    lifespan=lifespan,
)

# Chỉ cho phép kết nối từ giao diện Tauri / React chạy cục bộ
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "tauri://localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
"""


TEST_PY = """from __future__ import annotations

from pathlib import Path
from app.db.database import init_db
from app.repositories.store import CopilotRepository
from app.services.writing.evaluator import preprocess_essay, validate_assessment


def test_end_to_end_sqlite_and_validation(tmp_path: Path):
    test_db = tmp_path / "test_ielts.db"
    init_db(test_db)
    repo = CopilotRepository(db_path=test_db)

    # 1. Tạo hồ sơ học viên
    student = repo.create_student(
        {
            "name": "Nguyen Minh Anh",
            "target_overall": 7.0,
            "target_writing": 6.5,
            "target_speaking": 7.0,
            "notes": "Hay sai hòa hợp chủ-vị (SVA) và thiếu mạo từ.",
        }
    )
    assert student["name"] == "Nguyen Minh Anh"

    # 2. Tạo bài nộp Writing Task 2
    essay = (
        "Nowadays, university attendance is a hot topic. "
        "Many young undergraduates might procrastinate and fall behind in their studies, "
        "which ultimately lead to higher dropout rates."
    )
    sub = repo.create_writing_submission(
        {
            "student_id": student["id"],
            "task_type": "task2",
            "prompt_text": "Should university classes be optional?",
            "response_text": essay,
        }
    )
    assert sub["status"] == "draft"

    # 3. Kiểm tra Validator & Lưu đánh giá
    meta = preprocess_essay(sub["prompt_text"], essay, "task2")
    mock_llm_output = {
        "criteria": {
            "task_response": {"estimated_band": 6.0, "strengths": ["Clear opinion"], "evidence": []},
            "coherence_cohesion": {"estimated_band": 6.5, "strengths": ["Logical flow"], "evidence": []},
            "lexical_resource": {"estimated_band": 6.5, "strengths": ["Good academic words"], "evidence": []},
            "grammatical_range_accuracy": {
                "estimated_band": 6.0,
                "strengths": [],
                "evidence": [
                    {
                        "quote": "which ultimately lead to higher dropout rates",
                        "error_code": "SVA",
                        "issue": "Mệnh đề quan hệ bổ nghĩa cho cả mệnh đề trước cần chia động từ số ít.",
                        "suggestion": "which ultimately leads to higher dropout rates",
                    }
                ],
            },
        },
        "priority_actions": ["Ôn lại Subject-Verb Agreement"],
        "uncertainties": [],
    }
    enriched, extracted_errors = validate_assessment(mock_llm_output, essay, meta, "qwen3:8b")
    assert enriched["estimated_overall"] == 6.5
    assert enriched["validation_summary"]["all_quotes_verified"] is True

    saved_assessment = repo.save_assessment(sub["id"], enriched, extracted_errors, "qwen3:8b")
    assert saved_assessment["estimated_overall"] == 6.5

    # 4. Giáo viên duyệt và chốt band
    reviewed = repo.save_teacher_review(
        submission_id=sub["id"],
        teacher_overall=6.0,
        teacher_feedback="Bài viết lập luận tốt nhưng cần đủ 250 từ và sửa lỗi chia động từ.",
        assessment_id=saved_assessment["id"],
    )
    assert reviewed["teacher_overall"] == 6.0

    # 5. Kiểm tra tiến độ và thống kê lỗi lặp lại
    progress = repo.get_student_progress(student["id"])
    assert progress["student"]["current_overall"] == 6.0
    assert len(progress["recurring_errors"]) == 1
    assert progress["recurring_errors"][0]["code"] == "SVA"
"""


FILES_TO_GENERATE: dict[Path, str] = {
    BACKEND_DIR / "requirements.txt": REQUIREMENTS_TXT,
    APP_DIR / "__init__.py": "",
    APP_DIR / "core" / "__init__.py": "",
    APP_DIR / "core" / "config.py": CONFIG_PY,
    APP_DIR / "db" / "__init__.py": "",
    APP_DIR / "db" / "schema.sql": SCHEMA_SQL,
    APP_DIR / "db" / "database.py": DATABASE_PY,
    APP_DIR / "schemas" / "__init__.py": "",
    APP_DIR / "schemas" / "domain.py": SCHEMAS_PY,
    APP_DIR / "services" / "__init__.py": "",
    APP_DIR / "services" / "inference" / "__init__.py": "",
    APP_DIR / "services" / "inference" / "ollama_provider.py": OLLAMA_PROVIDER_PY,
    APP_DIR / "services" / "writing" / "__init__.py": "",
    APP_DIR / "services" / "writing" / "evaluator.py": EVALUATOR_PY,
    APP_DIR / "repositories" / "__init__.py": "",
    APP_DIR / "repositories" / "store.py": STORE_PY,
    APP_DIR / "api" / "__init__.py": "",
    APP_DIR / "api" / "routes.py": ROUTES_PY,
    APP_DIR / "main.py": MAIN_PY,
    BACKEND_DIR / "tests" / "__init__.py": "",
    BACKEND_DIR / "tests" / "test_backend_mvp.py": TEST_PY,
}


def main() -> None:
    print("=" * 72)
    print("IELTS COPILOT - KHOI TAO MOC 2: FASTAPI BACKEND + SQLITE 6 BANG")
    print("=" * 72)

    for file_path, content in FILES_TO_GENERATE.items():
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        print(f"[+] Đã tạo: {file_path.relative_to(PROJECT_ROOT)}")

    # Khởi tạo ngay file SQLite database tại data/ielts_copilot.db
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db_file = DATA_DIR / "ielts_copilot.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(SCHEMA_SQL)
    conn.close()
    print(f"\n[✓] Đã khởi tạo cơ sở dữ liệu SQLite (6 bảng chuẩn) tại: {db_file}")

    print("\n=== BƯỚC TIẾP THEO TRÊN POWERSHELL CỦA BẠN ===")
    print("1. Cài đặt FastAPI & Uvicorn vào .venv trên ổ F:")
    print("   .\\.venv\\Scripts\\pip.exe install -r apps\\backend\\requirements.txt")
    print("\n2. Chạy kiểm thử tự động (Unit Tests) cho Database & Validator:")
    print("   $env:PYTHONPATH='apps\\backend'; .\\.venv\\Scripts\\pytest.exe apps\\backend\\tests")
    print("\n3. Khởi chạy Backend Server tại http://127.0.0.1:8000:")
    print("   $env:PYTHONPATH='apps\\backend'; .\\.venv\\Scripts\\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload")
    print("   -> Mở trình duyệt vào: http://127.0.0.1:8000/docs để dùng thử ngay giao diện Swagger UI!")


if __name__ == "__main__":
    main()
