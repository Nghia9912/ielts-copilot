import math
import os
import re
import time
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT

WHISPER_MODEL_DIR = PROJECT_ROOT / "models" / "whisper"
AUDIO_STORAGE_DIR = PROJECT_ROOT / "data" / "audio"
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".webm", ".ogg"}
MAX_AUDIO_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


def _apply_pyav_and_cuda_dll_patches() -> None:
    try:
        import av
        orig_open = av.open
        if not getattr(orig_open, "_ielts_patched", False):
            def _compat_av_open(*args: Any, **kwargs: Any):
                kwargs.pop("metadata_errors", None)
                return orig_open(*args, **kwargs)
            _compat_av_open._ielts_patched = True
            av.open = _compat_av_open
    except ImportError:
        pass

    # Mượn luôn thư viện cublas64_12.dll có sẵn bên trong Ollama trên Windows
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        ollama_base = Path(local_app_data) / "Programs" / "Ollama"
        if ollama_base.exists():
            for dll_path in ollama_base.rglob("cublas64_12.dll"):
                dll_dir = str(dll_path.parent)
                if dll_dir not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
                    if hasattr(os, "add_dll_directory"):
                        try:
                            os.add_dll_directory(dll_dir)
                        except Exception:
                            pass
                break


_apply_pyav_and_cuda_dll_patches()


def validate_and_resolve_audio_path(filename: str) -> Path:
    AUDIO_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise ValueError(f"Định dạng '{ext}' không được hỗ trợ.")
    resolved = (AUDIO_STORAGE_DIR / safe_name).resolve()
    if AUDIO_STORAGE_DIR.resolve() not in resolved.parents:
        raise ValueError("Truy cập đường dẫn file không hợp lệ.")
    return resolved


def compute_fluency_metrics_from_segments(
    segments: list[dict[str, Any]],
    total_duration: float,
    transcript_text: str,
) -> dict[str, Any]:
    words = re.findall(r"\b[a-zA-Z0-9]+(?:['-][a-zA-Z0-9]+)*\b", transcript_text)
    word_count = len(words)
    speaking_time = 0.0
    total_pause_time = 0.0
    long_pauses = 0
    prev_end = 0.0
    logprobs: list[float] = []

    for idx, seg in enumerate(segments):
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        speaking_time += max(0.0, end - start)
        if idx > 0:
            gap = max(0.0, start - prev_end)
            total_pause_time += gap
            if gap >= 1.2:
                long_pauses += 1
        prev_end = max(prev_end, end)
        if seg.get("avg_logprob") is not None:
            logprobs.append(float(seg["avg_logprob"]))

    effective_duration = max(total_duration, prev_end, speaking_time, 1.0)
    wpm = round((word_count / effective_duration) * 60.0, 1) if word_count > 0 else 0.0
    clarity_pct = round(min(100.0, max(0.0, math.exp(sum(logprobs) / len(logprobs)) * 100.0)), 1) if logprobs else 85.0

    if wpm == 0:
        pace_label = "Chưa có dữ liệu"
    elif wpm < 95:
        pace_label = "Chậm / Ngập ngừng nhiều (<95 WPM)"
    elif wpm <= 165:
        pace_label = "Tự nhiên / Chuẩn IELTS (95–165 WPM)"
    else:
        pace_label = "Nói khá nhanh (>165 WPM)"

    return {
        "duration_seconds": round(effective_duration, 2),
        "speaking_time_seconds": round(speaking_time, 2),
        "total_pause_seconds": round(total_pause_time, 2),
        "long_pause_count": long_pauses,
        "word_count": word_count,
        "words_per_minute": wpm,
        "pace_assessment": pace_label,
        "whisper_clarity_percent": clarity_pct,
    }


class WhisperTranscriber:
    def __init__(self, model_size: str = "small.en") -> None:
        self.model_size = model_size
        self._model = None
        self._device_used = "uninitialized"
        self._force_cpu = False

    def _create_cpu_model(self):
        from faster_whisper import WhisperModel
        self._model = WhisperModel(
            self.model_size,
            device="cpu",
            compute_type="int8",
            cpu_threads=8,
            download_root=str(WHISPER_MODEL_DIR),
        )
        self._device_used = "cpu (int8, 8 threads)"
        self._force_cpu = True
        return self._model

    def _load_model(self):
        _apply_pyav_and_cuda_dll_patches()
        if self._model is not None:
            return self._model
        WHISPER_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        from faster_whisper import WhisperModel
        if self._force_cpu:
            return self._create_cpu_model()
        try:
            self._model = WhisperModel(
                self.model_size,
                device="cuda",
                compute_type="float16",
                download_root=str(WHISPER_MODEL_DIR),
            )
            self._device_used = "cuda (float16)"
        except Exception:
            self._create_cpu_model()
        return self._model

    def _run_inference(self, model: Any, audio_path: Path) -> tuple[list[Any], Any]:
        segments_iter, info = model.transcribe(
            str(audio_path),
            language="en",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
        )
        return list(segments_iter), info

    def transcribe_file(self, audio_path: Path) -> dict[str, Any]:
        _apply_pyav_and_cuda_dll_patches()
        if not audio_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file âm thanh: {audio_path.name}")

        start_t = time.perf_counter()
        model = self._load_model()
        try:
            raw_segments, info = self._run_inference(model, audio_path)
        except Exception as exc:
            err_msg = str(exc).lower()
            if not self._force_cpu and any(k in err_msg for k in ("cublas", "cudnn", "cuda", "dll")):
                cpu_model = self._create_cpu_model()
                raw_segments, info = self._run_inference(cpu_model, audio_path)
            else:
                raise

        seg_list: list[dict[str, Any]] = []
        full_texts: list[str] = []
        for s in raw_segments:
            text_clean = s.text.strip()
            if text_clean:
                full_texts.append(text_clean)
                seg_list.append({
                    "start": round(float(s.start), 2),
                    "end": round(float(s.end), 2),
                    "text": text_clean,
                    "avg_logprob": round(float(s.avg_logprob), 4) if s.avg_logprob is not None else None,
                })

        transcript_text = " ".join(full_texts).strip()
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        fluency_metrics = compute_fluency_metrics_from_segments(seg_list, duration, transcript_text)
        elapsed = round(time.perf_counter() - start_t, 2)

        return {
            "model_name": f"faster-whisper ({self.model_size})",
            "device": self._device_used,
            "elapsed_seconds": elapsed,
            "transcript_text": transcript_text,
            "segments": seg_list,
            "audio_metrics": fluency_metrics,
        }
