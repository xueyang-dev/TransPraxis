"""Evidence-aware claim-strength checks for academic report prose.

The checker is intentionally conservative.  It does not rewrite a sentence
without knowing the intended proposition; it reports when the wording asks
for stronger evidence than the packet contains and supplies a bounded wording
direction for the writer/repair layer.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional


SCHEMA_VERSION = "claim-strength-v1"

EVIDENCE_LEVELS = ("A", "B", "C", "D", "E")

_PATTERNS = (
    ("proof_or_certainty", re.compile(
        r"证明|由此证明|确保|完全|显著(?:提升|降低|改善)?|"
        r"proves?|ensures?|guarantees?|significantly", re.I), "D"),
    ("general_rule", re.compile(
        r"常用(?:手段|策略)?|通行译法|常见译法|普遍(?:适用|有效)?|"
        r"适用于所有|具有普适性|普遍规律|common(?:ly)? used|conventional", re.I), "D"),
    ("reader_effect", re.compile(
        r"不会造成理解障碍|确保读者|使(?:中文)?读者(?:能够|可以)?理解|"
        r"提升(?:了)?读者理解|降低(?:了)?认知负荷|促进读者接受|"
        r"reader(?:s)? (?:can|will) understand|improves? comprehension", re.I), "E"),
    ("quality_effect", re.compile(
        r"有效(?:提升|改善|传达|保留)|提高(?:了)?(?:译文|翻译)?(?:质量|效率|一致性)|"
        r"确保(?:译文|术语|质量)|有效(?:维护|保证)|effectively (?:preserves?|improves?)", re.I), "C"),
    ("historical_intent", re.compile(
        r"最终审校认为|译者(?:经过|通过)权衡|审校阶段(?:决定|删除)|"
        r"经审校后(?:得到|获得)|because the translator|the reviewer decided", re.I), "A"),
    ("unsupported_external_norm", re.compile(
        r"学界(?:常见|通行)|相关研究(?:中)?(?:常见|通行)|作者自创|作者创造|"
        r"widely accepted|field[- ]?standard|author[- ]created", re.I), "D"),
)
_NEGATION_PREFIX = re.compile(
    r"(?:不必|不应|不再|未|无|没有|不能|不得|并非|不是|不等于|"
    r"不把|不作|不概括|不将|避免|而非|而不是|仅限|cannot|without|not)",
    re.IGNORECASE,
)


def _visible_lines(text: Any) -> Iterable[str]:
    for raw in str(text or "").splitlines():
        line = re.sub(r"<!--.*?-->", "", raw).strip()
        if not line or line.startswith(">"):
            continue
        if re.match(r"^\*{0,2}(?:原文|初译|改译|译文|注释)\*{0,2}\s*[：:]", line):
            continue
        yield line


def claim_strength_violations(
    text: Any,
    *,
    evidence_level: str = "B",
    has_literature: bool = False,
    has_reader_evidence: bool = False,
    section_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return claims whose wording exceeds the supplied evidence level.

    Level A is direct project/revision evidence, B is source-target textual
    evidence, C is bounded analyst interpretation, D is literature-grounded
    generalization, and E is reader/effect evidence.  A stronger evidence
    level is required for a pattern than the letter shown in ``required``.
    """
    level = str(evidence_level or "B").upper()
    if level not in EVIDENCE_LEVELS:
        level = "B"
    rank = {value: index for index, value in enumerate(EVIDENCE_LEVELS)}
    available = "E" if has_reader_evidence else ("D" if has_literature else level)
    rows: List[Dict[str, Any]] = []
    for line in _visible_lines(text):
        for kind, pattern, required in _PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            # A bounded academic claim often mentions the prohibited stronger
            # wording in a negated disclaimer (e.g. “不能证明……普遍规律”).
            # Such a disclaimer is evidence discipline, not an overclaim.
            prefix = line[max(0, match.start() - 80):match.start()]
            if _NEGATION_PREFIX.search(prefix):
                continue
            if kind in {"reader_effect"} and has_reader_evidence:
                continue
            if kind == "unsupported_external_norm" and has_literature:
                continue
            if rank.get(available, 1) >= rank[required]:
                continue
            rows.append({
                "type": "claim_strength_overreach",
                "claim_kind": kind,
                "required_evidence_level": required,
                "available_evidence_level": available,
                "text": line[:300],
                "match": match.group(0),
                "section_id": section_id,
                "suggested_action": (
                    "改为‘在本案例/本文语境中显示、呈现或保持’，并删除未记录的因果、"
                    "读者效果、普遍性或译者动机判断。"
                ),
            })
            break
    return rows


def normalize_claim_strength(
    text: Any,
    *,
    evidence_level: str = "B",
    has_literature: bool = False,
    has_reader_evidence: bool = False,
    section_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Reusable, non-destructive normalizer result used by writer/validator."""
    violations = claim_strength_violations(
        text,
        evidence_level=evidence_level,
        has_literature=has_literature,
        has_reader_evidence=has_reader_evidence,
        section_id=section_id,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "review_required" if violations else "pass",
        "evidence_level": str(evidence_level or "B").upper(),
        "violations": violations,
        "normalization_policy": "diagnose_then_bound; no blind string replacement",
    }
