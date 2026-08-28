"""Canonical case origin, text roles and human-review semantics."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, List


VERSION = "case-provenance-v1"
REAL_REVISION = "REAL_REVISION"
SYNTHETIC_BASELINE = "SYNTHETIC_BASELINE"
SOURCE = "SOURCE"
HISTORICAL_INITIAL = "HISTORICAL_INITIAL"
CURRENT_TRANSLATION = "CURRENT_TRANSLATION"
REVIEW_STATUSES = frozenset({"unreviewed", "approved", "rejected"})

_CASE_TYPES = frozenset({
    "authentic_revision", "synthetic_contrast", "translation_decision",
})
_ORIGIN_ALIASES = {
    REAL_REVISION: REAL_REVISION,
    SYNTHETIC_BASELINE: SYNTHETIC_BASELINE,
    "authentic_revision": REAL_REVISION,
    "synthetic_contrast": SYNTHETIC_BASELINE,
}
_REVIEW_ALIASES = {
    "reviewed": "approved",
    "reviewed_clean": "approved",
    "review_failed": "rejected",
}


def case_type(case: Mapping[str, Any]) -> str:
    """Resolve the current internal case type, including old records."""
    value = str(case.get("case_type") or "").strip()
    if value in _CASE_TYPES:
        return value
    origin = _ORIGIN_ALIASES.get(str(case.get("case_origin") or "").strip())
    if origin == REAL_REVISION:
        return "authentic_revision"
    if origin == SYNTHETIC_BASELINE:
        return "synthetic_contrast"
    # Existing presentation code treated an absent type as an authentic case.
    return "authentic_revision"


def _metadata(case: Mapping[str, Any]) -> Dict[str, Any]:
    kind = case_type(case)
    if kind == "authentic_revision":
        return {
            "case_type": kind,
            "case_origin": REAL_REVISION,
            "text_role": {
                "source": SOURCE,
                "initial": HISTORICAL_INITIAL,
                "target": CURRENT_TRANSLATION,
            },
        }
    if kind == "synthetic_contrast":
        return {
            "case_type": kind,
            "case_origin": SYNTHETIC_BASELINE,
            "text_role": {
                "source": SOURCE,
                "initial": SYNTHETIC_BASELINE,
                "target": CURRENT_TRANSLATION,
            },
        }
    return {
        "case_type": kind,
        "case_origin": None,
        "text_role": {"source": SOURCE, "target": CURRENT_TRANSLATION},
    }


def _review_status(value: Any) -> str:
    value = str(value or "").strip().lower()
    return _REVIEW_ALIASES.get(
        value, value if value in REVIEW_STATUSES else "unreviewed")


def with_provenance(case: Mapping[str, Any]) -> Dict[str, Any]:
    """Fill canonical fields while retaining legacy fields and extra evidence."""
    out = dict(case)
    metadata = _metadata(out)
    out["case_type"] = metadata["case_type"]
    if metadata["case_origin"]:
        out["case_origin"] = metadata["case_origin"]
    else:
        out.pop("case_origin", None)
    out["text_role"] = dict(metadata["text_role"])
    status = _review_status(out.get("review_status"))
    out["review_status"] = status

    provenance = dict(out.get("provenance") or {})
    provenance.update({
        "case_origin": metadata["case_origin"],
        "text_role": dict(metadata["text_role"]),
        "review_status": status,
    })
    if metadata["case_origin"] == REAL_REVISION:
        provenance.update({"historical": True, "generated_for_analysis": False})
    elif metadata["case_origin"] == SYNTHETIC_BASELINE:
        provenance.update({"historical": False, "generated_for_analysis": True})
    out["provenance"] = provenance
    if metadata["case_origin"] == REAL_REVISION:
        out.update(historical=True, generated_for_analysis=False)
    elif metadata["case_origin"] == SYNTHETIC_BASELINE:
        out.update(historical=False, generated_for_analysis=True)
    return out


def provenance_issues(case: Mapping[str, Any]) -> List[str]:
    """Report contradictory explicit metadata without mutating the record."""
    expected = _metadata(case)
    issues: List[str] = []
    if case.get("case_origin") is not None and _ORIGIN_ALIASES.get(
            str(case.get("case_origin"))) != expected["case_origin"]:
        issues.append("case_origin_mismatch")
    supplied_roles = case.get("text_role")
    if supplied_roles is not None and (
            not isinstance(supplied_roles, Mapping)
            or dict(supplied_roles) != expected["text_role"]):
        issues.append("text_role_mismatch")
    status = case.get("review_status")
    if status is not None and str(status).strip().casefold() not in (
            REVIEW_STATUSES | frozenset(_REVIEW_ALIASES)):
        issues.append("review_status_invalid")
    provenance = case.get("provenance")
    if isinstance(provenance, Mapping):
        if provenance.get("case_origin") is not None and _ORIGIN_ALIASES.get(
                str(provenance.get("case_origin"))) != expected["case_origin"]:
            issues.append("provenance_case_origin_mismatch")
        supplied_provenance_roles = provenance.get("text_role")
        if supplied_provenance_roles is not None and (
                not isinstance(supplied_provenance_roles, Mapping)
                or dict(supplied_provenance_roles) != expected["text_role"]):
            issues.append("provenance_text_role_mismatch")
        if expected["case_origin"] in {REAL_REVISION, SYNTHETIC_BASELINE}:
            for key, expected_value in (
                    ("historical", expected["case_origin"] == REAL_REVISION),
                    ("generated_for_analysis",
                     expected["case_origin"] == SYNTHETIC_BASELINE)):
                if key in provenance and provenance.get(key) is not expected_value:
                    issues.append(f"provenance_{key}_mismatch")
    if expected["case_origin"] in {REAL_REVISION, SYNTHETIC_BASELINE}:
        for key, expected_value in (
                ("historical", expected["case_origin"] == REAL_REVISION),
                ("generated_for_analysis",
                 expected["case_origin"] == SYNTHETIC_BASELINE)):
            if key in case and case.get(key) is not expected_value:
                issues.append(f"{key}_mismatch")
    return sorted(set(issues))


def review_case(case: Mapping[str, Any], status: str, note: str = "") -> Dict[str, Any]:
    """Change review state only; approval can never promote case provenance."""
    status = str(status or "").strip().lower()
    if status not in REVIEW_STATUSES:
        raise ValueError(f"unsupported case review status: {status}")
    out = with_provenance(case)
    out["review_status"] = status
    if note:
        out["review_note"] = str(note)[:700]
    return with_provenance(out)


def display_contract(case: Mapping[str, Any]) -> Dict[str, Any]:
    """Return deterministic public labels and the provenance disclosure text."""
    origin = _metadata(case)["case_origin"]
    if origin == REAL_REVISION:
        return {
            "origin_label": "真实修订",
            "origin_description": "项目保存了真实初译与当前译文的修订记录。",
            "initial_label": "初译",
            "target_label": "改译",
        }
    if origin == SYNTHETIC_BASELINE:
        return {
            "origin_label": "合成对照",
            "origin_description": "模拟初译仅用于分析对照，不是项目历史初译。",
            "initial_label": "模拟初译",
            "target_label": "改译",
        }
    return {
        "origin_label": "翻译决策",
        "origin_description": "只展示当前译文及其分析证据，不构成初译—改译历史。",
        "initial_label": None,
        "target_label": "译文",
    }


def is_synthetic(case: Mapping[str, Any]) -> bool:
    return _metadata(case)["case_origin"] == SYNTHETIC_BASELINE


def is_authentic(case: Mapping[str, Any]) -> bool:
    return _metadata(case)["case_origin"] == REAL_REVISION


def counts_toward_minimum(case: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    """Apply the report profile's explicit synthetic-case counting decision."""
    return not is_synthetic(case) or bool(
        policy.get("synthetic_counts_toward_minimum", True))
