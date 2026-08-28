"""Human author evidence intake for MTI academic writing.

The pipeline can reach an evidence boundary where no recorded project artifact
answers an analytical question.  Instead of inferring, this module:

1. translates quality gaps into structured evidence needs (HN),
2. generates minimal targeted questions (HQ),
3. records provenance-bearing human answers (HE),
4. upgrades case capabilities without rewriting project history,
5. detects "I don't remember" and deterministic contradictions.

Human answers are always kept verbatim and distinguished from derived
academic interpretation and from recorded project evidence.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .academic_evidence import segment_index, stable_hash
from . import case_analysis

HUMAN_EVIDENCE_VERSION = "human-evidence-v2"

EVIDENCE_NEED_TYPES = (
    "translator_rationale", "initial_translation_missing", "alternative_considered",
    "reviewer_feedback", "review_acceptance_reason", "repair_reason",
    "terminology_decision_reason", "context_information", "reader_response",
    "source_interpretation", "theoretical_intention", "other_author_context",
    "synthetic_baseline_plausibility", "synthetic_optimization_preference",
)
RECOVERABILITY = (
    "human_recoverable", "system_recoverable", "historically_unrecoverable",
    "not_worth_requesting",
)
ACADEMIC_VALUE = ("critical", "high", "medium", "low")
HE_STATUSES = (
    "user_confirmed", "needs_clarification", "conflicted",
    "superseded", "withdrawn", "unavailable_after_human_check",
)
CONFLICT_STATUSES = ("contradicted", "not_corroborated", "consistent")

_UNAVAILABLE = re.compile(
    r"^(?:不知道|不记得|不记得了|忘记了|忘了|没印象|没有特别考虑|没有相关记录|没有记录|"
    r"没想过|不确定|想不起来|don'?t (?:know|remember)|not sure|"
    r"no (?:specific )?(?:reason|record|memory)|can'?t recall)[。！？!?]?$",
    re.IGNORECASE)
_QUOTED = re.compile(r"[“\"'『「]([^”\"'』」]{2,80})[”\"'』」]")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def dimension_to_need_type(dimension: str, plan: Dict[str, Any],
                           segment: Dict[str, Any]) -> str:
    if plan.get("case_type") == "synthetic_contrast":
        if dimension in {"initial_failure_or_alternative",
                         "initial_solution_or_failure",
                         "alternative_interpretation_or_strategy"}:
            return "synthetic_baseline_plausibility"
        if dimension in {"decision_rationale", "final_translation_decision",
                         "translation_effect", "bounded_conclusion",
                         "case_level_conclusion"}:
            return "synthetic_optimization_preference"
    delta = plan.get("translation_delta") or {}
    if dimension == "decision_rationale":
        return "repair_reason" if delta.get("changed") else "translator_rationale"
    if dimension == "translation_effect":
        return "reader_response"
    if dimension == "initial_failure_or_alternative":
        if not delta.get("available") or not delta.get("changed"):
            return "initial_translation_missing"
        return "alternative_considered"
    if dimension == "theory_mapping":
        return "theoretical_intention"
    if dimension == "evidence_use":
        return "reviewer_feedback"
    if dimension == "bounded_conclusion":
        return "translator_rationale"
    return "other_author_context"


def recoverability_of(need_type: str, plan: Dict[str, Any],
                      segment: Dict[str, Any]) -> str:
    delta = plan.get("translation_delta") or {}
    process = segment.get("process_evidence", {})
    findings = [x for x in (process.get("findings") or []) if isinstance(x, dict)]
    if need_type == "initial_translation_missing":
        if delta.get("available") and delta.get("initial_target"):
            return "system_recoverable"
        if segment.get("initial_target") is None:
            return "historically_unrecoverable"
        return "human_recoverable"
    if need_type == "reviewer_feedback":
        if findings:
            return "system_recoverable"
        return "not_worth_requesting"
    if need_type == "review_acceptance_reason":
        if not findings:
            return "historically_unrecoverable"
        return "human_recoverable"
    if need_type in ("translator_rationale", "repair_reason",
                     "alternative_considered", "reader_response",
                     "source_interpretation", "theoretical_intention",
                     "context_information", "terminology_decision_reason",
                     "synthetic_baseline_plausibility",
                     "synthetic_optimization_preference"):
        return "human_recoverable"
    return "not_worth_requesting"


def academic_value_of(need_type: str, affected_dimensions: Iterable[str],
                      blocks_p1: bool) -> str:
    if blocks_p1:
        return "critical"
    if need_type in ("translator_rationale", "repair_reason",
                     "reader_response", "alternative_considered",
                     "synthetic_baseline_plausibility",
                     "synthetic_optimization_preference"):
        if {"decision_rationale", "translation_effect",
            "bounded_conclusion"} & set(affected_dimensions):
            return "high"
        return "medium"
    if need_type in ("initial_translation_missing", "terminology_decision_reason"):
        return "medium"
    return "low"


def build_evidence_needs(
    evidence: Dict[str, Any], case_plans: Dict[str, Any],
    quality: Optional[Dict[str, Any]] = None,
    max_needs_per_case: int = 2,
) -> Dict[str, Any]:
    """Derive structured human-evidence needs from plan/completion gaps."""
    segs = segment_index(evidence)
    depth = ((quality or {}).get("diagnostics") or {}).get(
        "case_analysis_depth") or {}
    p1_cases = {
        str(x.get("case_id")) for x in (quality or {}).get("findings") or []
        if x.get("priority") == "P1" and x.get("case_id")}
    needs: List[Dict[str, Any]] = []
    seen: set = set()
    for plan in (case_plans.get("plans") or []):
        case_id = str(plan.get("case_id") or "")
        segment = segs.get(case_id) or {}
        delta = plan.get("translation_delta") or case_analysis.translation_delta(segment)
        if not delta.get("changed"):
            continue
        completion = case_analysis.contract_completion(plan)
        depth_entry = depth.get(case_id) or {}
        weak_dimensions = sorted({
            dimension for dimension, status in completion.items()
            if status in ("weak", "missing")
        } | {
            dimension for dimension, entry in depth_entry.items()
            if entry.get("status") in ("weak", "missing")
        })
        if not weak_dimensions:
            continue
        for dimension in weak_dimensions:
            need_type = dimension_to_need_type(dimension, plan, segment)
            recoverability = recoverability_of(need_type, plan, segment)
            if recoverability != "human_recoverable":
                continue
            key = (case_id, need_type)
            if key in seen:
                continue
            seen.add(key)
            blocks_p1 = case_id in p1_cases and dimension in (
                "decision_rationale", "evidence_use")
            value = academic_value_of(need_type, [dimension], blocks_p1)
            needs.append({
                "need_id": f"HN-{len(needs) + 1:03d}",
                "case_id": case_id,
                "segment_ids": [str(plan.get("source_segment_id") or case_id)],
                "missing_evidence": need_type,
                "reason": f"{dimension} 维度为 {completion.get(dimension, 'weak')}，"
                          f"无法用已记录项目证据回答。",
                "affected_dimensions": [dimension],
                "academic_value": value,
                "recoverability": recoverability,
                "status": "unresolved",
            })
    per_case: Dict[str, List[Dict[str, Any]]] = {}
    for need in needs:
        per_case.setdefault(need["case_id"], []).append(need)
    selected: List[Dict[str, Any]] = []
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    for case_id, case_needs in sorted(per_case.items()):
        case_needs.sort(key=lambda x: rank.get(x["academic_value"], 3))
        selected.extend(case_needs[:max_needs_per_case])
    artifact = {
        "schema_version": HUMAN_EVIDENCE_VERSION,
        "needs": selected,
        "skipped_needs": len(needs) - len(selected),
    }
    artifact["content_hash"] = stable_hash(
        {k: v for k, v in artifact.items() if k != "content_hash"})
    return artifact


def _question_template(need: Dict[str, Any], segment: Dict[str, Any],
                       plan: Dict[str, Any]) -> Tuple[str, str]:
    need_type = need["missing_evidence"]
    final = (segment.get("final_target") or "")[:80]
    initial = (segment.get("initial_target") or "")[:80]
    source = (segment.get("source") or "")[:100]
    findings = [x for x in (segment.get("process_evidence", {}).get(
        "findings") or []) if isinstance(x, dict)]
    finding = findings[0] if findings else {}
    suggestion = (finding.get("suggested_target") or "")[:60]
    question_type = need_type
    if need_type == "synthetic_baseline_plausibility":
        baseline = str((plan.get("synthetic_baseline") or {}).get("text") or "")[:100]
        return (question_type,
                f"这是一条为分析构造的模拟初译：「{baseline}」。你认为一名具备基本能力的"
                "译者是否可能作出这种处理？请只评价合理性，不把它当作你的历史译文。")
    if need_type == "synthetic_optimization_preference":
        target = str(plan.get("final_target") or
                     (plan.get("optimized_translation") or {}).get("text") or "")[:100]
        return (question_type,
                f"对于这条项目当前正式译文「{target}」，你认为它是否解决了所述问题？"
                "这里的模拟初译只是分析对照，不是历史初稿；如有更合适的译法，请说明。")
    if need_type == "translator_rationale":
        if final:
            return (question_type,
                    f"这里你为什么选择最终这个译法（「{final}」）？"
                    "如果采用更直白的表达，会损失什么？")
        return (question_type, "这一段你当时的翻译考虑是什么？")
    if need_type == "repair_reason":
        return (question_type,
                f"这段从初译「{initial}」改为「{final}」，是出于什么考虑？"
                "（你自己修改、审校建议，还是其他原因？）")
    if need_type == "alternative_considered":
        return (question_type,
                f"这一句你考虑过哪些其他译法？为什么最终选用了「{final}」？")
    if need_type == "review_acceptance_reason":
        return (question_type,
                f"审校建议「{suggestion}」你后来采纳了吗？"
                "采纳或未采纳的原因是什么？")
    if need_type == "reader_response":
        return (question_type,
                f"你预期中文读者从这一句（「{final}」）获得什么感受或理解？")
    if need_type == "source_interpretation":
        return (question_type,
                f"这一句源文「{source}」在你理解中的确切含义是什么？")
    if need_type == "context_information":
        return (question_type,
                f"这一段在原文中的上下文背景是什么？"
                "（人物关系、时间线、事件经过等）")
    if need_type == "terminology_decision_reason":
        return (question_type,
                f"这一句涉及的术语/专名你当时为什么这样处理？")
    if need_type == "theoretical_intention":
        return (question_type,
                f"你当时是否参考了某个理论或原则来指导这一句的处理？")
    return (question_type, f"关于这一段（“{source}”）的处理，你有什么补充信息？")


def generate_questions(
    needs_artifact: Dict[str, Any], evidence: Dict[str, Any],
    case_plans: Dict[str, Any],
) -> Dict[str, Any]:
    segs = segment_index(evidence)
    plans = {p["case_id"]: p for p in case_plans.get("plans", [])}
    questions: List[Dict[str, Any]] = []
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    for need in sorted(needs_artifact.get("needs", []),
                       key=lambda x: rank.get(x["academic_value"], 3)):
        case_id = str(need.get("case_id") or "")
        segment = segs.get(case_id) or {}
        plan = plans.get(case_id) or {}
        synthetic = plan.get("case_type") == "synthetic_contrast"
        delta = plan.get("translation_delta") or case_analysis.translation_delta(segment)
        if not delta.get("changed"):
            continue
        question_type, question = _question_template(need, segment, plan)
        questions.append({
            "question_id": f"HQ-{len(questions) + 1:03d}",
            "need_ids": [need["need_id"]],
            "case_id": case_id,
            "segment_ids": need.get("segment_ids", [case_id]),
            "question_type": question_type,
            "question": question,
            "context": {
                "case_type": plan.get("case_type", "authentic_revision"),
                "source": (plan.get("source_text") if synthetic else segment.get(
                    "source") or "")[:200],
                "initial_target": None if synthetic else (
                    segment.get("initial_target") or "")[:200] or None,
                "final_target": "" if synthetic else (
                    segment.get("final_target") or "")[:200],
                "synthetic_initial_translation": (
                    (plan.get("synthetic_baseline") or {}).get("text") or "")[:200]
                if synthetic else None,
                "final_target": (
                    plan.get("final_target") or
                    (plan.get("optimized_translation") or {}).get("text") or "")[:200]
                if synthetic else None,
                "target_provenance": "project_current_target" if synthetic else None,
                "synthetic_evidence": plan.get("synthetic_evidence") if synthetic else None,
            },
            "priority": need.get("academic_value", "low"),
            "status": "open",
        })
    artifact = {
        "schema_version": HUMAN_EVIDENCE_VERSION,
        "questions": questions,
        "critical_count": sum(1 for q in questions if q["priority"] == "critical"),
        "high_count": sum(1 for q in questions if q["priority"] == "high"),
    }
    artifact["content_hash"] = stable_hash(
        {k: v for k, v in artifact.items() if k != "content_hash"})
    return artifact


def _conflict_status(question: Dict[str, Any], answer: str,
                     segment: Dict[str, Any]) -> str:
    stored_initial = _norm(segment.get("initial_target"))
    stored_final = _norm(segment.get("final_target"))
    if not stored_initial:
        return "not_corroborated"
    quoted = [_norm(x) for x in _QUOTED.findall(answer)]
    if not quoted:
        return "not_corroborated"
    for piece in quoted:
        if piece and stored_initial and piece != stored_initial[:80] \
                and piece not in stored_initial:
            if question.get("question_type") in (
                    "initial_translation_missing", "repair_reason"):
                if piece == stored_final[:80] or piece in stored_final:
                    return "not_corroborated"
                return "contradicted"
    return "consistent"


def record_human_answer(
    questions_artifact: Dict[str, Any], question_id: str, answer: str,
    evidence: Dict[str, Any], interface: str = "academic_workspace",
    existing: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Record one human answer; returns (HE entry, updated questions artifact)."""
    questions = questions_artifact.get("questions") or []
    question = next((q for q in questions if q.get("question_id") == question_id), None)
    if not question:
        raise ValueError(f"未知问题：{question_id}")
    raw_answer = _norm(answer)
    if not raw_answer:
        raise ValueError("答案不能为空；如果确实没有信息，请回答“不记得”或“没有相关记录”。")
    case_id = str(question.get("case_id") or "")
    segs = segment_index(evidence)
    segment = segs.get(case_id) or {}
    if _UNAVAILABLE.match(raw_answer):
        status = "unavailable_after_human_check"
        conflict = "not_corroborated"
    else:
        status = "user_confirmed"
        conflict = _conflict_status(question, raw_answer, segment)
        if conflict == "contradicted":
            status = "conflicted"
    human_evidence_id = f"HE-{len(existing or []) + 1:04d}"
    entry = {
        "human_evidence_id": human_evidence_id,
        "case_id": case_id,
        "segment_ids": question.get("segment_ids", [case_id]),
        "question_id": question_id,
        "question_type": question.get("question_type"),
        "question": question.get("question", ""),
        "answer": raw_answer,
        "derived_interpretation": None,
        "evidence_role": question.get("question_type"),
        "provenance": {
            "type": "user_answer",
            "recorded_at": _now(),
            "interface": interface,
        },
        "status": status,
        "conflict_status": conflict,
        "scope": "case",
    }
    entry["content_hash"] = stable_hash(
        {k: v for k, v in entry.items() if k != "content_hash"})
    updated_questions = {
        **questions_artifact,
        "questions": [
            {**q, "status": "answered" if q.get("question_id") == question_id
             else q.get("status")}
            for q in questions],
    }
    updated_questions["content_hash"] = stable_hash(
        {k: v for k, v in updated_questions.items() if k != "content_hash"})
    return entry, updated_questions


def supersede_evidence(
    entry: Dict[str, Any], new_status: str, reason: str = "",
) -> Dict[str, Any]:
    if new_status not in ("superseded", "withdrawn", "corrected"):
        raise ValueError(f"非法状态：{new_status}")
    updated = {
        **entry,
        "status": "superseded" if new_status == "superseded" else (
            "withdrawn" if new_status == "withdrawn" else "needs_clarification"),
        "supersession": {
            "reason": reason,
            "recorded_at": _now(),
            "original_status": entry.get("status"),
        },
    }
    updated["content_hash"] = stable_hash(
        {k: v for k, v in updated.items() if k != "content_hash"})
    return updated


def case_capabilities(
    case_id: str, he_entries: Iterable[Dict[str, Any]],
    adequacy: Dict[str, Any],
) -> Dict[str, Any]:
    """Upgrade analytical capabilities from accepted human evidence."""
    usable = [
        x for x in he_entries
        if str(x.get("case_id")) == case_id
        and x.get("status") == "user_confirmed"]
    if not usable or not (adequacy.get("capabilities") or {}).get(
            "has_meaningful_revision") and not (adequacy.get("capabilities") or {}).get(
                "has_validated_synthetic_contrast"):
        return dict(adequacy)
    can = set(adequacy.get("can_support") or [])
    cannot = set(adequacy.get("cannot_support") or [])
    types = {x.get("question_type") for x in usable}
    if types & {"translator_rationale", "repair_reason", "review_acceptance_reason",
                "terminology_decision_reason"}:
        can.update({"translator_rationale", "decision_reasoning"})
        cannot.discard("process_claims")
        cannot.discard("historical_revision_reasoning")
    if "reader_response" in types:
        can.add("reader_response_claim")
    if "synthetic_baseline_plausibility" in types:
        can.add("author_judged_baseline_plausibility")
    if "synthetic_optimization_preference" in types:
        can.add("author_optimization_preference")
    level = adequacy.get("evidence_level", "source_final_only")
    if usable and level == "source_final_only":
        level = "source_final_plus_author_rationale"
    return {
        **adequacy,
        "evidence_level": level,
        "can_support": sorted(can),
        "cannot_support": sorted(cannot),
        "human_evidence_ids": [x["human_evidence_id"] for x in usable],
        "capabilities": {
            **(adequacy.get("capabilities") or {}),
            "has_revision_rationale": bool(types & {
                "translator_rationale", "repair_reason", "review_acceptance_reason",
                "terminology_decision_reason"}),
            "has_author_synthetic_judgment": bool(types & {
                "synthetic_baseline_plausibility",
                "synthetic_optimization_preference"}),
        },
    }


def evidence_index(entries: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {x["human_evidence_id"]: x for x in entries}


def evidence_hash(entries: Iterable[Dict[str, Any]]) -> str:
    return stable_hash([x.get("human_evidence_id") for x in entries])
