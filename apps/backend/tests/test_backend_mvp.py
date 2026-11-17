from __future__ import annotations

from pathlib import Path
from app.db.database import init_db
from app.repositories.store import CopilotRepository
from app.services.writing.evaluator import preprocess_essay, validate_assessment


def test_end_to_end_sqlite_and_validation(tmp_path: Path):
    test_db = tmp_path / "test_ielts.db"
    init_db(test_db)
    repo = CopilotRepository(db_path=test_db)

    # 1. Tạo hồ sơ học viên
    student = repo.create_student(
        {
            "name": "Nguyen Minh Anh",
            "target_overall": 7.0,
            "target_writing": 6.5,
            "target_speaking": 7.0,
            "notes": "Hay sai hòa hợp chủ-vị (SVA) và thiếu mạo từ.",
        }
    )
    assert student["name"] == "Nguyen Minh Anh"

    # 2. Tạo bài nộp Writing Task 2
    essay = (
        "Nowadays, university attendance is a hot topic. "
        "Many young undergraduates might procrastinate and fall behind in their studies, "
        "which ultimately lead to higher dropout rates."
    )
    sub = repo.create_writing_submission(
        {
            "student_id": student["id"],
            "task_type": "task2",
            "prompt_text": "Should university classes be optional?",
            "response_text": essay,
        }
    )
    assert sub["status"] == "draft"

    # 3. Kiểm tra Validator & Lưu đánh giá
    meta = preprocess_essay(sub["prompt_text"], essay, "task2")
    mock_llm_output = {
        "criteria": {
            "task_response": {"estimated_band": 6.0, "strengths": ["Clear opinion"], "evidence": []},
            "coherence_cohesion": {"estimated_band": 6.5, "strengths": ["Logical flow"], "evidence": []},
            "lexical_resource": {"estimated_band": 6.5, "strengths": ["Good academic words"], "evidence": []},
            "grammatical_range_accuracy": {
                "estimated_band": 6.0,
                "strengths": [],
                "evidence": [
                    {
                        "quote": "which ultimately lead to higher dropout rates",
                        "error_code": "SVA",
                        "issue": "Mệnh đề quan hệ bổ nghĩa cho cả mệnh đề trước cần chia động từ số ít.",
                        "suggestion": "which ultimately leads to higher dropout rates",
                    }
                ],
            },
        },
        "priority_actions": ["Ôn lại Subject-Verb Agreement"],
        "uncertainties": [],
    }
    enriched, extracted_errors = validate_assessment(mock_llm_output, essay, meta, "qwen3:8b")
    assert enriched["estimated_overall"] == 6.5
    assert enriched["validation_summary"]["all_quotes_verified"] is True

    saved_assessment = repo.save_assessment(sub["id"], enriched, extracted_errors, "qwen3:8b")
    assert saved_assessment["estimated_overall"] == 6.5

    # 4. Giáo viên duyệt và chốt band
    reviewed = repo.save_teacher_review(
        submission_id=sub["id"],
        teacher_overall=6.0,
        teacher_feedback="Bài viết lập luận tốt nhưng cần đủ 250 từ và sửa lỗi chia động từ.",
        assessment_id=saved_assessment["id"],
    )
    assert reviewed["teacher_overall"] == 6.0

    # 5. Kiểm tra tiến độ và thống kê lỗi lặp lại
    progress = repo.get_student_progress(student["id"])
    assert progress["student"]["current_overall"] == 6.0
    assert len(progress["recurring_errors"]) == 1
    assert progress["recurring_errors"][0]["code"] == "SVA"
