from __future__ import annotations
from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from app.schemas.studio import (
    AnalyzeLessonPlanRequest,
    CompanionActionRequest,
    CreatePostLessonReviewRequest,
    GenerateMaterialsRequest,
    GeneratePlaybookRequest,
    RegenerateSectionRequest,
    SessionStateUpdateRequest,
    UpdateHandoutExerciseRequest,
    UpdateLessonPlanReviewRequest,
    UpdatePlaybookActivityRequest,
    UpdateTeacherAnswerKeyRequest,
)
from app.services.studio.engine import TeachingStudioService
from app.services.studio.exporter import ExportDocType, ExportFormat, export_studio_document

studio_router = APIRouter(prefix="/api/studio", tags=["Teaching Studio"])
studio_service = TeachingStudioService()


@studio_router.post("/materials/upload")
async def upload_library_material(
    title: str = Form(""),
    skill: str = Form(""),
    file: UploadFile = File(...),
):
    content = await file.read()
    try:
        return studio_service.library.ingest_document(
            filename=file.filename or "material.txt",
            content_bytes=content,
            title=title,
            skill=skill,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@studio_router.get("/materials")
def list_library_materials(skill: str | None = None):
    return {"materials": studio_service.library.list_materials(skill=skill)}


@studio_router.delete("/materials/{material_id}")
def delete_library_material(material_id: str):
    ok = studio_service.library.delete_material(material_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu.")
    return {"status": "deleted", "material_id": material_id}


@studio_router.get("/lesson-plans")
def list_lesson_plans(student_id: str | None = None):
    return {"lesson_plans": studio_service.list_lesson_plans(student_id=student_id)}


@studio_router.get("/lesson-plans/{plan_id}")
def get_lesson_plan_detail(plan_id: str):
    plan = studio_service.get_lesson_plan_full(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Không tìm thấy Lesson Plan.")
    return plan


@studio_router.delete("/lesson-plans/{plan_id}")
def delete_lesson_plan(plan_id: str):
    ok = studio_service.delete_lesson_plan(plan_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Không tìm thấy Lesson Plan.")
    return {"status": "deleted", "lesson_plan_id": plan_id}


@studio_router.post("/lesson-plans/analyze")
def analyze_lesson_plan(payload: AnalyzeLessonPlanRequest):
    try:
        return studio_service.analyze_lesson_plan(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@studio_router.put("/lesson-plans/{plan_id}/review")
def review_and_update_lesson_plan(plan_id: str, payload: UpdateLessonPlanReviewRequest):
    try:
        return studio_service.update_lesson_plan_review(plan_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@studio_router.post("/lesson-plans/{plan_id}/playbook")
def generate_teaching_playbook(plan_id: str, payload: GeneratePlaybookRequest | None = None):
    req = payload or GeneratePlaybookRequest()
    try:
        return studio_service.generate_playbook(plan_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@studio_router.put("/activities/{activity_id}")
def update_playbook_activity(activity_id: str, payload: UpdatePlaybookActivityRequest):
    try:
        return studio_service.update_playbook_activity(activity_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@studio_router.post("/activities/{activity_id}/regenerate")
def regenerate_playbook_activity(activity_id: str, payload: RegenerateSectionRequest | None = None):
    req = payload or RegenerateSectionRequest()
    try:
        return studio_service.regenerate_single_activity(activity_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@studio_router.post("/lesson-plans/{plan_id}/materials")
def generate_handout_and_guide(plan_id: str, payload: GenerateMaterialsRequest | None = None):
    req = payload or GenerateMaterialsRequest()
    try:
        return studio_service.generate_handout_and_teacher_guide(plan_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@studio_router.put("/exercises/{exercise_id}")
def update_handout_exercise(exercise_id: str, payload: UpdateHandoutExerciseRequest):
    try:
        return studio_service.update_handout_exercise(exercise_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@studio_router.post("/exercises/{exercise_id}/regenerate")
def regenerate_handout_exercise(exercise_id: str, payload: RegenerateSectionRequest | None = None):
    req = payload or RegenerateSectionRequest()
    try:
        return studio_service.regenerate_single_exercise(exercise_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@studio_router.put("/teacher-guides/{guide_id}/answer-key")
def update_teacher_guide_answer_key(guide_id: str, payload: UpdateTeacherAnswerKeyRequest):
    try:
        return studio_service.update_teacher_answer_key(guide_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@studio_router.post("/lesson-plans/{plan_id}/session")
def start_or_get_teaching_session(plan_id: str):
    try:
        return studio_service.start_or_get_session(plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@studio_router.put("/sessions/{session_id}")
def update_teaching_session_state(session_id: str, payload: SessionStateUpdateRequest):
    try:
        return studio_service.update_session_state(session_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@studio_router.post("/sessions/{session_id}/companion")
def execute_companion_action(session_id: str, payload: CompanionActionRequest):
    try:
        return studio_service.run_companion_action(session_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@studio_router.post("/lesson-plans/{plan_id}/reviews")
def create_post_lesson_review(plan_id: str, payload: CreatePostLessonReviewRequest):
    try:
        return studio_service.create_post_lesson_review(plan_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@studio_router.post("/reviews/{review_id}/confirm-history")
def confirm_student_history_from_review(review_id: str):
    try:
        return studio_service.confirm_student_history_update(review_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@studio_router.get("/lesson-plans/{plan_id}/export/{doc_type}")
def export_teaching_studio_document(
    plan_id: str,
    doc_type: ExportDocType,
    fmt: ExportFormat = "docx",
):
    plan = studio_service.get_lesson_plan_full(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Không tìm thấy Lesson Plan.")
    try:
        file_bytes, filename, media_type = export_studio_document(plan, doc_type=doc_type, fmt=fmt)
        return Response(
            content=file_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
