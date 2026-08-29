"""Deterministic rendered-PDF QA.  LibreOffice is a preview, never Word truth."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping

import fitz


VERSION = "rendered-qa-v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def analyze_pdf(pdf_bytes: bytes) -> Dict[str, Any]:
    """Collect page facts and conservative heuristics.

    Suspicion is a warning or manual review, never an automatic hard fail.
    """
    pages = []
    warnings = []
    manual_reviews = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        for number, page in enumerate(document, start=1):
            rect = page.rect
            blocks = page.get_text("blocks") or []
            text_blocks = [x for x in blocks if x and len(x) > 4]
            text = page.get_text("text") or ""
            fonts = []
            sizes = []
            headings = []
            body_heights = []
            for block in text_blocks:
                x0, y0, x1, y1, content = block[:5]
                area = max(0.0, min(float(x1), rect.width) - max(0.0, float(x0))) * \
                    max(0.0, min(float(y1), rect.height) - max(0.0, float(y0)))
                page_dict = page.get_text("dict", clip=fitz.Rect(x0, y0, x1, y1))
                block_sizes = []
                block_fonts = []
                for span_block in page_dict.get("blocks") or []:
                    for line in span_block.get("lines") or []:
                        for span in line.get("spans") or []:
                            if span.get("font"):
                                block_fonts.append(str(span["font"]))
                            if span.get("size"):
                                size = round(float(span["size"]), 1)
                                block_sizes.append(size)
                                sizes.append(size)
                fonts.extend(block_fonts)
                body_heights.append(area)
                if block_sizes and block_fonts and max(block_sizes) >= 13:
                    headings.append({"bbox": [x0, y0, x1, y1],
                                     "text": str(content).strip()[:120],
                                     "font": block_fonts[0],
                                     "size": max(block_sizes)})
            page_number_region = bool(re.search(
                r"(?:^|\n)\s*\d{1,3}\s*(?:\n|$)", text))
            metrics = {
                "page": number,
                "width": round(rect.width, 2),
                "height": round(rect.height, 2),
                "text_block_count": len(text_blocks),
                "image_block_count": len(page.get_images(full=True)),
                "drawing_block_count": len(page.get_drawings()),
                "text_chars": len(text.strip()),
                "content_occupancy": round(sum(body_heights) /
                                           max(rect.width * rect.height, 1.0), 4),
                "font_names": sorted(set(fonts))[:20],
                "font_sizes": sorted(set(sizes))[:20],
                "headings": headings[:20],
                "header_region_chars": len((page.get_text(
                    "text", clip=fitz.Rect(0, 0, rect.width, rect.height * .08))
                    or "").strip()),
                "footer_region_chars": len((page.get_text(
                    "text", clip=fitz.Rect(0, rect.height * .92, rect.width,
                                           rect.height)) or "").strip()),
                "page_number_region": page_number_region,
            }
            pages.append(metrics)
    if pages and any(x["text_chars"] == 0 and not x["image_block_count"]
                     for x in pages):
        blanks = [x["page"] for x in pages
                  if not x["text_chars"] and not x["image_block_count"]]
        warnings.append({"type": "suspected_blank_page", "pages": blanks,
                         "severity": "warning"})
    occupied = [x["content_occupancy"] for x in pages if x["text_chars"]]
    if occupied:
        average = sum(occupied) / len(occupied)
        low = [x["page"] for x in pages if x["text_chars"] and
               x["content_occupancy"] < max(0.01, average * .1)]
        high = [x["page"] for x in pages if x["content_occupancy"] > .92]
        if low:
            manual_reviews.append({"type": "low_content_density",
                                   "pages": low, "severity": "manual_review"})
        if high:
            warnings.append({"type": "high_content_density", "pages": high,
                             "severity": "warning"})
    orphan_headings = []
    for page in pages:
        for heading in page["headings"]:
            below = heading["bbox"][3]
            if page["text_chars"] - len(heading["text"]) < 80:
                orphan_headings.append({"page": page["page"],
                                        "text": heading["text"]})
    if orphan_headings:
        manual_reviews.append({"type": "suspected_orphan_heading",
                               "items": orphan_headings,
                               "severity": "manual_review"})
    if len(pages) >= 2:
        body_pages = pages[1:]
        missing_header = [item["page"] for item in body_pages
                          if item["header_region_chars"] == 0]
        missing_footer = [item["page"] for item in body_pages
                          if item["footer_region_chars"] == 0]
        missing_numbers = [item["page"] for item in body_pages
                           if not item["page_number_region"]]
        if missing_header:
            manual_reviews.append({
                "type": "header_region_missing_or_unconfirmed",
                "pages": missing_header, "severity": "manual_review"})
        if missing_footer:
            manual_reviews.append({
                "type": "footer_region_missing_or_unconfirmed",
                "pages": missing_footer, "severity": "manual_review"})
        if missing_numbers:
            manual_reviews.append({
                "type": "page_number_region_missing_or_unconfirmed",
                "pages": missing_numbers, "severity": "manual_review"})
    overflow = [x["page"] for x in pages
                if any(h["bbox"][2] > x["width"] + 1 or h["bbox"][3] > x["height"] + 1
                       for h in x["headings"])]
    if overflow:
        manual_reviews.append({"type": "possible_boundary_overflow",
                               "pages": sorted(set(overflow)),
                               "severity": "manual_review"})
    return {
        "schema_version": VERSION,
        "page_count": len(pages),
        "pages": pages,
        "font_names": sorted({font for page in pages
                              for font in page["font_names"]}),
        "definite_failures": [],
        "warnings": warnings,
        "manual_reviews": manual_reviews,
        "status": "warning" if warnings else
        "manual_review" if manual_reviews else "pass",
    }


def build_render_record(
    *, document_kind: str, source_docx: bytes, rendered_pdf: bytes,
    engine: str, engine_version: str, analysis: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": VERSION, "document_kind": document_kind,
        "render_engine": engine, "render_engine_version": engine_version,
        "source_docx_hash": sha256(source_docx),
        "rendered_pdf_hash": sha256(rendered_pdf),
        "rendered_at": now_iso(), "page_count": analysis.get("page_count"),
        "analysis": dict(analysis),
        "status": "failed" if analysis.get("definite_failures") else "pass",
        "stale_reason": None,
    }


def key_page_references(render_record: Mapping[str, Any]) -> list[Dict[str, Any]]:
    """Return stable page locations for the pages an author must inspect."""
    pages = list((render_record.get("analysis") or {}).get("pages") or [])
    refs = [{"page": 1 if pages else None, "label": "封面", "basis": "首个渲染页"}]
    anchors = (
        ("中文摘要", ("摘  要", "摘要")),
        ("英文摘要", ("ABSTRACT", "Abstract")),
        ("目录", ("目录", "Contents")),
        ("首个案例页", ("案例", "例[")),
        ("参考文献", ("参考文献", "References")),
        ("附录", ("附录", "Appendix")),
    )
    for label, needles in anchors:
        found = None
        for page in pages:
            headings = " ".join(str(x.get("text") or "")
                                 for x in page.get("headings") or [])
            if any(needle.casefold() in headings.casefold() for needle in needles):
                found = page.get("page")
                break
        refs.append({"page": found, "label": label,
                     "basis": "标题 bounding box" if found else "未从标题可靠定位"})
    return refs


def render_qa_markdown(
    *, translation_hash: str, report_hash: str, docx_hash: str,
    render_record: Mapping[str, Any], pdf_qa: Mapping[str, Any],
    compliance: Mapping[str, Any], case_review: Mapping[str, Any],
    final_qa: Mapping[str, Any], placeholders: Iterable[Mapping[str, Any]] = (),
) -> str:
    warnings = pdf_qa.get("warnings") or []
    manual = list(pdf_qa.get("manual_reviews") or []) + list(placeholders or [])
    return "\n".join([
        "# report-qa", "",
        "## Artifact bindings", "",
        f"- Translation Truth Hash: `{translation_hash}`",
        f"- Report artifact hash: `{report_hash}`",
        f"- DOCX hash: `{docx_hash}`",
        f"- Rendered PDF hash: `{render_record.get('rendered_pdf_hash')}`",
        "",
        "## Case review", "",
        f"- Required: {case_review.get('required_count', 0)}",
        f"- Approved: {case_review.get('approved_count', 0)}",
        f"- Blocked: {case_review.get('blocked_count', 0)}",
        f"- Blocked IDs: {', '.join(case_review.get('blocked_case_ids') or []) or '—'}",
        "",
        "## Compliance", "",
        f"- Default profile: {compliance.get('profile_compliance', {}).get('status')}",
        f"- Project constraints: {compliance.get('project_constraints', {}).get('status')}",
        f"- Manual reviews: {len(compliance.get('manual_reviews') or [])}",
        f"- Conflicts: {len(compliance.get('conflicts') or [])}",
        f"- Enforced rules: {compliance.get('source_audit', {}).get('enforced_rule_count', 0)}",
        f"- Rules without reliable source mapping: {len(compliance.get('source_audit', {}).get('rules_without_source_mapping', []) or [])}",
        "",
        "## Structural QA", "",
        f"- Status: {final_qa.get('structural_qa', 'NOT_RUN')}",
        "",
        "## LibreOffice render", "",
        f"- Engine: {render_record.get('render_engine')} {render_record.get('render_engine_version')}",
        f"- Status: {render_record.get('status')}",
        f"- Pages: {render_record.get('page_count')}",
        f"- Source DOCX: `{render_record.get('source_docx_hash')}`",
        f"- PDF: `{render_record.get('rendered_pdf_hash')}`",
        "",
        "## PDF deterministic QA", "",
        f"- Status: {pdf_qa.get('status')}",
        f"- Warnings: {len(warnings)}",
        f"- Manual reviews: {len(manual)}",
        "",
        "```json",
        json.dumps({"warnings": warnings, "manual_reviews": manual},
                   ensure_ascii=False, indent=2),
        "```",
        "",
        "## Independent human facts", "",
        f"- Author Visual Review: {final_qa.get('author_visual_review', 'NOT_CONFIRMED')}",
        f"- Word Final Review: {final_qa.get('word_final_review', 'NOT_CONFIRMED')}",
        "",
        "LibreOffice PASS is not Microsoft Word final truth.",
        "",
        "## Manual Review Items",
        "",
        "- " + ("\n- ".join(str(item.get("rule_id") or item.get("type") or item)
                           for item in compliance.get("unresolved_items") or [])
                or "—"),
        "",
        "## Unresolved Placeholders",
        "",
        "- " + ("\n- ".join(str(item.get("excerpt") or item)
                           for item in placeholders or []) or "—"),
        "",
        "## Frozen Delivery readiness",
        "",
        f"- Case review gate: {case_review.get('status', 'not_run')}",
        f"- Compliance result: {compliance.get('status', 'not_run')}",
        f"- Structural QA: {final_qa.get('structural_qa', 'NOT_RUN')}",
        f"- LibreOffice Render: {final_qa.get('libreoffice_render', 'NOT_RUN')}",
        f"- Author Visual Review: {final_qa.get('author_visual_review', 'NOT_CONFIRMED')}",
        f"- Word Final Review: {final_qa.get('word_final_review', 'NOT_CONFIRMED')}",
        "",
    ])
