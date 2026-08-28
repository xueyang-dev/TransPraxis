"""Academic quality evaluation and structural repair planning.

This module evaluates whether the generated MTI report is *academically*
useful, not just technically valid.  It combines deterministic diagnostics
(paragraph roles, case richness, RQ coverage, evidence utilisation, conclusion
traceability, generic-prose patterns) with one low-temperature structured
semantic pass, then plans minimal structural repairs (including weak-case
replacement).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .academic_evidence import (
    case_role, is_eligible_revision_case, segment_index, stable_hash,
)
from . import academic_validator, case_analysis

QUALITY_VERSION = "academic-quality-v8"
REPORT_VERSION = "academic-quality-report-v1"

DIMENSIONS = (
    "research_alignment",
    "argument_quality",
    "case_quality",
    "analysis_depth",
    "theory_case_fit",
    "evidence_utilization",
    "literature_support",
    "cross_section_coherence",
    "academic_specificity",
    "redundancy",
    "conclusion_discipline",
    "writing_quality",
)
STATUSES = ("pass", "pass_with_warnings", "review_required", "fail", "not_applicable")
SEVERITIES = ("low", "medium", "high", "critical")
PRIORITIES = ("P0", "P1", "P2", "P3")
CASE_CLASSES = ("strong_case", "usable_case", "weak_case", "redundant_case", "misaligned_case")

_CLAIM_MARKER = re.compile(r"<!--claim:([A-Za-z0-9_.:-]+)-->")
_RQ_MARKER = re.compile(r"<!--rq:([A-Za-z0-9_.:-]+)-->")
_CASE_MARKER = re.compile(r"<!--case:([A-Za-z0-9_.:-]+)-->")
_LIT_CLAIM_MARKER = re.compile(r"<!--lit-claim:([A-Za-z0-9_.:-]+)-->")
_LIT_EVIDENCE_MARKER = re.compile(r"<!--lit-evidence:([A-Za-z0-9_.:-]+)-->")
_CITE_MARKER = re.compile(r"\[@([A-Za-z0-9_.:-]+)\]|<!--cite:([A-Za-z0-9_.:-]+)-->")
_SEG_REF = re.compile(r"\[(seg-[A-Za-z0-9_-]+-\d{4,})\]")
_SEG_QUOTE_REF = re.compile(
    r"\[(?:SOURCE|INITIAL|TARGET)\s+(seg-[A-Za-z0-9_-]+-\d{4,})\]")
_SYNTH_REF = re.compile(r"\b(SC-\d{4,})\b")
_STAT_MARKER = re.compile(r"<!--stat:([A-Za-z0-9_.-]+)-->")
_QUOTE_MARKER = re.compile(
    r"^\s*>\s*\[(SOURCE|TARGET|LITERATURE)\s+([^\]]+)\]:", re.MULTILINE)
_TERM_MARKER = re.compile(r"<!--term:([A-Za-z0-9_.:-]+)-->")
_SENT_SPLIT = re.compile(r"(?<=[。！？；!?;])\s*")

# Generic MTI/LLM boilerplate patterns (deterministic hard signals; the
# semantic pass handles paraphrase variants that regex cannot catch).
_GENERIC_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("realization_opening", re.compile(
        r"通过本次翻译实践[,，]?笔者(?:深刻|进一步|更加)?(?:地)?认识到")),
    ("future_reference", re.compile(
        r"为今后的翻译实践(?:提供了?)?(?:参考|借鉴|启示)")),
    ("quality_gain_claim", re.compile(
        r"这不(?:仅|但)(?:提高|提升)了翻译质量[,，]?也(?:为|对)今后的翻译实践")),
    ("comprehensive_factors", re.compile(
        r"在翻译过程中[,，]?需要综合考虑多种因素")),
    ("strategy_effectiveness", re.compile(
        r"该策略有效提升了译文的(?:准确性和可读性|质量)")),
    ("summary_boilerplate", re.compile(
        r"综上所述[,，]?笔者(?:认为|相信|希望)")),
    ("continuous_practice", re.compile(
        r"随着翻译实践的不断深入")),
    ("eng_realization", re.compile(
        r"through this translation practice[,]? the (?:author|translator) (?:deeply )?realized")),
    ("eng_future", re.compile(
        r"provide[ds]? (?:valuable )?(?:reference|insights) for future translation")),
    ("eng_quality_gain", re.compile(
        r"not only improves translation quality,? but also")),
    ("eng_generic_conclusion", re.compile(
        r"in conclusion[,]? the translator (?:believes|hopes)")),
]

_ANALYSIS_SIGNALS = re.compile(
    r"从结果看可解释为|这说明|这表明|原因在于|可归因于|体现了|反映了|"
    r"并非(?:简单|仅)|相较于|替代方案|权衡|局限|外推|this suggests|this indicates|"
    r"can be explained|rather than|trade-off|limitation", re.IGNORECASE)
_TRANSITION_SIGNALS = re.compile(
    r"^(?:接下来|下面|首先|其次|最后|综上|此外|另一方面|值得注意的是)", )
_SUMMARY_SIGNALS = re.compile(
    r"本节(?:总结|小结)|综上所述|总体而言|概括而言|本节主要(?:分析|讨论)")
_FILLER_SIGNALS = re.compile(
    r"^(?:在此|这里|本文|本报告|笔者)将(?:对|从|结合)", )
_TRANSLATION_DESCRIPTION = re.compile(
    r"译文(?:将|把|对|中)|(?:译为|译作|处理为|调整为)|"
    r"the translation (?:renders|turns|handles)")
_THEORY_TERM = re.compile(
    r"功能对等|目的论|关联理论|翻译转换|等值|functional equivalence|skopos|"
    r"relevance theory")


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text or "").strip(),
                       flags=re.DOTALL)
    try:
        value = json.loads(candidate)
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _is_transient_llm_error(exc: Exception) -> bool:
    module = type(exc).__module__ or ""
    message = str(exc).casefold()
    return module.startswith(("openai", "httpx", "httpcore")) or any(
        token in message for token in (
            "timeout", "connection", "rate limit", "502", "503", "504",
            "bad gateway", "temporarily unavailable"))


def detect_generic_patterns(text: str) -> List[str]:
    found = []
    for name, pattern in _GENERIC_PATTERNS:
        if pattern.search(text):
            found.append(name)
    return found


def classify_paragraph(text: str) -> str:
    """Best-effort paragraph role for diagnostic statistics."""
    stripped = (text or "").strip()
    if not stripped:
        return "filler"
    if _CLAIM_MARKER.search(stripped) or _RQ_MARKER.search(stripped) \
            or _LIT_CLAIM_MARKER.search(stripped):
        return "claim"
    if _SEG_REF.search(stripped) or _QUOTE_MARKER.search(stripped) \
            or _LIT_EVIDENCE_MARKER.search(stripped) or _STAT_MARKER.search(stripped):
        return "evidence"
    if detect_generic_patterns(stripped):
        return "generic"
    if _SUMMARY_SIGNALS.search(stripped):
        return "summary"
    if _TRANSITION_SIGNALS.search(stripped):
        return "transition"
    if _THEORY_TERM.search(stripped) and _ANALYSIS_SIGNALS.search(stripped):
        return "theoretical_interpretation"
    if _TRANSLATION_DESCRIPTION.search(stripped):
        return "translation_description"
    if _ANALYSIS_SIGNALS.search(stripped):
        return "analysis"
    if len(stripped) < 40 or _FILLER_SIGNALS.search(stripped):
        return "filler"
    return "background"


def paragraph_statistics(sections: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    counts: Counter = Counter()
    per_section: Dict[str, Dict[str, int]] = {}
    total = 0
    for section in sections:
        paragraphs = [x for x in re.split(r"\n\s*\n", section.get("content") or "")
                      if x.strip()]
        section_counts: Counter = Counter(classify_paragraph(x) for x in paragraphs)
        per_section[str(section.get("section_id"))] = dict(section_counts)
        counts.update(section_counts)
        total += len(paragraphs)
    return {
        "total_paragraphs": total,
        "paragraph_roles": dict(counts),
        "per_section_roles": per_section,
        "claim_bearing_paragraphs": counts.get("claim", 0),
        "evidence_bearing_paragraphs": counts.get("evidence", 0),
        "analysis_bearing_paragraphs": counts.get("analysis", 0),
        "generic_paragraphs": counts.get("generic", 0),
        "generic_rate": round(counts.get("generic", 0) / total, 3) if total else 0.0,
    }


def case_quality_signals(segment: Dict[str, Any], findings: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    process = segment.get("process_evidence", {})
    index = segment.get("segment_index")
    if index is None:
        seg_findings = list(process.get("findings") or [])
    else:
        seg_findings = [x for x in findings
                        if x.get("segment_index") == index]
    initial = segment.get("initial_target")
    final = segment.get("final_target")
    changed = is_eligible_revision_case(segment)
    repair = bool(process.get("repair_history"))
    term_ids = process.get("injected_glossary_entry_ids") or []
    availability = segment.get("availability", {})
    recorded_initial = availability.get("initial_target") == "recorded" \
        or initial is not None
    recorded_findings = availability.get("findings") == "recorded" or bool(seg_findings)
    recorded_repair = availability.get("repair_history") == "recorded" or bool(repair)
    return {
        "has_finding": bool(seg_findings),
        "finding_severities": sorted({x.get("severity") for x in seg_findings}),
        "has_actionable_or_blocking": any(
            x.get("severity") in ("actionable", "blocking") for x in seg_findings),
        "initial_to_final_changed": changed,
        "has_meaningful_revision": changed,
        "case_role": "revision_case" if changed else (
            "revision_evidence_boundary" if segment.get("integrity_flags")
            else case_role(segment)),
        "has_repair_history": repair,
        "terminology_decision_count": len(term_ids),
        "reviewed": bool(segment.get("reviewed")),
        "from_tm": bool(segment.get("from_tm")),
        "availability": availability,
        "evidence_richness": sum([
            bool(seg_findings), changed, repair, bool(term_ids),
            recorded_initial, recorded_findings, recorded_repair,
        ]),
    }


def classify_case(
    case: Dict[str, Any], segment: Optional[Dict[str, Any]],
    findings: Iterable[Dict[str, Any]], selected_ids: Iterable[str],
) -> Tuple[str, List[str]]:
    """Classify a selected case with an evidence-backed reason list."""
    reasons: List[str] = []
    case_id = str(case.get("case_id") or "")
    if not segment:
        return "weak_case", ["证据库中不存在该案例"]
    signals = case_quality_signals(segment, findings)
    if case_id not in set(selected_ids):
        return "misaligned_case", ["案例未出现在选中案例集合"]
    if not signals["has_meaningful_revision"]:
        return "weak_case", ["无有意义的初译—终译差异"]
    if signals["evidence_richness"] >= 5 and signals["has_actionable_or_blocking"]:
        return "strong_case", [
            f"证据丰富度 {signals['evidence_richness']}/7",
            "存在 actionable/blocking finding", "有修复或初译—终译差异"]
    if signals["evidence_richness"] >= 3:
        return "usable_case", [f"证据丰富度 {signals['evidence_richness']}/7"]
    if not signals["has_finding"] and not signals["initial_to_final_changed"] \
            and signals["terminology_decision_count"] == 0:
        return "weak_case", ["无 finding、无初译—终译差异、无术语决策"]
    return "usable_case", [f"证据丰富度 {signals['evidence_richness']}/7"]


def build_rq_matrix(
    research_model: Dict[str, Any], argument_plan: Dict[str, Any],
    selected_cases: Dict[str, Any], outline: Dict[str, Any],
) -> Dict[str, Any]:
    claims = {x["claim_id"]: x for x in argument_plan.get("claims", [])}
    rqs = {x["rq_id"]: x for x in research_model.get("research_questions", [])}
    cases = {x["case_id"]: x for x in selected_cases.get("cases", [])}
    sections = {x["section_id"]: x for x in outline.get("sections", [])}
    matrix: Dict[str, Dict[str, Any]] = {}
    for rq_id in rqs:
        matrix[rq_id] = {
            "claims": [], "cases": [], "sections": [], "answered": False,
            "unanswered_reason": "",
        }
    for claim_id, claim in claims.items():
        rq_id = str(claim.get("research_question") or "")
        if rq_id in matrix:
            matrix[rq_id]["claims"].append(claim_id)
        for evidence_id in claim.get("project_evidence") or []:
            if evidence_id in cases and rq_id in matrix \
                    and evidence_id not in matrix[rq_id]["cases"]:
                matrix[rq_id]["cases"].append(evidence_id)
    for section in outline.get("sections", []):
        for rq_id in section.get("research_questions") or []:
            if rq_id in matrix and section["section_id"] not in matrix[rq_id]["sections"]:
                matrix[rq_id]["sections"].append(section["section_id"])
    for rq_id, entry in matrix.items():
        conclusion_claims = {
            str(x) for sid, x in sections.items()
            if re.search(r"结论|结语|conclusion", str(x.get("title") or ""), re.I)
            for x in [x]
        }
        del conclusion_claims
        if entry["claims"] and entry["sections"]:
            entry["answered"] = True
        else:
            entry["unanswered_reason"] = (
                "无相关 claim" if not entry["claims"] else "无章节展开")
    orphan_claims = [
        claim_id for claim_id in claims
        if not any(claim_id in (x.get("claims") or []) for x in sections.values())]
    return {
        "matrix": matrix,
        "answered_rqs": sum(1 for x in matrix.values() if x["answered"]),
        "unanswered_rqs": [rq_id for rq_id, x in matrix.items() if not x["answered"]],
        "orphan_claims": orphan_claims,
        "sections_without_rq": [
            section_id for section_id, x in sections.items()
            if not x.get("research_questions")],
    }


def evidence_utilization(
    sections: Iterable[Dict[str, Any]],
    selected_cases: Dict[str, Any], evidence: Dict[str, Any],
) -> Dict[str, Any]:
    segs = segment_index(evidence)
    used_segments = set()
    for section in sections:
        content = section.get("content") or ""
        used_segments.update(_CASE_MARKER.findall(content))
        used_segments.update(_SEG_REF.findall(content))
        used_segments.update(_SEG_QUOTE_REF.findall(content))
        used_segments.update(_SYNTH_REF.findall(content))
    rows = []
    for case in selected_cases.get("cases", []):
        case_id = str(case.get("case_id") or "")
        synthetic = case.get("case_type") == "synthetic_contrast"
        segment = segs.get(case_id)
        signals = case_quality_signals(segment or {}, evidence.get("findings") or [])
        used = case_id in used_segments
        high_value_unused = bool(case.get("validation", {}).get(
            "academic_case_eligible")) if synthetic else bool(
                signals["has_actionable_or_blocking"] or signals[
                    "initial_to_final_changed"] or signals["has_repair_history"]
                or signals["terminology_decision_count"])
        rows.append({
            "case_id": case_id,
            "used_in_report": used,
            "evidence_richness": None if synthetic else signals["evidence_richness"],
            "case_type": case.get("case_type", "authentic_revision"),
            "high_value_unused": bool(high_value_unused and not used),
            "unused_dimensions": ["validated_synthetic_contrast"] if synthetic and not used else [
                name for name, present in (
                    ("finding", signals["has_finding"]),
                    ("initial_final_change", signals["initial_to_final_changed"]),
                    ("repair_history", signals["has_repair_history"]),
                    ("terminology_decision", signals["terminology_decision_count"] > 0),
                ) if present and not used
            ],
        })
    return {
        "selected_case_count": len(rows),
        "cases_used": sum(1 for x in rows if x["used_in_report"]),
        "high_value_unused_cases": [x["case_id"] for x in rows if x["high_value_unused"]],
        "rows": rows,
    }


def conclusion_traceability(
    outline: Dict[str, Any], sections: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_id = {x["section_id"]: x for x in sections}
    conclusion_ids = [
        x["section_id"] for x in outline.get("sections", [])
        if re.search(r"结论|结语|conclusion", str(x.get("title") or ""), re.I)]
    if not conclusion_ids and len(outline.get("sections", [])) > 1:
        conclusion_ids = [outline["sections"][-1]["section_id"]]
    out: List[Dict[str, Any]] = []
    for section_id in conclusion_ids:
        section = by_id.get(section_id) or {}
        content = section.get("content") or ""
        for paragraph in re.split(r"\n\s*\n", content):
            if re.match(r"^#{1,6}\s+", paragraph.strip()):
                continue
            paragraph_marked = any(pattern.search(paragraph) for pattern in (
                _CLAIM_MARKER, _RQ_MARKER, _SEG_REF, _CITE_MARKER,
                _STAT_MARKER, _LIT_CLAIM_MARKER))
            # Protect provenance comments before splitting on punctuation. IDs
            # legitimately contain periods and must remain atomic.
            protected: Dict[str, str] = {}
            def protect(match: re.Match) -> str:
                token = f"TRACEPROVENANCE{len(protected)}TOKEN"
                protected[token] = match.group(0)
                return token
            protected_paragraph = re.sub(
                r"<!--.*?-->", protect, paragraph, flags=re.DOTALL)
            for sentence in _SENT_SPLIT.split(protected_paragraph):
                for token, marker in protected.items():
                    sentence = sentence.replace(token, marker)
                sentence = _norm(sentence)
                if len(sentence) < 12:
                    continue
                traceable = paragraph_marked or bool(
                    _CLAIM_MARKER.search(sentence) or _RQ_MARKER.search(sentence)
                    or _SEG_REF.search(sentence) or _CITE_MARKER.search(sentence)
                    or _STAT_MARKER.search(sentence)
                    or _LIT_CLAIM_MARKER.search(sentence))
                out.append({
                    "section_id": section_id,
                    "sentence": sentence[:160],
                    "traceable_to_evidence": traceable,
                    "needs_semantic_check": not traceable,
                })
    return out


def cross_section_checks(sections: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    seen: Dict[str, str] = {}
    case_sections: Dict[str, List[str]] = {}
    claim_sections: Dict[str, List[str]] = {}
    for section in sections:
        section_id = str(section.get("section_id"))
        content = section.get("content") or ""
        for seg_id in sorted(set(_CASE_MARKER.findall(content)) |
                             set(_SEG_REF.findall(content)) |
                             set(_SYNTH_REF.findall(content))):
            case_sections.setdefault(seg_id, []).append(section_id)
        for claim_id in sorted(set(_CLAIM_MARKER.findall(content))):
            claim_sections.setdefault(claim_id, []).append(section_id)
        for paragraph in re.split(r"\n\s*\n", content):
            key = stable_hash(re.sub(r"\s+", " ", paragraph).strip()[:400])
            if key in seen and seen[key] != section_id:
                issues.append({
                    "type": "duplicate_paragraph", "section_id": section_id,
                    "other_section_id": seen[key], "severity": "low",
                    "evidence": _norm(paragraph)[:80],
                    "reason": "两个章节出现高度重复段落。",
                    "recommended_action": "合并或删除重复内容。",
                })
            seen[key] = section_id
    for case_id, section_list in case_sections.items():
        if len(section_list) > 1:
            issues.append({
                "type": "duplicate_case_analysis", "section_id": None,
                "case_id": case_id, "severity": "medium",
                "evidence": f"{case_id} 出现在 {len(section_list)} 个章节",
                "reason": "同一案例在多个章节重复展开，可能导致冗余或解释不一致。",
                "recommended_action": "集中展开一次，其余章节仅作交叉引用。",
            })
    for claim_id, section_list in claim_sections.items():
        if len(section_list) > 1 and len({x for x in section_list}) > 1:
            issues.append({
                "type": "duplicate_claim", "section_id": None, "claim_id": claim_id,
                "severity": "low", "evidence": f"{claim_id} 出现在 {len(section_list)} 个章节",
                "reason": "同一论点在多个章节重复标记，需确认是否构成重复论证。",
                "recommended_action": "若为重复论证，合并；若为递进，补充章节间衔接。",
            })
    return issues


def deterministic_diagnostics(
    research_model: Dict[str, Any], argument_plan: Dict[str, Any],
    selected_cases: Dict[str, Any], outline: Dict[str, Any],
    sections: Iterable[Dict[str, Any]], evidence: Dict[str, Any],
) -> Dict[str, Any]:
    findings_all = evidence.get("findings") or []
    segs = segment_index(evidence)
    selected_ids = {str(x.get("case_id")) for x in selected_cases.get("cases", [])}
    case_rows = []
    for case in selected_cases.get("cases", []):
        case_id = str(case.get("case_id") or "")
        synthetic = case.get("case_type") == "synthetic_contrast"
        decision = case.get("case_type") == "translation_decision"
        segment = segs.get(str(case.get("source_segment_id") or case_id)) or {}
        if synthetic:
            validation = case.get("validation") or {}
            cls = "strong_case" if validation.get("academic_case_eligible") else "weak_case"
            reasons = [validation.get("reason") or "; ".join(
                validation.get("rejected_reasons") or []) or "synthetic validation missing"]
        elif decision:
            decision_evidence = case.get("decision_evidence") or {}
            cls = "strong_case" if segment.get("source") and segment.get(
                "final_target") and decision_evidence else "weak_case"
            reasons = list(decision_evidence.get("reasons") or []) or [
                "翻译决策案例保留原文、终译和可分析的项目证据。"]
        else:
            cls, reasons = classify_case(case, segment, findings_all, selected_ids)
        case_rows.append({
            "case_id": case_id,
            "case_type": case.get("case_type", "authentic_revision"),
            "argument_role": case.get("argument_role", "supporting"),
            "semantic_alignment": (case.get("semantic_alignment") or {}).get("status"),
            "class": cls,
            "reasons": reasons,
            "supports_claims": sorted(set(case.get("supports_claims") or [])),
            "evidence_richness": None if synthetic else case_quality_signals(
                segment, findings_all)["evidence_richness"],
            "case_role": "synthetic_contrast_case" if synthetic else (
                "translation_decision_case" if decision else case_role(segment)),
            "synthetic_dimensions": {
                "difficulty_validity": "confirmed" if case.get("difficulty", {}).get(
                    "trigger") and case.get("difficulty", {}).get("reason") else "not_confirmed",
                "baseline_plausibility": case.get("baseline_plausibility", {}).get(
                    "status", "implausible"),
                "material_difference": (case.get("synthetic_evidence") or {}).get(
                    "material_difference", "fail"),
                "error_materiality": case.get("validation", {}).get(
                    "error_materiality", "not_confirmed"),
                "diagnosis_depth": "confirmed" if case.get("error", {}).get(
                    "diagnosis") and case.get("error", {}).get(
                        "meaning_or_function_distortion") else "not_confirmed",
                "repair_validity": case.get("validation", {}).get(
                    "repair_correctness", "not_confirmed"),
                "repair_correctness": (case.get("synthetic_evidence") or {}).get(
                    "repair_correctness", "fail"),
                "academic_analysis_value": (case.get("synthetic_evidence") or {}).get(
                    "academic_analysis_value", "fail"),
                "analysis_depth": "pending_semantic_review",
                "theory_case_fit": "pending_literature_grounding",
                "bounded_conclusion": "pending_semantic_review",
                "provenance_correctness": "confirmed" if (
                    (case.get("provenance") or {}).get("historical") is False
                    and (case.get("provenance") or {}).get(
                        "generated_for_analysis") is True)
                else "not_confirmed",
            } if synthetic else {},
        })
    return {
        "paragraph_statistics": paragraph_statistics(sections),
        "case_quality": case_rows,
        "rq_matrix": build_rq_matrix(research_model, argument_plan, selected_cases, outline),
        "evidence_utilization": evidence_utilization(sections, selected_cases, evidence),
        "conclusion_traceability": conclusion_traceability(outline, sections),
        "cross_section_checks": cross_section_checks(sections),
        "case_count_policy": {
            "status": selected_cases.get(
                "authentic_selection_status", selected_cases.get("selection_status")),
            "preferred": selected_cases.get("preferred_core_case_count"),
            "minimum": selected_cases.get("minimum_core_case_count"),
            "selected": len(selected_cases.get("cases", [])),
        },
    }


def _issue(issue_type: str, *, dimension: str, severity: str, priority: str,
           reason: str, recommended_action: str, section_id: Optional[str] = None,
           claim_id: Optional[str] = None, case_id: Optional[str] = None,
           evidence: str = "", repair_action: str = "rewrite") -> Dict[str, Any]:
    return {
        "issue_id": "",
        "type": issue_type,
        "dimension": dimension,
        "section_id": section_id,
        "claim_id": claim_id,
        "case_id": case_id,
        "severity": severity,
        "priority": priority,
        "evidence": evidence,
        "reason": reason,
        "recommended_action": recommended_action,
        "repair_action": repair_action,
    }


def _deterministic_findings(diagnostics: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    rq = diagnostics["rq_matrix"]
    for rq_id in rq["unanswered_rqs"]:
        issues.append(_issue(
            "research_question_unanswered", dimension="research_alignment",
            severity="high", priority="P1",
            reason=f"研究问题 {rq_id} 没有可追溯的 claim 与章节展开。",
            recommended_action="为 RQ 规划 claim 与对应章节，或从研究模型移除该 RQ。",
            claim_id=rq_id))
    for claim_id in rq["orphan_claims"]:
        issues.append(_issue(
            "orphan_claim", dimension="research_alignment", severity="medium",
            priority="P1", reason=f"全局论点 {claim_id} 未出现在任何章节。",
            recommended_action="在提纲中为该 claim 分配章节并落实 marker。",
            claim_id=claim_id))
    for section_id in rq["sections_without_rq"]:
        issues.append(_issue(
            "section_without_research_question", dimension="research_alignment",
            severity="low", priority="P3",
            reason=f"章节 {section_id} 未绑定任何研究问题。",
            recommended_action="绑定对应 RQ，或说明其作为报告必要功能章节。",
            section_id=section_id))
    for row in diagnostics["case_quality"]:
        if row.get("case_type") == "synthetic_contrast" and row["class"] == "weak_case":
            issues.append(_issue(
                "ineligible_synthetic_case_used",
                dimension="case_quality", severity="critical", priority="P1",
                reason=f"合成案例 {row['case_id']} 未通过 plausibility/materiality/repair gate。",
                recommended_action="从学术写作中移除该合成案例。",
                case_id=row["case_id"], evidence=row["reasons"][0],
                repair_action="replace_case"))
        elif row.get("case_role") == "non_revision_case":
            issues.append(_issue(
                "non_revision_case_used_as_revision_analysis",
                dimension="case_quality", severity="critical", priority="P1",
                reason=f"案例 {row['case_id']} 没有真实初译→终译差异，不能进入核心修订案例分析。",
                recommended_action="从核心案例池移除；不得用 Human Author Evidence 补造修订历史。",
                case_id=row["case_id"], evidence=row["reasons"][0],
                repair_action="replace_case"))
        elif row["class"] == "weak_case":
            issues.append(_issue(
                "weak_case", dimension="case_quality", severity="medium", priority="P2",
                reason=f"案例 {row['case_id']} 缺少真实翻译问题、决策差异或修复证据。",
                recommended_action="从候选池替换为证据更丰富的案例。",
                case_id=row["case_id"], evidence=row["reasons"][0],
                repair_action="replace_case"))
        elif row["class"] == "redundant_case":
            issues.append(_issue(
                "redundant_case", dimension="redundancy", severity="medium",
                priority="P2", reason=f"案例 {row['case_id']} 与其他案例重复。",
                recommended_action="删除或替换为不同证据类型的案例。",
                case_id=row["case_id"], repair_action="replace_case"))
        elif row["class"] == "misaligned_case":
            issues.append(_issue(
                "misaligned_case", dimension="case_quality", severity="high",
                priority="P1", reason=f"案例 {row['case_id']} 与所支持论点不匹配。",
                recommended_action="替换为与 claim 主题一致的案例。",
                case_id=row["case_id"], repair_action="replace_case"))
    for row in diagnostics["evidence_utilization"]["rows"]:
        if row["high_value_unused"]:
            issues.append(_issue(
                "high_value_evidence_unused", dimension="evidence_utilization",
                severity="medium", priority="P2",
                reason=f"案例 {row['case_id']} 有高价值过程证据但正文未使用"
                       f"（未用维度：{row['unused_dimensions']}）。",
                recommended_action="用 finding/修复/初译—终译差异充实该案例分析。",
                case_id=row["case_id"], repair_action="rewrite"))
    for item in diagnostics["conclusion_traceability"]:
        if item["needs_semantic_check"]:
            issues.append(_issue(
                "conclusion_without_trace", dimension="conclusion_discipline",
                severity="low", priority="P3",
                reason=f"结论句缺少证据标记，需人工或语义确认：{item['sentence']}",
                recommended_action="绑定 claim/案例/统计/文献标记，或删除无法追溯的断言。",
                section_id=item["section_id"]))
    issues.extend(_issue(
        x["type"], dimension="cross_section_coherence", severity=x["severity"],
        priority="P1" if x["severity"] == "high" else "P2",
        reason=x["reason"], recommended_action=x["recommended_action"],
        section_id=x.get("section_id"), case_id=x.get("case_id"),
        claim_id=x.get("claim_id"), evidence=x.get("evidence", ""))
        for x in diagnostics["cross_section_checks"])
    for item in diagnostics.get("deterministic_validation_issues") or []:
        issue_type = str(item.get("type") or "deterministic_surface_failure")
        issues.append(_issue(
            issue_type,
            dimension="surface_integrity" if issue_type.startswith("template_")
            else "claim_discipline",
            severity="high", priority="P1",
            reason=str(item.get("reason") or "确定性验证发现用户可见质量问题。"),
            recommended_action=str(item.get("suggested_action") or
                                   "定点修复受影响章节并重新验证。"),
            section_id=item.get("section_id"),
            evidence=str(item.get("evidence_id") or ""),
            repair_action="rewrite"))
    return issues


def _scoped_inputs(
    research_model: Dict[str, Any], argument_plan: Dict[str, Any],
    selected_cases: Dict[str, Any], outline: Dict[str, Any],
    sections: Iterable[Dict[str, Any]], evidence: Dict[str, Any],
    literature_claims: Dict[str, Any],
    diagnostics: Dict[str, Any],
) -> Dict[str, Any]:
    case_pool = []
    for case in selected_cases.get("cases", []):
        focus = case.get("focus") or {}
        focused_source = dict(focus.get("source_span") or {})
        focused_initial = dict(focus.get("initial_span") or {})
        focused_target = dict(focus.get("target_span") or {})
        if case.get("case_type") == "synthetic_contrast":
            case_pool.append({
                "case_id": case.get("case_id"),
                "case_type": "synthetic_contrast",
                "source_segment_id": case.get("source_segment_id"),
                "supports_claims": case.get("supports_claims"),
                "focus": {
                    "source": focused_source,
                    "initial": focused_initial or None,
                    "target": focused_target,
                },
                "difficulty": case.get("difficulty"),
                "synthetic_baseline": case.get("synthetic_baseline"),
                "error": case.get("error"),
                "optimized_translation": case.get("optimized_translation"),
                "final_target": case.get("final_target") or
                (case.get("optimized_translation") or {}).get("text"),
                "validation": case.get("validation"),
                "synthetic_evidence": case.get("synthetic_evidence"),
                "provenance": case.get("provenance"),
            })
            continue
        case_pool.append({
            "case_id": case.get("case_id"), "coverage_zone": case.get("coverage_zone"),
            "case_type": case.get("case_type", "authentic_revision"),
            "source_segment_id": case.get("source_segment_id"),
            "supports_claims": case.get("supports_claims"),
            "focus": {
                "source": focused_source,
                "initial": focused_initial or None,
                "target": focused_target,
            },
            "difficulty_group": case.get("difficulty_group"),
            "strategy_group": case.get("strategy_group"),
            "decision_evidence": case.get("decision_evidence"),
        })
    return {
        "research_model": {
            key: research_model.get(key) for key in (
                "research_topic", "research_questions", "theoretical_framework",
                "method", "analysis_dimensions", "expected_contribution",
                "project_metadata", "body_language", "writing_style")
        },
        "chapter_roles": {
            str(item.get("section_id")): item.get("role")
            for item in outline.get("sections") or []},
        "argument_plan": argument_plan,
        "selected_cases": case_pool,
        "case_count_policy": {
            "status": selected_cases.get(
                "authentic_selection_status", selected_cases.get("selection_status")),
            "preferred": selected_cases.get("preferred_core_case_count"),
            "minimum": selected_cases.get("minimum_core_case_count"),
            "selected": len(case_pool),
            "instruction": (
                "two_case_fallback is academically valid and must not be criticized "
                "solely for lacking a third case"),
        },
        "outline": [{k: v for k, v in x.items() if k != "content_hash"}
                    for x in outline.get("sections", [])],
        "report": "\n\n".join(
            f"## {x.get('section_id')} {x.get('title')}\n\n{x.get('content')}"
            for x in sections)[:60000],
        "literature_claims": literature_claims.get("items", [])[:40],
        "deterministic_diagnostics": diagnostics,
    }


def evaluate_quality(
    research_model: Dict[str, Any], argument_plan: Dict[str, Any],
    selected_cases: Dict[str, Any], outline: Dict[str, Any],
    sections: Iterable[Dict[str, Any]], evidence: Dict[str, Any],
    literature_sources: Dict[str, Any], literature_evidence_artifact: Dict[str, Any],
    literature_claims: Dict[str, Any], deterministic_validation: Dict[str, Any],
    call_llm: Callable, provider: str, api_key: str, model: str,
    case_analysis_plans: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    has_literature = bool(literature_sources.get("sources")) and bool(
        literature_evidence_artifact.get("items")) and bool(
            literature_claims.get("items"))
    final_report = str((research_model.get("report_constraints") or {}).get(
        "report_stage") or "") == "final_report"
    diagnostics = deterministic_diagnostics(
        research_model, argument_plan, selected_cases, outline, sections, evidence)
    diagnostics["deterministic_validation_issues"] = [
        dict(item) for item in deterministic_validation.get("issues") or []
        if item.get("type") in {
            "template_duplicate_rendering", "template_duplicate_heading",
            "template_internal_id_visible", "template_unresolved_marker",
            "unsupported_claim_strength",
        }
    ]
    findings = _deterministic_findings(diagnostics)
    for section in sections:
        section_id = section.get("section_id")
        content = section.get("content") or ""
        revision_claims = case_analysis.detect_revision_claims(content)
        if revision_claims:
            for case in selected_cases.get("cases", []):
                if case.get("case_type") != "authentic_revision":
                    continue
                case_id = str(case.get("case_id") or "")
                segment = segment_index(evidence).get(case_id) or {}
                if case_id in content and not is_eligible_revision_case(segment):
                    findings.append(_issue(
                        "non_revision_case_used_as_revision_analysis",
                        dimension="case_quality", severity="critical", priority="P1",
                        reason=f"正文声称案例 {case_id} 经修改，但保存的初译与终译没有有意义差异。",
                        recommended_action="删除虚构修订叙述并替换为真实 revision_case。",
                        section_id=section_id, case_id=case_id,
                        evidence=revision_claims[0]["text"], repair_action="replace_case"))
        for hit in case_analysis.detect_strategy_label_without_mechanism(content):
            findings.append(_issue(
                "strategy_label_without_mechanism", dimension="analysis_depth",
                severity="medium", priority="P1",
                reason=f"策略标签缺少机制解释：{hit}",
                recommended_action="补充问题→机制→效果的具体分析，删除空泛质量判断。",
                section_id=section_id))
        for hit in case_analysis.detect_unsupported_quality_effect(content):
            findings.append(_issue(
                "unsupported_quality_effect", dimension="analysis_depth",
                severity="medium", priority="P2",
                reason=f"质量效果判断缺少维度与文本证据：{hit}",
                recommended_action="指明效果维度（语义/逻辑/语用/节奏等）与具体文本特征。",
                section_id=section_id))
        for hit in case_analysis.detect_unsupported_process_claim(content):
            findings.append(_issue(
                "unsupported_process_claim", dimension="analysis_depth",
                severity="high", priority="P1",
                reason=f"无证据的过程/意图断言：{hit}",
                recommended_action="删除或将表述改为分析性对比并标注 counterfactual。",
                section_id=section_id))
        for hit in case_analysis.detect_case_to_general_rule_overreach(content):
            findings.append(_issue(
                "case_to_general_rule_overreach", dimension="conclusion_discipline",
                severity="medium", priority="P1",
                reason=f"单案例外推为一般规则：{hit}",
                recommended_action="将结论限定为本案例。",
                section_id=section_id))
    if not has_literature:
        for section in sections:
            for match in case_analysis._THEORY_LABEL.finditer(
                    section.get("content") or ""):
                findings.append(_issue(
                    "theory_name_dropping", dimension="theory_case_fit",
                    severity="medium", priority="P1",
                    reason="无落地文献支持，正文仍提及理论名称："
                           f"{match.group(0)}",
                    recommended_action="删除理论名称，或先登记并落地该理论文献。",
                    section_id=section.get("section_id")))
    dimensions: Dict[str, str] = {}
    for name in DIMENSIONS:
        if name == "literature_support":
            dimensions[name] = "pass" if has_literature else (
                "review_required" if final_report else "not_applicable")
        elif name == "theory_case_fit":
            dimensions[name] = "not_applicable" if not has_literature else "pass"
        else:
            dimensions[name] = "pass"

    system = (
        "你是保守的 MTI 翻译实践报告学术质量审稿人。只评估证据可追溯的学术质量，"
        "不给出单一总分，不检查文风细节，不改写正文。对每个维度给出状态："
        "pass / pass_with_warnings / review_required / fail / not_applicable。"
        "检测研究问题是否被回答、论点是否被证据支持、案例是否真正展示翻译决策与"
        "理由、分析是否超越‘原文→译文→策略标签’、理论是否真正解释证据、过程证据"
        "是否被使用、章节间是否矛盾或重复、结论是否过度外推、是否存在高度套话。"
        "只输出 JSON：{\"dimensions\":{\"research_alignment\":\"pass\"},"
        "\"findings\":[{\"type\":\"weak_analysis|generic_prose|theory_case_mismatch|"
        "unsupported_conclusion|contradiction|evidence_unused|weak_case|duplicate|"
        "research_question_unanswered|claim_unsupported\",\"dimension\":\"analysis_depth\","
        "\"section_id\":\"3\",\"claim_id\":\"C1\",\"case_id\":\"seg-...\","
        "\"severity\":\"low|medium|high|critical\",\"priority\":\"P0|P1|P2|P3\","
        "\"evidence\":\"具体句子的简短摘录\",\"reason\":\"...\","
        "\"recommended_action\":\"...\",\"repair_action\":\"rewrite|replace_case|"
        "narrow|downgrade|remove\"}],\"case_analysis_depth\":{\"seg-...\":{"
        "repair_action 可选：rewrite|replace_case|narrow|downgrade|remove|"
        "add_missing_problem_analysis|add_process_evidence|narrow_claim|"
        "replace_strategy_label_with_mechanism|add_theory_case_mapping|"
        "add_translation_effect_explanation|remove_fake_process_history|"
        "downgrade_unsupported_quality_claim|bound_case_conclusion。"
        "\"problem_definition\":{\"status\":\"strong|adequate|weak|missing|"
        "not_applicable\",\"reason\":\"...\"},\"evidence_use\":{...},"
        "\"initial_failure_or_alternative\":{...},\"decision_rationale\":{...},"
        "\"translation_effect\":{...},\"theory_mapping\":{...},"
        "\"bounded_conclusion\":{...}}}}。无问题时 findings 为空数组，"
        "case_analysis_depth 必须为每个选中案例输出全部 7 个维度；空洞的"
        "‘问题：句子很难/理由：它很复杂/策略：意译/效果：更自然’式内容必须判 weak。"
        "若 case_count_policy.status 为 two_case_fallback，两个案例已满足最低结构，"
        "不得仅因缺少第三案例给出负面判断；只检查是否披露证据稀缺。"
        "synthetic_contrast 应按难点有效性、模拟初译合理性、错误实质性、诊断深度、"
        "修复有效性、provenance 与结论边界评价；不得把它降格为缺少历史 finding 的"
        "弱案例，也不得把它计入真实修订证据。"
    )
    payload = _scoped_inputs(
        research_model, argument_plan, selected_cases, outline, sections, evidence,
        literature_claims, diagnostics)
    raw = None
    for attempt in range(2):
        suffix = "" if attempt == 0 else "\n上次输出无效；仅输出合法 JSON 对象。"
        try:
            response = call_llm(provider, api_key, model, system + suffix,
                                json.dumps(payload, ensure_ascii=False), temperature=0.1)
        except Exception as exc:
            if not _is_transient_llm_error(exc):
                raise
            response = ""
        raw = _parse_json(response)
        if raw is not None:
            break
    valid_sections = {str(x.get("section_id")) for x in outline.get("sections", [])}
    valid_claims = {str(x.get("claim_id")) for x in argument_plan.get("claims", [])}
    valid_cases = {str(x.get("case_id")) for x in selected_cases.get("cases", [])}
    if raw is None:
        dimensions["research_alignment"] = "review_required"
        findings.append(_issue(
            "quality_review_unavailable", dimension="research_alignment",
            severity="medium", priority="P1",
            reason="学术质量模型未返回可解析结果；确定性门禁仍已执行。",
            recommended_action="恢复模型连接后只重跑学术质量评估。",
            repair_action="rewrite"))
    if raw:
        for name, status in (raw.get("dimensions") or {}).items():
            if name in dimensions and status in STATUSES:
                dimensions[name] = status
        for item in raw.get("findings") or []:
            if not isinstance(item, dict):
                continue
            dimension = str(item.get("dimension") or "")
            if dimension not in dimensions:
                continue
            section_id = str(item.get("section_id") or "")
            claim_id = str(item.get("claim_id") or "")
            case_id = str(item.get("case_id") or "")
            severity = str(item.get("severity") or "medium").lower()
            if severity not in SEVERITIES:
                severity = "medium"
            priority = str(item.get("priority") or "P2").upper()
            if priority not in PRIORITIES:
                priority = "P2"
            repair_action = str(item.get("repair_action") or "rewrite")
            if repair_action not in (
                    "rewrite", "replace_case", "narrow", "downgrade", "remove",
                    "add_missing_problem_analysis", "add_process_evidence",
                    "narrow_claim", "replace_strategy_label_with_mechanism",
                    "add_theory_case_mapping", "add_translation_effect_explanation",
                    "remove_fake_process_history",
                    "downgrade_unsupported_quality_claim", "bound_case_conclusion"):
                repair_action = "rewrite"
            if repair_action == "replace_case" and not case_id:
                # A replacement needs a concrete selected case; without one the
                # finding can only be addressed by rewriting the section prose.
                repair_action = "rewrite"
            reason = str(item.get("reason") or "").strip()
            if not reason:
                continue
            findings.append(_issue(
                str(item.get("type") or "weak_analysis"), dimension=dimension,
                severity=severity, priority=priority, reason=reason,
                recommended_action=str(item.get("recommended_action") or "").strip(),
                section_id=section_id if section_id in valid_sections else None,
                claim_id=claim_id if claim_id in valid_claims else None,
                case_id=case_id if case_id in valid_cases else None,
                evidence=str(item.get("evidence") or "")[:200],
                repair_action=repair_action))
    depth_entries: Dict[str, Dict[str, Any]] = {}
    raw_depth = raw.get("case_analysis_depth") if raw else None
    if isinstance(raw_depth, dict):
        for case_id, depth_dimensions in raw_depth.items():
            if case_id not in valid_cases or not isinstance(depth_dimensions, dict):
                continue
            entry = {}
            for dimension in case_analysis.DEPTH_DIMENSIONS:
                value = depth_dimensions.get(dimension)
                if not isinstance(value, dict):
                    entry[dimension] = {"status": "missing", "reason": ""}
                    continue
                status = str(value.get("status") or "missing")
                if status not in case_analysis.DEPTH_STATUSES:
                    status = "missing"
                entry[dimension] = {
                    "status": status,
                    "reason": str(value.get("reason") or "")[:200],
                }
            depth_entries[case_id] = entry
    diagnostics["case_analysis_depth"] = depth_entries
    findings = _prioritized(findings)
    for i, item in enumerate(findings, 1):
        item["issue_id"] = f"AQ-{i:03d}"
    metrics = {
        "research_questions": len(research_model.get("research_questions", [])),
        "answered_rqs": diagnostics["rq_matrix"]["answered_rqs"],
        "unanswered_rqs": len(diagnostics["rq_matrix"]["unanswered_rqs"]),
        "global_claims": len(argument_plan.get("claims", [])),
        "orphan_claims": len(diagnostics["rq_matrix"]["orphan_claims"]),
        "selected_cases": len(selected_cases.get("cases", [])),
        "case_selection_status": selected_cases.get("selection_status", "unspecified"),
        "authentic_revision_cases": sum(1 for x in diagnostics["case_quality"]
                                         if x.get("case_type") == "authentic_revision"
                                         and x.get("case_role") == "revision_case"),
        "synthetic_contrast_cases": sum(1 for x in diagnostics["case_quality"]
                                         if x.get("case_type") == "synthetic_contrast"),
        "synthetic_case_count": sum(1 for x in diagnostics["case_quality"]
                                     if x.get("case_type") == "synthetic_contrast"),
        "synthetic_baseline_plausibility": {
            "pass": sum((x.get("synthetic_dimensions") or {}).get(
                "baseline_plausibility") == "plausible"
                for x in diagnostics["case_quality"]
                if x.get("case_type") == "synthetic_contrast"),
            "fail": sum((x.get("synthetic_dimensions") or {}).get(
                "baseline_plausibility") != "plausible"
                for x in diagnostics["case_quality"]
                if x.get("case_type") == "synthetic_contrast"),
        },
        "synthetic_materiality": {
            "pass": sum((x.get("synthetic_dimensions") or {}).get(
                "material_difference") == "pass"
                for x in diagnostics["case_quality"]),
            "fail": sum((x.get("synthetic_dimensions") or {}).get(
                "material_difference") != "pass"
                for x in diagnostics["case_quality"]
                if x.get("case_type") == "synthetic_contrast"),
        },
        "synthetic_repair_correctness": {
            "pass": sum((x.get("synthetic_dimensions") or {}).get(
                "repair_correctness") == "pass"
                for x in diagnostics["case_quality"]),
            "fail": sum((x.get("synthetic_dimensions") or {}).get(
                "repair_correctness") != "pass"
                for x in diagnostics["case_quality"]
                if x.get("case_type") == "synthetic_contrast"),
        },
        "synthetic_academic_analysis_value": {
            "pass": sum((x.get("synthetic_dimensions") or {}).get(
                "academic_analysis_value") == "pass"
                for x in diagnostics["case_quality"]
                if x.get("case_type") == "synthetic_contrast"),
            "fail": sum((x.get("synthetic_dimensions") or {}).get(
                "academic_analysis_value") != "pass"
                for x in diagnostics["case_quality"]
                if x.get("case_type") == "synthetic_contrast"),
        },
        "non_revision_cases": sum(1 for x in diagnostics["case_quality"]
                                  if x.get("case_type") == "authentic_revision"
                                  and x.get("case_role") == "non_revision_case"),
        "strong_cases": sum(1 for x in diagnostics["case_quality"] if x["class"] == "strong_case"),
        "usable_cases": sum(1 for x in diagnostics["case_quality"] if x["class"] == "usable_case"),
        "weak_cases": sum(1 for x in diagnostics["case_quality"] if x["class"] == "weak_case"),
        "redundant_cases": sum(1 for x in diagnostics["case_quality"] if x["class"] == "redundant_case"),
        "misaligned_cases": sum(1 for x in diagnostics["case_quality"] if x["class"] == "misaligned_case"),
        "paragraph_roles": diagnostics["paragraph_statistics"]["paragraph_roles"],
        "generic_paragraph_rate": diagnostics["paragraph_statistics"]["generic_rate"],
        "evidence_utilization": diagnostics["evidence_utilization"],
        "literature_grounding_status": (
            "grounded" if has_literature and all(
                x.get("evidence_grounded_status") in ("grounded", "grounded_user_material")
                for x in literature_claims.get("items", []))
            else "evidence_missing" if not literature_claims.get("items")
            else "needs_review"),
        "citation_validation_status": academic_validator.citation_validation_status(
            deterministic_validation, literature_sources, literature_evidence_artifact,
            literature_claims),
        "statistics_validation_status": academic_validator.statistics_validation_status(
            deterministic_validation),
        "case_eligibility_status": academic_validator.case_eligibility_status(
            deterministic_validation),
        "deterministic_validation_status": deterministic_validation.get("status", "unknown"),
        "cross_section_issue_count": len(diagnostics["cross_section_checks"]),
        "conclusion_support_issues": sum(
            1 for x in diagnostics["conclusion_traceability"] if x["needs_semantic_check"]),
        "finding_counts": dict(Counter(x["priority"] for x in findings)),
        "strategy_label_only_count": sum(
            1 for x in findings if x["type"] == "strategy_label_without_mechanism"),
        "unsupported_quality_effect_count": sum(
            1 for x in findings if x["type"] == "unsupported_quality_effect"),
        "unsupported_process_claim_count": sum(
            1 for x in findings if x["type"] == "unsupported_process_claim"),
        "overgeneralized_case_conclusion_count": sum(
            1 for x in findings if x["type"] == "case_to_general_rule_overreach"),
        "theory_name_dropping_count": sum(
            1 for x in findings if x["type"] == "theory_name_dropping"),
        "case_analysis_depth_summary": {
            dimension: dict(Counter(
                entry.get(dimension, {}).get("status", "missing")
                for entry in depth_entries.values()))
            for dimension in case_analysis.DEPTH_DIMENSIONS
        },
    }
    if case_analysis_plans:
        mappings = [p.get("theory_mapping") for p in
                    case_analysis_plans.get("plans", [])
                    if p.get("theory_mapping")]
        concepts = Counter(m.get("concept") for m in mappings)
        if mappings and len(mappings) > 1 \
                and max(concepts.values()) == len(mappings):
            findings.append(_issue(
                "same_theory_reused_mechanically", dimension="theory_case_fit",
                severity="low", priority="P2",
                reason=f"全部 {len(mappings)} 个案例使用同一理论概念"
                       f"「{mappings[0].get('concept')}」，疑似机械复用。",
                recommended_action="区分各案例中概念的具体适用条件与映射差异。"))
    artifact = {
        "schema_version": QUALITY_VERSION,
        "dimensions": dimensions,
        "metrics": metrics,
        "findings": findings,
        "diagnostics": diagnostics,
    }
    artifact["content_hash"] = stable_hash(
        {k: v for k, v in artifact.items() if k != "content_hash"})
    return artifact


def _prioritized(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(findings, key=lambda x: (
        rank.get(x["priority"], 3), severity_rank.get(x["severity"], 3),
        x.get("section_id") or "", x.get("case_id") or ""))


def quality_repair_plan(
    quality: Dict[str, Any], outline: Dict[str, Any],
) -> Dict[str, Any]:
    """Group quality findings into the smallest repairable units."""
    sections = {x["section_id"]: x for x in outline.get("sections", [])}
    plan = {"text_repairs": [], "case_replacements": []}
    for finding in quality.get("findings") or []:
        priority = finding.get("priority")
        if priority not in ("P0", "P1", "P2"):
            continue
        case_id = finding.get("case_id")
        if finding.get("repair_action") == "replace_case" and case_id:
            plan["case_replacements"].append({
                "issue_id": finding["issue_id"], "case_id": case_id,
                "section_id": finding.get("section_id"),
                "reason": finding.get("reason", ""),
            })
            continue
        if finding.get("repair_action") == "replace_case" and not case_id:
            # No concrete case to replace: treat as a section-level rewrite.
            finding = dict(finding, repair_action="rewrite")
        section_id = finding.get("section_id")
        if section_id in sections:
            plan["text_repairs"].append({
                "issue_id": finding["issue_id"], "section_id": section_id,
                "claim_id": finding.get("claim_id"),
                "case_id": case_id,
                "priority": priority,
                "repair_action": finding.get("repair_action", "rewrite"),
                "reason": finding.get("reason", ""),
                "recommended_action": finding.get("recommended_action", ""),
            })
    plan["text_repairs"].sort(key=lambda x: x["priority"])
    return plan


def select_replacement_case(
    case_id: str, claim_ids: Iterable[str], selected_cases: Dict[str, Any],
    argument_plan: Dict[str, Any], evidence: Dict[str, Any],
    synthetic_artifact: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Choose a stronger, non-redundant candidate from the pool.

    Evidence richness (finding/decision/repair/terminology) outranks the
    candidate-mining score, because length/complexity signals do not equal
    academic usefulness.
    """
    selected_ids = {str(x.get("case_id")) for x in selected_cases.get("cases", [])}
    old_case = next((x for x in selected_cases.get("cases", [])
                     if str(x.get("case_id")) == case_id), {})
    if old_case.get("case_type") == "synthetic_contrast":
        candidates = [x for x in (synthetic_artifact or {}).get("items", [])
                      if str(x.get("case_id")) not in selected_ids
                      and x.get("validation", {}).get("academic_case_eligible")]
        candidates.sort(key=lambda x: (
            x.get("difficulty", {}).get("academic_value") != "high",
            x.get("difficulty", {}).get("confidence") != "high",
            x.get("case_id")))
        return dict(candidates[0]) if candidates else None
    claims = {x["claim_id"]: x for x in argument_plan.get("claims", [])}
    claim_topics = {
        claim_id: str(claims[claim_id].get("research_question") or "")
        for claim_id in claim_ids if claim_id in claims
    }
    segs = segment_index(evidence)
    old_richness = case_quality_signals(
        segs.get(case_id) or {}, evidence.get("findings") or [])["evidence_richness"]
    candidates = []
    for candidate in evidence.get("candidate_cases", []):
        candidate_id = str(candidate.get("case_id") or "")
        if candidate_id in selected_ids:
            continue
        if candidate.get("academic_candidate_status", "eligible") != "eligible":
            continue
        segment = segs.get(candidate_id) or {}
        if not is_eligible_revision_case(segment):
            continue
        richness = case_quality_signals(segment, evidence.get("findings") or [])[
            "evidence_richness"]
        if richness <= old_richness or richness < 3:
            continue
        relevance = sum(
            1 for claim_id, topic in claim_topics.items()
            if topic and topic in " ".join(candidate.get("reasons") or []))
        candidates.append((richness, relevance, candidate.get("score", 0), candidate))
    candidates.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    if not candidates:
        return None
    return dict(candidates[0][3])


def render_quality_report(
    quality: Dict[str, Any], legacy_metrics: Optional[Dict[str, Any]] = None,
) -> str:
    lines = ["# 学术质量评估报告", ""]
    dimensions = quality.get("dimensions") or {}
    lines.append("## 维度状态")
    lines.append("")
    for name in DIMENSIONS:
        lines.append(f"- `{name}`: {dimensions.get(name, 'unknown')}")
    metrics = quality.get("metrics") or {}
    lines.extend(["", "## 度量", ""])
    for key, value in metrics.items():
        if key in ("paragraph_roles", "evidence_utilization", "finding_counts"):
            continue
        lines.append(f"- {key}: {value}")
    lines.append(f"- paragraph_roles: {metrics.get('paragraph_roles')}")
    lines.append(f"- finding_counts: {metrics.get('finding_counts')}")
    if legacy_metrics:
        lines.extend(["", "## 与旧架构对比", ""])
        for key, value in legacy_metrics.items():
            lines.append(f"- {key}: {value}")
    findings = quality.get("findings") or []
    lines.extend(["", "## 结构化发现", ""])
    if not findings:
        lines.append("无。")
    for item in findings:
        lines.append(
            f"- `{item.get('issue_id')}` [{item.get('priority')}/{item.get('severity')}] "
            f"{item.get('dimension')} · 章节 {item.get('section_id') or '-'} · "
            f"claim {item.get('claim_id') or '-'} · case {item.get('case_id') or '-'}："
            f"{item.get('reason', '')}（建议：{item.get('recommended_action', '')}）")
    lines.extend([
        "", "## 案例表", "",
        "| Case | Claim | Evidence richness | Class | Problem |",
        "|---|---|---|---|---|",
    ])
    for row in (quality.get("diagnostics") or {}).get("case_quality", []):
        richness = "-" if row.get("evidence_richness") is None \
            else f"{row['evidence_richness']}/7"
        lines.append(
            f"| {row['case_id']} | {', '.join(row['supports_claims'][:3]) or '-'} | "
            f"{richness} | {row['class']} | "
            f"{'; '.join(row['reasons'][:2]) or '-'} |")
    lines.extend([
        "", "> 本评估提供可追溯性、证据利用、论证关系、案例丰富度、内部一致性与"
        "支持强度的证据化判断；它不能裁定论文是否可发表、理论解释是否最终正确，"
        "也不能替代导师与评审人的学术判断。",
    ])
    return "\n".join(lines) + "\n"
