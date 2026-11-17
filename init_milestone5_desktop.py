#!/usr/bin/env python3
"""IELTS Copilot - Trình khởi tạo Mốc 5 (Hoàn thiện MVP):
1. Bổ sung Vision AI (dùng gemma3:4b sẵn có trong Ollama) để đọc ảnh biểu đồ Writing Task 1
   ra bảng số liệu đối chiếu (Chart Reference Data) trước khi chấm Task Achievement.
2. Bổ sung tính năng Backup / Restore SQLite Database và Xóa học viên kèm dọn sạch file audio (Mục 11).
3. Tạo ứng dụng Desktop 1 chạm (Start_IELTS_Copilot.bat) tự bật/tắt Backend không để chạy ngầm + Cấu hình Tauri 2.

Chạy trực tiếp tại thư mục F:\\ielts-copilot:
    .\\.venv\\Scripts\\python.exe init_milestone5_desktop.py
"""

import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path.cwd()
BACKEND_DIR = PROJECT_ROOT / "apps" / "backend"
APP_DIR = BACKEND_DIR / "app"
DESKTOP_DIR = PROJECT_ROOT / "apps" / "desktop"
TAURI_DIR = DESKTOP_DIR / "src-tauri"
DATA_DIR = PROJECT_ROOT / "data"


OLLAMA_PROVIDER_M5_PY = r'''import base64
import json
import time
import urllib.error
import urllib.request
from typing import Any

from app.core.config import BASELINE_MODEL, DEFAULT_MODEL, OLLAMA_BASE_URL


class OllamaProvider:
    """Lớp giao tiếp độc lập với Ollama Local Runtime (Hỗ trợ cả Text LLM và Vision Multimodal)."""

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

    def extract_task1_chart_data(
        self,
        image_bytes: bytes,
        prompt_text: str = "",
        vision_model: str = BASELINE_MODEL,
        timeout_sec: int = 120,
    ) -> dict[str, Any]:
        """Dùng model Vision (mặc định gemma3:4b đã tải ở Mốc 1) để trích xuất số liệu chuẩn từ ảnh biểu đồ Task 1."""
        b64_img = base64.b64encode(image_bytes).decode("ascii")
        schema = {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "description": "line_graph, bar_chart, pie_chart, table, map, or process_diagram",
                },
                "overall_trend_summary": {
                    "type": "string",
                    "description": "1-2 sentences summarizing the main overview/trend required for Band 7+ Task Achievement.",
                },
                "key_data_points": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exact figures, years, categories, highest/lowest values, and notable comparisons extracted from the image.",
                },
            },
            "required": ["chart_type", "overall_trend_summary", "key_data_points"],
        }

        sys_prompt = (
            "You are an IELTS Academic Writing Task 1 Chart Analyzer. "
            "Examine the attached chart/table/diagram carefully and extract all exact numbers, categories, "
            "time periods, highest/lowest points, and the main overview trend into structured JSON."
        )
        usr_prompt = f"Task 1 Prompt: {prompt_text.strip() or 'Summarize the main features and make comparisons.'}\nExtract exact reference data from this image."

        payload = {
            "model": vision_model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": usr_prompt, "images": [b64_img]},
            ],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 4096},
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
            raise RuntimeError(
                f"Lỗi khi gọi Vision model '{vision_model}' qua Ollama ({exc}). "
                "Hãy đảm bảo bạn đã tải model hỗ trợ ảnh như gemma3:4b."
            ) from exc

        elapsed = round(time.perf_counter() - start, 2)
        content = body.get("message", {}).get("content", "{}")
        parsed = json.loads(content)
        parsed["elapsed_seconds"] = elapsed
        parsed["vision_model"] = vision_model
        return parsed

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
'''


PROMPT_V2_M5_PY = r'''from typing import Any

RUBRIC_VERSION = "ielts-writing-v2.1-cambridge-calibrated"

ALLOWED_CRITERION_ERROR_CODES: dict[str, set[str]] = {
    "task_response": {
        "TR_UNDERDEVELOPED",
        "TR_UNBALANCED",
        "TR_OFF_TOPIC",
        "TR_UNCLEAR_POSITION",
        "TA_NO_OVERVIEW",
        "TA_INACCURATE_DATA",
        "TA_KEY_FEATURE_MISSING",
    },
    "coherence_cohesion": {"CC_COHESION", "CC_PARAGRAPHING", "CC_REFERENCING", "CC_PROGRESSION"},
    "lexical_resource": {"COLLOCATION", "WORD_CHOICE", "SPELLING", "REGISTER"},
    "grammatical_range_accuracy": {"ARTICLE", "PREPOSITION", "SVA", "TENSE", "PUNCTUATION", "SYNTAX"},
}


def build_calibrated_writing_prompts(
    prompt_text: str,
    essay_text: str,
    meta: dict[str, Any],
) -> tuple[str, str]:
    is_task1 = meta["task_type"] == "task1"
    task_label = "IELTS Academic Writing Task 1 (Chart/Report)" if is_task1 else "IELTS Academic Writing Task 2 (Essay)"

    if is_task1:
        tr_instructions = (
            "   - 'task_response' (Task Achievement for Task 1) ONLY evaluates:\n"
            "     * Does the report include a clear Overview paragraph summarizing main trends/stages? (If missing or unclear, use error_code: TA_NO_OVERVIEW).\n"
            "     * Are the figures/comparisons accurate compared to the provided CHART REFERENCE DATA? (If student cites wrong numbers or misreads trends, use error_code: TA_INACCURATE_DATA).\n"
            "     * Are key features adequately highlighted and compared rather than mechanically listing every number? (Use error_code: TA_KEY_FEATURE_MISSING).\n"
            "     * Band 7.0 Task Achievement requires a clear overview of main trends/stages AND accurate highlighting of key features, even if minor details could be fuller."
        )
    else:
        tr_instructions = (
            "   - 'task_response' (Task Response for Task 2) ONLY evaluates:\n"
            "     * Did the writer address all parts of the prompt? Is there a clear position? Are main ideas extended and supported?\n"
            "     * Allowed error_code: TR_UNDERDEVELOPED, TR_UNBALANCED, TR_OFF_TOPIC, TR_UNCLEAR_POSITION."
        )

    system_prompt = f"""You are a certified Senior Cambridge IELTS Writing Examiner evaluating an {task_label} script.
Your goal is to assign accurate, fair, Cambridge-calibrated band scores (0.0 to 9.0, in 0.5 increments).

=== CRITICAL CALIBRATION RULES (DO NOT VIOLATE) ===
1. NO CROSS-CRITERION DOUBLE PENALIZATION:
   - NEVER penalize 'task_response' or 'coherence_cohesion' for grammar, article, preposition, punctuation, or vocabulary/collocation slips!
{tr_instructions}
   - 'coherence_cohesion' ONLY evaluates: Paragraphing, logical progression, topic sentences, and cohesive devices (CC_COHESION, CC_PARAGRAPHING, CC_REFERENCING, CC_PROGRESSION).
   - 'lexical_resource' ONLY evaluates: Vocabulary range, collocations, word choice, register, and spelling (COLLOCATION, WORD_CHOICE, SPELLING, REGISTER).
   - 'grammatical_range_accuracy' ONLY evaluates: Variety of complex structures, tenses, articles, prepositions, and punctuation (ARTICLE, PREPOSITION, SVA, TENSE, PUNCTUATION, SYNTAX).

2. OFFICIAL CAMBRIDGE BAND 7.0 ANCHOR:
   - Award 6.5 or 7.0 for Lexical Resource and Grammar if the writer uses varied vocabulary and complex structures with clear meaning, EVEN IF a few occasional errors in collocation, word choice, articles, or punctuation occur. Only drop to 5.0–5.5 if errors are frequent and obscure communication.

3. VERBATIM QUOTES & CONCISE EVIDENCE:
   - Include at most 2 key evidence items per criterion.
   - Every 'quote' MUST be copied 100% verbatim from the Student Essay.
"""

    user_prompt = (
        f"=== TASK TYPE ===\n{task_label}\n\n"
        f"=== PREPROCESSING METRICS ===\n"
        f"- Word count: {meta['word_count']} words (Minimum required: {meta['min_words_required']})\n"
        f"- Underlength penalty applicable: {meta['is_underlength']}\n"
        f"- Paragraph count: {meta['paragraph_count']} | Sentence count: {meta['sentence_count']}\n\n"
        f"=== PROMPT & CHART REFERENCE DATA ===\n{prompt_text.strip()}\n\n"
        f"=== STUDENT SUBMISSION ===\n{essay_text.strip()}\n"
    )
    return system_prompt, user_prompt
'''


ROUTES_ADDITIONS_PY = r'''
# ================= BỔ SUNG MỐC 5: TASK 1 CHART VISION + BACKUP/RESTORE + DELETE STUDENT =================
import shutil
from datetime import datetime
from app.core.config import DB_PATH, DATA_DIR


@router.post("/task1/extract-chart")
async def extract_task1_chart_reference(
    prompt_text: str = Form(""),
    vision_model: str = Form("gemma3:4b"),
    chart_image: UploadFile = File(...),
):
    """Đọc ảnh biểu đồ Writing Task 1 bằng Vision AI cục bộ (gemma3:4b) và trả về JSON số liệu chuẩn."""
    ext = Path(chart_image.filename or "chart.png").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ ảnh .png, .jpg, .jpeg, .webp")
    img_bytes = await chart_image.read()
    if len(img_bytes) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Ảnh biểu đồ vượt quá 15MB.")
    try:
        extracted = llm.extract_task1_chart_data(
            image_bytes=img_bytes,
            prompt_text=prompt_text,
            vision_model=vision_model,
        )
        return extracted
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/students/{student_id}")
def delete_student_and_files(student_id: str):
    """Xóa hồ sơ học viên kèm toàn bộ bài làm và các file ghi âm liên quan (Mục 11 Bảo mật & Quyền riêng tư)."""
    student = repo.get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Không tìm thấy học viên.")

    from app.db.database import db_session
    removed_audio_files = 0
    with db_session() as conn:
        audio_rows = conn.execute(
            "SELECT source_audio_path FROM submissions WHERE student_id = ? AND source_audio_path IS NOT NULL",
            (student_id,),
        ).fetchall()
        for r in audio_rows:
            try:
                p = validate_and_resolve_audio_path(r["source_audio_path"])
                if p.exists():
                    p.unlink()
                    removed_audio_files += 1
            except Exception:
                pass
        conn.execute("DELETE FROM students WHERE id = ?", (student_id,))

    return {"status": "deleted", "student_id": student_id, "removed_audio_files": removed_audio_files}


@router.post("/system/backup")
def create_database_backup():
    """Tạo bản sao lưu (Backup) cơ sở dữ liệu SQLite sang F:\ielts-copilot\data\backups."""
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"ielts_copilot_backup_{stamp}.db"
    if DB_PATH.exists():
        shutil.copy2(DB_PATH, backup_file)
    backups = sorted([f.name for f in backup_dir.glob("*.db")], reverse=True)
    return {"status": "ok", "backup_created": backup_file.name, "available_backups": backups}


@router.get("/system/backups")
def list_database_backups():
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backups = sorted([f.name for f in backup_dir.glob("*.db")], reverse=True)
    return {"available_backups": backups}


@router.post("/system/restore/{backup_filename}")
def restore_database_backup(backup_filename: str):
    """Khôi phục (Restore) cơ sở dữ liệu từ bản sao lưu đã chọn."""
    backup_dir = (DATA_DIR / "backups").resolve()
    safe_name = Path(backup_filename).name
    source_file = (backup_dir / safe_name).resolve()
    if backup_dir not in source_file.parents or not source_file.exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy file backup hợp lệ.")
    shutil.copy2(source_file, DB_PATH)
    return {"status": "restored", "restored_from": safe_name}
'''


START_DESKTOP_BAT = r"""@echo off
chcp 65001 >nul
title IELTS Copilot - Local Desktop Assistant (F:\ielts-copilot)
echo ============================================================================
echo   IELTS COPILOT - KHOI DONG UNG DUNG DESKTOP OFFLINE (LENOVO LEGION 5)
echo ============================================================================

cd /d "%~dp0"
set OLLAMA_MODELS=F:\AI-Data\ollama\models
set HF_HOME=F:\AI-Data\huggingface
set PYTHONPATH=apps\backend

echo [1/3] Kiem tra tien trinh Backend cu tren cong 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr "127.0.0.1:8000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo [2/3] Khoi chay Local FastAPI Backend ngam tai http://127.0.0.1:8000 ...
start "IELTS_Copilot_Backend" /min ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo Doi Backend khoi dong (3 giay)...
timeout /t 3 /nobreak >nul

echo [3/3] Mo cua so Desktop App IELTS Copilot...
where msedge >nul 2>&1
if %errorlevel% equ 0 (
    start /wait msedge --app=http://127.0.0.1:8000 --window-size=1480,920
) else (
    start http://127.0.0.1:8000
    echo Nhan phim bat ky khi ban muon dong Backend Server...
    pause >nul
)

echo Dang dong tien trinh Backend de khong chay ngam...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr "127.0.0.1:8000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo Da dong hoan toan IELTS Copilot!
"""


TAURI_CONF_JSON = """{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "IELTS Copilot",
  "version": "0.1.0",
  "identifier": "com.local.ieltscopilot",
  "build": {
    "frontendDist": "../",
    "devUrl": "http://127.0.0.1:8000"
  },
  "app": {
    "windows": [
      {
        "title": "IELTS Copilot — Local Teaching Assistant",
        "width": 1440,
        "height": 900,
        "resizable": true,
        "fullscreen": false
      }
    ],
    "security": {
      "csp": "default-src 'self' http://127.0.0.1:8000; connect-src 'self' http://127.0.0.1:8000; media-src 'self' http://127.0.0.1:8000 blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
    }
  }
}
"""


TAURI_CAPABILITIES_JSON = """{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "default",
  "description": "Minimal capabilities for local offline IELTS Copilot teacher desktop app",
  "windows": ["main"],
  "permissions": [
    "core:default"
  ]
}
"""


def patch_ui_for_task1_and_backup(html_path: Path) -> None:
    if not html_path.exists():
        return
    html = html_path.read_text(encoding="utf-8")

    task1_box_html = """          <label>Đề bài (Prompt)</label>
          <textarea id="promptInput" rows="3" placeholder="Dán đề bài IELTS Writing vào đây..."></textarea>

          <!-- KHUNG TRÍCH XUẤT SỐ LIỆU BIỂU ĐỒ TASK 1 BẰNG VISION AI -->
          <div id="task1ChartBox" class="hidden" style="background:#0f172a; border:1px dashed var(--primary); border-radius:10px; padding:12px; margin-bottom:14px;">
            <label style="color:var(--primary);">📊 Đối chiếu Biểu đồ Writing Task 1 (Tải ảnh biểu đồ để AI Vision trích xuất số liệu chuẩn hoặc tự nhập bảng số liệu):</label>
            <div style="display:flex; gap:10px; align-items:center; margin-top:6px; margin-bottom:8px;">
              <input type="file" id="task1ImageFile" accept=".png,.jpg,.jpeg,.webp" style="margin:0; flex:1;" />
              <button id="extractChartBtn" class="btn btn-secondary" style="border:1px solid var(--primary); color:var(--primary);" onclick="extractTask1Chart()">👁 Đọc số liệu từ Ảnh (gemma3:4b)</button>
            </div>
            <textarea id="task1ChartDataInput" rows="3" style="margin:0;" placeholder="Số liệu trích xuất từ biểu đồ (Chart Reference Data) sẽ hiện tại đây để đối chiếu khi chấm Task 1..."></textarea>
          </div>"""

    if 'id="task1ChartBox"' not in html:
        html = html.replace(
            '          <label>Đề bài (Prompt)</label>\n          <textarea id="promptInput" rows="3" placeholder="Dán đề bài IELTS Writing vào đây..."></textarea>',
            task1_box_html,
        )

    if "triggerBackup()" not in html:
        html = html.replace(
            '<button class="tab-btn" onclick="switchTab(\'students\')">3. Student Records</button>',
            '<button class="tab-btn" onclick="switchTab(\'students\')">3. Student Records</button>\n'
            '      <button class="tab-btn" style="color:#4ade80;" onclick="triggerBackup()">💾 Backup DB</button>',
        )

    js_additions = """
    async function extractTask1Chart() {
      const fileInput = document.getElementById('task1ImageFile');
      if (!fileInput.files || fileInput.files.length === 0) {
        return alert('Hãy chọn 1 file ảnh biểu đồ Task 1 (.png, .jpg, .webp) trước!');
      }
      const btn = document.getElementById('extractChartBtn');
      btn.disabled = true;
      btn.textContent = 'Đang đọc biểu đồ bằng gemma3:4b...';
      try {
        const fd = new FormData();
        fd.append('prompt_text', document.getElementById('promptInput').value.trim());
        fd.append('vision_model', 'gemma3:4b');
        fd.append('chart_image', fileInput.files[0]);
        const res = await api('/api/task1/extract-chart', { method: 'POST', body: fd });
        const summary = [
          `[Chart Type]: ${res.chart_type || 'N/A'}`,
          `[Expected Overview]: ${res.overall_trend_summary || ''}`,
          `[Key Reference Data]:`,
          ...(res.key_data_points || []).map(p => `- ${p}`)
        ].join('\\n');
        document.getElementById('task1ChartDataInput').value = summary;
      } catch (e) {
        alert('Lỗi trích xuất ảnh biểu đồ: ' + e.message);
      } finally {
        btn.disabled = false;
        btn.textContent = '👁 Đọc số liệu từ Ảnh (gemma3:4b)';
      }
    }

    async function triggerBackup() {
      try {
        const res = await api('/api/system/backup', { method: 'POST' });
        alert(`✓ Đã tạo bản sao lưu Database an toàn tại:\\nF:\\\\ielts-copilot\\\\data\\\\backups\\\\${res.backup_created}`);
      } catch (e) {
        alert('Lỗi khi sao lưu Database: ' + e.message);
      }
    }
"""
    if "async function extractTask1Chart()" not in html:
        html = html.replace(
            "function updateWordCount() {",
            js_additions
            + "\n    function updateWordCount() {\n      const isT1 = document.getElementById('taskTypeSelect').value === 'task1';\n      const t1Box = document.getElementById('task1ChartBox');\n      if (t1Box) t1Box.classList.toggle('hidden', !isT1);",
        )

    old_submit_line = "const promptText = document.getElementById('promptInput').value.trim();"
    new_submit_line = (
        "let promptText = document.getElementById('promptInput').value.trim();\n"
        "      const chartRef = document.getElementById('task1ChartDataInput') ? document.getElementById('task1ChartDataInput').value.trim() : '';\n"
        "      if (taskType === 'task1' && chartRef) {\n"
        "        promptText += `\\n\\n[CHART REFERENCE DATA FOR TASK 1 VERIFICATION]:\\n${chartRef}`;\n"
        "      }"
    )
    if "CHART REFERENCE DATA FOR TASK 1 VERIFICATION" not in html and old_submit_line in html:
        html = html.replace(old_submit_line, new_submit_line, 1)

    html_path.write_text(html, encoding="utf-8")


def main() -> None:
    (APP_DIR / "services" / "inference" / "ollama_provider.py").write_text(OLLAMA_PROVIDER_M5_PY, encoding="utf-8")
    (APP_DIR / "prompts" / "ielts_writing_v2.py").write_text(PROMPT_V2_M5_PY, encoding="utf-8")

    db_file = DATA_DIR / "ielts_copilot.db"
    if db_file.exists():
        conn = sqlite3.connect(str(db_file))
        t1_tags = [
            ("tag-ta-no-overview", "TA_NO_OVERVIEW", "task_response", "Thiếu đoạn Overview tóm tắt xu hướng chính trong Writing Task 1"),
            ("tag-ta-inaccurate", "TA_INACCURATE_DATA", "task_response", "Trích dẫn sai số liệu hoặc sai xu hướng so với biểu đồ gốc Task 1"),
            ("tag-ta-missing-key", "TA_KEY_FEATURE_MISSING", "task_response", "Bỏ sót đặc điểm nổi bật hoặc không có sự so sánh giữa các nhóm trong Task 1"),
        ]
        for tid, code, cat, desc in t1_tags:
            conn.execute(
                "INSERT OR IGNORE INTO error_tags (id, code, category, description) VALUES (?, ?, ?, ?)",
                (tid, code, cat, desc),
            )
        conn.commit()
        conn.close()

    routes_file = APP_DIR / "api" / "routes.py"
    routes_code = routes_file.read_text(encoding="utf-8")
    if "/task1/extract-chart" not in routes_code:
        routes_file.write_text(routes_code + "\n" + ROUTES_ADDITIONS_PY, encoding="utf-8")

    patch_ui_for_task1_and_backup(DESKTOP_DIR / "index.html")

    (PROJECT_ROOT / "Start_IELTS_Copilot.bat").write_text(START_DESKTOP_BAT, encoding="utf-8")
    (TAURI_DIR / "capabilities").mkdir(parents=True, exist_ok=True)
    (TAURI_DIR / "tauri.conf.json").write_text(TAURI_CONF_JSON, encoding="utf-8")
    (TAURI_DIR / "capabilities" / "default.json").write_text(TAURI_CAPABILITIES_JSON, encoding="utf-8")

    print("=" * 72)
    print("[✓] ĐÃ HOÀN TẤT MỐC 5: TASK 1 VISION CHART + BACKUP/RESTORE + DESKTOP LAUNCHER!")
    print("- Đã tích hợp đọc ảnh biểu đồ Task 1 bằng gemma3:4b (Vision) -> JSON số liệu đối chiếu.")
    print("- Đã thêm nút '💾 Backup DB' trên thanh công cụ và API xóa học viên kèm file audio.")
    print("- Đã tạo ứng dụng khởi chạy 1 chạm: F:\\ielts-copilot\\Start_IELTS_Copilot.bat")
    print("=" * 72)


if __name__ == "__main__":
    main()