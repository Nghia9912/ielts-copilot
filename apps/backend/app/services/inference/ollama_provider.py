import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

from app.core.config import BASELINE_MODEL, DEFAULT_MODEL, OLLAMA_BASE_URL


class OllamaProvider:
    """Lớp giao tiếp độc lập với Ollama Local Runtime (Hỗ trợ cả Text LLM và Vision Multimodal)."""

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
            env["OLLAMA_MODELS"] = r"F:\AI-Data\ollama\models"
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
        timeout_sec: int = 120,
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
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Lỗi kết nối hoặc quá thời gian chờ Ollama ({self.base_url}): {exc}") from exc

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
