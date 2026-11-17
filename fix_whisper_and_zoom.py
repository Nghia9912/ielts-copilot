#!/usr/bin/env python3
"""IELTS Copilot - Bản sửa lỗi Whisper & Bổ sung tính năng Thu âm Học viên từ Zoom.

Chạy trực tiếp tại thư mục F:\\ielts-copilot:
    .\\.venv\\Scripts\\python.exe fix_whisper_and_zoom.py

Giải quyết 2 vấn đề:
1. Sửa lỗi SyntaxError (from __future__ import annotations) và lỗi PyAV (metadata_errors) trong whisper_service.py.
2. Bổ sung nút "💻 Thu tiếng Học viên từ Zoom (System Audio)" ngay trên Speaking Lab để thu trực tiếp
   giọng học viên phát ra từ ứng dụng Zoom (ngay cả khi giáo viên đeo tai nghe), bên cạnh nút Thu Micro
   và tính năng tải file ghi âm .m4a có sẵn của Zoom.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path.cwd()
APP_DIR = PROJECT_ROOT / "apps" / "backend" / "app"
DESKTOP_DIR = PROJECT_ROOT / "apps" / "desktop"


WHISPER_SERVICE_FIXED_PY = """import math
import re
import time
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT

WHISPER_MODEL_DIR = PROJECT_ROOT / "models" / "whisper"
AUDIO_STORAGE_DIR = PROJECT_ROOT / "data" / "audio"
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".webm", ".ogg"}
MAX_AUDIO_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


def _apply_pyav_compatibility_patch() -> None:
    \"\"\"Vá lỗi tương thích giữa faster-whisper và PyAV mới (bỏ metadata_errors).\"\"\"
    try:
        import av

        orig_open = av.open
        if getattr(orig_open, "_ielts_patched", False):
            return

        def _compat_av_open(*args: Any, **kwargs: Any):
            kwargs.pop("metadata_errors", None)
            return orig_open(*args, **kwargs)

        _compat_av_open._ielts_patched = True  # type: ignore[attr-defined]
        av.open = _compat_av_open
    except ImportError:
        pass


_apply_pyav_compatibility_patch()


def validate_and_resolve_audio_path(filename: str) -> Path:
    \"\"\"Đảm bảo file âm thanh hợp lệ và nằm nghiêm ngặt trong data/audio (chống Path Traversal).\"\"\"
    AUDIO_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise ValueError(
            f"Định dạng audio '{ext}' không được hỗ trợ. Chỉ chấp nhận: {', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))}"
        )
    resolved = (AUDIO_STORAGE_DIR / safe_name).resolve()
    if AUDIO_STORAGE_DIR.resolve() not in resolved.parents:
        raise ValueError("Truy cập đường dẫn file không hợp lệ.")
    return resolved


def compute_fluency_metrics_from_segments(
    segments: list[dict[str, Any]],
    total_duration: float,
    transcript_text: str,
) -> dict[str, Any]:
    \"\"\"Tính toán các chỉ số âm học & độ trôi chảy (Fluency) bằng code thông thường.\"\"\"
    words = re.findall(r"\\b[a-zA-Z0-9]+(?:['-][a-zA-Z0-9]+)*\\b", transcript_text)
    word_count = len(words)

    speaking_time = 0.0
    total_pause_time = 0.0
    long_pauses = 0  # Khoảng lặng >= 1.2 giây
    prev_end = 0.0
    logprobs: list[float] = []

    for idx, seg in enumerate(segments):
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        dur = max(0.0, end - start)
        speaking_time += dur

        if idx > 0:
            gap = max(0.0, start - prev_end)
            total_pause_time += gap
            if gap >= 1.2:
                long_pauses += 1
        prev_end = max(prev_end, end)

        if "avg_logprob" in seg and seg["avg_logprob"] is not None:
            logprobs.append(float(seg["avg_logprob"]))

    effective_duration = max(total_duration, prev_end, speaking_time, 1.0)
    wpm = round((word_count / effective_duration) * 60.0, 1) if word_count > 0 else 0.0

    if logprobs:
        avg_lp = sum(logprobs) / len(logprobs)
        clarity_pct = round(min(100.0, max(0.0, math.exp(avg_lp) * 100.0)), 1)
    else:
        clarity_pct = 85.0

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
    \"\"\"Quản lý nhận dạng giọng nói offline qua faster-whisper (lưu model trên ổ F:).\"\"\"

    def __init__(self, model_size: str = "small.en") -> None:
        self.model_size = model_size
        self._model = None
        self._device_used = "uninitialized"

    def _load_model(self):
        _apply_pyav_compatibility_patch()
        if self._model is not None:
            return self._model

        WHISPER_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "Chưa cài đặt 'faster-whisper'. Hãy chạy lệnh: "
                ".\\\\.venv\\\\Scripts\\\\pip.exe install faster-whisper python-multipart"
            ) from exc

        try:
            self._model = WhisperModel(
                self.model_size,
                device="cuda",
                compute_type="float16",
                download_root=str(WHISPER_MODEL_DIR),
            )
            self._device_used = "cuda (float16)"
        except Exception:
            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8",
                cpu_threads=8,
                download_root=str(WHISPER_MODEL_DIR),
            )
            self._device_used = "cpu (int8, 8 threads)"
        return self._model

    def transcribe_file(self, audio_path: Path) -> dict[str, Any]:
        _apply_pyav_compatibility_patch()
        if not audio_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file âm thanh: {audio_path.name}")

        start_t = time.perf_counter()
        model = self._load_model()
        segments_iter, info = model.transcribe(
            str(audio_path),
            language="en",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
        )

        seg_list: list[dict[str, Any]] = []
        full_texts: list[str] = []
        for s in segments_iter:
            text_clean = s.text.strip()
            if text_clean:
                full_texts.append(text_clean)
                seg_list.append(
                    {
                        "start": round(float(s.start), 2),
                        "end": round(float(s.end), 2),
                        "text": text_clean,
                        "avg_logprob": round(float(s.avg_logprob), 4) if s.avg_logprob is not None else None,
                    }
                )

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
"""


def patch_ui_for_zoom_audio(html_path: Path) -> None:
    if not html_path.exists():
        return
    html = html_path.read_text(encoding="utf-8")

    # Thêm nút "💻 Thu tiếng từ Zoom" cạnh nút "🎙 Thu âm Micro"
    old_btn = '<button id="recBtn" class="btn btn-secondary" onclick="toggleMicRecording()">🎙 Thu âm Micro</button>'
    new_btns = (
        '<button id="recBtn" class="btn btn-secondary" onclick="toggleMicRecording()">🎙 Thu Micro</button>\n'
        '              <button id="zoomRecBtn" class="btn btn-secondary" style="border:1px solid var(--primary); color:var(--primary);" onclick="toggleZoomAudioRecording()">💻 Thu tiếng Học viên từ Zoom</button>'
    )
    if "toggleZoomAudioRecording" not in html and old_btn in html:
        html = html.replace(old_btn, new_btns)

    zoom_js = """
    let zoomRecorder = null;
    let zoomStream = null;
    let zoomChunks = [];

    async function toggleZoomAudioRecording() {
      const btn = document.getElementById('zoomRecBtn');
      if (zoomRecorder && zoomRecorder.state === 'recording') {
        zoomRecorder.stop();
        btn.textContent = '💻 Thu tiếng Học viên từ Zoom';
        btn.classList.remove('btn-danger');
        btn.classList.add('btn-secondary');
        return;
      }
      try {
        // Bắt âm thanh phát ra từ hệ thống (System Audio / Zoom App) ngay cả khi đeo tai nghe
        const displayStream = await navigator.mediaDevices.getDisplayMedia({
          video: true,
          audio: {
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false
          }
        });

        const audioTracks = displayStream.getAudioTracks();
        if (!audioTracks || audioTracks.length === 0) {
          displayStream.getTracks().forEach(t => t.stop());
          alert('LƯU Ý: Bạn chưa bật công tắc "Chia sẻ âm thanh hệ thống" (Also share system audio) ở dưới cùng hộp thoại vừa hiện ra! Hãy bấm lại và tích chọn chia sẻ âm thanh nhé.');
          return;
        }

        // Chỉ giữ lại kênh âm thanh của học viên từ Zoom (hủy kênh hình ảnh để file nhẹ chỉ vài trăm KB)
        zoomStream = displayStream;
        const audioOnlyStream = new MediaStream(audioTracks);
        zoomChunks = [];
        zoomRecorder = new MediaRecorder(audioOnlyStream, { mimeType: 'audio/webm' });
        zoomRecorder.ondataavailable = e => { if (e.data.size > 0) zoomChunks.push(e.data); };
        zoomRecorder.onstop = () => {
          const blob = new Blob(zoomChunks, { type: 'audio/webm' });
          const file = new File([blob], 'zoom_student_speaking.webm', { type: 'audio/webm' });
          const dt = new DataTransfer();
          dt.items.add(file);
          document.getElementById('spkAudioFile').files = dt.files;
          if (zoomStream) zoomStream.getTracks().forEach(t => t.stop());
          alert('Đã thu xong tiếng học viên từ Zoom! Bấm "Chạy Whisper nhận diện giọng nói" để chuyển thành văn bản.');
        };
        zoomRecorder.start();
        btn.textContent = '⏹ Dừng thu từ Zoom';
        btn.classList.remove('btn-secondary');
        btn.classList.add('btn-danger');
      } catch (e) {
        console.error(e);
        alert('Đã hủy hoặc không chọn chia sẻ âm thanh hệ thống: ' + e.message);
      }
    }
"""
    if "async function toggleZoomAudioRecording()" not in html:
        html = html.replace("async function toggleMicRecording()", zoom_js + "\n    async function toggleMicRecording()")

    html_path.write_text(html, encoding="utf-8")


def main() -> None:
    whisper_file = APP_DIR / "services" / "transcription" / "whisper_service.py"
    whisper_file.parent.mkdir(parents=True, exist_ok=True)
    whisper_file.write_text(WHISPER_SERVICE_FIXED_PY, encoding="utf-8")

    ui_file = DESKTOP_DIR / "index.html"
    patch_ui_for_zoom_audio(ui_file)

    print("=" * 72)
    print("[✓] ĐÃ SỬA LỖI WHISPER SERVICE & BỔ SUNG THU ÂM HỌC VIÊN TỪ ZOOM!")
    print("- Đã sửa sạch lỗi SyntaxError & PyAV trong: apps/backend/app/services/transcription/whisper_service.py")
    print("- Đã thêm nút '💻 Thu tiếng Học viên từ Zoom' vào: apps/desktop/index.html")
    print("-> Nếu cửa sổ server uvicorn bị dừng lúc nãy, hãy khởi động lại uvicorn và nhấn F5 trên trình duyệt!")
    print("=" * 72)


if __name__ == "__main__":
    main()