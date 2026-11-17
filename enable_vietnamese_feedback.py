from pathlib import Path
import re

root = Path.cwd()

# 1. Cập nhật Prompt chấm Writing: Thang 70/30 + Bắt buộc Nhận xét & Gợi ý sửa bằng Tiếng Việt
PROMPT_VN_70_30 = """from typing import Any

RUBRIC_VERSION = "ielts-writing-v2.3-vn-balanced-70-30"

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
            "   - 'task_response' (Task Achievement cho Task 1) CHỈ đánh giá:\\n"
            "     * Bài viết có đoạn Overview rõ ràng tóm tắt xu hướng chính không? (Nếu thiếu/mơ hồ, gắn mã TA_NO_OVERVIEW và khóa trần 5.5).\\n"
            "     * Số liệu và so sánh có khớp với dữ liệu biểu đồ (CHART REFERENCE DATA) không? (Nếu sai lệch, gắn mã TA_INACCURATE_DATA).\\n"
            "     * Có làm nổi bật và so sánh các đặc điểm chính thay vì liệt kê máy móc không? (Gắn mã TA_KEY_FEATURE_MISSING)."
        )
    else:
        tr_instructions = (
            "   - 'task_response' (Task Response cho Task 2) CHỈ đánh giá:\\n"
            "     * Người viết có trả lời đầy đủ các vế của đề bài với quan điểm xuyên suốt không?\\n"
            "     * Các luận điểm chính có được giải thích sâu và kèm ví dụ cụ thể không? (Nếu ý sơ sài, chung chung, gắn mã TR_UNDERDEVELOPED và chấm 5.5–6.0).\\n"
            "     * Mã lỗi hợp lệ: TR_UNDERDEVELOPED, TR_UNBALANCED, TR_OFF_TOPIC, TR_UNCLEAR_POSITION."
        )

    system_prompt = f\"\"\"Bạn là Giám khảo Chấm thi IELTS Writing Cấp cao của Cambridge (Senior Cambridge IELTS Examiner) đang chấm bài {task_label}.
Nhiệm vụ của bạn là chấm điểm Band (từ 0.0 đến 9.0, bước nhảy 0.5) theo tỷ lệ: 70% Khắt khe chuẩn phòng thi thực chiến + 30% Nương tay hợp lý, và VIẾT TOÀN BỘ NHẬN XÉT, GIẢI THÍCH LỖI VÀ GỢI Ý SỬA BẰNG TIẾNG VIỆT.

=== QUY TẮC NGÔN NGỮ BẮT BUỘC (100% TIẾNG VIỆT CHO NHẬN XÉT & GỢI Ý SỬA) ===
1. Trường 'quote': BẮT BUỘC giữ nguyên văn 100% câu/cụm từ tiếng Anh trích từ bài làm của học viên (để phần mềm tô sáng trên bài gốc).
2. Trường 'issue' (Nhận xét lỗi): BẮT BUỘC viết bằng TIẾNG VIỆT rõ ràng, dễ hiểu, giải thích cụ thể câu trích dẫn đó sai hoặc yếu ở đâu theo tiêu chí IELTS.
3. Trường 'suggestion' (Gợi ý sửa): BẮT BUỘC hướng dẫn cách sửa bằng TIẾNG VIỆT, kèm theo cụm từ/câu tiếng Anh đã sửa chuẩn đặt trong dấu ngoặc kép.
   - Ví dụ chuẩn cho 'suggestion': "Đổi 'make time to visit' thành cụm collocation tự nhiên hơn và bỏ mạo từ 'the' trước 'life' -> Sửa thành: 'spend uninterrupted time visiting extended relatives throughout their lives'."
4. Mọi trường nhận xét tổng quát ('summary', 'overall_feedback', 'strengths', 'priority_improvements' nếu có) đều BẮT BUỘC viết bằng TIẾNG VIỆT.

=== 1. QUY TẮC 30% NƯƠNG TAY HỢP LÝ (CÔNG BẰNG, KHÔNG PHẠT KÉP) ===
- KHÔNG PHẠT KÉP CHÉO TIÊU CHÍ:
  * Tuyệt đối KHÔNG trừ điểm 'task_response' hay 'coherence_cohesion' vì lỗi ngữ pháp, mạo từ, giới từ, dấu câu hay từ vựng.
{tr_instructions}
  * 'coherence_cohesion' CHỈ chấm chia đoạn, mạch triển khai ý, câu chủ đề và từ nối (CC_COHESION, CC_PARAGRAPHING, CC_REFERENCING, CC_PROGRESSION).
  * 'lexical_resource' CHỈ chấm vốn từ, collocations, cách chọn từ, văn phong học thuật và chính tả (COLLOCATION, WORD_CHOICE, SPELLING, REGISTER).
  * 'grammatical_range_accuracy' CHỈ chấm độ đa dạng cấu trúc câu phức, thì, mạo từ, giới từ và dấu câu (ARTICLE, PREPOSITION, SVA, TENSE, PUNCTUATION, SYNTAX).
- CHẤP NHẬN LỖI NHỎ RẢI RÁC:
  * Không hạ điểm từ 7.0 xuống 5.5 chỉ vì 1–2 lỗi trượt nhỏ không mang tính hệ thống nếu phần còn lại có nhiều câu phức sạch lỗi.

=== 2. QUY TẮC 70% KHẮT KHE THỰC CHIẾN (CHỐNG LẠM PHÁT ĐIỂM 6.5 - 7.0) ===
Không chấm vống các bài mức trung bình lên 6.5 hoặc 7.0. Áp dụng nghiêm ngặt các mốc trần sau:
- TRẦN BAND 5.0 – 5.5:
  * Chấm 5.0–5.5 nếu luận điểm nêu ra nhưng thiếu giải thích/ví dụ cụ thể, dùng từ nối máy móc ở đầu mọi câu, từ vựng lặp lại/cơ bản, HOẶC có từ 4 lỗi ngữ pháp/mạo từ/giới từ đáng chú ý trở lên.
- MỐC BAND 6.0:
  * Chấm 6.0 khi bài viết trả lời đúng đề và có kết hợp câu đơn + câu phức, NHƯNG một số ý phụ còn chung chung HOẶC có 2–3 lỗi ngữ pháp/collocation lặp lại trong mỗi đoạn.
- MỐC BAND 6.5:
  * Chỉ chấm 6.5 khi lập luận chặt chẽ, phát triển ý rõ ràng, dùng câu phức thường xuyên và chỉ có một vài lỗi nhỏ không làm ảnh hưởng nghĩa.
- CHỐT CHẶN BAND 7.0+ (NGHIÊM NGẶT):
  * Chỉ chấm 7.0 khi TẤT CẢ các phần của đề bài được phát triển sâu sắc, chuyển ý mượt mà, dùng collocation học thuật tự nhiên và đa số câu đều hoàn toàn sạch lỗi (tối đa 1–2 lỗi nhỏ toàn bài).

=== 3. SỐ LƯỢNG TRÍCH DẪN ===
- Mỗi tiêu chí trích dẫn từ 1 đến 2 dẫn chứng ('evidence') tiêu biểu nhất.
\"\"\"

    user_prompt = (
        f"=== LOẠI BÀI (TASK TYPE) ===\\n{task_label}\\n\\n"
        f"=== THÔNG SỐ ĐỊNH LƯỢNG ===\\n"
        f"- Số từ: {meta['word_count']} từ (Yêu cầu tối thiểu: {meta['min_words_required']} từ)\\n"
        f"- Bị phạt thiếu từ (Underlength): {meta['is_underlength']}\\n"
        f"- Số đoạn văn: {meta['paragraph_count']} | Số câu: {meta['sentence_count']}\\n\\n"
        f"=== ĐỀ BÀI & DỮ LIỆU ĐỐI CHIẾU ===\\n{prompt_text.strip()}\\n\\n"
        f"=== BÀI LÀM CỦA HỌC VIÊN ===\\n{essay_text.strip()}\\n\\n"
        f"LƯU Ý QUAN TRỌNG: Hãy viết tất cả các trường 'issue', 'suggestion' và nhận xét bằng TIẾNG VIỆT (chỉ giữ nguyên 'quote' bằng tiếng Anh trích từ bài làm và câu tiếng Anh mẫu sửa lại)."
    )
    return system_prompt, user_prompt
"""

prompt_path = root / "apps" / "backend" / "app" / "prompts" / "ielts_writing_v2.py"
prompt_path.write_text(PROMPT_VN_70_30, encoding="utf-8")

# 2. Cập nhật mô tả JSON Schema trong writing/evaluator.py và speaking/evaluator.py (nếu có) sang Tiếng Việt
for eval_rel in [
    "apps/backend/app/services/writing/evaluator.py",
    "apps/backend/app/services/speaking/evaluator.py",
]:
    p = root / eval_rel
    if p.exists():
        txt = p.read_text(encoding="utf-8")
        # Đảm bảo nếu có prompt tiếng Anh trong speaking evaluator thì thêm chỉ dẫn Tiếng Việt
        if "speaking" in eval_rel and "TIẾNG VIỆT" not in txt:
            txt = txt.replace(
                "=== STUDENT TRANSCRIPT ===",
                "QUY TẮC NGÔN NGỮ: Viết toàn bộ nhận xét lỗi ('issue'), gợi ý sửa ('suggestion') và tóm tắt bằng TIẾNG VIỆT (giữ nguyên 'quote' tiếng Anh và câu tiếng Anh sửa mẫu).\n\n=== STUDENT TRANSCRIPT ===",
            )
        p.write_text(txt, encoding="utf-8")

print("[OK] Đã chuyển toàn bộ phần Nhận xét lỗi (issue) và Gợi ý sửa (suggestion) sang Tiếng Việt!")
