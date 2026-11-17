from __future__ import annotations
import io
import json
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db.database import db_session

ALLOWED_MATERIAL_EXTENSIONS = {".txt", ".md", ".docx", ".pdf"}
MAX_MATERIAL_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_txt_or_markdown(content_bytes: bytes, filename: str) -> tuple[str, list[dict[str, str]]]:
    text = content_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n").strip()
    lines = text.split("\n")
    sections: list[dict[str, str]] = []
    current_title = "Section 1 (Opening)"
    current_buf: list[str] = []
    sec_idx = 1

    for line in lines:
        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line.strip())
        if heading_match:
            if current_buf:
                sections.append({
                    "section_ref": f"{filename} :: {current_title}",
                    "content": "\n".join(current_buf).strip(),
                })
                current_buf = []
            sec_idx = len(sections) + 1
            current_title = f"Section {sec_idx}: {heading_match.group(2).strip()}"
        else:
            current_buf.append(line)

    if current_buf or not sections:
        sections.append({
            "section_ref": f"{filename} :: {current_title}",
            "content": "\n".join(current_buf).strip() or text,
        })
    return text, sections


def parse_docx_bytes(content_bytes: bytes, filename: str) -> tuple[str, list[dict[str, str]]]:
    """Extract text and section headings from .docx using stdlib zipfile + XML (with python-docx fallback if needed)."""
    sections: list[dict[str, str]] = []
    full_paragraphs: list[str] = []
    current_heading = "Document Body"
    current_buf: list[str] = []
    sec_num = 1

    try:
        with zipfile.ZipFile(io.BytesIO(content_bytes)) as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        for p in root.findall(".//w:p", ns):
            texts = [t.text for t in p.findall(".//w:t", ns) if t.text]
            para_text = "".join(texts).strip()
            if not para_text:
                continue
            full_paragraphs.append(para_text)
            style_el = p.find(".//w:pStyle", ns)
            style_val = style_el.attrib.get(f"{{{ns['w']}}}val", "") if style_el is not None else ""
            if "Heading" in style_val or "Title" in style_val:
                if current_buf:
                    sections.append({
                        "section_ref": f"{filename} :: {current_heading}",
                        "content": "\n".join(current_buf),
                    })
                    current_buf = []
                sec_num += 1
                current_heading = f"Section {sec_num} ({para_text[:60]})"
            else:
                current_buf.append(para_text)
    except Exception as exc:
        raise ValueError(f"Không thể đọc file DOCX '{filename}': {exc}") from exc

    if current_buf or not sections:
        sections.append({
            "section_ref": f"{filename} :: {current_heading}",
            "content": "\n".join(current_buf),
        })
    return "\n\n".join(full_paragraphs), sections


def parse_pdf_bytes(content_bytes: bytes, filename: str) -> tuple[str, list[dict[str, str]]]:
    """Extract page-by-page text from PDF locally using pypdf/pdfplumber or stdlib stream fallback."""
    sections: list[dict[str, str]] = []
    all_pages: list[str] = []

    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content_bytes))
        for idx, page in enumerate(reader.pages, start=1):
            txt = (page.extract_text() or "").strip()
            if txt:
                all_pages.append(txt)
                sections.append({
                    "section_ref": f"{filename} :: Page {idx}",
                    "content": txt,
                })
    except ImportError:
        # Pure-Python fallback for extracting literal text strings (...) from uncompressed PDF streams
        raw_latin = content_bytes.decode("latin-1", errors="ignore")
        chunks = re.findall(r"\(([^()]{3,})\)", raw_latin)
        cleaned = " ".join(c for c in chunks if re.search(r"[A-Za-z0-9]{2,}", c)).strip()
        if cleaned:
            all_pages.append(cleaned)
            sections.append({"section_ref": f"{filename} :: Page 1", "content": cleaned})

    full_text = "\n\n".join(all_pages).strip()
    if not sections:
        sections.append({"section_ref": f"{filename} :: Page 1", "content": full_text})
    return full_text, sections


class LocalMaterialLibrary:
    """Quản lý thư viện tài liệu giảng dạy cục bộ (TXT, MD, DOCX, PDF) có lưu vết nguồn."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path
        from app.db.studio_migrations import migrate_teaching_studio_db
        migrate_teaching_studio_db(db_path)

    def ingest_document(
        self,
        filename: str,
        content_bytes: bytes,
        title: str = "",
        skill: str = "",
    ) -> dict[str, Any]:
        safe_name = Path(filename or "lesson_material.txt").name
        ext = Path(safe_name).suffix.lower()
        if ext not in ALLOWED_MATERIAL_EXTENSIONS:
            raise ValueError(
                f"Định dạng '{ext}' không được hỗ trợ. Chỉ hỗ trợ: {', '.join(sorted(ALLOWED_MATERIAL_EXTENSIONS))}"
            )
        if len(content_bytes) > MAX_MATERIAL_SIZE_BYTES:
            raise ValueError("Kích thước tài liệu vượt quá giới hạn 15MB.")

        if ext in {".txt", ".md"}:
            raw_text, sections = parse_txt_or_markdown(content_bytes, safe_name)
        elif ext == ".docx":
            raw_text, sections = parse_docx_bytes(content_bytes, safe_name)
        else:
            raw_text, sections = parse_pdf_bytes(content_bytes, safe_name)

        mat_id = str(uuid.uuid4())
        ts = _now_iso()
        final_title = title.strip() or Path(safe_name).stem

        with db_session(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO material_library_sources (
                    id, title, source_filename, file_format, skill, sections_json, raw_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mat_id,
                    final_title,
                    safe_name,
                    ext.lstrip("."),
                    skill,
                    json.dumps(sections, ensure_ascii=False),
                    raw_text,
                    ts,
                ),
            )
            row = conn.execute("SELECT * FROM material_library_sources WHERE id = ?", (mat_id,)).fetchone()
            item = dict(row)
            item["sections"] = json.loads(item["sections_json"])
            return item

    def list_materials(self, skill: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT id, title, source_filename, file_format, skill, sections_json, created_at FROM material_library_sources WHERE 1=1"
        params: list[Any] = []
        if skill:
            query += " AND skill = ?"
            params.append(skill)
        query += " ORDER BY created_at DESC"
        with db_session(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["sections"] = json.loads(d.get("sections_json") or "[]")
                out.append(d)
            return out

    def get_materials_by_ids(self, material_ids: list[str]) -> list[dict[str, Any]]:
        if not material_ids:
            return []
        placeholders = ",".join("?" for _ in material_ids)
        with db_session(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM material_library_sources WHERE id IN ({placeholders})",
                material_ids,
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["sections"] = json.loads(d.get("sections_json") or "[]")
                out.append(d)
            return out

    def delete_material(self, material_id: str) -> bool:
        with db_session(self.db_path) as conn:
            cur = conn.execute("DELETE FROM material_library_sources WHERE id = ?", (material_id,))
            return cur.rowcount > 0
