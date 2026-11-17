from __future__ import annotations

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
    words = re.findall(r"\b[a-zA-Z0-9]+(?:['-][a-zA-Z0-9]+)*\b", essay_text)
    word_count = len(words)
    min_words = 150 if task_type == "task1" else 250
    paragraphs = [p.strip() for p in essay_text.strip().split("\n") if p.strip()]
    cleaned = re.sub(r"\s+", " ", essay_text.strip())
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()] if cleaned else []
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
    norm_essay = re.sub(r"\s+", " ", essay_text.strip()).lower()
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

            norm_q = re.sub(r"\s+", " ", quote.strip()).lower()
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
