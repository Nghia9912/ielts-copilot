from __future__ import annotations

from typing import Any

SPEAKING_RUBRIC_VERSION = "ielts-speaking-v1-cambridge-calibrated"

ALLOWED_SPEAKING_ERROR_CODES: dict[str, set[str]] = {
    "fluency_coherence": {"FC_HESITATION", "FC_COHESION", "FC_UNDERDEVELOPED", "FC_REPETITION"},
    "lexical_resource": {"COLLOCATION", "WORD_CHOICE", "SPEAKING_IDIOM", "REGISTER"},
    "grammatical_range_accuracy": {"ARTICLE", "PREPOSITION", "SVA", "TENSE", "SYNTAX"},
    "pronunciation": {"PRON_CHECK_REQUIRED"},
}


def build_calibrated_speaking_prompts(
    prompt_text: str,
    transcript_text: str,
    task_type: str,
    audio_metrics: dict[str, Any],
) -> tuple[str, str]:
    part_label = {
        "part1": "IELTS Speaking Part 1 (Introduction & Interview)",
        "part2": "IELTS Speaking Part 2 (Individual Long Turn / Cue Card)",
        "part3": "IELTS Speaking Part 3 (Two-Way Discussion)",
    }.get(task_type, "IELTS Speaking")

    system_prompt = f"""You are a certified Senior Cambridge IELTS Speaking Examiner evaluating a transcript and acoustic fluency metrics for {part_label}.

=== CRITICAL SPEAKING CALIBRATION RULES ===
1. STRICT CRITERION ISOLATION (NO DOUBLE PENALIZATION):
   - 'fluency_coherence': Evaluate speech flow, willingness to speak at length, topic development, discourse markers, and hesitation based on BOTH the transcript and the provided Acoustic Metrics (WPM & long pauses). Allowed error_code: FC_HESITATION, FC_COHESION, FC_UNDERDEVELOPED, FC_REPETITION. NEVER penalize grammar or vocabulary here!
   - 'lexical_resource': Evaluate spoken vocabulary range, idiomatic expressions, collocations, and ability to paraphrase. Allowed error_code: COLLOCATION, WORD_CHOICE, SPEAKING_IDIOM, REGISTER.
   - 'grammatical_range_accuracy': Evaluate range of spoken sentence structures and grammatical accuracy. Remember that spoken English naturally has minor slips; Band 7.0 allows a few grammatical errors if frequent error-free sentences are present. Allowed error_code: ARTICLE, PREPOSITION, SVA, TENSE, SYNTAX.
   - 'pronunciation': IMPORTANT ARCHITECTURAL LIMITATION — A text transcript alone CANNOT fully measure phoneme accuracy, word stress, or intonation. Provide a tentative baseline band (usually near the average of Fluency and Lexical, adjusted by Whisper clarity score) and include 1 reminder item with error_code 'PRON_CHECK_REQUIRED' advising the teacher to verify stress and intonation via the audio player.

2. OFFICIAL CAMBRIDGE SPEAKING BAND ANCHORS:
   - BAND 7.0: Speaks at length without noticeable effort or loss of coherence (typically 115–160 WPM with few long pauses); uses discourse markers and idiomatic/less common vocabulary flexibly despite some inappropriate choices; uses a range of complex structures with frequent error-free sentences.
   - BAND 6.0: Willing to speak at length though may lose coherence at times due to occasional repetition, self-correction, or hesitation; has wide enough vocabulary to discuss topics at length; uses a mix of simple and complex structures with some mistakes that rarely cause comprehension problems.
   - BAND 5.0: Maintains flow only with noticeable repetition, self-correction, or slow speech (<95 WPM); uses limited flexibility in vocabulary and complex grammar.

3. VERBATIM QUOTES:
   - Include at most 2 key evidence items per criterion.
   - Every 'quote' MUST be copied 100% verbatim from the Student Transcript.
"""

    user_prompt = (
        f"=== SPEAKING PART ===\n{part_label}\n\n"
        f"=== ACOUSTIC & FLUENCY METRICS (MEASURED FROM AUDIO) ===\n"
        f"- Total Duration: {audio_metrics.get('duration_seconds', 0)}s | Active Speaking Time: {audio_metrics.get('speaking_time_seconds', 0)}s\n"
        f"- Word Count: {audio_metrics.get('word_count', 0)} words | Speech Rate: {audio_metrics.get('words_per_minute', 0)} WPM ({audio_metrics.get('pace_assessment', 'N/A')})\n"
        f"- Long Pauses (>=1.2s): {audio_metrics.get('long_pause_count', 0)} | Total Pause Time: {audio_metrics.get('total_pause_seconds', 0)}s\n"
        f"- Whisper ASR Acoustic Clarity Proxy: {audio_metrics.get('whisper_clarity_percent', 85)}%\n\n"
        f"=== QUESTION / CUE CARD ===\n{prompt_text.strip()}\n\n"
        f"=== STUDENT TRANSCRIPT (VERIFIED) ===\n{transcript_text.strip()}\n"
    )
    return system_prompt, user_prompt
