#!/usr/bin/env python3
"""IELTS Copilot - Trình khởi tạo Mốc 4: Speaking Lab + Whisper Offline + Chấm Speaking.

Chạy trực tiếp tại thư mục F:\\ielts-copilot:
    .\\.venv\\Scripts\\python.exe init_speaking_mvp.py

Tính năng nổi bật (Mốc 4):
1. Tích hợp 2 Pipeline tách biệt cho Speaking theo đúng thiết kế Mục 7:
   - Pipeline 1 (Audio & Whisper): Lưu file MP3/WAV/M4A/WEBM an toàn trong F:\\ielts-copilot\\data\\audio
     (giới hạn 50MB, chống đọc file trái phép ngoài thư mục), chạy faster-whisper (small.en lưu tại
     F:\\ielts-copilot\\models\\whisper, không tốn ổ C:), tự động đo tốc độ nói (WPM), tổng thời gian nghỉ
     và số khoảng lặng dài (>= 1.2s).
   - Pipeline 2 (Language & Fluency Analysis): Giáo viên nghe lại file ghi âm trực tiếp trên UI, sửa lỗi
     nhận diện trong transcript (nếu có), sau đó gọi Qwen3 8B chấm theo IELTS Speaking Band Descriptors
     kèm kiểm tra trích dẫn (Quote Verification) và cảnh báo rõ giới hạn chấm Pronunciation từ văn bản.
2. Cập nhật giao diện http://127.0.0.1:8000/ với đủ 3 phân khu:
   Writing Lab · Speaking Lab (Upload file / Ghi âm Micro / Chỉnh Transcript) · Student Records.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path.cwd()
BACKEND_DIR = PROJECT_ROOT / "apps" / "backend"
APP_DIR = BACKEND_DIR / "app"
DESKTOP_DIR = PROJECT_ROOT / "apps" / "desktop"
DATA_DIR = PROJECT_ROOT / "data"


REQUIREMENTS_M4_TXT = """fastapi>=0.115.0
uvicorn[standard]>=0.30.0
pydantic>=2.9.0
pytest>=8.3.0
httpx>=0.27.0
python-multipart>=0.0.9
faster-whisper>=1.0.3
"""


WHISPER_SERVICE_PY = """from __future__ import annotations

import math
import re
import time
import wave
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT

WHISPER_MODEL_DIR = PROJECT_ROOT / "models" / "whisper"
AUDIO_STORAGE_DIR = PROJECT_ROOT / "data" / "audio"
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".webm", ".ogg"}
MAX_AUDIO_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


def validate_and_resolve_audio_path(filename: str) -> Path:
    \"\"\"Đảm bảo file âm thanh hợp lệ và nằm nghiêm ngặt trong data/audio (chống Path Traversal).\"\"\"
    AUDIO_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise ValueError(f"Định dạng audio '{ext}' không được hỗ trợ. Chỉ chấp nhận: {', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))}")
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

    # Ước lượng độ rõ âm học từ xác suất nhận diện của Whisper (chỉ dùng làm tham khảo phụ)
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

        # Ưu tiên thử GPU CUDA trước; nếu thiếu thư viện cuDNN hệ thống trên Windows thì tự chuyển sang CPU int8 (8 luồng)
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


SPEAKING_PROMPT_PY = """from __future__ import annotations

from typing import Any

SPEAKING_RUBRIC_VERSION = "ielts-speaking-v1-cambridge-calibrated"

ALLOWED_SPEAKING_ERROR_CODES: dict[str, set[str]] = {
    "fluency_coherence": {"FC_HESITATION", "FC_COHESION", "FC_UNDERDEVELOPED", "FC_REPETITION"},
    "lexical_resource": {"COLLOCATION", "WORD_CHOICE", "SPEAKING_IDIOM", "REGISTER"},
    "grammatical_range_accuracy": {"ARTICLE", "PREPOSITION", "SVA", "TENSE", "SYNTAX"},
    "pronunciation": {"PRON_CHECK_REQUIRED"},
}


def build_calibrated_speaking_prompts(
    prompt_text: str,
    transcript_text: str,
    task_type: str,
    audio_metrics: dict[str, Any],
) -> tuple[str, str]:
    part_label = {
        "part1": "IELTS Speaking Part 1 (Introduction & Interview)",
        "part2": "IELTS Speaking Part 2 (Individual Long Turn / Cue Card)",
        "part3": "IELTS Speaking Part 3 (Two-Way Discussion)",
    }.get(task_type, "IELTS Speaking")

    system_prompt = f\"\"\"You are a certified Senior Cambridge IELTS Speaking Examiner evaluating a transcript and acoustic fluency metrics for {part_label}.

=== CRITICAL SPEAKING CALIBRATION RULES ===
1. STRICT CRITERION ISOLATION (NO DOUBLE PENALIZATION):
   - 'fluency_coherence': Evaluate speech flow, willingness to speak at length, topic development, discourse markers, and hesitation based on BOTH the transcript and the provided Acoustic Metrics (WPM & long pauses). Allowed error_code: FC_HESITATION, FC_COHESION, FC_UNDERDEVELOPED, FC_REPETITION. NEVER penalize grammar or vocabulary here!
   - 'lexical_resource': Evaluate spoken vocabulary range, idiomatic expressions, collocations, and ability to paraphrase. Allowed error_code: COLLOCATION, WORD_CHOICE, SPEAKING_IDIOM, REGISTER.
   - 'grammatical_range_accuracy': Evaluate range of spoken sentence structures and grammatical accuracy. Remember that spoken English naturally has minor slips; Band 7.0 allows a few grammatical errors if frequent error-free sentences are present. Allowed error_code: ARTICLE, PREPOSITION, SVA, TENSE, SYNTAX.
   - 'pronunciation': IMPORTANT ARCHITECTURAL LIMITATION — A text transcript alone CANNOT fully measure phoneme accuracy, word stress, or intonation. Provide a tentative baseline band (usually near the average of Fluency and Lexical, adjusted by Whisper clarity score) and include 1 reminder item with error_code 'PRON_CHECK_REQUIRED' advising the teacher to verify stress and intonation via the audio player.

2. OFFICIAL CAMBRIDGE SPEAKING BAND ANCHORS:
   - BAND 7.0: Speaks at length without noticeable effort or loss of coherence (typically 115–160 WPM with few long pauses); uses discourse markers and idiomatic/less common vocabulary flexibly despite some inappropriate choices; uses a range of complex structures with frequent error-free sentences.
   - BAND 6.0: Willing to speak at length though may lose coherence at times due to occasional repetition, self-correction, or hesitation; has wide enough vocabulary to discuss topics at length; uses a mix of simple and complex structures with some mistakes that rarely cause comprehension problems.
   - BAND 5.0: Maintains flow only with noticeable repetition, self-correction, or slow speech (<95 WPM); uses limited flexibility in vocabulary and complex grammar.

3. VERBATIM QUOTES:
   - Include at most 2 key evidence items per criterion.
   - Every 'quote' MUST be copied 100% verbatim from the Student Transcript.
\"\"\"

    user_prompt = (
        f"=== SPEAKING PART ===\\n{part_label}\\n\\n"
        f"=== ACOUSTIC & FLUENCY METRICS (MEASURED FROM AUDIO) ===\\n"
        f"- Total Duration: {audio_metrics.get('duration_seconds', 0)}s | Active Speaking Time: {audio_metrics.get('speaking_time_seconds', 0)}s\\n"
        f"- Word Count: {audio_metrics.get('word_count', 0)} words | Speech Rate: {audio_metrics.get('words_per_minute', 0)} WPM ({audio_metrics.get('pace_assessment', 'N/A')})\\n"
        f"- Long Pauses (>=1.2s): {audio_metrics.get('long_pause_count', 0)} | Total Pause Time: {audio_metrics.get('total_pause_seconds', 0)}s\\n"
        f"- Whisper ASR Acoustic Clarity Proxy: {audio_metrics.get('whisper_clarity_percent', 85)}%\\n\\n"
        f"=== QUESTION / CUE CARD ===\\n{prompt_text.strip()}\\n\\n"
        f"=== STUDENT TRANSCRIPT (VERIFIED) ===\\n{transcript_text.strip()}\\n"
    )
    return system_prompt, user_prompt
"""


SPEAKING_EVALUATOR_PY = """from __future__ import annotations

import math
import re
from typing import Any

from app.prompts.ielts_speaking_v1 import (
    ALLOWED_SPEAKING_ERROR_CODES,
    SPEAKING_RUBRIC_VERSION,
    build_calibrated_speaking_prompts,
)
from app.services.transcription.whisper_service import compute_fluency_metrics_from_segments

SPEAKING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "object",
            "properties": {
                "fluency_coherence": {
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
                "pronunciation": {
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
                "fluency_coherence",
                "lexical_resource",
                "grammatical_range_accuracy",
                "pronunciation",
            ],
        },
        "priority_actions": {"type": "array", "items": {"type": "string"}},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["criteria", "priority_actions", "uncertainties"],
}


def calculate_overall_speaking_band(fc: float, lr: float, gra: float, pron: float) -> float:
    avg = (fc + lr + gra + pron) / 4.0
    return math.floor(avg * 2 + 0.5) / 2.0


def validate_speaking_assessment(
    raw_json: dict[str, Any],
    transcript_text: str,
    task_type: str,
    audio_metrics: dict[str, Any],
    model_name: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    norm_transcript = re.sub(r"\\s+", " ", transcript_text.strip()).lower()
    criteria = raw_json.get("criteria", {})
    warnings: list[str] = [
        "Lưu ý: Điểm Pronunciation chỉ là ước lượng sơ bộ. Giáo viên cần nghe trực tiếp bản ghi âm để chốt trọng âm, âm cuối (ending sounds) và ngữ điệu."
    ]
    extracted_errors: list[dict[str, Any]] = []
    scores: dict[str, float] = {}
    total_quotes = 0
    unverified_quotes = 0
    cross_violations = 0

    for key in ("fluency_coherence", "lexical_resource", "grammatical_range_accuracy", "pronunciation"):
        c_obj = criteria.get(key, {})
        raw_band = c_obj.get("estimated_band", 6.0)
        try:
            clamped = max(0.0, min(9.0, float(raw_band)))
            band = round(clamped * 2) / 2.0
        except (TypeError, ValueError):
            band = 6.0
        c_obj["estimated_band"] = band
        scores[key] = band

        allowed_codes = ALLOWED_SPEAKING_ERROR_CODES.get(key, set())
        for ev in c_obj.get("evidence", []):
            quote = ev.get("quote", "")
            err_code = ev.get("error_code", "WORD_CHOICE").upper().strip()
            ev["error_code"] = err_code

            if key == "pronunciation":
                ev["quote_verified"] = True
                continue

            total_quotes += 1
            norm_q = re.sub(r"\\s+", " ", quote.strip()).lower()
            is_verified = bool(norm_q and norm_q in norm_transcript)
            ev["quote_verified"] = is_verified
            if not is_verified:
                unverified_quotes += 1
                warnings.append(f"[{key}] Trích dẫn không khớp nguyên văn transcript: {quote}")

            if key == "fluency_coherence" and err_code not in allowed_codes:
                cross_violations += 1
                warnings.append(f"Lỗi '{err_code}' không được dùng để trừ điểm Fluency & Coherence.")

            extracted_errors.append(
                {
                    "error_code": err_code,
                    "evidence": quote,
                    "correction": ev.get("suggestion", ""),
                    "explanation": ev.get("issue", ""),
                    "confidence": 1.0 if is_verified else 0.4,
                }
            )

    overall = calculate_overall_speaking_band(
        scores["fluency_coherence"],
        scores["lexical_resource"],
        scores["grammatical_range_accuracy"],
        scores["pronunciation"],
    )

    uncertainties = list(raw_json.get("uncertainties", []))
    uncertainties.extend(warnings)

    enriched = {
        "skill": "speaking",
        "task_type": task_type,
        "rubric_version": SPEAKING_RUBRIC_VERSION,
        "model_name": model_name,
        "audio_metrics": audio_metrics,
        "estimated_overall": overall,
        "criteria": criteria,
        "priority_actions": raw_json.get("priority_actions", []),
        "uncertainties": uncertainties,
        "pronunciation_requires_teacher_audio_check": True,
        "validation_summary": {
            "total_quotes_checked": total_quotes,
            "verified_quotes": total_quotes - unverified_quotes,
            "unverified_quotes": unverified_quotes,
            "all_quotes_verified": unverified_quotes == 0,
            "cross_criterion_violations": cross_violations,
        },
        "teacher_review_required": True,
    }
    return enriched, extracted_errors
"""


SCHEMAS_M4_PY = """from __future__ import annotations

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


class SpeakingSubmissionCreate(BaseModel):
    student_id: str
    lesson_id: str | None = None
    task_type: Literal["part1", "part2", "part3"] = "part2"
    prompt_text: str = Field(..., min_length=5, max_length=4000)
    transcript_text: str = Field(default="", max_length=15000)
    duration_seconds: float = Field(default=90.0, ge=0.0, le=1800.0)


class TranscriptUpdateRequest(BaseModel):
    transcript_text: str = Field(..., min_length=5, max_length=15000)
    duration_seconds: float | None = Field(default=None, ge=0.0, le=1800.0)


class TranscribeRequest(BaseModel):
    whisper_model: Literal["small.en", "medium.en", "base.en"] = "small.en"


class AssessWritingRequest(BaseModel):
    model_name: str = "qwen3:8b"
    think: bool = Field(
        default=False,
        description="Bật/tắt chế độ suy luận sâu của Qwen3.",
    )


class TeacherReviewRequest(BaseModel):
    assessment_id: str | None = None
    teacher_overall: float = Field(..., ge=0.0, le=9.0)
    teacher_feedback: str = Field(default="", max_length=10000)
    updated_feedback_json: dict[str, Any] | None = None
"""


STORE_M4_PY = """from __future__ import annotations

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

    def create_speaking_submission(self, data: dict[str, Any]) -> dict[str, Any]:
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
                    prompt_text, response_text, source_audio_path, transcript_text, status, created_at
                ) VALUES (?, ?, ?, 'speaking', ?, ?, ?, ?, ?, 'draft', ?)
                \"\"\",
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


ROUTES_M4_PY = """from __future__ import annotations

import json
import uuid
from pathlib import Path
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.repositories.store import CopilotRepository
from app.schemas.domain import (
    AssessWritingRequest,
    SpeakingSubmissionCreate,
    StudentCreate,
    TeacherReviewRequest,
    TranscribeRequest,
    TranscriptUpdateRequest,
    WritingSubmissionCreate,
)
from app.services.inference.ollama_provider import OllamaProvider
from app.services.speaking.evaluator import (
    SPEAKING_SCHEMA,
    build_calibrated_speaking_prompts,
    validate_speaking_assessment,
)
from app.services.transcription.whisper_service import (
    ALLOWED_AUDIO_EXTENSIONS,
    AUDIO_STORAGE_DIR,
    MAX_AUDIO_SIZE_BYTES,
    WhisperTranscriber,
    compute_fluency_metrics_from_segments,
    validate_and_resolve_audio_path,
)
from app.services.writing.evaluator import (
    WRITING_SCHEMA,
    build_prompts,
    preprocess_essay,
    validate_assessment,
)

router = APIRouter(prefix="/api")
repo = CopilotRepository()
llm = OllamaProvider()
_transcribers: dict[str, WhisperTranscriber] = {}


def get_transcriber(model_size: str = "small.en") -> WhisperTranscriber:
    if model_size not in _transcribers:
        _transcribers[model_size] = WhisperTranscriber(model_size=model_size)
    return _transcribers[model_size]


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


@router.post("/submissions/speaking")
def create_speaking_submission_json(payload: SpeakingSubmissionCreate):
    \"\"\"Tạo bài nộp Speaking từ văn bản transcript (hoặc bài mẫu) kèm thời lượng.\"\"\"
    student = repo.get_student(payload.student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Không tìm thấy student_id.")

    metrics = compute_fluency_metrics_from_segments(
        segments=[],
        total_duration=payload.duration_seconds,
        transcript_text=payload.transcript_text,
    )
    return repo.create_speaking_submission(
        {
            "student_id": payload.student_id,
            "lesson_id": payload.lesson_id,
            "task_type": payload.task_type,
            "prompt_text": payload.prompt_text,
            "response_text": json.dumps({"audio_metrics": metrics, "segments": []}, ensure_ascii=False),
            "source_audio_path": None,
            "transcript_text": payload.transcript_text,
        }
    )


@router.post("/submissions/speaking/upload")
async def upload_speaking_submission(
    student_id: str = Form(...),
    task_type: str = Form("part2"),
    prompt_text: str = Form(...),
    audio_file: UploadFile = File(...),
):
    \"\"\"Upload bản ghi âm MP3/WAV/M4A/WEBM an toàn vào F:\\ielts-copilot\\data\\audio.\"\"\"
    student = repo.get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Không tìm thấy student_id.")

    orig_ext = Path(audio_file.filename or "audio.wav").suffix.lower()
    if orig_ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Định dạng '{orig_ext}' không hỗ trợ. Chỉ nhận: {', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))}",
        )

    content = await audio_file.read()
    if len(content) > MAX_AUDIO_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File âm thanh vượt quá giới hạn 50MB.")
    if len(content) < 100:
        raise HTTPException(status_code=400, detail="File âm thanh rỗng hoặc bị hỏng.")

    safe_filename = f"{uuid.uuid4()}{orig_ext}"
    target_path = validate_and_resolve_audio_path(safe_filename)
    target_path.write_bytes(content)

    return repo.create_speaking_submission(
        {
            "student_id": student_id,
            "lesson_id": None,
            "task_type": task_type if task_type in ("part1", "part2", "part3") else "part2",
            "prompt_text": prompt_text,
            "response_text": "{}",
            "source_audio_path": safe_filename,
            "transcript_text": "",
        }
    )


@router.get("/submissions/{submission_id}/audio")
def stream_submission_audio(submission_id: str):
    \"\"\"Phát lại file ghi âm gốc trên giao diện giáo viên.\"\"\"
    sub = repo.get_submission(submission_id)
    if not sub or not sub.get("source_audio_path"):
        raise HTTPException(status_code=404, detail="Bài nộp này không có file âm thanh đính kèm.")
    try:
        audio_path = validate_and_resolve_audio_path(sub["source_audio_path"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="File âm thanh không tồn tại trên ổ đĩa.")
    return FileResponse(path=str(audio_path), filename=audio_path.name)


@router.post("/submissions/{submission_id}/transcribe")
def transcribe_speaking_submission(submission_id: str, req: TranscribeRequest | None = None):
    \"\"\"Chạy faster-whisper offline chuyển file ghi âm thành văn bản kèm đo WPM & khoảng lặng.\"\"\"
    options = req or TranscribeRequest()
    sub = repo.get_submission(submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài nộp.")
    if not sub.get("source_audio_path"):
        raise HTTPException(status_code=400, detail="Bài nộp này chưa có file âm thanh để nhận diện.")

    repo.update_submission_status(submission_id, "processing")
    try:
        audio_path = validate_and_resolve_audio_path(sub["source_audio_path"])
        transcriber = get_transcriber(options.whisper_model)
        result = transcriber.transcribe_file(audio_path)

        meta_json = json.dumps(
            {
                "whisper_model": result["model_name"],
                "device": result["device"],
                "elapsed_seconds": result["elapsed_seconds"],
                "audio_metrics": result["audio_metrics"],
                "segments": result["segments"],
            },
            ensure_ascii=False,
        )
        updated = repo.update_speaking_transcript(
            submission_id=submission_id,
            transcript_text=result["transcript_text"],
            audio_meta_json=meta_json,
        )
        repo.update_submission_status(submission_id, "draft")
        updated["transcription_result"] = result
        return updated
    except Exception as exc:
        repo.update_submission_status(submission_id, "failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/submissions/{submission_id}/transcript")
def update_transcript_manually(submission_id: str, payload: TranscriptUpdateRequest):
    \"\"\"Cho phép giáo viên sửa lỗi nhận diện giọng nói trong transcript trước khi chấm.\"\"\"
    sub = repo.get_submission(submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài nộp.")

    try:
        meta = json.loads(sub.get("response_text") or "{}")
    except Exception:
        meta = {}

    segments = meta.get("segments", [])
    prev_dur = meta.get("audio_metrics", {}).get("duration_seconds", 90.0)
    dur = payload.duration_seconds if payload.duration_seconds is not None else prev_dur
    meta["audio_metrics"] = compute_fluency_metrics_from_segments(segments, float(dur), payload.transcript_text)

    updated = repo.update_speaking_transcript(
        submission_id=submission_id,
        transcript_text=payload.transcript_text,
        audio_meta_json=json.dumps(meta, ensure_ascii=False),
    )
    updated["audio_metrics"] = meta["audio_metrics"]
    return updated


@router.get("/submissions/{submission_id}")
def get_submission_detail(submission_id: str):
    detail = repo.get_submission_detail(submission_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài nộp.")
    return detail


@router.post("/submissions/{submission_id}/assess")
def assess_submission(submission_id: str, req: AssessWritingRequest | None = None):
    \"\"\"Chấm bài tự động: Tự nhận diện bài Writing hoặc Speaking để áp dụng đúng Rubric.\"\"\"
    options = req or AssessWritingRequest()
    sub = repo.get_submission(submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài nộp (submission_id).")

    repo.update_submission_status(submission_id, "processing")
    try:
        if sub["skill"] == "speaking":
            transcript = (sub.get("transcript_text") or "").strip()
            if len(transcript) < 10:
                raise ValueError("Transcript quá ngắn hoặc chưa chạy nhận dạng giọng nói.")
            try:
                stored_meta = json.loads(sub.get("response_text") or "{}")
            except Exception:
                stored_meta = {}
            audio_metrics = stored_meta.get("audio_metrics") or compute_fluency_metrics_from_segments(
                [], 90.0, transcript
            )
            sys_prompt, usr_prompt = build_calibrated_speaking_prompts(
                prompt_text=sub["prompt_text"],
                transcript_text=transcript,
                task_type=sub["task_type"],
                audio_metrics=audio_metrics,
            )
            raw_json, bench = llm.generate_structured(
                system_prompt=sys_prompt,
                user_prompt=usr_prompt,
                schema=SPEAKING_SCHEMA,
                model=options.model_name,
                think=options.think,
            )
            enriched, extracted_errors = validate_speaking_assessment(
                raw_json=raw_json,
                transcript_text=transcript,
                task_type=sub["task_type"],
                audio_metrics=audio_metrics,
                model_name=options.model_name,
            )
        else:
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


UI_M4_HTML = """<!DOCTYPE html>
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
    .card h2 { font-size: 1.05rem; margin-bottom: 14px; color: #e2e8f0; display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
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
      font-size: 0.9rem;
      transition: 0.15s;
    }
    .btn:hover { background: var(--primary-hover); color: #fff; }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .btn-secondary { background: var(--panel-alt); color: var(--text); }
    .btn-success { background: var(--success); color: #052e16; }
    .btn-danger { background: var(--danger); color: #fff; }
    .score-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 16px; }
    .score-box {
      background: #0f172a;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      text-align: center;
    }
    .score-box.overall { border-color: var(--primary); background: rgba(56, 189, 248, 0.1); }
    .score-box .label { font-size: 0.72rem; color: var(--muted); text-transform: uppercase; }
    .score-box .val { font-size: 1.5rem; font-weight: 800; margin-top: 4px; color: var(--text); }
    .score-box.overall .val { color: var(--primary); }
    .essay-preview {
      background: #0f172a;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 16px;
      white-space: pre-wrap;
      font-size: 0.95rem;
      line-height: 1.75;
      max-height: 440px;
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
    .metrics-bar {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
      margin-bottom: 14px;
    }
    .metric-pill {
      background: #0f172a;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 10px;
      text-align: center;
      font-size: 0.82rem;
    }
    .metric-pill b { display: block; font-size: 1.05rem; color: var(--primary); margin-top: 2px; }
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
      <button class="tab-btn active" onclick="switchTab('writing')">1. Writing Lab</button>
      <button class="tab-btn" onclick="switchTab('speaking')">2. Speaking Lab (Whisper + Audio)</button>
      <button class="tab-btn" onclick="switchTab('students')">3. Student Records</button>
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

          <label>Bài làm của học viên</label>
          <textarea id="essayInput" rows="11" oninput="updateWordCount()" placeholder="Dán bài viết của học viên vào đây..."></textarea>

          <div style="display:flex; justify-content:space-between; align-items:center; gap:12px;">
            <label style="display:flex; align-items:center; gap:8px; margin:0; cursor:pointer;">
              <input type="checkbox" id="thinkToggle" style="width:auto; margin:0;" />
              <span>Bật Deep Thinking</span>
            </label>
            <button id="assessBtn" class="btn" onclick="submitAndAssessWriting()">Chấm Writing ngay</button>
          </div>
        </div>

        <div id="essayHighlightCard" class="card hidden">
          <h2>
            <span>Bài gốc & Đối chiếu Trích dẫn (Bấm vào lỗi bên phải để tô sáng câu)</span>
            <button class="btn btn-secondary" style="padding:4px 10px; font-size:0.78rem;" onclick="clearHighlight('essayPreviewBox', currentEssayRaw)">Bỏ tô sáng</button>
          </h2>
          <div id="essayPreviewBox" class="essay-preview"></div>
        </div>
      </div>

      <div>
        <div class="card">
          <h2>
            <span>2. Kết quả Phân tích Writing & Kiểm duyệt của Giáo viên</span>
            <span id="rubricBadge" class="badge">Chưa có dữ liệu</span>
          </h2>
          <div id="emptyAssessmentState" style="color:var(--muted); padding:30px 0; text-align:center;">
            Hãy nhập bài viết bên trái và bấm <b>Chấm Writing ngay</b>, hoặc chọn một bài đã chấm từ tab <b>Student Records</b>.
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
            <div style="background:#0f172a; border:1px solid var(--primary); border-radius:10px; padding:14px; margin-bottom:16px;">
              <div style="font-weight:700; color:var(--primary); margin-bottom:10px;">Chốt điểm của Giáo viên (Teacher Review)</div>
              <div class="row-3" style="grid-template-columns: 1fr 2fr auto; align-items:end;">
                <div>
                  <label>Band Giáo viên chốt</label>
                  <input type="number" id="teacherBandInput" step="0.5" min="0" max="9" value="7.0" style="margin:0;" />
                </div>
                <div>
                  <label>Nhận xét của Giáo viên</label>
                  <input type="text" id="teacherFeedbackInput" placeholder="Nhận xét tổng kết của giáo viên..." style="margin:0;" />
                </div>
                <button class="btn btn-success" onclick="saveTeacherReview('writing')">Lưu Duyệt</button>
              </div>
              <div id="reviewSavedMsg" style="color:#4ade80; font-size:0.82rem; margin-top:8px;" class="hidden"></div>
            </div>
            <div id="criteriaDetailsBox"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 2: SPEAKING LAB -->
    <div id="tab-speaking" class="grid-2 hidden">
      <div>
        <div class="card">
          <h2>
            <span>1. Nhập File Ghi âm hoặc Tạo Bài Speaking</span>
            <button class="btn btn-secondary" style="padding:5px 12px; font-size:0.8rem;" onclick="loadSampleSpeaking()">+ Nạp bài Speaking mẫu (Test nhanh)</button>
          </h2>
          <div class="row-3">
            <div>
              <label>Học viên</label>
              <select id="spkStudentSelect"></select>
            </div>
            <div>
              <label>Phần thi (Part)</label>
              <select id="spkPartSelect">
                <option value="part2">Speaking Part 2 (Cue Card 1-2 phút)</option>
                <option value="part1">Speaking Part 1 (Interview)</option>
                <option value="part3">Speaking Part 3 (Discussion)</option>
              </select>
            </div>
            <div>
              <label>Whisper Model (Offline)</label>
              <select id="whisperModelSelect">
                <option value="small.en">Whisper small.en (Khuyên dùng)</option>
                <option value="base.en">Whisper base.en (Siêu nhanh)</option>
                <option value="medium.en">Whisper medium.en (Chính xác cao)</option>
              </select>
            </div>
          </div>

          <label>Câu hỏi / Cue Card (Prompt)</label>
          <textarea id="spkPromptInput" rows="2" placeholder="VD: Describe a book you have recently read. You should say: what kind of book it is, what it is about..."></textarea>

          <!-- KHU VỰC UPLOAD AUDIO HOẶC THU ÂM MICRO -->
          <div style="background:#0f172a; border:1px dashed var(--border); border-radius:10px; padding:14px; margin-bottom:14px;">
            <label style="color:var(--primary);">Bước A: Chọn file ghi âm (.mp3, .wav, .m4a, .webm ≤ 50MB) hoặc Thu âm trực tiếp</label>
            <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:8px;">
              <input type="file" id="spkAudioFile" accept=".mp3,.wav,.m4a,.webm,.ogg" style="margin:0; flex:1;" />
              <button id="recBtn" class="btn btn-secondary" onclick="toggleMicRecording()">🎙 Thu âm Micro</button>
              <button id="transcribeBtn" class="btn" onclick="uploadAndTranscribeAudio()">Chạy Whisper nhận diện giọng nói</button>
            </div>
            <div id="audioPlayerContainer" class="hidden" style="margin-top:12px;">
              <label>Nghe lại bản ghi âm gốc của học viên (Kiểm tra Pronunciation & đối chiếu Transcript):</label>
              <audio id="spkAudioPlayer" controls style="width:100%; margin-top:4px;"></audio>
            </div>
          </div>

          <!-- CHỈ SỐ ÂM HỌC & FLUENCY -->
          <div id="spkMetricsBar" class="metrics-bar">
            <div class="metric-pill">Thời lượng nói<b id="mDuration">0.0s</b></div>
            <div class="metric-pill">Tốc độ nói (WPM)<b id="mWpm">0 WPM</b></div>
            <div class="metric-pill">Khoảng lặng ≥1.2s<b id="mPauses">0 lần</b></div>
            <div class="metric-pill">Độ rõ Whisper<b id="mClarity">-</b></div>
          </div>

          <label>Bước B: Transcript (Giáo viên có thể sửa lại các từ Whisper nghe nhầm trước khi bấm Chấm)</label>
          <textarea id="spkTranscriptInput" rows="7" placeholder="Transcript sau khi chạy Whisper sẽ hiện ở đây (hoặc bạn có thể dán trực tiếp transcript để chấm thử)..."></textarea>

          <div style="display:flex; justify-content:space-between; align-items:center; gap:12px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <label style="margin:0;">Thời lượng ước tính (giây, nếu nhập tay):</label>
              <input type="number" id="spkManualDuration" value="95" style="width:90px; margin:0;" />
            </div>
            <button id="assessSpkBtn" class="btn" onclick="submitAndAssessSpeaking()">Chấm Speaking ngay (Qwen3 8B)</button>
          </div>
        </div>

        <div id="spkHighlightCard" class="card hidden">
          <h2>
            <span>Transcript đối chiếu bằng chứng (Bấm vào lỗi bên phải để tô sáng câu)</span>
            <button class="btn btn-secondary" style="padding:4px 10px; font-size:0.78rem;" onclick="clearHighlight('spkPreviewBox', currentSpkTranscriptRaw)">Bỏ tô sáng</button>
          </h2>
          <div id="spkPreviewBox" class="essay-preview"></div>
        </div>
      </div>

      <div>
        <div class="card">
          <h2>
            <span>2. Kết quả Phân tích Speaking & Kiểm duyệt Phát âm</span>
            <span id="spkRubricBadge" class="badge">Chưa có dữ liệu</span>
          </h2>

          <div id="emptySpkState" style="color:var(--muted); padding:30px 0; text-align:center;">
            Hãy tải file ghi âm (hoặc nạp bài mẫu) bên trái rồi bấm <b>Chấm Speaking ngay</b>.
          </div>

          <div id="spkResultBox" class="hidden">
            <div class="score-grid">
              <div class="score-box"><div class="label">Fluency (FC)</div><div id="scFC" class="val">-</div></div>
              <div class="score-box"><div class="label">Lexical (LR)</div><div id="scSpkLR" class="val">-</div></div>
              <div class="score-box"><div class="label">Grammar (GRA)</div><div id="scSpkGRA" class="val">-</div></div>
              <div class="score-box"><div class="label">Pronun (Tạm)</div><div id="scPRON" class="val">-</div></div>
              <div class="score-box overall"><div class="label">AI Overall</div><div id="scSpkOverall" class="val">-</div></div>
            </div>

            <div style="background:rgba(245, 158, 11, 0.12); border:1px solid var(--warning); color:#fde047; padding:10px 12px; border-radius:8px; font-size:0.84rem; margin-bottom:14px;">
              <b>Lưu ý kiến trúc (Mục 7):</b> Văn bản transcript không phản ánh hết âm cuối (ending sounds), trọng âm từ và ngữ điệu. Hãy nghe trình phát âm thanh bên trái và chốt điểm chính thức ở khung dưới đây.
            </div>

            <div id="spkValidationBanner" style="margin-bottom:14px; font-size:0.84rem; padding:8px 12px; border-radius:8px; background:#0f172a; border:1px solid var(--border);"></div>

            <div style="background:#0f172a; border:1px solid var(--primary); border-radius:10px; padding:14px; margin-bottom:16px;">
              <div style="font-weight:700; color:var(--primary); margin-bottom:10px;">Chốt điểm Speaking của Giáo viên (Sau khi nghe phát âm)</div>
              <div class="row-3" style="grid-template-columns: 1fr 2fr auto; align-items:end;">
                <div>
                  <label>Band Speaking chốt</label>
                  <input type="number" id="spkTeacherBandInput" step="0.5" min="0" max="9" value="6.5" style="margin:0;" />
                </div>
                <div>
                  <label>Nhận xét Phát âm & Phản xạ của Giáo viên</label>
                  <input type="text" id="spkTeacherFeedbackInput" placeholder="VD: Phát âm rõ, cần chú ý âm cuối /s/, /ed/ và giảm ngập ngừng ở giữa câu..." style="margin:0;" />
                </div>
                <button class="btn btn-success" onclick="saveTeacherReview('speaking')">Lưu Duyệt</button>
              </div>
              <div id="spkReviewSavedMsg" style="color:#4ade80; font-size:0.82rem; margin-top:8px;" class="hidden"></div>
            </div>

            <div id="spkCriteriaDetailsBox"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 3: STUDENT RECORDS -->
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
              <span>Tiến độ & Lịch sử Chấm bài của Học viên (Writing & Speaking)</span>
              <select id="progressStudentSelect" style="width:280px; margin:0;" onchange="loadStudentProgress()"></select>
            </h2>

            <div id="recurringErrorsBox" style="margin-bottom:18px;"></div>

            <h3 style="font-size:0.95rem; margin-bottom:10px; color:var(--muted);">Lịch sử các lượt chấm (Bấm "Mở lại bài" để xem chi tiết)</h3>
            <table>
              <thead>
                <tr>
                  <th>Thời gian</th>
                  <th>Kỹ năng / Task</th>
                  <th>Rubric / Model</th>
                  <th>Điểm thành phần</th>
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

    let currentSpkSubmissionId = null;
    let currentSpkAssessmentId = null;
    let currentSpkTranscriptRaw = "";

    let mediaRecorder = null;
    let recordedChunks = [];

    async function api(path, options = {}) {
      const resp = await fetch(path, {
        headers: options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
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
      document.getElementById('tab-speaking').classList.toggle('hidden', tab !== 'speaking');
      document.getElementById('tab-students').classList.toggle('hidden', tab !== 'students');
      const tabs = ['writing', 'speaking', 'students'];
      document.querySelectorAll('.tab-btn').forEach((btn, idx) => {
        btn.classList.toggle('active', tabs[idx] === tab);
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
      const selects = ['studentSelect', 'spkStudentSelect', 'progressStudentSelect'];
      selects.forEach(id => {
        const sel = document.getElementById(id);
        sel.innerHTML = '';
        students.forEach(s => {
          const label = `${s.name} (Target: ${s.target_overall || '-'} | Hiện tại: ${s.current_overall || 'Chưa chốt'})`;
          sel.add(new Option(label, s.id));
        });
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

    function escapeHtml(str) {
      return (str || '').replace(/[&<>"']/g, m => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m]));
    }

    function highlightQuoteInBox(boxId, rawText, quote) {
      const box = document.getElementById(boxId);
      if (!quote || !rawText) return;
      const escapedText = escapeHtml(rawText);
      const escapedQuote = escapeHtml(quote.trim());
      const idx = escapedText.toLowerCase().indexOf(escapedQuote.toLowerCase());
      if (idx === -1) {
        box.innerHTML = escapedText;
        return;
      }
      const before = escapedText.slice(0, idx);
      const match = escapedText.slice(idx, idx + escapedQuote.length);
      const after = escapedText.slice(idx + escapedQuote.length);
      box.innerHTML = `${before}<mark class="hl" id="activeHl_${boxId}">${match}</mark>${after}`;
      const el = document.getElementById(`activeHl_${boxId}`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    function clearHighlight(boxId, rawText) {
      document.getElementById(boxId).innerHTML = escapeHtml(rawText);
    }

    // ================= WRITING LAB =================
    async function submitAndAssessWriting() {
      const studentId = document.getElementById('studentSelect').value;
      const taskType = document.getElementById('taskTypeSelect').value;
      const modelName = document.getElementById('modelSelect').value;
      const promptText = document.getElementById('promptInput').value.trim();
      const essayText = document.getElementById('essayInput').value.trim();
      const think = document.getElementById('thinkToggle').checked;

      if (!studentId) return alert('Hãy chọn 1 học viên trước!');
      if (promptText.length < 10 || essayText.length < 20) return alert('Vui lòng nhập đầy đủ đề bài và bài làm!');

      const btn = document.getElementById('assessBtn');
      btn.disabled = true;
      btn.textContent = 'Đang chấm Writing (~25-40s)...';

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
        renderWritingAssessment(assessed, essayText);
      } catch (e) {
        alert('Lỗi khi chấm Writing: ' + e.message);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Chấm Writing ngay';
      }
    }

    function renderWritingAssessment(assessed, essayText) {
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
      document.getElementById('validationBanner').innerHTML =
        `<b>Kiểm tra trích dẫn:</b> ${val.verified_quotes ?? 0}/${val.total_quotes_checked ?? 0} câu khớp 100% · <b>Lỗi chéo tiêu chí:</b> ${val.cross_criterion_violations ?? 0} · <b>Tốc độ:</b> ${bench.elapsed_seconds ?? '-'}s (${bench.tokens_per_second ?? '-'} tok/s)`;

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
          item.onclick = () => highlightQuoteInBox('essayPreviewBox', currentEssayRaw, ev.quote || '');
          sec.appendChild(item);
        });
        critBox.appendChild(sec);
      }
    }

    // ================= SPEAKING LAB =================
    function loadSampleSpeaking() {
      document.getElementById('spkPartSelect').value = 'part2';
      document.getElementById('spkPromptInput').value =
        'Describe a skill that you learned when you were a teenager. You should say: what the skill is, when and how you learned it, who taught you, and explain why this skill is important to you.';
      document.getElementById('spkTranscriptInput').value =
        "Well, I would like to talk about cooking, which is a practical life skill that I picked up when I was around fifteen years old. At that time, both of my parents was working full-time and often came home quite late in the evening. So my grandmother, who is an amazing traditional cook, decided to teach me how to prepare simple daily meals for our family. Initially, I only helped her with washing vegetables and boiling rice, but gradually she showed me how to season dishes properly and balance different flavors. One of the biggest challenge for me was controlling the heat when stir-frying, because I burned the garlic several times during the first week. However, after practicing every weekend for a few months, I became much more confident in the kitchen. Looking back, learning how to cook at an early age has been extremely valuable for me. Not only does it allow me to eat healthier and save money when studying away from home, but cooking for my loved ones also helps me relieve stress after a long day.";
      document.getElementById('spkManualDuration').value = '88';
      updateSpkMetricsUI({ duration_seconds: 88.0, words_per_minute: 121.4, long_pause_count: 1, whisper_clarity_percent: 92.5 });
      currentSpkSubmissionId = null;
    }

    function updateSpkMetricsUI(m) {
      document.getElementById('mDuration').textContent = `${m.duration_seconds ?? 0}s`;
      document.getElementById('mWpm').textContent = `${m.words_per_minute ?? 0} WPM`;
      document.getElementById('mPauses').textContent = `${m.long_pause_count ?? 0} lần`;
      document.getElementById('mClarity').textContent = m.whisper_clarity_percent ? `${m.whisper_clarity_percent}%` : '-';
    }

    async function toggleMicRecording() {
      const btn = document.getElementById('recBtn');
      if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
        btn.textContent = '🎙 Thu âm Micro';
        btn.classList.remove('btn-danger');
        btn.classList.add('btn-secondary');
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        recordedChunks = [];
        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.ondataavailable = e => { if (e.data.size > 0) recordedChunks.push(e.data); };
        mediaRecorder.onstop = () => {
          const blob = new Blob(recordedChunks, { type: 'audio/webm' });
          const file = new File([blob], 'live_recording.webm', { type: 'audio/webm' });
          const dt = new DataTransfer();
          dt.items.add(file);
          document.getElementById('spkAudioFile').files = dt.files;
          stream.getTracks().forEach(t => t.stop());
          alert('Đã thu âm xong! Bấm "Chạy Whisper nhận diện giọng nói" để chuyển thành văn bản.');
        };
        mediaRecorder.start();
        btn.textContent = '⏹ Dừng thu âm';
        btn.classList.remove('btn-secondary');
        btn.classList.add('btn-danger');
      } catch (e) {
        alert('Không truy cập được Micro: ' + e.message);
      }
    }

    async function uploadAndTranscribeAudio() {
      const studentId = document.getElementById('spkStudentSelect').value;
      const part = document.getElementById('spkPartSelect').value;
      const promptText = document.getElementById('spkPromptInput').value.trim() || 'IELTS Speaking Practice';
      const whisperModel = document.getElementById('whisperModelSelect').value;
      const fileInput = document.getElementById('spkAudioFile');

      if (!studentId) return alert('Hãy chọn học viên trước!');
      if (!fileInput.files || fileInput.files.length === 0) return alert('Hãy chọn 1 file âm thanh (.mp3, .wav, .m4a, .webm) hoặc thu âm bằng Micro trước!');

      const btn = document.getElementById('transcribeBtn');
      btn.disabled = true;
      btn.textContent = 'Đang chạy Whisper offline (lần đầu sẽ tải model về ổ F:)...';

      try {
        const fd = new FormData();
        fd.append('student_id', studentId);
        fd.append('task_type', part);
        fd.append('prompt_text', promptText);
        fd.append('audio_file', fileInput.files[0]);

        const sub = await api('/api/submissions/speaking/upload', { method: 'POST', body: fd });
        currentSpkSubmissionId = sub.id;

        // Hiển thị trình phát âm thanh
        const playerBox = document.getElementById('audioPlayerContainer');
        const player = document.getElementById('spkAudioPlayer');
        player.src = `/api/submissions/${sub.id}/audio`;
        playerBox.classList.remove('hidden');

        const transRes = await api(`/api/submissions/${sub.id}/transcribe`, {
          method: 'POST',
          body: JSON.stringify({ whisper_model: whisperModel })
        });
        const tr = transRes.transcription_result || {};
        document.getElementById('spkTranscriptInput').value = tr.transcript_text || '';
        if (tr.audio_metrics) {
          document.getElementById('spkManualDuration').value = tr.audio_metrics.duration_seconds || 90;
          updateSpkMetricsUI(tr.audio_metrics);
        }
      } catch (e) {
        alert('Lỗi khi nhận diện giọng nói: ' + e.message);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Chạy Whisper nhận diện giọng nói';
      }
    }

    async function submitAndAssessSpeaking() {
      const studentId = document.getElementById('spkStudentSelect').value;
      const part = document.getElementById('spkPartSelect').value;
      const promptText = document.getElementById('spkPromptInput').value.trim();
      const transcriptText = document.getElementById('spkTranscriptInput').value.trim();
      const manualDur = parseFloat(document.getElementById('spkManualDuration').value) || 90.0;

      if (!studentId) return alert('Hãy chọn học viên trước!');
      if (promptText.length < 5 || transcriptText.length < 15) return alert('Vui lòng có câu hỏi và nội dung Transcript trước khi chấm!');

      const btn = document.getElementById('assessSpkBtn');
      btn.disabled = true;
      btn.textContent = 'Đang chấm Speaking bằng Qwen3 8B (~25-40s)...';

      try {
        if (!currentSpkSubmissionId) {
          const created = await api('/api/submissions/speaking', {
            method: 'POST',
            body: JSON.stringify({
              student_id: studentId,
              task_type: part,
              prompt_text: promptText,
              transcript_text: transcriptText,
              duration_seconds: manualDur
            })
          });
          currentSpkSubmissionId = created.id;
        } else {
          await api(`/api/submissions/${currentSpkSubmissionId}/transcript`, {
            method: 'PUT',
            body: JSON.stringify({ transcript_text: transcriptText, duration_seconds: manualDur })
          });
        }

        const assessed = await api(`/api/submissions/${currentSpkSubmissionId}/assess`, {
          method: 'POST',
          body: JSON.stringify({ model_name: 'qwen3:8b', think: false })
        });
        renderSpeakingAssessment(assessed, transcriptText);
      } catch (e) {
        alert('Lỗi khi chấm Speaking: ' + e.message);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Chấm Speaking ngay (Qwen3 8B)';
      }
    }

    function renderSpeakingAssessment(assessed, transcriptText) {
      currentSpkSubmissionId = assessed.submission_id;
      currentSpkAssessmentId = assessed.id;
      currentSpkTranscriptRaw = transcriptText;

      document.getElementById('emptySpkState').classList.add('hidden');
      document.getElementById('spkResultBox').classList.remove('hidden');
      document.getElementById('spkHighlightCard').classList.remove('hidden');
      document.getElementById('spkPreviewBox').innerHTML = escapeHtml(transcriptText);

      const fb = assessed.feedback_parsed || {};
      const crit = fb.criteria || {};
      if (fb.audio_metrics) updateSpkMetricsUI(fb.audio_metrics);

      document.getElementById('spkRubricBadge').textContent = `${assessed.rubric_version} · ${assessed.model_name}`;
      document.getElementById('scFC').textContent = crit.fluency_coherence?.estimated_band ?? assessed.task_response ?? '-';
      document.getElementById('scSpkLR').textContent = crit.lexical_resource?.estimated_band ?? assessed.lexical ?? '-';
      document.getElementById('scSpkGRA').textContent = crit.grammatical_range_accuracy?.estimated_band ?? assessed.grammar ?? '-';
      document.getElementById('scPRON').textContent = crit.pronunciation?.estimated_band ?? assessed.coherence ?? '-';
      document.getElementById('scSpkOverall').textContent = assessed.estimated_overall ?? '-';

      document.getElementById('spkTeacherBandInput').value = assessed.teacher_overall ?? assessed.estimated_overall ?? 6.5;
      document.getElementById('spkTeacherFeedbackInput').value = assessed.teacher_feedback || '';
      document.getElementById('spkReviewSavedMsg').classList.add('hidden');

      const val = fb.validation_summary || {};
      const bench = fb.benchmark || {};
      document.getElementById('spkValidationBanner').innerHTML =
        `<b>Kiểm tra trích dẫn Transcript:</b> ${val.verified_quotes ?? 0}/${val.total_quotes_checked ?? 0} câu khớp 100% · <b>Tốc độ:</b> ${bench.elapsed_seconds ?? '-'}s (${bench.tokens_per_second ?? '-'} tok/s)`;

      const critBox = document.getElementById('spkCriteriaDetailsBox');
      critBox.innerHTML = '';
      const labels = {
        fluency_coherence: 'Fluency & Coherence (Độ trôi chảy, nhịp nói WPM & mạch ý)',
        lexical_resource: 'Lexical Resource (Vốn từ giao tiếp, Idioms & Collocations)',
        grammatical_range_accuracy: 'Grammatical Range & Accuracy (Cấu trúc câu nói & Ngữ pháp)',
        pronunciation: 'Pronunciation (Gợi ý sơ bộ — Giáo viên nghe audio để chốt)'
      };

      for (const [key, title] of Object.entries(labels)) {
        const c = crit[key] || {};
        const sec = document.createElement('div');
        sec.className = 'crit-section';
        sec.innerHTML = `<div class="crit-title"><span>${title}</span><span>Band ${c.estimated_band ?? '-'}</span></div>`;
        (c.evidence || []).forEach(ev => {
          const item = document.createElement('div');
          item.className = 'ev-item';
          const verifiedTag = ev.quote_verified ? '<span style="color:#4ade80;">[✓ Khớp transcript]</span>' : '<span style="color:#f87171;">[⚠ Lệch]</span>';
          item.innerHTML = `
            <div class="ev-quote">"${escapeHtml(ev.quote || '')}" ${verifiedTag} <span class="badge">${escapeHtml(ev.error_code || '')}</span></div>
            <div>${escapeHtml(ev.issue || '')}</div>
            <div class="ev-fix">→ Gợi ý nâng cấp: ${escapeHtml(ev.suggestion || '')}</div>
          `;
          item.onclick = () => highlightQuoteInBox('spkPreviewBox', currentSpkTranscriptRaw, ev.quote || '');
          sec.appendChild(item);
        });
        critBox.appendChild(sec);
      }
    }

    async function saveTeacherReview(mode) {
      const isSpk = mode === 'speaking';
      const subId = isSpk ? currentSpkSubmissionId : currentSubmissionId;
      const assId = isSpk ? currentSpkAssessmentId : currentAssessmentId;
      if (!subId) return;

      const band = parseFloat(document.getElementById(isSpk ? 'spkTeacherBandInput' : 'teacherBandInput').value);
      const feedback = document.getElementById(isSpk ? 'spkTeacherFeedbackInput' : 'teacherFeedbackInput').value.trim();

      const res = await api(`/api/submissions/${subId}/review`, {
        method: 'POST',
        body: JSON.stringify({
          assessment_id: assId,
          teacher_overall: band,
          teacher_feedback: feedback
        })
      });
      const msg = document.getElementById(isSpk ? 'spkReviewSavedMsg' : 'reviewSavedMsg');
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
        errBox.innerHTML = '<div style="font-size:0.88rem; color:var(--muted); margin-bottom:8px;">Thống kê các lỗi học viên hay mắc nhất (Writing & Speaking):</div>' +
          data.recurring_errors.map(e => `<span class="badge" style="margin-right:8px; margin-bottom:6px; display:inline-block; background:#172554; border:1px solid var(--primary);">${e.code}: ${e.error_count} lần (${e.description})</span>`).join('');
      } else {
        errBox.innerHTML = '<div style="color:var(--muted); font-size:0.88rem;">Chưa có thống kê lỗi cho học viên này.</div>';
      }

      const tbody = document.getElementById('historyTableBody');
      tbody.innerHTML = '';
      (data.submissions_history || []).forEach(row => {
        const tr = document.createElement('tr');
        const dateStr = row.assessed_at ? new Date(row.assessed_at).toLocaleString('vi-VN') : new Date(row.created_at).toLocaleString('vi-VN');
        const skillTag = row.skill === 'speaking' ? '🎙 SPEAKING' : '✍ WRITING';
        tr.innerHTML = `
          <td>${dateStr}</td>
          <td><b>${skillTag}</b> · ${row.task_type.toUpperCase()}</td>
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
      const chosen = (detail.assessments || []).find(a => a.id === assessmentId) || (detail.assessments || [])[0];

      if (detail.skill === 'speaking') {
        switchTab('speaking');
        document.getElementById('spkStudentSelect').value = detail.student_id;
        document.getElementById('spkPartSelect').value = detail.task_type;
        document.getElementById('spkPromptInput').value = detail.prompt_text;
        document.getElementById('spkTranscriptInput').value = detail.transcript_text || '';
        currentSpkSubmissionId = detail.id;
        if (detail.source_audio_path) {
          document.getElementById('spkAudioPlayer').src = `/api/submissions/${detail.id}/audio`;
          document.getElementById('audioPlayerContainer').classList.remove('hidden');
        } else {
          document.getElementById('audioPlayerContainer').classList.add('hidden');
        }
        if (chosen) renderSpeakingAssessment(chosen, detail.transcript_text || '');
      } else {
        switchTab('writing');
        document.getElementById('studentSelect').value = detail.student_id;
        document.getElementById('taskTypeSelect').value = detail.task_type;
        document.getElementById('promptInput').value = detail.prompt_text;
        document.getElementById('essayInput').value = detail.response_text;
        updateWordCount();
        if (chosen) renderWritingAssessment(chosen, detail.response_text);
      }
    }

    initApp();
  </script>
</body>
</html>
"""


def main() -> None:
    (BACKEND_DIR / "requirements.txt").write_text(REQUIREMENTS_M4_TXT, encoding="utf-8")

    trans_dir = APP_DIR / "services" / "transcription"
    spk_dir = APP_DIR / "services" / "speaking"
    prompts_dir = APP_DIR / "prompts"

    trans_dir.mkdir(parents=True, exist_ok=True)
    spk_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "audio").mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "models" / "whisper").mkdir(parents=True, exist_ok=True)

    (trans_dir / "__init__.py").write_text("", encoding="utf-8")
    (trans_dir / "whisper_service.py").write_text(WHISPER_SERVICE_PY, encoding="utf-8")
    (prompts_dir / "ielts_speaking_v1.py").write_text(SPEAKING_PROMPT_PY, encoding="utf-8")
    (spk_dir / "__init__.py").write_text("", encoding="utf-8")
    (spk_dir / "evaluator.py").write_text(SPEAKING_EVALUATOR_PY, encoding="utf-8")

    (APP_DIR / "schemas" / "domain.py").write_text(SCHEMAS_M4_PY, encoding="utf-8")
    (APP_DIR / "repositories" / "store.py").write_text(STORE_M4_PY, encoding="utf-8")
    (APP_DIR / "api" / "routes.py").write_text(ROUTES_M4_PY, encoding="utf-8")
    (DESKTOP_DIR / "index.html").write_text(UI_M4_HTML, encoding="utf-8")

    # Thêm các mã lỗi Speaking vào bảng error_tags trong SQLite
    db_file = DATA_DIR / "ielts_copilot.db"
    if db_file.exists():
        conn = sqlite3.connect(str(db_file))
        speaking_tags = [
            ("tag-fc-hesitation", "FC_HESITATION", "fluency_coherence", "Ngập ngừng, tốc độ nói chậm hoặc nghỉ giữa câu quá lâu"),
            ("tag-fc-cohesion", "FC_COHESION", "fluency_coherence", "Thiếu từ nối tự nhiên trong văn nói (discourse markers)"),
            ("tag-fc-underdev", "FC_UNDERDEVELOPED", "fluency_coherence", "Câu trả lời Speaking quá ngắn, chưa mở rộng ý"),
            ("tag-fc-repetition", "FC_REPETITION", "fluency_coherence", "Lặp từ hoặc tự sửa lại (self-correction) quá nhiều"),
            ("tag-lr-idiom", "SPEAKING_IDIOM", "lexical_resource", "Dùng thành ngữ (idiomatic expression) chưa tự nhiên"),
            ("tag-pron-check", "PRON_CHECK_REQUIRED", "pronunciation", "Cần giáo viên nghe audio kiểm tra trọng âm, âm cuối và ngữ điệu"),
        ]
        for tid, code, cat, desc in speaking_tags:
            conn.execute(
                "INSERT OR IGNORE INTO error_tags (id, code, category, description) VALUES (?, ?, ?, ?)",
                (tid, code, cat, desc),
            )
        conn.commit()
        conn.close()

    print("=" * 72)
    print("[✓] ĐÃ KHỞI TẠO MỐC 4: SPEAKING LAB + WHISPER OFFLINE + CHẤM SPEAKING!")
    print("- Đã tạo Whisper service tại: apps/backend/app/services/transcription/whisper_service.py")
    print("- Đã tạo Speaking evaluator & rubric tại: apps/backend/app/services/speaking/evaluator.py")
    print("- Đã nâng cấp giao diện 3 tab (Writing Lab · Speaking Lab · Student Records) tại: http://127.0.0.1:8000/")
    print("\n=== BƯỚC TIẾP THEO TRÊN POWERSHELL CỦA BẠN ===")
    print("1. Cài thêm faster-whisper và python-multipart (lưu cache trên ổ F:):")
    print("   .\\.venv\\Scripts\\pip.exe install faster-whisper python-multipart")
    print("2. Tải lại trang http://127.0.0.1:8000/ và bấm sang tab '2. Speaking Lab' để dùng ngay!")
    print("=" * 72)


if __name__ == "__main__":
    main()