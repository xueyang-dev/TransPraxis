"""Adapt internal case analytics to the user-facing MTI example schema."""
from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, Mapping, Optional

from . import case_provenance


VERSION = "case-presentation-v3"
VISIBLE_FIELDS = frozenset({
    "原文", "初译", "模拟初译", "改译", "译文", "注释", "分析",
})
FORBIDDEN_HEADINGS = frozenset({
    "翻译难点", "译法分析", "翻译效果", "有界结论", "证据边界",
    "provenance", "case type",
})

_FIELD_LINE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*{1,2})?([^：:\n*]+?)(?:\*{1,2})?"
    r"(?:（[^）]*）|\([^)]*\))?\s*[：:]\s*(.*?)\s*$",
    re.IGNORECASE,
)
_QUOTE_LINE = re.compile(
    r"^\s*>\s*\[(?:SOURCE|INITIAL|TARGET|SYNTHETIC_SOURCE|SIMULATED|OPTIMIZED)\s+",
    re.IGNORECASE,
)
_VISIBLE_EVIDENCE_LABELS = {
    "source", "initial", "target", "原文", "初译", "改译", "译文",
    "模拟初译", "模拟译法", "优化译文", "对比译法（模拟）", "最终译文",
}
_ANALYSIS_LABELS = {
    "分析", "译法分析", "对比分析", "决策理由", "翻译效果", "备选方案",
    "备选译法", "策略分析", "理论解释",
}
_LIMIT_LABELS = {"有界结论", "证据边界", "证据限制"}
_NOTE_LABELS = {"注释", "备注"}
_LIMIT_NEEDED = re.compile(
    r"证据不足|无法(?:确定|证明|支持)|未(?:提供|记录)|不能(?:确定|证明|支持)|"
    r"尚无|仅(?:能|限于|支持)|需要(?:人工|进一步)|不代表|不得外推"
)


def _clean(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    # A legacy writer label occasionally leaked a literal ``>。`` before the
    # analysis paragraph.  It is not a user-authored blockquote and must not
    # survive into the canonical case presentation.
    text = re.sub(r"^>\s*[。．]\s*", "", text)
    return re.sub(r"^(?:[-*]\s*)+", "", text)


def _sentences(values: Iterable[Any]) -> str:
    parts = []
    seen = set()
    for value in values:
        text = _clean(value)
        key = re.sub(r"[\s。.!！？，,；;：:]", "", text).casefold()
        if not text or not key or key in seen:
            continue
        seen.add(key)
        if text[-1:] not in "。.!！？？；;":
            text += "。"
        parts.append(text)
    return "".join(parts)


def analysis_fragments_from_markdown(block: str) -> Dict[str, Any]:
    """Read writer prose, discarding its presentation labels by construction."""
    entries = []
    current: Optional[Dict[str, str]] = None
    for raw_line in str(block or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("<!--") or _QUOTE_LINE.match(line) \
                or re.match(r"^(?:[-*]\s*)?\*{1,2}例\[\d+\]", line):
            current = None
            continue
        match = _FIELD_LINE.match(line)
        if match:
            label = _clean(match.group(1)).casefold()
            current = {"label": label, "value": _clean(match.group(2))}
            entries.append(current)
            continue
        if current is not None and not line.startswith("#"):
            current["value"] = _clean(f"{current['value']} {line}")
        elif not line.startswith("#") and "本组小结" not in line:
            entries.append({"label": "分析", "value": _clean(line)})

    analysis = []
    limits = []
    notes = []
    for entry in entries:
        label = entry["label"]
        value = entry["value"]
        if label in _VISIBLE_EVIDENCE_LABELS or label == "翻译难点":
            continue
        if label in _NOTE_LABELS:
            notes.append(value)
        elif label in _LIMIT_LABELS:
            limits.append(value)
        elif label in _ANALYSIS_LABELS or label == "分析":
            analysis.append(value)
    return {"analysis": analysis, "limits": limits, "note": _sentences(notes) or None}


def _span_text(focus: Mapping[str, Any], name: str) -> str:
    span = focus.get(name) or focus.get(f"{name}_span") or {}
    return str(span.get("text") or "") if isinstance(span, Mapping) else str(span or "")


def _emphasize(text: str, candidates: Iterable[Any]) -> str:
    for candidate in candidates:
        value = _clean(candidate).strip('“”"\'')
        if not 2 <= len(value) <= 64 or len(value) >= max(2, int(len(text) * 0.8)):
            continue
        match = re.search(re.escape(value), text, re.IGNORECASE)
        if match:
            return text[:match.start()] + "**" + match.group(0) + "**" + text[match.end():]
    return text


def _focus_terms(case_node: Mapping[str, Any]) -> Dict[str, list[str]]:
    focus = case_node.get("focus") or {}
    issue = str(focus.get("issue") or "")
    source_terms: list[str] = []
    target_terms: list[str] = []
    if "→" in issue:
        source, target = issue.split("→", 1)
        source_terms.append(source)
        target_terms.append(target)
    elif "->" in issue:
        source, target = issue.split("->", 1)
        source_terms.append(source)
        target_terms.append(target)
    delta = case_node.get("translation_delta") or {}
    old_terms = [str(item.get("old") or "") for item in delta.get("lexical_changes") or []]
    new_terms = [str(item.get("new") or "") for item in delta.get("lexical_changes") or []]
    return {"source": source_terms, "initial": old_terms, "target": [*target_terms, *new_terms]}


def build_case_presentation(case_node: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the sole user-facing representation of one structured case node."""
    case_type = case_provenance.case_type(case_node)
    focus = case_node.get("focus") or {}
    source = _span_text(focus, "source")
    if case_type == "authentic_revision":
        initial = _span_text(focus, "initial")
    elif case_type == "synthetic_contrast":
        baseline = case_node.get("synthetic_baseline") or {}
        initial = str(baseline.get("text") or "") if isinstance(baseline, Mapping) else str(baseline or "")
        initial = initial or _span_text(focus, "initial")
    else:
        initial = ""
    target = _span_text(focus, "target")
    fields = case_node.get("analysis_fields") or {}
    existing = list(fields.get("visible_analysis") or [])
    analysis_parts = existing or [
        (fields.get("difficulty") or {}).get("statement")
        if isinstance(fields.get("difficulty"), Mapping) else fields.get("difficulty"),
        fields.get("rationale"),
        (fields.get("effect") or {}).get("demonstrated_by")
        if isinstance(fields.get("effect"), Mapping) else fields.get("effect"),
    ]
    analysis = _sentences(analysis_parts)
    limits = list(fields.get("limits") or [])
    bounded = str(fields.get("bounded_claim") or "")
    if bounded and _LIMIT_NEEDED.search(bounded):
        limits.append(bounded)
    necessary_limits = [value for value in limits if _LIMIT_NEEDED.search(str(value or ""))]
    analysis = _sentences([analysis, *necessary_limits]) or "本例分析限于上述可观察文本。"
    terms = _focus_terms(case_node)
    return {
        "schema_version": VERSION,
        "case_id": case_node.get("case_id"),
        "case_type": case_type,
        "example_number": int(case_node.get("example_number") or 0),
        "source": _emphasize(source, terms["source"]),
        "initial": _emphasize(initial, terms["initial"]) if initial else None,
        "target": _emphasize(target, terms["target"]),
        "note": fields.get("note") or None,
        "analysis": analysis,
    }


def render_case_presentation_markdown(presentation: Mapping[str, Any]) -> str:
    """Render only the fields permitted by the MTI report presentation contract."""
    number = int(presentation.get("example_number") or 0)
    case_id = str(presentation.get("case_id") or "")
    case_type = case_provenance.case_type(presentation)
    labels = case_provenance.display_contract(presentation)
    lines = [f"**例[{number}]**", f"<!--case:{case_id}-->", "",
             f"**原文**：{presentation.get('source') or ''}", ""]
    if labels["initial_label"]:
        lines.extend([f"**{labels['initial_label']}**：{presentation.get('initial') or ''}", "",
                      f"**{labels['target_label']}**：{presentation.get('target') or ''}", ""])
    else:
        lines.extend([f"**{labels['target_label']}**：{presentation.get('target') or ''}", ""])
    if presentation.get("note"):
        lines.extend([f"**注释**：{presentation['note']}", ""])
    lines.append(f"**分析**：{presentation.get('analysis') or ''}")
    return "\n".join(lines).strip()


def plain_text(value: Any) -> str:
    """Remove presentation-only emphasis before provenance comparison."""
    return re.sub(r"(?<!\\)(?:\*\*|__)(.+?)(?:\*\*|__)", r"\1", str(value or ""))


def analysis_repetition_audit(
    presentations: Iterable[Mapping[str, Any]],
    core_case_ids: Iterable[str] = (),
) -> Dict[str, Any]:
    """Detect repeated case-analysis prose without banning normal terminology."""
    rows = [dict(item) for item in presentations]
    core_ids = {str(value) for value in core_case_ids}
    analyses = [_clean(item.get("analysis")) for item in rows]
    matrix: list[list[float]] = []
    high_pairs = []
    fail_pairs = []
    for left, left_text in enumerate(analyses):
        matrix_row = []
        for right, right_text in enumerate(analyses):
            ratio = 1.0 if left == right else SequenceMatcher(
                None, left_text, right_text).ratio()
            matrix_row.append(round(ratio, 4))
            if right <= left or not left_text or not right_text:
                continue
            left_id = str(rows[left].get("case_id") or "")
            right_id = str(rows[right].get("case_id") or "")
            threshold = 0.82 if left_id in core_ids or right_id in core_ids else 0.86
            if ratio >= threshold:
                record = {
                    "left_case_id": left_id,
                    "right_case_id": right_id,
                    "left_example_number": rows[left].get("example_number"),
                    "right_example_number": rows[right].get("example_number"),
                    "similarity": round(ratio, 4),
                    "involves_core_case": left_id in core_ids or right_id in core_ids,
                }
                high_pairs.append(record)
                if ratio >= 0.92 or (record["involves_core_case"] and ratio >= 0.88):
                    fail_pairs.append(record)
        matrix.append(matrix_row)

    sentence_rows = []
    for item, analysis in zip(rows, analyses):
        for sentence in re.split(r"(?<=[。！？!?])", analysis):
            sentence = sentence.strip()
            if len(sentence) >= 16:
                sentence_rows.append((sentence, str(item.get("case_id") or "")))
    sentence_counts = Counter(sentence for sentence, _case_id in sentence_rows)
    repeated_sentences = [
        {
            "sentence": sentence,
            "count": count,
            "case_ids": sorted({case_id for current, case_id in sentence_rows
                                if current == sentence}),
        }
        for sentence, count in sentence_counts.most_common() if count > 1
    ]
    repeated_sentence_count = sum(item["count"] - 1 for item in repeated_sentences)
    exact_blocks = Counter(analysis for analysis in analyses if analysis)
    repeated_analysis_blocks = [
        {"analysis": analysis, "count": count}
        for analysis, count in exact_blocks.most_common() if count > 1
    ]
    status = "fail" if fail_pairs or repeated_analysis_blocks or any(
        item["count"] >= 4 for item in repeated_sentences) else (
        "pass_with_warnings" if high_pairs or repeated_sentences else "pass")
    return {
        "schema_version": "case-analysis-repetition-v1",
        "status": status,
        "analysis_count": len(analyses),
        "analysis_similarity_matrix": matrix,
        "high_similarity_pairs": high_pairs,
        "fail_similarity_pairs": fail_pairs,
        "repeated_sentences": repeated_sentences,
        "repeated_sentence_count": repeated_sentence_count,
        "repeated_analysis_blocks": repeated_analysis_blocks,
    }
