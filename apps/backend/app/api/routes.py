from __future__ import annotations

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
    """Tạo bài nộp Speaking từ văn bản transcript (hoặc bài mẫu) kèm thời lượng."""
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
    """Upload bản ghi âm MP3/WAV/M4A/WEBM an toàn vào F:/ielts-copilot/data/audio."""
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
    """Phát lại file ghi âm gốc trên giao diện giáo viên."""
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
    """Chạy faster-whisper offline chuyển file ghi âm thành văn bản kèm đo WPM & khoảng lặng."""
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
    """Cho phép giáo viên sửa lỗi nhận diện giọng nói trong transcript trước khi chấm."""
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
    """Chấm bài tự động: Tự nhận diện bài Writing hoặc Speaking để áp dụng đúng Rubric."""
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
    """Tạo bản sao lưu (Backup) cơ sở dữ liệu SQLite sang F:/ielts-copilot/data/backups."""
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


@router.delete("/submissions/{submission_id}")
def delete_single_submission(submission_id: str):
    sub = repo.get_submission(submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài nộp.")
    from app.db.database import db_session
    if sub.get("source_audio_path"):
        try:
            p = validate_and_resolve_audio_path(sub["source_audio_path"])
            if p.exists():
                p.unlink()
        except Exception:
            pass
    with db_session() as conn:
        conn.execute("DELETE FROM submissions WHERE id = ?", (submission_id,))
    return {"status": "deleted", "submission_id": submission_id}
