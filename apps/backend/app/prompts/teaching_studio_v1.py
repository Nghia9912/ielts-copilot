from __future__ import annotations
import json
from typing import Any

PROMPT_VERSION_ANALYZER = "studio-analyzer-v1.0"
PROMPT_VERSION_PLAYBOOK = "studio-playbook-v1.0"
PROMPT_VERSION_HANDOUT = "studio-handout-v1.0"
PROMPT_VERSION_TEACHER_GUIDE = "studio-teacher-guide-v1.0"
PROMPT_VERSION_COMPANION = "studio-companion-v1.0"
PROMPT_VERSION_REVIEW = "studio-review-v1.0"

ANALYZER_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "skill": {"type": "string", "enum": ["writing", "speaking", "integrated"]},
        "task_type": {"type": "string"},
        "duration_minutes": {"type": "integer"},
        "student_current_band": {"type": ["number", "null"]},
        "student_target_band": {"type": ["number", "null"]},
        "learning_objectives": {"type": "array", "items": {"type": "string"}},
        "prerequisite_knowledge": {"type": "array", "items": {"type": "string"}},
        "planned_activities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                    "learning_objective": {"type": "string"},
                    "priority_level": {"type": "string", "enum": ["essential", "core", "optional_extension"]},
                    "is_assumed": {"type": "boolean"},
                },
                "required": ["title", "duration_minutes", "learning_objective", "priority_level", "is_assumed"],
            },
        },
        "available_resources": {"type": "array", "items": {"type": "string"}},
        "expected_difficulties": {"type": "array", "items": {"type": "string"}},
        "assessment_criteria": {"type": "array", "items": {"type": "string"}},
        "explicit_vs_assumed": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field_name": {"type": "string"},
                    "status": {"type": "string", "enum": ["explicit", "assumed"]},
                    "rationale": {"type": "string"},
                },
                "required": ["field_name", "status", "rationale"],
            },
        },
    },
    "required": [
        "title",
        "skill",
        "task_type",
        "duration_minutes",
        "learning_objectives",
        "prerequisite_knowledge",
        "planned_activities",
        "available_resources",
        "expected_difficulties",
        "assessment_criteria",
        "explicit_vs_assumed",
    ],
}

PLAYBOOK_ACTIVITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "activity_order": {"type": "integer"},
        "title": {"type": "string"},
        "duration_minutes": {"type": "integer"},
        "learning_objective": {"type": "string"},
        "priority_level": {"type": "string", "enum": ["essential", "core", "optional_extension"]},
        "teaching_rationale": {"type": "string"},
        "teacher_instructions": {"type": "string"},
        "explanation_sequence": {"type": "array", "items": {"type": "string"}},
        "examples_counterexamples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "strong_example": {"type": "string"},
                    "weak_counterexample": {"type": "string"},
                    "comparison_point": {"type": "string"},
                },
                "required": ["strong_example", "weak_counterexample", "comparison_point"],
            },
        },
        "teacher_questions": {"type": "array", "items": {"type": "string"}},
        "expected_student_responses": {"type": "array", "items": {"type": "string"}},
        "common_misconceptions": {"type": "array", "items": {"type": "string"}},
        "understanding_checks": {"type": "array", "items": {"type": "string"}},
        "scaffolding_struggling": {"type": "string"},
        "extension_fast_learners": {"type": "string"},
        "transition_next": {"type": "string"},
    },
    "required": [
        "activity_order",
        "title",
        "duration_minutes",
        "learning_objective",
        "priority_level",
        "teaching_rationale",
        "teacher_instructions",
        "explanation_sequence",
        "examples_counterexamples",
        "teacher_questions",
        "expected_student_responses",
        "common_misconceptions",
        "understanding_checks",
        "scaffolding_struggling",
        "extension_fast_learners",
        "transition_next",
    ],
}

PLAYBOOK_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pedagogical_approach": {"type": "string"},
        "transition_buffer_minutes": {"type": "integer"},
        "activities": {"type": "array", "items": PLAYBOOK_ACTIVITY_SCHEMA},
    },
    "required": ["pedagogical_approach", "transition_buffer_minutes", "activities"],
}

HANDOUT_EXERCISE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "exercise_order": {"type": "integer"},
        "linked_activity_order": {"type": "integer"},
        "exercise_type": {
            "type": "string",
            "enum": [
                "model_analysis",
                "error_correction",
                "sentence_transformation",
                "paraphrasing",
                "vocabulary_collocation",
                "guided_paragraph",
                "independent_writing",
                "speaking_prompt",
                "self_assessment",
                "exit_ticket",
            ],
        },
        "progression_stage": {"type": "string", "enum": ["scaffolded", "guided", "independent"]},
        "title": {"type": "string"},
        "learning_objective": {"type": "string"},
        "difficulty_level": {"type": "string"},
        "student_instructions": {"type": "string"},
        "content_items": {"type": "array", "items": {"type": "string"}},
        "expected_response_format": {"type": "string"},
        "working_space_lines": {"type": "integer"},
    },
    "required": [
        "exercise_order",
        "linked_activity_order",
        "exercise_type",
        "progression_stage",
        "title",
        "learning_objective",
        "difficulty_level",
        "student_instructions",
        "content_items",
        "expected_response_format",
        "working_space_lines",
    ],
}

HANDOUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "intro_instructions": {"type": "string"},
        "exercises": {"type": "array", "items": HANDOUT_EXERCISE_SCHEMA},
        "self_assessment_checklist": {"type": "array", "items": {"type": "string"}},
        "exit_ticket_prompt": {"type": "string"},
        "homework_assignment": {"type": "string"},
    },
    "required": [
        "title",
        "intro_instructions",
        "exercises",
        "self_assessment_checklist",
        "exit_ticket_prompt",
        "homework_assignment",
    ],
}

TEACHER_GUIDE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer_keys": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "exercise_order": {"type": "integer"},
                    "exercise_title": {"type": "string"},
                    "correct_answers": {"type": "array", "items": {"type": "string"}},
                    "explanation_why": {"type": "string"},
                    "alternative_acceptable_answers": {"type": "array", "items": {"type": "string"}},
                    "common_student_mistakes": {"type": "array", "items": {"type": "string"}},
                    "suggested_feedback_remediation": {"type": "string"},
                    "open_ended_marking_criteria": {"type": "array", "items": {"type": "string"}},
                    "illustrative_sample_response": {"type": "string"},
                    "is_illustrative_llm_example": {"type": "boolean"},
                },
                "required": [
                    "exercise_order",
                    "exercise_title",
                    "correct_answers",
                    "explanation_why",
                    "alternative_acceptable_answers",
                    "common_student_mistakes",
                    "suggested_feedback_remediation",
                    "open_ended_marking_criteria",
                    "illustrative_sample_response",
                    "is_illustrative_llm_example",
                ],
            },
        },
        "objective_evaluation_checklist": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer_keys", "objective_evaluation_checklist"],
}

COMPANION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scenario": {"type": "string"},
        "diagnosis_or_rationale": {"type": "string"},
        "teacher_script_or_explanation": {"type": "string"},
        "guided_diagnostic_question": {"type": "string"},
        "adapted_exercise_or_task": {"type": "string"},
        "schedule_adjustment_plan": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "scenario",
        "diagnosis_or_rationale",
        "teacher_script_or_explanation",
        "guided_diagnostic_question",
        "adapted_exercise_or_task",
        "schedule_adjustment_plan",
    ],
}

REVIEW_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "concise_lesson_summary": {"type": "string"},
        "hypothesized_root_causes": {"type": "array", "items": {"type": "string"}},
        "proposed_next_steps": {"type": "array", "items": {"type": "string"}},
        "suggested_homework_refinement": {"type": "string"},
    },
    "required": [
        "concise_lesson_summary",
        "hypothesized_root_causes",
        "proposed_next_steps",
        "suggested_homework_refinement",
    ],
}


def build_lesson_analyzer_prompts(
    req_data: dict[str, Any],
    student_context: dict[str, Any] | None,
    library_sources: list[dict[str, Any]],
) -> tuple[str, str]:
    system_prompt = """You are a Senior Cambridge IELTS Instructional Designer and Lesson Plan Analyzer.
Your task is to analyze and normalize an IELTS teacher's lesson input into a structured lesson plan JSON.

CRITICAL RULES:
1. DISTINGUISH EXPLICIT INFORMATION FROM ASSUMPTIONS:
   - Any field, objective,prerequisite, or activity directly provided by the teacher must be marked 'status': 'explicit' in 'explicit_vs_assumed', and 'is_assumed': false in 'planned_activities'.
   - Whenever essential information (such as specific sub-activities, prerequisite skills, or assessment criteria) is missing from the raw input, propose reasonable pedagogical defaults and explicitly mark them 'status': 'assumed' in 'explicit_vs_assumed' (with a clear 'rationale') and 'is_assumed': true on assumed activities so the teacher can review and edit them.
2. NEVER FABRICATE QUOTES OR SOURCE REFERENCES:
   - When referencing attached teacher source materials, preserve exact source filenames and section/page markers.
3. TIME ALLOCATION:
   - Ensure the sum of 'planned_activities' durations fits sensibly within 'duration_minutes' (leaving ~5 minutes for transitions/feedback).
   - Tag each activity's 'priority_level' as 'essential', 'core', or 'optional_extension'."""

    lib_text = ""
    for src in library_sources:
        lib_text += f"\n[TEACHER SOURCE MATERIAL — FILE: {src['source_filename']}]\n{src.get('raw_text', '')[:2500]}\n"

    stu_text = "General Class / No specific student selected."
    if student_context:
        stu = student_context.get("student", {})
        errs = student_context.get("recurring_errors", [])
        err_str = ", ".join(f"{e['code']} ({e['error_count']}x)" for e in errs[:5]) or "None recorded yet"
        stu_text = (
            f"Student Name: {stu.get('name')} | Current Band: {stu.get('current_overall')} | "
            f"Target Band: {stu.get('target_overall')} (Writing: {stu.get('target_writing')}, Speaking: {stu.get('target_speaking')})\n"
            f"Known Recurring Errors from SQLite History: {err_str}\n"
            f"Teacher Notes on Student: {stu.get('notes', '')}"
        )

    user_prompt = (
        f"=== TEACHER INPUT ===\n"
        f"Provided Title: {req_data.get('title') or '(Not explicitly provided)'}\n"
        f"Skill: {req_data.get('skill')} | Task Type: {req_data.get('task_type')}\n"
        f"Target Duration: {req_data.get('duration_minutes')} minutes\n"
        f"Provided Objectives: {json.dumps(req_data.get('objectives', []), ensure_ascii=False)}\n"
        f"Teacher Notes: {req_data.get('teacher_notes') or '(None)'}\n\n"
        f"=== RAW LESSON PLAN TEXT ===\n{req_data.get('raw_lesson_plan') or '(No raw text pasted — derive structured activities from objectives & notes and mark as assumed)'}\n\n"
        f"=== STUDENT PROFILE CONTEXT ===\n{stu_text}\n"
        f"{lib_text}"
    )
    return system_prompt, user_prompt


def build_playbook_prompts(
    lesson_plan: dict[str, Any],
    activities: list[dict[str, Any]],
    student_context: dict[str, Any] | None,
    library_sources: list[dict[str, Any]],
) -> tuple[str, str]:
    system_prompt = """You are a Master IELTS Teacher Trainer generating an actionable Teaching Playbook.
CRITICAL PEDAGOGICAL & ACTIONABILITY RULES:
1. NO VAGUE ADVICE: Never write generic instructions like 'explain the topic clearly' or 'give students practice'. Write exact teacher scripts, step-by-step explanation sequences, concrete strong vs. weak IELTS examples, exact concept-check questions (CCQs), expected student answers, and realistic misconceptions.
2. FLEXIBLE PEDAGOGY: Select techniques suited to the specific IELTS skill, task type, and band level:
   - Activate prior knowledge briefly.
   - Model the target IELTS skill using strong vs. weak counterexamples before independent practice.
   - Use guided practice with gradually reduced scaffolding.
   - Check comprehension through actual student responses (not 'Do you understand?').
   - Conclude with an independent task testing the lesson objectives.
3. TIME MANAGEMENT: Match the planned activities and keep total activity minutes within the lesson duration (allowing ~5 minutes for transitions/feedback)."""

    stu_summary = "No specific student selected."
    if student_context and lesson_plan.get("personalization_enabled", 1):
        stu = student_context.get("student", {})
        errs = [f"{e['code']} ({e['description']})" for e in student_context.get("recurring_errors", [])[:4]]
        stu_summary = f"Student: {stu.get('name')} (Current: {stu.get('current_overall')}, Target: {stu.get('target_overall')}). Known weaknesses: {', '.join(errs) or 'None recorded'}."

    lib_text = ""
    for src in library_sources:
        lib_text += f"\n[SOURCE: {src['source_filename']}]\n{src.get('raw_text', '')[:1800]}\n"

    user_prompt = (
        f"=== REVIEWED LESSON PLAN ===\n"
        f"Title: {lesson_plan['title']}\n"
        f"Skill: {lesson_plan['skill']} | Task Type: {lesson_plan['task_type']}\n"
        f"Total Lesson Duration: {lesson_plan['duration_minutes']} minutes\n"
        f"Student Band: {lesson_plan.get('student_current_band')} -> Target: {lesson_plan.get('student_target_band')}\n"
        f"Learning Objectives: {lesson_plan['objectives_json']}\n"
        f"Expected Difficulties: {lesson_plan['expected_difficulties_json']}\n"
        f"Assessment Criteria: {lesson_plan['assessment_criteria_json']}\n"
        f"Planned Activities to Expand: {json.dumps(activities, ensure_ascii=False)}\n"
        f"Student Context: {stu_summary}\n"
        f"{lib_text}"
    )
    return system_prompt, user_prompt


def build_single_activity_regen_prompts(
    lesson_plan: dict[str, Any],
    activity: dict[str, Any],
    teacher_instruction: str,
) -> tuple[str, str]:
    system_prompt = (
        "You are a Master IELTS Teacher Trainer. Regenerate ONLY the specified Lesson Activity in the Teaching Playbook "
        "according to the teacher's modification request, keeping its order and aligning with the lesson objectives."
    )
    user_prompt = (
        f"Lesson Title: {lesson_plan['title']} ({lesson_plan['skill']} - {lesson_plan['task_type']})\n"
        f"Objectives: {lesson_plan['objectives_json']}\n"
        f"Current Activity (#{activity['activity_order']}): {json.dumps(activity, ensure_ascii=False)}\n"
        f"Teacher Regeneration Instruction: {teacher_instruction or 'Make instructions and examples more concrete and actionable.'}"
    )
    return system_prompt, user_prompt


def build_handout_prompts(
    lesson_plan: dict[str, Any],
    activities: list[dict[str, Any]],
    personalization_info: dict[str, Any],
) -> tuple[str, str]:
    system_prompt = """You are an IELTS Curriculum Developer creating a Student-Facing Handout (Worksheet).
CRITICAL RULES FOR STUDENT HANDOUTS:
1. ZERO ANSWER LEAKAGE (STRICT SEPARATION):
   - NEVER include answers, answer keys, '[Answer: ...]', teacher notes, or examiner marking keys inside the Student Handout!
   - 'student_instructions' and 'content_items' are given directly to the student to complete.
2. GENUINE LEARNING RESOURCE & PROGRESSION:
   - Progress logically from 'scaffolded' practice (e.g. model_analysis, error_correction, vocabulary_collocation) to 'guided' practice (sentence_transformation, paraphrasing, guided_paragraph) to 'independent' application (independent_writing or speaking_prompt).
   - Every exercise MUST map to a lesson learning objective and a playbook activity ('linked_activity_order').
3. PERSONALIZATION WITHOUT FABRICATION:
   - If personalization data is provided, target the student's actual recurring error codes and band gap while preserving the core lesson objectives."""

    user_prompt = (
        f"=== LESSON PLAN & PLAYBOOK ===\n"
        f"Title: {lesson_plan['title']} | Skill: {lesson_plan['skill']} ({lesson_plan['task_type']})\n"
        f"Duration: {lesson_plan['duration_minutes']} min | Band: {lesson_plan.get('student_current_band')} -> {lesson_plan.get('student_target_band')}\n"
        f"Learning Objectives: {lesson_plan['objectives_json']}\n"
        f"Playbook Activities: {json.dumps([{'order': a['activity_order'], 'title': a['title'], 'objective': a['learning_objective']} for a in activities], ensure_ascii=False)}\n"
        f"Personalization Context: {json.dumps(personalization_info, ensure_ascii=False)}\n"
    )
    return system_prompt, user_prompt


def build_single_exercise_regen_prompts(
    lesson_plan: dict[str, Any],
    exercise: dict[str, Any],
    teacher_instruction: str,
    difficulty_adjustment: str,
) -> tuple[str, str]:
    system_prompt = (
        "You are an IELTS Curriculum Developer. Regenerate ONLY this single student-facing exercise. "
        "CRITICAL: Do NOT include any answers, solutions, or teacher notes in the student exercise fields."
    )
    user_prompt = (
        f"Lesson: {lesson_plan['title']} ({lesson_plan['skill']} {lesson_plan['task_type']})\n"
        f"Current Exercise (#{exercise['exercise_order']}): {json.dumps(exercise, ensure_ascii=False)}\n"
        f"Difficulty Adjustment: {difficulty_adjustment}\n"
        f"Teacher Instruction: {teacher_instruction or 'Improve exercise quality and alignment with objective.'}"
    )
    return system_prompt, user_prompt


def build_teacher_guide_prompts(
    lesson_plan: dict[str, Any],
    handout: dict[str, Any],
    exercises: list[dict[str, Any]],
) -> tuple[str, str]:
    system_prompt = """You are a Senior Cambridge IELTS Examiner creating the Teacher Guide & Answer Key for a Student Handout.
CRITICAL RULES:
1. COMPLETE COVERAGE: Provide an answer key entry ('answer_keys') for EVERY exercise in the Student Handout (matching 'exercise_order').
2. MULTIPLE ACCEPTABLE ANSWERS: For open-ended, paraphrasing, sentence transformation, writing, or speaking tasks, provide 'alternative_acceptable_answers' and 'open_ended_marking_criteria'—never imply there is only one valid phrasing for open-ended IELTS tasks.
3. ILLUSTRATIVE MODEL LABELING: Any sample paragraph/essay/speaking response generated by you MUST set 'is_illustrative_llm_example': true and be framed as an illustrative example rather than an official Cambridge model answer."""

    user_prompt = (
        f"=== LESSON & STUDENT HANDOUT ===\n"
        f"Lesson Title: {lesson_plan['title']} ({lesson_plan['skill']} - {lesson_plan['task_type']})\n"
        f"Objectives: {lesson_plan['objectives_json']}\n"
        f"Handout Title: {handout['title']}\n"
        f"Student Exercises Requiring Answer Keys & Marking Guidance:\n"
        f"{json.dumps(exercises, ensure_ascii=False)}"
    )
    return system_prompt, user_prompt


def build_companion_action_prompts(
    lesson_plan: dict[str, Any],
    current_activity: dict[str, Any] | None,
    all_activities: list[dict[str, Any]],
    req_data: dict[str, Any],
) -> tuple[str, str]:
    system_prompt = """You are a Real-Time IELTS Teaching Companion assisting a teacher during a live online lesson.
Respond to the teacher's selected classroom scenario using ONLY the current lesson context:
- 'student_stuck': Provide an alternative simpler explanation, a simpler concrete example, 1 guided question, and a short 2-minute diagnostic check.
- 'understands_quickly': Increase task complexity, reduce scaffolding, and provide a transfer task using a fresh IELTS prompt on the same skill.
- 'answers_incorrectly': Diagnose the likely misconception, suggest a Socratic diagnostic question, and give corrective feedback that guides the student without immediately giving away the full answer.
- 'behind_schedule': Recalculate remaining time across uncompleted activities, identify optional/extension parts to shorten, and preserve the essential learning objective + final understanding check.
- 'alternative_explanation' / 'adjust_exercise_difficulty' / 'followup_questions': Provide targeted, ready-to-read teacher scripts and items."""

    user_prompt = (
        f"Scenario: {req_data['scenario']}\n"
        f"Lesson: {lesson_plan['title']} ({lesson_plan['skill']} {lesson_plan['task_type']})\n"
        f"Objectives: {lesson_plan['objectives_json']}\n"
        f"Remaining Time: {req_data.get('remaining_minutes') or lesson_plan['duration_minutes']} minutes\n"
        f"Current Activity: {json.dumps(current_activity or {}, ensure_ascii=False)}\n"
        f"All Activities: {json.dumps([{'order': a['activity_order'], 'title': a['title'], 'duration': a['duration_minutes'], 'priority': a.get('priority_level'), 'status': a.get('status')} for a in all_activities], ensure_ascii=False)}\n"
        f"Teacher Observation / Context: {req_data.get('student_response_or_context', '')}"
    )
    return system_prompt, user_prompt


def build_post_lesson_review_prompts(
    lesson_plan: dict[str, Any],
    review_input: dict[str, Any],
) -> tuple[str, str]:
    system_prompt = """You are an IELTS Instructional Specialist generating post-lesson hypotheses and next-step recommendations.
IMPORTANT: Your output will be stored as 'AI-Generated Hypotheses' strictly separated from the teacher's confirmed observations.
Keep your summary concise, practical, and directly tied to the recorded lesson outcomes."""

    user_prompt = (
        f"Lesson: {lesson_plan['title']} ({lesson_plan['skill']} - {lesson_plan['task_type']})\n"
        f"Objectives: {lesson_plan['objectives_json']}\n"
        f"Completed Activities: {json.dumps(review_input.get('completed_activities', []), ensure_ascii=False)}\n"
        f"Objectives Status: {json.dumps(review_input.get('objectives_achieved', {}), ensure_ascii=False)}\n"
        f"Student Difficulties Observed by Teacher: {json.dumps(review_input.get('student_difficulties', []), ensure_ascii=False)}\n"
        f"Exercises Too Easy: {json.dumps(review_input.get('exercises_too_easy', []), ensure_ascii=False)}\n"
        f"Exercises Too Hard: {json.dumps(review_input.get('exercises_too_hard', []), ensure_ascii=False)}\n"
        f"Teacher Confirmed Notes: {review_input.get('teacher_confirmed_notes', '')}\n"
        f"Homework Assigned: {review_input.get('homework_assigned', '')}\n"
        f"Recommended Next Focus: {review_input.get('recommended_next_focus', '')}"
    )
    return system_prompt, user_prompt
