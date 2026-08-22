"""实践报告证据化：为每个可用段落提供真实证据包。

证据包字段：
- segment_id / source / initial_target（若可用）/ final_target
- glossary decisions（注入的术语条目）
- deterministic findings / review findings / repair history / human actions

兼容导出规约（新学术流水线使用 academic_evidence.py 的全语料 artifact）：
1. 案例必须引用真实 segment_id；
2. 原文/译文必须逐字来自任务状态，不允许模型改写后冒充；
3. 不得宣称翻译技巧是译者真实意图，只能表述为“从结果看可解释为”；
4. 证据不足时明确说明；
5. 报告是初稿，需要人工核查。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from . import assets as _assets
from . import delivery as _delivery


def build_segment_evidence(state: Dict[str, Any], job_id: str,
                           index: int) -> Dict[str, Any]:
    """单个段落的证据包（全部来自任务状态，不包含模型改写内容）。"""
    pairs = state.get("pairs") or []
    if not (0 <= index < len(pairs)):
        return {"segment_id": _assets.segment_id(job_id, index),
                "available": False}
    pair = pairs[index]
    seg_findings = [f for f in state.get("findings") or []
                    if f.get("segment_index") == index]
    human_actions = [
        ha for ha in state.get("human_actions") or []
        if ha.get("finding_id") in ("*delivery*",) or
        ha.get("finding_id") == f"segment:{index}" or
        any(ha.get("finding_id") == _delivery.finding_id(f) for f in seg_findings)
    ]
    system_actions = [
        action for action in state.get("system_actions") or []
        if action.get("finding_id") == f"segment:{index}" or
        any(action.get("finding_id") == _delivery.finding_id(f)
            for f in seg_findings)
    ]
    fg = state.get("glossary_frozen") or {}
    return {
        "segment_id": _assets.segment_id(job_id, index),
        "available": True,
        "source": pair.get("source", ""),
        "initial_target": pair.get("initial_target"),
        "final_target": pair.get("target", ""),
        "integrity_flags": list(pair.get("integrity_flags") or []),
        "reviewed": bool(pair.get("reviewed")),
        "from_tm": bool(pair.get("from_tm")),
        "glossary_decisions": {
            "injected_entry_ids": list(pair.get("glossary_entry_ids") or []),
            "frozen_glossary_version": fg.get("version"),
            "frozen_glossary_hash": fg.get("glossary_hash"),
        },
        "deterministic_findings": [
            {k: f.get(k) for k in ("severity", "reason", "type", "entry_id",
                                   "kind", "detected_text", "resolved")}
            for f in seg_findings if f.get("type") == "check"
        ],
        "review_findings": [
            {k: f.get(k) for k in ("severity", "reason", "type",
                                   "suggested_target", "evidence_refs",
                                   "review_event_id", "resolved")}
            for f in seg_findings if f.get("type") == "review"
        ],
        "repair_history": [
            {k: f.get(k) for k in (
                "severity", "reason", "suggested_target", "resolved", "resolution")}
            for f in seg_findings
            if f.get("suggested_target") or (
                f.get("resolved") and f.get("resolution", {}).get("action")
                in {"human_fixed", "preserved", "retranslated", "system_fixed",
                    "system_alignment_fixed"})
        ],
        "human_actions": human_actions,
        "system_actions": system_actions,
    }


def export_segment_evidence_jsonl(state: Dict[str, Any],
                                  job_id: str) -> str:
    """导出全部段落的证据包（每行一个 JSON）。"""
    lines = []
    for i in range(len(state.get("pairs") or [])):
        lines.append(json.dumps(
            build_segment_evidence(state, job_id, i), ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


def evidence_text_block(state: Dict[str, Any], job_id: str,
                        max_chars: int = 9000) -> str:
    """Legacy bounded text export; not used by the academic writer pipeline."""
    parts, total = [], 0
    for i in range(len(state.get("pairs") or [])):
        ev = build_segment_evidence(state, job_id, i)
        chunk = (f"[{ev['segment_id']}] 原文：{ev['source']}\n"
                 f"   译文：{ev['final_target']}\n")
        if ev.get("initial_target") and ev["initial_target"] != ev["final_target"]:
            chunk += f"   初译：{ev['initial_target']}（后经修复/审校调整）\n"
        total += len(chunk)
        if total > max_chars:
            break
        parts.append(chunk)
    return "\n".join(parts)
