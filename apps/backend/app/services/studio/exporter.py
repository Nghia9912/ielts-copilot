from __future__ import annotations
import html
import io
import textwrap
import zipfile
from datetime import datetime, timezone
from typing import Any, Literal
import unicodedata

ExportDocType = Literal[
    "student_handout",
    "teacher_guide",
    "answer_key",
    "teaching_playbook",
    "post_lesson_summary",
]
ExportFormat = Literal["docx", "pdf"]


def build_structured_document_sections(
    plan: dict[str, Any],
    doc_type: ExportDocType,
) -> dict[str, Any]:
    """Build structured document model (title, subtitle, metadata, sections) for any of the 5 export types.
    Strictly enforces separation between student-facing and teacher-only content.
    """
    lesson_title = plan.get("title", "IELTS Lesson")
    skill_label = f"{plan.get('skill', 'writing').upper()} ({plan.get('task_type', 'task2').upper()})"
    student_name = plan.get("student_name") or "General Class"
    duration_str = f"{plan.get('duration_minutes', 60)} minutes"
    band_str = f"Current: {plan.get('student_current_band') or 'N/A'} -> Target: {plan.get('student_target_band') or '7.0'}"
    objectives = plan.get("learning_objectives", [])

    if doc_type == "student_handout":
        handout = plan.get("handout")
        if not handout:
            raise ValueError("Chưa tạo Student Handout cho bài học này.")
        sections: list[dict[str, Any]] = [
            {
                "heading": "Lesson Learning Objectives",
                "paragraphs": [f"• {obj}" for obj in objectives],
            }
        ]
        if handout.get("intro_instructions"):
            sections.append({
                "heading": "Student Instructions",
                "paragraphs": [handout["intro_instructions"]],
            })

        for ex in handout.get("exercises", []):
            ex_paras = [
                f"Stage: {ex.get('progression_stage', 'scaffolded').upper()} | Difficulty: {ex.get('difficulty_level', '')} | Objective: {ex.get('learning_objective', '')}",
                f"Instructions: {ex.get('student_instructions', '')}",
            ]
            for idx, item in enumerate(ex.get("content_items", []), start=1):
                ex_paras.append(f"  {idx}. {item}")
            ex_paras.append(f"Expected Response Format: {ex.get('expected_response_format', '')}")
            lines_count = max(2, min(20, int(ex.get("working_space_lines", 4))))
            for _ in range(lines_count):
                ex_paras.append("____________________________________________________________________________________")
            sections.append({
                "heading": f"Exercise {ex['exercise_order']}: {ex['title']} ({ex['exercise_type']})",
                "paragraphs": ex_paras,
            })

        checklist = handout.get("self_assessment_checklist", [])
        if checklist:
            sections.append({
                "heading": "Student Self-Assessment Checklist",
                "paragraphs": [f"[ ] {item}" for item in checklist],
            })
        if handout.get("exit_ticket_prompt"):
            sections.append({
                "heading": "Exit Ticket",
                "paragraphs": [
                    handout["exit_ticket_prompt"],
                    "____________________________________________________________________________________",
                    "____________________________________________________________________________________",
                ],
            })
        if handout.get("homework_assignment"):
            sections.append({
                "heading": "Homework Assignment",
                "paragraphs": [handout["homework_assignment"]],
            })

        return {
            "doc_type": "student_handout",
            "audience": "STUDENT WORKSHEET (NO ANSWERS INCLUDED)",
            "title": handout.get("title") or f"Student Handout — {lesson_title}",
            "metadata": [
                ("Lesson Title", lesson_title),
                ("IELTS Skill & Task", skill_label),
                ("Student", student_name),
                ("Duration", duration_str),
            ],
            "sections": sections,
        }

    if doc_type == "teacher_guide":
        tg = plan.get("teacher_guide")
        handout = plan.get("handout")
        if not tg or not handout:
            raise ValueError("Chưa tạo Teacher Guide cho bài học này.")
        sections = [
            {
                "heading": "1. Personalization & Pedagogical Context (Teacher Only)",
                "paragraphs": [
                    f"Personalization Applied: {'Yes' if handout.get('personalization_applied') else 'No'}",
                    f"Personalization Summary: {handout.get('personalization_summary') or 'Standard lesson alignment.'}",
                ],
            }
        ]
        for key in tg.get("answer_keys", []):
            paras = [
                f"Correct Answer(s): {'; '.join(key.get('correct_answers', []))}",
                f"Why This Is Correct: {key.get('explanation_why', '')}",
                f"Alternative Acceptable Answers: {'; '.join(key.get('alternative_acceptable_answers', [])) or 'N/A'}",
                f"Common Student Mistakes to Watch For: {'; '.join(key.get('common_student_mistakes', []))}",
                f"Suggested Feedback & Remediation: {key.get('suggested_feedback_remediation', '')}",
            ]
            if key.get("open_ended_marking_criteria"):
                paras.append(f"Open-Ended Marking Criteria: {'; '.join(key['open_ended_marking_criteria'])}")
            if key.get("illustrative_sample_response"):
                paras.append(
                    "[ILLUSTRATIVE LLM EXAMPLE — NOT AN OFFICIAL CAMBRIDGE MODEL ANSWER]: "
                    + key["illustrative_sample_response"]
                )
            sections.append({
                "heading": f"Exercise {key.get('exercise_order')}: {key.get('exercise_title')} — Teacher Guidance",
                "paragraphs": paras,
            })

        eval_check = tg.get("objective_evaluation_checklist", [])
        if eval_check:
            sections.append({
                "heading": "Lesson Objective Evaluation Checklist",
                "paragraphs": [f"[ ] {c}" for c in eval_check],
            })

        return {
            "doc_type": "teacher_guide",
            "audience": "TEACHER-ONLY GUIDE (CONFIDENTIAL — DO NOT DISTRIBUTE TO STUDENT)",
            "title": f"Teacher Guide — {lesson_title}",
            "metadata": [
                ("Lesson Title", lesson_title),
                ("IELTS Skill & Task", skill_label),
                ("Student & Band", f"{student_name} ({band_str})"),
                ("Duration", duration_str),
            ],
            "sections": sections,
        }

    if doc_type == "answer_key":
        tg = plan.get("teacher_guide")
        if not tg:
            raise ValueError("Chưa tạo Answer Key cho bài học này.")
        sections = []
        for key in tg.get("answer_keys", []):
            paras = [
                f"• Correct Answer(s): {' | '.join(key.get('correct_answers', []))}",
                f"• Explanation: {key.get('explanation_why', '')}",
                f"• Acceptable Alternatives: {' | '.join(key.get('alternative_acceptable_answers', [])) or 'See marking rubric'}",
                f"• Marking Criteria: {' | '.join(key.get('open_ended_marking_criteria', [])) or 'Accuracy & appropriateness'}",
            ]
            if key.get("illustrative_sample_response"):
                paras.append(
                    f"• Illustrative Example (Local LLM — Non-Official): {key['illustrative_sample_response']}"
                )
            sections.append({
                "heading": f"Answer Key — Exercise {key.get('exercise_order')}: {key.get('exercise_title')}",
                "paragraphs": paras,
            })
        sections.append({
            "heading": "Assessment Sheet & Objective Sign-Off",
            "paragraphs": [f"[ ] Achieved / [ ] Partial / [ ] Not Yet — {obj}" for obj in objectives],
        })
        return {
            "doc_type": "answer_key",
            "audience": "TEACHER-ONLY ANSWER KEY & ASSESSMENT SHEET",
            "title": f"Answer Key & Assessment Sheet — {lesson_title}",
            "metadata": [
                ("Lesson Title", lesson_title),
                ("IELTS Skill & Task", skill_label),
                ("Student", student_name),
                ("Duration", duration_str),
            ],
            "sections": sections,
        }

    if doc_type == "teaching_playbook":
        pb = plan.get("playbook")
        acts = plan.get("activities", [])
        if not pb or not acts:
            raise ValueError("Chưa tạo Teaching Playbook cho bài học này.")
        dur_val = pb.get("duration_validation", {})
        sections = [
            {
                "heading": "Pedagogical Approach & Time Validation",
                "paragraphs": [
                    f"Approach: {pb.get('pedagogical_approach', '')}",
                    f"Allocated Time: {dur_val.get('total_allocated_minutes', 0)} / {plan.get('duration_minutes', 60)} min "
                    f"(Activities: {dur_val.get('activities_sum_minutes', 0)} min + Transitions: {dur_val.get('transition_buffer_minutes', 5)} min)",
                    *(
                        [f"Time Adjustment Recommendation: {r}" for r in pb.get("time_shortening_recommendations", [])]
                        if pb.get("time_shortening_recommendations")
                        else ["Time Status: Fits cleanly within planned lesson duration."]
                    ),
                ],
            }
        ]
        for a in acts:
            paras = [
                f"Duration: {a.get('duration_minutes')} min | Priority: {a.get('priority_level', 'core').upper()} | Objective: {a.get('learning_objective')}",
                f"Teaching Rationale: {a.get('teaching_rationale', '')}",
                f"Exact Teacher Instructions: {a.get('teacher_instructions', '')}",
                "Suggested Explanation Sequence:",
                *[f"  Step {idx}: {step}" for idx, step in enumerate(a.get("explanation_sequence", []), start=1)],
            ]
            for ex_pair in a.get("examples_counterexamples", []):
                paras.append(
                    f"  • Strong Example: {ex_pair.get('strong_example', '')} | "
                    f"Weak Counterexample: {ex_pair.get('weak_counterexample', '')} "
                    f"(Key Point: {ex_pair.get('comparison_point', '')})"
                )
            paras.append(f"Teacher Questions (CCQs): {'; '.join(a.get('teacher_questions', []))}")
            paras.append(f"Expected Student Responses: {'; '.join(a.get('expected_student_responses', []))}")
            paras.append(f"Common Misconceptions: {'; '.join(a.get('common_misconceptions', []))}")
            paras.append(f"Understanding Checks: {'; '.join(a.get('understanding_checks', []))}")
            paras.append(f"Scaffolding (Struggling Student): {a.get('scaffolding_struggling', '')}")
            paras.append(f"Extension (Fast Learner): {a.get('extension_fast_learners', '')}")
            paras.append(f"Transition to Next Activity: {a.get('transition_next', '')}")
            sections.append({
                "heading": f"Activity {a.get('activity_order')}: {a.get('title')} ({a.get('duration_minutes')} min)",
                "paragraphs": paras,
            })

        return {
            "doc_type": "teaching_playbook",
            "audience": "TEACHER-FACING INSTRUCTIONAL PLAYBOOK",
            "title": f"Complete Teaching Playbook — {lesson_title}",
            "metadata": [
                ("Lesson Title", lesson_title),
                ("IELTS Skill & Task", skill_label),
                ("Student & Band", f"{student_name} ({band_str})"),
                ("Duration", duration_str),
            ],
            "sections": sections,
        }

    if doc_type == "post_lesson_summary":
        reviews = plan.get("reviews", [])
        if not reviews:
            raise ValueError("Chưa có bản Post-Lesson Review nào cho bài học này.")
        rev = reviews[0]
        ai_hyp = rev.get("ai_hypotheses_summary", {})
        obj_map = rev.get("objectives_achieved", {})
        obj_lines = [f"• {k}: {v.upper()}" for k, v in obj_map.items()] or ["• Recorded in teacher notes."]
        sections = [
            {
                "heading": "Part 1: Teacher-Confirmed Lesson Outcomes (Official Record)",
                "paragraphs": [
                    f"Completed Activities: {', '.join(rev.get('completed_activities', [])) or 'All core activities'}",
                    "Objectives Achievement Status:",
                    *obj_lines,
                    f"Observed Student Difficulties: {'; '.join(rev.get('student_difficulties', [])) or 'None noted'}",
                    f"Exercises Too Easy: {', '.join(rev.get('exercises_too_easy', [])) or 'None'}",
                    f"Exercises Too Hard: {', '.join(rev.get('exercises_too_hard', [])) or 'None'}",
                    f"Teacher Confirmed Notes: {rev.get('teacher_confirmed_notes', '')}",
                    f"Homework Assigned: {rev.get('homework_assigned', '')}",
                    f"Recommended Focus for Next Lesson: {rev.get('recommended_next_focus', '')}",
                    f"Student History Updated: {'Confirmed by Teacher' if rev.get('teacher_confirmed_history_update') else 'Pending Teacher Confirmation'}",
                ],
            },
            {
                "heading": "Part 2: AI-Generated Hypotheses & Proposed Next Steps (Advisory Only)",
                "paragraphs": [
                    f"Concise Summary: {ai_hyp.get('concise_lesson_summary', '')}",
                    "Hypothesized Root Causes:",
                    *[f"  • {c}" for c in ai_hyp.get("hypothesized_root_causes", [])],
                    "Proposed Next Steps:",
                    *[f"  • {s}" for s in ai_hyp.get("proposed_next_steps", [])],
                    f"Suggested Homework Refinement: {ai_hyp.get('suggested_homework_refinement', '')}",
                ],
            },
        ]
        return {
            "doc_type": "post_lesson_summary",
            "audience": "POST-LESSON REVIEW & LEARNING RECORD",
            "title": f"Post-Lesson Summary — {lesson_title}",
            "metadata": [
                ("Lesson Title", lesson_title),
                ("IELTS Skill & Task", skill_label),
                ("Student", student_name),
                ("Reviewed At", rev.get("created_at", "")[:19]),
            ],
            "sections": sections,
        }

    raise ValueError(f"Unsupported export doc_type: {doc_type}")


def generate_docx_bytes(doc_model: dict[str, Any]) -> bytes:
    """Generate a standalone, standards-compliant Microsoft Word (.docx) file using pure Python stdlib zipfile + OpenXML.
    Preserves 100% of UTF-8 Vietnamese accented characters, heading hierarchy, metadata table, and page numbers.
    """
    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
</Types>"""

    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

    doc_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>"""

    styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault>
      <w:rPr>
        <w:rFonts w:ascii="Segoe UI" w:hAnsi="Segoe UI" w:cs="Segoe UI"/>
        <w:sz w:val="22"/>
        <w:szCs w:val="22"/>
      </w:rPr>
    </w:rPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/>
    <w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Title">
    <w:name w:val="Title"/>
    <w:pPr><w:spacing w:before="60" w:after="120"/></w:pPr>
    <w:rPr><w:b/><w:color w:val="0F172A"/><w:sz w:val="36"/><w:szCs w:val="36"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/>
    <w:pPr><w:spacing w:before="240" w:after="100"/><w:keepNext/></w:pPr>
    <w:rPr><w:b/><w:color w:val="0369A1"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr>
  </w:style>
</w:styles>"""

    footer_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:p>
    <w:pPr><w:jc w:val="right"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="18"/><w:color w:val="64748B"/></w:rPr><w:t xml:space="preserve">IELTS Copilot Teaching Studio · Page </w:t></w:r>
    <w:fldSimple w:instr="PAGE"/>
    <w:r><w:rPr><w:sz w:val="18"/><w:color w:val="64748B"/></w:rPr><w:t xml:space="preserve"> of </w:t></w:r>
    <w:fldSimple w:instr="NUMPAGES"/>
  </w:p>
</w:ftr>"""

    def _p(text: str, style: str = "Normal", bold: bool = False, color: str | None = None) -> str:
        esc = html.escape(str(text))
        rpr = ""
        if bold or color:
            b_tag = "<w:b/>" if bold else ""
            c_tag = f'<w:color w:val="{color}"/>' if color else ""
            rpr = f"<w:rPr>{b_tag}{c_tag}</w:rPr>"
        return (
            f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
            f'<w:r>{rpr}<w:t xml:space="preserve">{esc}</w:t></w:r></w:p>'
        )

    body_parts: list[str] = [
        _p(doc_model.get("audience", ""), style="Normal", bold=True, color="0284C7"),
        _p(doc_model.get("title", ""), style="Title", bold=True),
    ]

    meta_pairs = doc_model.get("metadata", [])
    if meta_pairs:
        meta_line = "  |  ".join(f"{k}: {v}" for k, v in meta_pairs)
        body_parts.append(_p(meta_line, style="Normal", bold=True, color="475569"))

    for sec in doc_model.get("sections", []):
        body_parts.append(_p(sec.get("heading", ""), style="Heading1", bold=True))
        for para in sec.get("paragraphs", []):
            body_parts.append(_p(para, style="Normal"))

    sect_pr = """
    <w:sectPr>
      <w:footerReference w:type="default" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId2"/>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="708" w:footer="708" w:gutter="0"/>
    </w:sectPr>"""

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(body_parts)}{sect_pr}</w:body></w:document>"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml.encode("utf-8"))
        zf.writestr("_rels/.rels", rels_xml.encode("utf-8"))
        zf.writestr("word/_rels/document.xml.rels", doc_rels_xml.encode("utf-8"))
        zf.writestr("word/styles.xml", styles_xml.encode("utf-8"))
        zf.writestr("word/footer1.xml", footer_xml.encode("utf-8"))
        zf.writestr("word/document.xml", document_xml.encode("utf-8"))
    return buf.getvalue()


def _pdf_safe_text(text: str) -> str:
    """Prepare text for PDF 1.4 Type1 Helvetica stream while preserving readable Vietnamese & ASCII characters."""
    # Map Vietnamese "đ/Đ" explicitly before NFKD normalization so words stay completely readable
    replaced = text.replace("đ", "d").replace("Đ", "D").replace("•", "-").replace("→", "->")
    norm = unicodedata.normalize("NFKD", replaced)
    ascii_clean = "".join(ch for ch in norm if not unicodedata.combining(ch))
    safe = ascii_clean.encode("latin-1", errors="replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def generate_pdf_bytes(doc_model: dict[str, Any]) -> bytes:
    """Generate a valid, multi-page A4 PDF 1.4 document 100% locally in pure Python without any cloud service.
    Includes automatic line wrapping, multi-page pagination, clear heading hierarchy, and 'Page X of Y' footers.
    """
    lines_with_style: list[tuple[str, int, bool]] = []  # (text, font_size, is_bold)
    lines_with_style.append((doc_model.get("audience", ""), 10, True))
    lines_with_style.append((doc_model.get("title", ""), 16, True))
    meta_pairs = doc_model.get("metadata", [])
    if meta_pairs:
        meta_str = " | ".join(f"{k}: {v}" for k, v in meta_pairs)
        for wline in textwrap.wrap(meta_str, width=88) or [meta_str]:
            lines_with_style.append((wline, 9, True))
    lines_with_style.append(("", 10, False))

    for sec in doc_model.get("sections", []):
        lines_with_style.append(("", 8, False))
        heading = sec.get("heading", "")
        for wline in textwrap.wrap(heading, width=74) or [heading]:
            lines_with_style.append((wline, 13, True))
        for para in sec.get("paragraphs", []):
            wrapped = textwrap.wrap(str(para), width=86) or [""]
            for wline in wrapped:
                lines_with_style.append((wline, 10, False))

    # Paginate into A4 pages (height 842pt, top 780pt down to bottom 65pt)
    pages: list[list[tuple[str, int, bool, int]]] = []
    curr_page: list[tuple[str, int, bool, int]] = []
    y = 780
    for txt, sz, is_b in lines_with_style:
        step = sz + 6
        if y - step < 65:
            pages.append(curr_page)
            curr_page = []
            y = 780
        curr_page.append((txt, sz, is_b, y))
        y -= step
    if curr_page or not pages:
        pages.append(curr_page)

    total_pages = len(pages)
    objects: list[bytes] = []

    # Obj 1: Catalog, Obj 2: Pages, Obj 3: Font Regular (/F1), Obj 4: Font Bold (/F2)
    page_obj_ids = [5 + i * 2 for i in range(total_pages)]
    kids_str = " ".join(f"{pid} 0 R" for pid in page_obj_ids)

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids_str}] /Count {total_pages} >>".encode("ascii"))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

    for idx, p_lines in enumerate(pages, start=1):
        page_id = 5 + (idx - 1) * 2
        content_id = page_id + 1
        stream_cmds: list[str] = ["BT"]
        for txt, sz, is_b, y_pos in p_lines:
            if not txt:
                continue
            font_ref = "/F2" if is_b else "/F1"
            safe_txt = _pdf_safe_text(txt)
            stream_cmds.append(f"{font_ref} {sz} Tf 1 0 0 1 50 {y_pos} Tm ({safe_txt}) Tj")
        footer_txt = _pdf_safe_text(f"IELTS Copilot Teaching Studio  -  Page {idx} of {total_pages}")
        stream_cmds.append(f"/F1 9 Tf 1 0 0 1 360 35 Tm ({footer_txt}) Tj")
        stream_cmds.append("ET")
        stream_bytes = "\n".join(stream_cmds).encode("latin-1", errors="replace")

        page_dict = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode("ascii")
        content_dict = (
            f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii")
            + stream_bytes
            + b"\nendstream"
        )
        objects.append(page_dict)
        objects.append(content_dict)

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for obj_num, obj_bytes in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{obj_num} 0 obj\n".encode("ascii"))
        out.write(obj_bytes)
        out.write(b"\nendobj\n")

    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode("ascii"))
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return out.getvalue()


def export_studio_document(
    plan: dict[str, Any],
    doc_type: ExportDocType,
    fmt: ExportFormat = "docx",
) -> tuple[bytes, str, str]:
    """Export one of the 5 Teaching Studio documents in DOCX or PDF format.
    Returns (file_bytes, filename, media_type).
    """
    doc_model = build_structured_document_sections(plan, doc_type)
    safe_slug = "".join(c if c.isalnum() else "_" for c in plan.get("title", "lesson"))[:40].strip("_") or "lesson"
    if fmt == "docx":
        data = generate_docx_bytes(doc_model)
        filename = f"{doc_type}_{safe_slug}.docx"
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return data, filename, media_type
    if fmt == "pdf":
        data = generate_pdf_bytes(doc_model)
        filename = f"{doc_type}_{safe_slug}.pdf"
        media_type = "application/pdf"
        return data, filename, media_type
    raise ValueError(f"Định dạng xuất '{fmt}' không được hỗ trợ (chỉ hỗ trợ 'docx' hoặc 'pdf').")
