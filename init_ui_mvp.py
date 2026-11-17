#!/usr/bin/env python3
"""IELTS Copilot - Trình khởi tạo Mốc 3: Giao diện Writing Lab & Student Records (UI).

Chạy trực tiếp tại thư mục F:\\ielts-copilot:
    .\\.venv\\Scripts\\python.exe init_ui_mvp.py

Tính năng nổi bật:
1. Tích hợp giao diện trực quan (Writing Lab + Student Records + Teacher Review) ngay tại http://127.0.0.1:8000/
   (và lưu bản gốc tại apps/desktop/index.html để sẵn sàng đóng gói Tauri).
2. Không cần gõ JSON thủ công: Ô nhập đề bài và bài viết hỗ trợ xuống dòng tự nhiên, đếm từ trực tiếp (Live Word Counter).
3. Tự động tô sáng (Highlight) câu trích dẫn lỗi ngay trong bài viết gốc khi bấm vào từng nhận xét.
4. Khung Teacher Review: Giáo viên chỉnh lại Band (ví dụ từ 6.5 lên 7.0), nhập nhận xét và bấm Lưu 1 chạm.
5. Tự động hiển thị lại toàn bộ dữ liệu học viên và bài viết Cambridge 20 bạn đã chấm trong SQLite.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path.cwd()
APP_DIR = PROJECT_ROOT / "apps" / "backend" / "app"
DESKTOP_DIR = PROJECT_ROOT / "apps" / "desktop"


STORE_UPDATE_PY = """from __future__ import annotations

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
        lesson_id = data.get("lesson_id")
        if lesson_id in ("", "string"):
            lesson_id = None
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
                    lesson_id,
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
                \"\"\"
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


ROUTES_UPDATE_PY = """from __future__ import annotations

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


@router.get("/submissions/{submission_id}")
def get_submission_detail(submission_id: str):
    detail = repo.get_submission_detail(submission_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài nộp.")
    return detail


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


UI_HTML = """<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>IELTS Copilot — Local Teaching Assistant</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: #1e293b;
      --panel-alt: #334155;
      --text: #f8fafc;
      --muted: #94a3b8;
      --primary: #38bdf8;
      --primary-hover: #0284c7;
      --success: #22c55e;
      --warning: #f59e0b;
      --danger: #ef4444;
      --border: #334155;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding-bottom: 40px;
    }
    header {
      background: #090d16;
      border-bottom: 1px solid var(--border);
      padding: 14px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 20;
    }
    .brand { display: flex; align-items: center; gap: 12px; }
    .brand h1 { font-size: 1.25rem; font-weight: 700; color: var(--primary); }
    .badge {
      font-size: 0.75rem;
      padding: 3px 10px;
      border-radius: 999px;
      background: var(--panel-alt);
      color: var(--text);
      font-weight: 600;
    }
    .badge.online { background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid #22c55e; }
    .nav-tabs { display: flex; gap: 8px; }
    .tab-btn {
      background: transparent;
      color: var(--muted);
      border: 1px solid transparent;
      padding: 8px 16px;
      border-radius: 8px;
      cursor: pointer;
      font-weight: 600;
      font-size: 0.9rem;
    }
    .tab-btn.active {
      background: var(--panel);
      color: var(--primary);
      border-color: var(--primary);
    }
    .container { max-width: 1440px; margin: 20px auto; padding: 0 20px; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1.15fr; gap: 20px; align-items: start; }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 20px;
    }
    .card h2 { font-size: 1.05rem; margin-bottom: 14px; color: #e2e8f0; display: flex; justify-content: space-between; align-items: center; }
    label { display: block; font-size: 0.85rem; color: var(--muted); margin-bottom: 6px; font-weight: 600; }
    input, select, textarea {
      width: 100%;
      background: #0f172a;
      border: 1px solid var(--border);
      color: var(--text);
      padding: 10px 12px;
      border-radius: 8px;
      font-size: 0.92rem;
      margin-bottom: 14px;
      font-family: inherit;
    }
    textarea { resize: vertical; }
    .row-3 { display: grid; grid-template-columns: 1.5fr 1fr 1fr; gap: 12px; }
    .btn {
      background: var(--primary);
      color: #0f172a;
      border: none;
      padding: 10px 18px;
      border-radius: 8px;
      font-weight: 700;
      cursor: pointer;
      font-size: 0.92rem;
      transition: 0.15s;
    }
    .btn:hover { background: var(--primary-hover); color: #fff; }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .btn-secondary { background: var(--panel-alt); color: var(--text); }
    .btn-success { background: var(--success); color: #052e16; }
    .score-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 16px; }
    .score-box {
      background: #0f172a;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      text-align: center;
    }
    .score-box.overall { border-color: var(--primary); background: rgba(56, 189, 248, 0.1); }
    .score-box .label { font-size: 0.75rem; color: var(--muted); text-transform: uppercase; }
    .score-box .val { font-size: 1.55rem; font-weight: 800; margin-top: 4px; color: var(--text); }
    .score-box.overall .val { color: var(--primary); }
    .essay-preview {
      background: #0f172a;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 16px;
      white-space: pre-wrap;
      font-size: 0.96rem;
      line-height: 1.75;
      max-height: 460px;
      overflow-y: auto;
    }
    mark.hl {
      background: rgba(245, 158, 11, 0.35);
      color: #fef08a;
      padding: 2px 4px;
      border-radius: 4px;
      border-bottom: 2px solid var(--warning);
    }
    .crit-section {
      border-top: 1px solid var(--border);
      padding-top: 12px;
      margin-top: 12px;
    }
    .crit-title { font-weight: 700; color: var(--primary); margin-bottom: 8px; display: flex; justify-content: space-between; }
    .ev-item {
      background: #0f172a;
      border-left: 4px solid var(--warning);
      padding: 10px 12px;
      border-radius: 6px;
      margin-bottom: 8px;
      cursor: pointer;
      font-size: 0.88rem;
    }
    .ev-item:hover { background: #172554; }
    .ev-quote { font-style: italic; color: #fde047; margin-bottom: 4px; }
    .ev-fix { color: #4ade80; font-weight: 600; margin-top: 4px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
    th, td { padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: left; }
    th { color: var(--muted); font-weight: 600; background: #0f172a; }
    .hidden { display: none; }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <h1>IELTS Copilot</h1>
      <span class="badge">Offline Local Assistant · F:\\ielts-copilot</span>
      <span id="ollamaStatus" class="badge">Đang kiểm tra Ollama...</span>
    </div>
    <div class="nav-tabs">
      <button class="tab-btn active" onclick="switchTab('writing')">Writing Lab (Chấm & Duyệt bài)</button>
      <button class="tab-btn" onclick="switchTab('students')">Student Records (Hồ sơ & Tiến độ)</button>
    </div>
  </header>

  <div class="container">
    <!-- TAB 1: WRITING LAB -->
    <div id="tab-writing" class="grid-2">
      <div>
        <div class="card">
          <h2>
            <span>1. Nhập bài IELTS Writing</span>
            <span id="wordCountBadge" class="badge">0 từ (Tối thiểu: 250)</span>
          </h2>
          <div class="row-3">
            <div>
              <label>Học viên</label>
              <select id="studentSelect"></select>
            </div>
            <div>
              <label>Loại bài (Task)</label>
              <select id="taskTypeSelect" onchange="updateWordCount()">
                <option value="task2">Writing Task 2 (≥250 từ)</option>
                <option value="task1">Writing Task 1 (≥150 từ)</option>
              </select>
            </div>
            <div>
              <label>Model AI (Local)</label>
              <select id="modelSelect">
                <option value="qwen3:8b">qwen3:8b (Khuyên dùng)</option>
                <option value="gemma3:4b">gemma3:4b (Nhanh/Nhẹ)</option>
              </select>
            </div>
          </div>

          <label>Đề bài (Prompt)</label>
          <textarea id="promptInput" rows="3" placeholder="Dán đề bài IELTS Writing vào đây..."></textarea>

          <label>Bài làm của học viên (Xuống dòng thoải mái, không lo lỗi JSON)</label>
          <textarea id="essayInput" rows="11" oninput="updateWordCount()" placeholder="Dán bài viết của học viên vào đây..."></textarea>

          <div style="display:flex; justify-content:space-between; align-items:center; gap:12px;">
            <label style="display:flex; align-items:center; gap:8px; margin:0; cursor:pointer;">
              <input type="checkbox" id="thinkToggle" style="width:auto; margin:0;" />
              <span>Bật Deep Thinking (Chậm hơn ~70s, mặc định tắt ~30-40s)</span>
            </label>
            <button id="assessBtn" class="btn" onclick="submitAndAssess()">Chấm bài ngay (Local AI)</button>
          </div>
        </div>

        <div id="essayHighlightCard" class="card hidden">
          <h2>
            <span>Bài gốc & Đối chiếu Trích dẫn (Bấm vào lỗi bên phải để tô sáng câu)</span>
            <button class="btn btn-secondary" style="padding:4px 10px; font-size:0.78rem;" onclick="clearHighlight()">Bỏ tô sáng</button>
          </h2>
          <div id="essayPreviewBox" class="essay-preview"></div>
        </div>
      </div>

      <div>
        <div class="card">
          <h2>
            <span>2. Kết quả Phân tích & Kiểm duyệt của Giáo viên</span>
            <span id="rubricBadge" class="badge">Chưa có dữ liệu</span>
          </h2>

          <div id="emptyAssessmentState" style="color:var(--muted); padding:30px 0; text-align:center;">
            Hãy nhập bài viết bên trái và bấm <b>Chấm bài ngay</b>, hoặc chọn một bài đã chấm từ tab <b>Student Records</b>.
          </div>

          <div id="assessmentResultBox" class="hidden">
            <div class="score-grid">
              <div class="score-box"><div class="label">Task Resp</div><div id="scTR" class="val">-</div></div>
              <div class="score-box"><div class="label">Coherence</div><div id="scCC" class="val">-</div></div>
              <div class="score-box"><div class="label">Lexical</div><div id="scLR" class="val">-</div></div>
              <div class="score-box"><div class="label">Grammar</div><div id="scGRA" class="val">-</div></div>
              <div class="score-box overall"><div class="label">AI Overall</div><div id="scOverall" class="val">-</div></div>
            </div>

            <div id="validationBanner" style="margin-bottom:14px; font-size:0.84rem; padding:8px 12px; border-radius:8px; background:#0f172a; border:1px solid var(--border);"></div>

            <!-- KHUNG GIÁO VIÊN DUYỆT (TEACHER REVIEW) -->
            <div style="background:#0f172a; border:1px solid var(--primary); border-radius:10px; padding:14px; margin-bottom:16px;">
              <div style="font-weight:700; color:var(--primary); margin-bottom:10px;">
                Chốt điểm của Giáo viên (Teacher Review — Điểm chính thức lưu hồ sơ)
              </div>
              <div class="row-3" style="grid-template-columns: 1fr 2fr auto; align-items:end;">
                <div>
                  <label>Band Giáo viên chốt</label>
                  <input type="number" id="teacherBandInput" step="0.5" min="0" max="9" value="7.0" style="margin:0;" />
                </div>
                <div>
                  <label>Nhận xét bổ sung của Giáo viên</label>
                  <input type="text" id="teacherFeedbackInput" placeholder="VD: Bài đạt chuẩn Band 7.0 sách Cambridge 20, cần lưu ý thêm collocation..." style="margin:0;" />
                </div>
                <button class="btn btn-success" onclick="saveTeacherReview()">Lưu Duyệt</button>
              </div>
              <div id="reviewSavedMsg" style="color:#4ade80; font-size:0.82rem; margin-top:8px;" class="hidden"></div>
            </div>

            <div id="criteriaDetailsBox"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 2: STUDENT RECORDS -->
    <div id="tab-students" class="hidden">
      <div class="grid-2" style="grid-template-columns: 1fr 2fr;">
        <div class="card">
          <h2>Thêm Học viên mới</h2>
          <label>Họ và tên học viên</label>
          <input type="text" id="newStudentName" placeholder="VD: Trần Hoàng Nam" />
          <div class="row-3">
            <div>
              <label>Target Overall</label>
              <input type="number" id="newTargetOverall" step="0.5" value="7.0" />
            </div>
            <div>
              <label>Target Writing</label>
              <input type="number" id="newTargetWriting" step="0.5" value="6.5" />
            </div>
            <div>
              <label>Target Speaking</label>
              <input type="number" id="newTargetSpeaking" step="0.5" value="6.5" />
            </div>
          </div>
          <label>Ghi chú học viên</label>
          <textarea id="newStudentNotes" rows="2" placeholder="Điểm mạnh, điểm yếu cần lưu ý..."></textarea>
          <button class="btn" style="width:100%;" onclick="createNewStudent()">+ Tạo Hồ sơ Học viên</button>
        </div>

        <div>
          <div class="card">
            <h2>
              <span>Tiến độ & Lịch sử Chấm bài của Học viên</span>
              <select id="progressStudentSelect" style="width:280px; margin:0;" onchange="loadStudentProgress()"></select>
            </h2>

            <div id="recurringErrorsBox" style="margin-bottom:18px;"></div>

            <h3 style="font-size:0.95rem; margin-bottom:10px; color:var(--muted);">Lịch sử các lượt chấm (Bấm "Mở lại bài" để xem chi tiết hoặc chấm lại)</h3>
            <table>
              <thead>
                <tr>
                  <th>Thời gian</th>
                  <th>Task</th>
                  <th>Rubric / Model</th>
                  <th>TR / CC / LR / GRA</th>
                  <th>AI Band</th>
                  <th>GV Chốt</th>
                  <th>Thao tác</th>
                </tr>
              </thead>
              <tbody id="historyTableBody"></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script>
    let currentSubmissionId = null;
    let currentAssessmentId = null;
    let currentEssayRaw = "";

    async function api(path, options = {}) {
      const resp = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...options
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail));
      }
      return resp.json();
    }

    function switchTab(tab) {
      document.getElementById('tab-writing').classList.toggle('hidden', tab !== 'writing');
      document.getElementById('tab-students').classList.toggle('hidden', tab !== 'students');
      document.querySelectorAll('.tab-btn').forEach((btn, idx) => {
        btn.classList.toggle('active', (tab === 'writing' && idx === 0) || (tab === 'students' && idx === 1));
      });
      if (tab === 'students') loadStudentProgress();
    }

    function updateWordCount() {
      const text = document.getElementById('essayInput').value.trim();
      const words = text ? (text.match(/\\b[a-zA-Z0-9]+(?:['-][a-zA-Z0-9]+)*\\b/g) || []).length : 0;
      const taskType = document.getElementById('taskTypeSelect').value;
      const minW = taskType === 'task1' ? 150 : 250;
      const badge = document.getElementById('wordCountBadge');
      badge.textContent = `${words} từ (Tối thiểu: ${minW})`;
      badge.style.color = words >= minW ? '#4ade80' : '#fbbf24';
    }

    async function initApp() {
      try {
        const health = await api('/api/health');
        const st = document.getElementById('ollamaStatus');
        if (health.ollama && health.ollama.ollama_online) {
          st.textContent = `Ollama Online (${health.ollama.installed_models.join(', ')})`;
          st.classList.add('online');
        } else {
          st.textContent = 'Ollama Offline';
        }
      } catch (e) {
        console.error(e);
      }
      await loadStudentsList();
    }

    async function loadStudentsList() {
      const data = await api('/api/students');
      const students = data.students || [];
      const sel1 = document.getElementById('studentSelect');
      const sel2 = document.getElementById('progressStudentSelect');
      sel1.innerHTML = '';
      sel2.innerHTML = '';
      students.forEach(s => {
        const label = `${s.name} (Target: ${s.target_overall || '-'} | Hiện tại: ${s.current_overall || 'Chưa chốt'})`;
        sel1.add(new Option(label, s.id));
        sel2.add(new Option(label, s.id));
      });
      if (students.length > 0) {
        await loadStudentProgress();
      }
    }

    async function createNewStudent() {
      const name = document.getElementById('newStudentName').value.trim();
      if (!name) return alert('Vui lòng nhập họ tên học viên!');
      await api('/api/students', {
        method: 'POST',
        body: JSON.stringify({
          name,
          target_overall: parseFloat(document.getElementById('newTargetOverall').value) || 7.0,
          target_writing: parseFloat(document.getElementById('newTargetWriting').value) || 6.5,
          target_speaking: parseFloat(document.getElementById('newTargetSpeaking').value) || 6.5,
          notes: document.getElementById('newStudentNotes').value.trim()
        })
      });
      document.getElementById('newStudentName').value = '';
      document.getElementById('newStudentNotes').value = '';
      await loadStudentsList();
      alert('Đã tạo hồ sơ học viên thành công!');
    }

    async function submitAndAssess() {
      const studentId = document.getElementById('studentSelect').value;
      const taskType = document.getElementById('taskTypeSelect').value;
      const modelName = document.getElementById('modelSelect').value;
      const promptText = document.getElementById('promptInput').value.trim();
      const essayText = document.getElementById('essayInput').value.trim();
      const think = document.getElementById('thinkToggle').checked;

      if (!studentId) return alert('Hãy tạo hoặc chọn 1 học viên trước!');
      if (promptText.length < 10 || essayText.length < 20) return alert('Vui lòng nhập đầy đủ đề bài và bài làm!');

      const btn = document.getElementById('assessBtn');
      btn.disabled = true;
      btn.textContent = 'Đang chấm bằng AI cục bộ (vui lòng đợi ~25-40s)...';

      try {
        const sub = await api('/api/submissions/writing', {
          method: 'POST',
          body: JSON.stringify({
            student_id: studentId,
            task_type: taskType,
            prompt_text: promptText,
            response_text: essayText
          })
        });
        currentSubmissionId = sub.id;
        currentEssayRaw = essayText;

        const assessed = await api(`/api/submissions/${sub.id}/assess`, {
          method: 'POST',
          body: JSON.stringify({ model_name: modelName, think })
        });
        renderAssessment(assessed, essayText);
      } catch (e) {
        alert('Lỗi khi chấm bài: ' + e.message);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Chấm bài ngay (Local AI)';
      }
    }

    function escapeHtml(str) {
      return str.replace(/[&<>"']/g, m => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m]));
    }

    function highlightQuoteInEssay(quote) {
      const box = document.getElementById('essayPreviewBox');
      if (!quote || !currentEssayRaw) return;
      const escapedEssay = escapeHtml(currentEssayRaw);
      const escapedQuote = escapeHtml(quote.trim());
      const idx = escapedEssay.toLowerCase().indexOf(escapedQuote.toLowerCase());
      if (idx === -1) {
        box.innerHTML = escapedEssay;
        return;
      }
      const before = escapedEssay.slice(0, idx);
      const match = escapedEssay.slice(idx, idx + escapedQuote.length);
      const after = escapedEssay.slice(idx + escapedQuote.length);
      box.innerHTML = `${before}<mark class="hl" id="activeHl">${match}</mark>${after}`;
      const el = document.getElementById('activeHl');
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    function clearHighlight() {
      document.getElementById('essayPreviewBox').innerHTML = escapeHtml(currentEssayRaw);
    }

    function renderAssessment(assessed, essayText) {
      currentSubmissionId = assessed.submission_id;
      currentAssessmentId = assessed.id;
      currentEssayRaw = essayText;

      document.getElementById('emptyAssessmentState').classList.add('hidden');
      document.getElementById('assessmentResultBox').classList.remove('hidden');
      document.getElementById('essayHighlightCard').classList.remove('hidden');
      document.getElementById('essayPreviewBox').innerHTML = escapeHtml(essayText);

      const fb = assessed.feedback_parsed || {};
      document.getElementById('rubricBadge').textContent = `${assessed.rubric_version} · ${assessed.model_name}`;
      document.getElementById('scTR').textContent = assessed.task_response ?? '-';
      document.getElementById('scCC').textContent = assessed.coherence ?? '-';
      document.getElementById('scLR').textContent = assessed.lexical ?? '-';
      document.getElementById('scGRA').textContent = assessed.grammar ?? '-';
      document.getElementById('scOverall').textContent = assessed.estimated_overall ?? '-';

      document.getElementById('teacherBandInput').value = assessed.teacher_overall ?? assessed.estimated_overall ?? 6.5;
      document.getElementById('teacherFeedbackInput').value = assessed.teacher_feedback || '';
      document.getElementById('reviewSavedMsg').classList.add('hidden');

      const val = fb.validation_summary || {};
      const bench = fb.benchmark || {};
      const banner = document.getElementById('validationBanner');
      banner.innerHTML = `<b>Kiểm tra trích dẫn:</b> ${val.verified_quotes ?? 0}/${val.total_quotes_checked ?? 0} câu khớp 100% bài gốc · <b>Lỗi chéo tiêu chí:</b> ${val.cross_criterion_violations ?? 0} · <b>Tốc độ:</b> ${bench.elapsed_seconds ?? '-'}s (${bench.tokens_per_second ?? '-'} tok/s)`;

      const critBox = document.getElementById('criteriaDetailsBox');
      critBox.innerHTML = '';
      const labels = {
        task_response: 'Task Response (Trả lời đề & Phát triển luận điểm)',
        coherence_cohesion: 'Coherence & Cohesion (Mạch lạc & Liên kết đoạn)',
        lexical_resource: 'Lexical Resource (Vốn từ & Collocation)',
        grammatical_range_accuracy: 'Grammatical Range & Accuracy (Ngữ pháp & Cấu trúc câu)'
      };

      const criteria = fb.criteria || {};
      for (const [key, title] of Object.entries(labels)) {
        const c = criteria[key] || {};
        const sec = document.createElement('div');
        sec.className = 'crit-section';
        sec.innerHTML = `<div class="crit-title"><span>${title}</span><span>Band ${c.estimated_band ?? '-'}</span></div>`;
        (c.evidence || []).forEach(ev => {
          const item = document.createElement('div');
          item.className = 'ev-item';
          const verifiedTag = ev.quote_verified ? '<span style="color:#4ade80;">[✓ Khớp bài gốc]</span>' : '<span style="color:#f87171;">[⚠ Trích dẫn lệch]</span>';
          item.innerHTML = `
            <div class="ev-quote">"${escapeHtml(ev.quote || '')}" ${verifiedTag} <span class="badge">${escapeHtml(ev.error_code || '')}</span></div>
            <div>${escapeHtml(ev.issue || '')}</div>
            <div class="ev-fix">→ Gợi ý sửa: ${escapeHtml(ev.suggestion || '')}</div>
          `;
          item.onclick = () => highlightQuoteInEssay(ev.quote || '');
          sec.appendChild(item);
        });
        critBox.appendChild(sec);
      }
    }

    async function saveTeacherReview() {
      if (!currentSubmissionId) return;
      const band = parseFloat(document.getElementById('teacherBandInput').value);
      const feedback = document.getElementById('teacherFeedbackInput').value.trim();
      const res = await api(`/api/submissions/${currentSubmissionId}/review`, {
        method: 'POST',
        body: JSON.stringify({
          assessment_id: currentAssessmentId,
          teacher_overall: band,
          teacher_feedback: feedback
        })
      });
      const msg = document.getElementById('reviewSavedMsg');
      msg.textContent = `✓ Đã lưu điểm giáo viên chốt (Band ${res.teacher_overall}) vào hồ sơ học viên!`;
      msg.classList.remove('hidden');
      await loadStudentsList();
    }

    async function loadStudentProgress() {
      const studentId = document.getElementById('progressStudentSelect').value;
      if (!studentId) return;
      const data = await api(`/api/students/${studentId}/progress`);

      const errBox = document.getElementById('recurringErrorsBox');
      if (data.recurring_errors && data.recurring_errors.length > 0) {
        errBox.innerHTML = '<div style="font-size:0.88rem; color:var(--muted); margin-bottom:8px;">Thống kê các lỗi học viên hay mắc nhất (tự động tổng hợp từ các bài viết):</div>' +
          data.recurring_errors.map(e => `<span class="badge" style="margin-right:8px; margin-bottom:6px; display:inline-block; background:#172554; border:1px solid var(--primary);">${e.code}: ${e.error_count} lần (${e.description})</span>`).join('');
      } else {
        errBox.innerHTML = '<div style="color:var(--muted); font-size:0.88rem;">Chưa có thống kê lỗi cho học viên này.</div>';
      }

      const tbody = document.getElementById('historyTableBody');
      tbody.innerHTML = '';
      (data.submissions_history || []).forEach(row => {
        const tr = document.createElement('tr');
        const dateStr = row.assessed_at ? new Date(row.assessed_at).toLocaleString('vi-VN') : new Date(row.created_at).toLocaleString('vi-VN');
        tr.innerHTML = `
          <td>${dateStr}</td>
          <td>${row.task_type.toUpperCase()}</td>
          <td><span class="badge">${row.rubric_version || 'Chưa chấm'}</span></td>
          <td>${row.task_response ?? '-'} / ${row.coherence ?? '-'} / ${row.lexical ?? '-'} / ${row.grammar ?? '-'}</td>
          <td><b>${row.estimated_overall ?? '-'}</b></td>
          <td style="color:#4ade80; font-weight:700;">${row.teacher_overall ?? 'Chưa duyệt'}</td>
          <td><button class="btn btn-secondary" style="padding:4px 10px; font-size:0.8rem;" onclick="openSubmissionInLab('${row.submission_id}', '${row.assessment_id || ''}')">Mở lại bài</button></td>
        `;
        tbody.appendChild(tr);
      });
    }

    async function openSubmissionInLab(submissionId, assessmentId) {
      const detail = await api(`/api/submissions/${submissionId}`);
      switchTab('writing');
      document.getElementById('studentSelect').value = detail.student_id;
      document.getElementById('taskTypeSelect').value = detail.task_type;
      document.getElementById('promptInput').value = detail.prompt_text;
      document.getElementById('essayInput').value = detail.response_text;
      updateWordCount();

      if (detail.assessments && detail.assessments.length > 0) {
        const chosen = detail.assessments.find(a => a.id === assessmentId) || detail.assessments[0];
        renderAssessment(chosen, detail.response_text);
      }
    }

    initApp();
  </script>
</body>
</html>
"""


MAIN_UPDATE_PY = """from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.api.routes import router
from app.db.database import init_db

UI_FILE = Path(__file__).resolve().parents[2] / "desktop" / "index.html"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="IELTS Copilot Local Backend",
    description="Local IELTS Teaching Assistant API (100% Offline - SQLite + Ollama)",
    version="0.2.0",
    lifespan=lifespan,
)

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


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve_teacher_ui():
    if UI_FILE.exists():
        return UI_FILE.read_text(encoding="utf-8")
    return "<h1>IELTS Copilot UI not found. Run init_ui_mvp.py first.</h1>"
"""


def main() -> None:
    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    (DESKTOP_DIR / "index.html").write_text(UI_HTML, encoding="utf-8")
    (APP_DIR / "repositories" / "store.py").write_text(STORE_UPDATE_PY, encoding="utf-8")
    (APP_DIR / "api" / "routes.py").write_text(ROUTES_UPDATE_PY, encoding="utf-8")
    (APP_DIR / "main.py").write_text(MAIN_UPDATE_PY, encoding="utf-8")

    print("=" * 72)
    print("[✓] ĐÃ KHỞI TẠO GIAO DIỆN WRITING LAB & STUDENT RECORDS (MỐC 3)!")
    print("- Giao diện đã được gắn trực tiếp vào: http://127.0.0.1:8000/")
    print("- File giao diện gốc lưu tại: apps/desktop/index.html")
    print("-> Hãy mở trình duyệt truy cập ngay: http://127.0.0.1:8000/")
    print("=" * 72)


if __name__ == "__main__":
    main()