from __future__ import annotations

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
                """
                INSERT INTO students (
                    id, name, target_overall, target_writing, target_speaking,
                    current_overall, notes, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
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
        lesson_id = data.get("lesson_id")
        if lesson_id in ("", "string"):
            lesson_id = None
        with db_session(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO submissions (
                    id, student_id, lesson_id, skill, task_type,
                    prompt_text, response_text, status, created_at
                ) VALUES (?, ?, ?, 'writing', ?, ?, ?, 'draft', ?)
                """,
                (
                    sub_id,
                    data["student_id"],
                    lesson_id,
                    data["task_type"],
                    data["prompt_text"],
                    data["response_text"],
                    ts,
                ),
            )
            row = conn.execute("SELECT * FROM submissions WHERE id = ?", (sub_id,)).fetchone()
            return dict(row)

    def create_speaking_submission(self, data: dict[str, Any]) -> dict[str, Any]:
        sub_id = str(uuid.uuid4())
        ts = now_iso()
        lesson_id = data.get("lesson_id")
        if lesson_id in ("", "string"):
            lesson_id = None
        with db_session(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO submissions (
                    id, student_id, lesson_id, skill, task_type,
                    prompt_text, response_text, source_audio_path, transcript_text, status, created_at
                ) VALUES (?, ?, ?, 'speaking', ?, ?, ?, ?, ?, 'draft', ?)
                """,
                (
                    sub_id,
                    data["student_id"],
                    lesson_id,
                    data["task_type"],
                    data["prompt_text"],
                    data.get("response_text", ""),
                    data.get("source_audio_path"),
                    data.get("transcript_text", ""),
                    ts,
                ),
            )
            row = conn.execute("SELECT * FROM submissions WHERE id = ?", (sub_id,)).fetchone()
            return dict(row)

    def update_speaking_transcript(
        self,
        submission_id: str,
        transcript_text: str,
        audio_meta_json: str | None = None,
    ) -> dict[str, Any]:
        with db_session(self.db_path) as conn:
            if audio_meta_json is not None:
                conn.execute(
                    "UPDATE submissions SET transcript_text = ?, response_text = ? WHERE id = ?",
                    (transcript_text, audio_meta_json, submission_id),
                )
            else:
                conn.execute(
                    "UPDATE submissions SET transcript_text = ? WHERE id = ?",
                    (transcript_text, submission_id),
                )
            row = conn.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()
            return dict(row)

    def get_submission(self, submission_id: str) -> dict[str, Any] | None:
        with db_session(self.db_path) as conn:
            row = conn.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()
            return dict(row) if row else None

    def get_submission_detail(self, submission_id: str) -> dict[str, Any] | None:
        with db_session(self.db_path) as conn:
            sub = conn.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()
            if not sub:
                return None
            assessments = conn.execute(
                "SELECT * FROM assessments WHERE submission_id = ? ORDER BY created_at DESC",
                (submission_id,),
            ).fetchall()
            parsed_list = []
            for a in assessments:
                item = dict(a)
                try:
                    item["feedback_parsed"] = json.loads(item["feedback_json"])
                except Exception:
                    item["feedback_parsed"] = {}
                parsed_list.append(item)
            result = dict(sub)
            result["assessments"] = parsed_list
            return result

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

        # Hỗ trợ lưu cả Writing (TR, CC, LR, GRA) và Speaking (FC, PRON, LR, GRA)
        if enriched_feedback.get("skill") == "speaking":
            tr = crit.get("fluency_coherence", {}).get("estimated_band")
            cc = crit.get("pronunciation", {}).get("estimated_band")
        else:
            tr = crit.get("task_response", {}).get("estimated_band")
            cc = crit.get("coherence_cohesion", {}).get("estimated_band")

        lr = crit.get("lexical_resource", {}).get("estimated_band")
        gra = crit.get("grammatical_range_accuracy", {}).get("estimated_band")
        overall = enriched_feedback.get("estimated_overall")

        with db_session(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO assessments (
                    id, submission_id, rubric_version, model_name, model_version,
                    task_response, coherence, lexical, grammar, estimated_overall,
                    feedback_json, created_at
                ) VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment_id,
                    submission_id,
                    enriched_feedback.get("rubric_version", "ielts-writing-v2-cambridge-calibrated"),
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

            conn.execute("DELETE FROM submission_errors WHERE submission_id = ?", (submission_id,))
            for err in extracted_errors:
                code = err.get("error_code", "WORD_CHOICE").upper()
                tag_row = conn.execute("SELECT id FROM error_tags WHERE code = ?", (code,)).fetchone()
                if not tag_row:
                    tag_row = conn.execute("SELECT id FROM error_tags WHERE code = 'WORD_CHOICE'").fetchone()
                if tag_row and err.get("evidence"):
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO submission_errors (
                            submission_id, error_tag_id, evidence, correction, explanation, confidence
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
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
                """
                UPDATE assessments
                SET teacher_overall = ?, teacher_feedback = ?, feedback_json = ?, reviewed_at = ?
                WHERE id = ?
                """,
                (teacher_overall, teacher_feedback, new_json, ts, target["id"]),
            )
            conn.execute("UPDATE submissions SET status = 'reviewed' WHERE id = ?", (submission_id,))

            sub = conn.execute("SELECT student_id FROM submissions WHERE id = ?", (submission_id,)).fetchone()
            if sub:
                conn.execute(
                    "UPDATE students SET current_overall = ?, updated_at = ? WHERE id = ?",
                    (teacher_overall, ts, sub["student_id"]),
                )

            updated = conn.execute("SELECT * FROM assessments WHERE id = ?", (target["id"],)).fetchone()
            item = dict(updated)
            try:
                item["feedback_parsed"] = json.loads(item["feedback_json"])
            except Exception:
                item["feedback_parsed"] = {}
            return item

    def get_student_progress(self, student_id: str) -> dict[str, Any]:
        with db_session(self.db_path) as conn:
            student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
            if not student:
                raise ValueError("Không tìm thấy hồ sơ học viên.")

            history_rows = conn.execute(
                """
                SELECT
                    s.id AS submission_id,
                    s.skill,
                    s.task_type,
                    s.prompt_text,
                    s.status,
                    s.created_at,
                    a.id AS assessment_id,
                    a.rubric_version,
                    a.model_name,
                    a.task_response,
                    a.coherence,
                    a.lexical,
                    a.grammar,
                    a.estimated_overall,
                    a.teacher_overall,
                    a.teacher_feedback,
                    a.reviewed_at,
                    a.created_at AS assessed_at
                FROM submissions s
                LEFT JOIN assessments a ON a.submission_id = s.id
                WHERE s.student_id = ?
                ORDER BY s.created_at DESC, a.created_at DESC
                """,
                (student_id,),
            ).fetchall()

            recurring_errors = conn.execute(
                """
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
                """,
                (student_id,),
            ).fetchall()

            return {
                "student": dict(student),
                "submissions_history": [dict(r) for r in history_rows],
                "recurring_errors": [dict(r) for r in recurring_errors],
            }
