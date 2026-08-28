"""交付状态机、人工处理记录与定点重译。

交付状态：draft -> review_required -> approved/final
- 翻译完成但有 blocking -> review_required；
- draft 资产可下载，但不得显示为最终交付完成；
- 人工处理记录（finding ID / action / note / timestamp）全部落盘；
- 只有 blocking 被解决或明确接受风险后才能进入 final；
- retranslate_segments 抽取自 scripts/fix_segments.py 的能力（不破坏原脚本）。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import translation_target

DELIVERY_STATUSES = ("draft", "review_required", "approved", "final")
_HUMAN_ACTIONS = ("human_fixed", "accepted_risk", "retranslated",
                  "approve_final", "bypass_freeze", "preserved")
SEVERITY_LABELS = {
    "blocking": "必须处理",
    "actionable": "建议检查",
    "informational": "仅供参考",
}
SEVERITY_ORDER = {"blocking": 0, "actionable": 1, "informational": 2}
_DETECTED_TEXT_RE = re.compile(r"[「『“\"]([^」』”\"]+)[」』”\"]")
_CATEGORY_LABELS = {
    "semantic_accuracy": "语义准确性",
    "terminology_consistency": "术语一致性",
    "completeness": "完整性",
    "translation_completion": "翻译完成度",
    "format_integrity": "格式完整性",
    "source_language_residue": "源语残留",
    "deterministic_qa": "确定性检查",
    "review_finding": "审校发现",
    "fluency": "语言表达",
    "style": "风格一致性",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def finding_fingerprint(f: Dict[str, Any]) -> str:
    """Return semantic identity, independent of evidence or render identity."""
    segment_index = f.get("segment_index")
    if segment_index is None:
        segment_index = f.get("segment_id")
    payload = json.dumps({
        "type": f.get("type"),
        "entry_id": f.get("entry_id"),
        "segment_index": segment_index,
        "reason": f.get("reason"),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def finding_id(f: Dict[str, Any], index: Optional[int] = None) -> str:
    """Stable action/render ID: semantic identity plus event/evidence instance."""
    existing = str(f.get("id") or "")
    event_id = f.get("review_event_id") or f.get("finding_instance_id")
    evidence = sorted(set(_values(f.get("evidence_refs"))
                          + _values(f.get("evidence_ids"))))
    anonymous_instance = {
        "evidence": evidence,
        "detected_text": str(f.get("detected_text") or ""),
        "suggested_target": str(f.get("suggested_target") or ""),
        "review_detail": str(f.get("review_detail") or ""),
    }
    has_anonymous_instance = any(anonymous_instance.values())
    if existing and not event_id and not has_anonymous_instance:
        return existing
    identity = event_id or (json.dumps(anonymous_instance, ensure_ascii=False,
                                       sort_keys=True) if has_anonymous_instance else "")
    payload = json.dumps({
        "fingerprint": finding_fingerprint(f),
        "identity": identity,
        "legacy_id": existing,
    }, ensure_ascii=False, sort_keys=True)
    return "f-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def severity_label(severity: str) -> str:
    return SEVERITY_LABELS.get(str(severity or ""), str(severity or "未知"))


def _segment_index(finding: Dict[str, Any]) -> Optional[int]:
    value = finding.get("segment_index")
    if isinstance(value, bool) or not isinstance(value, int):
        value = finding.get("segment_id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _values(value: Any) -> List[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if value is not None and str(value).strip() else []


def _merge_finding(target: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    """Merge same-instance duplicates without dropping evidence metadata."""
    target["duplicate_count"] = (
        int(target.get("duplicate_count") or 1)
        + int(incoming.get("duplicate_count") or 1))
    for key in ("evidence_refs", "evidence_ids"):
        merged = list(dict.fromkeys(_values(target.get(key)) + _values(incoming.get(key))))
        if merged:
            target[key] = merged
    suggested = _values(incoming.get("suggested_target"))
    if suggested:
        all_targets = list(dict.fromkeys(
            _values(target.get("suggested_target"))
            + _values(target.get("suggested_targets")) + suggested))
        target["suggested_target"] = all_targets[0]
        if len(all_targets) > 1:
            target["suggested_targets"] = all_targets
    for key in ("detected_text", "review_detail"):
        if incoming.get(key) and not target.get(key):
            target[key] = incoming[key]
    for key in ("category", "summary", "source_span", "target_span",
                "explanation", "recommendation", "confidence", "detector",
                "diagnostic_version"):
        if incoming.get(key) is not None and not target.get(key):
            target[key] = incoming[key]


def _merge_unresolved_findings(
    findings: Iterable[Dict[str, Any]],
    severities: Iterable[str],
) -> List[Dict[str, Any]]:
    allowed = set(severities)
    out: List[Dict[str, Any]] = []
    positions: Dict[str, int] = {}
    for source in findings:
        if not isinstance(source, dict):
            continue
        f = dict(source)
        if f.get("resolved"):
            continue
        if f.get("severity") not in allowed:
            continue
        fid = finding_id(f)
        if fid not in positions:
            positions[fid] = len(out)
            f["duplicate_count"] = int(f.get("duplicate_count") or 1)
            out.append(f)
            continue
        existing = out[positions[fid]]
        _merge_finding(existing, f)
        if SEVERITY_ORDER.get(f.get("severity"), 99) < \
                SEVERITY_ORDER.get(existing.get("severity"), 99):
            existing["severity"] = f["severity"]
    return out


def review_queue_findings(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """所有未解决发现的审查视图（含 informational），同实例合并。"""
    return _merge_unresolved_findings(
        state.get("findings") or [], SEVERITY_LABELS.keys())


def unresolved_findings(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """未解决且需要动作的 findings（blocking / actionable）。"""
    return _merge_unresolved_findings(
        state.get("findings") or [], ("blocking", "actionable"))


def normalize_state_findings(state: Dict[str, Any]) -> Dict[str, Any]:
    """归并同一审校实例的重复记录；保留已解决记录和不同事件实例。"""
    raw = state.get("findings") or []
    if not isinstance(raw, list):
        return state
    merged: List[Dict[str, Any]] = []
    positions: Dict[str, int] = {}
    for source in raw:
        if not isinstance(source, dict) or source.get("resolved") \
                or source.get("severity") not in SEVERITY_LABELS:
            merged.append(source)
            continue
        finding = dict(source)
        fid = finding_id(finding)
        if fid not in positions:
            positions[fid] = len(merged)
            finding["duplicate_count"] = int(finding.get("duplicate_count") or 1)
            merged.append(finding)
            continue
        existing = merged[positions[fid]]
        _merge_finding(existing, finding)
        if SEVERITY_ORDER.get(finding.get("severity"), 99) < \
                SEVERITY_ORDER.get(existing.get("severity"), 99):
            existing["severity"] = finding["severity"]
    state["findings"] = merged
    return state


def finding_detected_text(finding: Dict[str, Any]) -> str:
    explicit = str(finding.get("detected_text") or "").strip()
    if explicit:
        return explicit
    match = _DETECTED_TEXT_RE.search(str(finding.get("reason") or ""))
    return match.group(1).strip() if match else ""


def is_source_residue_finding(finding: Dict[str, Any]) -> bool:
    reason = str(finding.get("reason") or "")
    return finding.get("kind") == "source_residue" \
        or "残留源语" in reason or "源语片段" in reason


def likely_proper_noun(text: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", str(text or ""))
    if len(words) < 2:
        return bool(words and words[0][0].isupper() and len(words[0]) >= 3)
    return sum(word[0].isupper() for word in words) >= 2


def finding_context(state: Dict[str, Any], finding: Dict[str, Any]) -> Dict[str, Any]:
    """Build the review card context from persisted translation/evidence state."""
    index = _segment_index(finding)
    event_id = finding.get("review_event_id") or finding.get("finding_instance_id")
    finding_evidence_refs = set(_values(finding.get("evidence_refs")))
    pairs = state.get("pairs") or []
    pair = pairs[index] if index is not None and 0 <= index < len(pairs) else {}
    review_evidence = []
    for entry in state.get("review_evidence") or []:
        segment_ids = entry.get("segment_ids") or []
        if (index in segment_ids or str(index) in {str(x) for x in segment_ids}) \
                and ((event_id and entry.get("review_event_id") == event_id)
                     or (not event_id and finding.get("type") == "review"
                         and not entry.get("review_event_id"))):
            trace_evidence_ids = [str(item) for item in entry.get("evidence_ids") or []
                                  if str(item) in finding_evidence_refs]
            trace_requests = [dict(request) for request in entry.get("requests") or []
                              if str(request.get("evidence_id")) in finding_evidence_refs]
            review_evidence.append({
                "phase": entry.get("phase"),
                "decision": entry.get("decision"),
                "evidence_ids": trace_evidence_ids,
                "requests": trace_requests,
                "completion_receipt": entry.get("completion_receipt") or {},
                "review_event_id": entry.get("review_event_id"),
            })
    detected = finding_detected_text(finding)
    finding_type = str(finding.get("type") or "")
    category = str(finding.get("category") or "").strip()
    if not category:
        if finding_type in {"review", "semantic"}:
            category = "semantic_accuracy"
        elif finding_type in {"glossary", "glossary_stale", "knowledge_conflict"}:
            category = "terminology_consistency"
        elif finding.get("kind") == "source_residue":
            category = "source_language_residue"
        elif finding_type == "check":
            category = "deterministic_qa"
        else:
            category = finding_type or "review_finding"
    detector = str(finding.get("detector") or "").strip()
    if not detector:
        detector = {
            "review": "Semantic QA", "glossary": "Terminology QA",
            "glossary_stale": "Terminology QA", "knowledge_conflict": "Knowledge QA",
            "check": "Deterministic QA",
        }.get(finding_type, "审校记录")
    evidence_ids = list(dict.fromkeys(_values(finding.get("evidence_refs"))))
    for trace in review_evidence:
        evidence_ids.extend(str(item) for item in trace.get("evidence_ids") or [])
    evidence_ids = list(dict.fromkeys(evidence_ids))
    required_diagnostics = ("summary", "explanation", "recommendation")
    diagnostic_complete = all(str(finding.get(field) or "").strip()
                               for field in required_diagnostics)
    return {
        "finding_id": finding_id(finding),
        "segment_index": index,
        "segment_number": index + 1 if index is not None else "?",
        "severity": finding.get("severity"),
        "severity_label": severity_label(finding.get("severity")),
        "reason": str(finding.get("reason") or "审校发现问题"),
        "category": category,
        "category_label": _CATEGORY_LABELS.get(category, category),
        "summary": str(finding.get("summary") or "").strip(),
        "source_span": str(finding.get("source_span") or "").strip(),
        "target_span": str(finding.get("target_span") or "").strip(),
        "explanation": str(finding.get("explanation") or "").strip(),
        "recommendation": str(finding.get("recommendation") or "").strip(),
        "confidence": finding.get("confidence"),
        "detector": detector,
        "diagnostic_version": finding.get("diagnostic_version"),
        "diagnostic_complete": diagnostic_complete,
        "legacy_diagnostic": not diagnostic_complete,
        "detected_text": detected,
        "source": str(pair.get("source") or ""),
        "target": str(pair.get("target") or ""),
        "initial_target": str(pair.get("initial_target") or ""),
        "source_residue": is_source_residue_finding(finding),
        "proper_noun_candidate": is_source_residue_finding(finding)
        and likely_proper_noun(detected),
        "evidence_refs": _values(finding.get("evidence_refs")),
        "evidence_ids": evidence_ids,
        "review_evidence": review_evidence,
        "duplicate_count": int(finding.get("duplicate_count") or 1),
        "review_event_id": event_id,
    }


def unresolved_blocking(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [f for f in unresolved_findings(state) if f.get("severity") == "blocking"]


def add_human_action(state: Dict[str, Any], finding_id_: str, action: str,
                     note: str = "", actor: str = "user") -> Dict[str, Any]:
    state.setdefault("human_actions", []).append({
        "finding_id": finding_id_,
        "action": action,
        "note": note,
        "timestamp": now_iso(),
        "actor": actor,
    })
    return state


def mark_findings(state: Dict[str, Any], finding_ids: List[str], action: str,
                  note: str = "", actor: str = "user") -> Tuple[Dict[str, Any], List[str]]:
    """标记指定 findings 为已处理，并写入人工处理记录。返回 (state, marked_ids)。"""
    ids = set(finding_ids or [])
    marked: List[str] = []
    for f in state.get("findings") or []:
        fid = finding_id(f)
        if fid in ids and not f.get("resolved"):
            f["resolved"] = True
            f["resolution"] = {"action": action, "note": note,
                               "timestamp": now_iso(), "actor": actor}
            add_human_action(state, fid, action, note, actor)
            marked.append(fid)
    return state, marked


def compute_delivery_status(state: Dict[str, Any]) -> str:
    """由当前状态推导交付状态；final/approved 只能由人工确认产生。"""
    if not state.get("p2_done"):
        return "draft"
    if unresolved_blocking(state):
        return "review_required"
    current = state.get("delivery_status")
    if current in ("approved", "final"):
        return current
    return "draft"


def report_ready(state: Dict[str, Any]) -> bool:
    """A requested academic report must pass its final report gate."""
    if not state.get("report_enabled", False):
        return True
    academic = state.get("academic_state") or {}
    return (state.get("report_status") or academic.get("report_status")) == "generated"


def approve_delivery(state: Dict[str, Any], note: str = "", actor: str = "user",
                     accept_blocking: bool = False) -> Tuple[Dict[str, Any], bool, List[str]]:
    """人工交付确认 -> final。

    - 存在未解决 blocking 且未接受风险 -> 拒绝进入 final，返回错误说明；
    - accept_blocking=True：把所有未解决 blocking 记录为 accepted_risk 后进入 final；
    - 全部人工处理记录保存到 state["human_actions"]。
    """
    if not state.get("p2_done"):
        return state, False, ["翻译尚未完成，不能创建最终交付版本"]
    if not report_ready(state):
        return state, False, ["实践报告尚未完成或未通过校验，不能创建最终交付版本"]
    target_report = translation_target.validate_translation_pairs(
        state.get("pairs") or [])
    pair_count_mismatch = bool(
        state.get("paras") and len(state.get("pairs") or []) != len(state.get("paras") or [])
    )
    if target_report["blocking"] or pair_count_mismatch:
        existing = {
            (item.get("type"), item.get("segment_index"), item.get("invariant_code"))
            for item in state.setdefault("findings", [])
        }
        for finding in translation_target.target_invariant_findings(target_report):
            key = (finding.get("type"), finding.get("segment_index"),
                   finding.get("invariant_code"))
            if key not in existing:
                state["findings"].append(finding)
        if pair_count_mismatch and not any(
                item.get("type") == "delivery_invariant"
                and item.get("invariant_code") == "pair_count_mismatch"
                for item in state["findings"] if isinstance(item, dict)):
            state["findings"].append({
                "type": "delivery_invariant", "severity": "blocking",
                "category": "format_integrity", "segment_index": None,
                "segment_id": None, "invariant_code": "pair_count_mismatch",
                "summary": "双语 pairs 数量与源文段落数量不一致",
                "reason": "双语 pairs 数量与源文段落数量不一致，不能进入最终交付",
                "detector": "Translation Target Invariant",
            })
        errors = [
            item.get("message", "译文未通过 Translation Target Invariant")
            for item in target_report.get("issues") or []
        ]
        if pair_count_mismatch:
            errors.append("双语 pairs 数量与源文段落数量不一致，不能进入最终交付")
        return state, False, errors
    blockers = unresolved_blocking(state)
    if blockers:
        if not accept_blocking:
            ids = "、".join(finding_id(f) for f in blockers)
            return state, False, [f"存在未解决的 blocking 问题，不能进入 final：{ids}"]
        for f in blockers:
            state, _ = mark_findings(state, [finding_id(f)], "accepted_risk",
                                     note or "接受风险（人工确认）", actor)
    state["delivery_status"] = "final"
    state["stage"] = "FINAL"
    # Delivery approval is document-scoped authority.  It does not prove that
    # the user inspected and accepted every segment, so segment-level
    # human_accepted fields remain unchanged.
    state["delivery_approved_by_human"] = True
    state["delivery_approval"] = {
        "timestamp": now_iso(), "actor": actor, "note": note,
    }
    add_human_action(state, "*delivery*", "approve_final", note, actor)
    return state, True, []


def retranslate_segments(
    job_id: str,
    indexes: List[int],
    provider: str,
    api_key: str,
    model: str,
    target_lang: str,
    style_rules: str = "",
    glossary: Optional[List[Dict[str, Any]]] = None,
    on_status=None,
    on_caption=None,
    actor: str = "user",
) -> Tuple[Dict[str, Any], List[int]]:
    """重新翻译指定段落（抽取自 scripts/fix_segments.py 的能力）。

    每段：前后文 + 批次翻译 + 完整性把关 + 自动修复一轮；
    保留并关闭该段旧问题，另存最终复验 findings，重算统计与交付状态。
    """
    import core

    state = core.load_job_state(job_id)
    if state is None:
        raise ValueError(f"找不到任务 {job_id}")
    paras, pairs = state["paras"], state["pairs"]
    indexes = sorted({int(i) for i in indexes if 0 <= int(i) < len(pairs)})
    if not indexes:
        return state, []
    was_reviewable_stage = state.get("stage") in ("FINAL", "REVIEW_REQUIRED")
    glossary = core.normalize_glossary(
        glossary if glossary is not None else state.get("glossary") or [])
    glossary_text = core.glossary_block(glossary)

    fixed: List[int] = []
    for idx in indexes:
        src = pairs[idx]["source"]
        ctx_prev = paras[max(0, idx - 2):idx]
        ctx_next = paras[idx + 1:idx + 3]
        try:
            tgt = core.translate_batch([src], ctx_prev, ctx_next, glossary_text,
                                       style_rules, target_lang, provider, api_key,
                                       model)[0]
            tgt = core.clean_xml_chars(tgt).replace("\n", " ")
            section_profile = core._batch_section_profile(
                state.get("document_profile"), idx, 1)
            findings = core.check_translation_batch(
                [src], [tgt], glossary, target_lang,
                section_profile=section_profile)
            fixable = [f for f in findings if f["severity"] in ("blocking", "actionable")]
            if fixable:
                repaired = core.repair_batch([src], [tgt], fixable, glossary_text,
                                             style_rules, target_lang, provider,
                                             api_key, model)
                if repaired and repaired[0].strip() \
                        and not core.is_incomplete_translation(src, repaired[0]):
                    tgt = core.clean_xml_chars(repaired[0]).replace("\n", " ")
            remaining = core.check_translation_batch(
                [src], [tgt], glossary, target_lang,
                section_profile=section_profile)
            pairs[idx]["target"] = tgt
            pairs[idx]["initial_target"] = tgt
            pairs[idx]["from_tm"] = False
            pairs[idx]["reviewed"] = False  # 重译后需重新审校，不进 TMX final memory
            pairs[idx]["review_status"] = "not_reviewed"
            pairs[idx]["target_provenance"] = "generated"
            for key in ("accepted_target", "human_accepted", "accepted_by_human"):
                pairs[idx].pop(key, None)
            for old in state.get("findings", []):
                if old.get("segment_index") != idx or old.get("resolved") \
                        or old.get("severity") not in ("blocking", "actionable"):
                    continue
                old["resolved"] = True
                old["resolution"] = {
                    "action": "retranslated", "note": f"重新翻译段 {idx}",
                    "timestamp": now_iso(), "actor": actor,
                }
                add_human_action(
                    state, finding_id(old), "retranslated", f"重新翻译段 {idx}",
                    actor)
            for finding in remaining:
                state["findings"].append({
                    **finding, "segment_index": idx, "segment_id": idx})
            add_human_action(state, f"segment:{idx}", "retranslated",
                             f"重新翻译段 {idx}", actor)
            fixed.append(idx)
            if on_caption:
                on_caption(f"✅ 段 {idx} 已重译（{len(src)} -> {len(tgt)} 字符）")
        except Exception as e:
            if on_caption:
                on_caption(f"⚠️ 段 {idx} 重译失败：{str(e)[:120]}")

    if fixed:
        from . import knowledge
        state["knowledge_candidates"] = knowledge.discard_candidates_for_segments(
            state.get("knowledge_candidates") or [], fixed)
    stats = state.setdefault("review_stats", {})
    stats["blocking"] = sum(1 for f in state["findings"]
                            if f["severity"] == "blocking" and not f.get("resolved"))
    stats["actionable"] = sum(1 for f in state["findings"]
                              if f["severity"] == "actionable" and not f.get("resolved"))
    stats["informational"] = sum(1 for f in state["findings"]
                                 if f["severity"] == "informational" and not f.get("resolved"))
    state["has_blocking"] = stats["blocking"] > 0
    if fixed:
        # Re-translation changes the canonical working translation.  Let the
        # core mutation entry record the exact dependency slice and revoke
        # approval/final QA while preserving immutable snapshots.
        core._mark_translation_truth_changed(
            job_id, state, fixed,
            "定点重译改变 CURRENT_TRANSLATION；只重建受影响案例与学术下游",
            actor=actor, action="retranslate_segments")
        if was_reviewable_stage:
            state["stage"] = "REVIEW_REQUIRED" if state["has_blocking"] else "TRANSLATED"
    state["delivery_status"] = compute_delivery_status(state)
    core.save_job_state(job_id, state)
    return state, fixed
