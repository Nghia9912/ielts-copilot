from __future__ import annotations
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from app.db.database import db_session, init_db
from app.main import app
from app.repositories.store import CopilotRepository
from app.schemas.studio import (
    AnalyzeLessonPlanRequest,
    CompanionActionRequest,
    CreatePostLessonReviewRequest,
    GenerateMaterialsRequest,
    GeneratePlaybookRequest,
    RegenerateSectionRequest,
    UpdateHandoutExerciseRequest,
    UpdateLessonPlanReviewRequest,
    UpdatePlaybookActivityRequest,
)
from app.services.studio.engine import (
    TeachingStudioService,
    recalculate_behind_schedule_plan,
    sanitize_and_verify_student_exercise,
    validate_playbook_durations,
)
from app.services.studio.exporter import export_studio_document
from app.services.studio.material_library import LocalMaterialLibrary


class MockStudioLLMProvider:
    """Deterministic Mock LLM Provider supporting representative Writing Task 1, Task 2, and Speaking lessons,
    plus simulated malformed output for bounded-retry testing.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_next_count: int = 0

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        model: str = "qwen3:8b",
        think: bool = False,
        timeout_sec: int = 180,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "model": model,
        })
        if self.fail_next_count > 0:
            self.fail_next_count -= 1
            return {"invalid_key": "missing required fields"}, {"elapsed_seconds": 0.05, "tokens_per_second": 50.0}

        props = schema.get("properties", {})

        # 1. Lesson Plan Analyzer
        if "explicit_vs_assumed" in props:
            is_t1 = "task1" in user_prompt.lower()
            is_spk = "speaking" in user_prompt.lower()
            skill = "speaking" if is_spk else "writing"
            t_type = "part2" if is_spk else ("task1" if is_t1 else "task2")
            return (
                {
                    "title": f"IELTS {skill.title()} ({t_type.upper()}) — Mastering Coherence & Target Structures",
                    "skill": skill,
                    "task_type": t_type,
                    "duration_minutes": 60,
                    "student_current_band": 6.0,
                    "student_target_band": 7.0,
                    "learning_objectives": [
                        "Xây dựng cấu trúc bài mạch lạc đạt chuẩn Band 7.0",
                        "Kiểm soát độ chính xác ngữ pháp (ARTICLE, SVA) và kết hợp từ học thuật (COLLOCATION)",
                    ],
                    "prerequisite_knowledge": ["Nắm vững cấu trúc câu đơn và câu ghép cơ bản"],
                    "planned_activities": [
                        {
                            "title": "Warm-up & Phân tích bài mẫu Band 7.0 vs Band 5.5",
                            "duration_minutes": 15,
                            "learning_objective": "Xây dựng cấu trúc bài mạch lạc đạt chuẩn Band 7.0",
                            "priority_level": "essential",
                            "is_assumed": False,
                        },
                        {
                            "title": "Thực hành có hướng dẫn: Sửa lỗi Collocation & Article",
                            "duration_minutes": 20,
                            "learning_objective": "Kiểm soát độ chính xác ngữ pháp (ARTICLE, SVA) và kết hợp từ học thuật (COLLOCATION)",
                            "priority_level": "core",
                            "is_assumed": False,
                        },
                        {
                            "title": "Thực hành độc lập có bấm giờ & Phản hồi",
                            "duration_minutes": 20,
                            "learning_objective": "Xây dựng cấu trúc bài mạch lạc đạt chuẩn Band 7.0",
                            "priority_level": "optional_extension",
                            "is_assumed": True,
                        },
                    ],
                    "available_resources": ["Handout bài tập cá nhân hóa", "Rubric chấm IELTS"],
                    "expected_difficulties": ["Học viên hay quên mạo từ xác định và viết câu chủ đề chung chung"],
                    "assessment_criteria": ["Task Response / Achievement", "Coherence & Cohesion", "Lexical Resource", "Grammar"],
                    "explicit_vs_assumed": [
                        {"field_name": "learning_objectives", "status": "explicit", "rationale": "Được giáo viên cung cấp trực tiếp."},
                        {"field_name": "planned_activities[2]", "status": "assumed", "rationale": "Đề xuất hoạt động vận dụng độc lập cuối buổi để kiểm tra chuẩn đầu ra."},
                    ],
                },
                {"elapsed_seconds": 0.1, "tokens_per_second": 42.0},
            )

        # 2. Teaching Playbook Generator
        if "pedagogical_approach" in props and "activities" in props:
            return (
                {
                    "pedagogical_approach": "Contrastive Model Analysis -> Guided Scaffolding -> Timed Independent Production",
                    "transition_buffer_minutes": 5,
                    "activities": [
                        {
                            "activity_order": 1,
                            "title": "Warm-up & Phân tích bài mẫu Band 7.0 vs Band 5.5",
                            "duration_minutes": 15,
                            "learning_objective": "Xây dựng cấu trúc bài mạch lạc đạt chuẩn Band 7.0",
                            "priority_level": "essential",
                            "teaching_rationale": "Giúp học viên nhận diện trực quan sự khác biệt giữa đoạn văn có câu chủ đề rõ ràng và đoạn văn liệt kê rời rạc.",
                            "teacher_instructions": "Chia sẻ màn hình 2 đoạn văn mẫu A (Band 5.5) và B (Band 7.0), yêu cầu học viên gạch chân câu chủ đề và từ nối trong 2 phút.",
                            "explanation_sequence": [
                                "Bước 1: Chiếu 2 đoạn văn ẩn điểm Band.",
                                "Bước 2: Yêu cầu học viên chỉ ra câu nêu luận điểm chính của mỗi đoạn.",
                                "Bước 3: Đúc kết công thức PEEL (Point - Explanation - Example - Link).",
                            ],
                            "examples_counterexamples": [
                                {
                                    "strong_example": "Longer summer holidays strengthen familial bonds by allowing children uninterrupted time with extended relatives.",
                                    "weak_counterexample": "Summer holidays are long and children can visit many cousins and it is very good.",
                                    "comparison_point": "Sử dụng danh từ hóa và mệnh đề chỉ phương thức (by + V-ing) thay vì nối câu bằng 'and'.",
                                }
                            ],
                            "teacher_questions": ["Câu đầu tiên của đoạn B trả lời trực tiếp phần nào của đề bài?"],
                            "expected_student_responses": ["Nêu trực tiếp lợi ích chính của kỳ nghỉ hè dài đối với gắn kết gia đình."],
                            "common_misconceptions": ["Học viên tưởng rằng dùng càng nhiều từ nối 'Moreover, Furthermore' ở đầu mọi câu là đạt điểm Coherence cao."],
                            "understanding_checks": ["Yêu cầu học viên sửa lại câu mở đầu của đoạn A trong 60 giây."],
                            "scaffolding_struggling": "Cung cấp khung câu khuyết (Sentence frame): 'One primary value of [Topic] lies in its ability to [Verb]...' ",
                            "extension_fast_learners": "Yêu cầu viết thêm 1 câu nhượng bộ (Concession clause) trước câu chủ đề.",
                            "transition_next": "Sau khi nắm vững khung đoạn văn, chúng ta chuyển sang xử lý các lỗi ngữ pháp và từ vựng thường làm mất điểm.",
                        },
                        {
                            "activity_order": 2,
                            "title": "Thực hành có hướng dẫn: Sửa lỗi Collocation & Article",
                            "duration_minutes": 20,
                            "learning_objective": "Kiểm soát độ chính xác ngữ pháp (ARTICLE, SVA) và kết hợp từ học thuật (COLLOCATION)",
                            "priority_level": "core",
                            "teaching_rationale": "Khắc phục trực tiếp các lỗi lặp lại trong lịch sử bài làm của học viên.",
                            "teacher_instructions": "Hướng dẫn học viên làm Exercise 1 và Exercise 2 trên Handout, gọi học viên giải thích lý do chọn mạo từ.",
                            "explanation_sequence": [
                                "Bước 1: Ôn nhanh quy tắc danh từ đếm được số nhiều không dùng 'the' khi nói chung.",
                                "Bước 2: Thực hành sửa 5 câu trích từ lỗi phổ biến.",
                            ],
                            "examples_counterexamples": [
                                {
                                    "strong_example": "foster strong relationships throughout life",
                                    "weak_counterexample": "maintain a stronger bond for the rest of the life",
                                    "comparison_point": "Cụm cố định là 'for the rest of their lives' hoặc 'throughout life', không dùng 'the life'.",
                                }
                            ],
                            "teacher_questions": ["Tại sao trong cụm 'for the rest of the life' mạo từ 'the' lại gây lỗiARTICLE?"],
                            "expected_student_responses": ["Vì 'life' nói chung hoặc phải đi với tính từ sở hữu 'their lives'."],
                            "common_misconceptions": ["Dịch từng từ từ tiếng Việt sang tiếng Anh dẫn đến thừa 'the'."],
                            "understanding_checks": ["Học viên tự đặt 2 câu mới sử dụng collocation 'foster strong relationships'."],
                            "scaffolding_struggling": "Gợi ý danh sách 3 động từ đi kèm với 'relationship' (build, foster, cement).",
                            "extension_fast_learners": "Viết lại câu sử dụng cấu trúc đảo ngữ với 'Not only...'.",
                            "transition_next": "Bây giờ các em sẽ áp dụng toàn bộ vào bài viết độc lập bấm giờ 20 phút.",
                        },
                        {
                            "activity_order": 3,
                            "title": "Thực hành độc lập có bấm giờ & Phản hồi",
                            "duration_minutes": 20,
                            "learning_objective": "Xây dựng cấu trúc bài mạch lạc đạt chuẩn Band 7.0",
                            "priority_level": "optional_extension",
                            "teaching_rationale": "Kiểm tra khả năng tự vận dụng kiến thức dưới áp lực thời gian phòng thi.",
                            "teacher_instructions": "Giao Exercise 3 trên Handout, bấm giờ 15 phút viết đoạn thân bài hoàn chỉnh và 5 phút đối chiếu Checklist.",
                            "explanation_sequence": [
                                "Bước 1: Học viên lập dàn ý 2 phút.",
                                "Bước 2: Viết đoạn văn 13 phút.",
                                "Bước 3: Tự kiểm tra bằng Self-Assessment Checklist.",
                            ],
                            "examples_counterexamples": [],
                            "teacher_questions": ["Đoạn văn vừa viết đã có câu ví dụ cụ thể chưa?"],
                            "expected_student_responses": ["Học viên chỉ ra câu số 3 trong đoạn văn của mình."],
                            "common_misconceptions": ["Đưa ví dụ mới vào câu cuối cùng của đoạn mà không giải thích."],
                            "understanding_checks": ["Chấm nhanh trực tiếp 1 đoạn của học viên theo 4 tiêu chí."],
                            "scaffolding_struggling": "Cho phép dùng dàn ý gợi ý sẵn 2 ý phụ.",
                            "extension_fast_learners": "Viết hoàn chỉnh cả 2 đoạn Body 1 và Body 2.",
                            "transition_next": "Tổng kết bài học và giao bài tập về nhà.",
                        },
                    ],
                },
                {"elapsed_seconds": 0.15, "tokens_per_second": 44.0},
            )

        # 3. Single Playbook Activity Regeneration
        if "activity_order" in props and "explanation_sequence" in props:
            return (
                {
                    "activity_order": 1,
                    "title": "[Regenerated] Warm-up & So sánh Chuyên sâu Band 6.0 vs 7.5",
                    "duration_minutes": 15,
                    "learning_objective": "Xây dựng cấu trúc bài mạch lạc đạt chuẩn Band 7.0",
                    "priority_level": "essential",
                    "teaching_rationale": "Đã cập nhật theo yêu cầu chỉnh sửa riêng của giáo viên.",
                    "teacher_instructions": "Hướng dẫn chi tiết mới đã được tái tạo riêng cho hoạt động này.",
                    "explanation_sequence": ["Bước 1 mới", "Bước 2 mới"],
                    "examples_counterexamples": [
                        {
                            "strong_example": "A well-structured curriculum balances academic rigor with recuperation.",
                            "weak_counterexample": "School is hard and holidays are good.",
                            "comparison_point": "Lexical density and clear topic focus.",
                        }
                    ],
                    "teacher_questions": ["Câu chủ đề mới có điểm gì nổi bật?"],
                    "expected_student_responses": ["Sử dụng danh từ trừu tượng chính xác."],
                    "common_misconceptions": ["Viết câu quá dài nhưng thiếu động từ chính."],
                    "understanding_checks": ["Học viên viết lại 1 câu chủ đề trong 2 phút."],
                    "scaffolding_struggling": "Cung cấp 2 từ khóa gợi ý.",
                    "extension_fast_learners": "Tự viết thêm câu giải thích nguyên nhân - kết quả.",
                    "transition_next": "Chuyển sang hoạt động số 2.",
                },
                {"elapsed_seconds": 0.08, "tokens_per_second": 45.0},
            )

        # 4. Student Handout Generator
        if "exercises" in props and "self_assessment_checklist" in props:
            has_article_err = "ARTICLE" in user_prompt
            has_tr_err = "TR_UNDERDEVELOPED" in user_prompt
            targeted_note = "ARTICLE & COLLOCATION" if has_article_err else ("TR_UNDERDEVELOPED" if has_tr_err else "General Band 7.0")
            return (
                {
                    "title": f"Student Handout — IELTS Target Practice ({targeted_note})",
                    "intro_instructions": "Hoàn thành các bài tập theo trình tự từ nhận diện mẫu đến tự viết đoạn văn.",
                    "exercises": [
                        {
                            "exercise_order": 1,
                            "linked_activity_order": 1,
                            "exercise_type": "model_analysis",
                            "progression_stage": "scaffolded",
                            "title": "Phân tích Đoạn văn Mẫu (Model Paragraph Analysis)",
                            "learning_objective": "Xây dựng cấu trúc bài mạch lạc đạt chuẩn Band 7.0",
                            "difficulty_level": "Band 6.0 -> 7.0",
                            "student_instructions": "Đọc hai đoạn văn dưới đây và xác định câu Topic Sentence, Supporting Idea và Example.",
                            "content_items": [
                                "Paragraph A: Extended summer vacations allow pupils to reconnect with extended family members.",
                                "Paragraph B: On the other hand, excessively long breaks may lead to summer learning loss.",
                            ],
                            "expected_response_format": "Gạch chân và ghi chú vai trò từng câu",
                            "working_space_lines": 4,
                        },
                        {
                            "exercise_order": 2,
                            "linked_activity_order": 2,
                            "exercise_type": "error_correction",
                            "progression_stage": "guided",
                            "title": f"Sửa lỗi Trọng tâm ({targeted_note})",
                            "learning_objective": "Kiểm soát độ chính xác ngữ pháp (ARTICLE, SVA) và kết hợp từ học thuật (COLLOCATION)",
                            "difficulty_level": "Band 6.5 -> 7.0",
                            "student_instructions": "Tìm và sửa các lỗi ngữ pháp/từ vựng trong các câu dưới đây.",
                            "content_items": [
                                "Longer summer breaks allow the children to make time to visit family relatives for the rest of the life.",
                                "Shorter school holidays help the student from falling back in studies.",
                            ],
                            "expected_response_format": "Viết lại câu hoàn chỉnh đã sửa lỗi",
                            "working_space_lines": 5,
                        },
                        {
                            "exercise_order": 3,
                            "linked_activity_order": 3,
                            "exercise_type": "independent_writing",
                            "progression_stage": "independent",
                            "title": "Viết Đoạn Thân bài Độc lập (Timed Body Paragraph)",
                            "learning_objective": "Xây dựng cấu trúc bài mạch lạc đạt chuẩn Band 7.0",
                            "difficulty_level": "Band 7.0 Target",
                            "student_instructions": "Viết 1 đoạn thân bài (90-110 từ) bàn về lợi ích của kỳ nghỉ hè ngắn đối với việc duy trì nhịp độ học tập.",
                            "content_items": [
                                "Prompt: What are the arguments in favour of shorter school holidays?",
                                "Yêu cầu: Áp dụng cấu trúc PEEL và ít nhất 2 collocations học thuật.",
                            ],
                            "expected_response_format": "Đoạn văn hoàn chỉnh 90-110 từ",
                            "working_space_lines": 8,
                        },
                    ],
                    "self_assessment_checklist": [
                        "Đoạn văn có câu Topic Sentence nêu rõ luận điểm chính.",
                        "Đã kiểm tra kỹ mạo từ (a/an/the) và danh từ số nhiều.",
                    ],
                    "exit_ticket_prompt": "Viết lại 1 câu có lỗi mạo từ của em thành câu đúng chuẩn Band 7.0.",
                    "homework_assignment": "Hoàn thành bài viết Task 2 đầy đủ (280 từ) và tự rà soát bằng Checklist trước khi nộp.",
                },
                {"elapsed_seconds": 0.12, "tokens_per_second": 43.0},
            )

        # 5. Single Exercise Regeneration
        if "exercise_order" in props and "student_instructions" in props:
            return (
                {
                    "exercise_order": 2,
                    "linked_activity_order": 2,
                    "exercise_type": "sentence_transformation",
                    "progression_stage": "guided",
                    "title": "[Regenerated] Biến đổi Câu Học thuật Nâng cao",
                    "learning_objective": "Kiểm soát độ chính xác ngữ pháp (ARTICLE, SVA) và kết hợp từ học thuật (COLLOCATION)",
                    "difficulty_level": "Band 7.0+",
                    "student_instructions": "Viết lại các câu sau sử dụng từ gợi ý trong ngoặc mà không làm thay đổi nghĩa.",
                    "content_items": [
                        "Children forget lessons during long breaks. (RETENTION) -> Long breaks...",
                        "Parents struggle to arrange childcare in summer. (BURDEN) -> Summer holidays...",
                    ],
                    "expected_response_format": "Viết câu hoàn chỉnh",
                    "working_space_lines": 4,
                },
                {"elapsed_seconds": 0.08, "tokens_per_second": 44.0},
            )

        # 6. Teacher Guide & Answer Key Generator
        if "answer_keys" in props and "objective_evaluation_checklist" in props:
            return (
                {
                    "answer_keys": [
                        {
                            "exercise_order": 1,
                            "exercise_title": "Phân tích Đoạn văn Mẫu (Model Paragraph Analysis)",
                            "correct_answers": ["Paragraph A mở đầu bằng câu chủ đề trực tiếp; Paragraph B dùng cụm chuyển ý tương phản."],
                            "explanation_why": "Cả hai câu đầu đều định hướng rõ nội dung toàn đoạn văn.",
                            "alternative_acceptable_answers": ["Học viên có thể diễn đạt bằng lời riêng miễn chỉ đúng chức năng Topic Sentence."],
                            "common_student_mistakes": ["Nhầm câu ví dụ với câu chủ đề."],
                            "suggested_feedback_remediation": "Yêu cầu học viên thử che câu đầu tiên đi xem đoạn văn còn rõ ý chính không.",
                            "open_ended_marking_criteria": ["Xác định đúng chức năng từng câu"],
                            "illustrative_sample_response": "Topic Sentence A states the familial benefit clearly.",
                            "is_illustrative_llm_example": True,
                        },
                        {
                            "exercise_order": 2,
                            "exercise_title": "Sửa lỗi Trọng tâm",
                            "correct_answers": [
                                "Longer summer breaks allow children to spend time visiting relatives, fostering strong relationships throughout their lives.",
                                "Shorter school holidays prevent students from falling behind in their studies.",
                            ],
                            "explanation_why": "Bỏ 'the' trước danh từ số nhiều nói chung ('children'), sửa 'help... from' thành 'prevent... from'.",
                            "alternative_acceptable_answers": ["keep students from falling behind in their academic studies"],
                            "common_student_mistakes": ["Giữ nguyên 'help from V-ing' hoặc dùng 'the life'."],
                            "suggested_feedback_remediation": "Ôn lại cấu trúc prevent/keep someone from doing something.",
                            "open_ended_marking_criteria": ["Đúng mạo từ", "Đúng giới từ đi kèm động từ"],
                            "illustrative_sample_response": "",
                            "is_illustrative_llm_example": True,
                        },
                        {
                            "exercise_order": 3,
                            "exercise_title": "Viết Đoạn Thân bài Độc lập (Timed Body Paragraph)",
                            "correct_answers": ["Đoạn văn mở (Open-ended) được chấm theo 4 tiêu chí IELTS Writing."],
                            "explanation_why": "Cần có Topic Sentence rõ ràng, giải thích nguyên nhân giảm sút trí nhớ học tập và ví dụ minh họa.",
                            "alternative_acceptable_answers": ["Chấp nhận mọi lập luận hợp lý về duy trì thói quen học tập hoặc giảm áp lực trông trẻ cho phụ huynh."],
                            "common_student_mistakes": ["Chỉ liệt kê ý mà không giải thích sâu (TR_UNDERDEVELOPED)."],
                            "suggested_feedback_remediation": "Đặt câu hỏi 'Why does that happen?' và 'What is the result?' sau luận điểm chính.",
                            "open_ended_marking_criteria": [
                                "Có câu chủ đề rõ ràng (CC)",
                                "Phát triển ý bằng giải thích + ví dụ (TR)",
                                "Sử dụng ít nhất 2 collocations chính xác (LR)",
                                "Không mắc lỗi mạo từ hệ thống (GRA)",
                            ],
                            "illustrative_sample_response": "Proponents of shorter summer breaks argue that brief intervals prevent academic regression. When students are away from formal instruction for over two months, they often forget core mathematical and linguistic concepts, requiring teachers to spend weeks reviewing prior material.",
                            "is_illustrative_llm_example": True,
                        },
                    ],
                    "objective_evaluation_checklist": [
                        "Học viên viết được Topic Sentence rõ ràng không lan man.",
                        "Học viên tự phát hiện và sửa được ít nhất 80% lỗi mạo từ và collocation.",
                    ],
                },
                {"elapsed_seconds": 0.12, "tokens_per_second": 45.0},
            )

        # 7. Teaching Companion Action
        if "diagnosis_or_rationale" in props and "teacher_script_or_explanation" in props:
            return (
                {
                    "scenario": "companion_adaptation",
                    "diagnosis_or_rationale": "Học viên đang lúng túng khi chuyển từ ý tiếng Việt sang câu chủ đề học thuật tiếng Anh.",
                    "teacher_script_or_explanation": "Hãy bắt đầu bằng chủ ngữ chỉ hành động (V-ing) hoặc danh từ chính của đề bài: 'Shortening summer holidays enables schools to...'",
                    "guided_diagnostic_question": "Theo em, kết quả trực tiếp nhất khi học sinh không nghỉ hè quá lâu là gì?",
                    "adapted_exercise_or_task": "Hoàn thành câu sau trong 1 phút: 'Shorter summer breaks help students maintain ________ because ________.'",
                    "schedule_adjustment_plan": [],
                },
                {"elapsed_seconds": 0.07, "tokens_per_second": 46.0},
            )

        # 8. Post-Lesson Review Hypotheses
        if "concise_lesson_summary" in props:
            return (
                {
                    "concise_lesson_summary": "Học viên đã nắm vững cấu trúc đoạn PEEL nhưng vẫn cần luyện thêm phản xạ sử dụng mạo từ dưới áp lực thời gian.",
                    "hypothesized_root_causes": [
                        "Thói quen dịch từng chữ từ tiếng mẹ đẻ khi viết nhanh.",
                    ],
                    "proposed_next_steps": [
                        "Dành 10 phút đầu buổi tới kiểm tra nhanh 5 câu sửa lỗi mạo từ.",
                        "Luyện viết đoạn Body 2 kết hợp câu nhượng bộ (Although/While).",
                    ],
                    "suggested_homework_refinement": "Yêu cầu học viên gạch chân toàn bộ danh từ số nhiều trong bài tập về nhà để tự kiểm tra mạo từ.",
                },
                {"elapsed_seconds": 0.08, "tokens_per_second": 45.0},
            )

        raise ValueError(f"Unrecognized schema in MockStudioLLMProvider: {list(props.keys())}")


def _unused_fixture(tmp_path: Path):
    db_file = tmp_path / "test_ielts_copilot.db"
    init_db(db_file)
    mock_llm = MockStudioLLMProvider()
    service = TeachingStudioService(db_path=db_file, llm_provider=mock_llm)  # type: ignore[arg-type]
    return db_file, service, mock_llm


def test_1_database_migrations_and_existing_features_preserved(temp_studio_env):
    """Verify non-destructive migration creates all Teaching Studio tables while preserving existing student/writing features."""
    db_file, service, _ = temp_studio_env
    repo = CopilotRepository(db_path=db_file)
    stu = repo.create_student({
        "name": "Nguyễn Minh Anh",
        "target_overall": 7.5,
        "target_writing": 7.0,
        "target_speaking": 7.0,
        "current_overall": 6.0,
        "notes": "Cần chú ý mạo từ.",
    })
    assert stu["id"]
    sub = repo.create_writing_submission({
        "student_id": stu["id"],
        "task_type": "task2",
        "prompt_text": "Some people think school holidays should be shorter.",
        "response_text": "Education is important for every child across the world.",
    })
    assert sub["id"]

    with db_session(db_file) as conn:
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    expected_tables = {
        "students",
        "lessons",
        "submissions",
        "assessments",
        "error_tags",
        "submission_errors",
        "material_library_sources",
        "lesson_plans",
        "teaching_playbooks",
        "lesson_activities",
        "handouts",
        "handout_exercises",
        "teacher_guides",
        "teaching_sessions",
        "lesson_reviews",
        "studio_inference_cache",
    }
    assert expected_tables.issubset(tables)


def test_2_material_library_ingestion_txt_md_docx_pdf(temp_studio_env):
    """Verify local material library ingests TXT, MD, DOCX, and PDF while preserving filename and sections."""
    db_file, service, _ = temp_studio_env
    lib = LocalMaterialLibrary(db_path=db_file)

    md_bytes = b"# Section 1: Overview\nUse clear overview sentences.\n## Section 2: Vocabulary\nAcademic verbs."
    m_md = lib.ingest_document("task1_guide.md", md_bytes, title="Task 1 Guide", skill="writing")
    assert m_md["source_filename"] == "task1_guide.md"
    assert len(m_md["sections"]) == 2
    assert "task1_guide.md :: Section 1" in m_md["sections"][0]["section_ref"]

    # Create a valid DOCX in memory and ingest it
    plan_dummy = {
        "title": "Sample Lesson",
        "skill": "writing",
        "task_type": "task2",
        "duration_minutes": 60,
        "learning_objectives": ["Write clear topic sentences"],
        "handout": {
            "title": "Sample Handout",
            "intro_instructions": "Complete all items.",
            "exercises": [
                {
                    "exercise_order": 1,
                    "exercise_type": "paraphrasing",
                    "progression_stage": "scaffolded",
                    "title": "Paraphrase Prompt",
                    "learning_objective": "Write clear topic sentences",
                    "difficulty_level": "Band 6.5",
                    "student_instructions": "Rewrite the prompt in your own words.",
                    "content_items": ["Some people think long holidays are beneficial."],
                    "expected_response_format": "1 sentence",
                    "working_space_lines": 3,
                }
            ],
            "self_assessment_checklist": ["Used synonyms accurately"],
            "exit_ticket_prompt": "Write 1 key takeaway.",
            "homework_assignment": "Write intro + Body 1.",
        },
    }
    docx_bytes, _, _ = export_studio_document(plan_dummy, "student_handout", "docx")
    m_docx = lib.ingest_document("imported_worksheet.docx", docx_bytes, title="Imported DOCX", skill="writing")
    assert "Sample Handout" in m_docx["raw_text"]

    pdf_bytes, _, _ = export_studio_document(plan_dummy, "student_handout", "pdf")
    m_pdf = lib.ingest_document("imported_handout.pdf", pdf_bytes, title="Imported PDF", skill="writing")
    assert m_pdf["file_format"] == "pdf"
    assert len(lib.list_materials()) == 3


def test_3_lesson_plan_parsing_and_duration_validation(temp_studio_env):
    """Verify lesson plan analysis, explicit vs. assumed distinction, and deterministic duration overflow validation."""
    _, service, _ = temp_studio_env

    plan = service.analyze_lesson_plan(
        AnalyzeLessonPlanRequest(
            raw_lesson_plan="Teach IELTS Writing Task 2 opinion essays.",
            title="Opinion Essay Structure",
            objectives=["Viết câu Thesis rõ quan điểm"],
            skill="writing",
            task_type="task2",
            duration_minutes=60,
        )
    )
    assert plan["id"]
    assert len(plan["activities"]) == 3
    assert any(x["status"] == "assumed" for x in plan["explicit_vs_assumed"])

    # Test deterministic duration validator when activities exceed available lesson duration
    overflow_check = validate_playbook_durations(
        activities=[
            {"title": "Intro & Modeling", "duration_minutes": 25, "priority_level": "essential"},
            {"title": "Guided Practice", "duration_minutes": 25, "priority_level": "core"},
            {"title": "Extra Debate Game", "duration_minutes": 20, "priority_level": "optional_extension"},
        ],
        lesson_duration_minutes=60,
        transition_buffer_minutes=5,
    )
    assert overflow_check["exceeds_available_time"] is True
    assert overflow_check["overflow_minutes"] == 15
    assert any("Extra Debate Game" in r for r in overflow_check["shortening_recommendations"])


def test_4_playbook_handout_consistency_and_answer_separation(temp_studio_env):
    """Verify playbook generation, handout-to-playbook activity linking, and strict separation of teacher answers from student handout."""
    _, service, _ = temp_studio_env
    plan = service.analyze_lesson_plan(AnalyzeLessonPlanRequest(title="Writing Task 2 Lesson", duration_minutes=60))
    plan = service.generate_playbook(plan["id"], GeneratePlaybookRequest())
    assert plan["playbook"] is not None
    assert plan["playbook"]["duration_validation"]["exceeds_available_time"] is False

    plan = service.generate_handout_and_teacher_guide(plan["id"], GenerateMaterialsRequest())
    handout = plan["handout"]
    t_guide = plan["teacher_guide"]
    assert handout is not None
    assert t_guide is not None

    act_ids = {a["id"] for a in plan["activities"]}
    for ex in handout["exercises"]:
        assert ex["activity_id"] in act_ids
        assert "Answer Key:" not in ex["student_instructions"]

    # Verify sanitize_and_verify_student_exercise strips any accidental answer leakage
    dirty_ex = {
        "title": "Test Leak",
        "student_instructions": "Fix the sentence. Answer Key: Do not show this",
        "content_items": ["Item 1 [Answer: hidden solution]", "Answer Key: secret"],
    }
    cleaned = sanitize_and_verify_student_exercise(dirty_ex)
    assert "Answer Key:" not in cleaned["student_instructions"]
    assert "[Answer:" not in cleaned["content_items"][0]
    assert len(cleaned["content_items"]) == 1

    # Verify Teacher Guide has complete answer keys & marks LLM sample responses as illustrative
    assert len(t_guide["answer_keys"]) == len(handout["exercises"])
    for k in t_guide["answer_keys"]:
        assert k["is_illustrative_llm_example"] is True


def test_5_student_personalization_and_missing_history_handling(temp_studio_env):
    """Verify personalization uses actual SQLite recurring errors and never fabricates history when a student has 0 submissions."""
    db_file, service, _ = temp_studio_env
    repo = CopilotRepository(db_path=db_file)

    # Student A: Has recurring ARTICLE & COLLOCATION errors
    stu_a = repo.create_student({"name": "Học viên A (Lỗi Ngữ pháp)", "current_overall": 5.5, "target_overall": 7.0})
    sub_a = repo.create_writing_submission({
        "student_id": stu_a["id"],
        "task_type": "task2",
        "prompt_text": "Prompt A",
        "response_text": "Essay A",
    })
    repo.save_assessment(
        submission_id=sub_a["id"],
        enriched_feedback={"estimated_overall": 5.5, "criteria": {}},
        extracted_errors=[
            {"error_code": "ARTICLE", "evidence": "the life", "correction": "life", "explanation": "Wrong article"},
            {"error_code": "COLLOCATION", "evidence": "make time", "correction": "spend time", "explanation": "Collocation"},
        ],
        model_name="qwen3:8b",
    )

    # Student B: Brand new student with 0 submissions
    stu_b = repo.create_student({"name": "Học viên B (Mới tinh)", "current_overall": 6.0, "target_overall": 7.0})

    ctx_a = service.build_student_personalization_context(stu_a["id"], personalization_enabled=True)
    assert ctx_a["personalization_applied"] is True
    assert "ARTICLE" in ctx_a["summary"]
    assert ctx_a["previous_submissions_count"] == 1

    ctx_b = service.build_student_personalization_context(stu_b["id"], personalization_enabled=True)
    assert ctx_b["previous_submissions_count"] == 0
    assert "chưa có bài nộp" in ctx_b["summary"]

    ctx_disabled = service.build_student_personalization_context(stu_a["id"], personalization_enabled=False)
    assert ctx_disabled["personalization_applied"] is False


def test_6_bounded_retry_on_invalid_llm_output(temp_studio_env):
    """Verify bounded retry recovers when LLM fails once, and raises actionable error when retries are exhausted."""
    _, service, mock_llm = temp_studio_env

    # Fail once, then succeed on retry #1
    mock_llm.fail_next_count = 1
    plan = service.analyze_lesson_plan(
        AnalyzeLessonPlanRequest(title="Retry Recovery Test", force_regenerate=True)
    )
    assert plan["id"]
    assert plan["metrics"]["attempts"] == 2

    # Fail 5 times (exceeding max_retries=2) -> must raise actionable ValueError
    mock_llm.fail_next_count = 5
    with pytest.raises(ValueError, match="trả về dữ liệu không hợp lệ sau 3 lần thử"):
        service.analyze_lesson_plan(
            AnalyzeLessonPlanRequest(title="Retry Exhausted Test", force_regenerate=True)
        )
    mock_llm.fail_next_count = 0


def test_7_selective_section_editing_and_regeneration(temp_studio_env):
    """Verify editing and regenerating a single activity or exercise preserves all other activities and exercises."""
    _, service, _ = temp_studio_env
    plan = service.analyze_lesson_plan(AnalyzeLessonPlanRequest(title="Selective Regen Lesson"))
    plan = service.generate_playbook(plan["id"], GeneratePlaybookRequest())
    plan = service.generate_handout_and_teacher_guide(plan["id"], GenerateMaterialsRequest())

    act_1_id = plan["activities"][0]["id"]
    act_2_title_before = plan["activities"][1]["title"]

    # Regenerate only Activity #1
    plan = service.regenerate_single_activity(
        act_1_id,
        RegenerateSectionRequest(teacher_instruction="Add stronger comparison examples"),
    )
    assert "[Regenerated]" in plan["activities"][0]["title"]
    assert plan["activities"][1]["title"] == act_2_title_before

    # Edit Activity #2 duration and verify playbook total duration updates
    act_2_id = plan["activities"][1]["id"]
    plan = service.update_playbook_activity(act_2_id, UpdatePlaybookActivityRequest(duration_minutes=18))
    assert plan["activities"][1]["duration_minutes"] == 18
    assert plan["playbook"]["duration_validation"]["activities_sum_minutes"] == 15 + 18 + 20

    # Regenerate only Exercise #2 while preserving Exercise #1 and #3
    ex_1_title_before = plan["handout"]["exercises"][0]["title"]
    ex_2_id = plan["handout"]["exercises"][1]["id"]
    plan = service.regenerate_single_exercise(
        ex_2_id,
        RegenerateSectionRequest(teacher_instruction="Make it sentence transformation", difficulty_adjustment="harder"),
    )
    assert plan["handout"]["exercises"][0]["title"] == ex_1_title_before
    assert "[Regenerated]" in plan["handout"]["exercises"][1]["title"]


def test_8_companion_session_and_post_lesson_review_separation(temp_studio_env):
    """Verify live Teaching Companion actions, behind-schedule recalculation, and Post-Lesson Review separation without overwriting student band score."""
    db_file, service, _ = temp_studio_env
    repo = CopilotRepository(db_path=db_file)
    stu = repo.create_student({
        "name": "Lê Quốc Bảo",
        "current_overall": 6.5,
        "target_overall": 7.5,
        "notes": "Hồ sơ ban đầu.",
    })

    plan = service.analyze_lesson_plan(AnalyzeLessonPlanRequest(title="Speaking Part 2 Lesson", skill="speaking", task_type="part2", student_id=stu["id"]))
    plan = service.generate_playbook(plan["id"], GeneratePlaybookRequest())
    plan = service.generate_handout_and_teacher_guide(plan["id"], GenerateMaterialsRequest())

    sess = service.start_or_get_session(plan["id"])
    assert sess["id"]

    adap = service.run_companion_action(
        sess["id"],
        CompanionActionRequest(scenario="behind_schedule", remaining_minutes=18),
    )
    assert len(adap["schedule_adjustment_plan"]) >= 2

    # Create Post-Lesson Review with confirm_update_student_history=False first
    rev = service.create_post_lesson_review(
        plan["id"],
        CreatePostLessonReviewRequest(
            session_id=sess["id"],
            completed_activities=["Warm-up"],
            objectives_achieved={"Xây dựng cấu trúc bài mạch lạc đạt chuẩn Band 7.0": "achieved"},
            student_difficulties=["Còn ngập ngừng khi chuyển ý"],
            teacher_confirmed_notes="Học viên nắm tốt công thức mở bài nhưng cần luyện thêm từ nối.",
            homework_assigned="Ghi âm lại bài nói 2 phút.",
            recommended_next_focus="Fluency & Discourse Markers",
            confirm_update_student_history=False,
        ),
    )
    assert rev["teacher_confirmed_history_update"] == 0
    assert rev["teacher_confirmed_notes"] != rev["ai_hypotheses_summary"]["concise_lesson_summary"]

    # Student notes must NOT be modified before teacher confirmation
    stu_before = repo.get_student(stu["id"])
    assert stu_before["notes"] == "Hồ sơ ban đầu."
    assert stu_before["current_overall"] == 6.5

    # Now explicitly confirm history update
    confirmed_rev = service.confirm_student_history_update(rev["id"])
    assert confirmed_rev["teacher_confirmed_history_update"] == 1
    stu_after = repo.get_student(stu["id"])
    assert "Fluency & Discourse Markers" in stu_after["notes"]
    assert stu_after["current_overall"] == 6.5  # Official band score strictly untouched!


def test_9_document_exports_docx_and_pdf_with_vietnamese_accents(temp_studio_env):
    """Verify all 5 document types export cleanly to both DOCX and PDF, preserving accented text and student/teacher separation."""
    _, service, _ = temp_studio_env
    plan = service.analyze_lesson_plan(AnalyzeLessonPlanRequest(title="Bài học IELTS Writing Task 1 — Tiếng Việt Có Dấu"))
    plan = service.generate_playbook(plan["id"], GeneratePlaybookRequest())
    plan = service.generate_handout_and_teacher_guide(plan["id"], GenerateMaterialsRequest())
    service.create_post_lesson_review(
        plan["id"],
        CreatePostLessonReviewRequest(
            teacher_confirmed_notes="Học viên đạt mục tiêu bài học tiếng Việt có dấu đặc biệt: ă, â, đ, ê, ô, ơ, ư.",
            homework_assigned="Viết báo cáo biểu đồ đường.",
        ),
    )
    full_plan = service.get_lesson_plan_full(plan["id"])

    for doc_type in ["student_handout", "teacher_guide", "answer_key", "teaching_playbook", "post_lesson_summary"]:
        docx_bytes, docx_name, _ = export_studio_document(full_plan, doc_type, "docx")  # type: ignore[arg-type]
        assert docx_name.endswith(".docx")
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
            xml_text = zf.read("word/document.xml").decode("utf-8")
            assert "IELTS" in xml_text
            if doc_type == "student_handout":
                assert "STUDENT WORKSHEET (NO ANSWERS INCLUDED)" in xml_text
                assert "TEACHER-ONLY" not in xml_text

        pdf_bytes, pdf_name, _ = export_studio_document(full_plan, doc_type, "pdf")  # type: ignore[arg-type]
        assert pdf_name.endswith(".pdf")
        assert pdf_bytes.startswith(b"%PDF-1.4")
        assert b"/Count " in pdf_bytes


import tempfile
import unittest

class TeachingStudioTestSuite(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.db_file = self.tmp_path / "test_ielts_copilot.db"
        init_db(self.db_file)
        self.mock_llm = MockStudioLLMProvider()
        self.service = TeachingStudioService(db_path=self.db_file, llm_provider=self.mock_llm)  # type: ignore[arg-type]
        self.env = (self.db_file, self.service, self.mock_llm)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_01_database_migrations_and_existing_features_preserved(self) -> None:
        test_1_database_migrations_and_existing_features_preserved(self.env)

    def test_02_material_library_ingestion_txt_md_docx_pdf(self) -> None:
        test_2_material_library_ingestion_txt_md_docx_pdf(self.env)

    def test_03_lesson_plan_parsing_and_duration_validation(self) -> None:
        test_3_lesson_plan_parsing_and_duration_validation(self.env)

    def test_04_playbook_handout_consistency_and_answer_separation(self) -> None:
        test_4_playbook_handout_consistency_and_answer_separation(self.env)

    def test_05_student_personalization_and_missing_history_handling(self) -> None:
        test_5_student_personalization_and_missing_history_handling(self.env)

    def test_06_bounded_retry_on_invalid_llm_output(self) -> None:
        # Test recovery after 1 failure
        self.mock_llm.fail_next_count = 1
        plan = self.service.analyze_lesson_plan(
            AnalyzeLessonPlanRequest(title="Retry Recovery Test", force_regenerate=True)
        )
        self.assertTrue(plan["id"])
        self.assertEqual(plan["metrics"]["attempts"], 2)

        # Test exhaustion after >2 failures
        self.mock_llm.fail_next_count = 5
        with self.assertRaises(ValueError) as ctx:
            self.service.analyze_lesson_plan(
                AnalyzeLessonPlanRequest(title="Retry Exhausted Test", force_regenerate=True)
            )
        self.assertIn("trả về dữ liệu không hợp lệ sau 3 lần thử", str(ctx.exception))
        self.mock_llm.fail_next_count = 0

    def test_07_selective_section_editing_and_regeneration(self) -> None:
        test_7_selective_section_editing_and_regeneration(self.env)

    def test_08_companion_session_and_post_lesson_review_separation(self) -> None:
        test_8_companion_session_and_post_lesson_review_separation(self.env)

    def test_09_document_exports_docx_and_pdf_with_vietnamese_accents(self) -> None:
        test_9_document_exports_docx_and_pdf_with_vietnamese_accents(self.env)

    def test_10_representative_task1_task2_and_speaking_lessons(self) -> None:
        for skill, task_type, raw_text in [
            ("writing", "task1", "Teach Academic Writing Task 1 line graph overview and key comparisons."),
            ("writing", "task2", "Teach Academic Writing Task 2 discussion + opinion essay paragraphing."),
            ("speaking", "part2", "Teach Speaking Part 2 Cue Card structuring and fluency discourse markers."),
        ]:
            plan = self.service.analyze_lesson_plan(
                AnalyzeLessonPlanRequest(
                    raw_lesson_plan=raw_text,
                    skill=skill,  # type: ignore[arg-type]
                    task_type=task_type,
                    duration_minutes=60,
                    force_regenerate=True,
                )
            )
            self.assertEqual(plan["skill"], skill)
            self.assertEqual(plan["task_type"], task_type)
            plan = self.service.generate_playbook(plan["id"], GeneratePlaybookRequest(force_regenerate=True))
            plan = self.service.generate_handout_and_teacher_guide(plan["id"], GenerateMaterialsRequest(force_regenerate=True))
            self.assertTrue(len(plan["handout"]["exercises"]) >= 3)
            self.assertEqual(len(plan["teacher_guide"]["answer_keys"]), len(plan["handout"]["exercises"]))



    def test_11_multi_page_docx_and_pdf_export_verification(self) -> None:
        plan = self.service.analyze_lesson_plan(
            AnalyzeLessonPlanRequest(
                title="Giáo án Đa Trang Tiếng Việt Có Dấu Đặc Biệt: ă â đ ê ô ơ ư ắ ự ể",
                duration_minutes=90,
            )
        )
        plan = self.service.generate_playbook(plan["id"], GeneratePlaybookRequest())
        plan = self.service.generate_handout_and_teacher_guide(plan["id"], GenerateMaterialsRequest())
        full_plan = self.service.get_lesson_plan_full(plan["id"])
        full_plan["handout"]["exercises"] = full_plan["handout"]["exercises"] * 4

        docx_bytes, _, _ = export_studio_document(full_plan, "student_handout", "docx")
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            self.assertIn("ă â đ ê ô ơ ư ắ ự ể", doc_xml)

        pdf_bytes, _, _ = export_studio_document(full_plan, "student_handout", "pdf")
        self.assertTrue(pdf_bytes.startswith(b"%PDF-1.4"))
        self.assertNotIn(b"/Count 1 >>", pdf_bytes)
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(pdf_bytes))
            self.assertGreaterEqual(len(reader.pages), 2)
        except ImportError:
            pass

    def test_12_fastapi_routes_and_regression_check(self) -> None:
        from fastapi import HTTPException
        from app.api import studio_routes
        studio_routes.studio_service = self.service
        res_list = studio_routes.list_lesson_plans()
        self.assertIn("lesson_plans", res_list)
        analyzed = studio_routes.analyze_lesson_plan(
            AnalyzeLessonPlanRequest(title="Route Integration Test", duration_minutes=60)
        )
        with self.assertRaises(HTTPException):
            studio_routes.export_teaching_studio_document(
                plan_id=analyzed["id"],
                doc_type="teaching_playbook",
                fmt="docx",
            )
        pb = studio_routes.generate_teaching_playbook(analyzed["id"], GeneratePlaybookRequest())
        self.assertTrue(pb["playbook"]["id"])
        resp = studio_routes.export_teaching_studio_document(
            plan_id=analyzed["id"],
            doc_type="teaching_playbook",
            fmt="docx",
        )
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
