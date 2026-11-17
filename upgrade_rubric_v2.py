#!/usr/bin/env python3
"""IELTS Copilot - Bản nâng cấp Rubric v2 (ielts-writing-v2):
Khắc phục lỗi AI chấm quá gắt (5.5 thay vì 6.5-7.0) và phạt trùng lỗi chéo tiêu chí.

Chạy tại thư mục F:\\ielts-copilot:
    .\\.venv\\Scripts\\python.exe upgrade_rubric_v2.py
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path.cwd()
APP_DIR = PROJECT_ROOT / "apps" / "backend" / "app"
PROMPTS_DIR = APP_DIR / "prompts"
WRITING_DIR = APP_DIR / "services" / "writing"


PROMPT_V2_PY = """from __future__ import annotations

from typing import Any

RUBRIC_VERSION = "ielts-writing-v2-cambridge-calibrated"

# Phân loại mã lỗi hợp lệ cho từng tiêu chí (Chống phạt trùng lỗi chéo tiêu chí)
ALLOWED_CRITERION_ERROR_CODES: dict[str, set[str]] = {
    "task_response": {"TR_UNDERDEVELOPED", "TR_UNBALANCED", "TR_OFF_TOPIC", "TR_UNCLEAR_POSITION"},
    "coherence_cohesion": {"CC_COHESION", "CC_PARAGRAPHING", "CC_REFERENCING", "CC_PROGRESSION"},
    "lexical_resource": {"COLLOCATION", "WORD_CHOICE", "SPELLING", "REGISTER"},
    "grammatical_range_accuracy": {"ARTICLE", "PREPOSITION", "SVA", "TENSE", "PUNCTUATION", "SYNTAX"},
}


def build_calibrated_writing_prompts(
    prompt_text: str,
    essay_text: str,
    meta: dict[str, Any],
) -> tuple[str, str]:
    task_label = (
        "IELTS Academic Writing Task 2"
        if meta["task_type"] == "task2"
        else "IELTS Academic Writing Task 1"
    )

    system_prompt = f\"\"\"You are a certified Senior Cambridge IELTS Writing Examiner evaluating an {task_label} script.
Your goal is to assign accurate, fair, Cambridge-calibrated band scores (0.0 to 9.0, in 0.5 increments) rather than acting like a pedantic proofreader.

=== CRITICAL CALIBRATION RULES (DO NOT VIOLATE) ===
1. NO CROSS-CRITERION DOUBLE PENALIZATION:
   - NEVER penalize 'task_response' or 'coherence_cohesion' for grammar, article, preposition, punctuation, or vocabulary/collocation slips!
   - 'task_response' ONLY evaluates: Did the writer answer all parts of the prompt? Is there a clear position? Are main ideas relevant and supported? (Allowed error_code: TR_UNDERDEVELOPED, TR_UNBALANCED, TR_OFF_TOPIC, TR_UNCLEAR_POSITION).
   - 'coherence_cohesion' ONLY evaluates: Paragraphing, logical progression of ideas, topic sentences, and cohesive devices. (Allowed error_code: CC_COHESION, CC_PARAGRAPHING, CC_REFERENCING, CC_PROGRESSION).
   - 'lexical_resource' ONLY evaluates: Vocabulary range, topic-specific terms, collocations, register, and spelling. (Allowed error_code: COLLOCATION, WORD_CHOICE, SPELLING, REGISTER).
   - 'grammatical_range_accuracy' ONLY evaluates: Variety of complex sentence structures, clauses, tenses, articles, prepositions, and punctuation. (Allowed error_code: ARTICLE, PREPOSITION, SVA, TENSE, PUNCTUATION, SYNTAX).

2. OFFICIAL CAMBRIDGE BAND ANCHORS (BAND 6 vs BAND 7 vs BAND 8):
   - BAND 7.0 ANCHOR:
     * Task Response (7.0): Addresses all parts of the task; presents a clear position and extends main ideas, even if there is occasional over-generalisation or a minor lapse in focus.
     * Coherence & Cohesion (7.0): Logically organises information into clear paragraphs with a clear central topic in each paragraph; uses cohesive devices flexibly even with minor under/over-use.
     * Lexical Resource (7.0): Uses a sufficient range of vocabulary to allow some flexibility and precision; uses some less common lexical items with awareness of style, EVEN IF occasional errors in word choice, collocation, or phrasing occur (e.g., "middle eastern location", "early relationship"). As long as the meaning is completely clear and vocabulary is varied, award 6.5 or 7.0—do NOT drop to 5.5!
     * Grammatical Range & Accuracy (7.0): Uses a variety of complex structures (relative clauses, conditionals, contrast clauses); produces frequent error-free sentences, EVEN IF a few errors in grammar, articles, prepositions, or punctuation persist (e.g., "(or)", missing plural "-s"). If errors never obscure communication, award 6.5 or 7.0—do NOT drop to 5.0!
   - BAND 6.0 ANCHOR:
     * Addresses the task but some parts are more fully covered than others; coherent arrangement with some faulty cohesion; adequate vocabulary with noticeable errors that never obscure meaning; mix of simple and complex sentence forms with some systematic grammar errors.
   - BAND 5.0 ANCHOR (ONLY use 5.0-5.5 if severely flawed):
     * Incompletely addresses the task, lacks paragraphing, uses very limited/repetitive vocabulary, or makes frequent grammatical errors that cause real difficulty for the reader.

3. VERBATIM QUOTES & CONCISE EVIDENCE:
   - Include at most 2 key evidence items per criterion (focus only on the most impactful issues).
   - Every 'quote' MUST be copied 100% verbatim (character-for-character, including exact capitalization) from the Student Essay. Never trim the beginning of a sentence and capitalize the next word.
\"\"\"

    user_prompt = (
        f"=== TASK TYPE ===\\n{task_label}\\n\\n"
        f"=== PREPROCESSING METRICS ===\\n"
        f"- Word count: {meta['word_count']} words (Minimum required: {meta['min_words_required']})\\n"
        f"- Underlength penalty applicable: {meta['is_underlength']}\\n"
        f"- Paragraph count: {meta['paragraph_count']} | Sentence count: {meta['sentence_count']}\\n\\n"
        f"=== PROMPT ===\\n{prompt_text.strip()}\\n\\n"
        f"=== STUDENT ESSAY ===\\n{essay_text.strip()}\\n"
    )
    return system_prompt, user_prompt
"""


EVALUATOR_V2_PY = """from __future__ import annotations

import math
import re
from typing import Any

from app.prompts.ielts_writing_v2 import (
    ALLOWED_CRITERION_ERROR_CODES,
    RUBRIC_VERSION,
    build_calibrated_writing_prompts,
)

WRITING_SCHEMA: dict[str, Any] = {
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


def preprocess_essay(prompt_text: str, essay_text: str, task_type: str = "task2") -> dict[str, Any]:
    words = re.findall(r"\\b[a-zA-Z0-9]+(?:['-][a-zA-Z0-9]+)*\\b", essay_text)
    word_count = len(words)
    min_words = 150 if task_type == "task1" else 250
    paragraphs = [p.strip() for p in essay_text.strip().split("\\n") if p.strip()]
    cleaned = re.sub(r"\\s+", " ", essay_text.strip())
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\\s+", cleaned) if s.strip()] if cleaned else []
    return {
        "task_type": task_type,
        "word_count": word_count,
        "min_words_required": min_words,
        "is_underlength": word_count < min_words,
        "paragraph_count": len(paragraphs),
        "sentence_count": len(sentences),
    }


def build_prompts(prompt_text: str, essay_text: str, meta: dict[str, Any]) -> tuple[str, str]:
    return build_calibrated_writing_prompts(prompt_text, essay_text, meta)


def calculate_overall_band(tr: float, cc: float, lr: float, gra: float) -> float:
    avg = (tr + cc + lr + gra) / 4.0
    return math.floor(avg * 2 + 0.5) / 2.0


def validate_assessment(
    raw_json: dict[str, Any],
    essay_text: str,
    meta: dict[str, Any],
    model_name: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    norm_essay = re.sub(r"\\s+", " ", essay_text.strip()).lower()
    criteria = raw_json.get("criteria", {})
    warnings: list[str] = []
    extracted_errors: list[dict[str, Any]] = []
    scores: dict[str, float] = {}
    total_quotes = 0
    unverified_quotes = 0
    cross_criterion_violations = 0

    for key in ("task_response", "coherence_cohesion", "lexical_resource", "grammatical_range_accuracy"):
        c_obj = criteria.get(key, {})
        raw_band = c_obj.get("estimated_band", 0.0)
        try:
            clamped = max(0.0, min(9.0, float(raw_band)))
            band = round(clamped * 2) / 2.0
        except (TypeError, ValueError):
            band = 0.0
        c_obj["estimated_band"] = band
        scores[key] = band

        allowed_codes = ALLOWED_CRITERION_ERROR_CODES.get(key, set())
        filtered_evidence: list[dict[str, Any]] = []

        for ev in c_obj.get("evidence", []):
            total_quotes += 1
            quote = ev.get("quote", "")
            err_code = ev.get("error_code", "WORD_CHOICE").upper().strip()
            ev["error_code"] = err_code

            norm_q = re.sub(r"\\s+", " ", quote.strip()).lower()
            is_verified = bool(norm_q and norm_q in norm_essay)
            ev["quote_verified"] = is_verified
            if not is_verified:
                unverified_quotes += 1
                warnings.append(f"[{key}] Quote không khớp nguyên văn: {quote}")

            # Kiểm tra xem AI có lấy lỗi ngữ pháp/từ vựng nhét nhầm vào TR hoặc CC không
            if key in ("task_response", "coherence_cohesion") and err_code not in allowed_codes:
                cross_criterion_violations += 1
                ev["misplaced_criterion_warning"] = (
                    f"Lỗi '{err_code}' thuộc về Ngữ pháp/Từ vựng, không được dùng để trừ điểm '{key}'."
                )
                warnings.append(ev["misplaced_criterion_warning"])

            filtered_evidence.append(ev)
            extracted_errors.append(
                {
                    "error_code": err_code,
                    "evidence": quote,
                    "correction": ev.get("suggestion", ""),
                    "explanation": ev.get("issue", ""),
                    "confidence": 1.0 if is_verified else 0.4,
                }
            )

        c_obj["evidence"] = filtered_evidence

    overall = calculate_overall_band(
        scores["task_response"],
        scores["coherence_cohesion"],
        scores["lexical_resource"],
        scores["grammatical_range_accuracy"],
    )

    uncertainties = list(raw_json.get("uncertainties", []))
    if meta["is_underlength"]:
        uncertainties.append(f"Thiếu từ: {meta['word_count']}/{meta['min_words_required']} từ.")
    uncertainties.extend(warnings)

    enriched = {
        "task_type": meta["task_type"],
        "rubric_version": RUBRIC_VERSION,
        "model_name": model_name,
        "preprocessing": meta,
        "estimated_overall": overall,
        "criteria": criteria,
        "priority_actions": raw_json.get("priority_actions", []),
        "uncertainties": uncertainties,
        "validation_summary": {
            "total_quotes_checked": total_quotes,
            "verified_quotes": total_quotes - unverified_quotes,
            "unverified_quotes": unverified_quotes,
            "all_quotes_verified": unverified_quotes == 0,
            "cross_criterion_violations": cross_criterion_violations,
        },
        "teacher_review_required": True,
    }
    return enriched, extracted_errors
"""


def main() -> None:
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    WRITING_DIR.mkdir(parents=True, exist_ok=True)

    (PROMPTS_DIR / "__init__.py").write_text("", encoding="utf-8")
    (PROMPTS_DIR / "ielts_writing_v2.py").write_text(PROMPT_V2_PY, encoding="utf-8")
    (WRITING_DIR / "evaluator.py").write_text(EVALUATOR_V2_PY, encoding="utf-8")

    # Bổ sung thêm các mã lỗi TR và CC vào bảng error_tags trong database.py
    db_file = PROJECT_ROOT / "data" / "ielts_copilot.db"
    if db_file.exists():
        import sqlite3
        conn = sqlite3.connect(str(db_file))
        new_tags = [
            ("tag-tr-unbalanced", "TR_UNBALANCED", "task_response", "Trả lời chưa cân đối giữa các vế của câu hỏi"),
            ("tag-tr-off-topic", "TR_OFF_TOPIC", "task_response", "Luận điểm đi lệch trọng tâm đề bài"),
            ("tag-tr-unclear", "TR_UNCLEAR_POSITION", "task_response", "Quan điểm cá nhân chưa rõ ràng hoặc mâu thuẫn"),
            ("tag-cc-paragraphing", "CC_PARAGRAPHING", "coherence_cohesion", "Chia đoạn hoặc câu chủ đề (topic sentence) chưa hợp lý"),
            ("tag-cc-referencing", "CC_REFERENCING", "coherence_cohesion", "Sử dụng đại từ thay thế (referencing) gây khó hiểu"),
            ("tag-cc-progression", "CC_PROGRESSION", "coherence_cohesion", "Mạch phát triển ý giữa các câu bị đứt quãng"),
            ("tag-lr-register", "REGISTER", "lexical_resource", "Dùng từ mang văn phong nói (informal) trong bài viết học thuật"),
            ("tag-gra-syntax", "SYNTAX", "grammatical_range_accuracy", "Cấu trúc câu phức bị lỗi cú pháp"),
        ]
        for tid, code, cat, desc in new_tags:
            conn.execute(
                "INSERT OR IGNORE INTO error_tags (id, code, category, description) VALUES (?, ?, ?, ?)",
                (tid, code, cat, desc),
            )
        conn.commit()
        conn.close()

    print("=" * 72)
    print("[✓] ĐÃ NÂNG CẤP RUBRIC LÊN PHIÊN BẢN: ielts-writing-v2-cambridge-calibrated")
    print("- Đã tách prompt sang: apps/backend/app/prompts/ielts_writing_v2.py")
    print("- Đã cập nhật bộ lọc chống phạt trùng lỗi chéo tiêu chí tại: apps/backend/app/services/writing/evaluator.py")
    print("- Đã bổ sung 8 mã lỗi chuyên biệt cho TR & CC vào SQLite Database.")
    print("=" * 72)


if __name__ == "__main__":
    main()
