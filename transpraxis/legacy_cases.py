"""Recover analytical contrast cases from an earlier thesis draft.

Legacy ``初译`` text is analytical material, not translation history.  This
module only reads a DOCX and academic evidence artifacts; it never mutates the
translation state, TM, glossary, or revision records.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from docx import Document
from docx.document import Document as _Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.oxml.ns import qn

from . import academic_evidence
from . import case_provenance
from . import synthetic_cases


INVENTORY_VERSION = "legacy-case-inventory-v1"
RECOVERY_VERSION = "legacy-case-recovery-v1"
BASELINE_ORIGIN = "legacy_analytical_draft"

_EXAMPLE = re.compile(r"^例\s*[\[【（(]\s*(\d+)\s*[\]】）)]\s*$")
_FIELD = re.compile(r"^(原文|初译|改译|分析)\s*[:：]\s*(.*)$")
_HEADING = re.compile(r"^(\d+(?:\.\d+)+)\s*(.+)$")

_GROUPS = {
    "3.3.1": ("学术术语与核心概念", "术语一致性与概念显化", "lexical_polysemy", "RQ2"),
    "3.3.2": ("长句与复杂信息结构", "句法重组与逻辑显化", "information_structure", "RQ1"),
    "3.3.3": ("修辞、语用与语域", "修辞功能与评价色彩传递", "metaphor", "RQ3"),
    "3.3.4": ("专名、指代与文化指称", "互文与理论负载信息补偿", "cultural_reference", "RQ2"),
    "3.3.5": ("修辞、语用与语域", "批判性立场与评价强度再现", "pragmatic_implication", "RQ3"),
}

_ISSUES = (
    (re.compile(r"scopic regime|operative form", re.I), "理论术语的概念边界与术语链一致性"),
    (re.compile(r"planetarity|planetary communities", re.I), "planetarity／planetary community 术语链"),
    (re.compile(r"on loan", re.I), "on loan 的伦理语义而非经济义"),
    (re.compile(r"as one, without making them the same", re.I), "共同性与差异性并存的逻辑显化"),
    (re.compile(r"a matter of .* rather than", re.I), "a matter of … rather than … 对比结构"),
    (re.compile(r"world scale regimes of seeing", re.I), "regimes of seeing 的概念化表达"),
    (re.compile(r"more-than-optical", re.I), "复合限定结构 more-than-optical"),
    (re.compile(r"multiple directions", re.I), "多重方位信息的句法重组"),
    (re.compile(r"\balterity\b", re.I), "alterity 的理论概念译名"),
    (re.compile(r"multiperspectival sensorium|volumetric sensing", re.I), "sensorium 与 volumetric sensing 的概念关联"),
    (re.compile(r"\bsensorium\b", re.I), "sensorium 的技术媒介概念边界"),
    (re.compile(r"eco-medium", re.I), "eco-medium 的跨学科术语辨析"),
    (re.compile(r"postcarbon communities", re.I), "postcarbon community 的共同体概念"),
    (re.compile(r"Neganthropocene", re.I), "Neganthropocene 术语与长句逻辑"),
    (re.compile(r"flatten things.*sharpens", re.I), "flatten／sharpen 隐喻对照"),
    (re.compile(r"violent blade", re.I), "暴力刀刃意象与评价强度"),
    (re.compile(r"family resemblances", re.I), "family resemblances 的理论隐喻"),
    (re.compile(r"kill grid", re.I), "kill grid 的军事术语与暴力隐喻"),
    (re.compile(r"meaning oscillates", re.I), "meaning oscillates 的动态隐喻与句法衔接"),
    (re.compile(r"volumetrically senses|trajectory", re.I), "volumetric sensing 与 trajectory 的语境化表达"),
    (re.compile(r"terrain hugging", re.I), "terrain hugging 的触觉隐喻"),
    (re.compile(r"Gebrauchsbilder", re.I), "Gebrauchsbilder 的跨语际术语呈现"),
    (re.compile(r"relative geographies", re.I), "relative geographies 的概念边界与引语整合"),
    (re.compile(r"integrate the human.*expel", re.I), "integrate／expel 的批判性对照"),
)


def _iter_body_paragraphs(document: _Document) -> Iterable[Paragraph]:
    """Yield body and table paragraphs in document order."""
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            for row in table.rows:
                for cell in row.cells:
                    yield from cell.paragraphs


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _normalised_with_map(text: Any) -> Tuple[str, List[int]]:
    raw = str(text or "")
    chars: List[str] = []
    offsets: List[int] = []
    for index, value in enumerate(raw):
        if value == "-" and index + 1 < len(raw) and raw[index + 1].isspace():
            continue
        for char in unicodedata.normalize("NFKC", value).casefold():
            if char.isalnum():
                chars.append(char)
                offsets.append(index)
    return "".join(chars), offsets


def _normalised(text: Any) -> str:
    return _normalised_with_map(text)[0]


def _section_group(heading: str) -> Tuple[str, str]:
    for prefix, values in _GROUPS.items():
        if heading.startswith(prefix):
            return values[0], values[1]
    return "未分类", heading or "未记录"


def parse_legacy_case_inventory(document_path: Path | str) -> Dict[str, Any]:
    """Parse every numbered source/initial/revised/analysis case in a DOCX."""
    path = Path(document_path).expanduser().resolve()
    document = Document(path)
    cases: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    current_field = ""
    subsection = ""

    def finish() -> None:
        nonlocal current
        if current is None:
            return
        missing = [field for field in (
            "legacy_source", "legacy_initial", "legacy_revised", "legacy_analysis")
                   if not current.get(field)]
        current["complete"] = not missing
        current["missing_fields"] = missing
        cases.append(current)
        current = None

    for paragraph in _iter_body_paragraphs(document):
        text = _clean(paragraph.text)
        if not text:
            continue
        example = _EXAMPLE.match(text)
        if example:
            finish()
            difficulty, strategy = _section_group(subsection)
            number = int(example.group(1))
            current = {
                "legacy_case_id": f"LEGACY-{number:04d}",
                "legacy_example_number": number,
                "legacy_source": "",
                "legacy_initial": "",
                "legacy_revised": "",
                "legacy_analysis": "",
                "old_subsection": subsection,
                "old_difficulty_group": difficulty,
                "old_strategy_group": strategy,
            }
            current_field = ""
            continue
        heading = _HEADING.match(text)
        if heading and (paragraph.style.name.lower().startswith("heading")
                        or heading.group(1).startswith("3.3")):
            finish()
            subsection = text
            current_field = ""
            continue
        if current is None:
            continue
        field = _FIELD.match(text)
        if field:
            current_field = {
                "原文": "legacy_source", "初译": "legacy_initial",
                "改译": "legacy_revised", "分析": "legacy_analysis",
            }[field.group(1)]
            current[current_field] = _clean(field.group(2))
        elif current_field and not current.get(current_field):
            current[current_field] = text
    finish()

    source_counts = Counter(_normalised(x.get("legacy_source")) for x in cases
                            if x.get("legacy_source"))
    duplicate_keys = {key for key, count in source_counts.items() if count > 1}
    duplicates = [{
        "normalised_source": key,
        "legacy_example_numbers": [x["legacy_example_number"] for x in cases
                                   if _normalised(x.get("legacy_source")) == key],
    } for key in sorted(duplicate_keys)]
    summary = {
        "total_case_count": len(cases),
        "complete_source_initial_revised_count": sum(
            bool(x.get("legacy_source") and x.get("legacy_initial")
                 and x.get("legacy_revised")) for x in cases),
        "complete_four_field_count": sum(bool(x.get("complete")) for x in cases),
        "missing_field_case_count": sum(not x.get("complete") for x in cases),
        "duplicate_case_count": sum(len(x["legacy_example_numbers"]) - 1
                                    for x in duplicates),
    }
    artifact = {
        "schema_version": INVENTORY_VERSION,
        "source_document": str(path),
        "source_document_name": path.name,
        "summary": summary,
        "duplicates": duplicates,
        "cases": sorted(cases, key=lambda x: x["legacy_example_number"]),
    }
    artifact["content_hash"] = academic_evidence.stable_hash(artifact["cases"])
    return artifact


def _source_alignment(
    legacy_source: str, segments: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    needle, _ = _normalised_with_map(legacy_source)
    if not needle:
        return {"status": "rejected", "reason": "legacy_source_missing"}
    candidates = []
    for segment in segments:
        canonical = str(segment.get("source") or "")
        haystack, offsets = _normalised_with_map(canonical)
        exact_start = haystack.find(needle)
        matcher = difflib.SequenceMatcher(None, needle, haystack, autojunk=False)
        blocks = [block for block in matcher.get_matching_blocks() if block.size]
        coverage = sum(block.size for block in blocks) / max(1, len(needle))
        max_block = max((block.size for block in blocks), default=0) / max(1, len(needle))
        candidates.append({
            "segment": segment, "canonical": canonical, "offsets": offsets,
            "exact_start": exact_start, "coverage": coverage,
            "max_block": max_block, "ratio": matcher.ratio(), "blocks": blocks,
        })
    candidates.sort(key=lambda item: (
        item["exact_start"] >= 0, item["coverage"], item["max_block"], item["ratio"]),
        reverse=True)
    if not candidates:
        return {"status": "rejected", "reason": "canonical_source_missing"}
    best = candidates[0]
    exact = [item for item in candidates if item["exact_start"] >= 0]
    method = "exact_normalised_match" if best["exact_start"] >= 0 else "constrained_fuzzy_span"
    if len(exact) > 1:
        return {"status": "rejected", "reason": "ambiguous_exact_source_match"}
    second_block = candidates[1]["max_block"] if len(candidates) > 1 else 0.0
    if method == "constrained_fuzzy_span" and not (
            best["coverage"] >= 0.95 and best["max_block"] >= 0.45
            and best["max_block"] - second_block >= 0.08):
        return {
            "status": "rejected", "reason": "source_alignment_below_threshold",
            "best_coverage": round(best["coverage"], 3),
            "best_contiguous_coverage": round(best["max_block"], 3),
        }
    if best["exact_start"] >= 0:
        norm_start = best["exact_start"]
        norm_end = norm_start + len(needle)
    else:
        norm_start = best["blocks"][0].b
        last = best["blocks"][-1]
        norm_end = last.b + last.size
    offsets = best["offsets"]
    if not offsets or norm_start >= len(offsets) or norm_end <= 0:
        return {"status": "rejected", "reason": "source_span_offsets_unavailable"}
    start = offsets[norm_start]
    end = offsets[min(len(offsets) - 1, norm_end - 1)] + 1
    segment = best["segment"]
    return {
        "status": "aligned", "method": method,
        "segment_id": str(segment.get("segment_id") or ""),
        "segment_index": int(segment.get("segment_index") or 0),
        "source_span": {"start": start, "end": end,
                        "text": best["canonical"][start:end]},
        "source_alignment_confidence": round(
            1.0 if method == "exact_normalised_match"
            else (best["coverage"] + best["max_block"]) / 2, 3),
        "normalised_coverage": round(best["coverage"], 3),
        "contiguous_coverage": round(best["max_block"], 3),
    }


def _sentence_windows(text: str, maximum: int = 3) -> List[Tuple[int, int, str]]:
    spans: List[Tuple[int, int]] = []
    start = 0
    for match in re.finditer(r"[。！？](?:[”’\"])?", text):
        if text[start:match.end()].strip():
            spans.append((start, match.end()))
        start = match.end()
    if text[start:].strip():
        spans.append((start, len(text)))
    if not spans:
        return [(0, len(text), text)] if text else []
    windows = []
    for index in range(len(spans)):
        for width in range(1, min(maximum, len(spans) - index) + 1):
            left, right = spans[index][0], spans[index + width - 1][1]
            windows.append((left, right, text[left:right].strip()))
    return windows


def _target_alignment(legacy_revised: str, target: str) -> Dict[str, Any]:
    needle = _normalised(legacy_revised)
    haystack, offsets = _normalised_with_map(target)
    exact_start = haystack.find(needle) if needle else -1
    if exact_start >= 0:
        start = offsets[exact_start]
        end = offsets[exact_start + len(needle) - 1] + 1
        return {
            "status": "aligned", "method": "exact_normalised_match",
            "target_span": {"start": start, "end": end, "text": target[start:end]},
            "target_alignment_confidence": 1.0,
            "legacy_revised_compatibility": "exact_current_compatible",
        }
    windows = []
    for start, end, text in _sentence_windows(target):
        ratio = difflib.SequenceMatcher(
            None, needle, _normalised(text), autojunk=False).ratio()
        windows.append((ratio, start, end, text))
    windows.sort(key=lambda row: (row[0], -row[1]), reverse=True)
    if not windows:
        return {"status": "rejected", "reason": "current_target_missing"}
    best = windows[0]
    second = windows[1][0] if len(windows) > 1 else 0.0
    if best[0] < 0.25 or best[0] - second < 0.02:
        return {
            "status": "rejected", "reason": "current_target_alignment_below_threshold",
            "best_similarity": round(best[0], 3), "second_similarity": round(second, 3),
        }
    return {
        "status": "aligned", "method": "legacy_revised_bridge_fuzzy_match",
        "target_span": {"start": best[1], "end": best[2], "text": best[3]},
        "target_alignment_confidence": round(best[0], 3),
        "second_similarity": round(second, 3),
        "legacy_revised_compatibility": "analytically_compatible_but_text_changed",
    }


def _targeted_issue(source: str, category: str) -> str:
    for pattern, issue in _ISSUES:
        if pattern.search(source):
            return issue
    return {
        "lexical_polysemy": "术语概念边界与上下文一致性",
        "information_structure": "复杂句的信息结构与逻辑显化",
        "metaphor": "隐喻功能与评价色彩",
        "cultural_reference": "互文或理论负载表达的补偿",
        "pragmatic_implication": "批判性立场与语篇功能",
    }.get(category, "受控翻译对比")


def _group_for_case(case: Mapping[str, Any]) -> Tuple[str, str, str, str]:
    heading = str(case.get("old_subsection") or "")
    for prefix, values in _GROUPS.items():
        if heading.startswith(prefix):
            return values
    return ("未分类", "受控对比分析", "information_structure", "RQ1")


def _authentic_match(
    legacy: Mapping[str, Any], segment: Mapping[str, Any],
    revision_candidates: Mapping[str, Mapping[str, Any]],
) -> bool:
    segment_id = str(segment.get("segment_id") or "")
    candidate = revision_candidates.get(segment_id) or {}
    if candidate.get("case_type") != "authentic_revision" \
            or candidate.get("historical") is not True:
        return False
    initial = _normalised(segment.get("initial_target"))
    final = _normalised(segment.get("final_target"))
    return bool(_normalised(legacy.get("legacy_initial")) in initial
                and _normalised(legacy.get("legacy_revised")) in final)


def recover_legacy_cases(
    inventory: Mapping[str, Any], evidence: Mapping[str, Any],
    call_llm: Callable, provider: str, api_key: str, model: str,
    qa_source_segment_ids: Optional[Iterable[str]] = None,
    cached_recovery: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Align legacy cases and independently apply the four final-report gates."""
    segments = list((evidence.get("project_evidence") or {}).get("segments") or [])
    segment_by_id = {str(x.get("segment_id")): x for x in segments}
    revision_candidates = academic_evidence.candidate_index(dict(evidence))
    qa_ids = {str(x) for x in qa_source_segment_ids or []}
    prepared: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for legacy in inventory.get("cases") or []:
        number = int(legacy.get("legacy_example_number") or 0)
        case_id = f"LSC-{number:04d}"
        if not legacy.get("complete"):
            rejected.append({"case_id": case_id, "legacy": dict(legacy),
                             "reason": "legacy_case_missing_fields"})
            continue
        source_alignment = _source_alignment(str(legacy.get("legacy_source") or ""), segments)
        if source_alignment.get("status") != "aligned":
            rejected.append({"case_id": case_id, "legacy": dict(legacy),
                             "source_alignment": source_alignment,
                             "reason": source_alignment.get("reason")})
            continue
        segment_id = str(source_alignment["segment_id"])
        segment = segment_by_id[segment_id]
        target_alignment = _target_alignment(
            str(legacy.get("legacy_revised") or ""), str(segment.get("final_target") or ""))
        if target_alignment.get("status") != "aligned":
            rejected.append({"case_id": case_id, "legacy": dict(legacy),
                             "source_alignment": source_alignment,
                             "target_alignment": target_alignment,
                             "reason": target_alignment.get("reason")})
            continue
        if segment.get("integrity_flags"):
            rejected.append({"case_id": case_id, "legacy": dict(legacy),
                             "source_alignment": source_alignment,
                             "target_alignment": target_alignment,
                             "reason": "integrity_flagged_source_segment"})
            continue
        difficulty, strategy, category, rq = _group_for_case(legacy)
        source_text = str((source_alignment.get("source_span") or {}).get("text") or "")
        target_text = str((target_alignment.get("target_span") or {}).get("text") or "")
        issue = _targeted_issue(str(legacy.get("legacy_source") or ""), category)
        authentic = _authentic_match(legacy, segment, revision_candidates)
        prepared.append(case_provenance.with_provenance({
            "case_id": case_id,
            "case_type": "authentic_revision" if authentic else "synthetic_contrast",
            "legacy_example_number": number,
            "source_segment_id": segment_id,
            "segment_index": int(segment.get("segment_index") or 0),
            "source_text": source_text,
            "legacy_source": legacy.get("legacy_source"),
            "legacy_revised": legacy.get("legacy_revised"),
            "legacy_analysis_seed": legacy.get("legacy_analysis"),
            "old_subsection": legacy.get("old_subsection"),
            "old_difficulty_group": legacy.get("old_difficulty_group"),
            "old_strategy_group": legacy.get("old_strategy_group"),
            "source_alignment": source_alignment,
            "target_alignment": target_alignment,
            "shares_segment_with_qa_candidate": segment_id in qa_ids,
            "target_contrast_text": target_text,
            "final_target": target_text,
            "difficulty_group": difficulty,
            "strategy_group": strategy,
            "research_questions": [rq],
            "targeted_issue": issue,
            "difficulty": {
                "category": category, "trigger": issue, "reason": issue,
                "academic_value": "high", "confidence": "high",
            },
            "historical": bool(authentic),
            "generated_for_analysis": not authentic,
            "baseline_origin": None if authentic else BASELINE_ORIGIN,
            "source_provenance": "project_source",
            "target_provenance": "project_current_target",
            "synthetic_baseline": None if authentic else {
                "text": legacy.get("legacy_initial"),
                "provenance": "analytical_simulation",
                "baseline_origin": BASELINE_ORIGIN,
                "legacy_example_number": number,
                "source_document": inventory.get("source_document_name"),
                "generation_status": "recovered",
                "targeted_issue": issue,
            },
            "provenance": {
                "historical": bool(authentic),
                "generated_for_analysis": not authentic,
                "source_provenance": "project_source",
                "target_provenance": "project_current_target",
                "analytical_provenance": None if authentic else {
                    "baseline_origin": BASELINE_ORIGIN,
                    "source_document": inventory.get("source_document_name"),
                    "legacy_example_number": number,
                },
            },
        }))

    cached_reviews = {}
    for old in (cached_recovery or {}).get("items") or []:
        if old.get("case_type") != "synthetic_contrast" or not old.get(
                "synthetic_evidence"):
            continue
        evidence_status = old.get("synthetic_evidence") or {}
        repair = (old.get("validation") or {}).get("repair_evidence") or {}
        cached_reviews[str(old.get("case_id") or "")] = {
            "case_id": old.get("case_id"),
            "plausibility": evidence_status.get("baseline_plausibility"),
            "materiality": evidence_status.get("material_difference"),
            "repair_correctness": evidence_status.get("repair_correctness"),
            "academic_analysis_value": evidence_status.get("academic_analysis_value"),
            "baseline_issue_span": repair.get("baseline_issue_span"),
            "final_repair_span": repair.get("final_repair_span"),
            "contrast_rationale": old.get("contrast_rationale") or
            evidence_status.get("academic_analysis_reason"),
            "rejection_reason": (old.get("validation") or {}).get("reason"),
            "duplicate_with_case_id": "",
        }
    synthetic_inputs = [x for x in prepared if x["case_type"] == "synthetic_contrast"
                        and x["case_id"] not in cached_reviews]
    system = (
        "Independently validate recovered analytical translation contrasts for an MTI report. "
        "The legacy initial is NOT historical evidence; it is a candidate simulated baseline. "
        "Judge four gates independently: plausibility (a competent human might produce it), "
        "materiality (the difference is substantive and serves the targeted issue), "
        "repair_correctness (the CURRENT project target offers a reasonable, defensible treatment "
        "of that issue), and academic_analysis_value (the contrast supports non-surface, "
        "case-specific MTI analysis tied to the stated RQ and is not a duplicate). Translation "
        "does not have one uniquely correct answer: do not fail a plausible alternative merely "
        "because it is not plainly wrong, and do not require the current target to be uniquely best. "
        "Fail when the current target does not actually address the stated issue or when the old "
        "analysis depended on an obsolete revised wording. Return JSON only: "
        "{\"validations\":[{\"case_id\":\"LSC-...\",\"plausibility\":\"pass|fail\","
        "\"materiality\":\"pass|fail\",\"repair_correctness\":\"pass|fail\","
        "\"academic_analysis_value\":\"pass|fail\","
        "\"baseline_issue_span\":\"exact contiguous baseline text\","
        "\"final_repair_span\":\"exact contiguous current-target text\","
        "\"contrast_rationale\":\"...\",\"rejection_reason\":\"...\","
        "\"duplicate_with_case_id\":\"\"}]}"
    )
    raw = synthetic_cases._call_json(
        call_llm, provider, api_key, model, system, {"cases": [{
            "case_id": x["case_id"], "source": x["source_text"],
            "legacy_simulated_initial": x["synthetic_baseline"]["text"],
            "current_project_target": x["target_contrast_text"],
            "legacy_revised_for_comparison_only": x["legacy_revised"],
            "targeted_issue": x["targeted_issue"],
            "research_questions": x["research_questions"],
            "legacy_analysis_seed": x["legacy_analysis_seed"],
        } for x in synthetic_inputs]}, 0.1) if synthetic_inputs else {
            "_call_status": "skipped", "validations": []}
    reviews = dict(cached_reviews)
    reviews.update({str(x.get("case_id")): x for x in raw.get("validations") or []
                    if isinstance(x, Mapping)})

    items: List[Dict[str, Any]] = []
    for case in prepared:
        if case["case_type"] == "authentic_revision":
            case.update({
                "validation": {"academic_case_eligible": True,
                               "authentic_provenance_match": True,
                               "rejected_reasons": []},
                "current_final_compatibility": "exact_current_compatible",
            })
            items.append(case)
            continue
        review = reviews.get(case["case_id"]) or {}
        baseline = str(case["synthetic_baseline"]["text"] or "")
        target = str(case["target_contrast_text"] or "")
        issue_span = str(review.get("baseline_issue_span") or "").strip()
        repair_span = str(review.get("final_repair_span") or "").strip()
        gates = {
            "baseline_plausibility": review.get("plausibility") == "pass",
            "material_difference": review.get("materiality") == "pass",
            "repair_correctness": review.get("repair_correctness") == "pass",
            "academic_analysis_value": review.get("academic_analysis_value") == "pass",
        }
        requirements = {
            "source_aligned": case["source_alignment"].get("status") == "aligned",
            "current_target_bound": case["target_alignment"].get("status") == "aligned",
            "meaningful_contrast": academic_evidence.has_meaningful_revision(baseline, target),
            "baseline_issue_span_grounded": bool(issue_span and (
                issue_span in baseline or _normalised(issue_span) in _normalised(baseline))),
            "final_repair_span_grounded": bool(repair_span and (
                repair_span in target or _normalised(repair_span) in _normalised(target))),
            "repair_span_materially_changed": academic_evidence.has_meaningful_revision(
                issue_span, repair_span),
            **gates,
        }
        if not requirements["repair_span_materially_changed"]:
            gates["material_difference"] = False
            requirements["material_difference"] = False
        duplicate = str(review.get("duplicate_with_case_id") or "").strip()
        if duplicate:
            requirements["academic_analysis_value"] = False
        eligible = all(requirements.values())
        rejected_reasons = [key for key, passed in requirements.items() if not passed]
        if duplicate:
            rejected_reasons.append(f"duplicate_with:{duplicate}")
        compatibility = str(case["target_alignment"].get(
            "legacy_revised_compatibility") or "")
        if not eligible:
            compatibility = "obsolete"
        case.update({
            "baseline_plausibility": {
                "status": "plausible" if gates["baseline_plausibility"] else "implausible",
                "reason": str(review.get("contrast_rationale") or "")[:700],
            },
            "error": {
                "category": case["difficulty"]["category"],
                "diagnosis": str(review.get("contrast_rationale") or "")[:700],
                "source_evidence_span": case["targeted_issue"],
                "materiality": "moderate" if gates["material_difference"] else "none",
            },
            "optimized_translation": {
                "text": target, "provenance": "project_current_target",
                "generation_status": "project_target",
            },
            "synthetic_evidence": {
                "historical": False,
                "generated_for_analysis": True,
                "baseline_plausibility": "pass" if gates["baseline_plausibility"] else "fail",
                "material_difference": "pass" if gates["material_difference"] else "fail",
                "repair_correctness": "pass" if gates["repair_correctness"] else "fail",
                "academic_analysis_value": "pass" if gates["academic_analysis_value"] else "fail",
                "generation_reason": case["targeted_issue"],
                "targeted_issue": case["targeted_issue"],
                "academic_analysis_reason": str(review.get("contrast_rationale") or "")[:700],
            },
            "validation": {
                "academic_case_eligible": eligible,
                "requirements": requirements,
                "repair_evidence": {"baseline_issue_span": issue_span,
                                    "final_repair_span": repair_span},
                "reason": str(review.get("contrast_rationale") or
                              review.get("rejection_reason") or "")[:700],
                "rejected_reasons": rejected_reasons,
            },
            "current_final_compatibility": compatibility,
            "contrast_rationale": str(review.get("contrast_rationale") or "")[:700],
            "limitations": [
                "该模拟初译来自前期论文案例设计，不属于项目真实修订历史。",
                "当前译文是一种可辩护处理，不据此声称其为唯一正确答案。",
            ],
        })
        items.append(case)

    all_items = [*items, *rejected]
    eligible_items = [x for x in items if x.get("validation", {}).get(
        "academic_case_eligible")]
    metrics = {
        "legacy_case_count": len(inventory.get("cases") or []),
        "source_aligned_count": sum(x.get("source_alignment", {}).get("status") == "aligned"
                                    for x in all_items),
        "current_final_exact_count": sum(x.get("current_final_compatibility") ==
                                         "exact_current_compatible" for x in all_items),
        "current_final_compatible_count": sum(x.get("current_final_compatibility") in {
            "exact_current_compatible", "analytically_compatible_but_text_changed"}
                                              for x in all_items),
        "four_gate_pass_count": len(eligible_items),
        "rejected_count": len(all_items) - len(eligible_items),
        "authentic_match_count": sum(x.get("case_type") == "authentic_revision"
                                     for x in eligible_items),
        "legacy_synthetic_pass_count": sum(x.get("case_type") == "synthetic_contrast"
                                           for x in eligible_items),
        "synthetic_baseline_plausibility": {
            "pass": sum(x.get("synthetic_evidence", {}).get("baseline_plausibility") == "pass"
                        for x in items),
            "fail": sum(x.get("case_type") == "synthetic_contrast" and
                        x.get("synthetic_evidence", {}).get("baseline_plausibility") != "pass"
                        for x in items),
        },
        "synthetic_materiality": {
            "pass": sum(x.get("synthetic_evidence", {}).get("material_difference") == "pass"
                        for x in items),
            "fail": sum(x.get("case_type") == "synthetic_contrast" and
                        x.get("synthetic_evidence", {}).get("material_difference") != "pass"
                        for x in items),
        },
        "synthetic_repair_correctness": {
            "pass": sum(x.get("synthetic_evidence", {}).get("repair_correctness") == "pass"
                        for x in items),
            "fail": sum(x.get("case_type") == "synthetic_contrast" and
                        x.get("synthetic_evidence", {}).get("repair_correctness") != "pass"
                        for x in items),
        },
        "synthetic_academic_analysis_value": {
            "pass": sum(x.get("synthetic_evidence", {}).get("academic_analysis_value") == "pass"
                        for x in items),
            "fail": sum(x.get("case_type") == "synthetic_contrast" and
                        x.get("synthetic_evidence", {}).get("academic_analysis_value") != "pass"
                        for x in items),
        },
    }
    artifact = {
        "schema_version": RECOVERY_VERSION,
        "source_document": inventory.get("source_document"),
        "inventory_content_hash": inventory.get("content_hash"),
        "pipeline_status": "complete" if raw.get("_call_status") in {"ok", "skipped"}
        else "failed",
        "model_call_status": raw.get("_call_status"),
        "model_call_error": raw.get("_call_error", ""),
        "metrics": metrics,
        "items": all_items,
    }
    artifact["content_hash"] = academic_evidence.stable_hash(all_items)
    return artifact


def merge_synthetic_artifacts(
    legacy_recovery: Optional[Mapping[str, Any]],
    newly_generated: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Combine validated synthetic sources, preserving the required preference order."""
    items: List[Dict[str, Any]] = []
    seen = set()
    for origin, artifact in ((BASELINE_ORIGIN, legacy_recovery),
                             ("newly_generated", newly_generated)):
        for raw in (artifact or {}).get("items") or []:
            if raw.get("case_type") != "synthetic_contrast":
                continue
            case = case_provenance.with_provenance(raw)
            case_id = str(case.get("case_id") or "")
            if not case_id or case_id in seen:
                continue
            seen.add(case_id)
            case.setdefault("baseline_origin", origin)
            if isinstance(case.get("synthetic_baseline"), Mapping):
                case["synthetic_baseline"] = {
                    **case["synthetic_baseline"],
                    "baseline_origin": case.get("baseline_origin") or origin,
                }
            baseline_text = str((case.get("synthetic_baseline") or {}).get(
                "text") or "").rstrip()
            if origin == "newly_generated" and re.search(r"[，,:：;；]$", baseline_text):
                validation = dict(case.get("validation") or {})
                rejected = list(validation.get("rejected_reasons") or [])
                if "baseline_truncated" not in rejected:
                    rejected.append("baseline_truncated")
                validation.update(
                    academic_case_eligible=False, rejected_reasons=rejected)
                evidence_status = dict(case.get("synthetic_evidence") or {})
                evidence_status["baseline_plausibility"] = "fail"
                case.update(validation=validation,
                            synthetic_evidence=evidence_status)
            items.append(case)
    metrics = {
        "synthetic_case_count": sum(x.get("validation", {}).get(
            "academic_case_eligible") for x in items),
        "legacy_synthetic_case_count": sum(
            x.get("baseline_origin") == BASELINE_ORIGIN and x.get(
                "validation", {}).get("academic_case_eligible") for x in items),
        "newly_generated_synthetic_case_count": sum(
            x.get("baseline_origin") == "newly_generated" and x.get(
                "validation", {}).get("academic_case_eligible") for x in items),
    }
    for gate in ("baseline_plausibility", "material_difference",
                 "repair_correctness", "academic_analysis_value"):
        metrics[f"synthetic_{gate}"] = {
            "pass": sum(x.get("synthetic_evidence", {}).get(gate) == "pass" for x in items),
            "fail": sum(x.get("synthetic_evidence", {}).get(gate) != "pass" for x in items),
        }
    artifact = {
        "schema_version": "combined-synthetic-validation-v1",
        "pipeline_status": "complete",
        "preference_order": [BASELINE_ORIGIN, "newly_generated"],
        "metrics": metrics,
        "items": items,
    }
    artifact["content_hash"] = academic_evidence.stable_hash(items)
    return artifact


def apply_manual_reviews(
    recovery: Mapping[str, Any], reviews: Mapping[str, Any],
) -> Dict[str, Any]:
    """Apply auditable human/agent gate decisions without changing baselines."""
    review_rows = reviews.get("reviews") or []
    by_id = {str(x.get("case_id") or ""): x for x in review_rows
             if isinstance(x, Mapping) and x.get("case_id")}
    items: List[Dict[str, Any]] = []
    requirement_keys = {
        "baseline_plausibility": "baseline_plausibility",
        "material_difference": "material_difference",
        "repair_correctness": "repair_correctness",
        "academic_analysis_value": "academic_analysis_value",
    }
    for raw in recovery.get("items") or []:
        case = case_provenance.with_provenance(raw)
        review = by_id.get(str(case.get("case_id") or ""))
        if not review or case.get("case_type") != "synthetic_contrast":
            items.append(case)
            continue
        evidence_status = dict(case.get("synthetic_evidence") or {})
        validation = dict(case.get("validation") or {})
        requirements = dict(validation.get("requirements") or {})
        for gate, value in (review.get("gate_overrides") or {}).items():
            if gate not in requirement_keys or value not in {"pass", "fail"}:
                continue
            evidence_status[gate] = value
            requirements[requirement_keys[gate]] = value == "pass"
        eligible = bool(requirements) and all(requirements.values())
        reason = str(review.get("reason") or "manual academic review")[:700]
        rejected_reasons = [str(x) for x in validation.get("rejected_reasons") or []
                            if not str(x).startswith("manual_review:")]
        if not eligible:
            rejected_reasons.append(f"manual_review:{reason}")
            case["current_final_compatibility"] = "obsolete"
        validation.update({
            "requirements": requirements,
            "academic_case_eligible": eligible,
            "rejected_reasons": rejected_reasons,
            "reason": str(review.get("rationale_override") or reason)[:700],
        })
        if review.get("rationale_override"):
            case["contrast_rationale"] = str(review["rationale_override"])[:700]
            evidence_status["academic_analysis_reason"] = case["contrast_rationale"]
        case = case_provenance.review_case(
            case, "approved" if eligible else "rejected", reason)
        case.update({
            "synthetic_evidence": evidence_status,
            "validation": validation,
            "manual_review": {
                "status": "pass" if eligible else "reject",
                "reason": reason,
                "gate_overrides": dict(review.get("gate_overrides") or {}),
                "reviewer": str(review.get("reviewer") or "user_requested_manual_audit"),
            },
        })
        items.append(case)

    legacy_count = int((recovery.get("metrics") or {}).get(
        "legacy_case_count") or len(items))
    eligible_items = [x for x in items if x.get("validation", {}).get(
        "academic_case_eligible")]
    synthetic_items = [x for x in items if x.get("case_type") == "synthetic_contrast"]
    metrics = {
        **dict(recovery.get("metrics") or {}),
        "source_aligned_count": sum(x.get("source_alignment", {}).get("status") == "aligned"
                                    for x in items),
        "current_final_exact_count": sum(x.get("current_final_compatibility") ==
                                         "exact_current_compatible" for x in items),
        "current_final_compatible_count": sum(x.get("current_final_compatibility") in {
            "exact_current_compatible", "analytically_compatible_but_text_changed"}
                                              for x in items),
        "four_gate_pass_count": len(eligible_items),
        "rejected_count": legacy_count - len(eligible_items),
        "authentic_match_count": sum(x.get("case_type") == "authentic_revision"
                                     for x in eligible_items),
        "legacy_synthetic_pass_count": sum(x.get("case_type") == "synthetic_contrast"
                                           for x in eligible_items),
    }
    for field, label in (
            ("baseline_plausibility", "synthetic_baseline_plausibility"),
            ("material_difference", "synthetic_materiality"),
            ("repair_correctness", "synthetic_repair_correctness"),
            ("academic_analysis_value", "synthetic_academic_analysis_value")):
        metrics[label] = {
            "pass": sum(x.get("synthetic_evidence", {}).get(field) == "pass"
                        for x in synthetic_items),
            "fail": sum(x.get("synthetic_evidence", {}).get(field) != "pass"
                        for x in synthetic_items),
        }
    artifact = {**dict(recovery), "metrics": metrics, "items": items,
                "manual_review_artifact": reviews.get("source") or
                reviews.get("schema_version") or "inline"}
    artifact["content_hash"] = academic_evidence.stable_hash(items)
    return artifact


def recovery_report_markdown(recovery: Mapping[str, Any]) -> str:
    metrics = recovery.get("metrics") or {}
    items = list(recovery.get("items") or [])
    lines = [
        "# Legacy Case Recovery Report", "",
        f"- 旧论文案例总数：{metrics.get('legacy_case_count', 0)}",
        f"- 成功 source-aligned：{metrics.get('source_aligned_count', 0)}",
        f"- legacy revised 与 current target 精确一致：{metrics.get('current_final_exact_count', 0)}",
        f"- current-final-compatible：{metrics.get('current_final_compatible_count', 0)}",
        f"- 四门 gate PASS：{metrics.get('four_gate_pass_count', 0)}",
        f"- validated legacy synthetic：{metrics.get('legacy_synthetic_pass_count', 0)}",
        f"- authentic provenance match：{metrics.get('authentic_match_count', 0)}",
        f"- rejected：{metrics.get('rejected_count', 0)}", "",
        "| legacy case | source alignment | current final | plausibility | materiality | repair | analysis value | status |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in sorted(items, key=lambda x: int(
            x.get("legacy_example_number") or x.get("legacy", {}).get(
                "legacy_example_number") or 0)):
        evidence = item.get("synthetic_evidence") or {}
        eligible = item.get("validation", {}).get("academic_case_eligible")
        reason = "; ".join(item.get("validation", {}).get("rejected_reasons") or []) \
            or str(item.get("reason") or "")
        lines.append(
            f"| {item.get('case_id')} | {item.get('source_alignment', {}).get('method', item.get('source_alignment', {}).get('reason', 'fail'))} "
            f"| {item.get('current_final_compatibility', item.get('target_alignment', {}).get('reason', 'unbound'))} "
            f"| {evidence.get('baseline_plausibility', 'n/a')} "
            f"| {evidence.get('material_difference', 'n/a')} "
            f"| {evidence.get('repair_correctness', 'n/a')} "
            f"| {evidence.get('academic_analysis_value', 'n/a')} "
            f"| {'PASS' if eligible else 'REJECT: ' + reason} |")
    return "\n".join(lines).rstrip() + "\n"
