"""Deterministic integrity checks for evidence-grounded MTI reports."""
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Optional

from .academic_evidence import (
    is_eligible_revision_case, literature_index, segment_index, stable_hash,
)
from . import case_analysis, literature_evidence, report_template, synthetic_cases, thesis_constraints

SCHEMA_VERSION = "academic-validation-v4"
VALIDATOR_VERSION = "validator-v11"

_SEGMENT_REF = re.compile(r"\[(seg-[A-Za-z0-9_-]+-\d{4,})\]")
_QUOTE = re.compile(
    r"^\s*>\s*\[(SOURCE|INITIAL|TARGET)\s+"
    r"((?:seg-[A-Za-z0-9_-]+-\d{4,})|(?:TD-\d{4,}))\]:\s*(.*)$",
    re.MULTILINE,
)
_SYNTHETIC_QUOTE = re.compile(
    r"^\s*>\s*\[(SYNTHETIC_SOURCE|SIMULATED|OPTIMIZED)\s+(SC-\d{4,})\]:\s*(.*)$",
    re.MULTILINE,
)
_SYNTHETIC_CASE_ID = re.compile(r"\b(SC-\d{4,})\b")
_SYNTHETIC_AS_HISTORY = re.compile(
    r"笔者(?:的)?初译|作者(?:的)?初译|译者(?:的)?初译|经(?:审校|修订)后|"
    r"初译阶段(?:出现|存在)|(?:后来|最终)(?:将|把).{0,40}(?:改为|修改为|修订为)|"
    r"the (?:author|translator) originally translated|after (?:review|revision)",
    re.IGNORECASE,
)
_EMPIRICAL_HUMAN_ERROR = re.compile(
    r"(?:常见|普遍|频繁)(?:的)?(?:人类|人工|译者)?(?:翻译)?错误|"
    r"(?:common|frequent|widespread) human translation error", re.IGNORECASE)
_STAT = re.compile(
    r"(-?\d[\d,.]*(?:%)?|true|false|\{[^<\n]*\}|\[[^<\n]*\])"
    r"<!--stat:([A-Za-z0-9_.-]+)-->")
_STAT_TOKEN = re.compile(r"\{\{STAT:([A-Za-z0-9_.-]+)\}\}")
_CITATION = re.compile(
    r"(?:\[@([A-Za-z0-9_.:-]+)\]|<!--cite:([A-Za-z0-9_.:-]+)-->)")
_TERM = re.compile(r"<!--term:([A-Za-z0-9_.:-]+)-->")
_CLAIM = re.compile(r"<!--claim:([A-Za-z0-9_.:-]+)-->")
_RQ = re.compile(r"<!--rq:([A-Za-z0-9_.:-]+)-->")
_LIT_CLAIM = re.compile(r"<!--lit-claim:([A-Za-z0-9_.:-]+)-->")
_LIT_EVIDENCE = re.compile(r"<!--lit-evidence:([A-Za-z0-9_.:-]+)-->")
_LIT_QUOTE = re.compile(
    r"^\s*>\s*\[LITERATURE\s+(LE-[A-Za-z0-9_-]+)\]:\s*(.*)$", re.MULTILINE)
_HUMAN_EV = re.compile(r"<!--human-ev:([A-Za-z0-9_.:-]+)-->")
_CASE_COUNT_POLICY = re.compile(
    r"<!--case-count-policy:(sufficient_revision_cases|two_case_fallback|"
    r"insufficient_revision_cases)-->")
_CASE_MARKER = re.compile(r"<!--case:([A-Za-z0-9_.:-]+)-->")
_VISIBLE_CASE_EXAMPLE = re.compile(
    r"^[ \t]*(?:[-*][ \t]*)?\*{1,2}例\[\d+\][^\n]*?\*{0,2}[ \t]*$",
    re.MULTILINE)
_DECISION_AS_REVISION = re.compile(
    r"(?:笔者|译者|作者)?(?:的)?初译|修改后|修订后|改译为|"
    r"(?:经|经过)(?:审校|修改|修订).{0,24}(?:改为|修改为|修订为)")
_THREE_CORE_CASES = re.compile(
    r"(?<!第)(?:三个|3\s*个|三则|three)\s*"
    r"(?:真实|核心|修订|translation\s+revision\s+)*案例",
    re.IGNORECASE)
_FORMAL_AUTHOR_YEAR = re.compile(
    r"(?:\b[A-Z][A-Za-z'’-]+(?:\s+(?:&|and)\s+[A-Z][A-Za-z'’-]+)?\s*"
    r"\((?:19|20)\d{2}[a-z]?\)|\([A-Z][A-Za-z'’-]+(?:\s+et\s+al\.)?,\s*"
    r"(?:19|20)\d{2}[a-z]?\))"
)
_ENGLISH_WORD = re.compile(r"\b[A-Za-z]+(?:['’-][A-Za-z]+)?\b")
_CJK_CHAR = re.compile(r"[\u3400-\u9fff]")


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _issue(issue_type: str, reason: str, *, severity: str = "error",
           section_id: Optional[str] = None, claim_id: Optional[str] = None,
           evidence_id: Optional[str] = None,
           suggested_action: str = "") -> Dict[str, Any]:
    return {
        "issue_id": "",
        "type": issue_type,
        "severity": severity,
        "section_id": section_id,
        "claim_id": claim_id,
        "evidence_id": evidence_id,
        "reason": reason,
        "suggested_action": suggested_action,
    }


def _statistics(evidence: Dict[str, Any]) -> Dict[str, Any]:
    return evidence.get("project_evidence", {}).get("statistics", {})


def resolve_statistic(stats: Mapping, key: str) -> tuple[bool, Any]:
    """Resolve a top-level or dotted path from canonical project statistics."""
    if key in stats:
        return True, stats[key]
    value: Any = stats
    for part in str(key).split("."):
        if not isinstance(value, Mapping) or part not in value:
            return False, None
        value = value[part]
    return True, value


def statistic_keys(stats: Mapping) -> set[str]:
    """Return canonical top-level and dotted statistic paths."""
    keys: set[str] = set()

    def visit(value: Any, prefix: str = "") -> None:
        if not isinstance(value, Mapping):
            return
        for raw_key, child in value.items():
            key = f"{prefix}.{raw_key}" if prefix else str(raw_key)
            keys.add(key)
            visit(child, key)

    visit(stats)
    return keys


_STATISTIC_ISSUE_TYPES = frozenset({
    "unknown_project_statistic", "wrong_project_statistic",
    "unresolved_statistic_token", "unmarked_project_statistic",
})
_CASE_VALIDATION_ISSUE_TYPES = frozenset({
    "case_count_status_mismatch", "insufficient_core_revision_cases",
    "missing_revision_evidence_scarcity_disclosure", "wrong_core_case_count_claim",
    "invalid_selected_case", "non_revision_case_used_as_revision_analysis",
    "synthetic_pipeline_unavailable", "synthetic_only_without_eligible_cases",
    "missing_synthetic_case_quotes", "missing_synthetic_methodology_disclosure",
    "missing_synthetic_limitation_disclosure", "mixed_case_groups_not_visible",
    "unknown_synthetic_case", "wrong_synthetic_case_quote",
    "synthetic_case_presented_as_historical", "ineligible_synthetic_case_selected",
    "synthetic_case_provenance_mismatch", "described_revision_not_in_stored_delta",
    "duplicate_selected_case_presentation", "case_presentation_count_mismatch",
    "unbound_visible_case_example", "orphan_case_marker",
    "translation_decision_presented_as_revision",
})


def _dimension_status(validation: Dict[str, Any], issue_types: set[str]) -> str:
    relevant = [x for x in validation.get("issues", [])
                if x.get("type") in issue_types]
    if any(x.get("severity") == "error" for x in relevant):
        return "fail"
    return "pass_with_warnings" if relevant else "pass"


def statistics_validation_status(validation: Dict[str, Any]) -> str:
    return _dimension_status(validation, _STATISTIC_ISSUE_TYPES)


def case_eligibility_status(validation: Dict[str, Any]) -> str:
    return _dimension_status(validation, _CASE_VALIDATION_ISSUE_TYPES)


def citation_validation_status(
    validation: Dict[str, Any],
    literature_sources_artifact: Optional[Dict[str, Any]] = None,
    literature_evidence_artifact: Optional[Dict[str, Any]] = None,
    literature_claims_artifact: Optional[Dict[str, Any]] = None,
) -> str:
    """Report only literature/citation integrity, independent of other gates."""
    literature_issues = [
        x for x in validation.get("issues", [])
        if "literature" in str(x.get("type") or "")
        or "citation" in str(x.get("type") or "")
        or x.get("type") in {
            "argument_plan_source_id_without_grounding",
            "outline_source_id_without_grounding",
        }
    ]
    if any(x.get("severity") == "error" for x in literature_issues):
        return "fail"
    if literature_issues:
        return "pass_with_warnings"
    sources = (literature_sources_artifact or {}).get("sources") or []
    evidence_items = [x for x in
                      (literature_evidence_artifact or {}).get("items") or []
                      if x.get("eligible_for_claim")]
    claims = (literature_claims_artifact or {}).get("items") or []
    if not sources or not evidence_items or not claims:
        return "evidence_missing"
    return "pass"


def _value_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
    return str(value)


def _described_piece_in(text: Any, piece: Any) -> bool:
    """Match an exact revision fragment or an ellipsis-abbreviated fragment."""
    haystack = _norm(text)
    parts = [x for x in re.split(r"(?:\.{3,}|…+)", _norm(piece)) if x]
    cursor = 0
    for part in parts:
        found = haystack.find(part, cursor)
        if found < 0:
            return False
        cursor = found + len(part)
    return bool(parts)


def expand_evidence_tokens(
    text: str, evidence: Dict[str, Any],
    statistic_overrides: Optional[Dict[str, Any]] = None,
) -> str:
    """Replace deterministic metric/term tokens with values and markers.

    ``statistic_overrides`` is only for a caller's explicit evidence scope,
    such as the one selected authentic case in a case-analysis section. A
    missing value deliberately remains for the validator to reject; this
    function never invents a statistic.
    """
    stats = dict(_statistics(evidence))
    stats.update(statistic_overrides or {})
    glossary = {str(x.get("id")): x for x in
                evidence.get("project_evidence", {}).get("glossary", [])
                if x.get("id")}
    literature = literature_index(evidence)

    def stat_repl(match: re.Match) -> str:
        key = match.group(1)
        found, value = resolve_statistic(stats, key)
        if not found or value is None:
            return match.group(0)
        return f"{_value_text(value)}<!--stat:{key}-->"

    def term_repl(match: re.Match) -> str:
        key = match.group(1)
        entry = glossary.get(key)
        if not entry:
            return match.group(0)
        value = entry.get("preferred") or entry.get("target") or entry.get("source") or key
        return f"{value}<!--term:{key}-->"

    def cite_repl(match: re.Match) -> str:
        key = match.group(1)
        source = literature.get(key)
        if not source:
            return match.group(0)
        citation = source.get("citation_metadata") or source.get("citation") or {}
        visible = str(citation.get("in_text") or "").strip()
        if not visible:
            authors = source.get("authors") or []
            author = str(authors[0]).strip() if authors else ""
            surname = author.split()[-1] if author else ""
            year = str(source.get("year") or "").strip()
            if surname and year:
                visible = f"{surname}（{year}）"
            elif source.get("title"):
                visible = f"《{source['title']}》"
            else:
                visible = key
        return f"{visible}<!--cite:{key}-->"

    text = re.sub(r"\{\{STAT:([A-Za-z0-9_.-]+)\}\}", stat_repl, text)
    text = re.sub(r"\{\{TERM:([A-Za-z0-9_.:-]+)\}\}", term_repl, text)
    text = re.sub(r"\[@([A-Za-z0-9_.:-]+)\]", cite_repl, text)

    def collapse(marker_type: str, key: str, value: Any) -> None:
        nonlocal text
        visible = _value_text(value)
        if not visible:
            return
        escaped = re.escape(visible)
        marker = f"<!--{marker_type}:{key}-->"
        marker_re = re.escape(marker)
        previous = None
        while previous != text:
            previous = text
            text = re.sub(
                rf"(?:{escaped}){{2,}}{marker_re}", f"{visible}{marker}", text)
            text = re.sub(
                rf"{escaped}\s*[（(]\s*{escaped}{marker_re}\s*[）)]",
                f"{visible}{marker}", text)
            text = re.sub(
                rf"([‘’“”\"']{escaped}[‘’“”\"'])\s*[（(]\s*"
                rf"{escaped}{marker_re}\s*[）)]", rf"\1{marker}", text)

    for key, value in stats.items():
        if value is not None:
            collapse("stat", str(key), value)
    for key, entry in glossary.items():
        value = entry.get("preferred") or entry.get("target") or entry.get("source")
        if value:
            collapse("term", str(key), value)
    return text


def case_statistic_overrides(
    section: Dict[str, Any], selected_cases: Dict[str, Any],
    evidence: Dict[str, Any],
) -> Dict[str, Any]:
    """Return case metrics only when the section has one authentic case.

    ``term_count`` is read from the canonical candidate matched to the selected
    case. It is not a document-wide count, so a section with zero or multiple
    cases must leave the token unresolved.
    """
    case_ids = [str(x) for x in section.get("cases") or [] if x]
    if len(case_ids) != 1:
        return {}
    case = next((x for x in selected_cases.get("cases", [])
                 if str(x.get("case_id")) == case_ids[0]), None)
    if not case or case.get("case_type") != "authentic_revision":
        return {}
    candidate = next((x for x in evidence.get("candidate_cases", [])
                      if str(x.get("case_id")) == case_ids[0]), None)
    if not candidate or candidate.get("case_type") != "authentic_revision" \
            or candidate.get("academic_candidate_status") != "eligible":
        return {}
    value = (candidate.get("features") or {}).get("term_count")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return {}
    return {"term_count": value}


def _section_map(report_md: str, outline: Dict[str, Any]) -> Dict[str, str]:
    wanted = [str(x.get("section_id")) for x in outline.get("sections", [])]
    positions = []
    for match in re.finditer(r"^##\s+([^\s]+)(?:\s+.*)?$", report_md, re.MULTILINE):
        section_id = match.group(1).rstrip(".．、")
        if section_id in wanted:
            positions.append((section_id, match.start(), match.end()))
    out = {}
    for i, (section_id, _start, body_start) in enumerate(positions):
        body_end = positions[i + 1][1] if i + 1 < len(positions) else len(report_md)
        out[section_id] = report_md[body_start:body_end].strip()
    return out


def _visible_prose(text: str) -> str:
    """Remove evidence quotations and hidden markers before language checks."""
    quote_label = re.compile(
        r"^(?:[-*]\s+)?(?:\*{1,2})?(?:SOURCE|INITIAL|TARGET|原文|"
        r"源语(?:（SOURCE）|\s*\(SOURCE\))?|初译|改译|译文)"
        r"(?:\*{1,2})?\s*[：:]", re.IGNORECASE)
    lines = [line for line in text.splitlines()
             if not line.lstrip().startswith(">")
             and not quote_label.match(line.strip())]
    return re.sub(r"<!--.*?-->", "", "\n".join(lines), flags=re.DOTALL)


def _has_english_prose_paragraph(text: str) -> bool:
    """Flag sustained English exposition, not terms, titles or quoted evidence."""
    visible = _visible_prose(text)
    for line in visible.splitlines():
        if line.lstrip().startswith("#"):
            continue
        english_words = len(_ENGLISH_WORD.findall(line))
        cjk_chars = len(_CJK_CHAR.findall(line))
        if english_words >= 12 and english_words > cjk_chars:
            return True
    for paragraph in re.split(r"\n\s*\n|\n(?=#{1,6}\s)", visible):
        english_words = len(_ENGLISH_WORD.findall(paragraph))
        cjk_chars = len(_CJK_CHAR.findall(paragraph))
        if english_words >= 12 and english_words > cjk_chars:
            return True
    return False


def _template_heading_records(report_md: str) -> List[Dict[str, Any]]:
    records = []
    for match in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", report_md, re.MULTILINE):
        payload = _norm(match.group(2))
        parts = payload.split(None, 1)
        records.append({
            "level": len(match.group(1)),
            "payload": payload,
            "heading_id": parts[0] if parts else "",
            "title": parts[1] if len(parts) > 1 else payload,
            "start": match.start(),
        })
    return records


def _template_heading_key(value: Any) -> str:
    value = _norm(value).casefold()
    value = re.sub(r"^\d+(?:\.\d+)*[.)、．]?\s*", "", value)
    value = re.sub(r"^第\s*[一二三四五六七八九十百千万]+\s*章\s*", "", value)
    return re.sub(r"[\s:：.。、()（）\[\]【】_\-]+", "", value)


def _template_title_matches(actual: Any, expected: Any) -> bool:
    actual_key = _template_heading_key(actual)
    expected_key = _template_heading_key(expected)
    if actual_key == expected_key:
        return True
    if "xxx" not in expected_key and "×××" not in expected_key:
        return False
    pattern = re.escape(expected_key).replace("xxx", ".+").replace("×××", ".+")
    return bool(re.fullmatch(pattern, actual_key))


def _template_structure_records(contract: Mapping[str, Any]) -> tuple[list, list]:
    structure = contract.get("document_structure") or {}
    chapters = list(structure.get("chapters") or [])
    top_level = int(structure.get("top_level") or 1)
    expected = []
    for chapter in chapters:
        expected.append({
            "section_id": str(chapter.get("section_id") or ""),
            "title": str(chapter.get("title") or ""),
            "role": str(chapter.get("role") or "generic_section"),
            "level": 2,
            "allows_dynamic_subsections": bool(
                chapter.get("allows_dynamic_subsections", False)),
            "required_subsections": [
                dict(item) for item in chapter.get("required_subsections") or []
                if isinstance(item, Mapping)
            ],
        })
    return expected, [top_level]


def validate_template_compliance(
    report_md: str,
    template_contract: Optional[Mapping[str, Any]],
    outline: Optional[Mapping[str, Any]] = None,
    report_artifact: Optional[Mapping[str, Any]] = None,
    selected_cases: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate the generated report against the immutable template contract."""
    if not template_contract:
        return {"status": "not_configured", "issues": [],
                "template_hash": None, "checked": False}
    issues: List[Dict[str, Any]] = []
    identity = template_contract.get("template_identity") or {}
    template_hash = str(identity.get("sha256") or "")
    expected, _ = _template_structure_records(template_contract)
    records = _template_heading_records(report_md)
    chapters = [x for x in records if x.get("level") == 2]
    expected_ids = [x["section_id"] for x in expected]
    actual_ids = [x.get("heading_id") for x in chapters]
    if actual_ids != expected_ids:
        if len(actual_ids) != len(expected_ids):
            issues.append(_issue(
                "template_chapter_count_mismatch",
                f"模板要求 {len(expected_ids)} 个正文一级章节，报告实际有 {len(actual_ids)} 个。",
                suggested_action="恢复模板章节数量与顺序，不要让模型新增或删除一级章节。"))
        for index, item in enumerate(expected):
            if index >= len(chapters):
                issues.append(_issue(
                    "template_missing_chapter",
                    f"报告缺少模板章节“{item['section_id']} {item['title']}”。",
                    section_id=item["section_id"],
                    suggested_action="保留该模板章节，并在证据不足时写明有限解释。"))
                continue
            actual = chapters[index]
            if str(actual.get("heading_id")) != item["section_id"]:
                issues.append(_issue(
                    "template_chapter_order_mismatch",
                    f"模板章节顺序错误：第 {index + 1} 个应为 {item['section_id']}。",
                    section_id=item["section_id"],
                    suggested_action="按 Template Contract 恢复章节顺序。"))
            if not _template_title_matches(actual.get("title"), item["title"]):
                issues.append(_issue(
                    "template_chapter_title_mismatch",
                    f"章节 {item['section_id']} 标题应为“{item['title']}”。",
                    section_id=item["section_id"],
                    suggested_action="恢复模板原始标题，不要改名。"))
    for index, item in enumerate(expected):
        if index >= len(chapters):
            continue
        actual = chapters[index]
        if str(actual.get("heading_id")) == item["section_id"] and not \
                _template_title_matches(actual.get("title"), item["title"]):
            issues.append(_issue(
                "template_chapter_title_mismatch",
                f"章节 {item['section_id']} 标题应为“{item['title']}”。",
                section_id=item["section_id"],
                suggested_action="恢复模板原始标题，不要改名。"))
        next_start = chapters[index + 1]["start"] if index + 1 < len(chapters) \
            else len(report_md)
        body = report_md[actual["start"]:next_start]
        body_records = _template_heading_records(body)
        matched_positions = []
        for subsection in item.get("required_subsections") or []:
            heading_id = str(subsection.get("heading_id") or "")
            title = str(subsection.get("title") or "")
            level = max(3, int(subsection.get("level") or 2) + 1)
            found_any_level = next((record for record in body_records
                                    if str(record.get("heading_id")) == heading_id
                                    and _template_heading_key(record.get("title")) ==
                                    _template_heading_key(title)), None)
            found = found_any_level if found_any_level and \
                found_any_level.get("level") == level else None
            if found_any_level and found is None:
                issues.append(_issue(
                    "template_subsection_level_mismatch",
                    f"小节 {heading_id} {title} 的标题层级不符合模板。",
                    section_id=item["section_id"],
                    suggested_action="恢复模板规定的小节标题层级。"))
            if found_any_level:
                matched_positions.append((heading_id, found_any_level["start"]))
            if not found:
                if not found_any_level:
                    issues.append(_issue(
                        "template_missing_subsection",
                        f"章节 {item['section_id']} 缺少模板小节“{heading_id} {title}”。",
                        section_id=item["section_id"],
                        suggested_action="保留模板小节标题，并在证据不足时保留有限解释。"))
        expected_order = [str(x.get("heading_id") or "")
                          for x in item.get("required_subsections") or []]
        actual_order = [heading_id for heading_id, _position in
                        sorted(matched_positions, key=lambda value: value[1])]
        if actual_order and actual_order != expected_order[:len(actual_order)]:
            issues.append(_issue(
                "template_subsection_order_mismatch",
                f"章节 {item['section_id']} 的模板小节顺序不一致。",
                section_id=item["section_id"],
                suggested_action="按模板规定的小节顺序组织正文。"))
        for record in body_records:
            dynamic_prefixes = [str(x.get("heading_id") or "") + "."
                                for x in item.get("required_subsections") or []
                                if x.get("allows_dynamic_children")]
            chapter_dynamic = item.get("allows_dynamic_subsections") and str(
                record.get("heading_id") or "").startswith(
                    str(item.get("section_id") or "") + ".")
            if record.get("level") > 2 and not any(
                    str(x.get("heading_id")) == str(record.get("heading_id")) and
                    _template_heading_key(x.get("title")) ==
                    _template_heading_key(record.get("title"))
                    for x in item.get("required_subsections") or []) and not any(
                        str(record.get("heading_id") or "").startswith(prefix)
                        for prefix in dynamic_prefixes) and not chapter_dynamic:
                issues.append(_issue(
                    "template_extra_subsection",
                    f"章节 {item['section_id']} 出现未在模板中定义的小节“{record.get('payload')}”。",
                    severity="warning", section_id=item["section_id"],
                    suggested_action="确认该小节确实属于模板；否则删除模型新增的小节。"))
        problem_ids = {
            str(record.get("heading_id"))[len("3.2."):]
            for record in body_records
            if str(record.get("heading_id") or "").startswith("3.2.")}
        solution_ids = {
            str(record.get("heading_id"))[len("3.3."):]
            for record in body_records
            if str(record.get("heading_id") or "").startswith("3.3.")}
        if item.get("role") == "case_analysis" and (problem_ids or solution_ids) \
                and problem_ids != solution_ids:
            issues.append(_issue(
                "template_case_mapping_mismatch",
                "翻译难点与翻译策略的三级标题没有形成一一对应关系。",
                section_id=item["section_id"],
                suggested_action="使 3.2.x 与 3.3.x 使用相同的 x 编号并逐项映射。"))
    if len(chapters) > len(expected):
        for actual in chapters[len(expected):]:
            issues.append(_issue(
                "template_extra_chapter",
                f"报告新增了模板未定义的一级章节“{actual.get('payload')}”。",
                suggested_action="删除未在模板中定义的一级章节。"))

    outline = outline or {}
    if template_hash:
        for artifact_name, artifact in (("outline", outline),
                                        ("report_artifact", report_artifact or {})):
            value = str((artifact or {}).get("template_hash") or "")
            if value and value != template_hash:
                issues.append(_issue(
                    "template_hash_mismatch",
                    f"{artifact_name} 使用的模板哈希与当前模板不一致。",
                    suggested_action="使所有下游产物重新依赖当前模板后再导出。"))
    structure = template_contract.get("document_structure") or {}
    if report_artifact is not None:
        for matter_key, artifact_key in (("front_matter", "front_matter"),
                                          ("back_matter", "back_matter")):
            required_matter = list(structure.get(matter_key) or [])
            actual_matter = list((report_artifact or {}).get(artifact_key) or [])
            required_titles = [_template_heading_key(x.get("title")) for x in required_matter]
            actual_titles = [_template_heading_key(x.get("title")) for x in actual_matter]
            if required_titles != actual_titles:
                issues.append(_issue(
                    "template_matter_mismatch",
                    f"模板{('前置' if matter_key == 'front_matter' else '后置')}部分未完整保留。",
                    suggested_action="由模板渲染器保留固定前后置内容，不要由模型重建。"))
        front_items = {str(x.get("role")): x for x in
                       (report_artifact or {}).get("front_matter") or []}
        for role in ("abstract_zh", "abstract_en"):
            if role in {str(x.get("role")) for x in structure.get("front_matter") or []} \
                    and not str((front_items.get(role) or {}).get("content") or "").strip():
                issues.append(_issue(
                    "template_front_matter_content_missing",
                    f"模板要求的 {role} 尚未生成正文。",
                    suggested_action="只重新生成缺失的摘要前置页。"))
        for role in ("keywords_zh", "keywords_en"):
            if role in {str(x.get("role")) for x in structure.get("front_matter") or []} \
                    and not (front_items.get(role) or {}).get("keywords"):
                issues.append(_issue(
                    "template_front_matter_content_missing",
                    f"模板要求的 {role} 尚未生成。",
                    suggested_action="从已生成摘要与项目主题补齐关键词。"))
        actual_back = list((report_artifact or {}).get("back_matter") or [])
        for required in structure.get("back_matter") or []:
            match = next((item for item in actual_back
                          if str(item.get("role")) == str(required.get("role"))
                          and _template_heading_key(item.get("title")) ==
                          _template_heading_key(required.get("title"))), None)
            if match is not None and not str(match.get("content") or "").strip():
                issues.append(_issue(
                    "template_back_matter_content_missing",
                    f"模板后置部分“{required.get('title')}”没有内容或占位说明。",
                    suggested_action="仅补齐该后置部分；信息缺失时保留需要用户补充。"))

    minimum_cases = int((structure.get("case_requirement") or {}).get(
        "minimum_cases") or 0)
    actual_case_count = len((selected_cases or {}).get("cases") or [])
    if minimum_cases and actual_case_count < minimum_cases:
        issues.append(_issue(
            "template_case_minimum_not_met",
            f"模板至少要求 {minimum_cases} 个例证，当前只有 {actual_case_count} 个。",
            suggested_action="仅重建案例选择与第三章；证据仍不足时保持报告 incomplete。"))

    public_md = report_template.public_report_markdown(
        report_md, (report_artifact or {}).get("case_labels") or {})
    if re.search(r"\b(?:seg-[A-Za-z0-9_.:-]+|finding-[A-Za-z0-9_.:-]+|"
                 r"term-[A-Za-z0-9_.:-]+|claim-[A-Za-z0-9_.:-]+)\b", public_md,
                 re.IGNORECASE):
        issues.append(_issue(
            "template_internal_id_visible", "用户可见报告仍包含内部 evidence ID。",
            suggested_action="保留 hidden provenance marker，并在 preview/DOCX 映射为例[n]。"))
    if re.search(r"\{\{(?:STAT|TERM):[^}]+\}\}", public_md):
        issues.append(_issue(
            "template_unresolved_marker", "用户可见报告仍包含未解析 token。",
            suggested_action="只重建包含未解析 token 的章节。"))
    if re.search(r"基于\s*基于|行星性\s*行星性|全球主义\s*全球主义|"
                 r"\b(84|42|0)[（(]?\s*\1", public_md):
        issues.append(_issue(
            "template_duplicate_rendering", "用户可见报告包含重复词或重复统计值。",
            suggested_action="修复 marker expansion 后只重建受影响章节。"))
    public_records = _template_heading_records(public_md)
    for previous, current in zip(public_records, public_records[1:]):
        if previous["level"] == current["level"] and _template_heading_key(
                previous["title"]) == _template_heading_key(current["title"]):
            issues.append(_issue(
                "template_duplicate_heading", f"标题“{current['payload']}”重复出现。",
                suggested_action="由 assembler 保留唯一 canonical heading。"))
            break

    case_sections = [x for x in (outline.get("sections") or [])
                     if x.get("cases")]
    case_roles = {str(x.get("section_id")): str(x.get("role") or "")
                  for x in (outline.get("sections") or [])}
    if (selected_cases or {}).get("cases") and not any(
            case_roles.get(str(x.get("section_id"))) == "case_analysis"
            for x in case_sections):
        issues.append(_issue(
            "template_case_role_missing",
            "报告有已选案例，但模板没有承担案例分析的明确章节。",
            severity="warning",
            suggested_action="标记 case_analysis 章节；没有该角色时保留警告并请求人工规划。"))
    for section in case_sections:
        if str(section.get("role") or "") != "case_analysis":
            issues.append(_issue(
                "template_case_role_mismatch",
                f"案例被路由到非 case_analysis 章节 {section.get('section_id')}。",
                severity="warning",
                section_id=str(section.get("section_id")),
                suggested_action="将案例只路由到模板角色为 case_analysis 的章节。"))

    status = "fail" if any(x.get("severity") == "error" for x in issues) else \
        "review_required" if any(x.get("type") in {
            "template_case_role_missing", "template_case_role_mismatch"
        } for x in issues) else "pass_with_warnings" if issues else "pass"
    return {
        "status": status,
        "issues": issues,
        "checked": True,
        "template_hash": template_hash,
        "expected_chapters": len(expected),
        "actual_chapters": len(chapters),
    }


def validate_academic_report(
    report_md: str,
    evidence: Dict[str, Any],
    research_model: Dict[str, Any],
    argument_plan: Dict[str, Any],
    selected_cases: Dict[str, Any],
    outline: Dict[str, Any],
    literature_sources_artifact: Optional[Dict[str, Any]] = None,
    literature_evidence_artifact: Optional[Dict[str, Any]] = None,
    literature_claims_artifact: Optional[Dict[str, Any]] = None,
    human_evidence: Optional[Iterable[Dict[str, Any]]] = None,
    synthetic_artifact: Optional[Dict[str, Any]] = None,
    template_contract: Optional[Mapping[str, Any]] = None,
    report_artifact: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate identity, provenance, statistics, citations and structure."""
    issues: List[Dict[str, Any]] = []
    segs = segment_index(evidence)
    if literature_sources_artifact is None:
        literature_sources_artifact = {
            "sources": list(literature_index(evidence).values())}
    literature = literature_evidence.source_index(literature_sources_artifact)
    lit_evidence = literature_evidence.evidence_index(
        literature_evidence_artifact or {})
    lit_claims = literature_evidence.claim_index(literature_claims_artifact or {})
    human_entries = human_evidence or []
    human_index = {x.get("human_evidence_id"): x for x in human_entries}
    claims = {str(c.get("claim_id")): c for c in argument_plan.get("claims", [])}
    rqs = {str(r.get("rq_id")): r for r in research_model.get("research_questions", [])}
    glossary = {str(x.get("id")): x for x in
                evidence.get("project_evidence", {}).get("glossary", [])
                if x.get("id")}
    stats = _statistics(evidence)
    sections = _section_map(report_md, outline)
    canonical_synthetic = synthetic_cases.case_index(synthetic_artifact or {})

    tm_found, tm_reuse = resolve_statistic(stats, "tm_reuse_count")
    if tm_found and tm_reuse == 0:
        strong_tm_inference = re.compile(
            r"(?:机器翻译|大语言模型|\bLLM\b|\bMT\b).{0,50}"
            r"(?:未使用|没有使用|未启用|未发挥|完全依赖人工|全程人工)|"
            r"(?:完全依赖人工|全程人工).{0,50}(?:翻译|机器|模型)",
            re.IGNORECASE)
        for section_id, body in sections.items():
            if strong_tm_inference.search(_visible_prose(body)):
                issues.append(_issue(
                    "unsupported_claim_strength",
                    "TM 复用记录为 0 只能说明当前项目未观察到 TM 复用记录，"
                    "不能证明机器翻译或 LLM 未使用，也不能证明全程依赖人工。",
                    section_id=section_id,
                    suggested_action="区分 Translation Memory、Machine Translation 与 LLM，"
                                     "将结论降为‘未观察到 TM 复用记录’。"))

    if not report_md.strip():
        issues.append(_issue("empty_report", "报告内容为空。"))

    constraints = research_model.get("report_constraints") or \
        outline.get("report_constraints") or {}
    required_chapters = thesis_constraints.chapter_index(constraints)
    required_ids = list((constraints.get("document_scope") or {}).get(
        "body_chapters") or required_chapters)
    outline_by_id = {str(x.get("section_id")): x for x in outline.get("sections", [])}
    if required_chapters and list(outline_by_id) != required_ids:
        issues.append(_issue(
            "institutional_chapter_structure_mismatch",
            f"正文提纲必须依次采用已配置的 section：{', '.join(required_ids)}。",
            suggested_action="按 report_constraints 重新生成 academic-outline。"))
    for section_id, chapter in required_chapters.items():
        planned = outline_by_id.get(section_id)
        if not planned:
            continue
        if _norm(planned.get("title")) != _norm(chapter.get("title")):
            issues.append(_issue(
                "institutional_chapter_title_mismatch",
                f"第 {section_id} 章标题应为“{chapter.get('title')}”。",
                section_id=section_id,
                suggested_action="恢复 report_constraints 中配置的章节标题。"))
        body = sections.get(section_id) or ""
        for subsection in chapter.get("required_subsections") or []:
            heading_id = str(subsection.get("heading_id") or "")
            title = str(subsection.get("title") or "")
            heading_level = int(subsection.get("level") or 2)
            pattern = re.compile(
                r"^" + re.escape("#" * (heading_level + 1)) + r"\s+" +
                re.escape(heading_id) + r"(?:\s+|[.．、])" +
                re.escape(title) + r"\s*$", re.MULTILINE)
            if body and not pattern.search(body):
                issues.append(_issue(
                    "missing_institutional_subsection",
                    f"第 {section_id} 章缺少规定小节“{heading_id} {title}”。",
                    section_id=section_id,
                    suggested_action="按 academic-outline.required_subsections 补写该小节。"))

    body_language = (constraints.get("body_language") or {}).get("language")
    if body_language == "zh-CN" and _has_english_prose_paragraph(report_md):
        issues.append(_issue(
            "thesis_body_language_mismatch",
            "报告正文包含不符合当前语言配置的连续英文论述段落。",
            suggested_action="按 report_constraints 中的语言配置调整论述文本。"))

    configured_ids = list(required_chapters)
    configured_template = bool((constraints.get("template") or {}).get("configured"))
    role_by_id = {str(x.get("section_id")): str(x.get("role") or "")
                  for x in constraints.get("chapters") or []}
    role_id = lambda role: next((section_id for section_id, value in role_by_id.items()
                                 if value == role), "")
    legacy_fallback = configured_ids[-1] if configured_ids and not configured_template else ""
    conclusion_id = str((constraints.get("research_question_policy") or {}).get(
        "answer_in_section") or role_id("conclusion_reflection") or legacy_fallback)
    analysis_id = str((constraints.get("research_question_policy") or {}).get(
        "develop_in_section") or role_id("case_analysis") or legacy_fallback)
    conclusion = sections.get(conclusion_id, "") if required_chapters else ""
    conclusion_case_ids = set(_SEGMENT_REF.findall(conclusion)) | set(
        _SYNTHETIC_CASE_ID.findall(conclusion))
    analysis_body = sections.get(analysis_id, "") if required_chapters else ""
    analysis_case_ids = set(_SEGMENT_REF.findall(analysis_body)) | set(
        _SYNTHETIC_CASE_ID.findall(analysis_body))
    new_conclusion_cases = conclusion_case_ids - analysis_case_ids
    if new_conclusion_cases:
        issues.append(_issue(
            "conclusion_introduces_case_evidence",
            "结论部分不得首次引入案例证据：" +
            "、".join(sorted(new_conclusion_cases)) + "。",
            section_id=conclusion_id,
            suggested_action="删除新增案例，只综合前文已经建立的案例发现。"))

    # Literature source -> exact block -> literature evidence -> literature
    # claim -> global claim integrity.  Source existence alone is never support.
    for source_id, source in literature.items():
        citation = source.get("citation_metadata") or source.get("citation") or {}
        if citation.get("title") and _norm(citation.get("title")) != _norm(source.get("title")):
            issues.append(_issue(
                "literature_metadata_mismatch",
                f"来源 {source_id} 的 citation title 与注册题名不一致。",
                evidence_id=source_id))
        if citation.get("year") and str(citation.get("year")) != str(source.get("year")):
            issues.append(_issue(
                "literature_metadata_mismatch",
                f"来源 {source_id} 的 citation year 与注册年份不一致。",
                evidence_id=source_id))
        citation_authors = citation.get("authors")
        if citation_authors and [_norm(x) for x in citation_authors] != [
                _norm(x) for x in source.get("authors") or []]:
            issues.append(_issue(
                "literature_metadata_mismatch",
                f"来源 {source_id} 的 citation authors 与注册作者不一致。",
                evidence_id=source_id))
        block_hashes = []
        for block in source.get("content_blocks") or []:
            identity = {
                "source_id": source_id, "location": block.get("location"),
                "text": block.get("text"), "provenance": block.get("provenance"),
                "origin_id": block.get("origin_id"),
            }
            expected_block_hash = stable_hash(identity)
            expected_block_id = "LB-" + expected_block_hash[:16]
            if block.get("content_hash") != expected_block_hash or block.get(
                    "block_id") != expected_block_id:
                issues.append(_issue(
                    "literature_source_block_hash_mismatch",
                    f"来源 {source_id} 的 block {block.get('block_id')} 哈希或身份无效。",
                    evidence_id=block.get("block_id")))
            block_hashes.append({
                "block_id": block.get("block_id"),
                "content_hash": block.get("content_hash"),
            })
        if block_hashes or source.get("source_file_hash"):
            expected_source_hash = stable_hash({
                "binary_hash": source.get("source_file_hash"), "blocks": block_hashes})
            if source.get("content_hash") != expected_source_hash:
                issues.append(_issue(
                    "literature_source_content_hash_mismatch",
                    f"来源 {source_id} 的内容哈希与保存 block/file snapshot 不一致。",
                    evidence_id=source_id))

    for evidence_id, item in lit_evidence.items():
        source_id = str(item.get("source_id") or "")
        source = literature.get(source_id)
        if not source:
            issues.append(_issue(
                "literature_evidence_source_missing",
                f"文献证据 {evidence_id} 指向不存在的来源 {source_id}。",
                evidence_id=evidence_id))
            continue
        if item.get("source_content_hash") != source.get("content_hash"):
            issues.append(_issue(
                "literature_source_hash_mismatch",
                f"文献证据 {evidence_id} 的来源内容哈希与来源快照不一致。",
                evidence_id=evidence_id))
        if item.get("evidence_type") == "metadata_only":
            continue
        block_id = item.get("source_block_id")
        blocks = {x.get("block_id"): x for x in source.get("content_blocks") or []}
        block = blocks.get(block_id)
        if not block:
            issues.append(_issue(
                "invalid_literature_location",
                f"文献证据 {evidence_id} 的 source block/location 不存在。",
                evidence_id=evidence_id))
            continue
        if block.get("location") != item.get("location"):
            issues.append(_issue(
                "invalid_literature_location",
                f"文献证据 {evidence_id} 的精确位置与来源快照不一致。",
                evidence_id=evidence_id))
        if str(block.get("text") or "") != str(item.get("evidence_text") or ""):
            issues.append(_issue(
                "literature_evidence_text_mismatch",
                f"文献证据 {evidence_id} 的逐字文本与来源快照不一致。",
                evidence_id=evidence_id))
        expected_hash = stable_hash({k: v for k, v in item.items() if k != "content_hash"})
        if item.get("content_hash") != expected_hash:
            issues.append(_issue(
                "literature_evidence_hash_mismatch",
                f"文献证据 {evidence_id} 的内容哈希无效。",
                evidence_id=evidence_id))

    for literature_claim_id, claim in lit_claims.items():
        source_id = str(claim.get("source_id") or "")
        if source_id not in literature:
            issues.append(_issue(
                "literature_claim_source_missing",
                f"文献主张 {literature_claim_id} 指向不存在的来源 {source_id}。",
                evidence_id=literature_claim_id))
        support_ids = [str(x) for x in claim.get("supporting_evidence_ids") or []]
        if not support_ids:
            issues.append(_issue(
                "literature_claim_without_evidence",
                f"文献主张 {literature_claim_id} 没有逐字证据支持。",
                evidence_id=literature_claim_id))
        for evidence_id in support_ids:
            item = lit_evidence.get(evidence_id)
            if not item:
                issues.append(_issue(
                    "literature_claim_unknown_evidence",
                    f"文献主张 {literature_claim_id} 引用未知证据 {evidence_id}。",
                    evidence_id=evidence_id))
            elif item.get("source_id") != source_id or not item.get("eligible_for_claim"):
                issues.append(_issue(
                    "literature_claim_evidence_mismatch",
                    f"文献主张 {literature_claim_id} 与证据 {evidence_id} 的来源或资格不匹配。",
                    evidence_id=evidence_id))
        expected_claim_hash = stable_hash(
            {k: v for k, v in claim.items() if k != "content_hash"})
        if claim.get("content_hash") != expected_claim_hash:
            issues.append(_issue(
                "literature_claim_hash_mismatch",
                f"文献主张 {literature_claim_id} 的内容哈希无效。",
                evidence_id=literature_claim_id))

    for global_claim_id, global_claim in claims.items():
        literature_claim_ids = [str(x) for x in global_claim.get("literature_claims") or []]
        literature_evidence_ids = [str(x) for x in global_claim.get("literature_evidence") or []]
        for literature_claim_id in literature_claim_ids:
            if literature_claim_id not in lit_claims:
                issues.append(_issue(
                    "global_claim_unknown_literature_claim",
                    f"全局论点 {global_claim_id} 引用未知文献主张 {literature_claim_id}。",
                    claim_id=global_claim_id, evidence_id=literature_claim_id))
        allowed_support = {
            evidence_id for literature_claim_id in literature_claim_ids
            for evidence_id in (lit_claims.get(literature_claim_id) or {}).get(
                "supporting_evidence_ids") or []
        }
        for evidence_id in literature_evidence_ids:
            if evidence_id in literature:
                issues.append(_issue(
                    "argument_plan_source_id_without_grounding",
                    f"全局论点 {global_claim_id} 仅引用 paper/source ID {evidence_id}，没有文献主张与逐字证据。",
                    claim_id=global_claim_id, evidence_id=evidence_id))
            elif evidence_id not in lit_evidence:
                issues.append(_issue(
                    "global_claim_unknown_literature_evidence",
                    f"全局论点 {global_claim_id} 引用未知文献证据 {evidence_id}。",
                    claim_id=global_claim_id, evidence_id=evidence_id))
            elif evidence_id not in allowed_support:
                issues.append(_issue(
                    "global_claim_literature_support_mismatch",
                    f"全局论点 {global_claim_id} 的证据 {evidence_id} 不属于其文献主张。",
                    claim_id=global_claim_id, evidence_id=evidence_id))
        support_category = str(global_claim.get("support_category") or "")
        if support_category in {"literature_supported", "mixed_evidence"} and not (
                literature_claim_ids and literature_evidence_ids):
            issues.append(_issue(
                "global_claim_missing_literature_grounding",
                f"全局论点 {global_claim_id} 标记为 {support_category}，但缺少文献主张或逐字证据。",
                claim_id=global_claim_id))

    for seg_id in sorted(set(_SEGMENT_REF.findall(report_md))):
        if seg_id not in segs:
            issues.append(_issue(
                "invented_segment_id", f"不存在的段落引用：{seg_id}",
                evidence_id=seg_id, suggested_action="删除引用或改用证据库中的 segment_id。"))
    planned_case_ids = {str(x.get("case_id")) for x in selected_cases.get("cases", [])}
    for section in outline.get("sections", []):
        planned_case_ids.update(str(x) for x in section.get("cases") or [])
    for seg_id in sorted(set(_SEGMENT_REF.findall(report_md))):
        if seg_id not in planned_case_ids:
            issues.append(_issue(
                "unplanned_segment_reference",
                f"正文引用了未纳入分节案例计划的段落：{seg_id}。",
                evidence_id=seg_id,
                suggested_action="删除该引用，或先在案例选择与提纲中纳入该案例。"))

    selected_by_id = {str(x.get("case_id")): x
                      for x in selected_cases.get("cases", [])}
    for kind, case_id, quote in _QUOTE.findall(report_md):
        selected_case = selected_by_id.get(case_id) or {}
        seg_id = str(selected_case.get("source_segment_id") or case_id)
        if seg_id not in segs:
            continue
        expected_key = {"SOURCE": "source", "INITIAL": "initial_target",
                        "TARGET": "final_target"}[kind]
        expected = segs[seg_id].get(expected_key)
        if _norm(quote) != _norm(expected):
            issues.append(_issue(
                "wrong_initial_translation" if kind == "INITIAL"
                else "wrong_final_translation" if kind == "TARGET"
                else "wrong_segment_quote",
                f"{kind} 引文与所选案例的保存文本不一致。",
                evidence_id=case_id,
                suggested_action="逐字使用学术证据库中的原文或终译。"))

    selected_synthetic = {
        str(x.get("case_id")): x for x in selected_cases.get("cases", [])
        if x.get("case_type") == "synthetic_contrast"}
    selected_decisions = {
        str(x.get("case_id")): x for x in selected_cases.get("cases", [])
        if x.get("case_type") == "translation_decision"}
    synthetic_quotes = _SYNTHETIC_QUOTE.findall(report_md)
    for kind, case_id, quote in synthetic_quotes:
        case = canonical_synthetic.get(case_id) or selected_synthetic.get(case_id)
        if not case:
            issues.append(_issue(
                "unknown_synthetic_case", f"不存在的合成案例：{case_id}",
                evidence_id=case_id))
            continue
        expected = {
            "SYNTHETIC_SOURCE": case.get("source_text"),
            "SIMULATED": case.get("synthetic_baseline", {}).get("text"),
            "OPTIMIZED": case.get("optimized_translation", {}).get("text"),
        }[kind]
        if _norm(quote) != _norm(expected):
            issues.append(_issue(
                "wrong_synthetic_case_quote",
                f"{kind} 引文与 {case_id} 的合成案例 artifact 不一致。",
                evidence_id=case_id,
                suggested_action="逐字使用 synthetic case artifact 中对应字段。"))

    def stat_matches(rendered: str, expected: Any) -> bool:
        expected_text = _value_text(expected)
        if isinstance(expected, (dict, list, tuple)):
            try:
                return json.loads(rendered) == json.loads(expected_text)
            except (TypeError, ValueError):
                return False
        return rendered.replace(",", "") == expected_text.replace(",", "")

    section_spans = []
    headings = list(re.finditer(
        r"^##\s+([^\s]+)(?:\s+.*)?$", report_md, re.MULTILINE))
    for index, heading in enumerate(headings):
        section_id = heading.group(1).rstrip(".．、")
        section_end = headings[index + 1].start() \
            if index + 1 < len(headings) else len(report_md)
        section_spans.append((heading.end(), section_end, section_id))

    def scoped_stats(position: int) -> Dict[str, Any]:
        for start, end, section_id in section_spans:
            if start <= position < end:
                scoped = dict(stats)
                scoped.update(case_statistic_overrides(
                    outline_by_id.get(section_id) or {}, selected_cases, evidence))
                return scoped
        return stats

    for match in _STAT.finditer(report_md):
        rendered, key = match.groups()
        available_stats = scoped_stats(match.start())
        found, expected = resolve_statistic(available_stats, key)
        if not found or expected is None:
            issues.append(_issue(
                "unknown_project_statistic", f"未知项目统计：{key}",
                evidence_id=f"metric:{key}", suggested_action="改用 evidence.statistics 中的指标。"))
        elif not stat_matches(rendered, expected):
            issues.append(_issue(
                "wrong_project_statistic",
                f"统计 {key} 报告为 {rendered}，证据值为 {_value_text(expected)}。",
                evidence_id=f"metric:{key}", suggested_action="使用 {{STAT:%s}} 占位符。" % key))
    for key in sorted(set(_STAT_TOKEN.findall(report_md))):
        issues.append(_issue(
            "unresolved_statistic_token",
            f"报告仍含无法从当前项目证据解析的统计占位符：{key}。",
            evidence_id=f"metric:{key}",
            suggested_action=("确认该指标存在于 evidence.statistics 或明确绑定的案例证据中；"
                              "无法解析时不得填入估计值。")))

    # Conservative check for numeric claims explicitly framed as project totals.
    project_terms = re.compile(r"本(?:项目|次|文)|全文|段落|审校|复用|术语|发现")
    for line in report_md.splitlines():
        if line.lstrip().startswith(">"):
            continue
        if project_terms.search(line) and re.search(r"\d+(?:\.\d+)?(?:%|段|条|处|次)", line) \
                and "<!--stat:" not in line:
            issues.append(_issue(
                "unmarked_project_statistic",
                f"项目数字缺少统计来源标记：{_norm(line)[:100]}",
                severity="warning",
                suggested_action="改用 {{STAT:metric_name}}，或明确说明该数字不是项目统计。"))

    for evidence_id, quote in _LIT_QUOTE.findall(report_md):
        item = lit_evidence.get(evidence_id)
        if not item:
            issues.append(_issue(
                "unknown_literature_quote_evidence",
                f"文献直接引语引用未知证据 {evidence_id}。",
                evidence_id=evidence_id))
        elif _norm(quote) != _norm(item.get("evidence_text")):
            issues.append(_issue(
                "literature_quote_mismatch",
                f"文献直接引语与 {evidence_id} 的保存文本不一致。",
                evidence_id=evidence_id))
    for literature_claim_id in sorted(set(_LIT_CLAIM.findall(report_md))):
        if literature_claim_id not in lit_claims:
            issues.append(_issue(
                "unknown_literature_claim_marker",
                f"正文包含未知文献主张 marker：{literature_claim_id}。",
                evidence_id=literature_claim_id))
    for evidence_id in sorted(set(_LIT_EVIDENCE.findall(report_md))):
        if evidence_id not in lit_evidence:
            issues.append(_issue(
                "unknown_literature_evidence_marker",
                f"正文包含未知文献证据 marker：{evidence_id}。",
                evidence_id=evidence_id))

    citation_ids = {a or b for a, b in _CITATION.findall(report_md)}
    for source_id in sorted(citation_ids):
        source = literature.get(source_id)
        if not source:
            issues.append(_issue(
                "unknown_literature_citation", f"文献注册表中不存在：{source_id}",
                evidence_id=source_id, suggested_action="删除或先登记并核验该来源。"))
        elif not source.get("citation_allowed") or source.get(
                "allowed_citation_status") == "not_allowed":
            issues.append(_issue(
                "uncitable_literature_source",
                f"来源 {source_id} 的状态不允许正式引用。",
                evidence_id=source_id, suggested_action="核验来源后更新 citation_allowed。"))
        else:
            marker_pattern = (r"(?:\[@" + re.escape(source_id) + r"\]|<!--cite:"
                              + re.escape(source_id) + r"-->)")
            for marker in re.finditer(marker_pattern, report_md):
                line_start = report_md.rfind("\n", 0, marker.start()) + 1
                line_end = report_md.find("\n", marker.end())
                line = report_md[line_start:line_end if line_end >= 0 else len(report_md)]
                visible_line = re.sub(r"\[@[^\]]+\]|<!--.*?-->", "", line)
                years = set(re.findall(r"(?:19|20)\d{2}", visible_line))
                registered_year = str(source.get("year") or "")
                if years and registered_year and registered_year not in years:
                    issues.append(_issue(
                        "citation_metadata_mismatch",
                        f"引用 {source_id} 所在句年份 {sorted(years)} 与注册年份 {registered_year} 不一致。",
                        evidence_id=source_id,
                        suggested_action="按 literature registry 修正作者—年份信息。"))
                visible_author_year = _FORMAL_AUTHOR_YEAR.search(visible_line)
                authors = source.get("authors") or []
                if visible_author_year and authors:
                    author = str(authors[0]).strip()
                    tokens = [x.casefold() for x in author.split() if x]
                    if tokens and not any(x in visible_line.casefold()
                                          for x in (tokens[0], tokens[-1])):
                        issues.append(_issue(
                            "citation_metadata_mismatch",
                            f"引用 {source_id} 所在句作者与注册作者 {author} 不一致。",
                            evidence_id=source_id,
                            suggested_action="按 literature registry 修正作者—年份信息。"))
    for match in _FORMAL_AUTHOR_YEAR.finditer(report_md):
        line_start = report_md.rfind("\n", 0, match.start()) + 1
        line_end = report_md.find("\n", match.end())
        line = report_md[line_start:line_end if line_end >= 0 else len(report_md)]
        if "[@" not in line:
            issues.append(_issue(
                "unregistered_formal_citation",
                f"正式作者—年份引用没有 registry key：{match.group(0)}",
                evidence_id=match.group(0),
                suggested_action="使用 [@source_id] 绑定文献注册表，或删除未核验引用。"))

    for human_id in sorted(set(_HUMAN_EV.findall(report_md))):
        entry = human_index.get(human_id)
        if not entry:
            issues.append(_issue(
                "unknown_human_evidence", f"正文引用未知人类证据：{human_id}。",
                evidence_id=human_id,
                suggested_action="删除引用，或先登记对应人类证据。"))
        elif entry.get("status") not in ("user_confirmed",):
            issues.append(_issue(
                "unusable_human_evidence",
                f"人类证据 {human_id} 状态为 {entry.get('status')}，不可用于写作。",
                evidence_id=human_id,
                suggested_action="修正/撤回该证据，或从正文删除其引用。"))
        elif entry.get("conflict_status") == "contradicted":
            issues.append(_issue(
                "conflicted_human_evidence",
                f"人类证据 {human_id} 与项目记录矛盾，需人工复核后才能引用。",
                evidence_id=human_id))
    for claim in claims.values():
        for human_id in claim.get("human_evidence_ids") or []:
            if human_id not in human_index:
                issues.append(_issue(
                    "argument_unknown_human_evidence",
                    f"论点 {claim['claim_id']} 引用未知人类证据 {human_id}。",
                    claim_id=claim["claim_id"], evidence_id=human_id))
            elif human_index[human_id].get("status") not in ("user_confirmed",):
                issues.append(_issue(
                    "argument_unusable_human_evidence",
                    f"论点 {claim['claim_id']} 引用不可用的人类证据 {human_id}。",
                    claim_id=claim["claim_id"], evidence_id=human_id))

    for entry_id in sorted(set(_TERM.findall(report_md))):
        if entry_id not in glossary:
            issues.append(_issue(
                "unknown_terminology_decision", f"未知术语决策：{entry_id}",
                evidence_id=entry_id, suggested_action="改用已保存的 glossary entry id。"))
    if "{{TERM:" in report_md:
        issues.append(_issue("unresolved_term_token", "报告仍含未解析的术语占位符。"))

    for plan_section in outline.get("sections", []):
        section_id = str(plan_section.get("section_id"))
        body = sections.get(section_id)
        if body is None:
            issues.append(_issue(
                "missing_required_section", f"缺少提纲要求的章节 {section_id}。",
                section_id=section_id, suggested_action="按 academic-outline 重写该节。"))
            continue
        min_chars = int(plan_section.get("minimum_chars") or 120)
        visible = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
        if len(re.sub(r"\s+", "", visible)) < min_chars:
            issues.append(_issue(
                "section_too_short", f"章节 {section_id} 未达到完整性下限 {min_chars} 字符。",
                severity="warning", section_id=section_id,
                suggested_action="补足论证，而不是机械扩写。"))
        for claim_id in plan_section.get("claims") or []:
            if claim_id not in claims:
                issues.append(_issue(
                    "outline_unknown_claim", f"章节 {section_id} 引用未知论点 {claim_id}。",
                    section_id=section_id, claim_id=claim_id))
            elif f"<!--claim:{claim_id}-->" not in body:
                issues.append(_issue(
                    "missing_planned_claim", f"章节 {section_id} 未落实论点 {claim_id}。",
                    section_id=section_id, claim_id=claim_id,
                    suggested_action="围绕该 claim 与其证据补写或调整提纲。"))
        for case_id in plan_section.get("cases") or []:
            if case_id not in segs and case_id not in selected_synthetic \
                    and case_id not in selected_decisions:
                issues.append(_issue(
                    "outline_unknown_case", f"章节 {section_id} 引用未知案例 {case_id}。",
                    section_id=section_id, evidence_id=case_id))
            elif case_id not in body:
                planned = [str(x) for x in plan_section.get("cases") or []]
                used = sum(1 for x in planned if x in body)
                severity = "error" if used == 0 else "warning"
                issues.append(_issue(
                    "missing_selected_case", f"章节 {section_id} 未使用已选案例 {case_id}。",
                    section_id=section_id, evidence_id=case_id,
                    severity=severity,
                    suggested_action="使用该案例，或重新规划案例选择；"
                                     "若该节已展开部分案例，可删除未展开案例的计划。"))
        for rq_id in plan_section.get("research_questions") or []:
            if rq_id not in rqs:
                issues.append(_issue(
                    "outline_unknown_research_question",
                    f"章节 {section_id} 引用未知研究问题 {rq_id}。",
                    section_id=section_id))
            elif f"<!--rq:{rq_id}-->" not in body:
                issues.append(_issue(
                    "missing_research_question_link",
                    f"章节 {section_id} 未标明对研究问题 {rq_id} 的回应。",
                    severity="warning", section_id=section_id))

        planned_lit_claims = {str(x) for x in plan_section.get(
            "literature_claims") or []}
        planned_lit_evidence = {str(x) for x in plan_section.get(
            "literature_evidence") or []}
        if plan_section.get("literature") and not (
                planned_lit_claims and planned_lit_evidence):
            issues.append(_issue(
                "outline_source_id_without_grounding",
                f"章节 {section_id} 只规划了 paper/source ID，没有文献主张与逐字证据。",
                section_id=section_id))
        for literature_claim_id in planned_lit_claims:
            if literature_claim_id not in lit_claims:
                issues.append(_issue(
                    "outline_unknown_literature_claim",
                    f"章节 {section_id} 引用未知文献主张 {literature_claim_id}。",
                    section_id=section_id, evidence_id=literature_claim_id))
            elif f"<!--lit-claim:{literature_claim_id}-->" not in body:
                issues.append(_issue(
                    "missing_planned_literature_claim",
                    f"章节 {section_id} 未落实文献主张 {literature_claim_id}。",
                    section_id=section_id, evidence_id=literature_claim_id))
        for evidence_id in planned_lit_evidence:
            if evidence_id not in lit_evidence:
                issues.append(_issue(
                    "outline_unknown_literature_evidence",
                    f"章节 {section_id} 引用未知文献证据 {evidence_id}。",
                    section_id=section_id, evidence_id=evidence_id))
            elif f"<!--lit-evidence:{evidence_id}-->" not in body and not re.search(
                    r"\[LITERATURE\s+" + re.escape(evidence_id) + r"\]", body):
                issues.append(_issue(
                    "missing_planned_literature_evidence",
                    f"章节 {section_id} 未使用文献证据 {evidence_id}。",
                    section_id=section_id, evidence_id=evidence_id))
        planned_sources = {str(x) for x in plan_section.get(
            "literature_sources") or []}
        planned_sources.update(
            str(lit_evidence[x].get("source_id")) for x in planned_lit_evidence
            if x in lit_evidence)
        used_sources = {a or b for a, b in _CITATION.findall(body)}
        for source_id in sorted(used_sources - planned_sources):
            issues.append(_issue(
                "section_literature_outside_plan",
                f"章节 {section_id} 引用了计划外文献 {source_id}。",
                section_id=section_id, evidence_id=source_id,
                suggested_action="删除该引用，或先在论证计划中绑定文献主张与证据。"))
        for literature_claim_id in set(_LIT_CLAIM.findall(body)) - planned_lit_claims:
            issues.append(_issue(
                "section_literature_claim_outside_plan",
                f"章节 {section_id} 使用了计划外文献主张 {literature_claim_id}。",
                section_id=section_id, evidence_id=literature_claim_id))
        for evidence_id in set(_LIT_EVIDENCE.findall(body)) - planned_lit_evidence:
            issues.append(_issue(
                "section_literature_evidence_outside_plan",
                f"章节 {section_id} 使用了计划外文献证据 {evidence_id}。",
                section_id=section_id, evidence_id=evidence_id))

    selected_ids = {str(x.get("case_id")) for x in selected_cases.get("cases", [])}
    authentic_ids = {str(x.get("case_id")) for x in selected_cases.get("cases", [])
                     if x.get("case_type") in {None, "", "authentic_revision"}}
    decision_ids = {str(x.get("case_id")) for x in selected_cases.get("cases", [])
                    if x.get("case_type") == "translation_decision"}
    synthetic_ids = {str(x.get("case_id")) for x in selected_cases.get("cases", [])
                     if x.get("case_type") == "synthetic_contrast"}
    case_section_id = next((str(item.get("section_id"))
                            for item in outline.get("sections") or []
                            if item.get("role") == "case_analysis"), None)
    case_markers = _CASE_MARKER.findall(report_md)
    structured_nodes = list((report_artifact or {}).get("case_nodes") or [])
    has_structured_case_graph = report_artifact is not None \
        and "case_nodes" in (report_artifact or {})
    if has_structured_case_graph:
        structured_ids = [str(node.get("case_id") or "") for node in structured_nodes
                          if node.get("type") == "case_example"]
        case_presentations = [
            str(node.get("case_id")) for node in structured_nodes
            if node.get("type") == "case_example" and node.get("visible")
            and node.get("provenance_bound") and str(node.get("case_id")) in case_markers
            and f"<!--case:{node.get('case_id')}-->" in str(node.get("content") or "")]
        visible_count = len(_VISIBLE_CASE_EXAMPLE.findall(report_md))
        if visible_count > len([
                node for node in structured_nodes if node.get("visible")]):
            issues.append(_issue(
                "unbound_visible_case_example",
                f"报告有 {visible_count} 个可见例证，但只有 "
                f"{len([node for node in structured_nodes if node.get('visible')])} 个"
                "形成 structured case node。",
                section_id=case_section_id,
                suggested_action="只定点修复未绑定例证，禁止用重复案例补数。"))
        for case_id in sorted(set(case_markers) - set(case_presentations)):
            issues.append(_issue(
                "orphan_case_marker", f"案例 marker {case_id} 没有对应的可见结构化例证。",
                section_id=case_section_id, evidence_id=case_id,
                suggested_action="将 marker、可见例证和 structured node 由同一 assembly 节点生成。"))
    else:
        structured_ids = []
        marked_ids = set(case_markers)
        source_quote_ids = [
            case_id for kind, case_id, _quote in _QUOTE.findall(report_md)
            if kind == "SOURCE" and case_id not in marked_ids]
        source_quote_ids.extend(
            case_id for kind, case_id, _quote in _SYNTHETIC_QUOTE.findall(report_md)
            if kind == "SYNTHETIC_SOURCE" and case_id not in marked_ids)
        case_presentations = [*case_markers, *source_quote_ids]
        structured_ids = list(case_presentations)
    bound_ids = set(case_presentations) & selected_ids
    missing_case_ids = sorted(selected_ids - bound_ids)
    if selected_ids and (
            len(structured_ids) != len(selected_ids) or len(bound_ids) != len(selected_ids)):
        issue = _issue(
            "case_presentation_count_mismatch",
            f"报告 selected={len(selected_ids)}、structured={len(structured_ids)}、"
            f"provenance-safe visible={len(bound_ids)}。",
            section_id=case_section_id,
            suggested_action="只重建缺失案例所属的 case_analysis subsection。")
        issue.update({
            "selected_case_count": len(selected_ids),
            "structured_case_node_count": len(structured_ids),
            "unique_provenance_bound_visible_case_count": len(bound_ids),
            "missing_case_ids": missing_case_ids,
        })
        issues.append(issue)
    for case_id, count in Counter(structured_ids).items():
        if case_id in selected_ids and count > 1:
            issues.append(_issue(
                "duplicate_selected_case_presentation",
                f"同一案例 {case_id} 被包装成 {count} 个用户可见例证。",
                section_id=case_section_id, evidence_id=case_id,
                suggested_action="同一案例只保留一个例[n]；不同分析维度合并到该例分析中。"))
    for node in structured_nodes:
        case_id = str(node.get("case_id") or "")
        if case_id in decision_ids and _DECISION_AS_REVISION.search(
                str(node.get("content") or node.get("analysis") or "")):
            issues.append(_issue(
                "translation_decision_presented_as_revision",
                f"translation_decision {case_id} 被表述成历史初译或改译过程。",
                section_id=case_section_id, evidence_id=case_id,
                suggested_action="改用‘原文—译文—翻译难点—译法分析’，不得虚构修订历史。"))
    case_heading_ids = re.findall(
        r"^\s*(?:[-*]\s*)?(?:\*{1,2})?案例[^\n：:]*?"
        r"\b((?:seg-[A-Za-z0-9_-]+-\d{4,}|TD-\d{4,}|SC-\d{4,}))\b",
        report_md, re.MULTILINE | re.IGNORECASE)
    for case_id, count in Counter(case_heading_ids).items():
        if case_id in selected_ids and count > 1:
            issues.append(_issue(
                "duplicate_selected_case_presentation",
                f"同一案例 {case_id} 被包装成 {count} 个用户可见例证。",
                section_id=case_section_id, evidence_id=case_id,
                suggested_action="同一案例只保留一个例[n]；不同分析维度合并到该例分析中。"))
    selected_count = len(authentic_ids)
    if selected_cases.get("selection_policy") in {"mixed", "synthetic_only"} \
            and selected_cases.get("synthetic_pipeline_status") == "failed":
        issues.append(_issue(
            "synthetic_pipeline_unavailable",
            "合成案例 provider/stage 运行失败；当前报告只能使用已验证的真实案例。",
            severity="warning",
            suggested_action="恢复 provider 后重新运行 synthetic stages。"))
    if selected_cases.get("selection_policy") == "synthetic_only" and not synthetic_ids:
        issues.append(_issue(
            "synthetic_only_without_eligible_cases",
            "已请求仅使用合成案例，但没有通过完整资格门禁的合成案例。",
            suggested_action="恢复生成/验证阶段或改用 mixed/authentic_only；不得绕过资格门禁。"))
    if "selection_status" in selected_cases:
        preferred = int(selected_cases.get("preferred_core_case_count")
                        or selected_cases.get("requested_case_count") or 3)
        minimum = int(selected_cases.get("minimum_core_case_count") or min(2, preferred))
        expected_status = (
            "sufficient_revision_cases" if selected_count >= preferred else
            "two_case_fallback" if selected_count >= minimum else
            "insufficient_revision_cases")
        recorded_authentic_status = selected_cases.get(
            "authentic_selection_status", selected_cases.get("selection_status"))
        if recorded_authentic_status == "not_applicable":
            expected_status = "not_applicable"
        elif recorded_authentic_status != expected_status:
            issues.append(_issue(
                "case_count_status_mismatch",
                "案例数量与选择产物中的 case-count status 不一致。",
                suggested_action="重新运行案例选择，不要手工覆盖案例数量状态。"))
        if expected_status == "insufficient_revision_cases":
            issues.append(_issue(
                "revision_evidence_scarcity",
                f"只有 {selected_count} 个合格修订案例，少于最低要求 {minimum} 个。",
                severity="warning",
                suggested_action="保留真实修订案例，并用明确标注的 translation_decision "
                                 "或 synthetic_contrast 补充分析；不得伪造改译历史。"))
        elif expected_status == "two_case_fallback":
            markers = set(_CASE_COUNT_POLICY.findall(report_md))
            if "two_case_fallback" not in markers:
                issues.append(_issue(
                    "missing_revision_evidence_scarcity_disclosure",
                    "双案例章节未披露修订证据稀缺及不补造第三案例的边界。",
                    suggested_action=(
                        "在案例分析或结论中说明仅有两个合格核心修订案例，并保留 "
                        "<!--case-count-policy:two_case_fallback-->。")))
            if _THREE_CORE_CASES.search(report_md):
                issues.append(_issue(
                    "wrong_core_case_count_claim",
                    "正文声称使用三个案例，但合格核心修订案例只有两个。",
                    suggested_action="改为双案例结构，并披露第三案例未以弱证据补位。"))
    if synthetic_ids:
        quote_kinds = {
            case_id: {kind for kind, current_id, _ in synthetic_quotes
                      if current_id == case_id}
            for case_id in synthetic_ids}
        for case_id, kinds in quote_kinds.items():
            missing = {"SYNTHETIC_SOURCE", "SIMULATED", "OPTIMIZED"} - kinds
            if missing:
                issues.append(_issue(
                    "missing_synthetic_case_quotes",
                    f"合成案例 {case_id} 缺少透明展示字段：{', '.join(sorted(missing))}。",
                    evidence_id=case_id,
                    suggested_action="逐字展示真实源文、模拟初译和优化译文。"))
        methodology_ok = "<!--synthetic-methodology-->" in report_md and bool(
            re.search(r"模拟初译.{0,80}(?:不代表|并非).{0,20}(?:历史|实际|真实)",
                      report_md, re.DOTALL))
        if not methodology_ok:
            issues.append(_issue(
                "missing_synthetic_methodology_disclosure",
                "使用合成案例时，正文必须说明模拟初译为分析生成且不代表历史译文。",
                suggested_action="补充可见方法说明并保留 <!--synthetic-methodology-->。"))
        limitation_ok = "<!--synthetic-limitation-->" in report_md and bool(
            re.search(r"(?:不|不能|无法).{0,30}(?:发生频率|发生率|错误频率)", report_md))
        if not limitation_ok:
            issues.append(_issue(
                "missing_synthetic_limitation_disclosure",
                "使用合成案例时，正文必须说明它不能证明人类错误发生频率。",
                suggested_action="补充局限说明并保留 <!--synthetic-limitation-->。"))
        if authentic_ids and not (
                re.search(r"^#{3,6}\s+.*真实修订案例", report_md, re.MULTILINE)
                and re.search(r"^#{3,6}\s+.*合成对比案例", report_md, re.MULTILINE)):
            issues.append(_issue(
                "mixed_case_groups_not_visible",
                "混合案例章节没有用可见小标题区分真实修订与合成对比。",
                suggested_action="分别使用‘真实修订案例’和‘合成对比案例’小标题。"))
        synthetic_sections = re.findall(
            r"^#{3,6}\s+.*合成对比案例.*?(?=^#{3,6}\s+|^##\s+|\Z)", report_md,
            re.MULTILINE | re.DOTALL)
        for paragraph in re.split(r"\n\s*\n", report_md):
            referenced_synthetic = synthetic_ids & set(_SYNTHETIC_CASE_ID.findall(paragraph))
            in_synthetic_section = any(paragraph and paragraph in body
                                       for body in synthetic_sections)
            if (referenced_synthetic or in_synthetic_section) and \
                    _SYNTHETIC_AS_HISTORY.search(paragraph):
                issues.append(_issue(
                    "synthetic_case_presented_as_historical",
                    "合成案例被表述为作者或译者的历史初译/修订过程。",
                    evidence_id=sorted(referenced_synthetic)[0]
                    if referenced_synthetic else None,
                    suggested_action="改为‘模拟初译/优化译文’，明确其为分析构造。"))
        empirical_supported = all(
            canonical_synthetic.get(case_id, {}).get(
                "error_pattern_grounding", {}).get("empirical_frequency_supported")
            for case_id in synthetic_ids)
        if not empirical_supported and _EMPIRICAL_HUMAN_ERROR.search(report_md):
            issues.append(_issue(
                "unsupported_human_error_frequency_claim",
                "合成案例没有实证频率依据，不能称为常见或普遍的人类翻译错误。",
                suggested_action="改为‘一种合理的翻译失败模式’。"))

    candidate_status = {str(x.get("case_id")): x.get(
        "academic_candidate_status", "eligible")
        for x in evidence.get("candidate_cases", [])}
    for case_id in authentic_ids:
        if case_id not in candidate_status or case_id not in segs:
            issues.append(_issue(
                "invalid_selected_case", f"选中案例不在候选池或证据库中：{case_id}",
                evidence_id=case_id))
            continue
        segment = segs[case_id]
        if candidate_status[case_id] != "eligible" or not is_eligible_revision_case(
                segment):
            issues.append(_issue(
                "non_revision_case_used_as_revision_analysis",
                f"案例 {case_id} 没有通过初译→终译完整性门禁，不能作为核心修订案例。",
                evidence_id=case_id,
                suggested_action="替换为 revision_case；Human Evidence 不能改变该资格。"))
    for case_id in synthetic_ids:
        case = canonical_synthetic.get(case_id)
        selected_case = selected_synthetic.get(case_id) or {}
        if not case or not case.get("validation", {}).get("academic_case_eligible"):
            issues.append(_issue(
                "ineligible_synthetic_case_selected",
                f"合成案例 {case_id} 未通过 canonical synthetic eligibility gate。",
                evidence_id=case_id,
                suggested_action="从选案中移除或重新运行合成案例验证。"))
        elif selected_case.get("provenance") != {
                "historical": False, "generated_for_analysis": True}:
            issues.append(_issue(
                "synthetic_case_provenance_mismatch",
                f"合成案例 {case_id} 的结构化 provenance 无效。",
                evidence_id=case_id,
                suggested_action="恢复 canonical synthetic provenance。"))

    for plan_section in outline.get("sections", []):
        section_id = str(plan_section.get("section_id"))
        body = sections.get(section_id) or ""
        revision_claims = case_analysis.detect_revision_claims(body)
        if not revision_claims:
            continue
        referenced = [str(x) for x in plan_section.get("cases") or []
                      if str(x) in body and str(x) in segs and str(x) in authentic_ids]
        for case_id in referenced:
            segment = segs[case_id]
            if not is_eligible_revision_case(segment):
                issues.append(_issue(
                    "invented_revision",
                    f"章节 {section_id} 声称案例 {case_id} 发生修订，但项目记录没有真实差异。",
                    section_id=section_id, evidence_id=case_id,
                    suggested_action="删除该修订叙述并改用真实 revision_case。"))
        for claim in revision_claims:
            if not claim.get("old") or not claim.get("new"):
                continue
            matches_synthetic_delta = any(
                _described_piece_in(
                    selected_synthetic[case_id].get(
                        "synthetic_baseline", {}).get("text"), claim["old"])
                and _described_piece_in(
                    selected_synthetic[case_id].get(
                        "optimized_translation", {}).get("text"), claim["new"])
                for case_id in plan_section.get("cases") or []
                if case_id in selected_synthetic and case_id in body)
            if matches_synthetic_delta:
                continue
            matches_stored_delta = any(
                claim["old"] in _norm(segs[case_id].get("initial_target"))
                and claim["new"] in _norm(segs[case_id].get("final_target"))
                for case_id in referenced
                if is_eligible_revision_case(segs[case_id]))
            if referenced and not matches_stored_delta:
                issues.append(_issue(
                    "described_revision_not_in_stored_delta",
                    f"章节 {section_id} 描述的“{claim['old']}→{claim['new']}”"
                    "与所引案例保存的初译/终译差异不一致。",
                    section_id=section_id,
                    suggested_action="逐字依据 INITIAL/TARGET 记录描述实际变化。"))

    template_contract = template_contract or research_model.get("template_contract") \
        or (report_artifact or {}).get("template_contract")
    template_compliance = validate_template_compliance(
        report_md, template_contract, outline, report_artifact, selected_cases)
    issues.extend(template_compliance.get("issues") or [])
    for i, item in enumerate(issues, 1):
        item["issue_id"] = f"AV-{i:03d}"
    counts = Counter(x["severity"] for x in issues)
    status = "fail" if counts.get("error") else (
        "pass_with_warnings" if counts.get("warning") else "pass")
    result = {
        "schema_version": SCHEMA_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "status": status,
        "issues": issues,
        "summary": {
            "errors": counts.get("error", 0),
            "warnings": counts.get("warning", 0),
            "segment_references": len(
                set(_SEGMENT_REF.findall(report_md))
                | {case_id for _kind, case_id, _quote in _QUOTE.findall(report_md)}),
            "statistics_markers": len(_STAT.findall(report_md)),
            "citation_markers": len(_CITATION.findall(report_md)),
            "literature_claim_markers": len(_LIT_CLAIM.findall(report_md)),
            "literature_evidence_markers": len(_LIT_EVIDENCE.findall(report_md)),
            "literature_quote_markers": len(_LIT_QUOTE.findall(report_md)),
            "claim_markers": len(_CLAIM.findall(report_md)),
            "research_question_markers": len(_RQ.findall(report_md)),
            "selected_case_count": len(selected_ids),
            "structured_case_node_count": len(structured_ids),
            "unique_provenance_bound_visible_case_count": len(bound_ids),
        },
    }
    case_issue_types = _CASE_VALIDATION_ISSUE_TYPES | {"missing_selected_case"}
    case_issues = [item for item in issues if item.get("type") in case_issue_types]
    result["case_validation"] = {
        "status": "fail" if any(item.get("severity") == "error"
                                  for item in case_issues) else
        "pass_with_warnings" if case_issues else "pass",
        "selected_case_count": len(selected_ids),
        "structured_case_node_count": len(structured_ids),
        "unique_provenance_bound_visible_case_count": len(bound_ids),
        "missing_case_ids": sorted(selected_ids - bound_ids),
    }
    result["template_compliance"] = template_compliance
    result["content_hash"] = stable_hash({k: v for k, v in result.items()
                                          if k != "content_hash"})
    return result


def render_warnings_markdown(
    validation: Dict[str, Any],
    review: Optional[Dict[str, Any]] = None,
    literature_review: Optional[Dict[str, Any]] = None,
    evidence: Optional[Dict[str, Any]] = None,
    quality_dimensions: Optional[Dict[str, str]] = None,
) -> str:
    lines = ["# 学术证据与质量警告", ""]
    lines.append(f"- 确定性验证：{validation.get('status', 'unknown')}")
    if validation.get("template_compliance"):
        lines.append("- 模板合规：" + str(
            (validation.get("template_compliance") or {}).get("status", "unknown")))
    if review:
        lines.append(f"- 语义审稿：{review.get('status', 'unknown')}")
    if literature_review:
        lines.append(f"- 文献支持审校：{literature_review.get('status', 'unknown')}")
    if quality_dimensions:
        lines.extend(["", "## 质量维度", ""])
        lines.extend(f"- {key}: {value}" for key, value in quality_dimensions.items())
    limitations = (evidence or {}).get("limitations") or []
    if limitations:
        lines.extend(["", "## 缺失或受限证据", ""])
        lines.extend(f"- {item}" for item in limitations)
    all_issues = list(validation.get("issues") or []) \
        + list((review or {}).get("issues") or []) \
        + list((literature_review or {}).get("issues") or [])
    if all_issues:
        lines.extend(["", "## 未解决问题", ""])
        for item in all_issues:
            lines.append(
                f"- `{item.get('issue_id', '?')}` [{item.get('severity', '?')}] "
                f"{item.get('section_id') or '-'}：{item.get('reason', '')}")
    else:
        lines.extend(["", "未发现确定性来源错误；这不等于学术解释已经由人工确认。"])
    lines.extend(["", "> 自动验证可核对来源身份、结构和可计算的一致性，不能证明理论解释必然正确。"])
    return "\n".join(lines) + "\n"
