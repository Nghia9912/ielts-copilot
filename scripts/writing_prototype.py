#!/usr/bin/env python3
"""IELTS Copilot - Bước 1: Prototype chấm IELTS Writing độc lập qua Ollama Local API.

Nguyên tắc kiến trúc:
1. Code thông thường (Python): Đếm từ, tách câu, kiểm tra trích dẫn (quote verification),
   kiểm tra thang điểm (0.0 - 9.0, bước 0.5) và tự tính Overall Band chuẩn IELTS.
2. LLM (Qwen3 8B / Gemma 3 4B qua Ollama): Phân tích ngôn ngữ theo rubric và trả về JSON có cấu trúc.
3. Không cần cài thêm thư viện ngoài (chỉ dùng Python Standard Library) để bạn chạy thử ngay lập tức.
"""

from __future__ import annotations

import json
import math
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

OLLAMA_API_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "qwen3:8b"
RUBRIC_VERSION = "ielts-writing-v1"


# ============================================================================
# 1. PREPROCESSING (Xử lý văn bản bằng code thông thường)
# ============================================================================
def count_words(text: str) -> int:
    """Đếm số từ chuẩn trong bài viết tiếng Anh."""
    words = re.findall(r"\b[a-zA-Z0-9]+(?:['-][a-zA-Z0-9]+)*\b", text)
    return len(words)


def split_sentences(text: str) -> list[str]:
    """Tách câu cơ bản phục vụ đối chiếu bằng chứng."""
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    return [s.strip() for s in sentences if s.strip()]


def preprocess_submission(prompt_text: str, essay_text: str, task_type: str = "task2") -> dict[str, Any]:
    """Kiểm tra đầu vào và thống kê độ dài trước khi gọi LLM."""
    if task_type not in ("task1", "task2"):
        raise ValueError("task_type phải là 'task1' hoặc 'task2'.")
    if not prompt_text.strip():
        raise ValueError("Đề bài (prompt_text) không được để trống.")
    if not essay_text.strip():
        raise ValueError("Bài viết (essay_text) không được để trống.")

    word_count = count_words(essay_text)
    min_words = 150 if task_type == "task1" else 250
    paragraphs = [p.strip() for p in essay_text.strip().split("\n") if p.strip()]
    sentences = split_sentences(essay_text)

    return {
        "task_type": task_type,
        "word_count": word_count,
        "min_words_required": min_words,
        "is_underlength": word_count < min_words,
        "paragraph_count": len(paragraphs),
        "sentence_count": len(sentences),
        "sentences": sentences,
    }


# ============================================================================
# 2. JSON SCHEMA & PROMPT (Ép Ollama sinh JSON chuẩn theo Rubric)
# ============================================================================
WRITING_ASSESSMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "object",
            "properties": {
                "task_response": {
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
                                    "issue": {"type": "string"},
                                    "suggestion": {"type": "string"},
                                },
                                "required": ["quote", "issue", "suggestion"],
                            },
                        },
                    },
                    "required": ["estimated_band", "strengths", "evidence"],
                },
                "coherence_cohesion": {
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
                                    "issue": {"type": "string"},
                                    "suggestion": {"type": "string"},
                                },
                                "required": ["quote", "issue", "suggestion"],
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
            },
            "required": [
                "task_response",
                "coherence_cohesion",
                "lexical_resource",
                "grammatical_range_accuracy",
            ],
        },
        "priority_actions": {"type": "array", "items": {"type": "string"}},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["criteria", "priority_actions", "uncertainties"],
}


def build_writing_prompt(
    prompt_text: str,
    essay_text: str,
    preprocessing_meta: dict[str, Any],
) -> tuple[str, str]:
    """Tạo system prompt và user prompt tách biệt cho Task 1 hoặc Task 2."""
    task_label = "IELTS Academic Writing Task 2" if preprocessing_meta["task_type"] == "task2" else "IELTS Academic Writing Task 1"
    first_criterion_desc = (
        "Task Response (TR): mức độ trả lời đầy đủ câu hỏi, phát triển luận điểm rõ ràng, có dẫn chứng cụ thể."
        if preprocessing_meta["task_type"] == "task2"
        else "Task Achievement (TA): mức độ tóm tắt thông tin chính, chọn lọc đặc điểm nổi bật (overview) và so sánh số liệu chính xác."
    )

    system_prompt = (
        f"You are an experienced IELTS Writing Examiner Assistant evaluating an {task_label} submission.\n"
        "CRITICAL RULES:\n"
        "1. Every 'quote' field MUST be an EXACT verbatim substring copied directly from the student's essay. Never paraphrase or invent quotes.\n"
        "2. All 'estimated_band' values must be valid IELTS bands between 0.0 and 9.0 in increments of 0.5 (e.g., 5.5, 6.0, 6.5, 7.0).\n"
        f"3. Evaluate strictly across the 4 official criteria:\n"
        f"   - {first_criterion_desc}\n"
        "   - Coherence and Cohesion (CC): bố cục đoạn văn, mạch lập luận, cách dùng cohesive devices tự nhiên.\n"
        "   - Lexical Resource (LR): vốn từ, collocations, word choice, spelling (gắn error_code như COLLOCATION, WORD_CHOICE, SPELLING).\n"
        "   - Grammatical Range and Accuracy (GRA): cấu trúc câu phức, thì, mạo từ, giới từ, sự hòa hợp chủ-vị (gắn error_code như ARTICLE, PREPOSITION, SVA, TENSE, PUNCTUATION).\n"
        "4. Return valid JSON matching the requested schema. Do not include markdown fences."
    )

    user_prompt = (
        f"=== TASK TYPE ===\n{task_label}\n\n"
        f"=== PREPROCESSING METRICS ===\n"
        f"- Word count: {preprocessing_meta['word_count']} words (Minimum required: {preprocessing_meta['min_words_required']})\n"
        f"- Underlength penalty applicable: {preprocessing_meta['is_underlength']}\n"
        f"- Paragraph count: {preprocessing_meta['paragraph_count']}\n\n"
        f"=== PROMPT ===\n{prompt_text.strip()}\n\n"
        f"=== STUDENT ESSAY ===\n{essay_text.strip()}\n"
    )
    return system_prompt, user_prompt


# ============================================================================
# 3. VALIDATION LAYER (Kiểm tra tính nhất quán bằng code Python)
# ============================================================================
def normalize_for_quote_check(text: str) -> str:
    """Chuẩn hóa khoảng trắng để kiểm tra câu trích dẫn có nằm trong bài gốc không."""
    return re.sub(r"\s+", " ", text.strip()).lower()


def is_valid_ielts_band(score: Any) -> bool:
    """Kiểm tra điểm band nằm trong khoảng [0.0, 9.0] và chia hết cho 0.5."""
    if not isinstance(score, (int, float)):
        return False
    if score < 0.0 or score > 9.0:
        return False
    return math.isclose((score * 2) % 1, 0.0, abs_tol=1e-6)


def calculate_ielts_overall_band(tr: float, cc: float, lr: float, gra: float) -> float:
    """Tính Overall Writing Band theo quy tắc làm tròn chuẩn IELTS (tới 0.5 gần nhất)."""
    avg = (tr + cc + lr + gra) / 4.0
    # Nhân 2, làm tròn nửa lên (round half up), rồi chia 2
    return math.floor(avg * 2 + 0.5) / 2.0


def validate_and_enrich_assessment(
    raw_result: dict[str, Any],
    original_essay: str,
    preprocessing_meta: dict[str, Any],
    model_name: str,
) -> dict[str, Any]:
    """Kiểm tra trích dẫn, thang điểm và bổ sung cờ kiểm duyệt cho giáo viên."""
    normalized_essay = normalize_for_quote_check(original_essay)
    validation_warnings: list[str] = []
    criteria = raw_result.get("criteria", {})

    band_scores: dict[str, float] = {}
    total_quotes = 0
    unverified_quotes = 0

    for crit_name in (
        "task_response",
        "coherence_cohesion",
        "lexical_resource",
        "grammatical_range_accuracy",
    ):
        crit_data = criteria.get(crit_name, {})
        band = crit_data.get("estimated_band")

        if not is_valid_ielts_band(band):
            validation_warnings.append(
                f"Band không hợp lệ ở '{crit_name}': {band}. Đã ép kiểu về phạm vi chuẩn."
            )
            try:
                clamped = max(0.0, min(9.0, float(band)))
                band = round(clamped * 2) / 2.0
            except (TypeError, ValueError):
                band = 0.0
            crit_data["estimated_band"] = band

        band_scores[crit_name] = float(band)

        # Kiểm tra từng câu quote trong evidence
        for item in crit_data.get("evidence", []):
            total_quotes += 1
            quote_text = item.get("quote", "")
            norm_quote = normalize_for_quote_check(quote_text)
            if norm_quote and norm_quote in normalized_essay:
                item["quote_verified"] = True
            else:
                item["quote_verified"] = False
                unverified_quotes += 1
                validation_warnings.append(
                    f"[{crit_name}] Trích dẫn không khớp nguyên văn bài gốc: \"{quote_text}\""
                )

    estimated_overall = calculate_ielts_overall_band(
        band_scores["task_response"],
        band_scores["coherence_cohesion"],
        band_scores["lexical_resource"],
        band_scores["grammatical_range_accuracy"],
    )

    uncertainties = list(raw_result.get("uncertainties", []))
    if preprocessing_meta["is_underlength"]:
        uncertainties.append(
            f"Bài viết chỉ có {preprocessing_meta['word_count']}/{preprocessing_meta['min_words_required']} từ (thiếu độ dài tối thiểu)."
        )
    uncertainties.extend(validation_warnings)

    return {
        "task_type": preprocessing_meta["task_type"],
        "rubric_version": RUBRIC_VERSION,
        "model_name": model_name,
        "preprocessing": {
            "word_count": preprocessing_meta["word_count"],
            "min_words_required": preprocessing_meta["min_words_required"],
            "is_underlength": preprocessing_meta["is_underlength"],
            "paragraph_count": preprocessing_meta["paragraph_count"],
            "sentence_count": preprocessing_meta["sentence_count"],
        },
        "estimated_overall": estimated_overall,
        "criteria": criteria,
        "priority_actions": raw_result.get("priority_actions", []),
        "uncertainties": uncertainties,
        "validation_summary": {
            "total_quotes_checked": total_quotes,
            "verified_quotes": total_quotes - unverified_quotes,
            "unverified_quotes": unverified_quotes,
            "all_quotes_verified": unverified_quotes == 0,
        },
        "teacher_review_required": True,
    }


# ============================================================================
# 4. OLLAMA CLIENT (Gọi Local LLM qua 127.0.0.1:11434)
# ============================================================================
def call_ollama_structured(
    model: str,
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    timeout_sec: int = 180,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Gọi Ollama /api/chat ở chế độ offline, ép trả về JSON theo schema."""
    # Với Qwen3, thêm /no_think vào cuối prompt nếu muốn tắt chuỗi suy luận dài để phản hồi nhanh hơn
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "format": schema,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_ctx": 8192,
        },
    }

    req = urllib.request.Request(
        OLLAMA_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start_time = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Không kết nối được với Ollama tại {OLLAMA_API_URL}. "
            "Hãy chắc chắn bạn đã bật Ollama và tải model bằng lệnh: "
            f"`ollama pull {model}` (Chi tiết: {exc})"
        ) from exc

    elapsed_sec = round(time.perf_counter() - start_time, 2)
    content_str = body.get("message", {}).get("content", "{}")
    parsed_json = json.loads(content_str)

    eval_count = body.get("eval_count", 0)
    eval_duration_ns = body.get("eval_duration", 1)
    tokens_per_sec = round(eval_count / (eval_duration_ns / 1e9), 2) if eval_duration_ns > 0 else 0.0

    benchmark_metrics = {
        "elapsed_seconds": elapsed_sec,
        "prompt_eval_tokens": body.get("prompt_eval_count", 0),
        "output_tokens": eval_count,
        "tokens_per_second": tokens_per_sec,
    }
    return parsed_json, benchmark_metrics


# ============================================================================
# 5. CHẠY THỬ NGHIỆM (DEMO & BENCHMARK)
# ============================================================================
SAMPLE_PROMPT = (
    "Some people believe that university students should be required to attend classes. "
    "Others believe that going to classes should be optional for students. "
    "Discuss both these views and give your own opinion."
)

SAMPLE_ESSAY = """Nowadays, the question of whether university attendance should be compulsory or optional has sparked considerable debate. While some argue that mandatory attendance instills discipline, I firmly believe that university students are adults who should have the freedom to manage their own learning schedules.

On the one hand, proponents of compulsory classes point out that regular attendance helps students stay engaged with the curriculum. In lectures, professors often explain complex concepts that are difficult to grasp from textbooks alone. Furthermore, classroom discussions allow students to interact with peers and clarify their doubts immediately. Without a strict attendance policy, many young undergraduates might procrastinate and fall behind in their studies, which ultimately lead to higher dropout rates.

On the other hand, treating university attendance as optional respects the autonomy of adult learners. Many students today have part-time jobs or family responsibilities to support their tuition fees. With recorded lectures and digital resources widely available, students can study effectively at their own pace. Moreover, forcing reluctant students to sit in a lecture hall does not guarantee active learning; instead, universities should evaluate students based on their assignments and final examination performance.

In conclusion, although mandatory attendance can provide structure for less disciplined learners, I contend that optional attendance is more suitable for higher education because it promotes independence and accommodates diverse student lifestyles."""


def main() -> None:
    print("=" * 72)
    print("IELTS COPILOT - PROTOTYPE CHẤM WRITING & KIỂM TRA TRÍCH DẪN (OFFLINE)")
    print("=" * 72)

    pre_meta = preprocess_submission(SAMPLE_PROMPT, SAMPLE_ESSAY, task_type="task2")
    print(
        f"[Preprocessing] Số từ: {pre_meta['word_count']} | "
        f"Số đoạn: {pre_meta['paragraph_count']} | "
        f"Số câu: {pre_meta['sentence_count']}"
    )

    sys_prompt, usr_prompt = build_writing_prompt(SAMPLE_PROMPT, SAMPLE_ESSAY, pre_meta)
    print(f"[Inference] Đang gửi bài tới model '{DEFAULT_MODEL}' qua {OLLAMA_API_URL}...")

    try:
        raw_json, bench = call_ollama_structured(
            model=DEFAULT_MODEL,
            system_prompt=sys_prompt,
            user_prompt=usr_prompt,
            schema=WRITING_ASSESSMENT_SCHEMA,
        )
    except RuntimeError as err:
        print(f"\n[!] LỖI KẾT NỐI OLLAMA:\n{err}")
        return

    final_report = validate_and_enrich_assessment(
        raw_result=raw_json,
        original_essay=SAMPLE_ESSAY,
        preprocessing_meta=pre_meta,
        model_name=DEFAULT_MODEL,
    )
    final_report["benchmark"] = bench

    output_path = Path("sample_assessment_output.json")
    output_path.write_text(json.dumps(final_report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n[Hoàn tất!]")
    print(f"- Thời gian xử lý: {bench['elapsed_seconds']}s ({bench['tokens_per_second']} tokens/s)")
    print(f"- Estimated Overall Band (tính chuẩn IELTS): {final_report['estimated_overall']}")
    print(
        f"- Kiểm tra trích dẫn: {final_report['validation_summary']['verified_quotes']}/"
        f"{final_report['validation_summary']['total_quotes_checked']} câu khớp 100% với bài gốc."
    )
    print(f"- Kết quả JSON đầy đủ đã lưu tại: {output_path.resolve()}")


if __name__ == "__main__":
    main()
