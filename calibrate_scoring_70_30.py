from pathlib import Path
import re

root = Path.cwd()

# 1. Cập nhật Prompt chấm Writing theo tỷ lệ 70% Khắt khe thực chiến / 30% Nương tay hợp lý
PROMPT_70_30_PY = """from typing import Any

RUBRIC_VERSION = "ielts-writing-v2.2-balanced-70-30"

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
            "   - 'task_response' (Task Achievement for Task 1) ONLY evaluates:\\n"
            "     * Does the report include a clear Overview paragraph summarizing main trends/stages? (If missing/vague, use TA_NO_OVERVIEW and cap at 5.5).\\n"
            "     * Are the figures/comparisons accurate compared to the provided CHART REFERENCE DATA? (If inaccurate, use TA_INACCURATE_DATA).\\n"
            "     * Are key features adequately highlighted and compared rather than mechanically listing numbers? (Use TA_KEY_FEATURE_MISSING)."
        )
    else:
        tr_instructions = (
            "   - 'task_response' (Task Response for Task 2) ONLY evaluates:\\n"
            "     * Did the writer address all parts of the prompt with a clear position throughout?\\n"
            "     * Are main ideas extended with specific explanations and examples? (If ideas are brief, generalized, or repetitive, use TR_UNDERDEVELOPED and score 5.5–6.0).\\n"
            "     * Allowed error_code: TR_UNDERDEVELOPED, TR_UNBALANCED, TR_OFF_TOPIC, TR_UNCLEAR_POSITION."
        )

    system_prompt = f\"\"\"You are a certified Senior Cambridge IELTS Writing Examiner evaluating an {task_label} script.
Your goal is to assign realistic, balanced band scores (0.0 to 9.0, in 0.5 increments) following a 70% Strict Official Examiner / 30% Constructive Leniency calibration.

=== 1. THE 30% CONSTRUCTIVE LENIENCY RULES (FAIRNESS) ===
- NO CROSS-CRITERION DOUBLE PENALIZATION:
  * NEVER penalize 'task_response' or 'coherence_cohesion' for grammar, article, preposition, punctuation, or vocabulary slips.
{tr_instructions}
  * 'coherence_cohesion' ONLY evaluates paragraphing, logical progression, topic sentences, and cohesive devices (CC_COHESION, CC_PARAGRAPHING, CC_REFERENCING, CC_PROGRESSION).
  * 'lexical_resource' ONLY evaluates vocabulary range, collocations, word choice, register, and spelling (COLLOCATION, WORD_CHOICE, SPELLING, REGISTER).
  * 'grammatical_range_accuracy' ONLY evaluates variety of complex structures, tenses, articles, prepositions, and punctuation (ARTICLE, PREPOSITION, SVA, TENSE, PUNCTUATION, SYNTAX).
- OCCASIONAL SLIP TOLERANCE:
  * Do not drop a criterion from 7.0 to 5.5 over 1–2 isolated, non-systematic slips if the rest of the script demonstrates strong control and majority error-free sentences.

=== 2. THE 70% STRICT EXAMINER ANCHORS (NO SCORE INFLATION) ===
Do NOT inflate mediocre essays to Band 6.5 or 7.0. Apply these strict band ceilings:
- BAND 5.0 – 5.5 CEILING:
  * Award 5.0–5.5 if main ideas are asserted without sufficient explanation/examples, if cohesive devices are mechanical/overused, if vocabulary is basic/repetitive, OR if there are 4+ noticeable grammar/article/preposition errors that cause strain.
- BAND 6.0 ANCHOR:
  * Award 6.0 when the essay addresses the task relevantly and uses a mix of simple and complex sentence forms, BUT some conclusions remain underdeveloped/generalized OR there are 2–3 recurring errors in grammar/collocation per paragraph (even if meaning is still clear).
- BAND 6.5 ANCHOR:
  * Award 6.5 ONLY when arguments are well-organized and supported, complex structures are attempted regularly, and errors are occasional rather than systematic.
- BAND 7.0+ GATEKEEPER (STRICT):
  * Award 7.0 ONLY when ALL parts of the prompt are fully developed with clear progression, natural academic collocations, and a high proportion of error-free complex sentences (at most 1–2 minor slips across the essay).

=== 3. VERBATIM QUOTES & CONCISE EVIDENCE ===
- Include 1 to 2 key evidence items per criterion.
- Every 'quote' MUST be copied 100% verbatim from the Student Essay.
\"\"\"

    user_prompt = (
        f"=== TASK TYPE ===\\n{task_label}\\n\\n"
        f"=== PREPROCESSING METRICS ===\\n"
        f"- Word count: {meta['word_count']} words (Minimum required: {meta['min_words_required']})\\n"
        f"- Underlength penalty applicable: {meta['is_underlength']}\\n"
        f"- Paragraph count: {meta['paragraph_count']} | Sentence count: {meta['sentence_count']}\\n\\n"
        f"=== PROMPT & CHART REFERENCE DATA ===\\n{prompt_text.strip()}\\n\\n"
        f"=== STUDENT SUBMISSION ===\\n{essay_text.strip()}\\n"
    )
    return system_prompt, user_prompt
"""

prompt_path = root / "apps" / "backend" / "app" / "prompts" / "ielts_writing_v2.py"
prompt_path.write_text(PROMPT_70_30_PY, encoding="utf-8")

# 2. Bổ sung khóa trần điểm bài viết ngắn (Underlength Ceiling) trong evaluator.py
eval_path = root / "apps" / "backend" / "app" / "services" / "writing" / "evaluator.py"
if eval_path.exists():
    etxt = eval_path.read_text(encoding="utf-8")
    underlength_guard = """
    # Kiem soat tran diem Task Response khi bai viet thieu tu (Underlength Penalty)
    wc = int(meta.get("word_count", 0))
    min_w = int(meta.get("min_words_required", 250))
    if wc < min_w and "task_response" in criteria:
        tr_band = float(criteria["task_response"].get("estimated_band", 6.0))
        ratio = wc / max(1, min_w)
        if ratio < 0.65:
            tr_band = min(tr_band, 4.5)
        elif ratio < 0.85:
            tr_band = min(tr_band, 5.5)
        else:
            tr_band = min(tr_band, 6.0)
        criteria["task_response"]["estimated_band"] = tr_band
"""
    if "Underlength Penalty" not in etxt and "scores = [" in etxt:
        etxt = etxt.replace("    scores = [", underlength_guard + "\n    scores = [", 1)
        eval_path.write_text(etxt, encoding="utf-8")

print("[OK] Đã cập nhật thang chấm Writing mới (v2.2-balanced-70-30): 70% Khắt khe chuẩn Cambridge + 30% Nương tay hợp lý!")
