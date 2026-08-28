"""Structured case analysis: evidence adequacy, translation deltas and
analysis contracts for MTI translation case analyses.

This module is deliberately deterministic where possible.  The LLM only fills
the *analysis plan* (problem / alternatives / rationale / effect / theory
mapping / bounded conclusion) from bounded inputs, and every plan field is
validated against the available evidence before the writer sees it.
"""
from __future__ import annotations

import difflib
import json
import re
from typing import Any, Callable, Dict, Iterable, List, Optional

from .academic_evidence import (
    case_role, has_meaningful_revision, is_eligible_revision_case, segment_index,
    stable_hash,
)
from . import case_provenance

ANALYSIS_VERSION = "case-analysis-v5"

EVIDENCE_LEVELS = ("rich_process_evidence", "partial_process_evidence",
                   "source_final_only", "validated_synthetic_contrast")
PROBLEM_TYPES = (
    "syntactic_ambiguity", "logical_relation", "information_structure",
    "reference_resolution", "lexical_polysemy", "cultural_reference",
    "register", "voice", "metaphor", "rhythm", "narrative_perspective",
    "cohesion", "terminology", "pragmatic_implication", "other",
)
ALTERNATIVE_LABELS = ("historical_alternative", "analytical_comparison",
                      "counterfactual_rendering")
DEPTH_DIMENSIONS = (
    "problem_definition", "evidence_use", "initial_failure_or_alternative",
    "decision_rationale", "translation_effect", "theory_mapping",
    "bounded_conclusion",
)
DEPTH_STATUSES = ("strong", "adequate", "weak", "missing", "not_applicable")

ANALYSIS_CONTRACT = (
    "translation_problem",
    "difficulty_evidence",
    "initial_solution_or_failure",
    "alternative_interpretation_or_strategy",
    "final_translation_decision",
    "decision_rationale",
    "translation_effect",
    "theory_connection",
    "evidence_boundary",
    "case_level_conclusion",
)

_GENERIC_EFFECT = re.compile(
    r"(?:提高|提升)(?:了)?(?:译文|翻译|文本)?的?(?:可读性|准确性|自然度|流畅性)|"
    r"(?:使|让|令)译文(?:更加|更|更为)?(?:自然|准确|流畅|通顺|易懂)|"
    r"(?:improve[ds]?|enhance[ds]?|increase[ds]?)(?: the)? (?:readability|accuracy|"
    r"naturalness|fluency)")
_STRATEGY_LABEL = re.compile(
    r"(?:采用了|运用了|使用|采取)(?:了)?(?:直译|意译|增译|省译|转换|拆分|重组|"
    r"语序调整|音译)(?:的)?策略")
_PROCESS_CLAIM = re.compile(
    r"(?:译者|笔者)(?:最初|首先|一开始|曾)(?:考虑|尝试|选择|认为)|"
    r"(?:机器翻译|初译)(?:失败|错误|无法)(?:因为|由于)|"
    r"the (?:translator|author) (?:initially|first) (?:considered|tried|chose)")
_GENERAL_RULE = re.compile(
    r"因此[,，]?(?:在|对于)?(?:文学|商务|科技|法律)?翻译中(?:应当|需要|必须|应)|"
    r"hence,? (?:in )?(?:literary|legal|technical) translation (?:should|must|needs)")
_THEORY_LABEL = re.compile(
    r"(?:功能对等|目的论|关联理论|翻译转换|等值|functional equivalence|"
    r"skopos|relevance theory)")
_REVISION_PROSE = re.compile(
    r"修改后|修订后|经过(?:人工)?修订|初译.{0,120}(?:终译|最终译文|最终).{0,80}"
    r"(?:改|调整|修订|替换|变)|(?:从|将)[“\"'].*?[”\"'].{0,20}"
    r"(?:改|调整|修订|替换)(?:成|为)[“\"'].*?[”\"']",
    re.DOTALL)
_REVISION_PAIR = re.compile(
    r"(?:从|将)[“\"']([^”\"']{1,160})[”\"'].{0,20}"
    r"(?:改|调整|修订|替换)(?:成|为)[“\"']([^”\"']{1,160})[”\"']",
    re.DOTALL)


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


def translation_delta(segment: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic structural/text delta between initial and final targets."""
    initial = segment.get("initial_target")
    final = segment.get("final_target")
    if initial is None or final is None:
        return {"available": False}
    initial_text = str(initial)
    final_text = str(final)
    raw_changed = _norm(initial_text) != _norm(final_text)
    meaningful = has_meaningful_revision(initial_text, final_text)
    eligible = is_eligible_revision_case(segment)
    if not meaningful:
        return {
            "available": True,
            "changed": False,
            "meaningful": False,
            "formatting_only": raw_changed,
            "case_role": "non_revision_case",
            "lexical_changes": [],
            "structural_changes": [],
            "omission_addition": [],
            "finding_link": [],
            "repair_link": bool(segment.get("process_evidence", {}).get("repair_history")),
            "unchanged": True,
            "academically_eligible": False,
        }
    matcher = difflib.SequenceMatcher(None, initial_text, final_text, autojunk=False)
    lexical: List[str] = []
    structural: List[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_piece = initial_text[i1:i2]
        new_piece = final_text[j1:j2]
        if tag == "replace":
            lexical.append({"old": old_piece[:120], "new": new_piece[:120]})
        elif tag == "insert":
            structural.append({"addition": new_piece[:120]})
        elif tag == "delete":
            structural.append({"removal": old_piece[:120]})
    findings = segment.get("process_evidence", {}).get("findings") or []
    findings = [x for x in findings if isinstance(x, dict)]
    findings_by_idx: Dict[Any, List[Dict[str, Any]]] = {}
    for finding in findings:
        index = finding.get("segment_index")
        if index is not None:
            findings_by_idx.setdefault(index, []).append(finding)
    finding_link = [
        {"severity": x.get("severity"), "reason": x.get("reason", "")[:120]}
        for x in findings_by_idx.get(segment.get("segment_index"), [])]
    return {
        "available": True,
        "changed": True,
        "meaningful": True,
        "formatting_only": False,
        "case_role": "revision_case" if eligible else "revision_evidence_boundary",
        "academically_eligible": eligible,
        "lexical_changes": lexical,
        "structural_changes": structural,
        "omission_addition": [x for x in structural
                              if "addition" in x or "removal" in x],
        "finding_link": finding_link,
        "repair_link": bool(segment.get("process_evidence", {}).get("repair_history")),
        "unchanged": False,
    }


def evidence_adequacy(segment: Dict[str, Any]) -> Dict[str, Any]:
    """Classify what a case's process evidence can and cannot support."""
    delta = translation_delta(segment)
    process = segment.get("process_evidence", {})
    findings = process.get("findings") or []
    repair = bool(process.get("repair_history"))
    has_actionable = any(x.get("severity") in ("actionable", "blocking")
                         for x in findings)
    changed = bool(delta.get("changed") and delta.get("academically_eligible"))
    terms = bool(process.get("injected_glossary_entry_ids"))
    role = "revision_case" if changed else (
        "revision_evidence_boundary" if delta.get("changed") else case_role(segment))
    if not changed:
        level = "source_final_only"
        can = ["textual_analysis"]
        cannot = ["historical_revision_reasoning", "process_claims",
                  "initial_failure_reasoning", "revision_case_analysis"]
    elif repair and has_actionable:
        level = "rich_process_evidence"
        can = ["textual_analysis", "translation_decision", "revision_reasoning",
               "error_repair_analysis"]
        cannot = []
    elif (has_actionable or terms) and repair:
        level = "rich_process_evidence"
        can = ["textual_analysis", "translation_decision", "revision_reasoning"]
        cannot = ["error_repair_analysis"]
    elif has_actionable or changed or terms:
        level = "partial_process_evidence"
        can = ["textual_analysis", "translation_decision",
               "limited_process_inference"]
        cannot = ["historical_revision_reasoning"]
    else:
        level = "source_final_only"
        can = ["textual_analysis", "translator_interpretation",
               "theory_based_analysis"]
        cannot = ["historical_revision_reasoning", "process_claims",
                  "initial_failure_reasoning"]
    return {
        "case_id": segment.get("segment_id"),
        "case_role": role,
        "evidence_level": level,
        "can_support": can,
        "cannot_support": sorted(cannot),
        "translation_delta": delta,
        "capabilities": {
            "has_meaningful_revision": changed,
            "has_review_finding": bool(findings),
            "has_repair_history": repair,
            "has_revision_rationale": False,
            "has_theory_support": False,
        },
    }


def synthetic_evidence_adequacy(case: Dict[str, Any]) -> Dict[str, Any]:
    """Capabilities of an eligible analytical contrast, never project history."""
    eligible = bool(case.get("validation", {}).get("academic_case_eligible"))
    return {
        "case_id": case.get("case_id"),
        "case_type": "synthetic_contrast",
        "case_role": "synthetic_contrast_case",
        "evidence_level": "validated_synthetic_contrast" if eligible else "source_final_only",
        "can_support": [
            "textual_analysis", "plausible_error_analysis", "contrastive_repair_analysis",
            "theory_based_analysis",
        ] if eligible else ["textual_analysis"],
        "cannot_support": [
            "historical_revision_reasoning", "historical_process_claims",
            "empirical_human_error_frequency", "author_initial_translation_claim",
        ],
        "translation_delta": case.get("actual_delta") or {},
        "capabilities": {
            "has_meaningful_revision": False,
            "has_validated_synthetic_contrast": eligible,
            "has_review_finding": False,
            "has_repair_history": False,
            "has_revision_rationale": False,
            "has_theory_support": False,
        },
        "provenance": case.get("provenance") or {},
        "synthetic_evidence": case.get("synthetic_evidence") or {},
    }


def translation_decision_evidence_adequacy(
    case: Dict[str, Any], segment: Dict[str, Any],
) -> Dict[str, Any]:
    """Capabilities of an unchanged, evidence-rich translation decision."""
    base = evidence_adequacy(segment)
    has_evidence = bool(
        segment.get("source") and segment.get("final_target")
        and ((segment.get("process_evidence") or {}).get("findings")
             or (segment.get("process_evidence") or {}).get(
                 "injected_glossary_entry_ids")
             or (case.get("features") or {}).get("clause_markers", 0) >= 2)
    )
    return {
        **base,
        "case_id": case.get("case_id"),
        "case_type": "translation_decision",
        "case_role": "translation_decision_case",
        "evidence_level": "translation_decision_evidence" if has_evidence
        else "source_final_only",
        "can_support": [
            "textual_analysis", "translation_decision", "terminology_analysis",
            "syntax_or_rhetoric_analysis", "bounded_quality_confirmation",
        ] if has_evidence else ["textual_analysis"],
        "cannot_support": sorted(set(base.get("cannot_support") or []) | {
            "historical_revision_reasoning", "initial_failure_reasoning",
            "author_initial_translation_claim",
        }),
        "capabilities": {
            **base.get("capabilities", {}),
            "has_translation_decision_evidence": has_evidence,
        },
    }


def detect_revision_claims(text: str) -> List[Dict[str, Any]]:
    """Return deterministic revision-prose claims and any quoted X→Y pair."""
    claims = []
    for match in _REVISION_PROSE.finditer(text or ""):
        window = (text or "")[max(0, match.start() - 80):match.end() + 120]
        pair = _REVISION_PAIR.search(window)
        claims.append({
            "text": _norm(window)[:300],
            "old": _norm(pair.group(1)) if pair else None,
            "new": _norm(pair.group(2)) if pair else None,
        })
    return claims


def detect_strategy_label_without_mechanism(text: str) -> List[str]:
    hits = []
    for match in _STRATEGY_LABEL.finditer(text):
        window = text[max(0, match.start() - 40):match.end() + 80]
        if _GENERIC_EFFECT.search(window):
            hits.append(_norm(match.group(0) + " " + window)[:160])
    return hits


def detect_unsupported_quality_effect(text: str) -> List[str]:
    hits = []
    for match in _GENERIC_EFFECT.finditer(text):
        window = text[max(0, match.start() - 60):match.end() + 60]
        # A specific dimension name or concrete feature nearby is a weak signal
        # of mechanism; absence of any is a strong signal of label-only effect.
        if not re.search(r"语义|逻辑|指称|信息结构|语域|节奏|叙事|语用|文化|"
                         r"术语|semantic|logical|reference|register|rhythm|"
                         r"narrative|pragmatic|cultural|terminolog", window):
            hits.append(_norm(window)[:160])
    return hits


def detect_unsupported_process_claim(text: str) -> List[str]:
    hits = []
    for match in _PROCESS_CLAIM.finditer(text):
        window = text[max(0, match.start() - 40):match.end() + 120]
        if "<!--" not in window or "finding" not in window:
            hits.append(_norm(window)[:160])
    return hits


def detect_case_to_general_rule_overreach(text: str) -> List[str]:
    hits = []
    for match in _GENERAL_RULE.finditer(text):
        hits.append(_norm(text[max(0, match.start() - 50):match.end() + 60])[:160])
    return hits


def _scoped_planner_input(
    evidence: Dict[str, Any], selected_cases: Dict[str, Any],
    argument_plan: Dict[str, Any], literature_claims: Dict[str, Any],
) -> Dict[str, Any]:
    segs = segment_index(evidence)
    claims = {x["claim_id"]: x for x in argument_plan.get("claims", [])}
    cases = []
    for case in selected_cases.get("cases", []):
        case_id = str(case.get("case_id") or "")
        case_type = case.get("case_type") or "authentic_revision"
        synthetic = case_type == "synthetic_contrast"
        source_segment_id = str(case.get("source_segment_id") or case_id)
        segment = segs.get(source_segment_id) or {}
        adequacy = synthetic_evidence_adequacy(case) if synthetic else (
            translation_decision_evidence_adequacy(case, segment)
            if case_type == "translation_decision" else evidence_adequacy(segment))
        if synthetic:
            cases.append({
                "case_id": case_id,
                "case_type": "synthetic_contrast",
                "source_segment_id": case.get("source_segment_id"),
                "coverage_zone": case.get("coverage_zone"),
                "supports_claims": case.get("supports_claims", []),
                "claim_statements": [
                    claims.get(x, {}).get("claim", "")
                    for x in case.get("supports_claims", [])],
                "evidence_level": adequacy["evidence_level"],
                "case_role": adequacy["case_role"],
                "capabilities": adequacy["capabilities"],
                "can_support": adequacy["can_support"],
                "cannot_support": adequacy["cannot_support"],
                "translation_delta": adequacy["translation_delta"],
                "source_text": ((case.get("focus") or {}).get(
                    "source_span") or {}).get("text") or case.get("source_text", ""),
                "difficulty": case.get("difficulty"),
                "baseline_origin": case.get("baseline_origin"),
                "legacy_analysis_seed": case.get("legacy_analysis_seed"),
                "synthetic_baseline": case.get("synthetic_baseline"),
                "baseline_plausibility": case.get("baseline_plausibility"),
                "error": case.get("error"),
                "optimized_translation": case.get("optimized_translation"),
                "final_target": case.get("final_target") or
                ((case.get("optimized_translation") or {}).get("text")
                 if isinstance(case.get("optimized_translation"), dict) else ""),
                "target_contrast_text": case.get("target_contrast_text") or "",
                "repair_validation": case.get("validation"),
                "synthetic_evidence": case.get("synthetic_evidence"),
                "provenance": case.get("provenance"),
            })
            continue
        cases.append({
            "case_id": case_id,
            "case_type": case_type,
            "source_segment_id": source_segment_id,
            "coverage_zone": case.get("coverage_zone"),
            "supports_claims": case.get("supports_claims", []),
            "claim_statements": [
                claims.get(x, {}).get("claim", "") for x in case.get("supports_claims", [])],
            "evidence_level": adequacy["evidence_level"],
            "case_role": adequacy["case_role"],
            "capabilities": adequacy["capabilities"],
            "can_support": adequacy["can_support"],
            "cannot_support": adequacy["cannot_support"],
            "translation_delta": adequacy["translation_delta"],
            "source": ((case.get("focus") or {}).get(
                "source_span") or {}).get("text"),
            "initial_target": ((case.get("focus") or {}).get(
                "initial_span") or {}).get("text")
            if case_type == "authentic_revision" else None,
            "final_target": ((case.get("focus") or {}).get(
                "target_span") or {}).get("text"),
            "focus": case.get("focus"),
            "difficulty_group": case.get("difficulty_group"),
            "strategy_group": case.get("strategy_group"),
            "research_question_ids": case.get("research_questions"),
            "findings": [
                {k: x.get(k) for k in ("severity", "type", "reason",
                                       "suggested_target")}
                for x in (segment.get("process_evidence", {}).get("findings") or [])[:6]],
            "repair_history": bool(segment.get("process_evidence", {}).get("repair_history")),
            "terminology_decisions": [
                {k: x.get(k) for k in ("source", "target", "preferred", "status")}
                for x in (segment.get("process_evidence", {}).get(
                    "terminology_decisions") or [])[:6]],
        })
    return {
        "cases": cases,
        "literature_claims": literature_claims.get("items", [])[:30],
        "problem_types": list(PROBLEM_TYPES),
        "alternative_labels": list(ALTERNATIVE_LABELS),
    }


def build_case_analysis_plans(
    evidence: Dict[str, Any], selected_cases: Dict[str, Any],
    argument_plan: Dict[str, Any], literature_claims: Dict[str, Any],
    call_llm: Callable, provider: str, api_key: str, model: str,
    human_evidence: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Plan each selected case's analysis under evidence constraints."""
    segs = segment_index(evidence)
    adequacy_by_case = {
        str(x.get("case_id")): (
            synthetic_evidence_adequacy(x)
            if x.get("case_type") == "synthetic_contrast"
            else translation_decision_evidence_adequacy(
                x, segs.get(str(x.get("source_segment_id") or "")) or {})
            if x.get("case_type") == "translation_decision"
            else evidence_adequacy(segs.get(str(x.get("case_id"))) or {}))
        for x in selected_cases.get("cases", [])}
    selected_by_id = {str(x.get("case_id")): x
                      for x in selected_cases.get("cases", [])}
    has_literature = bool(literature_claims.get("items"))
    usable_human = [
        x for x in (human_evidence or [])
        if x.get("status") == "user_confirmed"
        and x.get("conflict_status") != "contradicted"]
    human_by_case: Dict[str, List[Dict[str, Any]]] = {}
    for item in usable_human:
        human_by_case.setdefault(str(item.get("case_id") or ""), []).append(item)
    system = (
        "你是保守的 MTI 案例分析规划器。为每个案例制定分析计划；只使用输入中的"
        "项目证据与文献主张，不编造译者意图、草稿、过程历史或理论。区分："
        "authentic_revision 是真实历史初译→修订→终译；translation_decision 是"
        "没有历史修订的当前原文—译文决策案例，不得写成"
        "错误修订；synthetic_contrast 是"
        "为分析生成且已验证的模拟初译→错误诊断→当前正式译文对照，绝非作者历史。"
        "evidence_level 决定案例能支持什么。对每个案例给出 problem（必须是具体"
        "翻译问题；证据不足时 grounded=false 并说明需要什么人工证据）、"
        "initial_failure（authentic 指历史初译不足；synthetic 只能指模拟初译中的"
        "已验证错误，必须明确 simulated=true）、"
        "alternatives（必须标注 historical_alternative / analytical_comparison / "
        "counterfactual_rendering；没有证据的备选一律 counterfactual_rendering）、"
        "decision_rationale、translation_effect（dimension 必须取自 "
        "semantic_precision/logical_relation/reference_clarity/information_structure/"
        "register/rhythm/reader_processing/narrative_voice/pragmatic_force/"
        "cultural_accessibility/terminological_precision，且 demonstrated_by 必须引用"
        "具体文本特征；无法具体说明时省略）、theory_mapping（仅当存在文献主张时给出"
        "concept/source_feature/target_requirement/relation 四元组，否则置 null）、"
        "bounded_conclusion（只限本案例）、recommended_human_evidence（证据缺口清单）。"
        "synthetic 的 bounded_conclusion 必须说明它只展示合理失败模式，不证明错误频率；"
        "不得给 synthetic 使用 historical_alternative 或任何历史过程语言。"
        "只输出 JSON：{\"plans\":[{\"case_id\":\"...\",\"problem\":{\"type\":\"...\","
        "\"statement\":\"...\",\"grounded\":true},\"initial_failure\":{...}|null,"
        "\"alternatives\":[{\"label\":\"counterfactual_rendering\",\"text\":\"...\"}],"
        "\"decision_rationale\":\"...\",\"translation_effect\":{\"dimension\":\"...\","
        "\"demonstrated_by\":\"...\"}|null,\"theory_mapping\":{\"concept\":\"...\","
        "\"source_feature\":\"...\",\"target_requirement\":\"...\",\"relation\":\"...\"}|null,"
        "\"bounded_conclusion\":\"...\",\"recommended_human_evidence\":[\"...\"],"
        "\"human_evidence_ids\":[\"HE-...\"]}]}。"
        " 可选输入 human_evidence 是作者事后提供的解释。若某案例有可用 human_evidence，"
        "decision_rationale 可以引用它并在 human_evidence_ids 列出对应 id；不得把作者"
        "事后解释写成项目同期过程；human_evidence_ids 只能引用该案例自己的证据。"
    )
    payload = _scoped_planner_input(
        evidence, selected_cases, argument_plan, literature_claims)
    payload["human_evidence"] = [
        {k: x.get(k) for k in ("human_evidence_id", "case_id", "question_type",
                               "answer")}
        for x in usable_human]
    raw = None
    for attempt in range(2):
        suffix = "" if attempt == 0 else "\n上次输出无效；仅输出合法 JSON 对象。"
        try:
            response = call_llm(provider, api_key, model, system + suffix,
                                json.dumps(payload, ensure_ascii=False), temperature=0.1)
        except Exception:
            response = None
        raw = _parse_json(response) if response else None
        if raw is not None:
            break
    valid_cases = {str(x.get("case_id")) for x in selected_cases.get("cases", [])}
    plans = []
    seen = set()
    for item in (raw or {}).get("plans") or []:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("case_id") or "")
        if case_id not in valid_cases or case_id in seen:
            continue
        seen.add(case_id)
        adequacy = adequacy_by_case.get(case_id, {})
        selected_case = case_provenance.with_provenance(
            selected_by_id.get(case_id) or {})
        case_type = case_provenance.case_type(selected_case)
        cannot = set(adequacy.get("cannot_support") or [])
        problem = item.get("problem") if isinstance(item.get("problem"), dict) else {}
        human_ids = [str(x) for x in item.get("human_evidence_ids") or []]
        valid_human = [x for x in human_ids
                       if x in {h.get("human_evidence_id")
                                for h in human_by_case.get(case_id, [])}]
        problem_type = str(problem.get("type") or "other")
        if problem_type not in PROBLEM_TYPES:
            problem_type = "other"
        grounded = bool(problem.get("grounded"))
        if grounded and not (
                adequacy.get("capabilities", {}).get("has_meaningful_revision")
                or adequacy.get("capabilities", {}).get(
                    "has_translation_decision_evidence")
                or adequacy.get("capabilities", {}).get(
                    "has_validated_synthetic_contrast")):
            grounded = False
        initial_failure = item.get("initial_failure")
        if case_type == "synthetic_contrast" and isinstance(initial_failure, dict):
            initial_failure = {**initial_failure, "simulated": True}
        elif case_type == "translation_decision":
            initial_failure = None
        elif isinstance(initial_failure, dict) and cannot & {
                "historical_revision_reasoning", "initial_failure_reasoning"}:
            initial_failure = None
        alternatives = []
        for alt in item.get("alternatives") or []:
            if not isinstance(alt, dict):
                continue
            label = str(alt.get("label") or "counterfactual_rendering")
            if label not in ALTERNATIVE_LABELS:
                label = "counterfactual_rendering"
            if label == "historical_alternative" and (
                    case_type in {"synthetic_contrast", "translation_decision"} or cannot & {
                        "historical_revision_reasoning"}):
                label = "analytical_comparison"
            alternatives.append({"label": label,
                                 "text": str(alt.get("text") or "")[:300]})
        effect = item.get("translation_effect")
        if not isinstance(effect, dict) or not effect.get("dimension") \
                or not effect.get("demonstrated_by"):
            effect = None
        theory_mapping = None
        if has_literature:
            mapping = item.get("theory_mapping")
            if isinstance(mapping, dict) and mapping.get("concept") \
                    and mapping.get("source_feature") and mapping.get("relation"):
                theory_mapping = {
                    "concept": str(mapping.get("concept"))[:120],
                    "source_feature": str(mapping.get("source_feature"))[:300],
                    "target_requirement": str(mapping.get("target_requirement") or "")[:300],
                    "relation": str(mapping.get("relation"))[:300],
                }
        plans.append({
            "case_id": case_id,
            "case_type": case_type,
            "case_origin": selected_case.get("case_origin"),
            "text_role": dict(selected_case.get("text_role") or {}),
            "review_status": selected_case.get("review_status", "unreviewed"),
            "analysis_contract_type": case_type,
            "case_role": adequacy.get("case_role", "non_revision_case"),
            "capabilities": {
                **adequacy.get("capabilities", {}),
                "has_revision_rationale": bool(valid_human),
                "has_theory_support": bool(theory_mapping),
            },
            "evidence_level": adequacy.get("evidence_level", "source_final_only"),
            "can_support": adequacy.get("can_support", []),
            "cannot_support": sorted(cannot),
            "translation_delta": adequacy.get("translation_delta", {}),
            "source_segment_id": selected_case.get("source_segment_id"),
            "source_text": selected_case.get("source_text")
            if case_type == "synthetic_contrast" else None,
            "synthetic_baseline": selected_case.get("synthetic_baseline")
            if case_type == "synthetic_contrast" else None,
            "baseline_origin": selected_case.get("baseline_origin")
            if case_type == "synthetic_contrast" else None,
            "legacy_analysis_seed": selected_case.get("legacy_analysis_seed")
            if case_type == "synthetic_contrast" else None,
            "error_manifest": selected_case.get("error")
            if case_type == "synthetic_contrast" else None,
            "optimized_translation": selected_case.get("optimized_translation")
            if case_type == "synthetic_contrast" else None,
            "final_target": selected_case.get("final_target")
            if case_type == "synthetic_contrast" else None,
            "target_contrast_text": selected_case.get("target_contrast_text")
            if case_type == "synthetic_contrast" else None,
            "synthetic_evidence": selected_case.get("synthetic_evidence")
            if case_type == "synthetic_contrast" else None,
            "synthetic_validation": selected_case.get("validation")
            if case_type == "synthetic_contrast" else None,
            "problem": {
                "type": problem_type,
                "statement": str(problem.get("statement") or "")[:300],
                "grounded": grounded,
            },
            "initial_failure": initial_failure if isinstance(initial_failure, dict)
            and str(initial_failure.get("description") or "") else None,
            "alternatives": alternatives,
            "decision_rationale": str(item.get("decision_rationale") or "")[:400],
            "translation_effect": effect,
            "theory_mapping": theory_mapping,
            "theory_connection_status": (
                "mapped" if theory_mapping else
                "not_applicable" if not has_literature else "missing"),
            "bounded_conclusion": str(item.get("bounded_conclusion") or "")[:300],
            "human_evidence_ids": valid_human,
            "human_evidence": [
                {k: h.get(k) for k in ("human_evidence_id", "question_type",
                                       "answer", "question")}
                for h in human_by_case.get(case_id, [])
                if h.get("human_evidence_id") in valid_human],
            "recommended_human_evidence": [
                str(x)[:200] for x in (item.get("recommended_human_evidence") or [])][:6],
            "analysis_contract": {
                component: "planned" for component in ANALYSIS_CONTRACT},
        })
    missing = sorted(valid_cases - seen)
    for case_id in missing:
        adequacy = adequacy_by_case.get(case_id, {})
        selected_case = case_provenance.with_provenance(
            selected_by_id.get(case_id) or {})
        case_type = case_provenance.case_type(selected_case)
        plans.append({
            "case_id": case_id,
            "case_type": case_type,
            "case_origin": selected_case.get("case_origin"),
            "text_role": dict(selected_case.get("text_role") or {}),
            "review_status": selected_case.get("review_status", "unreviewed"),
            "analysis_contract_type": case_type,
            "case_role": adequacy.get("case_role", "non_revision_case"),
            "capabilities": adequacy.get("capabilities", {}),
            "evidence_level": adequacy.get("evidence_level", "source_final_only"),
            "can_support": adequacy.get("can_support", []),
            "cannot_support": adequacy.get("cannot_support", []),
            "translation_delta": adequacy.get("translation_delta", {}),
            "source_segment_id": selected_case.get("source_segment_id"),
            "source_text": selected_case.get("source_text")
            if case_type == "synthetic_contrast" else None,
            "synthetic_baseline": selected_case.get("synthetic_baseline")
            if case_type == "synthetic_contrast" else None,
            "error_manifest": selected_case.get("error")
            if case_type == "synthetic_contrast" else None,
            "optimized_translation": selected_case.get("optimized_translation")
            if case_type == "synthetic_contrast" else None,
            "final_target": selected_case.get("final_target")
            if case_type == "synthetic_contrast" else None,
            "target_contrast_text": selected_case.get("target_contrast_text")
            if case_type == "synthetic_contrast" else None,
            "synthetic_evidence": selected_case.get("synthetic_evidence")
            if case_type == "synthetic_contrast" else None,
            "synthetic_validation": selected_case.get("validation")
            if case_type == "synthetic_contrast" else None,
            "problem": {"type": "other", "statement": "", "grounded": False},
            "initial_failure": None,
            "alternatives": [],
            "decision_rationale": "",
            "translation_effect": None,
            "theory_mapping": None,
            "theory_connection_status": "not_applicable" if not has_literature
            else "missing",
            "bounded_conclusion": "",
            "human_evidence_ids": [],
            "human_evidence": [],
            "recommended_human_evidence": [
                "规划失败：请提供该案例的具体翻译问题与过程证据。"],
            "analysis_contract": {
                component: "unplanned" for component in ANALYSIS_CONTRACT},
        })
    for plan in plans:
        selected_case = case_provenance.with_provenance(
            selected_by_id.get(str(plan.get("case_id"))) or {})
        plan.update({
            "case_origin": selected_case.get("case_origin"),
            "text_role": dict(selected_case.get("text_role") or {}),
            "review_status": selected_case.get("review_status", "unreviewed"),
            "source_segment_id": selected_case.get("source_segment_id") or
            selected_case.get("segment_id") or plan.get("source_segment_id"),
            "research_question_ids": list(selected_case.get("research_questions") or []),
            "difficulty_group": selected_case.get("difficulty_group"),
            "strategy_group": selected_case.get("strategy_group"),
            "difficulty_subsection": selected_case.get("difficulty_subsection"),
            "strategy_subsection": selected_case.get("strategy_subsection"),
            "target_subsection": selected_case.get("target_subsection"),
            "focus": selected_case.get("focus"),
        })
    plans.sort(key=lambda x: x["case_id"])
    artifact = {"schema_version": ANALYSIS_VERSION, "plans": plans}
    artifact["content_hash"] = stable_hash(
        {k: v for k, v in artifact.items() if k != "content_hash"})
    return artifact


def plan_index(artifact: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {x["case_id"]: x for x in artifact.get("plans", [])}


def render_analysis_contract(plan: Dict[str, Any]) -> str:
    """Human/machine-readable contract the writer must realise."""
    if plan.get("case_type") == "synthetic_contrast":
        baseline = (plan.get("synthetic_baseline") or {}).get("text", "")
        optimized = plan.get("target_contrast_text") or plan.get("final_target") or (
            plan.get("optimized_translation") or {}).get("text", "")
        error = plan.get("error_manifest") or {}
        validation = plan.get("synthetic_validation") or {}
        lines = [
            f"案例 {plan.get('case_id')}（synthetic_contrast；非历史证据）",
            "- 推理链：翻译难点 → 合理模拟错误 → 错误诱因 → 错误诊断 → "
            "意义/功能失真 → 当前正式译文对照 → 修复验证 → 理论连接（若有）→ 有界结论",
            f"- 真实源文：{plan.get('source_text') or ''}",
            f"- 模拟初译：{baseline}",
            f"- 错误诊断：{error.get('diagnosis') or '（未计划，需如实说明）'}",
            f"- 当前正式译文（改译对照）：{optimized}",
            f"- 修复验证：{validation.get('reason') or validation.get('repair_correctness')}",
            "- 来源边界：模拟初译属于分析阶段构造；当前正式译文来自项目 target，不属于历史改译证据。",
            "- 必须使用 SYNTHETIC_SOURCE / SIMULATED / OPTIMIZED 标签；"
            "禁止‘笔者初译/经审校修改/最终修订’等历史过程措辞。",
            "- 结论边界：只说明一种合理失败模式，不声称其在人类译者中常见。",
        ]
        mapping = plan.get("theory_mapping")
        if mapping:
            lines.append(
                f"- 理论映射：{mapping.get('concept')}：源语特征「{mapping.get('source_feature')}」"
                f"→ 目标需求「{mapping.get('target_requirement')}」→ 关系「{mapping.get('relation')}」")
        for item in plan.get("recommended_human_evidence") or []:
            lines.append(f"- 可选人工判断：{item}")
        return "\n".join(lines)
    if plan.get("case_type") == "translation_decision":
        lines = [
            f"案例 {plan.get('case_id')}（translation_decision；无历史修订）",
            "- 推理链：真实翻译难点 → 当前译文决策 → 术语/句法/修辞或 QA 证据 → "
            "决策理由 → 具体效果 → 有界结论",
            "- 标签：使用 SOURCE / TARGET；不得声称发生过初译错误或历史修订。",
            f"- 问题：{plan.get('problem', {}).get('statement') or '（未计划，需如实说明）'}",
        ]
        if plan.get("decision_rationale"):
            lines.append(f"- 决策理由：{plan['decision_rationale']}")
        effect = plan.get("translation_effect")
        if effect:
            lines.append(
                f"- 效果维度：{effect.get('dimension')}（依据：{effect.get('demonstrated_by')}）")
        if plan.get("bounded_conclusion"):
            lines.append(f"- 有界结论：{plan['bounded_conclusion']}")
        lines.append("- 证据边界：译文未发生变化，只能分析可观察的翻译决策，不能重构历史改译过程。")
        return "\n".join(lines)
    lines = [
        f"案例 {plan.get('case_id')}（{plan.get('case_role')}；"
        f"{plan.get('evidence_level')}）",
        "- 推理链：翻译问题 → 初译不足 → finding/文本差异 → 修订决策 → "
        "终译 → 实际变化 → 改进理由 → 理论连接（若有）→ 有界结论",
        f"- 问题：{plan.get('problem', {}).get('statement') or '（未计划，需如实说明）'}",
    ]
    initial = plan.get("initial_failure")
    if initial:
        lines.append(f"- 初始方案/失败：{initial.get('description', '')}")
    for alt in plan.get("alternatives") or []:
        lines.append(f"- 备选（{alt.get('label')}）：{alt.get('text')}")
    if plan.get("decision_rationale"):
        lines.append(f"- 决策理由：{plan['decision_rationale']}")
    effect = plan.get("translation_effect")
    if effect:
        lines.append(
            f"- 效果维度：{effect.get('dimension')}（依据：{effect.get('demonstrated_by')}）")
    mapping = plan.get("theory_mapping")
    if mapping:
        lines.append(
            f"- 理论映射：{mapping.get('concept')}：源语特征「{mapping.get('source_feature')}」"
            f"→ 目标需求「{mapping.get('target_requirement')}」→ 关系「{mapping.get('relation')}」")
    else:
        lines.append(f"- 理论映射：{plan.get('theory_connection_status')}")
    if plan.get("bounded_conclusion"):
        lines.append(f"- 有界结论：{plan['bounded_conclusion']}")
    for item in plan.get("recommended_human_evidence") or []:
        lines.append(f"- 需要人工证据：{item}")
    return "\n".join(lines)


def contract_completion(plan: Dict[str, Any]) -> Dict[str, str]:
    statuses = {}
    statuses["translation_problem"] = (
        "strong" if plan.get("problem", {}).get("grounded") and plan.get(
            "problem", {}).get("statement") else
        "weak" if plan.get("problem", {}).get("statement") else "missing")
    statuses["difficulty_evidence"] = (
        "strong" if plan.get("translation_delta", {}).get("changed") or plan.get(
            "translation_delta", {}).get("finding_link") else
        "not_applicable" if plan.get("evidence_level") == "source_final_only"
        else "weak")
    statuses["initial_solution_or_failure"] = (
        "strong" if plan.get("initial_failure") else
        "not_applicable" if plan.get("evidence_level") == "source_final_only"
        else "missing")
    statuses["alternative_interpretation_or_strategy"] = (
        "adequate" if plan.get("alternatives") else "missing")
    statuses["final_translation_decision"] = (
        "strong" if plan.get("decision_rationale") else "weak")
    statuses["decision_rationale"] = (
        "strong" if plan.get("decision_rationale") else "missing")
    statuses["translation_effect"] = (
        "strong" if plan.get("translation_effect") else "missing")
    statuses["theory_connection"] = plan.get("theory_connection_status", "not_applicable")
    statuses["evidence_boundary"] = (
        "adequate" if plan.get("cannot_support") else "weak")
    statuses["case_level_conclusion"] = (
        "strong" if plan.get("bounded_conclusion") else "missing")
    return statuses
