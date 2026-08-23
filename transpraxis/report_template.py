"""Canonical DOCX report-template contracts and template-aware rendering.

The parser is deliberately deterministic.  A template may be semantically
ambiguous, but its heading hierarchy, styles, sections, and fixed text are
still preserved instead of being re-invented by a model.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from typing import Any, Dict, List, Mapping, Optional

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph


SCHEMA_VERSION = "report-template-contract-v1"
RENDERER_VERSION = "report-template-renderer-v1"


class TemplateParseError(ValueError):
    """Raised when an uploaded DOCX cannot be converted to a contract."""


_ROLE_RULES = (
    ("references", ("参考文献", "references", "bibliography")),
    ("acknowledgements", ("致谢", "acknowledg")),
    ("appendix", ("附录", "appendix", "annex")),
    ("abstract", ("摘要", "abstract")),
    ("table_of_contents", ("目录", "contents", "table of contents", "toc")),
    ("introduction", ("引言", "绪论", "introduction", "background")),
    ("project_overview", ("项目描述", "项目概况", "研究方法", "project overview",
                           "project description", "methodology", "research method")),
    ("theoretical_framework", ("理论框架", "文献综述", "theoretical framework",
                                "literature review", "theory")),
    ("case_analysis", ("案例分析", "案例研究", "case analysis", "case study")),
    ("conclusion_reflection", ("结论", "反思", "conclusion", "reflection", "discussion")),
)


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _title_key(value: Any) -> str:
    value = _norm(value).casefold()
    value = re.sub(r"^第\s*[一二三四五六七八九十百千万]+\s*章\s*", "", value)
    value = re.sub(r"^\d+(?:\.\d+)*[.)、．]?\s*", "", value)
    return re.sub(r"[\s:：.。、()（）\[\]【】_-]+", "", value)


def _display_title(value: Any) -> str:
    text = _norm(value)
    text = re.sub(r"^第\s*[一二三四五六七八九十百千万]+\s*章\s*", "", text)
    text = re.sub(r"^\d+(?:\.\d+)*[.)、．]?\s+", "", text)
    return text or _norm(value)


def _role_for_title(value: Any) -> str:
    key = _title_key(value)
    for role, candidates in _ROLE_RULES:
        if any(_title_key(candidate) in key or key in _title_key(candidate)
               for candidate in candidates):
            return role
    return "generic_section"


def _section_id(value: Any, fallback: str) -> str:
    text = _norm(value)
    numeric = re.match(r"^\s*(\d+(?:\.\d+)*)[.)、．]?\s+", text)
    if numeric:
        return numeric.group(1)
    chinese = re.match(r"^\s*第\s*([一二三四五六七八九十百千万]+)\s*章", text)
    if chinese:
        digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                  "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        value = chinese.group(1)
        if value in digits:
            return str(digits[value])
    return str(fallback)


def _paragraph_outline_level(paragraph) -> Optional[int]:
    style_name = _norm(getattr(getattr(paragraph, "style", None), "name", ""))
    match = re.search(r"(?:heading|标题)\s*([1-9])", style_name, re.IGNORECASE)
    if match:
        return int(match.group(1))
    ppr = paragraph._p.pPr
    outline = ppr.find(qn("w:outlineLvl")) if ppr is not None else None
    if outline is not None:
        try:
            return int(outline.get(qn("w:val"))) + 1
        except (TypeError, ValueError):
            return None
    return None


def _paragraph_style_name(paragraph) -> str:
    return _norm(getattr(getattr(paragraph, "style", None), "name", ""))


def _heading_records(document) -> List[Dict[str, Any]]:
    records = []
    for index, paragraph in enumerate(document.paragraphs):
        text = _norm(paragraph.text)
        level = _paragraph_outline_level(paragraph)
        if not text or level is None:
            continue
        records.append({
            "paragraph_index": index,
            "title": text,
            "level": level,
            "style": _paragraph_style_name(paragraph),
        })
    return records


def _style_info(document, name: str) -> Dict[str, Any]:
    try:
        style = document.styles[name]
    except KeyError:
        return {"present": False}
    font = style.font
    size = font.size.pt if font.size else None
    color = str(font.color.rgb) if font.color and font.color.rgb else None
    return {
        "present": True,
        "font_name": font.name,
        "font_size_pt": size,
        "bold": font.bold,
        "italic": font.italic,
        "color": color,
        "line_spacing": style.paragraph_format.line_spacing,
        "space_after_pt": (style.paragraph_format.space_after.pt
                            if style.paragraph_format.space_after else None),
        "first_line_indent_twips": (
            round(style.paragraph_format.first_line_indent.twips)
            if style.paragraph_format.first_line_indent else None),
    }


def _section_geometry(section) -> Dict[str, Any]:
    return {
        "page_width_emu": int(section.page_width or 0),
        "page_height_emu": int(section.page_height or 0),
        "top_margin_emu": int(section.top_margin or 0),
        "bottom_margin_emu": int(section.bottom_margin or 0),
        "left_margin_emu": int(section.left_margin or 0),
        "right_margin_emu": int(section.right_margin or 0),
        "header_distance_emu": int(section.header_distance or 0),
        "footer_distance_emu": int(section.footer_distance or 0),
    }


def _fixed_text(document) -> List[str]:
    values = []
    for paragraph in document.paragraphs:
        text = _norm(paragraph.text)
        if text and _paragraph_outline_level(paragraph) is None:
            values.append(text)
    return values[:100]


def _numbering_profile(document) -> List[Dict[str, Any]]:
    values = []
    for index, paragraph in enumerate(document.paragraphs):
        ppr = paragraph._p.pPr
        num_pr = ppr.find(qn("w:numPr")) if ppr is not None else None
        if num_pr is None:
            continue
        num_id = num_pr.find(qn("w:numId"))
        ilvl = num_pr.find(qn("w:ilvl"))
        values.append({
            "paragraph_index": index,
            "num_id": num_id.get(qn("w:val")) if num_id is not None else None,
            "level": ilvl.get(qn("w:val")) if ilvl is not None else None,
            "style": _paragraph_style_name(paragraph),
        })
    return values


def _matter_record(record: Mapping[str, Any], order: int) -> Dict[str, Any]:
    return {
        "section_id": _section_id(record.get("title"), str(order)),
        "title": _display_title(record.get("title")),
        "source_title": record.get("title"),
        "role": _role_for_title(record.get("title")),
        "level": record.get("level", 1),
        "required": True,
        "style": record.get("style", ""),
    }


def _chapter_record(record: Mapping[str, Any], order: int,
                    all_records: List[Mapping[str, Any]], top_level: int = 1) -> Dict[str, Any]:
    source_title = record.get("title") or f"章节 {order}"
    title = _display_title(source_title)
    section_id = _section_id(source_title, str(order))
    start = next(index for index, item in enumerate(all_records)
                 if item is record)
    children = []
    next_order = 1
    for child in all_records[start + 1:]:
        if child.get("level", 1) <= record.get("level", 1):
            break
        source_child_title = child.get("title") or f"小节 {next_order}"
        child_title = _display_title(source_child_title)
        children.append({
            "heading_id": _section_id(source_child_title, f"{section_id}.{next_order}"),
            "title": child_title,
            "source_title": source_child_title,
            "level": int(child.get("level") or 2),
            "required": True,
            "style": child.get("style", ""),
            "markdown_prefix": "#" * max(
                3, int(child.get("level") or 2) - top_level + 2),
        })
        next_order += 1
    return {
        "section_id": section_id,
        "title": title,
        "source_title": source_title,
        "role": _role_for_title(title),
        "level": int(record.get("level") or 1),
        "purpose": "按模板章节标题与顺序组织翻译实践证据。",
        "required_subsections": children,
        "style": record.get("style", ""),
    }


def parse_docx_template(filename: str, template_bytes: bytes) -> Dict[str, Any]:
    """Parse a DOCX into a stable, serializable Template Contract."""
    if not template_bytes:
        raise TemplateParseError("模板文件为空。")
    try:
        document = Document(io.BytesIO(template_bytes))
    except Exception as exc:  # python-docx raises several parser-specific errors
        raise TemplateParseError(f"DOCX 模板无法读取：{exc}") from exc
    records = _heading_records(document)
    if not records:
        raise TemplateParseError("未识别到 Heading 样式或 outline level；请上传包含章节标题的 DOCX 模板。")
    top_level = min(record["level"] for record in records)
    body_records = [record for record in records if record["level"] == top_level]
    front_roles = {"abstract", "table_of_contents"}
    back_roles = {"references", "acknowledgements", "appendix"}
    front = []
    body = []
    back = []
    body_started = False
    for record in body_records:
        role = _role_for_title(record["title"])
        item = _matter_record(record, len(front) + len(back) + len(body) + 1)
        if not body_started and role in front_roles:
            front.append(item)
            continue
        if role in back_roles:
            back.append(item)
            continue
        body_started = True
        body.append(record)
    chapters = [_chapter_record(record, index, records, top_level)
                for index, record in enumerate(body, start=1)]
    if not chapters:
        raise TemplateParseError("模板没有可识别的正文一级章节。")

    sections = [{"geometry": _section_geometry(section)}
                for section in document.sections]
    headers = [
        [_norm(p.text) for p in section.header.paragraphs if _norm(p.text)]
        for section in document.sections
    ]
    footers = [
        [_norm(p.text) for p in section.footer.paragraphs if _norm(p.text)]
        for section in document.sections
    ]
    tables = []
    for table in document.tables:
        rows = []
        for row in table.rows[:3]:
            rows.append([_norm(cell.text) for cell in row.cells])
        tables.append({"rows": rows, "columns": len(table.columns)})
    template_hash = hashlib.sha256(template_bytes).hexdigest()
    contract = {
        "schema_version": SCHEMA_VERSION,
        "template_identity": {
            "filename": str(filename or "template.docx"),
            "sha256": template_hash,
            "template_id": template_hash[:16],
            "source_type": "docx",
        },
        "document_structure": {
            "front_matter": front,
            "chapters": chapters,
            "back_matter": back,
            "heading_count": len(records),
            "top_level": top_level,
        },
        "style_contract": {
            "sections": sections,
            "styles": {name: _style_info(document, name) for name in (
                "Normal", "Title", "Heading 1", "Heading 2", "Heading 3",
                "Intense Quote", "List Bullet", "List Number")},
            "headers": headers,
            "footers": footers,
            "tables": tables,
            "fixed_text": _fixed_text(document),
            "numbering": _numbering_profile(document),
        },
        "source_provenance": {
            "parser": "deterministic-docx-heading-v1",
            "source_filename": str(filename or "template.docx"),
            "warnings": [],
        },
        "strictness": "strict_structure",
    }
    contract["content_hash"] = hashlib.sha256(
        json.dumps(contract, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")).hexdigest()
    return contract


def contract_summary(contract: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not contract:
        return {"configured": False, "status": "template_not_configured"}
    structure = contract.get("document_structure") or {}
    chapters = structure.get("chapters") or []
    subsection_count = sum(len(x.get("required_subsections") or []) for x in chapters)
    return {
        "configured": True,
        "status": "parsed",
        "filename": (contract.get("template_identity") or {}).get("filename"),
        "template_id": (contract.get("template_identity") or {}).get("template_id"),
        "template_hash": (contract.get("template_identity") or {}).get("sha256"),
        "chapter_count": len(chapters),
        "subsection_count": subsection_count,
        "front_matter": [x.get("title") for x in structure.get("front_matter") or []],
        "back_matter": [x.get("title") for x in structure.get("back_matter") or []],
    }


def _delete_paragraph(paragraph: Paragraph) -> None:
    paragraph._element.getparent().remove(paragraph._element)


def _heading_level(paragraph: Paragraph) -> Optional[int]:
    return _paragraph_outline_level(paragraph)


def _find_heading(document, title: str, level: Optional[int] = None) -> Optional[Paragraph]:
    key = _title_key(title)
    for paragraph in document.paragraphs:
        if level is not None and _heading_level(paragraph) != level:
            continue
        if _title_key(paragraph.text) == key:
            return paragraph
    return None


def _insert_paragraph_after(anchor: Paragraph, text: str, style: Optional[str] = None) -> Paragraph:
    element = OxmlElement("w:p")
    anchor._p.addnext(element)
    paragraph = Paragraph(element, anchor._parent)
    if style:
        try:
            paragraph.style = style
        except KeyError:
            pass
    paragraph.add_run(text)
    return paragraph


def _add_markdown_runs(paragraph: Paragraph, text: str) -> None:
    pieces = re.split(r"(\*\*[^*]+\*\*)", str(text or ""))
    for piece in pieces:
        if not piece:
            continue
        bold = piece.startswith("**") and piece.endswith("**")
        value = piece[2:-2] if bold else piece
        run = paragraph.add_run(value)
        if bold:
            run.bold = True


def _insert_content_after(anchor: Paragraph, content: str) -> Paragraph:
    current = anchor
    for raw_line in str(content or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("<!--"):
            continue
        if re.match(r"^#{1,6}\s+", line):
            continue
        style = None
        if line.startswith("> "):
            style = "Intense Quote"
            line = line[2:].strip()
        elif re.match(r"^[-*]\s+", line):
            style = "List Bullet"
            line = re.sub(r"^[-*]\s+", "", line)
        paragraph = _insert_paragraph_after(current, "", style)
        paragraph._p.remove(paragraph.runs[0]._r)
        _add_markdown_runs(paragraph, line)
        current = paragraph
    return current


def _section_content(report_artifact: Mapping[str, Any], section_id: str) -> Dict[str, Any]:
    for section in report_artifact.get("sections") or []:
        if str(section.get("section_id")) == str(section_id):
            return dict(section)
    return {}


def render_report_docx(
    report_artifact: Mapping[str, Any],
    template_bytes: bytes,
    template_contract: Mapping[str, Any],
) -> io.BytesIO:
    """Render a structured report into a copy of the user's DOCX template.

    The template remains the document authority: its sections, styles,
    headers/footers, and existing heading paragraphs are retained.  Generated
    prose is inserted beneath matching canonical headings.
    """
    if not template_bytes:
        raise TemplateParseError("模板文件为空。")
    document = Document(io.BytesIO(template_bytes))
    chapters = ((template_contract.get("document_structure") or {}).get("chapters")
                or [])
    top_level = int(((template_contract.get("document_structure") or {}).get(
        "top_level") or 1))
    body_titles = {_title_key(x.get("title")) for x in chapters}
    chapter_paragraphs = [
        paragraph for paragraph in document.paragraphs
        if _heading_level(paragraph) == top_level and _title_key(paragraph.text) in body_titles
    ]
    if not chapter_paragraphs:
        # Do not silently rebuild a structurally incompatible template.
        raise TemplateParseError("模板正文标题与 Template Contract 不一致，无法安全填充。")
    back_titles = {
        _title_key(x.get("title"))
        for x in ((template_contract.get("document_structure") or {}).get("back_matter")
                  or [])
    }
    in_body = False
    first_body_element = chapter_paragraphs[0]._p
    for paragraph in list(document.paragraphs):
        if paragraph._p is first_body_element:
            in_body = True
            continue
        if not in_body:
            continue
        if _heading_level(paragraph) == top_level and _title_key(paragraph.text) in back_titles:
            in_body = False
            continue
        if in_body and _heading_level(paragraph) is None:
            _delete_paragraph(paragraph)

    for chapter in chapters:
        section_id = str(chapter.get("section_id"))
        heading = _find_heading(document, chapter.get("title"), top_level)
        if heading is None:
            continue
        section = _section_content(report_artifact, section_id)
        subsections = { _title_key(x.get("title")): x
                        for x in section.get("subsections") or [] }
        if subsections:
            chapter_content = section.get("intro_content") or ""
            if chapter_content:
                _insert_content_after(heading, chapter_content)
            for required in chapter.get("required_subsections") or []:
                sub_heading = _find_heading(document, required.get("title"),
                                            int(required.get("level") or 2))
                if sub_heading is None:
                    continue
                item = subsections.get(_title_key(required.get("title"))) or {}
                _insert_content_after(sub_heading, item.get("content") or "")
        else:
            _insert_content_after(heading, section.get("content") or "")
    out = io.BytesIO()
    document.save(out)
    out.seek(0)
    return out
