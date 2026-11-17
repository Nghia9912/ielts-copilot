from __future__ import annotations

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
                """
                INSERT OR IGNORE INTO error_tags (id, code, category, description)
                VALUES (?, ?, ?, ?)
                """,
                (tag_id, code, category, description),
            )


def _run_studio_migrations(custom_path: Path | None = None) -> None:
    from app.db.studio_migrations import migrate_teaching_studio_db
    migrate_teaching_studio_db(custom_path)

_orig_init_db_studio = init_db
def init_db(custom_path: Path | None = None) -> None:
    _orig_init_db_studio(custom_path)
    _run_studio_migrations(custom_path)
