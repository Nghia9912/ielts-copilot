from __future__ import annotations

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
    norm_transcript = re.sub(r"\s+", " ", transcript_text.strip()).lower()
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
            norm_q = re.sub(r"\s+", " ", quote.strip()).lower()
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
