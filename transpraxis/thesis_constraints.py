"""Configurable report-structure metadata for the writing pipeline."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Mapping


SCHEMA_VERSION = "transpraxis-report-constraints-v4"


# This is a concrete project profile, not a generic rules engine.  The
# roadmap is the currently checked-in authority map; any item that still
# needs a school-handbook confirmation is explicitly marked manual.
COMPLIANCE_PROFILES = {
    "MTI_PRACTICE_REPORT_DEFAULT": {
        "profile_id": "MTI_PRACTICE_REPORT_DEFAULT",
        "institution": "示例培养单位",
        "program": "MTI 英语笔译",
        "effective_date": "2026",
        "source_documents": [{
            "file": "docs/mti-practice-driven-roadmap.md",
            "page": "—",
            "clause": "阶段 4：Compliance Profile + Language Constraints",
            "authority": "TransPraxis 项目规范映射；待学校手册逐条确认的项目显示为 manual",
        }],
        "rules": [
            {"id": "abstract_zh_length", "label": "中文摘要 400—600 字",
             "source_clause": "阶段 4 / 首批确定性检查 / 中文摘要",
             "applicability": "启用实践报告时",
             "check_level": "deterministic"},
            {"id": "keywords_count", "label": "中英文关键词各 5—8 个",
             "source_clause": "阶段 4 / 首批确定性检查 / 中英文关键词",
             "applicability": "启用实践报告时",
             "check_level": "deterministic"},
            {"id": "toc_depth", "label": "目录最多三级",
             "source_clause": "阶段 4 / 首批确定性检查 / 目录",
             "applicability": "启用实践报告时",
             "check_level": "deterministic"},
            {"id": "citation_reference_bidirectional", "label": "正文引用与参考文献双向对应",
             "source_clause": "阶段 4 / 首批确定性检查 / 正文引用与参考文献",
             "applicability": "存在参考文献或正文引用时",
             "check_level": "deterministic"},
            {"id": "figure_table_numbering", "label": "图表按章编号",
             "source_clause": "阶段 4 / 首批确定性检查 / 图号与表号",
             "applicability": "报告含图表时",
             "check_level": "deterministic"},
            {"id": "front_back_matter", "label": "正文与附录角色正确",
             "source_clause": "阶段 4 / 首批确定性检查 / 正文与附录",
             "applicability": "启用模板或报告要求附录时",
             "check_level": "deterministic"},
            {"id": "bilingual_appendix", "label": "存在双语对照附录",
             "source_clause": "阶段 4 / 首批确定性检查 / 双语对照附录",
             "applicability": "实践报告终稿",
             "check_level": "deterministic"},
            {"id": "source_word_count", "label": "源文原则上不少于 10,000 词",
             "source_clause": "阶段 4 / 首批确定性检查 / 笔译实践源文",
             "applicability": "实践报告终稿",
             "check_level": "deterministic"},
            {"id": "case_conclusion_coverage", "label": "案例分析为核心章节且结论回应研究问题",
             "source_clause": "阶段 4 / 首批确定性检查 / 案例分析与结论",
             "applicability": "启用实践报告时",
             "check_level": "deterministic"},
            {"id": "layout_structure", "label": "页面与标题结构符合模板",
             "source_clause": "阶段 4 / 首批确定性检查 / 页面结构与样式",
             "applicability": "存在 DOCX 时",
             "check_level": "manual"},
            {"id": "synthetic_case_policy", "label": "合成案例计数与披露符合 profile",
             "source_clause": "阶段 4 / 首批确定性检查 / synthetic case 政策",
             "applicability": "报告含合成对照案例时",
             "check_level": "deterministic"},
            {"id": "author_placeholders", "label": "人工确认项已处理",
             "source_clause": "阶段 4 / 首批确定性检查 / 【待作者填写】",
             "applicability": "报告或模板含人工确认项时",
             "check_level": "manual"},
        ],
    },
}


def compliance_profile(profile_id: str = "MTI_PRACTICE_REPORT_DEFAULT") -> Dict[str, Any]:
    """Return a copy of one explicit compliance profile."""
    profile = deepcopy(COMPLIANCE_PROFILES.get(profile_id) or
                       COMPLIANCE_PROFILES["MTI_PRACTICE_REPORT_DEFAULT"])
    source = profile.get("source_documents", [{}])[0]
    for rule in profile.get("rules") or []:
        rule["source"] = {
            "file": source.get("file", "—"),
            "page": source.get("page", "—"),
            "clause": rule.get("source_clause") or "—",
            "authority": source.get("authority", "—"),
        }
    return profile

CASE_POLICIES = {
    "proposal": {
        "minimum_cases": 6,
        "recommended_cases": 8,
        "target_cases": 8,
        "candidate_pool_target": 10,
        "synthetic_counts_toward_minimum": True,
        "synthetic_count_policy": "counts_toward_minimum",
    },
    "final_report": {
        "minimum_cases": 20,
        "recommended_cases": 24,
        "target_cases": 24,
        "candidate_pool_target": 26,
        "final_case_types": ["authentic_revision", "synthetic_contrast"],
        "contrast_required": True,
        "translation_decision_role": "candidate_evidence_only",
        "translation_decision_final_allowed": False,
        "research_question_minimum_contrasts": 2,
        "synthetic_gate_count": 4,
        "synthetic_counts_toward_minimum": True,
        "synthetic_count_policy": "counts_toward_minimum",
    },
}


def report_stage(settings: Mapping[str, Any] | None = None) -> str:
    value = str((settings or {}).get("report_stage") or "final_report").strip()
    return value if value in CASE_POLICIES else "final_report"


def case_policy(settings: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    stage = report_stage(settings)
    settings = settings or {}
    policy = {"report_stage": stage, **CASE_POLICIES[stage]}
    profile = settings.get("strict_compliance_profile")
    if profile is None:
        profile = settings.get("compliance_profile")
    profile_value = profile.get("synthetic_counts_toward_minimum") \
        if isinstance(profile, Mapping) else None
    if profile_value is None and isinstance(profile, bool):
        profile_value = not profile
    if profile_value is None and isinstance(profile, str) \
            and profile.casefold() in {"strict", "strict_compliance"}:
        profile_value = False
    if "synthetic_counts_toward_minimum" in settings:
        profile_value = bool(settings["synthetic_counts_toward_minimum"])
    if profile_value is not None:
        policy["synthetic_counts_toward_minimum"] = bool(profile_value)
    policy["synthetic_count_policy"] = (
        "counts_toward_minimum" if policy["synthetic_counts_toward_minimum"]
        else "supplement_only")
    if isinstance(profile, Mapping) and profile.get("profile_id"):
        policy["compliance_profile_id"] = str(profile["profile_id"])
    elif isinstance(profile, str) and profile:
        policy["compliance_profile_id"] = profile
    elif isinstance(profile, bool):
        policy["compliance_profile_id"] = "strict" if profile else "generic"
    return policy


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
    policy = case_policy(settings)
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "translation_practice_report",
        "report_stage": policy["report_stage"],
        "case_policy": policy,
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


def case_subsection_roots(chapter: Mapping[str, Any]) -> tuple[str, str]:
    """Return the difficulty/strategy roots for one case-analysis chapter."""
    required = list(chapter.get("required_subsections") or [])

    def find(side: str, hints: tuple[str, ...]) -> str:
        def first(candidates: list[str]) -> str:
            return min((value for value in candidates if value),
                       key=lambda value: (value.count("."), len(value)), default="")

        mapped = first([
            str(item.get("heading_id") or "") for item in required
            if item.get("mapping_side") == side])
        if mapped:
            return mapped
        return first([
            str(item.get("heading_id") or "") for item in required
            if any(hint in str(item.get("title") or "").casefold() for hint in hints)
        ])

    section_id = str(chapter.get("section_id") or "3")
    problem = find("problem", ("难点", "翻译问题", "difficult", "translation problem",
                               "challenge"))
    solution = find("solution", ("策略", "解决", "strategy", "solution"))
    return problem or f"{section_id}.2", solution or f"{section_id}.3"
