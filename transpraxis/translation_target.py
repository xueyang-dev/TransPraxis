"""Deterministic acceptance checks for translation targets and deliveries."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Sequence


_MODEL_PREFIX = re.compile(
    r"^(?:以下是(?:译文|翻译)|下面是(?:译文|翻译)|译文如下|"
    r"here(?:'s| is) the translation|translation)\s*[:：]",
    re.IGNORECASE,
)
_FENCE = re.compile(r"^\s*```[^\n]*(?:\n|$)", re.IGNORECASE)


def _issue(code: str, message: str, *, segment_index: Any = None) -> Dict[str, Any]:
    result = {"code": code, "message": message, "severity": "blocking"}
    if isinstance(segment_index, int) and not isinstance(segment_index, bool):
        result["segment_index"] = segment_index
    return result


def _json_transport(value: str) -> bool:
    candidate = value.strip()
    if not candidate or candidate[0] not in "[{":
        return False
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, (list, dict))


def is_translation_transport_wrapper(value: Any) -> bool:
    """Return whether a value is an unprocessed JSON/Markdown transport form."""
    if not isinstance(value, str):
        return True
    candidate = value.strip()
    if _FENCE.match(candidate):
        return True
    return _json_transport(candidate)


def validate_translation_target(
    source: Any,
    target: Any,
    *,
    segment_index: Any = None,
    allow_json: bool = False,
) -> Dict[str, Any]:
    """Validate one ordinary prose target without invoking a model."""
    source_text = "" if source is None else str(source)
    target_text = "" if target is None else str(target)
    issues: List[Dict[str, Any]] = []
    if source_text.strip() and target is not None and not isinstance(target, str):
        issues.append(_issue("invalid_target_type", "正文段落译文必须是字符串",
                             segment_index=segment_index))
    elif not target_text.strip() and source_text.strip():
        issues.append(_issue("empty_target", "正文段落译文不能为空",
                             segment_index=segment_index))
    elif not allow_json and is_translation_transport_wrapper(target_text):
        issues.append(_issue(
            "transport_wrapper",
            "译文仍是 JSON/Markdown transport wrapper，不能作为普通正文交付",
            segment_index=segment_index))
    elif not allow_json and _MODEL_PREFIX.match(target_text.strip()):
        issues.append(_issue(
            "model_explanation_prefix",
            "译文包含模型解释前缀，可能不是纯目标文本",
            segment_index=segment_index))
    return {"ok": not issues, "blocking": bool(issues), "issues": issues}


def validate_translation_pairs(
    pairs: Sequence[Dict[str, Any]], *, allow_json: bool = False
) -> Dict[str, Any]:
    """Validate all pairs and return a serializable report with segment reasons."""
    issues: List[Dict[str, Any]] = []
    for index, pair in enumerate(pairs or []):
        if not isinstance(pair, dict):
            issues.append(_issue("invalid_pair", "双语段落记录不是对象",
                                 segment_index=index))
            continue
        report = validate_translation_target(
            pair.get("source"), pair.get("target"), segment_index=index,
            allow_json=allow_json or bool(pair.get("target_is_json")))
        issues.extend(report["issues"])
    return {
        "ok": not issues,
        "blocking": bool(issues),
        "issues": issues,
        "checked_pairs": len(pairs or []),
    }


def target_invariant_findings(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert a validation report into the project's review-queue shape."""
    findings = []
    for issue in report.get("issues") or []:
        index = issue.get("segment_index")
        findings.append({
            "segment_id": index,
            "segment_index": index,
            "type": "delivery_invariant",
            "severity": "blocking",
            "category": "format_integrity",
            "summary": issue.get("message") or "译文未通过交付 invariant",
            "source_span": None,
            "target_span": None,
            "explanation": issue.get("message") or "目标文本不符合普通 prose 交付协议。",
            "recommendation": "重新解析或重新翻译该段；不要把模型原始 transport 响应写入交付产物。",
            "confidence": None,
            "detector": "Translation Target Invariant",
            "diagnostic_version": 1,
            "reason": issue.get("message") or issue.get("code"),
            "invariant_code": issue.get("code"),
        })
    return findings
