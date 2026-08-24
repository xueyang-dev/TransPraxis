"""Canonical evidence store for MTI academic writing.

This module is deliberately deterministic.  It scans the complete saved
translation state, assigns stable identities, computes project statistics and
mines an explainable pool of academically useful candidate cases.  It never
asks a model to count, invent missing history, or verify literature.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import assets
from . import report_evidence

SCHEMA_VERSION = "academic-evidence-v5"
ALLOWED_SOURCE_STATUSES = {
    "metadata_verified", "user_provided", "imported_unverified", "candidate",
    "rejected",
}
CITABLE_SOURCE_STATUSES = {"metadata_verified", "user_provided"}
ALLOWED_CONTENT_STATUSES = {
    "full_text_available", "partial_text_available", "notes_only", "metadata_only",
}

_LEGACY_SOURCE_STATUS = {
    "verified": "metadata_verified",
    "user_provided": "user_provided",
    "imported_notes": "imported_unverified",
    "unverified_candidate": "candidate",
}

_SUBORDINATION = re.compile(
    r"\b(?:although|because|before|after|while|whereas|which|that|who|whom|"
    r"whose|when|where|if|unless|since|as|despite|whether)\b",
    re.IGNORECASE,
)
_PASSIVE = re.compile(
    r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+\s+){0,2}\w+(?:ed|en)\b",
    re.IGNORECASE,
)


def stable_hash(value: Any) -> str:
    """Stable SHA-256 for JSON-compatible academic artifacts."""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalized_translation_target(value: Any, *, ignore_punctuation: bool = False) -> str:
    """Conservatively normalize a saved translation for revision eligibility."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    if ignore_punctuation:
        text = "".join(ch for ch in text
                       if not ch.isspace()
                       and not unicodedata.category(ch).startswith(("P", "Z")))
    else:
        text = re.sub(r"\s+", "", text)
    return text.casefold()


def has_meaningful_revision(
    initial: Any, final: Any, *, allow_formatting_revision: bool = False,
) -> bool:
    """True only for a real lexical/content initial→final target change.

    Whitespace and punctuation-only differences remain non-revision cases.
    """
    if initial is None or final is None:
        return False
    initial_text = normalized_translation_target(initial)
    final_text = normalized_translation_target(final)
    if not initial_text or not final_text or initial_text == final_text:
        return False
    content_changed = normalized_translation_target(
        initial, ignore_punctuation=True) != normalized_translation_target(
            final, ignore_punctuation=True)
    return content_changed or allow_formatting_revision


def case_role(segment: Dict[str, Any]) -> str:
    return "revision_case" if has_meaningful_revision(
        segment.get("initial_target"), segment.get("final_target")) \
        else "non_revision_case"


def is_eligible_revision_case(segment: Dict[str, Any]) -> bool:
    """A textual delta is core-eligible only when no integrity flag is present."""
    return has_meaningful_revision(
        segment.get("initial_target"), segment.get("final_target")) \
        and not segment.get("integrity_flags")


def normalize_literature_registry(
    sources: Optional[Iterable[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Normalize a pragmatic literature registry without inventing metadata."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for i, raw in enumerate(sources or []):
        if not isinstance(raw, dict):
            continue
        source_id = str(raw.get("source_id") or f"source-{i + 1:03d}").strip()
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        status = str(raw.get("verification_status") or raw.get("source_status")
                     or "candidate").strip()
        status = _LEGACY_SOURCE_STATUS.get(status, status)
        if status not in ALLOWED_SOURCE_STATUSES:
            status = "candidate"
        authors = raw.get("authors") or []
        if isinstance(authors, str):
            authors = [x.strip() for x in re.split(r"[;；]", authors) if x.strip()]
        citation = raw.get("citation_metadata")
        if not isinstance(citation, dict):
            citation = raw.get("citation") if isinstance(raw.get("citation"), dict) else {}
        citation = dict(citation)
        if isinstance(citation.get("authors"), str):
            citation["authors"] = [x.strip() for x in re.split(
                r"[;；]", citation["authors"]) if x.strip()]
        notes = raw.get("notes") or []
        if isinstance(notes, str):
            notes = [notes]
        excerpts = raw.get("manual_excerpts") or []
        if isinstance(excerpts, str):
            excerpts = [excerpts]
        extracted = raw.get("extracted_passages") or []
        if isinstance(extracted, str):
            extracted = [extracted]
        concepts = raw.get("concepts") or []
        if isinstance(concepts, str):
            concepts = [x.strip() for x in re.split(r"[;；,，]", concepts) if x.strip()]
        content_status = str(raw.get("content_availability") or "").strip()
        if content_status not in ALLOWED_CONTENT_STATUSES:
            if raw.get("content") or raw.get("source_text") or raw.get("local_source_path"):
                content_status = "full_text_available"
            elif excerpts or extracted:
                content_status = "partial_text_available"
            elif notes:
                content_status = "notes_only"
            else:
                content_status = "metadata_only"
        citation_allowed = bool(raw.get(
            "citation_allowed",
            str(raw.get("allowed_citation_status") or "") == "allowed"
            or status in CITABLE_SOURCE_STATUSES,
        ))
        entry = {
            "source_id": source_id,
            "title": str(raw.get("title") or "").strip(),
            "authors": [str(x).strip() for x in authors if str(x).strip()],
            "year": raw.get("year"),
            "source_type": str(raw.get("source_type") or "unspecified").strip(),
            "citation_metadata": citation,
            "local_source_path": str(raw.get("local_source_path") or "").strip() or None,
            "import_identity": raw.get("import_identity") or None,
            "verification_status": status,
            "allowed_citation_status": "allowed" if citation_allowed else "not_allowed",
            "content_availability": content_status,
            "concepts": [str(x).strip() for x in concepts
                         if str(x).strip()],
            "notes": notes,
            "manual_excerpts": excerpts,
            "extracted_passages": extracted,
            "content": raw.get("content", raw.get("source_text")),
            "content_format": str(raw.get("content_format") or "").strip() or None,
            "citation_allowed": citation_allowed,
            "verification": raw.get("verification") or None,
        }
        # User-provided metadata may be cited, but remains visibly distinct from
        # independently verified literature.
        if status not in CITABLE_SOURCE_STATUSES or status == "rejected" or not (
                entry["title"] and entry["authors"] and entry["year"]):
            entry["citation_allowed"] = False
            entry["allowed_citation_status"] = "not_allowed"
        out.append(entry)
    return out


def _location(profile: Optional[Dict[str, Any]], index: int) -> Dict[str, Any]:
    location = {"paragraph": index, "section_id": None, "chapter": None,
                "topic": None, "recorded": False}
    for section in (profile or {}).get("sections") or []:
        start, end = section.get("start_segment"), section.get("end_segment")
        if isinstance(start, int) and isinstance(end, int) and start <= index <= end:
            location.update({
                "section_id": section.get("section_id"),
                "chapter": section.get("section_id"),
                "topic": section.get("topic"),
                "recorded": True,
            })
            break
    return location


def _zone(index: int, total: int) -> str:
    if total <= 1:
        return "beginning"
    ratio = index / max(1, total - 1)
    if ratio < 1 / 3:
        return "beginning"
    if ratio < 2 / 3:
        return "middle"
    return "end"


def _term_density(source: str, glossary: Iterable[Dict[str, Any]]) -> Tuple[int, List[str]]:
    folded = source.casefold()
    ids = []
    for term in glossary:
        needle = str(term.get("source") or "").strip().casefold()
        if needle and needle in folded:
            ids.append(str(term.get("id") or needle))
    return len(ids), ids


def _candidate_features(
    segment: Dict[str, Any],
    glossary: List[Dict[str, Any]],
) -> Dict[str, Any]:
    source = segment["source"]
    findings = segment["process_evidence"]["findings"]
    initial = segment.get("initial_target")
    final = segment.get("final_target") or ""
    term_count, term_ids = _term_density(source, glossary)
    punctuation = len(re.findall(r"[,;:—–\-()\[\]\"“”‘’]", source))
    clauses = len(_SUBORDINATION.findall(source))
    blocking = sum(f.get("severity") == "blocking" for f in findings)
    actionable = sum(f.get("severity") == "actionable" for f in findings)
    informational = sum(f.get("severity") == "informational" for f in findings)
    revised = has_meaningful_revision(initial, final)
    repair_history = bool(segment["process_evidence"].get("repair_history"))
    human_actions = bool(segment["process_evidence"].get("human_actions"))
    system_actions = bool(segment["process_evidence"].get("system_actions"))
    repaired = bool(revised and (repair_history or human_actions or system_actions))
    conflict = any(bool(f.get("conflict")) for f in findings)
    complete_chain = bool(source and revised and findings and repaired)
    integrity_flags = list(segment.get("integrity_flags") or [])

    score = 0.0
    reasons: List[str] = []
    if complete_chain:
        score += 40
        reasons.append("complete_translation_evidence_chain")
    if blocking:
        score += 24 + min(blocking, 2)
        reasons.append("blocking_finding")
    if actionable:
        score += 20 + min(actionable, 3)
        reasons.append("actionable_finding")
    if repaired:
        score += 18
        reasons.append("revision_with_repair_link")
    if revised:
        score += 12
        reasons.append("meaningful_initial_final_revision")
    if conflict:
        score += 5
        reasons.append("terminology_conflict")
    if term_count:
        score += min(4, term_count * 1.5)
        reasons.append("terminology_dense")
    if segment.get("from_tm"):
        score += 1
        reasons.append("tm_reuse")
    if len(source) >= 180:
        score += min(5, len(source) / 100)
        reasons.append("long_source")
    if clauses >= 2:
        score += min(4, clauses)
        reasons.append("clause_complexity")
    if punctuation >= 5:
        score += min(3, punctuation / 3)
        reasons.append("punctuation_complexity")
    if _PASSIVE.search(source):
        score += 1.5
        reasons.append("passive_construction")
    if re.search(r"[\"“”‘’]|—|–", source):
        score += 1
        reasons.append("quotation_or_dash_complexity")
    if informational and not (blocking or actionable):
        score += min(1, informational * 0.2)
    if integrity_flags:
        score -= 100
        reasons.append("integrity_review_required")

    return {
        "score": round(score, 3),
        "reasons": reasons,
        "academic_candidate_status": (
            "review_required" if integrity_flags else "eligible"),
        "features": {
            "source_chars": len(source),
            "clause_markers": clauses,
            "punctuation_count": punctuation,
            "term_count": term_count,
            "term_entry_ids": term_ids,
            "blocking_findings": blocking,
            "actionable_findings": actionable,
            "informational_findings": informational,
            "has_meaningful_revision": revised,
            "repair_evidence": repaired,
            "has_repair_history": repair_history,
            "has_human_revision_action": human_actions,
            "complete_evidence_chain": complete_chain,
            "terminology_conflict": conflict,
            "tm_reuse": bool(segment.get("from_tm")),
            "integrity_flags": integrity_flags,
        },
    }


def _mark_neighbor_target_overlap(segments: List[Dict[str, Any]]) -> None:
    """Flag likely cross-segment target duplication after a revision."""
    for current, following in zip(segments, segments[1:]):
        if case_role(current) != "revision_case":
            continue
        current_final = normalized_translation_target(current.get("final_target"))
        following_final = normalized_translation_target(following.get("final_target"))
        if len(following_final) < 60 or len(current_final) < len(following_final):
            continue
        tail = current_final[-len(following_final):]
        overlap = difflib.SequenceMatcher(
            None, tail, following_final, autojunk=False).ratio()
        if overlap >= 0.75:
            current.setdefault("integrity_flags", []).append({
                "type": "probable_adjacent_target_overlap",
                "following_segment_id": following.get("segment_id"),
                "similarity": round(overlap, 3),
            })


def _mark_neighbor_initial_overlap(segments: List[Dict[str, Any]]) -> None:
    """Flag an alleged initial translation copied from an adjacent target."""
    for index, current in enumerate(segments):
        if case_role(current) != "revision_case":
            continue
        initial = normalized_translation_target(
            current.get("initial_target"), ignore_punctuation=True)
        if len(initial) < 8:
            continue
        for neighbor_index in (index - 1, index + 1):
            if not 0 <= neighbor_index < len(segments):
                continue
            neighbor = segments[neighbor_index]
            neighbor_target = normalized_translation_target(
                neighbor.get("final_target"), ignore_punctuation=True)
            if initial and initial in neighbor_target:
                current.setdefault("integrity_flags", []).append({
                    "type": "probable_adjacent_initial_target_overlap",
                    "adjacent_segment_id": neighbor.get("segment_id"),
                    "position": "previous" if neighbor_index < index else "following",
                    "contained_fraction": 1.0,
                })
                break


def mine_candidate_cases(
    segments: List[Dict[str, Any]],
    glossary: Optional[List[Dict[str, Any]]] = None,
    max_candidates: int = 80,
) -> List[Dict[str, Any]]:
    """Mine only genuine revision cases, then rank academic usefulness."""
    scored = []
    for segment in segments:
        role = case_role(segment)
        if role != "revision_case":
            continue
        details = _candidate_features(segment, glossary or [])
        scored.append({
            "case_id": segment["segment_id"],
            "segment_id": segment["segment_id"],
            "segment_index": segment["segment_index"],
            "coverage_zone": segment["coverage_zone"],
            "case_type": "authentic_revision",
            "provenance": {
                "historical": True,
                "generated_for_analysis": False,
            },
            "case_role": role,
            **details,
        })
    scored.sort(key=lambda x: (-x["score"], x["segment_index"]))

    # Keep whole-corpus coverage explicit even when the highest scores cluster.
    chosen: Dict[str, Dict[str, Any]] = {}
    per_zone = min(3, max(1, max_candidates // 3))
    for zone in ("beginning", "middle", "end"):
        for item in [x for x in scored if x["coverage_zone"] == zone][:per_zone]:
            if len(chosen) >= max_candidates:
                break
            chosen[item["segment_id"]] = item
    for item in scored:
        if len(chosen) >= max_candidates:
            break
        if item["score"] > 0:
            chosen[item["segment_id"]] = item
    return sorted(chosen.values(), key=lambda x: (-x["score"], x["segment_index"]))


def mine_translation_decision_cases(
    segments: List[Dict[str, Any]],
    glossary: Optional[List[Dict[str, Any]]] = None,
    max_candidates: int = 40,
) -> List[Dict[str, Any]]:
    """Mine unchanged but evidence-rich decisions without inventing revisions."""
    scored = []
    for segment in segments:
        if case_role(segment) != "non_revision_case" or segment.get("integrity_flags"):
            continue
        details = _candidate_features(segment, glossary or [])
        features = details["features"]
        has_decision_evidence = bool(
            features["actionable_findings"]
            or features["term_count"]
            or features["clause_markers"] >= 2
            or features["punctuation_count"] >= 5
        )
        if not has_decision_evidence or not segment.get("source") \
                or not segment.get("final_target"):
            continue
        scored.append({
            "case_id": f"TD-{int(segment['segment_index']) + 1:04d}",
            "source_segment_id": segment["segment_id"],
            "segment_index": segment["segment_index"],
            "coverage_zone": segment["coverage_zone"],
            "case_type": "translation_decision",
            "case_role": "translation_decision_case",
            "academic_candidate_status": "eligible",
            "provenance": {"historical": True, "generated_for_analysis": False},
            "decision_evidence": {
                "initial_equals_final": True,
                "finding_count": len(segment["process_evidence"].get("findings") or []),
                "terminology_entry_ids": list(
                    segment["process_evidence"].get("injected_glossary_entry_ids") or []),
            },
            "score": details["score"],
            "reasons": ["unchanged_translation_decision", *details["reasons"]],
            "features": features,
        })
    scored.sort(key=lambda x: (-x["score"], x["segment_index"]))
    chosen: Dict[str, Dict[str, Any]] = {}
    for zone in ("beginning", "middle", "end"):
        item = next((x for x in scored if x["coverage_zone"] == zone), None)
        if item:
            chosen[item["case_id"]] = item
    for item in scored:
        if len(chosen) >= max_candidates:
            break
        chosen[item["case_id"]] = item
    return sorted(chosen.values(), key=lambda x: (-x["score"], x["segment_index"]))


def _workflow_evidence(state: Dict[str, Any], statistics: Dict[str, Any]) -> Dict[str, Any]:
    """Expose only workflow facts actually recorded by TransPraxis."""
    return {
        "source_filename": str(state.get("filename") or ""),
        "target_language": str(state.get("target_lang") or ""),
        "translation_scope": {
            "segments": statistics.get("total_segments", 0),
            "translated_segments": statistics.get("translated_segments", 0),
        },
        "pre_translation": {
            "document_parsed": bool(state.get("paras")),
            "document_profile_built": bool(state.get("document_profile")),
            "terminology_extracted": bool(state.get("glossary") or state.get("auto_terms")),
            "terminology_frozen": bool(state.get("glossary_frozen")),
            "translation_memory_enabled": bool(state.get("use_tm")),
        },
        "translation": {
            "initial_and_final_versions_recorded": statistics.get(
                "segments_with_initial_final_data", 0),
            "terminology_constraints_recorded": sum(
                bool(pair.get("glossary_entry_ids")) for pair in state.get("pairs") or []),
            "tm_reuse_records": statistics.get("tm_reuse_count", 0),
        },
        "post_translation": {
            "reviewed_segments": statistics.get("reviewed_segments", 0),
            "recorded_findings": sum(
                statistics.get(key, 0) for key in (
                    "recorded_blocking_findings", "recorded_actionable_findings",
                    "recorded_informational_findings")),
            "human_actions": len(state.get("human_actions") or []),
            "meaningful_revisions": statistics.get("meaningfully_revised_segments", 0),
            "delivery_status": str(state.get("delivery_status") or ""),
        },
    }


def _project_statistics(state: Dict[str, Any], segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    findings = state.get("findings") or []
    active_findings = [f for f in findings if not f.get("resolved")]
    by_severity = Counter(str(f.get("severity") or "unknown")
                          for f in active_findings)
    by_type = Counter(str(f.get("type") or "unknown") for f in active_findings)
    recorded_by_severity = Counter(str(f.get("severity") or "unknown")
                                   for f in findings)
    with_versions = [s for s in segments if s.get("initial_target") is not None
                     and s.get("final_target") is not None]
    revised = [s for s in with_versions if has_meaningful_revision(
        s.get("initial_target"), s.get("final_target"))]
    revision_with_findings = [s for s in revised
                              if s["process_evidence"].get("findings")]
    revision_with_repair_history = [s for s in revised
                                    if s["process_evidence"].get("repair_history")]
    complete_chains = [s for s in revised if _candidate_features(s, {})[
        "features"]["complete_evidence_chain"]]
    academically_eligible = [s for s in revised if is_eligible_revision_case(s)]
    stats = {
        "total_segments": len(state.get("paras") or state.get("pairs") or []),
        "translated_segments": len(state.get("pairs") or []),
        "reviewed_segments": sum(bool(p.get("reviewed")) for p in state.get("pairs") or []),
        "blocking_findings": by_severity.get("blocking", 0),
        "actionable_findings": by_severity.get("actionable", 0),
        "informational_findings": by_severity.get("informational", 0),
        "recorded_blocking_findings": recorded_by_severity.get("blocking", 0),
        "recorded_actionable_findings": recorded_by_severity.get("actionable", 0),
        "recorded_informational_findings": recorded_by_severity.get(
            "informational", 0),
        "segments_with_initial_final_data": len(with_versions),
        "unchanged_segments": len(with_versions) - len(revised),
        "meaningfully_revised_segments": len(revised),
        "revision_cases_with_findings": len(revision_with_findings),
        "revision_cases_with_repair_history": len(revision_with_repair_history),
        "revision_cases_with_complete_repair_chains": len(complete_chains),
        "revision_cases_academically_eligible": len(academically_eligible),
        "repaired_segments": len(revised),
        "term_conflicts": sum(bool(f.get("conflict")) for f in findings),
        "tm_reuse_count": sum(bool(p.get("from_tm")) for p in state.get("pairs") or []),
        "issue_category_distribution": dict(sorted(by_type.items())),
        "repair_category_distribution": {
            "initial_final_changed": len(revised),
            "suggested_target_recorded": sum(bool(f.get("suggested_target")) for f in findings),
            "human_action_recorded": len(state.get("human_actions") or []),
            "system_action_recorded": len(state.get("system_actions") or []),
        },
        "coverage_distribution": dict(Counter(s["coverage_zone"] for s in segments)),
    }
    return stats


def build_academic_evidence(
    state: Dict[str, Any],
    job_id: str,
    literature_sources: Optional[Iterable[Dict[str, Any]]] = None,
    max_candidates: int = 80,
) -> Dict[str, Any]:
    """Build the canonical PROJECT/LITERATURE/AUTHOR evidence artifact."""
    pairs = state.get("pairs") or []
    glossary = state.get("glossary") or []
    glossary_by_id = {str(e.get("id")): e for e in glossary if e.get("id")}
    findings_by_seg: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for finding in state.get("findings") or []:
        idx = finding.get("segment_index")
        if isinstance(idx, int):
            findings_by_seg[idx].append(dict(finding))

    segments = []
    for i, pair in enumerate(pairs):
        base = report_evidence.build_segment_evidence(state, job_id, i)
        injected = list(pair.get("glossary_entry_ids") or [])
        segments.append({
            "evidence_type": "PROJECT_EVIDENCE",
            "segment_id": assets.segment_id(job_id, i),
            "segment_index": i,
            "source": pair.get("source", ""),
            "initial_target": pair.get("initial_target"),
            "final_target": pair.get("target", ""),
            "integrity_flags": list(pair.get("integrity_flags") or []),
            "reviewed": bool(pair.get("reviewed")),
            "from_tm": bool(pair.get("from_tm")),
            "coverage_zone": _zone(i, len(pairs)),
            "case_role": "revision_case" if has_meaningful_revision(
                pair.get("initial_target"), pair.get("target"))
            else "non_revision_case",
            "location": _location(state.get("document_profile"), i),
            "process_evidence": {
                "findings": findings_by_seg.get(i, []),
                "deterministic_findings": base.get("deterministic_findings") or [],
                "review_findings": base.get("review_findings") or [],
                "repair_history": base.get("repair_history") or [],
                "human_actions": base.get("human_actions") or [],
                "system_actions": base.get("system_actions") or [],
                "terminology_decisions": [glossary_by_id[x] for x in injected
                                          if x in glossary_by_id],
                "injected_glossary_entry_ids": injected,
            },
            "availability": {
                "initial_target": "recorded" if pair.get("initial_target") is not None
                else "not_recorded",
                "findings": "recorded" if i in findings_by_seg else "not_recorded",
                "repair_history": "recorded" if base.get("repair_history")
                else "not_recorded",
                "terminology_decisions": "recorded" if injected else "not_recorded",
                "location": "recorded" if _location(
                    state.get("document_profile"), i)["recorded"] else "not_recorded",
            },
        })

    _mark_neighbor_target_overlap(segments)
    _mark_neighbor_initial_overlap(segments)
    candidates = mine_candidate_cases(segments, glossary, max_candidates=max_candidates)
    decision_candidates = mine_translation_decision_cases(
        segments, glossary, max_candidates=max_candidates)
    statistics = _project_statistics(state, segments)
    limitations = []
    if any(s["availability"]["initial_target"] == "not_recorded" for s in segments):
        limitations.append(
            "Historical job: initial translations, glossary injection, or repair history may be unavailable.")
    academically_eligible = sum(
        x.get("academic_candidate_status") == "eligible" for x in candidates)
    if academically_eligible < 3:
        status = "two_case_fallback_available" if academically_eligible == 2 \
            else "insufficient_revision_cases"
        limitations.append(
            f"{status}: only {academically_eligible} academically eligible meaningful "
            "revisions are available; ineligible cases must not be used as backfill.")
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "evidence_classes": {
            "PROJECT_EVIDENCE": "facts recorded by the translation workflow",
            "LITERATURE_EVIDENCE": "registered external or user-provided sources",
            "AUTHOR_ANALYSIS": "interpretation produced during academic planning/writing",
        },
        "coverage_policy": {
            "segments_scanned": len(segments),
            "scan_scope": "whole_corpus",
            "candidate_limit": max_candidates,
            "zones": ["beginning", "middle", "end"],
            "zone_minimum_candidates": min(3, max(1, len(segments) // 3))
            if segments else 0,
            "bounded": len(segments) > max_candidates,
            "eligibility_rule": "revision_case_only",
            "preferred_core_case_count": 3,
            "minimum_core_case_count": 2,
            "revision_candidate_pool": len(candidates),
            "eligible_revision_cases": academically_eligible,
            "translation_decision_candidate_pool": len(decision_candidates),
        },
        "project_evidence": {
            "segments": segments,
            "statistics": statistics,
            "document_profile": state.get("document_profile"),
            "glossary": glossary,
            "workflow": _workflow_evidence(state, statistics),
        },
        "author_analysis": [],
        "candidate_cases": candidates,
        "translation_decision_candidates": decision_candidates,
        "limitations": limitations,
    }
    artifact["content_hash"] = stable_hash({k: v for k, v in artifact.items()
                                            if k != "content_hash"})
    return artifact


def segment_index(evidence: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {s["segment_id"]: s for s in
            evidence.get("project_evidence", {}).get("segments", [])}


def candidate_index(evidence: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {c["case_id"]: c for c in evidence.get("candidate_cases", [])}


def literature_index(evidence: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    sources = evidence.get("sources")
    if not isinstance(sources, list):
        sources = evidence.get("literature_sources")
    if not isinstance(sources, list):
        # academic-evidence-v1 compatibility: this field contained source
        # metadata despite its misleading name.
        sources = evidence.get("literature_evidence", [])
    return {s["source_id"]: s for s in sources if isinstance(s, dict) and s.get("source_id")}
