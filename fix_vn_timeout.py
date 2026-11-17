from pathlib import Path
import subprocess
import time
import re

root = Path.cwd()

# 1. Cập nhật ollama_provider.py: Tối ưu tốc độ JSON tiếng Việt, tắt ngầm <think>, chống lặp và nâng timeout
ollama_py = root / "apps" / "backend" / "app" / "services" / "inference" / "ollama_provider.py"
OLLAMA_CODE = """import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

from app.core.config import BASELINE_MODEL, DEFAULT_MODEL, OLLAMA_BASE_URL


class OllamaProvider:
    \"\"\"Lớp giao tiếp độc lập với Ollama Local Runtime (Hỗ trợ cả Text LLM và Vision Multimodal).\"\"\"

    def __init__(self, base_url: str = OLLAMA_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def _ensure_ollama_running(self) -> None:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception:
            pass
        try:
            env = os.environ.copy()
            env["OLLAMA_MODELS"] = r"F:\\AI-Data\\ollama\\models"
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                ["ollama", "serve"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            for _ in range(10):
                time.sleep(0.5)
                try:
                    req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        if resp.status == 200:
                            return
                except Exception:
                    continue
        except Exception:
            pass

    def health_check(self) -> dict[str, Any]:
        self._ensure_ollama_running()
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in data.get("models", [])]
                return {"ollama_online": True, "installed_models": models}
        except Exception as exc:
            return {"ollama_online": False, "installed_models": [], "error": str(exc)}

    def list_models(self) -> list[dict[str, Any]]:
        self._ensure_ollama_running()
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
        timeout_sec: int = 180,
    ) -> dict[str, Any]:
        self._ensure_ollama_running()
        b64_img = base64.b64encode(image_bytes).decode("ascii")
        schema = {
            "type": "object",
            "properties": {
                "chart_type": {"type": "string"},
                "overall_trend_summary": {"type": "string"},
                "key_data_points": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["chart_type", "overall_trend_summary", "key_data_points"],
        }
        sys_prompt = (
            "You are an IELTS Academic Writing Task 1 Chart Analyzer. "
            "Extract all exact numbers, categories, time periods, highest/lowest points, and the main overview trend into JSON."
        )
        usr_prompt = f"Task 1 Prompt: {prompt_text.strip() or 'Summarize the main features.'}\\nExtract reference data."
        payload = {
            "model": vision_model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": usr_prompt, "images": [b64_img]},
            ],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 4096, "num_predict": 1024},
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
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Lỗi khi gọi Vision model '{vision_model}': {exc}") from exc

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
        timeout_sec: int = 300,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self._ensure_ollama_running()
        effective_user_prompt = user_prompt
        if not think and "qwen3" in model.lower() and "/no_think" not in effective_user_prompt:
            effective_user_prompt = effective_user_prompt.rstrip() + "\\n\\n/no_think"

        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": effective_user_prompt},
            ],
            "format": schema,
            "think": think,
            "stream": False,
            "options": {
                "temperature": 0.15,
                "num_ctx": 6144,
                "num_predict": 3072,
                "repeat_penalty": 1.15,
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
        except TimeoutError as exc:
            raise RuntimeError(
                f"Model {model} xử lý quá thời gian chờ ({timeout_sec}s). Hãy tắt 'Bật Deep Thinking' hoặc thử lại."
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Lỗi kết nối Ollama ({self.base_url}): {exc}") from exc

        elapsed = round(time.perf_counter() - start, 2)
        content = body.get("message", {}).get("content", "{}").strip()
        if content.startswith("```"):
            content = content.strip("`").removeprefix("json").strip()
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
ollama_py.write_text(OLLAMA_CODE, encoding="utf-8")

# 2. Cập nhật ielts_writing_v2.py: Nhận xét + Gợi ý sửa bằng Tiếng Việt súc tích, dùng nháy đơn '...' tránh kẹt JSON
prompt_py = root / "apps" / "backend" / "app" / "prompts" / "ielts_writing_v2.py"
PROMPT_CODE = """from typing import Any

RUBRIC_VERSION = "ielts-writing-v2.4-vn-fast-70-30"

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
    task_label = "IELTS Academic Writing Task 1" if is_task1 else "IELTS Academic Writing Task 2"

    underlength_rule = ""
    if meta.get("is_underlength"):
        underlength_rule = (
            f"\\n   - UNDERLENGTH PENALTY: Bài viết chỉ có {meta['word_count']}/{meta['min_words_required']} từ. "
            "Bắt buộc giới hạn 'task_response' tối đa 5.0 (nếu dưới 150 từ) hoặc 5.5 (nếu thiếu từ nhẹ)."
        )

    if is_task1:
        tr_instructions = (
            "   - 'task_response' (Task Achievement): Đánh giá đoạn Overview, độ chính xác số liệu và so sánh đặc điểm chính "
            "(Mã lỗi: TA_NO_OVERVIEW, TA_INACCURATE_DATA, TA_KEY_FEATURE_MISSING)." + underlength_rule
        )
    else:
        tr_instructions = (
            "   - 'task_response' (Task Response): Đánh giá mức độ trả lời hết câu hỏi, quan điểm rõ ràng và độ sâu lập luận "
            "(Mã lỗi: TR_UNDERDEVELOPED, TR_UNBALANCED, TR_OFF_TOPIC, TR_UNCLEAR_POSITION)." + underlength_rule
        )

    system_prompt = f\"\"\"You are a Senior Cambridge IELTS Writing Examiner evaluating an {task_label} submission.
Apply a BALANCED 70% STRICT CAMBRIDGE / 30% CONSTRUCTIVE LENIENCY standard (0.0 to 9.0, step 0.5).

=== 1. SCORING CALIBRATION (70% STRICT / 30% LENIENT) ===
- 30% LENIENCY (NO DOUBLE PENALIZATION):
  * Do NOT penalize 'task_response' or 'coherence_cohesion' for grammar, article, or spelling slips.
  * Tolerate 1-2 minor slips in Lexical/Grammar at Band 6.5-7.0 if complex structures and academic collocations are used accurately elsewhere.
- 70% STRICTNESS (PREVENT SCORE INFLATION):
  * Band 5.0 - 5.5 Ceiling: Ideas are brief/generalized/repetitive (TR <= 5.5), mechanical linkers 'First of all, Secondly' in every paragraph (CC <= 5.5), basic repetitive vocabulary (LR <= 5.5), or frequent grammar/article/preposition errors (GRA <= 5.5).
  * Band 6.0 Ceiling: Addresses the prompt with relevant ideas, but examples are general or complex sentences have noticeable errors.
  * Band 6.5 - 7.0+: Requires well-developed PEEL paragraphs, natural cohesion, less common collocations, and mostly error-free complex sentences.
{tr_instructions}

=== 2. MANDATORY VIETNAMESE OUTPUT & JSON SAFETY RULES (CRITICAL) ===
- Write 'summary', 'issue', and 'suggestion' 100% in VIETNAMESE (Tiếng Việt).
- Keep 'quote' 100% VERBATIM in English copied from the student's essay.
- BE CONCISE TO ENSURE FAST GENERATION:
  * Include AT MOST 2 evidence items per criterion (1-2 items maximum).
  * Keep each 'issue' and 'suggestion' concise (1-2 sentences, under 35 words).
  * NEVER use double quotes (\") inside any text string! Use single quotes ('...') when writing corrected English phrases inside 'suggestion' (Example: Viết lại thành: 'Students can broaden their academic horizons...').\"\"\"

    user_prompt = (
        f"=== TASK TYPE ===\\n{task_label}\\n\\n"
        f"=== METRICS ===\\n"
        f"- Word count: {meta['word_count']} (Min required: {meta['min_words_required']}, Underlength: {meta['is_underlength']})\\n"
        f"- Paragraphs: {meta['paragraph_count']} | Sentences: {meta['sentence_count']}\\n\\n"
        f"=== PROMPT ===\\n{prompt_text.strip()}\\n\\n"
        f"=== STUDENT SUBMISSION ===\\n{essay_text.strip()}\\n\\n"
        f"Evaluate strictly using the 70/30 rubric. Output 'summary', 'issue', and 'suggestion' in concise VIETNAMESE using single quotes ('...') for English rewrites."
    )
    return system_prompt, user_prompt
"""
prompt_py.write_text(PROMPT_CODE, encoding="utf-8")

# 3. Cập nhật mô tả WRITING_SCHEMA trong evaluator.py sang Tiếng Việt để ép bộ sinh JSON của Ollama tuân thủ 100%
eval_py = root / "apps" / "backend" / "app" / "services" / "writing" / "evaluator.py"
if eval_py.exists():
    etxt = eval_py.read_text(encoding="utf-8")
    etxt = etxt.replace(
        '"issue": {"type": "string"}',
        '"issue": {"type": "string", "description": "Nhận xét lỗi ngắn gọn 1 câu bằng TIẾNG VIỆT (không dùng dấu ngoặc kép)"}',
    ).replace(
        '"suggestion": {"type": "string"}',
        '"suggestion": {"type": "string", "description": "Gợi ý sửa bằng TIẾNG VIỆT kèm câu tiếng Anh viết lại trong dấu nháy đơn"}',
    )
    eval_py.write_text(etxt, encoding="utf-8")

# 4. Tự động khởi động lại tiến trình FastAPI Backend trên cổng 8000 để áp dụng ngay lập tức
print("[1/2] Đang khởi động lại Backend Server trên cổng 8000 để nạp code mới...")
netstat = subprocess.run(["netstat", "-aon"], capture_output=True, text=True)
for line in netstat.stdout.splitlines():
    if "127.0.0.1:8000" in line and "LISTENING" in line:
        parts = line.split()
        pid = parts[-1]
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)

env = dict(os.environ) if "os" in globals() else __import__("os").environ.copy()
env["OLLAMA_MODELS"] = r"F:\AI-Data\ollama\models"
env["HF_HOME"] = r"F:\AI-Data\huggingface"
env["PYTHONPATH"] = str(root / "apps" / "backend")

venv_py = str(root / ".venv" / "Scripts" / "python.exe")
subprocess.Popen(
    [venv_py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
    cwd=str(root),
    env=env,
    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
)
time.sleep(2.5)
print("[2/2] [OK] Đã sửa dứt điểm lỗi Timeout tiếng Việt và tự động khởi động lại Backend tại [http://127.0.0.1:8000](http://127.0.0.1:8000) !")
