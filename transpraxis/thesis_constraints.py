"""Configurable report-structure metadata for the writing pipeline."""
from __future__ import annotations

from typing import Any, Dict, Mapping


SCHEMA_VERSION = "transpraxis-report-constraints-v2"


def _sections(settings: Mapping[str, Any], raw=None) -> list[Dict[str, Any]]:
    raw = (settings.get("report_sections") or settings.get("outline_sections") or []) \
        if raw is None else raw
    sections: list[Dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, Mapping):
            continue
        section_id = str(item.get("section_id") or index)
        title = str(item.get("title") or f"Section {section_id}").strip()
        required = []
        for subsection in item.get("required_subsections") or []:
            if isinstance(subsection, str):
                subsection = {"title": subsection}
            if not isinstance(subsection, Mapping):
                continue
            heading_id = str(subsection.get("heading_id") or "").strip()
            heading_title = str(subsection.get("title") or "").strip()
            if heading_id and heading_title:
                required.append({
                    "heading_id": heading_id,
                    "title": heading_title,
                    "level": int(subsection.get("level") or 2),
                    "markdown_prefix": "#" * (int(subsection.get("level") or 2) + 1),
                })
        sections.append({
            "section_id": section_id,
            "title": title,
            "role": str(item.get("role") or "generic_section"),
            "level": int(item.get("level") or 1),
            "purpose": str(item.get("purpose") or "").strip(),
            "required_subsections": required,
        })
    return sections


def _template_contract(settings: Mapping[str, Any]) -> Mapping[str, Any] | None:
    return settings.get("report_template_contract") or settings.get("template_contract")


def _template_sections(
    contract: Mapping[str, Any], project_name: str = "",
) -> list[Dict[str, Any]]:
    structure = contract.get("document_structure") or {}
    sections = []
    for item in structure.get("chapters") or []:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title") or "").strip()
        if project_name:
            title = title.replace("XXX", project_name).replace("×××", project_name)
        sections.append({
            "section_id": str(item.get("section_id") or len(sections) + 1),
            "title": title,
            "role": str(item.get("role") or "generic_section"),
            "level": int(item.get("level") or 1),
            "purpose": str(item.get("purpose") or "").strip(),
            "required_subsections": [
                {
                    "heading_id": str(x.get("heading_id") or ""),
                    "title": str(x.get("title") or "").strip(),
                    "level": int(x.get("level") or 2),
                    "markdown_prefix": str(x.get("markdown_prefix") or (
                        "#" * (int(x.get("level") or 2) + 1))),
                    "required": bool(x.get("required", True)),
                    "allows_dynamic_children": bool(
                        x.get("allows_dynamic_children", False)),
                    "mapping_group": x.get("mapping_group"),
                    "mapping_side": x.get("mapping_side"),
                }
                for x in item.get("required_subsections") or []
                if isinstance(x, Mapping) and str(x.get("title") or "").strip()
            ],
        })
    return sections


def build_constraints(settings: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Build canonical report constraints with template-first structure."""
    settings = dict(settings or {})
    contract = _template_contract(settings)
    explicit_override = settings.get("report_structure_override") \
        or settings.get("report_sections_override") \
        or settings.get("outline_sections_override")
    template_sections = _template_sections(
        contract, str(settings.get("project_name") or "").strip()) if contract else []
    if explicit_override:
        sections = _sections(settings, explicit_override)
        structure_source = "explicit_user_override"
    elif template_sections:
        sections = template_sections
        structure_source = "parsed_template_contract"
    else:
        sections = _sections(settings)
        structure_source = "user_configured_sections" if sections else "generic_planning"
    language = str(settings.get("body_language") or "").strip()
    identity = (contract or {}).get("template_identity") or {}
    structure = (contract or {}).get("document_structure") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "translation_practice_report",
        "template": {
            "configured": bool(contract),
            "status": "parsed" if contract else "template_not_configured",
            "template_id": identity.get("template_id"),
            "template_hash": identity.get("sha256"),
            "contract_version": (contract or {}).get("schema_version"),
            "source_provenance": (contract or {}).get("source_provenance") or {},
            "strictness": (contract or {}).get("strictness") or "generic",
            "structure_source": structure_source,
            "explicit_override": bool(explicit_override),
        },
        "template_id": identity.get("template_id"),
        "template_hash": identity.get("sha256"),
        "template_contract_version": (contract or {}).get("schema_version"),
        "template_contract": contract,
        "structure_source": structure_source,
        "body_language": {
            "language": language,
            "status": "configured" if language else "unspecified",
        },
        "document_scope": {
            "body_chapters": [x["section_id"] for x in sections],
            "current_pipeline_scope": "configured_sections",
        },
        "chapters": sections,
        "front_matter": list(structure.get("front_matter") or []) if contract else [],
        "back_matter": list(structure.get("back_matter") or []) if contract else [],
        "style_contract": (contract or {}).get("style_contract") or {},
        "strict_structure": bool(contract),
        "cross_chapter_chain": list(settings.get("cross_chapter_chain") or []),
        "case_analysis_contract": [
            "problem_and_question_link",
            "source_and_context",
            "recorded_translation_evidence",
            "decision_rationale",
            "bounded_conclusion",
        ],
        "evidence_rules": {
            "do_not_reconstruct_missing_translation": True,
            "do_not_infer_unobserved_intention": True,
            "theory_is_optional_and_must_be_grounded": True,
            "case_count_follows_evidence": True,
        },
        "style_rules": {
            "academic_register": settings.get("writing_style") or "规范、克制、证据驱动的书面语",
            "toc_max_heading_depth": int(settings.get("toc_max_heading_depth") or 3),
        },
    }


def chapter_index(constraints: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x["section_id"]): dict(x)
            for x in constraints.get("chapters") or []}
