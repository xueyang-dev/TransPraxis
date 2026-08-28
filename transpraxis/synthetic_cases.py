"""Synthetic contrast cases for evidence-bounded MTI analysis.

The source is real project evidence.  Every baseline, diagnosis and optimized
translation is an academic experiment and is never written to project state.
"""
from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import academic_evidence
from . import case_provenance
from .academic_evidence import has_meaningful_revision, segment_index, stable_hash

OPPORTUNITY_VERSION = "synthetic-opportunity-v6"
BASELINE_VERSION = "synthetic-baseline-v2"
ERROR_MANIFEST_VERSION = "synthetic-error-manifest-v3"
OPTIMIZER_VERSION = "synthetic-optimizer-v2"
VALIDATION_VERSION = "synthetic-validation-v8"

CASE_TYPE = "synthetic_contrast"
ERROR_CATEGORIES = (
    "lexical_polysemy", "idiom_misreading", "syntax_attachment",
    "logical_relation", "negation_scope", "reference_resolution",
    "cultural_reference", "proper_noun", "register", "narrative_voice",
    "metaphor", "pragmatic_implication", "information_structure",
    "cohesion", "temporal_relation", "overliteral_translation",
    "undertranslation", "overtranslation",
)
MATERIALITY = ("major", "moderate", "minor", "none")
PLAUSIBILITY = ("plausible", "borderline", "implausible")
CONFIRMATION = ("confirmed", "partial", "not_confirmed")

_SIGNALS = (
    ("negation_scope", re.compile(r"\b(?:not|never|neither|nor|no longer|without)\b", re.I)),
    ("logical_relation", re.compile(r"\b(?:although|unless|whereas|despite|while|since)\b", re.I)),
    ("syntax_attachment", re.compile(r"\b(?:which|that|who|whom|whose)\b", re.I)),
    ("reference_resolution", re.compile(r"\b(?:it|this|that|they|them|he|she|his|her)\b", re.I)),
    ("temporal_relation", re.compile(r"\b(?:before|after|until|when|then|already|still)\b", re.I)),
    ("information_structure", re.compile(r"[—–:;]|[“”\"]")),
    ("proper_noun", re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")),
)

_REVIEW_CATEGORY_SIGNAL = {
    "lexical_polysemy": re.compile(r"含义|语义|词义|译为"),
    "idiom_misreading": re.compile(r"习语|短语|意为|直译|字面"),
    "syntax_attachment": re.compile(r"修饰|从句|主语|宾语|句法"),
    "logical_relation": re.compile(r"逻辑|因果|转折|并列|关系"),
    "negation_scope": re.compile(r"否定|范围|不再|并非"),
    "reference_resolution": re.compile(r"指代|主语|人物|所指"),
    "cultural_reference": re.compile(r"文化|典故|惯例|通用译名"),
    "proper_noun": re.compile(r"人名|地名|专有|保留原文|标准译名"),
    "register": re.compile(r"语域|口语|书面|正式|生硬"),
    "narrative_voice": re.compile(r"叙事|语气|视角|口吻"),
    "metaphor": re.compile(r"比喻|隐喻|拟人|字面"),
    "pragmatic_implication": re.compile(r"语用|暗含|意蕴|言外"),
    "information_structure": re.compile(r"信息|强调|焦点|并列|结构"),
    "cohesion": re.compile(r"衔接|连贯|指代|重复"),
    "temporal_relation": re.compile(r"时间|先后|此前|随后"),
    "overliteral_translation": re.compile(r"直译|字面|生硬"),
    "undertranslation": re.compile(r"漏译|缺失|未完整|省略"),
    "overtranslation": re.compile(r"增译|增加|原文仅|过度"),
}


def _parse_json(text: Any) -> Optional[Dict[str, Any]]:
    candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text or "").strip(),
                       flags=re.DOTALL)
    try:
        value = json.loads(candidate)
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _call_json(
    call_llm: Callable, provider: str, api_key: str, model: str,
    system: str, payload: Dict[str, Any], temperature: float,
) -> Dict[str, Any]:
    last_error = ""
    last_response = ""
    for attempt in range(2):
        try:
            response = call_llm(
                provider, api_key, model,
                system + ("" if attempt == 0 else "\nReturn valid JSON only."),
                json.dumps(payload, ensure_ascii=False), temperature=temperature)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"[:500]
            response = None
        last_response = str(response or "")
        parsed = _parse_json(response)
        if parsed is not None:
            parsed["_call_status"] = "ok"
            return parsed
    if last_error:
        return {"_call_status": "error", "_call_error": last_error}
    return {"_call_status": "invalid_json",
            "_invalid_response_excerpt": last_response[:500]}


def _artifact(version: str, items: List[Dict[str, Any]], **metadata: Any) -> Dict[str, Any]:
    return {
        "schema_version": version,
        **metadata,
        "items": items,
        "content_hash": stable_hash(items),
    }


def _screening_signals(source: str) -> List[str]:
    signals = [name for name, pattern in _SIGNALS if pattern.search(source)]
    if len(source) >= 100 and source.count(",") >= 2:
        signals.append("multi_clause_structure")
    if re.search(r"\b[A-Za-z]+(?:ed|ing)\s+(?:at|for|from|into|of|off|on|out|over|to|up|with)\b",
                 source, re.I):
        signals.append("lexical_or_idiomatic_phrase")
    return signals


def _error_pattern_grounding(
    segment: Dict[str, Any], category: str, trigger: str,
) -> Dict[str, Any]:
    """Use same-segment review history only when it explicitly names the trigger."""
    category_signal = _REVIEW_CATEGORY_SIGNAL.get(category)
    matches = []
    for finding in segment.get("process_evidence", {}).get("findings") or []:
        reason = str(finding.get("reason") or "")
        if finding.get("severity") not in {"actionable", "blocking"}:
            continue
        if not trigger or trigger.casefold() not in reason.casefold():
            continue
        if category_signal and not category_signal.search(reason):
            continue
        matches.append({
            "type": str(finding.get("type") or "review"),
            "severity": str(finding.get("severity") or ""),
            "reason": reason[:500],
        })
    if matches:
        return {
            "type": "project_review_pattern",
            "supporting_findings": matches[:3],
            "empirical_frequency_supported": False,
        }
    return {"type": "model_inference", "empirical_frequency_supported": False}


def _error_id(case: Dict[str, Any]) -> str:
    source_id = str(case.get("opportunity_id") or case.get("case_id") or "")
    return f"ERR-{source_id.rsplit('-', 1)[-1]}"


def _passage_for_trigger(source: str, trigger: str) -> str:
    """Return the complete sentence range containing an exact trigger span."""
    folded_source, folded_trigger = source.casefold(), trigger.casefold()
    start = folded_source.find(folded_trigger)
    if start < 0:
        return ""
    end = start + len(trigger)
    boundary = re.compile(
        r"[.!?。！？](?:[\"'”’])?(?:[0-9⁰¹²³⁴⁵⁶⁷⁸⁹]+)?"
        r"(?=\s|$|[A-Z\u3400-\u9fff])")
    prior = list(boundary.finditer(source[:start]))
    passage_start = prior[-1].end() if prior else 0
    following = boundary.search(source[end:])
    passage_end = end + following.end() if following else len(source)
    return source[passage_start:passage_end].strip()


def _target_excerpt_for_source(
    source: str, source_excerpt: str, target: str,
) -> str:
    """Bind a focused source passage to an excerpt of the saved target.

    Synthetic opportunities are intentionally focused on one source passage,
    while project evidence stores paragraph-level targets.  Sentence order is
    the only alignment assumption available here; the returned text remains an
    exact substring of the saved target and is never a generated translation.
    """
    if not source or not source_excerpt or not target:
        return ""
    start = source.casefold().find(source_excerpt.casefold())
    if start < 0:
        return ""
    boundary = re.compile(
        r"[.!?。！？](?:[\"'”’])?(?:[0-9⁰¹²³⁴⁵⁶⁷⁸⁹]+)?"
        r"(?=\s|$|[A-Z\u3400-\u9fff])")
    source_prefix_count = len(boundary.findall(source[:start]))
    source_sentence_count = max(1, len(boundary.findall(source_excerpt)))
    spans = []
    cursor = 0
    for match in boundary.finditer(target):
        spans.append((cursor, match.end()))
        cursor = match.end()
    if cursor < len(target.strip()):
        spans.append((cursor, len(target)))
    if not spans:
        return target
    first = min(source_prefix_count, len(spans) - 1)
    last = min(len(spans), first + source_sentence_count)
    return target[spans[first][0]:spans[last - 1][1]].strip()


def _bounded_source_pool(
    evidence: Dict[str, Any], max_scan: int,
) -> List[Dict[str, Any]]:
    segments = evidence.get("project_evidence", {}).get("segments", [])
    candidates = []
    for segment in segments:
        source = str(segment.get("source") or "").strip()
        final_target = str(segment.get("final_target") or "").strip()
        if segment.get("integrity_flags") or not final_target:
            continue
        signals = _screening_signals(source)
        if not source or not signals:
            continue
        candidates.append((len(signals), len(source), segment, signals))
    candidates.sort(key=lambda row: (-row[0], -min(row[1], 300), row[2]["segment_index"]))
    chosen: Dict[str, Dict[str, Any]] = {}
    zones = ("beginning", "middle", "end")
    for zone in zones:
        for _, _, segment, signals in candidates:
            if segment.get("coverage_zone") == zone:
                chosen[segment["segment_id"]] = {"segment": segment, "signals": signals}
                break
    for _, _, segment, signals in candidates:
        if len(chosen) >= max_scan:
            break
        chosen.setdefault(segment["segment_id"], {"segment": segment, "signals": signals})
    ordered = sorted(chosen.values(), key=lambda x: x["segment"]["segment_index"])
    by_index = {int(x.get("segment_index")): x for x in segments}
    return [{
        "segment_id": row["segment"]["segment_id"],
        "segment_index": row["segment"]["segment_index"],
        "source_text": str(row["segment"].get("source") or "")[:1200],
        "context_before": str((by_index.get(row["segment"]["segment_index"] - 1) or {}).get(
            "source") or "")[:500],
        "context_after": str((by_index.get(row["segment"]["segment_index"] + 1) or {}).get(
            "source") or "")[:500],
        "screening_signals": row["signals"],
    } for row in ordered]


def _deterministic_opportunity_pool(
    evidence: Dict[str, Any], existing_segment_ids: Iterable[str], limit: int,
) -> List[Dict[str, Any]]:
    """Fill a screened opportunity pool from evidence-derived case signals.

    This is a candidate generator, not an acceptance gate.  Every fallback
    opportunity still goes through baseline plausibility, materiality, repair,
    and academic-value validation before it can reach a report.
    """
    segments = segment_index(evidence)
    glossary = evidence.get("project_evidence", {}).get("glossary", [])
    seen = {str(x) for x in existing_segment_ids}
    candidates = list(evidence.get("translation_decision_candidates") or [])
    candidates.sort(key=lambda x: (-float(x.get("score") or 0),
                                   int(x.get("segment_index") or 0)))
    out = []
    for candidate in candidates:
        if len(out) >= limit:
            break
        segment_id = str(candidate.get("source_segment_id") or "")
        if not segment_id or segment_id in seen:
            continue
        segment = segments.get(segment_id) or {}
        source = str(segment.get("source") or "")
        if not source or segment.get("integrity_flags"):
            continue
        features = candidate.get("features") or {}
        term_anchor, term = academic_evidence._term_anchor(segment, glossary, source)
        proper = re.search(
            r"\b[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+)+\b", source)
        rhetoric = re.search(
            r"\b(?:gaze|flatten(?:ing)?|fluidity|imaginary|metaphor|vulnerab|"
            r"estrangement|affective|nonhuman|community|world-scale)\w*\b",
            source, re.IGNORECASE)
        connector = re.search(
            r"\b(?:although|whereas|rather|instead|because|since|while|despite|"
            r"not only|but also|unless)\b", source, re.IGNORECASE)
        pronoun = re.search(r"\b(?:it|this|that|they|them|which|who|whose)\b",
                            source, re.IGNORECASE)
        if term_anchor and int(features.get("term_count") or 0) >= 1 and term:
            category = "lexical_polysemy"
            trigger = str(term.get("source") or source[term_anchor[0]:term_anchor[1]])
            reason = ("该术语在当前文本中承担概念识别功能；普通译者可能采用一个表面可通、"
                      "但概念边界或术语链关联较弱的对应词。")
            failure = "采用字面或近义术语后，概念边界与同段术语关系变弱。"
        elif proper:
            category = "proper_noun"
            trigger = proper.group(0)
            reason = ("该专名同时涉及文本指称与背景识别；普通译者可能选择合理但不够稳定的"
                      "音译、意译或专名形式。")
            failure = "专名处理基本可读，但会削弱指称稳定性或文化识别线索。"
        elif rhetoric:
            category = "metaphor"
            trigger = rhetoric.group(0)
            reason = ("该表达在上下文中承担修辞或评价功能；普通译者可能作语义上可成立的"
                      "字面处理，却没有充分保留其意象或论述功能。")
            failure = "字面处理保留基本意义，但会压平隐喻、评价色彩或语篇作用。"
        elif connector and int(features.get("clause_markers") or 0) >= 2:
            category = "information_structure"
            trigger = connector.group(0)
            reason = ("该连接结构组织了让步、转折或焦点关系；普通译者可能保留过多英语"
                      "信息顺序，使逻辑关系在中文中不够显化。")
            failure = "逻辑关系大体可恢复，但信息焦点或句间层次不够清晰。"
        elif pronoun and len(source) >= 80:
            category = "reference_resolution"
            trigger = pronoun.group(0)
            reason = ("该指代需要结合局部语境解析；普通译者可能使用形式上对应的指代词，"
                      "但使所指关系或篇章衔接变得含混。")
            failure = "形式对应保留了指代，却没有充分显化中文读者需要的所指关系。"
        elif int(features.get("clause_markers") or 0) >= 3:
            category = "syntax_attachment"
            trigger = (connector or pronoun).group(0) if (connector or pronoun) else source[:24]
            reason = ("该句包含多层修饰或从属关系；普通译者可能基本保留英语修饰顺序，"
                      "造成中文修饰边界或信息焦点不够自然。")
            failure = "语义基本完整，但修饰层级和信息焦点仍受英语句法牵引。"
        else:
            continue
        passage = _passage_for_trigger(source, trigger)
        if not passage:
            continue
        seen.add(segment_id)
        index = int(candidate.get("segment_index") or segment.get("segment_index") or 0)
        out.append({
            "opportunity_id": f"EO-F{index:04d}",
            "segment_id": segment_id,
            "segment_index": index,
            "source_text": passage,
            "context_before": "",
            "context_after": "",
            "error_category": category,
            "trigger_span": trigger,
            "difficulty_reason": reason,
            "likely_failure_mode": failure,
            "academic_value": "high" if category in {
                "lexical_polysemy", "metaphor", "information_structure",
                "syntax_attachment"} else "medium",
            "confidence": "medium",
            "error_pattern_grounding": {
                "type": "model_inference",
                "empirical_frequency_supported": False,
            },
        })
    return out


def mine_error_opportunities(
    evidence: Dict[str, Any], call_llm: Callable, provider: str, api_key: str,
    model: str, max_scan: int = 16, max_opportunities: int = 8,
) -> Dict[str, Any]:
    """Find grounded error opportunities without seeing any saved translation."""
    source_pool = _bounded_source_pool(evidence, max_scan)
    system = (
        "You identify a small set of academically useful translation-error opportunities "
        "in real English source passages. A difficulty must name the exact source trigger "
        "and explain a realistic mistranslation mechanism. Do not select a sentence merely "
        "because it is long. Prefer a defensible terminology, syntactic/information-structure, "
        "rhetorical, cultural/proper-name or cohesion contrast when the source supports one; "
        "use negation or temporal categories only when a direct reading would materially change "
        "meaning or function. Keep the returned opportunities varied when the source pool allows "
        "it, rather than assigning the same category to every sentence. Do not claim that humans "
        "commonly make the error. Return JSON "
        "only: {\"opportunities\":[{\"segment_id\":\"seg-...\",\"error_category\":"
        "\"lexical_polysemy|idiom_misreading|syntax_attachment|logical_relation|"
        "negation_scope|reference_resolution|cultural_reference|proper_noun|register|"
        "narrative_voice|metaphor|pragmatic_implication|information_structure|cohesion|"
        "temporal_relation|overliteral_translation|undertranslation|overtranslation\","
        "\"trigger_span\":\"exact source span\",\"difficulty_reason\":\"...\","
        "\"likely_failure_mode\":\"...\",\"academic_value\":\"high|medium\","
        "\"confidence\":\"high|medium\"}]}."
    )
    raw = _call_json(call_llm, provider, api_key, model, system, {
        "source_passages": source_pool,
        "maximum_opportunities": max_opportunities,
        "allowed_categories": list(ERROR_CATEGORIES),
    }, 0.1)
    pool = {x["segment_id"]: x for x in source_pool}
    canonical_segments = segment_index(evidence)
    items = []
    seen = set()
    rejected = []
    category_counts = Counter()
    category_cap = max(1, int(max_opportunities * 0.4))
    for item in raw.get("opportunities") or []:
        if not isinstance(item, dict):
            rejected.append({"reason": "not_an_object"})
            continue
        segment_id = str(item.get("segment_id") or "")
        source = pool.get(segment_id)
        category = str(item.get("error_category") or "")
        trigger = str(item.get("trigger_span") or "").strip()
        reason = str(item.get("difficulty_reason") or "").strip()
        failure = str(item.get("likely_failure_mode") or "").strip()
        if segment_id in seen:
            rejected.append({"segment_id": segment_id, "reason": "duplicate_segment"})
            continue
        if not source:
            rejected.append({"segment_id": segment_id, "reason": "segment_not_in_screened_pool"})
            continue
        if category not in ERROR_CATEGORIES:
            rejected.append({"segment_id": segment_id, "reason": "invalid_error_category",
                             "value": category})
            continue
        if category_counts[category] >= category_cap:
            rejected.append({"segment_id": segment_id,
                             "reason": "category_overrepresented",
                             "value": category})
            continue
        if not trigger or trigger.casefold() not in source["source_text"].casefold():
            rejected.append({"segment_id": segment_id, "reason": "trigger_not_exact_source_span",
                             "value": trigger[:160]})
            continue
        if not reason or not failure:
            rejected.append({"segment_id": segment_id, "reason": "missing_mechanism"})
            continue
        passage = _passage_for_trigger(source["source_text"], trigger)
        if not passage:
            rejected.append({"segment_id": segment_id,
                             "reason": "trigger_passage_not_recoverable"})
            continue
        seen.add(segment_id)
        category_counts[category] += 1
        items.append({
            "opportunity_id": f"EO-{source['segment_index']:04d}",
            "segment_id": segment_id,
            "segment_index": source["segment_index"],
            "source_text": passage,
            "context_before": source["context_before"],
            "context_after": source["context_after"],
            "error_category": category,
            "trigger_span": trigger,
            "difficulty_reason": reason[:500],
            "likely_failure_mode": failure[:500],
            "academic_value": str(item.get("academic_value") or "medium")
            if str(item.get("academic_value") or "medium") in {"high", "medium"}
            else "medium",
            "confidence": str(item.get("confidence") or "medium")
            if str(item.get("confidence") or "medium") in {"high", "medium"}
            else "medium",
            "error_pattern_grounding": _error_pattern_grounding(
                canonical_segments.get(segment_id) or {}, category, trigger),
        })
        if len(items) >= max_opportunities:
            break
    if len(items) < max_opportunities:
        fallback = _deterministic_opportunity_pool(
            evidence, seen, max_opportunities - len(items))
        for opportunity in fallback:
            category = str(opportunity.get("error_category") or "")
            if category_counts[category] >= category_cap:
                continue
            seen.add(str(opportunity.get("segment_id") or ""))
            category_counts[category] += 1
            items.append(opportunity)
            if len(items) >= max_opportunities:
                break
    return _artifact(
        OPPORTUNITY_VERSION, items,
        pipeline_status="complete" if raw.get("_call_status") == "ok" or items else "failed",
        total_source_segments=len(evidence.get("project_evidence", {}).get("segments", [])),
        screened_segments=len(source_pool), opportunities_found=len(items),
        model_call_status=raw.get("_call_status", "unknown"),
        model_call_error=raw.get("_call_error", ""),
        invalid_response_excerpt=raw.get("_invalid_response_excerpt", ""),
        model_response_parsed=raw.get("_call_status") == "ok",
        model_returned_opportunities=len(raw.get("opportunities") or []),
        rejected_opportunities=rejected[:30], taxonomy=list(ERROR_CATEGORIES))


def generate_baselines(
    opportunities: Dict[str, Any], call_llm: Callable, provider: str,
    api_key: str, model: str,
) -> Dict[str, Any]:
    """Generate plausible imperfect baselines without any final translation input."""
    inputs = [{
        "case_id": f"SC-{int(x['segment_index']):04d}",
        "source_text": x["source_text"],
        "context_before": x.get("context_before"),
        "context_after": x.get("context_after"),
        "difficulty": {k: x.get(k) for k in (
            "error_category", "trigger_span", "difficulty_reason",
            "likely_failure_mode")},
    } for x in opportunities.get("items", [])]
    if not inputs:
        return _artifact(BASELINE_VERSION, [], generated=0,
                         pipeline_status=opportunities.get("pipeline_status", "complete"))
    system = (
        "Generate one simulated Chinese initial translation per item for academic contrast. "
        "The supplied targeted issue and likely failure mode are the exact analytical target: "
        "construct a plausible human-like baseline that leaves that one difficulty materially "
        "unresolved, without inventing a different error. Keep the basic meaning, grammar and "
        "surface fluency intact; do not omit a whole sentence, use machine-like nonsense, or "
        "make a gratuitous low-level mistake. If the supplied issue has no defensible material "
        "contrast for this passage, return an empty text for that case rather than forcing one. "
        "You are not seeing and must not infer a historical translation. Return JSON only: "
        "{\"baselines\":[{\"case_id\":\"SC-...\",\"text\":\"...\","
        "\"why_tempting\":\"...\"}]}"
    )
    raw = _call_json(call_llm, provider, api_key, model, system,
                     {"cases": inputs}, 0.45)
    generated = {str(x.get("case_id")): x for x in raw.get("baselines") or []
                 if isinstance(x, dict)}
    items = []
    for opportunity in opportunities.get("items", []):
        case_id = f"SC-{int(opportunity['segment_index']):04d}"
        value = generated.get(case_id) or {}
        text = str(value.get("text") or "").strip()
        items.append(case_provenance.with_provenance({
            "case_id": case_id,
            "case_type": CASE_TYPE,
            "baseline_origin": "newly_generated",
            "opportunity_id": opportunity["opportunity_id"],
            "source_segment_id": opportunity["segment_id"],
            "source_text": opportunity["source_text"],
            "context_before": opportunity.get("context_before", ""),
            "context_after": opportunity.get("context_after", ""),
            "difficulty": {
                "category": opportunity["error_category"],
                "trigger": opportunity["trigger_span"],
                "reason": opportunity["difficulty_reason"],
                "likely_failure_mode": opportunity["likely_failure_mode"],
                "academic_value": opportunity["academic_value"],
                "confidence": opportunity["confidence"],
            },
            "error_pattern_grounding": opportunity["error_pattern_grounding"],
            "synthetic_baseline": {
                "text": text,
                "provenance": "analytical_simulation",
                "baseline_origin": "newly_generated",
                "why_tempting": str(value.get("why_tempting") or "")[:500],
                "generation_reason": opportunity["difficulty_reason"][:500],
                "targeted_issue": opportunity["error_category"],
                "generated_at": str(value.get("generated_at") or "")[:80],
                "generation_status": "generated" if text else "failed",
            },
            "historical": False,
            "generated_for_analysis": True,
            "source_provenance": "project_source",
            "target_provenance": "project_current_target",
            "provenance": {
                "historical": False,
                "generated_for_analysis": True,
            },
            "generation_reason": opportunity["difficulty_reason"][:500],
            "targeted_issue": opportunity["error_category"],
        }))
    return _artifact(BASELINE_VERSION, items, generated=sum(
        x["synthetic_baseline"]["generation_status"] == "generated" for x in items),
        pipeline_status="complete" if raw.get("_call_status") == "ok" else "failed",
        model_call_error=raw.get("_call_error", ""))


def build_error_manifest(
    baselines: Dict[str, Any], call_llm: Callable, provider: str,
    api_key: str, model: str,
) -> Dict[str, Any]:
    """Independently assess baseline plausibility, then diagnose the error."""
    cases = [x for x in baselines.get("items", [])
             if x.get("synthetic_baseline", {}).get("generation_status") == "generated"]
    if not baselines.get("items"):
        return _artifact(ERROR_MANIFEST_VERSION, [], plausible=0,
                         pipeline_status=baselines.get("pipeline_status", "complete"))
    if not cases:
        items = [{
            **case,
            "baseline_plausibility": {
                "status": "implausible",
                "reason": "No simulated baseline was generated.",
            },
            "error": {
                "error_id": _error_id(case),
                "category": case.get("difficulty", {}).get("category", ""),
                "diagnosis": "", "why_tempting": "",
                "meaning_or_function_distortion": "", "materiality": "none",
                "baseline_already_adequate": True, "source_evidence": "",
            },
        } for case in baselines.get("items", [])]
        return _artifact(
            ERROR_MANIFEST_VERSION, items, plausible=0,
            pipeline_status=baselines.get("pipeline_status", "complete"),
            plausibility_call_status="skipped", diagnosis_call_status="skipped")
    plausibility_system = (
        "Independently judge whether each simulated Chinese baseline could plausibly be "
        "produced by a reasonably competent human translator. Reject strawmen, absurd or "
        "unrelated output, gratuitous bad grammar, and translations that are too conveniently "
        "wrong. Do not judge repair quality. Return JSON only: {\"reviews\":[{\"case_id\":"
        "\"SC-...\",\"status\":\"plausible|borderline|implausible\",\"reason\":\"...\"}]}"
    )
    plausibility_raw = _call_json(
        call_llm, provider, api_key, model, plausibility_system,
        {"cases": [{k: x.get(k) for k in ("case_id", "source_text", "context_before",
                                            "context_after", "difficulty", "synthetic_baseline")}
                   for x in cases]}, 0.1)
    plausibility = {str(x.get("case_id")): x for x in plausibility_raw.get("reviews") or []
                    if isinstance(x, dict)}
    plausible_cases = []
    for case in cases:
        review = plausibility.get(case["case_id"]) or {}
        if review.get("status") == "plausible":
            plausible_cases.append(case)
    diagnosis_system = (
        "Diagnose each plausible simulated baseline against its real source and context. "
        "Explain what is misunderstood, why the reading is tempting, and what meaning or "
        "function is distorted. A stylistic preference is not a material error. If the "
        "baseline is already adequate, say so. Return JSON only: {\"diagnoses\":[{"
        "\"case_id\":\"SC-...\",\"category\":\"...\",\"diagnosis\":\"...\","
        "\"why_tempting\":\"...\",\"meaning_or_function_distortion\":\"...\","
        "\"materiality\":\"major|moderate|minor|none\","
        "\"baseline_already_adequate\":false,"
        "\"source_evidence_span\":\"exact continuous source span\","
        "\"source_evidence\":\"brief explanation\"}]}"
    )
    diagnosis_raw = _call_json(
        call_llm, provider, api_key, model, diagnosis_system,
        {"cases": [{k: x.get(k) for k in ("case_id", "source_text", "context_before",
                                            "context_after", "difficulty", "synthetic_baseline")}
                   for x in plausible_cases]}, 0.1) if plausible_cases else {
                       "_call_status": "skipped", "diagnoses": []}
    diagnoses = {str(x.get("case_id")): x for x in diagnosis_raw.get("diagnoses") or []
                 if isinstance(x, dict)}
    items = []
    for case in baselines.get("items", []):
        review = plausibility.get(case["case_id"]) or {}
        status = str(review.get("status") or "implausible")
        if status not in PLAUSIBILITY:
            status = "implausible"
        raw_error = diagnoses.get(case["case_id"]) or {}
        materiality = str(raw_error.get("materiality") or "none")
        if materiality not in MATERIALITY:
            materiality = "none"
        items.append({
            **case,
            "baseline_plausibility": {
                "status": status,
                "reason": str(review.get("reason") or "No valid plausibility review returned.")[:500],
            },
            "error": {
                "error_id": _error_id(case),
                "category": str(raw_error.get("category") or case.get(
                    "difficulty", {}).get("category") or ""),
                "diagnosis": str(raw_error.get("diagnosis") or "")[:700],
                "why_tempting": str(raw_error.get("why_tempting") or "")[:500],
                "meaning_or_function_distortion": str(raw_error.get(
                    "meaning_or_function_distortion") or "")[:700],
                "materiality": materiality,
                "baseline_already_adequate": bool(raw_error.get(
                    "baseline_already_adequate", True)),
                "source_evidence_span": str(raw_error.get(
                    "source_evidence_span") or "")[:300],
                "source_evidence": str(raw_error.get("source_evidence") or "")[:500],
            },
        })
    manifest_ok = plausibility_raw.get("_call_status") == "ok" and (
        not plausible_cases or diagnosis_raw.get("_call_status") == "ok")
    return _artifact(ERROR_MANIFEST_VERSION, items,
                     plausible=sum(x["baseline_plausibility"]["status"] == "plausible"
                                   for x in items),
                     pipeline_status="complete" if manifest_ok else "failed",
                     plausibility_call_status=plausibility_raw.get("_call_status"),
                     diagnosis_call_status=diagnosis_raw.get("_call_status"))


def optimize_translations(
    error_manifest: Dict[str, Any], call_llm: Callable, provider: str,
    api_key: str, model: str, terminology: Optional[Iterable[Dict[str, Any]]] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Bind each baseline to the real current target for controlled contrast.

    The old function name is kept for artifact compatibility.  With project
    evidence it does not generate a replacement translation: the target is
    read-only project evidence and remains separate from translation state.
    """
    if evidence is not None:
        segments = segment_index(evidence)
        items = []
        for case in error_manifest.get("items", []):
            segment = segments.get(str(case.get("source_segment_id") or "")) or {}
            target = str(segment.get("final_target") or segment.get("target") or "").strip()
            baseline_text = str((case.get("synthetic_baseline") or {}).get(
                "text") or "").strip()
            target_contrast = _target_excerpt_for_source(
                str(segment.get("source") or ""),
                str(case.get("source_text") or ""), target)
            items.append(case_provenance.with_provenance({
                **case,
                "final_target": target,
                "target_contrast_text": target_contrast,
                "target_contrast_provenance": "project_current_target",
                "optimized_translation": {
                    "text": target,
                    "focus_text": target_contrast,
                    "provenance": "project_current_target",
                    "repairs_error_id": "",
                    "repair_decision": "",
                    "addresses_error": "",
                    "generation_status": "project_target" if target else "failed",
                },
                "source_provenance": "project_source",
                "target_provenance": "project_current_target",
                "historical": False,
                "generated_for_analysis": True,
                "provenance": {
                    "historical": False,
                    "generated_for_analysis": True,
                },
            }))
        return _artifact(
            OPTIMIZER_VERSION, items,
            generated=0,
            project_targets_bound=sum(bool(x.get("final_target")) for x in items),
            pipeline_status=error_manifest.get("pipeline_status", "complete"),
            model_call_status="not_called_project_target")

    eligible_inputs = [x for x in error_manifest.get("items", [])
                       if x.get("baseline_plausibility", {}).get("status") == "plausible"
                       and x.get("error", {}).get("materiality") in {"major", "moderate"}
                       and not x.get("error", {}).get("baseline_already_adequate")]
    if not error_manifest.get("items"):
        return _artifact(OPTIMIZER_VERSION, [], generated=0,
                         pipeline_status=error_manifest.get("pipeline_status", "complete"))
    if not eligible_inputs:
        items = [{
            **case,
            "optimized_translation": {
                "text": "", "provenance": "ai_optimized_for_analysis",
                "repairs_error_id": case.get("error", {}).get("error_id", ""),
                "repair_decision": "", "addresses_error": "",
                "generation_status": "skipped_or_failed",
            },
        } for case in error_manifest.get("items", [])]
        return _artifact(
            OPTIMIZER_VERSION, items, generated=0,
            pipeline_status=error_manifest.get("pipeline_status", "complete"))
    system = (
        "Produce an independently optimized Chinese translation for each case. It must solve "
        "the diagnosed semantic, pragmatic or structural error and avoid unrelated rewriting. "
        "This is an analytical AI output, not a historical final translation. Return JSON only: "
        "{\"optimizations\":[{\"case_id\":\"SC-...\",\"text\":\"...\","
        "\"repair_decision\":\"...\",\"addresses_error\":\"...\"}]}"
    )
    raw = _call_json(call_llm, provider, api_key, model, system, {
        "cases": [{k: x.get(k) for k in (
            "case_id", "source_text", "context_before", "context_after", "difficulty",
            "synthetic_baseline", "error")} for x in eligible_inputs],
        "terminology_constraints": list(terminology or [])[:30],
    }, 0.2)
    optimized = {str(x.get("case_id")): x for x in raw.get("optimizations") or []
                 if isinstance(x, dict)}
    items = []
    for case in error_manifest.get("items", []):
        value = optimized.get(case["case_id"]) or {}
        text = str(value.get("text") or "").strip()
        items.append(case_provenance.with_provenance({
            **case,
            "optimized_translation": {
                "text": text,
                "provenance": "ai_optimized_for_analysis",
                "repairs_error_id": case.get("error", {}).get("error_id", ""),
                "repair_decision": str(value.get("repair_decision") or "")[:500],
                "addresses_error": str(value.get("addresses_error") or "")[:500],
                "generation_status": "generated" if text else "skipped_or_failed",
            },
        }))
    return _artifact(OPTIMIZER_VERSION, items, generated=sum(
        x["optimized_translation"]["generation_status"] == "generated" for x in items),
        pipeline_status="complete" if raw.get("_call_status") == "ok" else "failed",
        model_call_error=raw.get("_call_error", ""))


def contrast_delta(baseline: Any, optimized: Any) -> Dict[str, Any]:
    baseline_text, optimized_text = str(baseline or ""), str(optimized or "")
    changed = has_meaningful_revision(baseline_text, optimized_text)
    changes = []
    if changed:
        matcher = difflib.SequenceMatcher(None, baseline_text, optimized_text, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "equal":
                changes.append({"operation": tag, "baseline": baseline_text[i1:i2][:120],
                                "optimized": optimized_text[j1:j2][:120]})
    return {"changed": changed, "changes": changes}


def validate_synthetic_cases(
    optimized_artifact: Dict[str, Any], call_llm: Callable, provider: str,
    api_key: str, model: str, evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    reviewable = [x for x in optimized_artifact.get("items", [])
                  if x.get("optimized_translation", {}).get("generation_status")
                  in {"generated", "project_target"}]
    if not optimized_artifact.get("items"):
        return _artifact(VALIDATION_VERSION, [], metrics={
            "synthetic_case_count": 0,
            "synthetic_baselines_generated": 0,
            "baselines_rejected_as_implausible": 0,
            "errors_rejected_as_non_material": 0,
            "repairs_rejected": 0,
            "academically_eligible_synthetic_cases": 0,
            "synthetic_academic_analysis_value": {"pass": 0, "fail": 0},
            "synthetic_baseline_plausibility": {"pass": 0, "fail": 0},
            "synthetic_materiality": {"pass": 0, "fail": 0},
            "synthetic_repair_correctness": {"pass": 0, "fail": 0},
        }, pipeline_status=optimized_artifact.get("pipeline_status", "complete"))
    system = (
        "Independently validate each synthetic contrast. Judge separately whether the error is "
        "grounded in the source, materially different from the current project target, and whether "
        "the current project target fixes the diagnosed problem without changing unrelated meaning. "
        "Confirm academic_analysis_value only when the contrast concerns a non-surface translation "
        "problem, exposes a concrete strategy, has enough local context, can be tied to a research "
        "question, and is worth substantive MTI case analysis rather than repeating another case. "
        "Reject a baseline that is already "
        "correct. Return JSON only: {\"validations\":[{\"case_id\":\"SC-...\","
        "\"diagnosis_grounding\":\"confirmed|partial|not_confirmed\","
        "\"material_difference\":\"confirmed|partial|not_confirmed\","
        "\"error_materiality\":\"confirmed|partial|not_confirmed\","
        "\"repair_correctness\":\"confirmed|partial|not_confirmed\","
        "\"repair_value\":\"confirmed|partial|not_confirmed\","
        "\"academic_analysis_value\":\"confirmed|partial|not_confirmed\","
        "\"baseline_issue_span\":\"exact contiguous span from the baseline showing the diagnosed issue\","
        "\"final_repair_span\":\"exact contiguous span from the project-target focus showing the repair\","
        "\"academic_analysis_value_reason\":\"...\","
        "\"baseline_already_correct\":false,\"unrelated_meaning_change\":false,"
        "\"reason\":\"...\"}]}"
    )
    raw: Dict[str, Any]
    if not reviewable:
        raw = {"_call_status": "skipped", "validations": []}
    else:
        raw = _call_json(call_llm, provider, api_key, model, system, {
            "cases": [{k: x.get(k) for k in (
                "case_id", "source_text", "context_before", "context_after", "difficulty",
                "synthetic_baseline", "baseline_plausibility", "error",
                "optimized_translation", "final_target", "target_contrast_text")}
                       for x in reviewable]
        }, 0.1)
    validations = {str(x.get("case_id")): x for x in raw.get("validations") or []
                   if isinstance(x, dict)}
    items = []
    for case in optimized_artifact.get("items", []):
        raw_validation = validations.get(case["case_id"]) or {}
        checks = {}
        raw_materiality = raw_validation.get("material_difference")
        if raw_materiality is None:
            raw_materiality = raw_validation.get("error_materiality")
        raw_repair_value = raw_validation.get("repair_value")
        if raw_repair_value is None:
            raw_repair_value = raw_validation.get("repair_correctness")
        raw_checks = {
            "diagnosis_grounding": raw_validation.get("diagnosis_grounding"),
            "error_materiality": raw_materiality,
            "repair_correctness": raw_validation.get("repair_correctness"),
            "repair_value": raw_repair_value,
            "academic_analysis_value": raw_validation.get("academic_analysis_value"),
        }
        for key in ("diagnosis_grounding", "error_materiality",
                    "repair_correctness", "repair_value",
                    "academic_analysis_value"):
            value = str(raw_checks.get(key) or "not_confirmed")
            checks[key] = value if value in CONFIRMATION else "not_confirmed"
        delta = contrast_delta(case.get("synthetic_baseline", {}).get("text"),
                               case.get("target_contrast_text") or
                               case.get("final_target") or
                               case.get("optimized_translation", {}).get("text"))
        canonical_segment = segment_index(evidence or {}).get(str(
            case.get("source_segment_id") or ""))
        source_text = str(case.get("source_text") or "")
        baseline_text = str((case.get("synthetic_baseline") or {}).get("text") or "")
        trigger = str(case.get("difficulty", {}).get("trigger") or "")
        source_evidence_span = str(case.get("error", {}).get(
            "source_evidence_span") or "")
        canonical_source = str((canonical_segment or {}).get("source") or "")
        project_target = str((canonical_segment or {}).get("final_target") or "")
        target_contrast = str(case.get("target_contrast_text") or
                              case.get("final_target") or
                              case.get("optimized_translation", {}).get("text") or "")
        baseline_issue_span = str(raw_validation.get("baseline_issue_span") or "").strip()
        final_repair_span = str(raw_validation.get("final_repair_span") or "").strip()
        repair_evidence_confirmed = bool(
            baseline_issue_span and final_repair_span
            and baseline_issue_span in baseline_text
            and final_repair_span in target_contrast
            and has_meaningful_revision(baseline_issue_span, final_repair_span))
        content_baseline = academic_evidence.normalized_translation_target(
            baseline_text, ignore_punctuation=True)
        content_target = academic_evidence.normalized_translation_target(
            target_contrast, ignore_punctuation=True)
        content_matcher = difflib.SequenceMatcher(
            None, content_baseline, content_target, autojunk=False)
        changed_content_size = sum(
            len(content_baseline[i1:i2]) + len(content_target[j1:j2])
            for tag, i1, i2, j1, j2 in content_matcher.get_opcodes()
            if tag != "equal")
        repair_baseline_content = academic_evidence.normalized_translation_target(
            baseline_issue_span, ignore_punctuation=True)
        repair_target_content = academic_evidence.normalized_translation_target(
            final_repair_span, ignore_punctuation=True)
        repair_matcher = difflib.SequenceMatcher(
            None, repair_baseline_content, repair_target_content, autojunk=False)
        repair_opcodes = [op for op in repair_matcher.get_opcodes()
                          if op[0] != "equal"]
        repair_changed_content_size = sum(
            len(repair_baseline_content[i1:i2])
            + len(repair_target_content[j1:j2])
            for tag, i1, i2, j1, j2 in repair_opcodes)
        # A one-word synonym swap is not a controlled analytical contrast by
        # itself.  Keep the threshold small and transparent; a keyed term or
        # name can still pass when the reviewer supplies a real repair span.
        issue_category = str(case.get("difficulty", {}).get("category") or "")
        micro_edit = (len(repair_opcodes) == 1
                      and repair_changed_content_size <= 4
                      and repair_opcodes[0][0] == "replace"
                      and issue_category not in {
                          "proper_noun", "cultural_reference", "lexical_polysemy",
                      })
        term_anchor, term = academic_evidence._term_anchor(
            canonical_segment or {},
            (evidence or {}).get("project_evidence", {}).get("glossary", []),
            canonical_source or source_text)
        trigger_matches_term = bool(
            term and trigger and str(term.get("source") or "").casefold()
            in trigger.casefold())
        target_term_markers = [str(term.get(key) or "") for key in (
            "target", "preferred", "proposed_target") if term]
        target_issue_anchor = (not trigger_matches_term or
                               any(marker and marker in target_contrast
                                   for marker in target_term_markers))
        project_target_status = case.get("optimized_translation", {}).get(
            "generation_status") == "project_target"
        boundary = re.compile(
            r"[.!?。！？](?:[\"'”’])?(?:[0-9⁰¹²³⁴⁵⁶⁷⁸⁹]+)?"
            r"(?=\s|$|[A-Z\u3400-\u9fff])")
        source_sentence_count = max(1, len(boundary.findall(source_text)))
        baseline_sentence_count = max(1, len(re.findall(r"[.!?。！？]", baseline_text)))
        baseline_complete = baseline_sentence_count >= source_sentence_count
        requirements = {
            "real_source_exists": bool(canonical_segment)
            and bool(source_text) and source_text in canonical_source,
            "project_target_grounded": not project_target_status or (
                bool(project_target) and bool(target_contrast)
                and target_contrast in project_target),
            "baseline_complete": baseline_complete,
            "opportunity_grounded": bool(trigger and case.get(
                "difficulty", {}).get("reason"))
            and trigger.casefold() in source_text.casefold(),
            "baseline_plausible": case.get("baseline_plausibility", {}).get(
                "status") == "plausible" and baseline_complete,
            "diagnosis_evidence_backed": checks["diagnosis_grounding"] == "confirmed"
            and bool(source_evidence_span)
            and source_evidence_span.casefold() in source_text.casefold(),
            "error_confirmed": checks["error_materiality"] == "confirmed"
            and case.get("error", {}).get("materiality") in {"major", "moderate"}
            and bool(case.get("error", {}).get("diagnosis")),
            "materiality_pass": checks["error_materiality"] == "confirmed"
            and delta["changed"] and not micro_edit and repair_evidence_confirmed
            and target_issue_anchor,
            "repair_evidence_confirmed": repair_evidence_confirmed,
            "repair_confirmed": checks["repair_correctness"] == "confirmed"
            and repair_evidence_confirmed,
            "repair_value_confirmed": checks["repair_value"] == "confirmed",
            "academic_analysis_value_confirmed": checks[
                "academic_analysis_value"] == "confirmed",
            "analysis_context_sufficient": bool(source_text) and bool(trigger)
            and bool(case.get("context_before") or case.get("context_after")
                      or len(source_text) >= 60),
            "repair_traceable": (
                bool(case.get("final_target"))
                if case.get("optimized_translation", {}).get(
                    "generation_status") == "project_target" else
                bool(case.get("error", {}).get("error_id"))
                and case.get("optimized_translation", {}).get("repairs_error_id")
                == case.get("error", {}).get("error_id")
                and bool(case.get("optimized_translation", {}).get("repair_decision"))
                and bool(case.get("optimized_translation", {}).get("addresses_error"))),
            "meaningful_contrast": delta["changed"],
            "baseline_not_already_correct": not bool(raw_validation.get(
                "baseline_already_correct", True)),
            "no_unrelated_meaning_change": not bool(raw_validation.get(
                "unrelated_meaning_change", True)),
        }
        requirements["academic_analysis_value_confirmed"] = (
            requirements["academic_analysis_value_confirmed"]
            and requirements["analysis_context_sufficient"]
            and bool(case.get("difficulty", {}).get("reason"))
            and case.get("difficulty", {}).get("academic_value", "high") in {
                "high", "medium"})
        eligible = all(requirements.values())
        rejected_reasons = [key for key, passed in requirements.items() if not passed]
        synthetic_evidence = {
            "historical": False,
            "generated_for_analysis": True,
            "baseline_plausibility": "pass" if requirements["baseline_plausible"] else "fail",
            "material_difference": "pass" if requirements["materiality_pass"] else "fail",
            "repair_correctness": "pass" if requirements["repair_confirmed"]
            and requirements["repair_value_confirmed"] else "fail",
            "academic_analysis_value": "pass" if requirements[
                "academic_analysis_value_confirmed"] else "fail",
            "generation_reason": str(case.get("generation_reason") or
                                      case.get("difficulty", {}).get("reason") or "")[:500],
            "targeted_issue": str(case.get("targeted_issue") or
                                   case.get("difficulty", {}).get("category") or "")[:120],
            "academic_analysis_reason": str(raw_validation.get(
                "academic_analysis_value_reason") or raw_validation.get(
                    "reason") or "")[:500],
        }
        items.append(case_provenance.with_provenance({
            **case,
            "synthetic_evidence": synthetic_evidence,
            "actual_delta": delta,
            "validation": {
                **checks,
                "baseline_already_correct": bool(raw_validation.get(
                    "baseline_already_correct", True)),
                "unrelated_meaning_change": bool(raw_validation.get(
                    "unrelated_meaning_change", True)),
                "reason": str(raw_validation.get("reason") or "")[:700],
                "requirements": requirements,
                "repair_evidence": {
                    "baseline_issue_span": baseline_issue_span,
                    "final_repair_span": final_repair_span,
                    "changed_content_size": changed_content_size,
                    "repair_span_changed_content_size": repair_changed_content_size,
                    "micro_edit": micro_edit,
                    "target_issue_anchor": target_issue_anchor,
                },
                "academic_case_eligible": eligible,
                "rejected_reasons": rejected_reasons,
            },
            "theory_potential": (
                "可用于解释该错误机制与修复关系；连接具体理论前仍需 Literature Evidence。"),
            "limitations": [
                "模拟初译不代表作者的历史译文。",
                "该案例只展示一种合理的失败模式，不证明其在人类译者中的发生频率。",
            ],
        }))
    return _artifact(
        VALIDATION_VERSION, items,
        pipeline_status=(
            "failed" if optimized_artifact.get("pipeline_status") == "failed" else
            "complete" if raw.get("_call_status") in {"ok", "skipped"} else "failed"),
        model_call_error=raw.get("_call_error", ""), metrics={
        "synthetic_baselines_generated": sum(
            x.get("synthetic_baseline", {}).get("generation_status") == "generated"
            for x in items),
        "baselines_rejected_as_implausible": sum(
            x.get("synthetic_baseline", {}).get("generation_status") == "generated"
            and x.get("baseline_plausibility", {}).get("status") != "plausible"
            for x in items),
        "errors_rejected_as_non_material": sum(
            x.get("baseline_plausibility", {}).get("status") == "plausible"
            and not x.get("validation", {}).get("requirements", {}).get("error_confirmed")
            for x in items),
        "repairs_rejected": sum(
            x.get("optimized_translation", {}).get("generation_status") == "generated"
            and (not x.get("validation", {}).get("requirements", {}).get("repair_confirmed")
            or not x.get("validation", {}).get("requirements", {}).get(
                "repair_value_confirmed")) for x in items),
        "academically_eligible_synthetic_cases": sum(
            x.get("validation", {}).get("academic_case_eligible") for x in items),
        "synthetic_case_count": sum(
            x.get("validation", {}).get("academic_case_eligible") for x in items),
        "synthetic_baseline_plausibility": {
            "pass": sum(x.get("synthetic_evidence", {}).get(
                "baseline_plausibility") == "pass" for x in items),
            "fail": sum(x.get("synthetic_evidence", {}).get(
                "baseline_plausibility") != "pass" for x in items),
        },
        "synthetic_materiality": {
            "pass": sum(x.get("synthetic_evidence", {}).get(
                "material_difference") == "pass" for x in items),
            "fail": sum(x.get("synthetic_evidence", {}).get(
                "material_difference") != "pass" for x in items),
        },
        "synthetic_repair_correctness": {
            "pass": sum(x.get("synthetic_evidence", {}).get(
                "repair_correctness") == "pass" for x in items),
            "fail": sum(x.get("synthetic_evidence", {}).get(
                "repair_correctness") != "pass" for x in items),
        },
        "synthetic_academic_analysis_value": {
            "pass": sum(x.get("synthetic_evidence", {}).get(
                "academic_analysis_value") == "pass" for x in items),
            "fail": sum(x.get("synthetic_evidence", {}).get(
                "academic_analysis_value") != "pass" for x in items),
        },
    })


def case_index(artifact: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x["case_id"]): x for x in artifact.get("items", []) if x.get("case_id")}


def select_diverse_cases(
    artifact: Dict[str, Any], limit: int,
) -> List[Dict[str, Any]]:
    """Prefer high-value, high-confidence cases while preserving category diversity."""
    eligible = [x for x in artifact.get("items", [])
                if x.get("validation", {}).get("academic_case_eligible")]
    eligible.sort(key=lambda x: (
        x.get("baseline_origin") != "legacy_analytical_draft",
        x.get("difficulty", {}).get("academic_value") != "high",
        x.get("difficulty", {}).get("confidence") != "high",
        x.get("case_id")))
    selected, used_categories = [], set()
    for case in eligible:
        category = case.get("error", {}).get("category") or case.get(
            "difficulty", {}).get("category")
        if category in used_categories:
            continue
        selected.append(case)
        used_categories.add(category)
        if len(selected) >= limit:
            return selected
    for case in eligible:
        if case not in selected:
            selected.append(case)
        if len(selected) >= limit:
            break
    return selected
