"""Evidence-grounded academic writing orchestration.

The LLM performs semantic planning, prose writing and critique.  This module
owns durable artifacts, dependency hashes, scoped packets, resume behavior and
targeted section repair.  Translation state remains untouched.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import academic_evidence
from . import claim_strength
from . import academic_quality
from . import academic_validator
from . import case_analysis
from . import case_presentation
from . import case_provenance
from . import human_evidence
from . import literature_evidence
from . import legacy_cases
from . import report_template
from . import synthetic_cases
from . import thesis_constraints

PIPELINE_VERSION = "academic-pipeline-v13"
VERSIONS = {
    "evidence_version": academic_evidence.SCHEMA_VERSION,
    "case_provenance_version": case_provenance.VERSION,
    "report_constraints_version": thesis_constraints.SCHEMA_VERSION,
    "template_contract_version": report_template.SCHEMA_VERSION,
    "research_model_version": "research-model-v3",
    "literature_sources_version": literature_evidence.SOURCES_VERSION,
    "literature_evidence_version": literature_evidence.EVIDENCE_VERSION,
    "literature_claims_version": literature_evidence.CLAIMS_VERSION,
    "argument_plan_version": "argument-planner-v5",
    "synthetic_opportunity_version": synthetic_cases.OPPORTUNITY_VERSION,
    "synthetic_baseline_version": synthetic_cases.BASELINE_VERSION,
    "synthetic_error_manifest_version": synthetic_cases.ERROR_MANIFEST_VERSION,
    "synthetic_optimizer_version": synthetic_cases.OPTIMIZER_VERSION,
    "synthetic_validation_version": synthetic_cases.VALIDATION_VERSION,
    "legacy_inventory_version": legacy_cases.INVENTORY_VERSION,
    "legacy_recovery_version": legacy_cases.RECOVERY_VERSION,
    "case_selection_version": "case-selector-v10",
    "outline_version": "academic-outline-v9",
    "writer_version": "academic-writer-v18",
    "validator_version": academic_validator.VALIDATOR_VERSION,
    "report_artifact_version": "academic-report-artifact-v6",
    "reviewer_version": "academic-reviewer-v1",
    "literature_reviewer_version": "literature-support-reviewer-v1",
    "academic_quality_version": academic_quality.QUALITY_VERSION,
    "case_analysis_version": case_analysis.ANALYSIS_VERSION,
    "claim_strength_version": claim_strength.SCHEMA_VERSION,
    "human_evidence_version": human_evidence.HUMAN_EVIDENCE_VERSION,
}

ARTIFACT_FILES = {
    "evidence": "academic-evidence.json",
    "research_model": "research-model.json",
    "literature_sources": "literature-sources.json",
    "literature_evidence": "literature-evidence.jsonl",
    "literature_claims": "literature-claims.jsonl",
    "argument_plan": "argument-plan.json",
    "synthetic_opportunities": "synthetic-error-opportunities.jsonl",
    "synthetic_baselines": "synthetic-baselines.jsonl",
    "synthetic_error_manifest": "synthetic-error-manifest.jsonl",
    "synthetic_optimized": "synthetic-optimized-translations.jsonl",
    "synthetic_validation": "synthetic-case-validation.jsonl",
    "legacy_inventory": "legacy-case-inventory.json",
    "legacy_recovery": "legacy-case-recovery.json",
    "selected_cases": "selected-cases.json",
    "outline": "academic-outline.json",
    "sections": "academic-sections.json",
    "report": "academic-report.json",
    "compliance": "academic-compliance.json",
    "language_constraints": "language-constraints.json",
    "validation": "academic-validation.json",
    "review": "academic-review.json",
    "literature_support_review": "literature-support-review.json",
    "academic_quality": "academic-quality-evaluation.json",
    "case_analysis_plans": "case-analysis-plans.json",
    "human_evidence": "human-academic-evidence.jsonl",
    "human_evidence_needs": "human-evidence-needs.json",
    "human_evidence_questions": "human-evidence-questions.json",
    "quality_repair_history": "academic-quality-repair-history.json",
    "repair_history": "academic-repair-history.json",
    "final_docx_validation": "final-docx-validation.json",
    "report_qa": "report-qa.json",
    "libreoffice_render": "libreoffice-render-status.json",
}

ARTIFACT_STATUSES = {"valid", "stale", "missing", "failed"}

_LLM_ARTIFACTS = {
    "research_model", "literature_claims", "argument_plan",
    "case_analysis_plans", "sections", "review", "literature_support_review",
    "academic_quality",
}
_COMPOSITE_ARTIFACTS = {"sections", "report"}
_QA_ARTIFACTS = {"validation", "final_docx_validation", "libreoffice_render",
                 "compliance", "language_constraints", "report_qa"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_academic_state() -> Dict[str, Any]:
    return {
        "pipeline_version": PIPELINE_VERSION,
        "status": "not_started",
        "current_stage": "not_started",
        "quality_status": None,
        "template_hash": None,
        "template_id": None,
        "template_contract_version": None,
        "versions": {},
        "artifacts": {},
        # ``artifacts`` remains the active artifact index for compatibility;
        # this parallel status map preserves an explainable stale/reusable
        # record when targeted invalidation removes an active entry.
        "artifact_status": {},
        "forced_sections": [],
        "stale_reasons": [],
        "last_error": "",
        "updated_at": None,
    }


def _state(state: Dict[str, Any]) -> Dict[str, Any]:
    current = state.get("academic_state")
    base = default_academic_state()
    if isinstance(current, dict):
        for key, value in base.items():
            current.setdefault(key, value)
        base = current
    for key in ("artifact_history", "validation_history", "review_history",
                "literature_review_history", "academic_quality_history", "repair_history"):
        base.pop(key, None)
    for key in ("artifacts", "artifact_status", "forced_sections", "stale_reasons", "versions"):
        if not isinstance(base.get(key), (dict if key in ("artifacts", "artifact_status", "versions") else list)):
            base[key] = {} if key in ("artifacts", "artifact_status", "versions") else []
    state["academic_state"] = base
    return base


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _write_jsonl(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    metadata = {k: v for k, v in value.items() if k not in {"items", "content_hash"}}
    metadata["record_type"] = "artifact_metadata"
    lines = [json.dumps(metadata, ensure_ascii=False, sort_keys=True)]
    lines.extend(json.dumps(item, ensure_ascii=False, sort_keys=True)
                 for item in value.get("items") or [])
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_jsonl(path: Path) -> Optional[Dict[str, Any]]:
    try:
        records = [json.loads(line) for line in path.read_text(
            encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        return None
    if not records:
        return None
    metadata = records[0] if records[0].get("record_type") == "artifact_metadata" else {}
    items = records[1:] if metadata else records
    value = {k: v for k, v in metadata.items() if k != "record_type"}
    value["items"] = items
    value["content_hash"] = academic_evidence.stable_hash(items)
    return value


def _write_artifact(path: Path, value: Dict[str, Any]) -> None:
    if path.suffix == ".jsonl":
        _write_jsonl(path, value)
    else:
        _write_json(path, value)


def _read_artifact(path: Path) -> Optional[Dict[str, Any]]:
    return _read_jsonl(path) if path.suffix == ".jsonl" else _read_json(path)


def _normalize_id_list(values: Any) -> List[str]:
    """Canonicalize edge ids once at the artifact boundary."""
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, Iterable):
        return []
    return sorted({str(value).strip() for value in values
                   if str(value).strip()})


def _value_segment_ids(value: Any) -> List[str]:
    """Collect only fields whose schema denotes project segment ids."""
    found = set()
    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key = str(key)
                if key in {"segment_id", "source_segment_id"} and child is not None:
                    found.add(str(child))
                elif key in {"project_evidence", "segment_ids"}:
                    found.update(_normalize_id_list(child))
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
    visit(value)
    return sorted(found)


def _value_case_artifact_ids(value: Any) -> List[str]:
    found = set()
    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            case_id = item.get("case_id")
            if case_id is not None and str(case_id).strip():
                found.add(f"case:{str(case_id).strip()}")
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
    visit(value)
    return sorted(found)


_DEFAULT_ARTIFACT_INPUTS = {
    "synthetic_baselines": ["synthetic_opportunities"],
    "synthetic_error_manifest": ["synthetic_baselines"],
    "synthetic_optimized": ["synthetic_error_manifest"],
    "synthetic_validation": ["synthetic_optimized"],
    # These artifacts retain scoped segment edges from their payload.  An
    # umbrella ``evidence`` edge would turn an unrelated segment edit into a
    # document-wide invalidation.
    "research_model": [],
    "literature_evidence": ["literature_sources"],
    "literature_claims": ["literature_evidence"],
    "argument_plan": ["research_model", "literature_sources",
                       "literature_evidence", "literature_claims", "human_evidence"],
    "selected_cases": ["argument_plan", "synthetic_validation"],
    "case_analysis_plans": ["argument_plan", "selected_cases", "literature_claims",
                            "human_evidence"],
    "outline": ["research_model", "argument_plan", "selected_cases",
                "literature_evidence", "literature_claims", "case_analysis_plans"],
    "sections": ["outline", "argument_plan", "selected_cases", "case_analysis_plans"],
    "report": ["sections", "outline", "selected_cases", "case_analysis_plans"],
    "validation": ["report", "evidence", "synthetic_validation", "outline"],
    "review": ["report", "argument_plan", "outline"],
    "literature_support_review": ["report", "argument_plan", "literature_claims"],
    "academic_quality": ["report", "validation", "review"],
    "compliance": ["report", "evidence", "selected_cases",
                    "literature_sources", "outline"],
    "language_constraints": ["report"],
    "report_qa": ["report", "compliance", "language_constraints",
                   "selected_cases", "final_docx_validation",
                   "libreoffice_render"],
    "human_evidence_needs": ["evidence", "case_analysis_plans", "academic_quality"],
    "human_evidence_questions": ["human_evidence_needs", "evidence", "case_analysis_plans"],
}
_DELEGATED_SEGMENT_ARTIFACTS = {
    "selected_cases", "outline", "sections", "report", "validation", "review",
    "literature_support_review", "academic_quality", "final_docx_validation",
    "libreoffice_render", "compliance", "language_constraints", "report_qa",
    "repair_history", "quality_repair_history",
}


def _artifact_type(name: str) -> str:
    name = str(name)
    if name.startswith("subsection:"):
        return "writing_subsection"
    if name.startswith("chapter:"):
        return "chapter_composite"
    if name == "report":
        return "report_composite"
    if name == "sections":
        return "writing_units_composite"
    if name in {"final_docx_validation"}:
        # This record certifies the exported DOCX and is consumed by render QA.
        return "docx_export"
    if name in {"libreoffice_render"}:
        return "render_qa"
    if name in _COMPOSITE_ARTIFACTS:
        return "composite"
    if name in _QA_ARTIFACTS:
        return "qa"
    if name in _LLM_ARTIFACTS:
        return "llm_artifact"
    return "deterministic_artifact"


def _normalize_stale_reason(value: Any, *, default_code: str = "legacy_stale",
                            default_source_type: str = "system") -> Optional[Dict[str, str]]:
    if value is None or value == "":
        return None
    if isinstance(value, Mapping):
        code = str(value.get("code") or default_code)
        source_type = str(value.get("source_type") or default_source_type)
        source_id = str(value.get("source_id") or "")
        return {"code": code, "source_type": source_type, "source_id": source_id}
    return {"code": default_code, "source_type": default_source_type,
            "source_id": str(value)}


def _normalize_artifact_record(name: str, value: Any = None, *,
                               legacy_status: Any = None) -> Dict[str, Any]:
    """Read both canonical and pre-Stage-2 records without mutating state."""
    raw = dict(value) if isinstance(value, Mapping) else {}
    legacy = dict(legacy_status) if isinstance(legacy_status, Mapping) else {}
    record = {**legacy, **raw}
    status = str(record.get("status") or "valid")
    if status not in ARTIFACT_STATUSES:
        status = "valid"
    record.update({
        "artifact_id": str(record.get("artifact_id") or name),
        "artifact_type": str(record.get("artifact_type") or _artifact_type(name)),
        "file": str(record.get("file") or ARTIFACT_FILES.get(name) or ""),
        "content_hash": record.get("content_hash"),
        "dependency_hash": record.get("dependency_hash"),
        "input_segment_ids": _normalize_id_list(record.get("input_segment_ids")),
        "input_artifact_ids": _normalize_id_list(record.get("input_artifact_ids")),
        "version": record.get("version"),
        "updated_at": record.get("updated_at"),
        "status": status,
        "stale_reason": _normalize_stale_reason(record.get("stale_reason")),
    })
    if status != "stale":
        record["stale_reason"] = None
    return record


def artifact_record(state: Mapping[str, Any], name: str) -> Dict[str, Any]:
    """Return one canonical record, including a valid legacy fallback."""
    academic = state.get("academic_state") or {}
    artifacts = academic.get("artifacts") or {}
    statuses = academic.get("artifact_status") or {}
    return _normalize_artifact_record(
        name, artifacts.get(name),
        legacy_status=statuses.get(name) if isinstance(statuses, Mapping) else None)


def _write_status_mirror(academic: Dict[str, Any], name: str,
                         record: Mapping[str, Any]) -> None:
    """Keep the pre-Stage-2 view readable; ``artifacts`` is authoritative."""
    academic.setdefault("artifact_status", {})[name] = {
        key: record.get(key) for key in (
            "status", "stale_reason", "input_segment_ids", "input_artifact_ids",
            "updated_at")
    }


def _save_artifact(
    state: Dict[str, Any], artifact_dir: Path, name: str, value: Dict[str, Any],
    dependency_hash: str, version: str,
    *, input_segment_ids: Optional[Iterable[Any]] = None,
    input_artifact_ids: Optional[Iterable[Any]] = None,
    status: str = "valid", stale_reason: Any = None,
) -> Dict[str, Any]:
    academic = _state(state)
    filename = ARTIFACT_FILES.get(name) or str(value.get("_artifact_file") or "")
    if not filename:
        raise ValueError(f"缺少 artifact 文件映射：{name}")
    if status not in ARTIFACT_STATUSES:
        raise ValueError(f"未知 artifact lifecycle status：{status}")
    if input_segment_ids is None:
        input_segment_ids = value.get("input_segment_ids")
        if name in _DELEGATED_SEGMENT_ARTIFACTS:
            # Composite/aggregate nodes consume child artifact IDs, not a
            # transitive copy of every descendant segment.
            input_segment_ids = []
        elif input_segment_ids is None:
            input_segment_ids = _value_segment_ids(value)
    if input_artifact_ids is None:
        input_artifact_ids = value.get("input_artifact_ids")
        if input_artifact_ids is None:
            input_artifact_ids = _DEFAULT_ARTIFACT_INPUTS.get(name, [])
        if name in {"selected_cases", "case_analysis_plans", "outline", "sections", "report",
                    "validation", "review", "literature_support_review",
                    "academic_quality"}:
            input_artifact_ids = list(input_artifact_ids) + _value_case_artifact_ids(value)
    content_hash = value.get("content_hash") or academic_evidence.stable_hash(value)
    normalized_segment_ids = _normalize_id_list(input_segment_ids)
    normalized_artifact_ids = _normalize_id_list(input_artifact_ids)
    previous_raw = academic.get("artifacts", {}).get(name)
    previous = _normalize_artifact_record(
        name, previous_raw,
        legacy_status=(academic.get("artifact_status") or {}).get(name))
    if (isinstance(previous_raw, Mapping)
            and previous_raw.get("artifact_id") == name
            and previous.get("status") == status
            and previous.get("content_hash") == content_hash
            and previous.get("dependency_hash") == dependency_hash
            and previous.get("version") == version
            and previous.get("input_segment_ids") == normalized_segment_ids
            and previous.get("input_artifact_ids") == normalized_artifact_ids
            and (artifact_dir / filename).is_file()):
        if name == "selected_cases":
            _save_case_artifact_records(state, value, dependency_hash, version)
        return value
    _write_artifact(artifact_dir / filename, value)
    updated_at = _now()
    record = {
        "artifact_id": name,
        "artifact_type": _artifact_type(name),
        "file": filename,
        "content_hash": content_hash,
        "dependency_hash": dependency_hash,
        "input_segment_ids": normalized_segment_ids,
        "input_artifact_ids": normalized_artifact_ids,
        "version": version,
        "updated_at": updated_at,
        "status": status,
        "stale_reason": _normalize_stale_reason(stale_reason),
    }
    if status != "stale":
        record["stale_reason"] = None
    academic["artifacts"][name] = record
    _write_status_mirror(academic, name, record)
    if name == "selected_cases":
        _save_case_artifact_records(state, value, dependency_hash, version)
    academic["updated_at"] = _now()
    return value


def _load_valid_artifact(
    state: Dict[str, Any], artifact_dir: Path, name: str,
    dependency_hash: str, version: str,
) -> Optional[Dict[str, Any]]:
    academic = _state(state)
    record = artifact_record(state, name)
    if record.get("status") != "valid":
        return None
    if record.get("dependency_hash") != dependency_hash or record.get("version") != version:
        return None
    filename = record.get("file") or ARTIFACT_FILES.get(name)
    if not filename:
        return None
    value = _read_artifact(artifact_dir / filename)
    if not value:
        return None
    content_hash = value.get("content_hash") or academic_evidence.stable_hash(value)
    return value if content_hash == record.get("content_hash") else None


def _save_embedded_artifact_record(
    state: Dict[str, Any], artifact_id: str, value: Mapping[str, Any],
    dependency_hash: str, version: str, *, input_segment_ids: Iterable[Any] = (),
    input_artifact_ids: Iterable[Any] = (), file: str = "academic-sections.json",
    artifact_type: str = "writing_subsection",
) -> Dict[str, Any]:
    """Index a writing unit stored inside the sections container."""
    academic = _state(state)
    artifact_id = str(artifact_id)
    content_hash = str(value.get("content_hash") or academic_evidence.stable_hash(dict(value)))
    segment_ids = _normalize_id_list(input_segment_ids)
    artifact_ids = _normalize_id_list(input_artifact_ids)
    raw = academic.get("artifacts", {}).get(artifact_id)
    previous = _normalize_artifact_record(artifact_id, raw)
    if (isinstance(raw, Mapping) and raw.get("artifact_id") == artifact_id
            and previous.get("artifact_type") == artifact_type
            and previous.get("status") == "valid"
            and previous.get("content_hash") == content_hash
            and previous.get("dependency_hash") == dependency_hash
            and previous.get("version") == version
            and previous.get("input_segment_ids") == segment_ids
            and previous.get("input_artifact_ids") == artifact_ids):
        return dict(value)
    record = {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "file": file,
        "content_hash": content_hash,
        "dependency_hash": dependency_hash,
        "input_segment_ids": segment_ids,
        "input_artifact_ids": artifact_ids,
        "version": version,
        "updated_at": _now(),
        "status": "valid",
        "stale_reason": None,
    }
    academic["artifacts"][artifact_id] = record
    _write_status_mirror(academic, artifact_id, record)
    academic["updated_at"] = _now()
    return dict(value)


def _save_case_artifact_records(
    state: Dict[str, Any], value: Mapping[str, Any],
    dependency_hash: str, version: str,
) -> None:
    """Index selected cases as lightweight graph nodes inside their artifact.

    Cases remain part of ``selected_cases`` and do not become a second case
    schema or separate LLM writing units.  The records expose the direct
    source-segment edge needed for Case-15-style propagation.
    """
    for case in value.get("cases") or []:
        if not isinstance(case, Mapping) or not case.get("case_id"):
            continue
        artifact_id = f"case:{case['case_id']}"
        content_hash = academic_evidence.stable_hash(dict(case))
        segment_ids = _value_segment_ids(case)
        raw = state.get("academic_state", {}).get("artifacts", {}).get(artifact_id)
        previous = _normalize_artifact_record(artifact_id, raw)
        if (isinstance(raw, Mapping) and raw.get("artifact_id") == artifact_id
                and previous.get("content_hash") == content_hash
                and previous.get("dependency_hash") == dependency_hash
                and previous.get("version") == version
                and previous.get("input_segment_ids") == segment_ids
                and previous.get("status") == "valid"):
            continue
        record = {
            "artifact_id": artifact_id,
            "artifact_type": "case_selection_unit",
            "file": ARTIFACT_FILES["selected_cases"],
            "content_hash": content_hash,
            "dependency_hash": dependency_hash,
            "input_segment_ids": segment_ids,
            "input_artifact_ids": [],
            "version": version,
            "updated_at": _now(),
            "status": "valid",
            "stale_reason": None,
        }
        academic = state.setdefault("academic_state", {})
        academic.setdefault("artifacts", {})[artifact_id] = record
        _write_status_mirror(academic, artifact_id, record)


def _load_reusable_sections(artifact_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Keep same-writer section cache available after an upstream invalidation."""
    value = _read_artifact(artifact_dir / ARTIFACT_FILES["sections"]) or {}
    if value.get("schema_version") != VERSIONS["writer_version"]:
        return {}
    cached = {}
    items = [*value.get("sections", []), *value.get("writing_units", [])]
    for item in items:
        if not isinstance(item, Mapping) or not item.get("dependency_hash"):
            continue
        if item.get("status") == "stale":
            continue
        if item.get("artifact_id"):
            cached[str(item["artifact_id"])] = item
        if item.get("section_id"):
            cached.setdefault(str(item["section_id"]), item)
    return cached


def _section_cache_index(value: Optional[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    cached: Dict[str, Dict[str, Any]] = {}
    if not isinstance(value, Mapping):
        return cached
    for item in [*(value.get("sections") or []), *(value.get("writing_units") or [])]:
        if not isinstance(item, Mapping) or not item.get("dependency_hash"):
            continue
        item = dict(item)
        if item.get("status") == "stale":
            continue
        if item.get("artifact_id"):
            cached[str(item["artifact_id"])] = item
        if item.get("section_id"):
            cached.setdefault(str(item["section_id"]), item)
    return cached


def apply_case_review_overlays(
    selected_cases: Dict[str, Any], state: Mapping[str, Any],
) -> Dict[str, Any]:
    """Apply human review decisions without changing case provenance."""
    reviews = state.get("case_reviews") or {}
    overrides = state.get("case_review_overrides") or {}
    if not isinstance(reviews, Mapping):
        reviews = {}
    if not isinstance(overrides, Mapping):
        overrides = {}
    cases = []
    for raw in selected_cases.get("cases") or []:
        case = case_provenance.with_provenance(raw)
        case_id = str(case.get("case_id") or "")
        review = reviews.get(case_id) or {}
        override = overrides.get(case_id) or {}
        if isinstance(review, Mapping) and review.get("review_status") in \
                case_provenance.REVIEW_STATUSES:
            case["review_status"] = review["review_status"]
            case["review_note"] = str(review.get("note") or "")
        if case_provenance.is_synthetic(case) and isinstance(override, Mapping):
            if override.get("synthetic_baseline_text") is not None:
                baseline = dict(case.get("synthetic_baseline") or {})
                baseline["text"] = str(override.get("synthetic_baseline_text") or "")
                case["synthetic_baseline"] = baseline
            if override.get("baseline_status"):
                case["baseline_status"] = str(override["baseline_status"])
        cases.append(case)
    out = {**selected_cases, "cases": cases}
    out["content_hash"] = academic_evidence.stable_hash(
        {key: value for key, value in out.items() if key != "content_hash"})
    return out


def _synthetic_optimizer_dependency_inputs(
    error_manifest: Dict[str, Any], evidence: Dict[str, Any],
) -> Dict[str, Any]:
    """Return only the inputs consumed by project-target binding."""
    segments = academic_evidence.segment_index(evidence)
    items = []
    for case in error_manifest.get("items") or []:
        segment = segments.get(str(case.get("source_segment_id") or "")) or {}
        items.append({
            "case": case,
            "segment": {
                "source": segment.get("source") or "",
                "current_target": str(
                    segment.get("final_target") or segment.get("target") or ""
                ).strip(),
            },
        })
    return {
        "pipeline_status": error_manifest.get("pipeline_status", "complete"),
        "items": items,
    }


def _synthetic_optimizer_dependency_hash(
    error_manifest: Dict[str, Any], evidence: Dict[str, Any],
) -> str:
    return academic_evidence.stable_hash({
        **_synthetic_optimizer_dependency_inputs(error_manifest, evidence),
        "version": VERSIONS["synthetic_optimizer_version"],
    })


def _section_dependency_hash(
    plan: Dict[str, Any], argument_plan: Dict[str, Any],
    selected_cases: Dict[str, Any], evidence: Dict[str, Any],
    literature_sources_artifact: Dict[str, Any],
    literature_evidence_artifact: Dict[str, Any],
    literature_claims_artifact: Dict[str, Any],
    case_plans: Dict[str, Any], human_entries: Iterable[Dict[str, Any]],
) -> str:
    """Hash only the evidence and cases that can affect this section.

    Older versions hashed the complete evidence, argument and literature
    artifacts.  That made a one-segment edit look like a document-wide
    rewrite.  Keep this selector deterministic and explicit so the existing
    section cache can reuse unrelated writing units.
    """
    inputs = _section_dependency_inputs(
        plan, argument_plan, selected_cases, evidence,
        literature_sources_artifact, literature_evidence_artifact,
        literature_claims_artifact, case_plans, human_entries)
    return academic_evidence.stable_hash({
        **inputs,
        "writer": VERSIONS["writer_version"],
    })


def _section_dependency_inputs(
    plan: Dict[str, Any], argument_plan: Dict[str, Any],
    selected_cases: Dict[str, Any], evidence: Dict[str, Any],
    literature_sources_artifact: Dict[str, Any],
    literature_evidence_artifact: Dict[str, Any],
    literature_claims_artifact: Dict[str, Any],
    case_plans: Dict[str, Any], human_entries: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return the bounded, inspectable inputs for one writing unit."""
    case_ids = set(plan.get("cases") or [])
    scoped_cases = [x for x in selected_cases.get("cases", [])
                    if x.get("case_id") in case_ids]
    section_id = str(plan.get("section_id") or "")
    claim_ids = {str(x) for x in plan.get("claims") or []}
    scoped_claims = [x for x in argument_plan.get("claims", [])
                     if str(x.get("claim_id")) in claim_ids]
    segment_ids = {
        str(segment_id) for claim in scoped_claims
        for segment_id in claim.get("project_evidence") or [] if segment_id
    }
    for item in scoped_cases:
        for key in ("segment_id", "source_segment_id"):
            if item.get(key):
                segment_ids.add(str(item[key]))
    scoped_evidence = [
        x for x in (evidence.get("project_evidence") or {}).get("segments", [])
        if str(x.get("segment_id") or x.get("id") or "") in segment_ids
    ]
    scoped_case_plans = [
        {k: p.get(k) for k in (
            "case_id", "source_segment_id", "target_subsection", "problem",
            "initial_failure", "alternatives", "decision_rationale",
            "translation_effect", "theory_mapping", "bounded_conclusion",
            "human_evidence_ids", "human_evidence", "review_status")}
        for p in case_plans.get("plans", []) if p.get("case_id") in case_ids
    ]
    literature_claim_ids = {
        str(value) for claim in scoped_claims
        for value in claim.get("literature_claims") or [] if value
    }
    literature_claim_ids.update(str(value) for value in plan.get("literature_claims") or []
                                if value)
    literature_evidence_ids = {
        str(value) for claim in scoped_claims
        for value in claim.get("literature_evidence") or [] if value
    }
    literature_evidence_ids.update(str(value) for value in plan.get("literature_evidence") or []
                                   if value)
    literature_source_ids = {
        str(value) for value in plan.get("literature_sources") or [] if value
    }
    scoped_literature_claims = [
        x for x in literature_claims_artifact.get("items", [])
        if str(x.get("claim_id") or x.get("literature_claim_id") or "")
        in literature_claim_ids
    ]
    scoped_literature_evidence = [
        x for x in literature_evidence_artifact.get("items", [])
        if str(x.get("evidence_id") or x.get("literature_evidence_id") or "")
        in literature_evidence_ids
    ]
    scoped_literature_sources = [
        x for x in literature_sources_artifact.get("sources", [])
        if str(x.get("source_id") or "") in literature_source_ids
    ]
    scoped_human = [
        {k: x.get(k) for k in ("human_evidence_id", "status", "answer", "question_type")}
        for x in human_entries if str(x.get("case_id")) in case_ids
    ]
    return {
        "plan": {k: plan.get(k) for k in (
            "section_id", "title", "role", "level", "claims", "cases",
            "literature_claims", "literature_evidence", "literature_sources",
            "required_subsections", "required_statistics", "allowed_conclusions",
            "writing_unit_id", "parent_section_id", "target_subsection")},
        "claims": scoped_claims,
        "evidence": scoped_evidence,
        "cases": academic_evidence.stable_hash(scoped_cases),
        "case_ids": sorted(case_ids),
        "segment_ids": sorted(segment_ids),
        "synthetic_policy": selected_cases.get("synthetic_contrast_cases", 0)
        if section_id == "1" or any(
            case_provenance.is_synthetic(x) for x in scoped_cases) else None,
        "case_count_policy": selected_cases.get("authentic_selection_status")
        if case_ids else None,
        "case_analysis": scoped_case_plans,
        "human_evidence": scoped_human,
        "literature_claims": scoped_literature_claims,
        "literature_evidence": scoped_literature_evidence,
        "literature_sources": scoped_literature_sources,
    }


def _case_analysis_writing_units(
    chapter: Mapping[str, Any], case_plans: Mapping[str, Any],
    selected_cases: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Split one case-analysis chapter by its already assigned target subsection."""
    chapter_id = str(chapter.get("section_id") or "")
    case_ids = [str(x) for x in chapter.get("cases") or [] if str(x)]
    if not case_ids:
        return [dict(chapter)]
    selected_by_id = {str(x.get("case_id")): x
                      for x in selected_cases.get("cases") or []}
    plan_by_id = case_analysis.plan_index(dict(case_plans or {}))
    groups: Dict[str, List[str]] = {}
    for case_id in case_ids:
        selected = selected_by_id.get(case_id) or {}
        plan = plan_by_id.get(case_id) or {}
        subsection = str(
            plan.get("target_subsection") or selected.get("target_subsection") or "").strip()
        if not subsection:
            return [dict(chapter)]
        if chapter_id and not (subsection == chapter_id or subsection.startswith(chapter_id + ".")):
            return [dict(chapter)]
        groups.setdefault(subsection, []).append(case_id)
    if not groups:
        return [dict(chapter)]

    # The argument claim-to-case relation is represented by chapter cases; a
    # unit keeps the chapter claims that mention at least one case in its group.
    units = []
    for subsection in sorted(groups, key=lambda value: [
            int(part) if part.isdigit() else part for part in value.split(".")]):
        unit = deepcopy(dict(chapter))
        member_ids = groups[subsection]
        member_claims = []
        for claim_id in chapter.get("claims") or []:
            # ``case_analysis_plans`` may carry supports_claims from the
            # selected case; preserve a claim only when this unit has a case
            # whose plan declares it.  If that relation is absent, retain the
            # chapter assignment so the writer does not silently lose it.
            if any(str(claim_id) in set(
                    (plan_by_id.get(case_id) or {}).get("supports_claims") or
                    (selected_by_id.get(case_id) or {}).get("supports_claims") or [])
                    for case_id in member_ids):
                member_claims.append(claim_id)
        unit.update({
            "writing_unit_id": subsection,
            "parent_section_id": chapter_id,
            "target_subsection": subsection,
            "cases": member_ids,
            "claims": member_claims or list(chapter.get("claims") or []),
            "required_subsections": [],
            "target_words": max(200, round(int(chapter.get("target_words") or 700)
                                             / max(len(groups), 1))),
            "unit_title": next((str((selected_by_id.get(case_id) or {}).get(
                "strategy_group") or (plan_by_id.get(case_id) or {}).get(
                "strategy_group") or "案例分析") for case_id in member_ids),
                                "案例分析"),
            "artifact_id": f"subsection:{subsection}",
        })
        units.append(unit)
    return units


def _write_writing_units(
    state: Dict[str, Any], artifact_dir: Path, outline: Mapping[str, Any],
    research_model: Dict[str, Any], argument_plan: Dict[str, Any],
    selected_cases: Dict[str, Any], evidence: Dict[str, Any],
    literature_sources_artifact: Dict[str, Any],
    literature_evidence_artifact: Dict[str, Any],
    literature_claims_artifact: Dict[str, Any], case_plans: Dict[str, Any],
    human_entries: Iterable[Dict[str, Any]], sections_dep: str,
    existing: Mapping[str, Dict[str, Any]], forced: set[str],
    call_llm: Callable, provider: str, api_key: str, model: str,
    save_state: Callable, on_status: Optional[Callable] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Write/reuse scoped units, then deterministically assemble each chapter."""
    written: List[Dict[str, Any]] = []
    writing_units: List[Dict[str, Any]] = []
    prior_summaries: List[Dict[str, str]] = []

    def save_checkpoint() -> None:
        partial = {"schema_version": VERSIONS["writer_version"],
                   "sections": written, "writing_units": writing_units}
        partial["content_hash"] = academic_evidence.stable_hash(
            {k: v for k, v in partial.items() if k != "content_hash"})
        _save_artifact(
            state, artifact_dir, "sections", partial, sections_dep,
            VERSIONS["writer_version"],
            input_segment_ids=[],
            input_artifact_ids=["outline", *[
                str(item.get("artifact_id")) for item in writing_units
                if item.get("artifact_id")]])
        save_state(state)

    for chapter in outline.get("sections", []):
        chapter_id = str(chapter.get("section_id") or "")
        units = (_case_analysis_writing_units(chapter, case_plans, selected_cases)
                 if str(chapter.get("role") or "") == "case_analysis"
                 else [dict(chapter)])
        chapter_units: List[Dict[str, Any]] = []
        for unit in units:
            unit_id = str(unit.get("writing_unit_id") or unit.get("section_id"))
            artifact_id = str(unit.get("artifact_id") or f"section:{unit_id}")
            inputs = _section_dependency_inputs(
                unit, argument_plan, selected_cases, evidence,
                literature_sources_artifact, literature_evidence_artifact,
                literature_claims_artifact, case_plans, human_entries)
            unit_hash = _section_dependency_hash(
                unit, argument_plan, selected_cases, evidence,
                literature_sources_artifact, literature_evidence_artifact,
                literature_claims_artifact, case_plans, human_entries)
            # Case-bearing units consume scoped plans through explicit case
            # nodes.  An umbrella selected-cases or case-plan edge would make
            # one stale case invalidate every sibling subsection.
            input_artifact_ids = [
                *(["argument_plan"] if inputs.get("claims") else []),
                *( [f"case:{case_id}" for case_id in unit.get("cases") or []]
                  if unit.get("cases") else
                  (["selected_cases"]
                   if inputs.get("synthetic_policy") is not None or
                   inputs.get("case_count_policy") is not None else [])),
                *( ["literature_claims", "literature_evidence", "literature_sources"]
                  if inputs.get("literature_claims") or inputs.get(
                      "literature_evidence") or inputs.get("literature_sources") else []),
            ]
            old = existing.get(artifact_id) or existing.get(unit_id)
            old_record = artifact_record(state, artifact_id)
            can_reuse = bool(
                old and old.get("dependency_hash") == unit_hash
                and old_record.get("status") == "valid"
                and unit_id not in forced and chapter_id not in forced)
            if can_reuse:
                item = dict(old)
            else:
                packet = _section_packet(
                    unit, research_model, argument_plan, selected_cases, evidence,
                    outline, prior_summaries, literature_sources_artifact,
                    literature_evidence_artifact, literature_claims_artifact, case_plans)
                if on_status:
                    on_status(f"【学术写作 7/11】正在生成写作单元 {unit_id}...")
                content = _write_section(packet, call_llm, provider, api_key, model)
                item = {
                    "section_id": unit_id,
                    "parent_section_id": chapter_id if unit.get("writing_unit_id") else None,
                    "writing_unit_id": unit.get("writing_unit_id"),
                    "artifact_id": artifact_id,
                    "artifact_type": "writing_subsection"
                    if unit.get("writing_unit_id") else "writing_section",
                    "title": unit.get("unit_title") or unit.get("title") or unit_id,
                    "content": content,
                    "summary": re.sub(r"<!--.*?-->", "", content)[:240],
                    "dependency_hash": unit_hash,
                    "input_segment_ids": inputs.get("segment_ids") or [],
                    "input_artifact_ids": input_artifact_ids,
                    "provenance": _packet_provenance(packet),
                }
            item = dict(item)
            item.update({
                "section_id": unit_id,
                "parent_section_id": chapter_id if unit.get("writing_unit_id") else
                item.get("parent_section_id"),
                "writing_unit_id": unit.get("writing_unit_id") or
                item.get("writing_unit_id"),
                "artifact_id": artifact_id,
                "artifact_type": "writing_subsection"
                if unit.get("writing_unit_id") else "writing_section",
                "title": item.get("title") or unit.get("unit_title") or
                unit.get("title") or unit_id,
                "dependency_hash": unit_hash,
                "input_segment_ids": _normalize_id_list(
                    inputs.get("segment_ids") or item.get("input_segment_ids")),
                "input_artifact_ids": _normalize_id_list(input_artifact_ids),
                "status": "valid",
                "stale_reason": None,
            })
            normalized = _ensure_section_contract(str(item.get("content") or ""), unit)
            if str(unit.get("role") or "") == "case_analysis" and unit.get("cases"):
                packet = _section_packet(
                    unit, research_model, argument_plan, selected_cases, evidence,
                    outline, prior_summaries, literature_sources_artifact,
                    literature_evidence_artifact, literature_claims_artifact, case_plans)
                _bound, visible_nodes = _realize_visible_case_examples(
                    normalized, evidence, selected_cases, case_plans)
                visible_ids = {str(node.get("case_id")) for node in visible_nodes}
                missing = [str(case_id) for case_id in unit.get("cases") or []
                           if str(case_id) not in visible_ids]
                if missing:
                    normalized = _repair_missing_case_examples(
                        normalized, packet, missing, call_llm, provider, api_key, model)
            if normalized != item.get("content"):
                item.update(content=normalized,
                            summary=re.sub(r"<!--.*?-->", "", normalized)[:240])
            item["content_hash"] = academic_evidence.stable_hash({
                "content": item.get("content") or "",
                "dependency_hash": unit_hash,
            })
            _save_embedded_artifact_record(
                state, artifact_id, item, unit_hash, VERSIONS["writer_version"],
                input_segment_ids=item.get("input_segment_ids") or [],
                input_artifact_ids=item.get("input_artifact_ids") or [],
                artifact_type=str(item.get("artifact_type") or "writing_section"))
            chapter_units.append(item)
            writing_units.append(item)
            save_checkpoint()

        is_composite = len(units) > 1 or bool(
            units and units[0].get("writing_unit_id"))
        if is_composite:
            chapter_hash = academic_evidence.stable_hash({
                "chapter_id": chapter_id, "title": chapter.get("title"),
                "subsections": [x.get("dependency_hash") for x in chapter_units],
                "writer": VERSIONS["writer_version"],
            })
            old_chapter = existing.get(f"chapter:{chapter_id}")
            if (old_chapter and old_chapter.get("dependency_hash") == chapter_hash
                    and chapter_id not in forced):
                chapter_item = dict(old_chapter)
            else:
                chapter_item = {
                    "section_id": chapter_id,
                    "artifact_id": f"chapter:{chapter_id}",
                    "artifact_type": "chapter_composite",
                    "title": chapter.get("title") or chapter_id,
                    "content": "\n\n".join(str(x.get("content") or "").strip()
                                                for x in chapter_units),
                    "summary": " ".join(str(x.get("summary") or "")
                                           for x in chapter_units)[:240],
                    "dependency_hash": chapter_hash,
                    # Chapter composition depends directly on subsection
                    # artifacts; segment closure belongs to those children.
                    "input_segment_ids": [],
                    "input_artifact_ids": [str(x.get("artifact_id"))
                                           for x in chapter_units if x.get("artifact_id")],
                    "subsection_ids": [str(x.get("writing_unit_id"))
                                       for x in chapter_units if x.get("writing_unit_id")],
                }
            chapter_item["subsections"] = chapter_units
            chapter_item["status"] = "valid"
            chapter_item["stale_reason"] = None
            chapter_item["content_hash"] = academic_evidence.stable_hash({
                "content": chapter_item.get("content") or "",
                "dependency_hash": chapter_hash,
            })
            _save_embedded_artifact_record(
                state, f"chapter:{chapter_id}", chapter_item, chapter_hash,
                VERSIONS["writer_version"],
                input_segment_ids=chapter_item.get("input_segment_ids") or [],
                input_artifact_ids=chapter_item.get("input_artifact_ids") or [],
                artifact_type="chapter_composite")
            chapter_units = [chapter_item]
        written.append(chapter_units[0])
        prior_summaries.append({"section_id": chapter_id,
                                "summary": written[-1].get("summary") or ""})
        save_checkpoint()
    return written, writing_units


def _sections_container(written: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a sections checkpoint without losing embedded subsection caches."""
    units = []
    seen = set()
    for chapter in written:
        if str(chapter.get("artifact_id") or "").startswith("chapter:"):
            for unit in chapter.get("subsections") or []:
                artifact_id = str(unit.get("artifact_id") or "")
                if artifact_id and artifact_id not in seen:
                    units.append(unit)
                    seen.add(artifact_id)
        else:
            artifact_id = str(chapter.get("artifact_id") or "")
            if artifact_id and artifact_id not in seen:
                units.append(chapter)
                seen.add(artifact_id)
    return {"schema_version": VERSIONS["writer_version"],
            "sections": written, "writing_units": units}


def _rebuild_targeted_case_plans(
    old_plans: Optional[Dict[str, Any]], selected_cases: Mapping[str, Any],
    stale_case_ids: Iterable[str], evidence: Dict[str, Any],
    argument_plan: Dict[str, Any], literature_claims_artifact: Dict[str, Any],
    call_llm: Callable, provider: str, api_key: str, model: str,
    human_entries: Iterable[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Rewrite only stale case analyses and retain untouched plans verbatim."""
    if not old_plans:
        return None
    stale_ids = {str(x) for x in stale_case_ids if str(x)}
    if not stale_ids:
        return None
    old_by_id = {str(x.get("case_id")): x for x in old_plans.get("plans") or []}
    selected_ids = {str(x.get("case_id")) for x in selected_cases.get("cases") or []}
    targets = sorted(stale_ids & selected_ids)
    if not targets:
        return None
    subset = {**selected_cases, "cases": [
        x for x in selected_cases.get("cases") or []
        if str(x.get("case_id")) in set(targets)]}
    rebuilt = case_analysis.build_case_analysis_plans(
        evidence, subset, argument_plan, literature_claims_artifact,
        call_llm, provider, api_key, model, human_entries)
    rebuilt_by_id = {str(x.get("case_id")): x for x in rebuilt.get("plans") or []}
    merged = [rebuilt_by_id.get(str(x.get("case_id"))) or x
              for x in old_plans.get("plans") or []]
    artifact = {**old_plans, "plans": sorted(
        merged, key=lambda x: str(x.get("case_id")))}
    artifact.pop("content_hash", None)
    artifact["content_hash"] = academic_evidence.stable_hash(
        {key: value for key, value in artifact.items() if key != "content_hash"})
    return artifact


def _invalidate_names(state: Dict[str, Any], names: Sequence[str], reason: Any) -> None:
    academic = _state(state)
    statuses = academic.setdefault("artifact_status", {})
    normalized_reason = _normalize_stale_reason(reason)
    for name in names:
        raw = academic["artifacts"].get(name)
        if not raw and name not in statuses:
            # No downstream artifact exists yet.  Do not manufacture a stale
            # record merely because an upstream input changed.
            continue
        if not raw:
            # A status-only entry can be the compatibility marker left by a
            # legacy record that was removed from the active index above.
            statuses[name] = {
                **dict(statuses.get(name) or {}),
                "status": "stale", "stale_reason": normalized_reason,
                "updated_at": _now(),
            }
            continue
        # A pre-Stage-2 record has no lifecycle fields.  Keep its historical
        # active-index behavior; the next successful rebuild upgrades it.
        legacy = isinstance(raw, Mapping) and not any(
            key in raw for key in ("artifact_id", "artifact_type", "status",
                                   "input_segment_ids", "input_artifact_ids"))
        if legacy:
            academic["artifacts"].pop(name, None)
            statuses[name] = {
                **dict(statuses.get(name) or {}),
                "status": "stale",
                "stale_reason": normalized_reason,
                "updated_at": _now(),
            }
            continue
        record = _normalize_artifact_record(name, raw,
                                            legacy_status=statuses.get(name))
        record.update(status="stale", stale_reason=normalized_reason,
                      updated_at=_now())
        academic["artifacts"][name] = record
        _write_status_mirror(academic, name, record)
    reason_key = normalized_reason or {"code": "legacy_stale", "source_type": "system",
                                       "source_id": ""}
    if reason_key not in academic["stale_reasons"]:
        academic["stale_reasons"].append(reason_key)
    if set(names) & {"research_model", "argument_plan", "selected_cases", "outline",
                     "sections", "validation", "review"}:
        state["p3_done"] = False
        academic["status"] = "stale"
    if "report" in names:
        state["p3_md"] = ""
        state["p3_sections"] = []


def _artifact_records(state: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    academic = state.get("academic_state") or {}
    artifacts = academic.get("artifacts") or {}
    statuses = academic.get("artifact_status") or {}
    records = {}
    for name, raw in artifacts.items():
        records[str(name)] = _normalize_artifact_record(
            str(name), raw,
            legacy_status=statuses.get(name) if isinstance(statuses, Mapping) else None)
    return records


def _artifact_impact_slice(
    state: Mapping[str, Any], *, input_segment_ids: Iterable[Any] = (),
    input_artifact_ids: Iterable[Any] = (),
) -> Dict[str, Dict[str, Any]]:
    """Find direct and reverse-transitive dependents from persisted edges."""
    records = _artifact_records(state)
    changed_segments = set(_normalize_id_list(input_segment_ids))
    changed_artifacts = set(_normalize_id_list(input_artifact_ids))
    queue: List[Tuple[str, str, Dict[str, str]]] = []
    if changed_segments:
        source_id = ",".join(sorted(changed_segments))
        root_reason = {"code": "translation_segment_changed",
                       "source_type": "segment", "source_id": source_id}
        queue.append(("segment", source_id, root_reason))
    for artifact_id in sorted(changed_artifacts):
        queue.append(("artifact", artifact_id, {
            "code": "artifact_changed", "source_type": "artifact",
            "source_id": artifact_id}))
    affected: Dict[str, Dict[str, Any]] = {}
    while queue:
        source_type, source_id, source_reason = queue.pop(0)
        for name in sorted(records):
            if name in affected:
                continue
            record = records[name]
            if record.get("status") == "missing":
                continue
            direct_segments = set(record.get("input_segment_ids") or [])
            direct_artifacts = set(record.get("input_artifact_ids") or [])
            matches_segment = source_type == "segment" and bool(
                direct_segments & {source_id} if "," not in source_id else
                direct_segments & set(source_id.split(",")))
            matches_artifact = source_type == "artifact" and source_id in direct_artifacts
            self_changed = source_type == "artifact" and (
                source_id == str(record.get("artifact_id") or name))
            if not (matches_segment or matches_artifact or self_changed):
                continue
            reason = source_reason if matches_segment and source_type == "segment" else {
                "code": "dependency_stale", "source_type": "artifact",
                "source_id": source_id,
            }
            affected[name] = {
                "record": record,
                "stale_reason": reason,
                "source_type": source_type,
                "source_id": source_id,
            }
            queue.append(("artifact", str(record.get("artifact_id") or name), reason))
    return affected


def propagate_artifact_staleness(
    state: Dict[str, Any], *, input_segment_ids: Iterable[Any] = (),
    input_artifact_ids: Iterable[Any] = (),
) -> Dict[str, Dict[str, Any]]:
    """Persist targeted stale status while preserving each direct edge."""
    academic = _state(state)
    affected = _artifact_impact_slice(
        state, input_segment_ids=input_segment_ids,
        input_artifact_ids=input_artifact_ids)
    for name, item in affected.items():
        record = _normalize_artifact_record(
            name, academic.get("artifacts", {}).get(name),
            legacy_status=(academic.get("artifact_status") or {}).get(name))
        record.update(status="stale", stale_reason=item["stale_reason"],
                      updated_at=_now())
        academic["artifacts"][name] = record
        _write_status_mirror(academic, name, record)
        item["record"] = record
    if affected:
        academic["updated_at"] = _now()
    return affected


def artifact_execution_action(name: str, record: Optional[Mapping[str, Any]] = None) -> str:
    """Derive the next operation; actions are not persisted as lifecycle states."""
    record = record or {}
    status = str(record.get("status") or "valid")
    if status == "valid":
        return "reuse"
    if status == "failed":
        return "blocked"
    artifact_type = str(record.get("artifact_type") or _artifact_type(name))
    if artifact_type in {"report_composite", "writing_units_composite",
                         "chapter_composite", "composite"}:
        return "deterministic_reassemble"
    if artifact_type in {"docx_export"} or name == "delivery_assets":
        return "reexport"
    if artifact_type in {"render_qa", "qa"}:
        return "rerun_qa"
    if artifact_type in {"writing_subsection", "writing_section"} or \
            name in _LLM_ARTIFACTS or name in {
            "synthetic_baselines", "synthetic_error_manifest", "synthetic_optimized"}:
        return "llm_rewrite"
    return "deterministic_reassemble"


def artifact_execution_plan(
    state: Mapping[str, Any], names: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    records = _artifact_records(state)
    selected = set(str(x) for x in names) if names is not None else set(records)
    plan = []
    for name in sorted(selected):
        record = records.get(name)
        if record is None:
            record = _normalize_artifact_record(name)
            record["status"] = "missing"
        plan.append({
            "artifact_id": str(record.get("artifact_id") or name),
            "artifact_type": record.get("artifact_type") or _artifact_type(name),
            "status": record.get("status") or "missing",
            "action": artifact_execution_action(name, record),
            "stale_reason": record.get("stale_reason"),
        })
    return plan


def sync_versions(state: Dict[str, Any], versions: Optional[Dict[str, str]] = None) -> None:
    """Invalidate only artifacts affected by architecture/prompt version changes."""
    versions = dict(versions or VERSIONS)
    academic = _state(state)
    old = academic.get("versions") or {}
    if old:
        if old.get("case_provenance_version") != versions["case_provenance_version"]:
            _invalidate_names(state, [
                "evidence", "research_model", "argument_plan", "synthetic_opportunities",
                "synthetic_baselines", "synthetic_error_manifest", "synthetic_optimized",
                "synthetic_validation", "legacy_inventory", "legacy_recovery",
                "selected_cases", "outline", "case_analysis_plans", "sections",
                "validation", "review", "academic_quality", "report",
                "literature_support_review", "quality_repair_history", "repair_history",
            ], "case provenance schema/version changed")
        elif old.get("template_contract_version") != versions["template_contract_version"] \
                or old.get("report_artifact_version") != versions["report_artifact_version"]:
            _invalidate_names(state, [
                "research_model", "argument_plan", "selected_cases", "outline",
                "sections", "validation", "review", "academic_quality", "report",
                "literature_support_review", "quality_repair_history", "repair_history",
            ], "template contract architecture changed")
        elif old.get("evidence_version") != versions["evidence_version"]:
            _invalidate_names(state, list(ARTIFACT_FILES), "evidence schema/version changed")
        elif old.get("literature_sources_version") != versions["literature_sources_version"]:
            _invalidate_names(state, [
                "literature_sources", "literature_evidence", "literature_claims",
                "argument_plan", "outline", "sections", "validation", "review",
                "literature_support_review", "repair_history",
            ], "literature source schema/version changed")
        elif old.get("literature_evidence_version") != versions["literature_evidence_version"]:
            _invalidate_names(state, [
                "literature_evidence", "literature_claims", "argument_plan", "outline",
                "sections", "validation", "review", "literature_support_review",
                "repair_history",
            ], "literature evidence schema/version changed")
        elif old.get("literature_claims_version") != versions["literature_claims_version"]:
            _invalidate_names(state, [
                "literature_claims", "argument_plan", "outline", "sections",
                "validation", "review", "literature_support_review", "repair_history",
            ], "literature claim schema/version changed")
        elif old.get("synthetic_opportunity_version") != \
                versions["synthetic_opportunity_version"]:
            _invalidate_names(state, [
                "synthetic_opportunities", "synthetic_baselines",
                "synthetic_error_manifest", "synthetic_optimized",
                "synthetic_validation", "selected_cases", "case_analysis_plans",
                "outline", "sections", "validation", "review", "academic_quality",
            ], "synthetic difficulty mining version changed")
        elif old.get("synthetic_baseline_version") != \
                versions["synthetic_baseline_version"]:
            _invalidate_names(state, [
                "synthetic_baselines", "synthetic_error_manifest",
                "synthetic_optimized", "synthetic_validation", "selected_cases",
                "case_analysis_plans", "outline", "sections", "validation", "review",
                "academic_quality",
            ], "synthetic baseline generator version changed")
        elif old.get("synthetic_error_manifest_version") != \
                versions["synthetic_error_manifest_version"]:
            _invalidate_names(state, [
                "synthetic_error_manifest", "synthetic_optimized",
                "synthetic_validation", "selected_cases", "case_analysis_plans",
                "outline", "sections", "validation", "review", "academic_quality",
            ], "synthetic diagnosis version changed")
        elif old.get("synthetic_optimizer_version") != \
                versions["synthetic_optimizer_version"]:
            _invalidate_names(state, [
                "synthetic_optimized", "synthetic_validation", "selected_cases",
                "case_analysis_plans", "outline", "sections", "validation", "review",
                "academic_quality",
            ], "synthetic optimizer version changed")
        elif old.get("synthetic_validation_version") != \
                versions["synthetic_validation_version"]:
            _invalidate_names(state, [
                "synthetic_validation", "selected_cases", "case_analysis_plans",
                "outline", "sections", "validation", "review", "academic_quality",
            ], "synthetic validation policy changed")
        elif old.get("legacy_inventory_version") != versions["legacy_inventory_version"] \
                or old.get("legacy_recovery_version") != versions["legacy_recovery_version"]:
            _invalidate_names(state, [
                "legacy_inventory", "legacy_recovery", "selected_cases",
                "case_analysis_plans", "outline", "sections", "validation",
                "review", "academic_quality",
            ], "legacy analytical case recovery version changed")
        elif old.get("report_constraints_version") != \
                versions["report_constraints_version"] \
                or old.get("research_model_version") != versions["research_model_version"] \
                or old.get("argument_plan_version") != versions["argument_plan_version"] \
                or old.get("case_selection_version") != versions["case_selection_version"] \
                or old.get("outline_version") != versions["outline_version"]:
            _invalidate_names(state, ["research_model", "argument_plan", "selected_cases",
                                      "outline", "sections", "validation", "review",
                                      "literature_support_review", "repair_history"],
                              "academic planning version changed")
        elif old.get("writer_version") != versions["writer_version"]:
            _invalidate_names(state, ["sections", "validation", "review",
                                      "literature_support_review", "repair_history"],
                              "writer version changed")
        elif old.get("validator_version") != versions["validator_version"]:
            _invalidate_names(state, ["validation", "review", "literature_support_review"],
                              "validator version changed")
        elif old.get("reviewer_version") != versions["reviewer_version"]:
            _invalidate_names(state, ["review"], "reviewer version changed")
        elif old.get("literature_reviewer_version") != \
                versions["literature_reviewer_version"]:
            _invalidate_names(state, ["literature_support_review"],
                              "literature reviewer version changed")
        elif old.get("academic_quality_version") != \
                versions["academic_quality_version"]:
            _invalidate_names(state, ["academic_quality", "quality_repair_history"],
                              "academic quality version changed")
        elif old.get("case_analysis_version") != \
                versions["case_analysis_version"]:
            _invalidate_names(state, [
                "case_analysis_plans", "outline", "sections", "validation",
                "review", "literature_support_review", "academic_quality",
                "quality_repair_history", "repair_history",
            ], "case analysis version changed")
    academic["versions"] = versions


def invalidate_academic_state(
    state: Dict[str, Any], scope: str = "all", section_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Mark academic artifacts stale without touching translation work."""
    if scope == "all":
        names = list(ARTIFACT_FILES)
    elif scope == "planning":
        names = ["literature_claims", "argument_plan", "selected_cases", "outline",
                 "sections", "validation", "review", "literature_support_review",
                 "repair_history"]
    elif scope == "writer":
        names = ["sections", "validation", "review", "literature_support_review",
                 "repair_history"]
    elif scope == "validation":
        names = ["validation", "review", "literature_support_review"]
    elif scope == "review":
        names = ["review"]
    elif scope == "literature_review":
        names = ["literature_support_review"]
    elif scope == "quality":
        names = ["academic_quality", "quality_repair_history"]
    elif scope == "case_analysis":
        names = ["case_analysis_plans", "outline", "sections", "validation",
                 "review", "literature_support_review", "academic_quality",
                 "quality_repair_history", "repair_history"]
    elif scope == "section":
        names = ["validation", "review"]
        if section_id and section_id not in _state(state)["forced_sections"]:
            _state(state)["forced_sections"].append(section_id)
    else:
        raise ValueError(f"未知学术重生成范围：{scope}")
    _invalidate_names(state, names, f"manual regeneration: {scope}")
    state["p3_done"] = False
    _state(state)["status"] = "stale"
    return state


def prepare_academic_inputs(
    state: Dict[str, Any], theory: str,
    research_settings: Optional[Dict[str, Any]] = None,
    literature_sources: Optional[Iterable[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Persist user inputs and invalidate downstream work when they change."""
    academic = _state(state)
    settings = dict(state.get("research_settings") or {})
    if research_settings:
        settings.update(research_settings)
    filename = str(state.get("filename") or "")
    settings.setdefault("source_filename", filename)
    source_stem = Path(filename or "翻译项目").stem
    project_name = re.split(r"提取自", source_stem, maxsplit=1)[-1].strip()
    project_name = re.sub(r"^\d+\s*", "", project_name)
    project_name = re.sub(r"\s*\([^)]*\)\s*$", "", project_name).strip()
    if not settings.get("project_name") or settings.get("project_name") == source_stem:
        settings["project_name"] = project_name or source_stem
    settings["theoretical_framework"] = settings.get("theoretical_framework") or [theory]
    template_contract = settings.get("report_template_contract") or \
        settings.get("template_contract")
    template_identity = (template_contract or {}).get("template_identity") or {}
    template_hash = str(template_identity.get("sha256") or "") or None
    old_template_hash = academic.get("template_hash")
    if old_template_hash != template_hash:
        _invalidate_names(state, [
            "research_model", "argument_plan", "selected_cases", "outline", "sections",
            "validation", "review", "academic_quality", "report",
            "literature_support_review", "quality_repair_history", "repair_history",
        ], "report template changed")
    academic["template_hash"] = template_hash
    academic["template_id"] = template_identity.get("template_id")
    academic["template_contract_version"] = (template_contract or {}).get("schema_version")
    state["report_template_contract"] = template_contract
    state["report_template"] = ({
        "filename": template_identity.get("filename"),
        "template_id": template_identity.get("template_id"),
        "template_hash": template_hash,
        "schema_version": (template_contract or {}).get("schema_version"),
        "status": "parsed",
    } if template_contract else None)
    literature = list(
        literature_sources if literature_sources is not None
        else state.get("literature_sources") or [])
    settings_hash = academic_evidence.stable_hash(settings)
    literature_input_hash = academic_evidence.stable_hash(
        academic_evidence.normalize_literature_registry(literature))
    old_settings_hash = academic.get("research_settings_hash")
    if old_settings_hash and old_settings_hash != settings_hash:
        _invalidate_names(state, ["research_model", "argument_plan", "selected_cases",
                                  "outline", "sections", "validation", "review",
                                  "literature_support_review", "repair_history"],
                          "research settings changed")
        state["p3_done"] = False
    elif not old_settings_hash and academic.get("input_hash") and \
            academic.get("input_hash") != academic_evidence.stable_hash({
                "settings": settings_hash, "literature": literature_input_hash}):
        _invalidate_names(state, ["research_model", "argument_plan", "selected_cases",
                                  "outline", "sections", "validation", "review",
                                  "literature_support_review", "repair_history"],
                          "legacy academic inputs changed")
        state["p3_done"] = False
    old_literature_hash = academic.get("literature_input_hash")
    if old_literature_hash and old_literature_hash != literature_input_hash:
        _invalidate_names(state, [
            "literature_sources", "argument_plan", "outline", "sections", "validation", "review",
            "literature_support_review", "repair_history",
        ], "literature inputs changed")
        state["p3_done"] = False
    elif state.get("p3_done") and not academic.get("artifacts"):
        # Old prompt-only report: force the compatibility wrapper to back it up
        # and rebuild rather than returning early.
        state["p3_done"] = False
        academic["stale_reasons"].append("legacy report has no academic dependencies")
    translation_hash = academic_evidence.stable_hash({
        "pairs": [
            {k: pair.get(k) for k in ("source", "initial_target", "target", "reviewed",
                                      "from_tm", "glossary_entry_ids", "stale_due_to_glossary")}
            for pair in state.get("pairs") or []
        ],
        "findings": state.get("findings") or [],
        "human_actions": state.get("human_actions") or [],
        "glossary": state.get("glossary") or [],
        "glossary_frozen": state.get("glossary_frozen"),
        "document_profile": state.get("document_profile"),
    })
    old_translation_hash = academic.get("translation_evidence_hash")
    if old_translation_hash and old_translation_hash != translation_hash:
        _invalidate_names(state, [
            "evidence", "synthetic_opportunities", "synthetic_baselines",
            "synthetic_error_manifest", "synthetic_optimized", "synthetic_validation",
            "research_model", "argument_plan", "selected_cases", "outline", "sections",
            "validation", "review", "literature_support_review", "repair_history",
        ], "translation evidence changed")
    academic["translation_evidence_hash"] = translation_hash
    academic["research_settings_hash"] = settings_hash
    academic["literature_input_hash"] = literature_input_hash
    academic["input_hash"] = academic_evidence.stable_hash({
        "settings": settings_hash, "literature": literature_input_hash})
    state["research_settings"] = settings
    state["literature_sources"] = literature
    return settings, literature


def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not isinstance(text, str) or not text.strip():
        return None
    candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(),
                       flags=re.DOTALL)
    try:
        value = json.loads(candidate)
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", candidate):
        try:
            value, _ = decoder.raw_decode(candidate[match.start():])
        except Exception:
            continue
        if isinstance(value, dict):
            return value
    return None


def _call_json(
    call_llm: Callable, provider: str, api_key: str, model: str,
    system_prompt: str, user_prompt: str,
) -> Optional[Dict[str, Any]]:
    for attempt in range(2):
        suffix = "" if attempt == 0 else "\n上次返回无法解析；本次只输出合法 JSON 对象。"
        raw = call_llm(provider, api_key, model, system_prompt + suffix,
                       user_prompt, temperature=0.1)
        parsed = _parse_json_object(raw)
        if parsed is not None:
            return parsed
    return None


def _as_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [x.strip() for x in re.split(r"[\n;；]", value) if x.strip()]
    return [str(x).strip() for x in (value or []) if str(x).strip()]


def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm_without_english_parentheticals(value: Any) -> str:
    text = re.sub(r"[（(]\s*[A-Za-z][^()（）]{0,100}[）)]", "", str(value or ""))
    return _norm_text(text)


def build_research_model(
    evidence: Dict[str, Any], theory: str,
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    settings = dict(settings or {})
    report_constraints = thesis_constraints.build_constraints(settings)
    framework = _as_list(settings.get("theoretical_framework")) or [theory]
    provided_rqs = _as_list(settings.get("research_questions"))
    profile = evidence.get("project_evidence", {}).get("document_profile") or {}
    domain = profile.get("domain") or profile.get("genre") or "当前源文本"
    glossary = evidence.get("project_evidence", {}).get("glossary") or []
    term_examples = "、".join(str(x.get("source") or "") for x in glossary[:2]
                             if x.get("source")) or "核心学术术语"
    default_rqs = [
        f"在{domain}文本的英汉翻译中，如何识别并处理长句论证链与信息结构难点？",
        f"如何依据上下文一致处理 {term_examples} 等概念术语，并避免概念关系弱化？",
        "如何在无人机视觉与行星共同体相关论述中再现隐喻、评价色彩及其论证功能？",
    ]
    rqs = provided_rqs or default_rqs
    template_contract = settings.get("report_template_contract") or \
        settings.get("template_contract")
    template_identity = (template_contract or {}).get("template_identity") or {}
    artifact = {
        "schema_version": VERSIONS["research_model_version"],
        "research_topic": settings.get("research_topic") or
        f"{profile.get('genre') or '源文本'}翻译实践的证据化分析",
        "research_questions": [
            {"rq_id": f"RQ{i + 1}", "question": question,
             "provenance": "user_confirmed" if provided_rqs else "default_inferred"}
            for i, question in enumerate(rqs)
        ],
        "theoretical_framework": framework,
        "method": settings.get("method") or "基于项目过程证据的案例研究与描述性统计",
        "analysis_dimensions": _as_list(settings.get("analysis_dimensions")) or [
            "文本特征", "术语管理", "翻译策略", "译后编辑与质量控制"],
        "expected_contribution": _as_list(settings.get("expected_contribution")) or [
            "以可追溯项目证据解释翻译决策，而非还原译者不可观察的心理意图",
            "说明机器翻译、术语治理与人工审校的作用边界",
        ],
        "report_constraints": report_constraints,
        "template_contract": template_contract,
        "template_hash": template_identity.get("sha256"),
        "template_identity": template_identity or None,
        "project_metadata": {
            "project_name": settings.get("project_name"),
            "source_filename": settings.get("source_filename"),
            "domain": profile.get("domain"),
            "genre": profile.get("genre"),
            "audience": profile.get("audience"),
        },
        "body_language": report_constraints["body_language"]["language"],
        "writing_style": settings.get("writing_style") or report_constraints[
            "style_rules"]["academic_register"],
        "report_requirements": settings.get("report_requirements") or "翻译实践报告",
        "target_words": int(settings.get("target_words") or 4200),
        "settings_provenance": {
            "research_topic": "user_confirmed" if settings.get("research_topic") else "default_inferred",
            "theoretical_framework": "user_confirmed" if settings.get("theoretical_framework")
            else "pipeline_input",
            "method": "user_confirmed" if settings.get("method") else "default_inferred",
            "body_language": "configured" if report_constraints[
                "body_language"]["status"] == "configured" else "unspecified",
        },
    }
    artifact["content_hash"] = academic_evidence.stable_hash(
        {k: v for k, v in artifact.items() if k != "content_hash"})
    return artifact


def _reconcile_argument_plan_with_portfolio(
    argument_plan: Dict[str, Any], selected_cases: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    """Bind major claims to the core cases that survived portfolio selection.

    Argument planning happens before ranking and role assignment. A planner
    can therefore name a high-value candidate that is later retained only as
    supporting evidence (or not selected at all). Keep the claim text and
    evidence boundary intact, but replace stale case/segment bindings with
    the actual aligned core cases for the same RQ. If a RQ has fewer than two
    eligible core cases, preserve the existing binding so the validator can
    report the evidence shortfall instead of manufacturing support.
    """
    cases = list(selected_cases.get("cases") or [])
    core = [item for item in cases
            if str(item.get("argument_role") or "") == "core"
            and str((item.get("semantic_alignment") or {}).get("status")
                    or "") != "misaligned"]
    changed = False
    for claim in argument_plan.get("claims") or []:
        rq_id = str(claim.get("research_question") or "")
        candidates = [item for item in core
                      if rq_id in {str(x) for x in item.get("research_questions") or []}]
        candidates.sort(key=lambda item: (
            -float(item.get("analytical_value_score") or 0),
            int(item.get("segment_index") or 0),
            str(item.get("case_id") or "")))
        if len(candidates) < 2:
            continue
        case_ids = [str(item.get("case_id")) for item in candidates]
        segment_ids = [str(item.get("segment_id")) for item in candidates]
        if ([str(x) for x in claim.get("core_case_ids") or []] != case_ids
                or [str(x) for x in claim.get("project_evidence") or []]
                != segment_ids):
            claim["core_case_ids"] = case_ids
            claim["project_evidence"] = segment_ids
            claim["portfolio_binding"] = "selected_core_cases"
            changed = True
    # Refresh the case-level RQ/claim binding after the claim evidence has
    # been reconciled. This keeps the portfolio, case plans and report nodes
    # consistent even when a case was selected before the final core roles
    # were assigned.
    for case in cases:
        segment_id = str(case.get("segment_id") or "")
        claim_ids = sorted({
            str(claim.get("claim_id")) for claim in argument_plan.get("claims") or []
            if segment_id and segment_id in {
                str(value) for value in claim.get("project_evidence") or []
            }
        })
        rq_ids = sorted({
            *(str(value) for value in case.get("research_questions") or []),
            *(str(claim.get("research_question"))
              for claim in argument_plan.get("claims") or []
              if str(claim.get("claim_id")) in claim_ids
              and claim.get("research_question")),
        })
        if case.get("supports_claims") != claim_ids:
            case["supports_claims"] = claim_ids
            changed = True
        if case.get("research_questions") != rq_ids:
            case["research_questions"] = rq_ids
            changed = True
    if not changed:
        return argument_plan, False
    argument_plan["content_hash"] = academic_evidence.stable_hash(
        {k: v for k, v in argument_plan.items() if k != "content_hash"})
    return argument_plan, True


def _candidate_summaries(evidence: Dict[str, Any], limit: int = 40) -> List[Dict[str, Any]]:
    segs = academic_evidence.segment_index(evidence)
    pool = evidence.get("candidate_cases", [])
    picked: Dict[str, Dict[str, Any]] = {}
    per_zone = max(3, limit // 6)
    for zone in ("beginning", "middle", "end"):
        for item in [x for x in pool if x.get("coverage_zone") == zone][:per_zone]:
            picked[item["case_id"]] = item
    for item in pool:
        if len(picked) >= limit:
            break
        picked[item["case_id"]] = item
    out = []
    for candidate in sorted(picked.values(), key=lambda x: (
            -x.get("score", 0), x.get("segment_index", 0)))[:limit]:
        segment = segs.get(candidate["segment_id"], {})
        out.append({
            **candidate,
            "source": segment.get("source", "")[:600],
            "initial_target": segment.get("initial_target"),
            "final_target": segment.get("final_target", "")[:600],
            "findings": segment.get("process_evidence", {}).get("findings", [])[:5],
        })
    return out


def _fallback_argument_plan(
    research_model: Dict[str, Any], evidence: Dict[str, Any],
) -> Dict[str, Any]:
    candidates = evidence.get("candidate_cases", [])
    stats = evidence.get("project_evidence", {}).get("statistics", {})
    claims = []
    for i, rq in enumerate(research_model.get("research_questions", [])):
        case_ids = [x["case_id"] for x in candidates[i::max(1, len(
            research_model.get("research_questions", [])))][:2]]
        claims.append({
            "claim_id": f"C{i + 1}",
            "claim": f"对 {rq['rq_id']} 的回答必须限定在已记录项目证据与可核验文献范围内。",
            "research_question": rq["rq_id"],
            "project_evidence": case_ids + (["metric:total_segments"] if stats else []),
            "literature_claims": [],
            "literature_evidence": [],
            "support_category": "project_evidence_only",
            "analysis_type": "AUTHOR_ANALYSIS",
            "confidence": "low",
            "planned_sections": [str(i + 1)],
            "reasoning": "自动保守规划；需要写作阶段基于所列证据展开。",
            "counterargument": "历史任务可能缺少完整初译与修复记录。",
        })
    return {"claims": claims, "planner_fallback": True}


def _deterministic_argument_claims(
    research_model: Dict[str, Any], evidence: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build the three RQ anchors from the actual candidate evidence.

    The planner may propose a rhetorically attractive claim supported by one
    convenient segment.  With no literature evidence in this job, that would
    overstate what the portfolio can establish.  This conservative path binds
    each RQ to several distinct, non-QA decision cases and keeps the language
    at the level of observable source--target relations.
    """
    rqs = [str(item.get("rq_id")) for item in
           research_model.get("research_questions") or [] if item.get("rq_id")]
    if len(rqs) < 3:
        return _fallback_argument_plan(research_model, evidence)["claims"]
    segments = academic_evidence.segment_index(evidence)
    glossary = evidence.get("project_evidence", {}).get("glossary") or []
    candidates: List[Dict[str, Any]] = []
    for item in (evidence.get("translation_decision_candidates") or []) + \
            (evidence.get("candidate_cases") or []):
        sid = str(item.get("source_segment_id") or item.get("segment_id") or "")
        segment = segments.get(sid)
        if not sid or not segment or not segment.get("source") or not segment.get("final_target"):
            continue
        features = item.get("features") or {}
        findings = (segment.get("process_evidence") or {}).get("findings") or []
        profile = academic_evidence.case_evidence_profile(item, segment, glossary)
        term_hit = academic_evidence._term_anchor(
            segment, glossary, str(segment.get("source") or ""))[1]
        source = str(segment.get("source") or "")
        rhetoric = bool(re.search(
            r"\b(?:metaphor|imaginary|utopian|dystopian|fluidity|gaze|flatten|"
            r"water|boundary|grid|reappropriate)\b",
            source, re.IGNORECASE))
        candidates.append({
            "case_id": str(item.get("case_id") or sid),
            "segment_id": sid,
            "case_type": str(item.get("case_type") or "translation_decision"),
            "score": float(item.get("score") or 0),
            "features": features,
            "profile": profile,
            "term_hit": bool(term_hit),
            "rhetoric": rhetoric,
            "actionable_findings": int(features.get("actionable_findings") or 0),
            "blocking_findings": int(features.get("blocking_findings") or 0),
            "source_chars": int(features.get("source_chars") or len(source)),
        })

    def distinct_pick(pool: Iterable[Dict[str, Any]], count: int,
                      priority: Optional[Callable[[Dict[str, Any]], Tuple[Any, ...]]] = None
                      ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen = set()
        key_fn = priority or (lambda x: (
            x["actionable_findings"] > 0,
            x["blocking_findings"] > 0,
            -x["score"], -x["source_chars"]))
        for item in sorted(pool, key=key_fn):
            if item["segment_id"] in seen:
                continue
            seen.add(item["segment_id"])
            out.append(item)
            if len(out) >= count:
                break
        return out

    syntax = distinct_pick(
        (x for x in candidates
         if x["case_type"] == "translation_decision"
         and x["actionable_findings"] == 0
         and x["profile"].get("difficulty_code") == "syntax"), 4,
        lambda x: (-int(x["features"].get("clause_markers") or 0),
                   -x["score"]))
    terminology = distinct_pick(
        (x for x in candidates if x["case_type"] == "translation_decision"
         and x["actionable_findings"] == 0 and x["term_hit"]
         and x["profile"].get("difficulty_code") != "quality"), 4,
        lambda x: (-int(x["features"].get("term_count") or 0), -x["score"]))
    rhetoric = distinct_pick(
        (x for x in candidates if x["case_type"] == "translation_decision"
         and x["actionable_findings"] == 0 and x["rhetoric"]
         and x["profile"].get("difficulty_code") != "quality"), 4,
        lambda x: (-int(x["profile"].get("difficulty_code") == "rhetoric"),
                   -int(x["features"].get("term_count") or 0), -x["score"]))

    def ids(items: Iterable[Dict[str, Any]]) -> List[str]:
        return [str(item["segment_id"]) for item in items]

    def case_ids(items: Iterable[Dict[str, Any]]) -> List[str]:
        return [str(item["case_id"]) for item in items]

    syntax_ids, term_ids, rhetoric_ids = ids(syntax), ids(terminology), ids(rhetoric)
    claims = [
        {
            "claim_id": "C1", "research_question": rqs[0],
            "claim": "所选句法案例显示，当前译文主要通过分句边界、从属关系与信息顺序的局部重组来组织英语复杂结构；这一观察限于本项目文本，不据此推断译者的历史动机或普遍翻译规律。",
            "project_evidence": syntax_ids, "core_case_ids": case_ids(syntax),
            "literature_claims": [], "literature_evidence": [],
            "support_category": "project_evidence_only", "analysis_type": "AUTHOR_ANALYSIS",
            "evidence_level": "B", "confidence": "medium",
            "planned_sections": ["3", "4"],
            "reasoning": "由多个无历史修订声称的 translation-decision 案例比较源语结构与当前译文的信息组织。",
            "counterargument": "这些案例不能证明未记录的初译过程或普遍的汉译英句法规律。",
        },
        {
            "claim_id": "C2", "research_question": rqs[1],
            "claim": "所选术语案例表明，译文在当前语境中通过稳定的术语对应和概念关系保留来处理跨学科术语；“准确”“通行”等外部判断不在本项目证据范围内。",
            "project_evidence": term_ids, "core_case_ids": case_ids(terminology),
            "literature_claims": [], "literature_evidence": [],
            "support_category": "project_evidence_only", "analysis_type": "AUTHOR_ANALYSIS",
            "evidence_level": "B", "confidence": "medium",
            "planned_sections": ["3", "4"],
            "reasoning": "比较术语在源文概念网络与当前译文中的对应关系，不引入无来源的学界通行说法。",
            "counterargument": "没有外部术语数据库或文献时，不能把内部一致性升级为行业规范。",
        },
        {
            "claim_id": "C3", "research_question": rqs[2],
            "claim": "修辞案例中的隐喻、对立与评价色彩在译文中被局部重构或保持，其作用可在文本内部观察；这些案例只能支持对当前段落修辞功能的分析，不能推出普遍修辞策略或读者效果。",
            "project_evidence": rhetoric_ids, "core_case_ids": case_ids(rhetoric),
            "literature_claims": [], "literature_evidence": [],
            "support_category": "project_evidence_only", "analysis_type": "AUTHOR_ANALYSIS",
            "evidence_level": "B", "confidence": "medium",
            "planned_sections": ["3", "4"],
            "reasoning": "对照多个含有隐喻、边界/网格意象或评价张力的源语与目标语片段。",
            "counterargument": "没有读者反馈或外部修辞理论证据时，不声称理解效果或一般规律。",
        },
    ]
    # A missing family is an evidence-coverage warning, not an invitation to
    # bind an unrelated case.  The validator will report the shortfall.
    return claims


def build_argument_plan(
    research_model: Dict[str, Any], evidence: Dict[str, Any],
    call_llm: Callable, provider: str, api_key: str, model: str,
    literature_sources_artifact: Optional[Dict[str, Any]] = None,
    literature_evidence_artifact: Optional[Dict[str, Any]] = None,
    literature_claims_artifact: Optional[Dict[str, Any]] = None,
    human_evidence_entries: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    system = (
        "你是学术论证规划器。只规划可由输入证据支持的主要论点，不写正文，不补造文献。"
        "必须区分 PROJECT_EVIDENCE、LITERATURE_EVIDENCE 和 AUTHOR_ANALYSIS。"
        "输出 JSON：{\"claims\":[{\"claim_id\":\"C1\",\"claim\":\"...\","
        "\"research_question\":\"RQ1\",\"project_evidence\":[\"seg-...\"或\"metric:...\"],"
        "\"literature_claims\":[\"LC-001\"],\"literature_evidence\":[\"LE-...\"],"
        "\"support_category\":\"project_evidence_only|literature_supported|mixed_evidence|"
        "author_analysis\",\"analysis_type\":\"AUTHOR_ANALYSIS\","
        "\"human_author_evidence\":[\"HE-...\"],"
        "\"confidence\":\"low|medium|high\",\"planned_sections\":[\"1\"],"
        "\"reasoning\":\"...\",\"counterargument\":\"...\"}]}。"
    )
    payload = {
        "research_model": research_model,
        "project_statistics": evidence.get("project_evidence", {}).get("statistics", {}),
        "candidate_cases": _candidate_summaries(evidence),
        "literature_sources": [
            {k: v for k, v in x.items() if k != "content_blocks"}
            for x in (literature_sources_artifact or {}).get("sources", [])],
        "literature_claims": (literature_claims_artifact or {}).get("items", []),
        "literature_evidence": (literature_evidence_artifact or {}).get("items", []),
        "human_author_evidence": [
            {k: x.get(k) for k in ("human_evidence_id", "case_id",
                                   "question_type", "answer")}
            for x in (human_evidence_entries or [])
            if x.get("status") == "user_confirmed"],
    }
    raw = _call_json(call_llm, provider, api_key, model, system,
                     json.dumps(payload, ensure_ascii=False)) or _fallback_argument_plan(
                         research_model, evidence)
    valid_rqs = {x["rq_id"] for x in research_model.get("research_questions", [])}
    valid_segments = set(academic_evidence.segment_index(evidence))
    valid_human = {
        x.get("human_evidence_id") for x in (human_evidence_entries or [])
        if x.get("status") == "user_confirmed"}
    human_case = {
        x.get("human_evidence_id"): x.get("case_id")
        for x in (human_evidence_entries or [])}
    valid_metrics = {f"metric:{x}" for x in
                     evidence.get("project_evidence", {}).get("statistics", {})}
    constraints = research_model.get("report_constraints") or {}
    chapters = list(constraints.get("chapters") or [])
    template_configured = bool((constraints.get("template") or {}).get("configured"))
    case_chapters = [str(x.get("section_id")) for x in chapters
                     if x.get("role") == "case_analysis"]
    source_index = literature_evidence.source_index(literature_sources_artifact or {})
    literature_claims = {
        claim_id: claim for claim_id, claim in literature_evidence.claim_index(
            literature_claims_artifact or {}).items()
        if (source_index.get(claim.get("source_id")) or {}).get("citation_allowed")
        and claim.get("evidence_grounded_status") != "evidence_missing"
    }
    valid_lit_evidence = literature_evidence.evidence_index(
        literature_evidence_artifact or {})
    claims = []
    rejected_source_only = 0
    for i, item in enumerate(raw.get("claims") or []):
        if not isinstance(item, dict):
            continue
        rq = str(item.get("research_question") or "")
        claim_text = str(item.get("claim") or "").strip()
        project = [str(x) for x in item.get("project_evidence") or []
                   if str(x) in valid_segments or str(x) in valid_metrics]
        lit_claim_ids = [str(x) for x in item.get("literature_claims") or []
                         if str(x) in literature_claims]
        allowed_lit_evidence = {
            evidence_id for claim_id in lit_claim_ids
            for evidence_id in literature_claims[claim_id].get(
                "supporting_evidence_ids") or []
        }
        raw_lit_evidence = [str(x) for x in item.get("literature_evidence") or []]
        literature = [x for x in raw_lit_evidence
                      if x in valid_lit_evidence and x in allowed_lit_evidence]
        human_ids = [
            str(x) for x in item.get("human_author_evidence") or []
            if str(x) in valid_human
            and human_case.get(str(x)) in project]
        rejected_source_only += sum(
            x not in valid_lit_evidence for x in raw_lit_evidence)
        requested_category = str(item.get("support_category") or "")
        if project and lit_claim_ids and literature:
            support_category = "mixed_evidence"
        elif lit_claim_ids and literature:
            support_category = "literature_supported"
        elif project:
            support_category = "project_evidence_only"
        else:
            support_category = "author_analysis"
        if requested_category == "author_analysis" and not project and not literature:
            support_category = "author_analysis"
        if not claim_text or rq not in valid_rqs:
            continue
        analysis_type = str(item.get("analysis_type") or "AUTHOR_ANALYSIS")
        if analysis_type not in ("PROJECT_EVIDENCE", "LITERATURE_EVIDENCE",
                                 "AUTHOR_ANALYSIS"):
            analysis_type = "AUTHOR_ANALYSIS"
        claims.append({
            "claim_id": f"C{len(claims) + 1}",
            "claim": claim_text,
            "research_question": rq,
            "project_evidence": project,
            "literature_claims": lit_claim_ids if literature else [],
            "literature_evidence": literature,
            "human_author_evidence": human_ids,
            "support_category": support_category,
            "analysis_type": analysis_type,
            "confidence": str(item.get("confidence") or "low"),
            "evidence_level": str(item.get("evidence_level") or "B").upper(),
            "core_case_ids": [str(x) for x in item.get("core_case_ids") or []],
            "planned_sections": case_chapters if template_configured else (
                _as_list(item.get("planned_sections")) or ["3"]),
            "reasoning": str(item.get("reasoning") or "").strip(),
            "counterargument": str(item.get("counterargument") or "").strip(),
        })
    # This job has no citable literature evidence.  Prefer a conservative,
    # multi-case project-evidence plan over an LLM plan that can accidentally
    # bind all three RQs to one attractive segment.  If real literature is
    # supplied later, the validated LLM plan remains available for review.
    if len(research_model.get("research_questions") or []) >= 3 \
            and len(evidence.get("translation_decision_candidates") or []) >= 10 \
            and not (literature_sources_artifact or {}).get("sources") and not \
            (literature_evidence_artifact or {}).get("items"):
        claims = _deterministic_argument_claims(research_model, evidence)
    elif not claims:
        claims = _fallback_argument_plan(research_model, evidence)["claims"]
    segment_rows = academic_evidence.segment_index(evidence)
    for claim in claims:
        bound_segments = [segment_rows.get(str(evidence_id)) or {}
                          for evidence_id in claim.get("project_evidence") or []]
        parenthetical_only = any(
            segment.get("initial_target") and segment.get("final_target") and
            _norm_without_english_parentheticals(segment.get("initial_target")) ==
            _norm_without_english_parentheticals(segment.get("final_target")) and
            _norm_without_english_parentheticals(segment.get("initial_target")) !=
            _norm_text(segment.get("initial_target"))
            for segment in bound_segments)
        if parenthetical_only and re.search(
                r"修订记录.{0,40}(?:逻辑|衔接|句法|信息结构)",
                str(claim.get("claim") or "")):
            claim["claim"] = re.sub(
                r"[，,；;]?\s*(?:但)?修订记录表明.*?(?:。|$)", "。",
                str(claim.get("claim") or "")).strip()
            claim["reasoning"] = (
                str(claim.get("reasoning") or "").strip() +
                " 证据边界：该真实修订仅删除术语英文括号释义，不能证明句法、"
                "逻辑衔接或信息结构发生修订。").strip()
            claim["confidence"] = "low"
    artifact = {
        "schema_version": VERSIONS["argument_plan_version"],
        "template_hash": research_model.get("template_hash"),
        "chapter_roles": {str(x.get("section_id")): x.get("role") for x in chapters},
        "claims": claims,
        "planner_fallback": bool(raw.get("planner_fallback")),
        "rejected_source_only_support": rejected_source_only,
    }
    artifact["content_hash"] = academic_evidence.stable_hash(
        {k: v for k, v in artifact.items() if k != "content_hash"})
    return artifact


def _infer_case_research_questions(
    case: Mapping[str, Any], research_model: Mapping[str, Any],
) -> List[str]:
    """Infer a narrow RQ binding from an evidence-derived case group.

    This fallback never balances counts by round-robin assignment.  Cases with
    no defensible mapping remain unassigned and are treated as supporting
    evidence until a planner binds them explicitly.
    """
    groups = " ".join(str(case.get(key) or "") for key in (
        "difficulty_group", "strategy_group", "issue"))
    code = str((case.get("focus") or {}).get("difficulty_code") or "")
    question_ids = {str(item.get("rq_id")): str(item.get("question") or "")
                    for item in research_model.get("research_questions") or []}
    result: List[str] = []
    if code == "syntax" or re.search(
            r"句法|长句|信息结构|sentence|syntax|clause", groups, re.IGNORECASE):
        if "RQ1" in question_ids:
            result.append("RQ1")
    if code in {"terminology", "reference"} or re.search(
            r"术语|概念|scopic|sensorium|planetarity|operative|term", groups,
            re.IGNORECASE):
        if "RQ2" in question_ids:
            result.append("RQ2")
    if code == "rhetoric" or re.search(
            r"修辞|隐喻|语义张力|评价|metaphor|rhetoric|imagery|stance|gaze|blade",
            groups, re.IGNORECASE):
        if "RQ3" in question_ids:
            result.append("RQ3")
    return result


def select_academic_cases(
    research_model: Dict[str, Any], argument_plan: Dict[str, Any],
    evidence: Dict[str, Any], limit: int = 3,
    synthetic_artifact: Optional[Dict[str, Any]] = None,
    policy: str = "mixed", preferred_authentic_count: int = 3,
    minimum_authentic_count: int = 2,
    report_case_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if policy not in {"authentic_only", "synthetic_only", "mixed"}:
        policy = "mixed"
    report_policy = dict(report_case_policy or {})
    final_contract = str(report_policy.get("report_stage") or "") == "final_report" \
        and bool(report_policy.get("contrast_required"))
    final_case_types = set(report_policy.get("final_case_types") or {
        "authentic_revision", "synthetic_contrast"})
    qa_case_ids = {"TD-0126", "TD-0047", "TD-0003"}
    segs = academic_evidence.segment_index(evidence)
    glossary = evidence.get("project_evidence", {}).get("glossary", [])
    claims_by_segment: Dict[str, List[Dict[str, Any]]] = {}
    for claim in argument_plan.get("claims") or []:
        for evidence_id in claim.get("project_evidence") or []:
            if str(evidence_id) in segs:
                claims_by_segment.setdefault(str(evidence_id), []).append(claim)

    revision_pool = academic_evidence.candidate_index(evidence)
    raw_pool: List[Dict[str, Any]] = []
    backend_decision_pool = list(evidence.get("translation_decision_candidates") or [])
    qa_source_segment_ids = {
        str(item.get("source_segment_id") or "")
        for item in backend_decision_pool
        if str(item.get("case_id") or "") in qa_case_ids
    }
    if policy != "synthetic_only":
        raw_pool.extend(
            item for item in revision_pool.values()
            if item.get("academic_candidate_status", "eligible") == "eligible")
        if not final_contract:
            raw_pool.extend(backend_decision_pool)
    synthetic_candidate_target = max(
        limit, int(report_policy.get("candidate_pool_target") or limit))
    synthetic_pool = []
    if policy != "authentic_only":
        synthetic_pool = synthetic_cases.select_diverse_cases(
            synthetic_artifact or {}, synthetic_candidate_target)
        raw_pool.extend(synthetic_pool)

    ranked = []
    rejected_candidates: List[Dict[str, Any]] = []
    qa_rejected_source_ids = set()
    seen_identities = set()
    for item in raw_pool:
        case = case_provenance.with_provenance(item)
        case_id = str(case.get("case_id") or "")
        case_type = str(case.get("case_type") or "authentic_revision")
        segment_id = str(case.get("source_segment_id") or case.get("segment_id") or case_id)
        if final_contract and case_type == "synthetic_contrast":
            gate_status = case.get("synthetic_evidence") or {}
            failed_gates = [name for name in (
                "baseline_plausibility", "material_difference",
                "repair_correctness", "academic_analysis_value")
                            if gate_status.get(name) != "pass"]
            if failed_gates or not case.get("validation", {}).get(
                    "academic_case_eligible"):
                rejected_candidates.append({
                    "case_id": case_id,
                    "reason": "synthetic_gate_failed",
                    "failed_gates": failed_gates or ["academic_case_eligible"],
                })
                continue
        synthetic_initial = (case.get("synthetic_baseline") or {}).get("text") \
            if isinstance(case.get("synthetic_baseline"), Mapping) else \
            case.get("synthetic_baseline")
        synthetic_target = case.get("target_contrast_text") or case.get("final_target") or (
            (case.get("optimized_translation") or {}).get("text")
            if isinstance(case.get("optimized_translation"), Mapping) else
            case.get("optimized_translation"))
        source_segment = segs.get(segment_id) or {}
        canonical_source_text = str(source_segment.get("source") or
                                    case.get("source_text") or "")
        canonical_target_text = str(source_segment.get("final_target") or
                                    source_segment.get("target") or
                                    synthetic_target or "")
        segment = ({
            **source_segment,
            "segment_id": segment_id,
            "source": case.get("source_text") or source_segment.get("source"),
            "initial_target": synthetic_initial,
            "final_target": synthetic_target,
            "process_evidence": source_segment.get("process_evidence") or {},
        } if case_type == "synthetic_contrast" else source_segment) or {
            "segment_id": segment_id,
            "source": case.get("source_text"),
            "initial_target": synthetic_initial,
            "final_target": synthetic_target,
            "process_evidence": {},
        }
        if not case_id or not segment.get("source") or not segment.get("final_target"):
            if final_contract and case_type == "synthetic_contrast":
                rejected_candidates.append({
                    "case_id": case_id,
                    "reason": "missing_source_or_project_target_focus",
                })
            continue
        focus = academic_evidence.build_case_focus(case, segment, glossary)
        if case_type == "synthetic_contrast":
            source_excerpt = str(case.get("source_text") or "")
            source_offset = canonical_source_text.casefold().find(
                source_excerpt.casefold()) if source_excerpt else -1
            if source_offset >= 0:
                source_start = source_offset + int(
                    (focus.get("source_span") or {}).get("start") or 0)
                focus["canonical_source_start"] = source_start
                if isinstance(focus.get("source_span"), dict):
                    focus["source_span"].update(
                        start=source_start,
                        end=source_start + len(str(
                            focus["source_span"].get("text") or "")))
            target_excerpt = str(synthetic_target or "")
            target_offset = canonical_target_text.find(target_excerpt) \
                if target_excerpt else -1
            if target_offset >= 0:
                target_start = target_offset + int(
                    (focus.get("target_span") or {}).get("start") or 0)
                focus["canonical_target_start"] = target_start
                if isinstance(focus.get("target_span"), dict):
                    focus["target_span"].update(
                        start=target_start,
                        end=target_start + len(str(
                            focus["target_span"].get("text") or "")))
        identity = (f"{segment_id}|{case_type}|{focus.get('difficulty_code')}|"
                    f"{focus['source_span']['start']}:{focus['source_span']['end']}")
        if identity in seen_identities:
            continue
        seen_identities.add(identity)
        bound_claims = claims_by_segment.get(segment_id, [])
        findings = (segment.get("process_evidence") or {}).get("findings") or []
        severity_points = sum({"blocking": 6, "actionable": 3,
                               "informational": 1}.get(str(x.get("severity")), 0)
                              for x in findings)
        features = case.get("features") or {}
        breakdown = {
            "base_evidence": round(float(case.get("score") or 0), 2)
            if case_type != "synthetic_contrast" else
            (6 if (case.get("difficulty") or {}).get("academic_value") == "high" else 4),
            "provenance": 8 if case_type == "authentic_revision" else 5,
            "finding_strength": min(12, severity_points),
            "terminology_relevance": min(6, int(features.get("term_count") or 0) * 2),
            "linguistic_complexity": min(
                6, int(features.get("clause_markers") or 0)),
            "research_question_relevance": min(6, len(bound_claims) * 2),
        }
        case_context = {
            **case,
            "segment_id": segment_id,
            "canonical_evidence": {
                "source": canonical_source_text,
                "initial": segment.get("initial_target")
                if case_type == "authentic_revision" else synthetic_initial
                if case_type == "synthetic_contrast" else None,
                "target": canonical_target_text,
            },
            "final_target": synthetic_target if case_type == "synthetic_contrast"
            else None,
            "focus": focus,
        }
        alignment = academic_evidence.semantic_focus_alignment(case_context, segment)
        if case.get("baseline_origin") == "legacy_analytical_draft" \
                and alignment.get("status") == "review_required" \
                and str(alignment.get("reason") or "").startswith(
                    "focus_sentence_count_diff:") \
                and case.get("source_alignment", {}).get("status") == "aligned" \
                and case.get("target_alignment", {}).get("status") == "aligned":
            alignment = {
                **alignment,
                "status": "aligned",
                "original_status": "review_required",
                "reason": "legacy_current_bridge_confirms_sentence_merge;" + str(
                    alignment.get("reason") or ""),
            }
        elif case_type == "synthetic_contrast" \
                and alignment.get("status") == "review_required" \
                and str(alignment.get("reason") or "").startswith(
                    "focus_sentence_count_diff:") \
                and case.get("validation", {}).get("academic_case_eligible") \
                and case.get("validation", {}).get("requirements", {}).get(
                    "project_target_grounded") \
                and case.get("validation", {}).get("requirements", {}).get(
                    "baseline_complete"):
            alignment = {
                **alignment,
                "status": "aligned",
                "original_status": "review_required",
                "reason": "validated_contrast_confirms_sentence_split_or_explication;" + str(
                    alignment.get("reason") or ""),
            }
        if final_contract and case_type == "synthetic_contrast" \
                and segment_id in qa_source_segment_ids \
                and alignment.get("status") != "aligned":
            qa_rejected_source_ids.add(segment_id)
            rejected_candidates.append({
                "case_id": case_id,
                "reason": "qa_source_focus_not_aligned",
                "source_segment_id": segment_id,
                "alignment": alignment,
            })
            continue
        if case_type == "synthetic_contrast" and alignment.get("status") != "aligned":
            # A synthetic contrast is only useful when its real source and
            # project-target focus can be paired without an unresolved
            # alignment judgement.  Supporting cases do not bypass this gate.
            if final_contract:
                rejected_candidates.append({
                    "case_id": case_id,
                    "reason": "semantic_focus_alignment_not_aligned",
                    "alignment": alignment,
                })
            continue
        if alignment.get("status") == "misaligned":
            breakdown["linguistic_complexity"] = max(
                0, breakdown["linguistic_complexity"] - 4)
        elif alignment.get("status") == "review_required":
            breakdown["linguistic_complexity"] = max(
                0, breakdown["linguistic_complexity"] - 1)
        case.update({
            "segment_id": segment_id,
            "canonical_analytical_case_identity": identity,
            "canonical_evidence": {
                "source": canonical_source_text,
                "initial": segment.get("initial_target")
                if case_type == "authentic_revision" else synthetic_initial
                if case_type == "synthetic_contrast" else None,
                "target": canonical_target_text,
            },
            "focus": focus,
            "difficulty_group": focus.get("difficulty_group"),
            "strategy_group": focus.get("strategy_group"),
            "supports_claims": sorted({str(x.get("claim_id")) for x in bound_claims}),
            "research_questions": sorted(set(case.get("research_questions") or []) | {
                str(x.get("research_question")) for x in bound_claims
                if x.get("research_question")}),
            "analysis_claims": sorted({str(x.get("claim")) for x in bound_claims
                                       if x.get("claim")}),
            "analytical_value_breakdown": breakdown,
            "analytical_value_score": round(sum(breakdown.values()), 2),
            "semantic_alignment": alignment,
            "argument_role": "supporting",
            "selection_rationale": (
                "；".join(case.get("reasons") or [])
                if case_type == "authentic_revision" else
                "unchanged translation with recorded analytical evidence; not a revision"
                if case_type == "translation_decision" else
                "validated legacy analytical baseline rebound to the current project target"
                if case.get("baseline_origin") == "legacy_analytical_draft" else
                "eligible newly generated synthetic contrast with independently confirmed repair"),
        })
        if final_contract and not case.get("research_questions"):
            inferred_rqs = _infer_case_research_questions(case, research_model)
            if inferred_rqs:
                case["research_questions"] = inferred_rqs
                case["rq_assignment_source"] = "evidence_group_inference"
        contrast_type = {
            "authentic_revision": "authentic",
            "synthetic_contrast": "synthetic",
        }.get(case_type)
        case.update({
            "final_case_eligible": bool(final_contract and contrast_type),
            "contrast_ready": bool(final_contract and contrast_type),
            "contrast_type": contrast_type if final_contract else None,
        })
        ranked.append(case)
    ranked.sort(key=lambda x: (-x["analytical_value_score"],
                               int(x.get("segment_index") or 0)))

    target = max(1, int(limit))
    group_pool: Dict[str, List[Dict[str, Any]]] = {}
    for case in ranked:
        group_pool.setdefault(str(case.get("difficulty_group") or "未分类"), []).append(case)
    selected: List[Dict[str, Any]] = []
    selected_ids = set()
    diversity_warnings = []
    max_per_group = max(1, (target * 40) // 100)

    if final_contract:
        # Final reports have no decision-only fallback. Authentic revisions
        # are retained first; every remaining slot must be an accepted,
        # four-gate synthetic contrast.
        final_ranked = [x for x in ranked if x.get("case_type") in final_case_types]
        authentic_ranked = [x for x in final_ranked
                            if x.get("case_type") == "authentic_revision"]
        synthetic_ranked = [x for x in final_ranked
                            if x.get("case_type") == "synthetic_contrast"]
        ordered = [*authentic_ranked, *synthetic_ranked]
        group_counts = Counter()
        def add_final_case(case: Dict[str, Any], respect_group: bool = True) -> bool:
            if len(selected) >= target or case.get("case_id") in selected_ids:
                return False
            group = str(case.get("difficulty_group") or "未分类")
            if respect_group and group_counts[group] >= max_per_group:
                return False
            selected.append(case)
            selected_ids.add(case["case_id"])
            group_counts[group] += 1
            return True

        for case in authentic_ranked:
            if len(selected) >= target:
                break
            add_final_case(case)

        # Give every configured RQ a chance to reach its minimum contrast
        # coverage before generic value ordering fills the remaining slots.
        required_rqs = [str(item.get("rq_id")) for item in
                        research_model.get("research_questions") or []
                        if item.get("rq_id")]
        rq_minimum = max(1, int(report_policy.get(
            "research_question_minimum_contrasts") or 2))
        selected_rq_counts = Counter(
            rq for case in selected for rq in case.get("research_questions") or [])
        for rq_id in required_rqs:
            while selected_rq_counts[rq_id] < rq_minimum and len(selected) < target:
                candidate = next((case for case in ordered
                                  if rq_id in (case.get("research_questions") or [])
                                  and case.get("case_id") not in selected_ids), None)
                if candidate is None:
                    break
                if not add_final_case(candidate):
                    # RQ coverage is a hard analytical requirement; if the
                    # only remaining candidate is in a saturated difficulty
                    # group, retain it and record the diversity trade-off.
                    add_final_case(candidate, respect_group=False)
                selected_rq_counts[rq_id] += 1

        for case in ordered:
            if len(selected) >= target:
                break
            add_final_case(case)
        if len(selected) < min(target, len(final_ranked)):
            diversity_warnings.append(
                "对比案例按 difficulty group 的 40% 软上限无法完全达到目标；保留可用候选并记录失衡。")
            for case in ordered:
                if len(selected) >= target:
                    break
                if case.get("case_id") not in selected_ids:
                    selected.append(case)
                    selected_ids.add(case["case_id"])
        if len(selected) < target:
            diversity_warnings.append(
                f"最终可用对比案例只有 {len(selected)} 个，未用 translation_decision 凑数。")
    else:
        requested_synthetic = int(report_policy.get(
            "synthetic_case_target") or (target if policy == "synthetic_only"
                                          else min(10, max(0, target // 3))))
        synthetic_target = min(
            len(synthetic_pool), target, max(0, requested_synthetic))
        if synthetic_target:
            synthetic_ranked = [x for x in ranked
                                if x.get("case_type") == "synthetic_contrast"]
            for case in synthetic_ranked[:synthetic_target]:
                selected.append(case)
                selected_ids.add(case["case_id"])
        major_groups = [group for group, items in group_pool.items() if len(items) >= 3]
        representative_qa_ids = {"TD-0003", "TD-0047", "TD-0126"}
        for group in sorted(major_groups, key=lambda key: -group_pool[key][0][
                "analytical_value_score"]):
            group_items = list(group_pool[group])
            if group == "质量问题与译文完整性" and any(
                    item.get("case_id") in representative_qa_ids for item in group_items):
                pinned = [item for item in group_items
                          if item.get("case_id") in representative_qa_ids]
                remainder = [item for item in group_items if item not in pinned]
                group_items = pinned + remainder
            for case in group_items[:3]:
                if len(selected) >= target:
                    break
                if case.get("case_id") in selected_ids:
                    continue
                selected.append(case)
                selected_ids.add(case["case_id"])
        quality_group_cap = min(3, max_per_group)
        group_counts = Counter(str(x.get("difficulty_group") or "未分类") for x in selected)
        for case in ranked:
            if len(selected) >= target:
                break
            group = str(case.get("difficulty_group") or "未分类")
            group_cap = quality_group_cap if group == "质量问题与译文完整性" else max_per_group
            if case["case_id"] in selected_ids or group_counts[group] >= group_cap:
                continue
            selected.append(case)
            selected_ids.add(case["case_id"])
            group_counts[group] += 1
        if len(selected) < target:
            diversity_warnings.append(
                "真实证据分布无法在 40% 软上限内达到目标数量；已保留质量排序并记录失衡。")
            for case in sorted(ranked, key=lambda x: (
                    str(x.get("difficulty_group") or "") == "质量问题与译文完整性",
                    -float(x.get("analytical_value_score") or 0))):
                if len(selected) >= target:
                    break
                if case["case_id"] not in selected_ids:
                    selected.append(case)
                    selected_ids.add(case["case_id"])

    rq_counts = Counter(rq for case in selected for rq in case["research_questions"])
    for case in selected:
        if not case["research_questions"]:
            inferred = _infer_case_research_questions(case, research_model)
            if inferred:
                case["research_questions"] = inferred
                case["rq_assignment_source"] = "evidence_group_inference"
                rq_counts.update(inferred)
            else:
                # Do not fabricate a research-question mapping merely to make
                # the distribution look balanced.  The case remains usable as
                # supporting evidence, but cannot carry a major RQ claim.
                case["rq_assignment_source"] = "unassigned_evidence_boundary"
        else:
            case["rq_assignment_source"] = "argument_plan_evidence_binding"

    # Mark a small, auditable set of core cases.  Core cases must be distinct,
    # analytically rich and locally aligned; the rest remain supporting cases.
    core_target = int(report_policy.get("core_case_target") or 10)
    core_target = max(8, min(12, core_target))
    core_codes = ("syntax", "terminology", "rhetoric", "reference", "discourse")
    core_candidates = [x for x in sorted(selected, key=lambda item: (
        -float(item.get("analytical_value_score") or 0),
        int(item.get("segment_index") or 0)))
        if str((x.get("focus") or {}).get("difficulty_code") or "") in core_codes
        and (x.get("semantic_alignment") or {}).get("status") != "misaligned"
        and str(x.get("difficulty_group") or "") != "质量问题与译文完整性"]
    core_ids = set()
    # Ensure each major analytical family has representation where the evidence
    # permits it, then fill the remaining core slots by value.
    for code in core_codes:
        candidate = next((x for x in core_candidates
                          if str((x.get("focus") or {}).get("difficulty_code") or "") == code
                          and x.get("case_id") not in core_ids), None)
        if candidate and len(core_ids) < core_target:
            core_ids.add(candidate.get("case_id"))
    for candidate in core_candidates:
        if len(core_ids) >= core_target:
            break
        core_ids.add(candidate.get("case_id"))
    for case in selected:
        case["argument_role"] = "core" if case.get("case_id") in core_ids else "supporting"

    cases = sorted(selected, key=lambda x: (
        str(x.get("difficulty_group") or ""), -x["analytical_value_score"],
        int(x.get("segment_index") or 0)))
    countable_case_ids = {
        str(x.get("case_id")) for x in cases
        if case_provenance.counts_toward_minimum(x, report_policy)
    }
    countable_case_count = len(countable_case_ids)
    authentic_count = sum(x.get("case_type") == "authentic_revision" for x in cases)
    decision_count = sum(x.get("case_type") == "translation_decision" for x in cases)
    synthetic_count = sum(x.get("case_type") == "synthetic_contrast" for x in cases)
    legacy_synthetic_count = sum(
        x.get("case_type") == "synthetic_contrast"
        and x.get("baseline_origin") == "legacy_analytical_draft" for x in cases)
    newly_generated_synthetic_count = sum(
        x.get("case_type") == "synthetic_contrast"
        and x.get("baseline_origin") == "newly_generated" for x in cases)
    if final_contract:
        for case in cases:
            case_type = str(case.get("case_type") or "")
            case["final_case_eligible"] = case_type in final_case_types
            case["contrast_ready"] = case["final_case_eligible"]
            case["contrast_type"] = {
                "authentic_revision": "authentic",
                "synthetic_contrast": "synthetic",
            }.get(case_type)
    synthetic_target = synthetic_count if final_contract else min(
        len(synthetic_pool), target, max(0, int(report_policy.get(
            "synthetic_case_target") or (target if policy == "synthetic_only"
                                          else min(10, max(0, target // 3))))))
    minimum = min(minimum_authentic_count, preferred_authentic_count)
    if policy == "synthetic_only":
        authentic_status = "not_applicable"
        recommendations = []
        scarcity_disclosure = ""
    elif authentic_count >= preferred_authentic_count:
        authentic_status = "sufficient_revision_cases"
        recommendations: List[str] = []
        scarcity_disclosure = ""
    elif authentic_count >= minimum:
        authentic_status = "two_case_fallback"
        recommendations = [
            "retain_verified_authentic_cases",
            "disclose_revision_evidence_scarcity",
            "do_not_backfill_with_ineligible_cases",
            "use_only_explicitly_labeled_eligible_synthetic_contrasts",
        ]
        scarcity_disclosure = (
            f"现有项目证据仅支持 {authentic_count} 个通过修订资格门禁的真实修订案例；"
            "未用弱证据或无真实修订的片段补足第三个案例。")
    else:
        authentic_status = "insufficient_revision_cases"
        recommendations = [
            "recover_historical_translation_versions_or_revision_records",
            "do_not_backfill_with_ineligible_cases",
            "use_only_explicitly_labeled_eligible_synthetic_contrasts",
        ]
        scarcity_disclosure = (
            f"现有项目证据仅支持 {authentic_count} 个通过修订资格门禁的真实修订案例，"
            f"少于最低要求 {minimum} 个。")
    selection_status = (
        "final_contrast_case_selection" if final_contract and countable_case_count >= target else
        "insufficient_contrast_cases" if final_contract else
        "mixed_case_selection" if sum(bool(x) for x in (
            authentic_count, decision_count, synthetic_count)) > 1 else
        "translation_decision_selection" if decision_count else
        "synthetic_only_selection" if synthetic_count else
        "no_eligible_synthetic_cases" if policy == "synthetic_only" else
        authentic_status)
    portfolio_groups = []
    for group_index, difficulty in enumerate(dict.fromkeys(
            str(x.get("difficulty_group") or "未分类") for x in cases), start=1):
        members = [x for x in cases
                   if str(x.get("difficulty_group") or "未分类") == difficulty]
        strategy = str(members[0].get("strategy_group") or "证据约束的翻译决策")
        group_id = f"G{group_index}"
        for case in members:
            case.update({
                "portfolio_group_id": group_id,
                "difficulty_subsection": f"3.2.{group_index}",
                "strategy_subsection": f"3.3.{group_index}",
                "target_subsection": f"3.3.{group_index}",
            })
        portfolio_groups.append({
            "group_id": group_id,
            "difficulty_group": difficulty,
            "strategy_group": strategy,
            "difficulty_subsection": f"3.2.{group_index}",
            "strategy_subsection": f"3.3.{group_index}",
            "case_ids": [str(x.get("case_id")) for x in members],
            "case_count": len(members),
        })
    artifact = {
        "schema_version": VERSIONS["case_selection_version"],
        "selection_policy": policy,
        "preference_order": (
            "verified authentic revision > validated legacy analytical baseline > "
            "eligible newly generated synthetic contrast > "
            "translation decision as backend candidate only > unsupported reconstructed history"
            if final_contract else
            "verified authentic revision > evidence-rich translation decision > "
            "eligible synthetic contrast > unsupported reconstructed history"),
        "eligibility_rule": "case_type_specific_gate",
        "requested_case_count": limit,
        "report_case_policy": report_policy,
        "candidate_pool_target": int(report_policy.get(
            "candidate_pool_target") or max(limit, len(ranked))),
        "candidate_pool_count": len(revision_pool) + len(backend_decision_pool),
        "ranked_candidate_pool_count": len(ranked),
        "final_candidate_pool_count": len(ranked),
        "translation_decision_candidate_pool_count": len(backend_decision_pool),
        "backend_candidate_pool": [{
            "case_id": x.get("case_id"),
            "case_type": "translation_decision",
            "source_segment_id": x.get("source_segment_id"),
            "score": x.get("score"),
            "rejected_from_final_report": final_contract,
            "rejection_reason": "candidate_evidence_type_not_final_case_type"
            if final_contract else "",
        } for x in backend_decision_pool],
        "ranked_candidate_pool": [{
            "case_id": x.get("case_id"),
            "case_type": x.get("case_type"),
            "segment_id": x.get("segment_id"),
            "analytical_value_score": x.get("analytical_value_score"),
            "difficulty_group": x.get("difficulty_group"),
            "strategy_group": x.get("strategy_group"),
            "focus": x.get("focus"),
        } for x in ranked[:max(limit, int(report_policy.get(
            "candidate_pool_target") or limit))]],
        "preferred_core_case_count": preferred_authentic_count,
        "minimum_core_case_count": minimum,
        "case_count_policy": "authentic_and_synthetic_pools_remain_distinct",
        "synthetic_case_count_policy": report_policy.get(
            "synthetic_count_policy", "counts_toward_minimum"),
        "countable_case_count": countable_case_count,
        "synthetic_supplement_case_count": len(cases) - countable_case_count,
        "eligible_case_count": len(ranked),
        "revision_candidate_pool_count": len(revision_pool),
        "eligible_synthetic_case_count": sum(
            x.get("validation", {}).get("academic_case_eligible")
            for x in (synthetic_artifact or {}).get("items", [])),
        "eligible_legacy_synthetic_case_count": sum(
            x.get("baseline_origin") == "legacy_analytical_draft"
            and x.get("validation", {}).get("academic_case_eligible")
            for x in (synthetic_artifact or {}).get("items", [])),
        "eligible_newly_generated_synthetic_case_count": sum(
            x.get("baseline_origin") == "newly_generated"
            and x.get("validation", {}).get("academic_case_eligible")
            for x in (synthetic_artifact or {}).get("items", [])),
        "synthetic_gate_metrics": dict((synthetic_artifact or {}).get(
            "metrics") or {}),
        "synthetic_case_target": synthetic_target,
        "synthetic_candidate_count": len(synthetic_pool),
        "synthetic_pipeline_status": (synthetic_artifact or {}).get(
            "pipeline_status", "not_run"),
        "selected_case_count": len(cases),
        "final_case_count": len(cases) if final_contract else 0,
        "final_countable_case_count": countable_case_count if final_contract else 0,
        "contrast_case_count": sum(bool(x.get("contrast_ready")) for x in cases)
        if final_contract else 0,
        "contrast_ready_case_count": sum(bool(x.get("contrast_ready")) for x in cases)
        if final_contract else 0,
        "translation_decision_visible_count": decision_count if final_contract else 0,
        "authentic_revision_cases": authentic_count,
        "translation_decision_cases": decision_count,
        "synthetic_contrast_cases": synthetic_count,
        "legacy_synthetic_contrast_cases": legacy_synthetic_count,
        "newly_generated_synthetic_contrast_cases": newly_generated_synthetic_count,
        "authentic_selection_status": authentic_status,
        "selection_status": selection_status,
        "case_coverage_status": (
            "insufficient" if countable_case_count < int(report_policy.get(
                "minimum_cases") or 0) else
            "minimum_with_warning" if countable_case_count < int(report_policy.get(
                "recommended_cases") or len(cases)) else "good"),
        "difficulty_distribution": dict(Counter(
            str(x.get("difficulty_group") or "未分类") for x in cases)),
        "strategy_distribution": dict(Counter(
            str(x.get("strategy_group") or "未分类") for x in cases)),
        "research_question_distribution": dict(rq_counts),
        "required_research_questions": [str(item.get("rq_id")) for item in
                                         research_model.get("research_questions") or []
                                         if item.get("rq_id")],
        "core_case_ids": sorted(str(x) for x in core_ids if x),
        "supporting_case_ids": sorted(str(x.get("case_id")) for x in cases
                                       if x.get("case_id") not in core_ids),
        "argument_role_distribution": dict(Counter(
            str(x.get("argument_role") or "supporting") for x in cases)),
        "diversity_warnings": diversity_warnings,
        "case_portfolio": {
            "candidate_pool_count": len(revision_pool) + len(backend_decision_pool),
            "ranked_candidate_pool_count": len(ranked),
            "selected_case_count": len(cases),
            "groups": portfolio_groups,
            "cases": [{
                "case_id": x.get("case_id"),
                "case_type": x.get("case_type"),
                "case_origin": x.get("case_origin"),
                "text_role": dict(x.get("text_role") or {}),
                "review_status": x.get("review_status", "unreviewed"),
                "baseline_origin": x.get("baseline_origin"),
                "segment_id": x.get("segment_id"),
                "focus": x.get("focus"),
                "difficulty_group": x.get("difficulty_group"),
                "strategy_group": x.get("strategy_group"),
                "research_question_ids": x.get("research_questions"),
                "argument_role": x.get("argument_role"),
                "semantic_alignment": x.get("semantic_alignment"),
                "provenance_confidence": "high" if x.get("canonical_evidence") else "low",
                "analytical_value_score": x.get("analytical_value_score"),
                "final_case_eligible": x.get("final_case_eligible", False),
                "contrast_ready": x.get("contrast_ready", False),
                "contrast_type": x.get("contrast_type"),
            } for x in cases],
        },
        "scarcity_disclosure_required": authentic_status in {
            "two_case_fallback", "insufficient_revision_cases"},
        "synthetic_methodology_disclosure_required": synthetic_count > 0,
        "synthetic_limitation_disclosure_required": synthetic_count > 0,
        "scarcity_disclosure": scarcity_disclosure,
        "scarcity_recommendations": recommendations,
        "rejected_candidates": [*rejected_candidates, *[
            {"case_id": item.get("case_id"),
             "reason": ";".join(item.get("validation", {}).get(
                 "rejected_reasons") or ["synthetic_gate_failed"])}
            for item in (synthetic_artifact or {}).get("items", [])
            if not item.get("validation", {}).get("academic_case_eligible")]],
        "qa_excluded_case_ids": sorted(qa_case_ids & {
            str(x.get("case_id")) for x in backend_decision_pool}),
        "qa_excluded_source_segment_ids": sorted(qa_rejected_source_ids),
        "cases": cases,
    }
    artifact["content_hash"] = academic_evidence.stable_hash(
        {k: v for k, v in artifact.items() if k != "content_hash"})
    return artifact


def final_contrast_portfolio_markdown(selected_cases: Mapping[str, Any]) -> str:
    """Render the pre-writing portfolio review without adding report prose."""
    policy = selected_cases.get("report_case_policy") or {}
    cases = [x for x in selected_cases.get("cases") or []
             if x.get("case_type") in {"authentic_revision", "synthetic_contrast"}
             and x.get("contrast_ready")]
    lines = ["# Final Contrast Case Portfolio", "",
             f"- final_case_count: {len(cases)}",
             f"- minimum_required: {int(policy.get('minimum_cases') or 20)}",
             f"- contrast_case_count: {sum(bool(x.get('contrast_ready')) for x in cases)}",
             f"- translation_decision_visible_count: 0",
             f"- candidate_pool_count: {selected_cases.get('candidate_pool_count', 0)}",
             f"- synthetic_suitability_count: {selected_cases.get('eligible_synthetic_case_count', 0)}",
             f"- synthetic_gate_metrics: {json.dumps(selected_cases.get('synthetic_gate_metrics') or {}, ensure_ascii=False, sort_keys=True)}",
             ""]
    if len(cases) < int(policy.get("minimum_cases") or 20):
        lines.extend(["状态：insufficient_contrast_cases", ""])
    for number, case in enumerate(cases, 1):
        focus = case.get("focus") or {}
        source = (focus.get("source_span") or {}).get("text") or case.get("source_text")
        initial = (focus.get("initial_span") or {}).get("text")
        if case.get("case_type") == "synthetic_contrast":
            initial = initial or (case.get("synthetic_baseline") or {}).get("text")
        target = (focus.get("target_span") or {}).get("text") or \
            case.get("target_contrast_text")
        gate = case.get("synthetic_evidence") or {}
        lines.extend([
            f"## 例[{number}] {case.get('case_id')}", "",
            f"- type: {'authentic' if case.get('case_type') == 'authentic_revision' else 'synthetic'}",
            f"- case_type: {case.get('case_type')}",
            f"- baseline_origin: {case.get('baseline_origin') or 'historical_project_revision'}",
            f"- targeted_issue: {focus.get('issue') or case.get('targeted_issue') or ''}",
            f"- difficulty: {case.get('difficulty_group') or ''}",
            f"- strategy: {case.get('strategy_group') or ''}",
            f"- research_questions: {', '.join(case.get('research_questions') or [])}",
            "", "原文：", str(source or ""), "",
            ("初译：" if case.get("case_type") == "authentic_revision" else "模拟初译："),
            str(initial or ""), "", "改译：", str(target or ""), "",
            "contrast rationale：",
            str(case.get("contrast_rationale") or gate.get(
                "academic_analysis_reason") or case.get("selection_rationale") or "")[:800], "",
            "gate status：",
            f"plausibility={gate.get('baseline_plausibility', 'n/a')}; "
            f"materiality={gate.get('material_difference', 'n/a')}; "
            f"repair_correctness={gate.get('repair_correctness', 'n/a')}; "
            f"academic_analysis_value={gate.get('academic_analysis_value', 'n/a')}", "",
        ])
    rejected = selected_cases.get("rejected_candidates") or []
    if rejected:
        lines.extend(["## Rejected candidates", ""])
        lines.extend(f"- {x.get('case_id')}: {x.get('reason')}" for x in rejected)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _fallback_outline(
    research_model: Dict[str, Any], argument_plan: Dict[str, Any],
    selected_cases: Dict[str, Any],
) -> Dict[str, Any]:
    constraints = research_model.get("report_constraints") or \
        thesis_constraints.build_constraints(research_model)
    required_chapters = thesis_constraints.chapter_index(constraints)
    claims = [c["claim_id"] for c in argument_plan.get("claims", [])]
    rqs = [r["rq_id"] for r in research_model.get("research_questions", [])]
    cases = [c["case_id"] for c in selected_cases.get("cases", [])]
    authentic_cases = [c["case_id"] for c in selected_cases.get("cases", [])
                       if c.get("case_type") == "authentic_revision"]
    synthetic_case_ids = [c["case_id"] for c in selected_cases.get("cases", [])
                          if c.get("case_type") == "synthetic_contrast"]
    total = int(research_model.get("target_words") or 4200)
    case_status = selected_cases.get(
        "authentic_selection_status", selected_cases.get("selection_status"))
    scarcity = str(selected_cases.get("scarcity_disclosure") or "")
    analysis_conclusions = ["理论解释必须表述为作者分析而非真实心理意图"]
    conclusion_limits = ["结论强度不得超过项目与文献证据"]
    if case_status == "two_case_fallback" and scarcity:
        analysis_conclusions.append(scarcity)
        conclusion_limits.append("明确披露核心修订案例只有两个，不补造第三案例")
    if synthetic_case_ids:
        analysis_conclusions.append(
            "合成对比案例必须标为模拟初译/改译，不能写成作者历史修订")
        conclusion_limits.append(
            "合成案例只展示合理失败模式，不证明人类译者中的发生频率")
    template_configured = bool((constraints.get("template") or {}).get("configured"))
    sections = []
    for section_id, chapter in required_chapters.items():
        sections.append({
            "section_id": section_id,
            "title": chapter.get("title") or f"Section {section_id}",
            "role": chapter.get("role") or (
                "generic_section" if template_configured else "case_analysis"),
            "level": chapter.get("level", 1),
            "purpose": chapter.get("purpose") or "仅陈述证据库可支持的内容",
            "required_subsections": chapter.get("required_subsections") or [],
            "research_questions": rqs,
            "claims": claims,
            "cases": cases,
            "case_groups": {"authentic_revision": authentic_cases,
                            "translation_decision": [
                                x for x in cases if x not in authentic_cases
                                and x not in synthetic_case_ids],
                            "synthetic_contrast": synthetic_case_ids},
            "literature_claims": [], "literature_evidence": [], "literature_sources": [],
            "required_statistics": [],
            "target_words": round(total / max(len(required_chapters), 1)),
            "minimum_chars": 200,
            "allowed_conclusions": analysis_conclusions + conclusion_limits,
        })
    if not sections:
        sections = [{
            "section_id": "1",
            "title": "写作提纲",
            "role": "generic_section" if template_configured else "case_analysis",
            "level": 1,
            "purpose": "仅陈述证据库可支持的内容",
            "required_subsections": [],
            "research_questions": rqs,
            "claims": claims,
            "cases": cases,
            "case_groups": {"authentic_revision": authentic_cases,
                            "synthetic_contrast": synthetic_case_ids},
            "literature_claims": [], "literature_evidence": [], "literature_sources": [],
            "required_statistics": [], "target_words": total, "minimum_chars": 200,
            "allowed_conclusions": analysis_conclusions + conclusion_limits,
        }]
    planning_warnings = []
    if template_configured and not any(
            x.get("role") == "case_analysis" for x in sections):
        planning_warnings.append(
            "模板没有明确的 case_analysis 章节；案例不会被静默塞入最后一章，请确认章节角色。")
    return {"sections": sections, "planner_fallback": True,
        "planning_warnings": planning_warnings,
        "report_constraints": constraints,
        "case_count_policy": {
            "status": case_status,
            "preferred": selected_cases.get("preferred_core_case_count", 3),
            "minimum": selected_cases.get("minimum_core_case_count", 2),
            "selected": len(cases),
            "scarcity_disclosure": scarcity,
        }}


def _generic_outline_role(title: Any, supplied_role: Any) -> str:
    """Prefer a recognizable chapter title over an LLM's extra role field."""
    detected = report_template._role_for_title(title)
    if detected != "generic_section":
        return detected
    title_key = re.sub(r"[\s:：.。、()（）\[\]【】_-]+", "", str(title or "").casefold())
    hints = (
        ("project_overview", ("项目与方法", "项目方法", "项目流程")),
        ("conclusion_reflection", ("讨论与结论", "总结与反思", "结论与反思")),
    )
    for role, candidates in hints:
        if any(candidate.casefold() in title_key for candidate in candidates):
            return role
    return str(supplied_role or "generic_section")


def build_academic_outline(
    research_model: Dict[str, Any], argument_plan: Dict[str, Any],
    selected_cases: Dict[str, Any], evidence: Dict[str, Any],
    call_llm: Callable, provider: str, api_key: str, model: str,
    literature_sources_artifact: Optional[Dict[str, Any]] = None,
    literature_evidence_artifact: Optional[Dict[str, Any]] = None,
    literature_claims_artifact: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    constraints = research_model.get("report_constraints") or \
        thesis_constraints.build_constraints(research_model)
    required_chapters = thesis_constraints.chapter_index(constraints)
    system = (
        "你是证据约束型学术提纲规划器。提纲必须服务研究问题，并且只能引用给定 claim、case、"
        "literature claim、literature evidence 和 statistic id。只输出 JSON："
        "{\"sections\":[{\"section_id\":\"1\","
        "\"title\":\"...\",\"purpose\":\"...\",\"research_questions\":[\"RQ1\"],"
        "\"claims\":[\"C1\"],\"cases\":[\"seg-...\"],"
        "\"literature_claims\":[\"LC-001\"],"
        "\"literature_evidence\":[\"LE-...\"],"
        "\"required_statistics\":[\"total_segments\"],\"target_words\":900,"
        "\"minimum_chars\":300,\"allowed_conclusions\":[\"...\"]}]}。"
        "仅在 report_constraints 提供结构时遵循其 section_id、标题、功能和"
        "required_subsections；未提供结构时不得自行补充固定模板。各 section 只使用"
        "其写作包内的证据，不得在结论部分引入未在前文建立的新案例证据。"
        "若 report_constraints.template.configured=true，输入的 chapters 是唯一合法的"
        "章节集合；不得新增、删除、改名或重排 section_id/title，只为这些已有章节分配"
        "purpose、research_questions、claims、cases、literature 和 statistics。chapter role"
        "决定 case_analysis/conclusion 等职责。"
        "案例数量以 selected_cases.case_count_policy 为准；two_case_fallback 是合格的"
        "双案例结构，不得虚构或要求第三个案例，并须在案例分析或结论中披露证据稀缺。"
        "若存在 synthetic_contrast，必须与 authentic_revision 分组，并规划方法说明和局限；"
        "不得把模拟初译写成历史初译。"
    )
    payload = {
        "research_model": research_model,
        "argument_plan": argument_plan,
        "selected_cases": selected_cases,
        "literature_sources": [
            {k: v for k, v in x.items() if k != "content_blocks"}
            for x in (literature_sources_artifact or {}).get("sources", [])],
        "literature_claims": (literature_claims_artifact or {}).get("items", []),
        "literature_evidence": (literature_evidence_artifact or {}).get("items", []),
        "available_statistics": list(evidence.get("project_evidence", {}).get("statistics", {})),
        "report_constraints": constraints,
    }
    raw = _call_json(call_llm, provider, api_key, model, system,
                     json.dumps(payload, ensure_ascii=False)) or _fallback_outline(
                         research_model, argument_plan, selected_cases)
    valid_claims = {x["claim_id"] for x in argument_plan.get("claims", [])}
    valid_cases = {x["case_id"] for x in selected_cases.get("cases", [])}
    valid_rqs = {x["rq_id"] for x in research_model.get("research_questions", [])}
    lit_sources = literature_evidence.source_index(literature_sources_artifact or {})
    lit_evidence = literature_evidence.evidence_index(literature_evidence_artifact or {})
    lit_claims = literature_evidence.claim_index(literature_claims_artifact or {})
    valid_stats = academic_validator.statistic_keys(
        evidence.get("project_evidence", {}).get("statistics", {}))
    raw_items = [x for x in raw.get("sections") or [] if isinstance(x, dict)]
    raw_by_id = {str(x.get("section_id")): x for x in raw_items
                 if x.get("section_id") is not None}

    def normalize_section(section_id, chapter, item):
        item = item or {}
        section_lit_claims = [str(x) for x in item.get("literature_claims") or []
                              if str(x) in lit_claims]
        allowed_evidence = {
            evidence_id for claim_id in section_lit_claims
            for evidence_id in lit_claims[claim_id].get("supporting_evidence_ids") or []
        }
        section_lit_evidence = [
            str(x) for x in item.get("literature_evidence") or []
            if str(x) in lit_evidence and str(x) in allowed_evidence
        ]
        section_sources = sorted({
            lit_evidence[x]["source_id"] for x in section_lit_evidence
            if lit_evidence[x].get("source_id") in lit_sources
        })
        role = chapter.get("role") or str(item.get("role") or "generic_section")
        default_statistics = []
        if role == "project_overview":
            default_statistics = [x for x in (
                "total_segments", "translated_segments", "reviewed_segments",
                "meaningfully_revised_segments", "tm_reuse_count") if x in valid_stats]
        return {
            "section_id": section_id,
            # Template title/order/level/role are authoritative.  The model
            # only fills the evidence assignment fields below.
            "title": chapter.get("title") or str(
                item.get("title") or f"章节 {section_id}").strip(),
            "role": role,
            "level": chapter.get("level", 1),
            "purpose": chapter.get("purpose") or str(item.get("purpose") or "").strip(),
            "required_subsections": chapter.get("required_subsections", []),
            "research_questions": [str(x) for x in item.get("research_questions") or []
                                   if str(x) in valid_rqs],
            "claims": [str(x) for x in item.get("claims") or [] if str(x) in valid_claims],
            "cases": [str(x) for x in item.get("cases") or [] if str(x) in valid_cases],
            "literature_claims": section_lit_claims if section_lit_evidence else [],
            "literature_evidence": section_lit_evidence,
            "literature_sources": section_sources,
            "required_statistics": list(dict.fromkeys([
                *default_statistics,
                *[str(x) for x in item.get("required_statistics") or []
                  if str(x) in valid_stats],
            ])),
            "target_words": max(200, int(item.get("target_words") or 700)),
            "minimum_chars": max(100, int(item.get("minimum_chars") or 200)),
            "allowed_conclusions": _as_list(item.get("allowed_conclusions")),
        }

    if required_chapters:
        # Canonical construction prevents an LLM response from deleting or
        # renaming a template chapter, even when it returns fewer sections.
        sections = [normalize_section(section_id, chapter, raw_by_id.get(section_id))
                    for section_id, chapter in required_chapters.items()]
        fallback = bool(raw.get("planner_fallback"))
    else:
        sections = [normalize_section(
            str(item.get("section_id") or index),
            {"title": str(item.get("title") or f"章节 {index}"),
             "role": _generic_outline_role(
                 item.get("title"), item.get("role")),
             "level": 1,
             "purpose": str(item.get("purpose") or ""),
             "required_subsections": []}, item)
                    for index, item in enumerate(raw_items, start=1)]
        if not sections:
            fallback_outline = _fallback_outline(
                research_model, argument_plan, selected_cases)
            sections = fallback_outline["sections"]
            fallback = True
        else:
            fallback = bool(raw.get("planner_fallback"))

    # Deterministically route evidence by explicit chapter role.  No section
    # position is allowed to imply analysis or conclusion semantics.
    section_by_id = {x["section_id"]: x for x in sections}
    case_sections = [x for x in sections if x.get("role") == "case_analysis"]
    conclusion_sections = [x for x in sections if x.get("role") == "conclusion_reflection"]
    intro_sections = [x for x in sections if x.get("role") == "introduction"]
    template_configured = bool((constraints.get("template") or {}).get("configured"))
    planning_warnings = list(raw.get("planning_warnings") or [])
    if (research_model.get("template_hash") or
            (constraints.get("template") or {}).get("configured")) and not case_sections:
        planning_warnings.append(
            "模板没有明确的 case_analysis 章节；案例未被自动路由，请确认章节角色。")
    for section in sections:
        section["cases"] = []
        section["research_questions"] = list(dict.fromkeys(section["research_questions"]))
    if intro_sections and valid_rqs:
        intro_sections[0]["research_questions"] = sorted(valid_rqs)
    for section in [*case_sections, *conclusion_sections]:
        section["research_questions"] = sorted(valid_rqs)

    # Bind claims to model-planned sections first; otherwise choose an
    # explicit role, never the last section by accident.
    claims_by_id = {x["claim_id"]: x for x in argument_plan.get("claims", [])}
    for section in sections:
        section["claims"] = list(dict.fromkeys(section["claims"]))
    for claim_id in valid_claims:
        if any(claim_id in x["claims"] for x in sections):
            continue
        claim = claims_by_id.get(claim_id) or {}
        planned = [] if template_configured else [
            section_by_id.get(str(x)) for x in claim.get("planned_sections") or []]
        target = next((x for x in planned if x), None)
        target = target or (case_sections[0] if case_sections else
                            (conclusion_sections[0] if conclusion_sections else sections[0]))
        target["claims"].append(claim_id)

    # Bound per-section case load and guarantee every selected case has a
    # section only when the template explicitly allows case analysis.
    case_claims: Dict[str, set] = {}
    for claim in argument_plan.get("claims", []):
        for case_id in claim.get("project_evidence") or []:
            case_claims.setdefault(str(case_id), set()).add(claim["claim_id"])
    selected_ids = {str(x.get("case_id")) for x in selected_cases.get("cases", [])}
    selected_by_id = {str(x.get("case_id")): x
                      for x in selected_cases.get("cases", [])}
    for section in sections:
        section["cases"] = section["cases"][:max(4, len(selected_ids))]
    assigned = {case_id for section in sections for case_id in section["cases"]}
    for case_id in sorted(selected_ids - assigned):
        if not template_configured and case_id not in case_claims and \
                selected_by_id.get(case_id, {}).get("case_type") != "synthetic_contrast":
            # Zone-coverage candidates without a claim binding do not need a
            # section; forcing them in would create impossible validation.
            continue
        if not case_sections:
            planning_warnings.append(
                f"案例 {case_id} 没有可用的 case_analysis 章节，未强行写入其他章节。")
            continue
        best = max(
            case_sections, key=lambda x: len(
                set(x["claims"]) & (case_claims.get(case_id) or set())))
        best["cases"].append(case_id)
    for section in sections:
        for claim_id in section["claims"]:
            global_claim = claims_by_id.get(claim_id) or {}
            for literature_claim_id in global_claim.get("literature_claims") or []:
                if literature_claim_id in lit_claims and literature_claim_id not in section[
                        "literature_claims"]:
                    section["literature_claims"].append(literature_claim_id)
            for evidence_id in global_claim.get("literature_evidence") or []:
                if evidence_id in lit_evidence and evidence_id not in section[
                        "literature_evidence"]:
                    section["literature_evidence"].append(evidence_id)
        section["literature_sources"] = sorted({
            lit_evidence[x]["source_id"] for x in section["literature_evidence"]
            if x in lit_evidence and lit_evidence[x].get("source_id") in lit_sources
        })
        section["case_groups"] = {
            "authentic_revision": [case_id for case_id in section["cases"]
                                     if selected_by_id.get(case_id, {}).get(
                                         "case_type") == "authentic_revision"],
            "translation_decision": [case_id for case_id in section["cases"]
                                      if selected_by_id.get(case_id, {}).get(
                                          "case_type") == "translation_decision"],
            "synthetic_contrast": [case_id for case_id in section["cases"]
                                    if selected_by_id.get(case_id, {}).get(
                                        "case_type") == "synthetic_contrast"],
        }
    for section in conclusion_sections:
        section["claims"] = sorted(valid_claims)
    artifact = {
        "schema_version": VERSIONS["outline_version"],
        "report_constraints": constraints,
        "template_hash": (constraints.get("template") or {}).get("template_hash"),
        "template_id": (constraints.get("template") or {}).get("template_id"),
        "sections": sections,
        "planner_fallback": fallback,
        "planning_warnings": sorted(set(planning_warnings)),
        "case_count_policy": {
            "status": selected_cases.get(
                "authentic_selection_status", selected_cases.get("selection_status")),
            "preferred": selected_cases.get("preferred_core_case_count", 3),
            "minimum": selected_cases.get("minimum_core_case_count", 2),
            "selected": len(selected_cases.get("cases", [])),
            "scarcity_disclosure": selected_cases.get("scarcity_disclosure", ""),
        },
        "case_groups": {
            "authentic_revision": [case_id for case_id, item in selected_by_id.items()
                                     if item.get("case_type") == "authentic_revision"],
            "translation_decision": [case_id for case_id, item in selected_by_id.items()
                                     if item.get("case_type") == "translation_decision"],
            "synthetic_contrast": [case_id for case_id, item in selected_by_id.items()
                                    if item.get("case_type") == "synthetic_contrast"],
        },
    }
    artifact["content_hash"] = academic_evidence.stable_hash(
        {k: v for k, v in artifact.items() if k != "content_hash"})
    return artifact


def _case_assignment_for_plan(
    case_id: str, plan: Mapping[str, Any], selected_case: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    selected_case = selected_case or {}
    if selected_case.get("target_subsection"):
        return {
            "case_id": case_id,
            "difficulty_group": selected_case.get("difficulty_group"),
            "strategy_group": selected_case.get("strategy_group"),
            "difficulty_subsection": selected_case.get("difficulty_subsection"),
            "strategy_subsection": selected_case.get("strategy_subsection"),
            "target_subsection": selected_case.get("target_subsection"),
            "group_title": selected_case.get("strategy_group"),
            "research_question_ids": list(selected_case.get("research_questions") or []),
            "argument_role": selected_case.get("argument_role", "supporting"),
            "semantic_alignment": selected_case.get("semantic_alignment") or {},
            "required": True,
        }
    problem_type = str((plan.get("problem") or {}).get("type") or "other")
    if problem_type in {
            "terminology", "reference_resolution", "lexical_polysemy",
            "cultural_reference"}:
        group, title = "1", "术语、专名与文化指称"
    elif problem_type in {
            "syntactic_ambiguity", "logical_relation", "information_structure"}:
        group, title = "2", "句法与信息结构"
    elif problem_type in {
            "metaphor", "pragmatic_implication", "register", "voice", "rhythm",
            "narrative_perspective"}:
        group, title = "3", "修辞、语用与语域"
    else:
        group, title = "4", "连贯性与质量控制"
    return {
        "case_id": case_id,
        "difficulty_group": f"3.2.{group}",
        "strategy_group": f"3.3.{group}",
        "target_subsection": f"3.3.{group}",
        "group_title": title,
        "argument_role": selected_case.get("argument_role", "supporting"),
        "semantic_alignment": selected_case.get("semantic_alignment") or {},
        "required": True,
    }


def _scope_case_assignment(
    assignment: Mapping[str, Any], section: Mapping[str, Any],
) -> Dict[str, Any]:
    """Rebase a portfolio group onto the actual case-analysis chapter."""
    scoped = dict(assignment)
    value = str(scoped.get("target_subsection") or "")
    parts = value.split(".")
    if len(parts) < 3 or not parts[-1].isdigit():
        return scoped
    problem_root, solution_root = thesis_constraints.case_subsection_roots(section)
    suffix = parts[-1]
    scoped.update(
        difficulty_subsection=f"{problem_root}.{suffix}",
        strategy_subsection=f"{solution_root}.{suffix}",
        target_subsection=f"{solution_root}.{suffix}",
    )
    return scoped


def _section_packet(
    section: Dict[str, Any], research_model: Dict[str, Any],
    argument_plan: Dict[str, Any], selected_cases: Dict[str, Any],
    evidence: Dict[str, Any], outline: Dict[str, Any],
    prior_summaries: List[Dict[str, str]],
    literature_sources_artifact: Optional[Dict[str, Any]] = None,
    literature_evidence_artifact: Optional[Dict[str, Any]] = None,
    literature_claims_artifact: Optional[Dict[str, Any]] = None,
    case_analysis_plans: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    claims = {x["claim_id"]: x for x in argument_plan.get("claims", [])}
    cases = {x["case_id"]: x for x in selected_cases.get("cases", [])}
    segments = academic_evidence.segment_index(evidence)
    lit_sources = literature_evidence.source_index(literature_sources_artifact or {})
    lit_evidence = literature_evidence.evidence_index(literature_evidence_artifact or {})
    lit_claims = literature_evidence.claim_index(literature_claims_artifact or {})
    plans = case_analysis.plan_index(case_analysis_plans or {})
    required_case_ids = [str(x) for x in section.get("cases", []) if str(x) in cases]

    case_assignments = [
        _scope_case_assignment(_case_assignment_for_plan(
            case_id, plans.get(case_id) or {}, cases.get(case_id) or {}), section)
        for case_id in required_case_ids]
    case_term_ids = set()
    for case_id in section.get("cases", []):
        selected = cases.get(case_id) or {}
        source_id = case_id if selected.get("case_type") == "authentic_revision" \
            else selected.get("source_segment_id")
        case_term_ids.update((segments.get(str(source_id)) or {}).get(
            "process_evidence", {}).get("injected_glossary_entry_ids", []))
    all_terms = evidence.get("project_evidence", {}).get("glossary", [])
    if "术语" in (section.get("title", "") + section.get("purpose", "")):
        terminology = all_terms[:30]
    else:
        terminology = [x for x in all_terms if x.get("id") in case_term_ids]
    available_segment_ids = list(segments)
    if len(available_segment_ids) > 40:
        available_segment_ids = available_segment_ids[:39] + [available_segment_ids[-1]]
    available_evidence = [{
        "segment_id": segment_id,
        "coverage_zone": (segments.get(segment_id) or {}).get("coverage_zone"),
        "case_role": (segments.get(segment_id) or {}).get("case_role"),
    } for segment_id in available_segment_ids]
    canonical_stats = evidence.get("project_evidence", {}).get("statistics", {})
    statistics = {
        x: academic_validator.resolve_statistic(canonical_stats, x)[1]
        for x in section.get("required_statistics", [])
        if academic_validator.resolve_statistic(canonical_stats, x)[0]
    }
    statistics.update(academic_validator.case_statistic_overrides(
        section, selected_cases, evidence))
    return {
        "research_model": research_model,
        "global_outline": [
            {k: x.get(k) for k in ("section_id", "title", "purpose",
                                    "research_questions", "claims", "cases",
                                    "literature_claims", "literature_evidence")}
            for x in outline.get("sections", [])
        ],
        "current_section": section,
        "claims": [claims[x] for x in section.get("claims", []) if x in claims],
        # This is an index of available evidence, not implicit case selection;
        # only the explicit ``cases`` list may be used as a case in the report.
        "available_segment_ids": available_segment_ids,
        "available_evidence": available_evidence,
        "cases": [{
            **{key: value for key, value in cases[x].items()
               if key != "canonical_evidence"},
            "evidence": {
                "source": ((cases[x].get("focus") or {}).get("source_span") or {}).get(
                    "text"),
                "initial_target": ((cases[x].get("focus") or {}).get(
                    "initial_span") or {}).get("text")
                if cases[x].get("case_type") != "translation_decision" else None,
                "final_target": ((cases[x].get("focus") or {}).get(
                    "target_span") or {}).get("text"),
                "focus": cases[x].get("focus"),
            },
        } for x in section.get("cases", []) if x in cases],
        "required_case_ids": required_case_ids,
        "must_render_all_cases": bool(required_case_ids),
        "case_assignments": case_assignments,
        "case_analyses": [{
            **plans[x],
            "analysis_contract_text": case_analysis.render_analysis_contract(plans[x]),
            "contract_completion": case_analysis.contract_completion(plans[x]),
        } for x in section.get("cases", []) if x in plans],
        "literature_sources": [
            {k: v for k, v in lit_sources[x].items() if k != "content_blocks"}
            for x in section.get("literature_sources", []) if x in lit_sources
            and lit_sources[x].get("citation_allowed")],
        "literature_claims": [lit_claims[x] for x in section.get(
            "literature_claims", []) if x in lit_claims],
        "literature_evidence": [lit_evidence[x] for x in section.get(
            "literature_evidence", []) if x in lit_evidence],
        "statistics": statistics,
        "workflow_evidence": evidence.get("project_evidence", {}).get("workflow", {})
        if section.get("role") == "project_overview" else {},
        "terminology_decisions": terminology,
        "prior_section_summaries": prior_summaries,
        "writing_constraints": {
            "report_constraints": research_model.get(
                "report_constraints") or outline.get(
                    "report_constraints") or thesis_constraints.build_constraints(
                        research_model),
            "required_subsections": section.get("required_subsections") or [],
            "claim_marker": "<!--claim:C1-->",
            "rq_marker": "<!--rq:RQ1-->",
            "source_quote": "> [SOURCE seg-...]: exact source",
            "initial_quote": "> [INITIAL seg-...]: exact initial target",
            "target_quote": "> [TARGET seg-...]: exact final target",
            "synthetic_source_quote": "> [SYNTHETIC_SOURCE SC-...]: exact source",
            "synthetic_baseline_quote": "> [SIMULATED SC-...]: exact simulated baseline",
            "synthetic_target_quote": "> [OPTIMIZED SC-...]: exact current project target",
            "project_statistic": "{{STAT:metric_name}}",
            "terminology_decision": "{{TERM:entry_id}}",
            "formal_citation": "[@source_id]",
            "literature_quote": "> [LITERATURE LE-...]: exact evidence text",
            "literature_claim_marker": "<!--lit-claim:LC-001-->",
            "literature_evidence_marker": "<!--lit-evidence:LE-...-->",
            "analysis_contract": "按 case_analyses 中的 analysis_contract_text 逐项落实",
            "required_case_ids": required_case_ids,
            "must_render_all_cases": bool(required_case_ids),
            "case_assignments": case_assignments,
            "evidence_level_policy": (
                "authentic_revision 必须有真实初译→终译；synthetic_contrast 必须通过"
                "独立合成资格门禁；两者不得互相转换"),
            "case_count_policy": {
                **dict(selected_cases.get("report_case_policy") or {}),
                "status": selected_cases.get(
                    "authentic_selection_status", selected_cases.get("selection_status")),
                "preferred": selected_cases.get("preferred_core_case_count", 3),
                "minimum": selected_cases.get("minimum_core_case_count", 2),
                "selected": len(selected_cases.get("cases", [])),
                "scarcity_disclosure": selected_cases.get("scarcity_disclosure", ""),
                "required_marker": "<!--case-count-policy:two_case_fallback-->"
                if selected_cases.get(
                    "authentic_selection_status", selected_cases.get(
                        "selection_status")) == "two_case_fallback" else "",
            },
            "synthetic_case_policy": {
                "present": bool(selected_cases.get("synthetic_contrast_cases")),
                "methodology_marker": "<!--synthetic-methodology-->",
                "methodology_disclosure": (
                    "合成对比案例以真实源文和当前正式译文为基础，模拟初译为分析阶段构造，"
                    "不代表作者的历史翻译；其合理性、实质性差异与修复正确性分别经过检查。"),
                "limitation_marker": "<!--synthetic-limitation-->",
                "limitation_disclosure": (
                    "合成案例只能展示合理的翻译失败模式，不能证明此类错误在人类译者中的"
                    "实际发生频率。"),
            },
        },
    }


def _writer_heading_key(value: Any) -> str:
    value = str(value or "").strip()
    value = re.sub(r"^第\s*[一二三四五六七八九十百千万]+\s*章\s*", "", value)
    value = re.sub(r"^[一二三四五六七八九十]+[、.．]\s*", "", value)
    value = re.sub(r"^\d+(?:\.\d+)*[.)、．]?\s+", "", value).strip()
    return re.sub(r"[\s:：.。、()（）\[\]【】_-]+", "", value.casefold())


def _ensure_section_contract(text: str, section: Mapping[str, Any]) -> str:
    """Keep required template headings visible even when the model omits them."""
    required = list(section.get("required_subsections") or [])
    is_case_section = str(section.get("role") or "") == "case_analysis"
    is_case_unit = is_case_section and bool(section.get("writing_unit_id"))
    case_roots = thesis_constraints.case_subsection_roots(section) \
        if is_case_section else ()
    lines = str(text or "").splitlines()
    normalized = []
    seen = set()
    section_key = _writer_heading_key(section.get("title"))
    substantive_started = False
    for line in lines:
        stripped = line.strip()
        if not substantive_started and stripped and not stripped.startswith("<!--") \
                and _writer_heading_key(stripped) == section_key:
            # The assembler supplies the canonical chapter heading.
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", stripped)
        if not match:
            normalized.append(line)
            if stripped and not stripped.startswith("<!--"):
                substantive_started = True
            continue
        title = match.group(2).strip()
        if _writer_heading_key(title) == section_key:
            # _compose_report supplies the authoritative chapter heading.
            continue
        matched = next((item for item in required
                        if _writer_heading_key(item.get("title")) ==
                        _writer_heading_key(title)), None)
        if matched:
            heading_id = str(matched.get("heading_id") or "").strip()
            prefix = str(matched.get("markdown_prefix") or (
                "#" * (int(matched.get("level") or 2) + 1)))
            normalized.append(f"{prefix} {heading_id} {matched.get('title')}")
            seen.add(_writer_heading_key(matched.get("title")))
        else:
            numeric = re.match(r"^(\d+(?:\.\d+)*)(?:[.)、．])?\s+(.+)$", title)
            heading_id = numeric.group(1) if numeric else ""
            dynamic_allowed = any(
                item.get("allows_dynamic_children") and heading_id.startswith(
                    str(item.get("heading_id") or "") + ".")
                for item in required) or any(
                    heading_id.startswith(root + ".") for root in case_roots)
            chapter_child = heading_id.startswith(
                str(section.get("section_id") or "") + ".")
            if numeric and chapter_child and (dynamic_allowed or not required):
                depth = heading_id.count(".") + 2
                normalized.append(f"{'#' * min(6, depth)} {heading_id} {numeric.group(2)}")
            else:
                # Preserve useful prose labels without allowing an LLM to add
                # structural headings outside the template contract.
                normalized.append(f"**{title}**")
        substantive_started = True
    missing = [item for item in required
               if _writer_heading_key(item.get("title")) not in seen]
    if missing:
        normalized.append("")
        normalized.append("当前项目证据不足以自动补写以下模板要求的小节；请人工补充。")
        for item in missing:
            heading_id = str(item.get("heading_id") or "").strip()
            prefix = str(item.get("markdown_prefix") or (
                "#" * (int(item.get("level") or 2) + 1)))
            normalized.extend(["", f"{prefix} {heading_id} {item.get('title')}",
                               "当前项目证据不足以对此作进一步实证分析，需人工补充。"])
    text = "\n".join(normalized).strip()
    if is_case_section:
        problem_root, solution_root = case_roots
        if section.get("cases") and not is_case_unit:
            for root, title in ((problem_root, "翻译难点"),
                                (solution_root, "翻译策略与解决方案")):
                if not re.search(rf"^#{{3,6}}\s+{re.escape(root)}(?:\s|$)", text,
                                 re.MULTILINE):
                    text += f"\n\n### {root} {title}"
        problem_ids = set(re.findall(
            rf"^#{{4,6}}\s+{re.escape(problem_root)}\.(\d+)\b", text,
            re.MULTILINE))
        solution_ids = set(re.findall(
            rf"^#{{4,6}}\s+{re.escape(solution_root)}\.(\d+)\b", text,
            re.MULTILINE))
        if not is_case_unit:
            for root, suffixes in ((problem_root, problem_ids - solution_ids),
                                   (solution_root, solution_ids - problem_ids)):
                for suffix in suffixes:
                    text = re.sub(
                        rf"^#{{4,6}}\s+({re.escape(root)}\.{suffix}\s+.+)$",
                        r"**\1**", text, flags=re.MULTILINE)
    missing_rqs = [str(rq) for rq in section.get("research_questions") or []
                   if f"<!--rq:{rq}-->" not in text]
    if missing_rqs:
        text += "\n" + "".join(f"<!--rq:{rq}-->" for rq in missing_rqs)
    return text.strip()


def _write_section(
    packet: Dict[str, Any], call_llm: Callable, provider: str, api_key: str,
    model: str, repair_issues: Optional[List[Dict[str, Any]]] = None,
    existing: str = "",
) -> str:
    repair = bool(repair_issues)
    system = (
        "你是证据约束型学术写作者。根据论点计划写当前 section，不得新增主要论点、"
        "项目事实或文献。authentic_revision 必须逐字使用 SOURCE/INITIAL/TARGET；"
        "translation_decision 只使用 SOURCE/TARGET，并明确初译与终译一致、用于分析"
        "可观察的翻译决策，绝不能写成错误后改译；"
        "synthetic_contrast 必须逐字使用 SYNTHETIC_SOURCE/SIMULATED/OPTIMIZED，"
        "并明确称为‘模拟初译’和‘改译’；改译字段消费当前正式译文，不是新生成的历史终稿。"
        "项目数字只能用 packet.statistics 中已提供的 "
        "{{STAT:key}}；缺失指标不得猜测，也不要输出对应 token。正式文献只能用 [@source_id]；"
        "文献直接引语必须逐字复制 literature_evidence 并使用 LITERATURE 格式；文献释义必须"
        "同时保留 lit-claim 与 lit-evidence marker，并引用对应 source_id；"
        "项目术语决策用 {{TERM:entry_id}}。每个落实的 claim 和 RQ 分别保留 HTML marker。"
        "理论解释必须写成作者分析，例如‘从结果看可解释为’，不得冒充译者真实意图。"
        "证据等级规则：当前源语—目标语对照通常只支持文本层面的‘显示、呈现、保持、"
        "对应’；‘证明、确保、显著、有效提升、降低认知负荷、不会造成理解障碍、通行译法、"
        "译者经过权衡’分别需要文献、读者反馈或真实过程记录，packet 未提供时必须删除或降级。"
        "无文献证据时，不得从模型记忆补作者、年份、书名或理论命题。内部 ID 只能存在于"
        "规定的 quote/HTML marker，普通论文句子不得出现 segment id、artifact、finding id、"
        "evidence registry 等系统语言。只输出章节正文。"
    )
    constraints = (packet.get("writing_constraints") or {}).get(
        "report_constraints") or {}
    language = (constraints.get("body_language") or {}).get("language")
    if language == "zh-CN":
        system += (
            f" 当前报告正文语言配置为 {language}。本节的论述、分析、标题和过渡语应遵循该配置；"
            "逐字引语、术语、专名和参考文献信息可保留原文。"
        )
    required_subsections = (packet.get("writing_constraints") or {}).get(
        "required_subsections") or []
    if required_subsections:
        system += (
            " 当前章必须按 required_subsections 的顺序使用可见标题，并逐项采用其中的"
            "markdown_prefix，格式为‘markdown_prefix 编号 标题’，不得省略、改名或压平层级。"
        )
    role = str((packet.get("current_section") or {}).get("role") or "")
    if role == "introduction":
        system += (
            " 本章必须在 1.1 只写真实项目背景与意义；1.2 原样提出 packet 中 2—3 个研究问题；"
            "1.3 必须准确说明当前四章结构。不得虚构行业数据、研究空白、目标读者反应或"
            "文献依赖的理论共识；没有文献时将其写成本文研究范围与实践动机。")
    elif role == "project_overview":
        system += (
            " 本章只使用 workflow_evidence、statistics 与 project_metadata。2.1 说明原文件、"
            "方向、范围、片段数、文本类型和交付记录；2.2.1/2.2.2/2.2.3 分别写真实译前、"
            "译中、译后流程。不得虚构客户、团队、CATTI、Trados 或客户反馈。"
            "区分系统检查、人工操作、自动 QA 与人工修订；reviewed_segments 是系统审查记录，"
            "不能改写成‘由审校人员审校’。TM reuse=0 只能写‘项目记录中未观察到 TM 复用’，"
            "不能推出机器翻译或 LLM 未使用、完全依赖人工或效率变化；当前 delivery_status 为 draft"
            "时只能写‘形成当前工作稿/记录了问题’，不能声称质量已经确保达标。")
    elif role == "case_analysis":
        current_section = packet.get("current_section") or {}
        section_id = str(current_section.get("section_id") or "3")
        problem_root, solution_root = thesis_constraints.case_subsection_roots(
            current_section)
        structure = (
            f"本章必须保持 {section_id}.1 源语类型与特征、{problem_root} 翻译难点、"
            f"{solution_root} 翻译策略与解决方案。"
            if not required_subsections else
            "本章必须保持 required_subsections 规定的案例分析结构。")
        system += (
            f" {structure}"
            f"{problem_root}.x 与 {solution_root}.x 必须按 packet.case_assignments 中由当前项目证据形成的组别"
            f"同号一一对应，不能套用固定分类；每个 {solution_root}.x 先说明具体难点与策略，再用多个"
            "不同子现象的案例验证，最后写本组小结。案例只写模板允许的原文、初译/译文、"
            "改译（仅真实修订）、可选注释和分析。翻译难点、策略、译法解释、效果与有界"
            "结论必须自然融入一个连续的‘分析’段落，不能显示为案例字段或小标题。案例正文"
            "不要显示内部 ID。selected cases 中每个"
            "case_id 只能作为一个编号例证出现一次，不得把同一段落按不同维度包装成两个案例，"
            "也不得新增未选择的案例。每个案例只能逐字使用 packet.cases.evidence 中的 focus"
            "文本，不能扩展成完整 segment。translation_decision 只能称为翻译决策案例。finding 数量只"
            "表示检测记录，不等于发生同等数量的实际改译；TM reuse=0 时不得写 TM 污染、"
            "机器翻译未使用或全程人工。真实修订若仅删除英文括号释义，只能支持术语格式与"
            "阅读连续性分析，不能证明句法、逻辑衔接或信息结构发生修订。")
        final_policy = (packet.get("writing_constraints") or {}).get(
            "case_count_policy") or {}
        if final_policy.get("report_stage") == "final_report" \
                and final_policy.get("contrast_required"):
            system += (
                " 当前为 final_report：正式案例只允许 authentic_revision 或 "
                "synthetic_contrast，translation_decision 不得进入可见案例。每个正式案例"
                "必须同时呈现原文、初译/模拟初译、改译和分析；分析必须具体解释 baseline/真实"
                "初译为何合理、哪里不足、改译改变了什么、为何适合当前语境、体现何种策略以及"
                "结论边界。Chapter 3 在第一次案例前只统一说明一次 synthetic 方法，不能在每例"
                "重复方法段落；synthetic 案例可见标签必须是‘模拟初译’，不得只写‘初译’。")
        required_case_ids = packet.get("required_case_ids") or []
        if required_case_ids:
            system += (
                " packet.required_case_ids 中的案例全部是 required，不是可选上下文；必须按"
                "packet.case_assignments 将每个案例各写成一个独立可见例证，恰好一次，并在"
                "例证标题下一行保留 <!--case:CASE_ID-->。例证编号可暂用例[1]，最终 assembly"
                "会统一编号。authentic_revision 使用原文、初译、改译、可选注释、分析；"
                "synthetic_contrast 使用原文、模拟初译、改译、可选注释、分析；"
                "translation_decision 只使用原文、译文、可选注释、分析，不得使用"
                "‘初译’‘修改后’‘改译为’等历史修订措辞。每个案例必须服务其"
                "research_question_ids，不能让某个研究问题只依赖一个例证。普通案例不得"
                "显示‘翻译难点、译法分析、翻译效果、有界结论、证据边界、provenance、"
                "case type’等内部标签；注释只用于必要的文化、专名或术语来源说明。"
                "标记为 core 的案例承担 RQ 论证，须比 supporting 案例展开更多具体机制；supporting"
                "案例用于补充现象，不得被写成独立的一般规律。source/target focus 若为"
                "review_required，只能使用克制措辞；misaligned 案例不得进入 core。"
            )
    elif role == "conclusion_reflection":
        system += (
            " 本章必须逐项回应研究问题，总结已建立的策略、实践经验、真实局限和改进方向；"
            "每个 RQ 的回答必须回指多个已建立的 core cases 及其所属小节，不得把唯一真实修订"
            "案例扩展成普遍结论；不得首次引入任何案例或新证据。明确说明没有读者测试、"
            "文献或完整修订历史时的限制。")
    count_policy = (packet.get("writing_constraints") or {}).get(
        "case_count_policy") or {}
    if count_policy.get("status") == "two_case_fallback":
        system += (
            " 本项目采用 two_case_fallback：两个真实修订案例已满足最低核心案例结构。"
            "不得要求、暗示或补写第三案例。当前章节若承担案例分析或结论功能，须明确说明"
            "修订证据稀缺，并逐字保留 <!--case-count-policy:two_case_fallback--> marker；"
            f"可使用的披露语句为：{count_policy.get('scarcity_disclosure')}"
        )
    synthetic_policy = (packet.get("writing_constraints") or {}).get(
        "synthetic_case_policy") or {}
    section_id = str((packet.get("current_section") or {}).get("section_id") or "")
    if synthetic_policy.get("present"):
        system += (
            " 合成案例绝不能使用‘笔者初译为、经审校后修改为、初译阶段出现、最终将其"
            "修改为’等历史过程措辞，也不得称其为常见/普遍人类错误，除非 packet 提供"
            "实证频率证据。允许的表述是‘为考察可能偏差，构造如下模拟初译’。"
            f"方法披露：{synthetic_policy.get('methodology_disclosure')}"
            f"{synthetic_policy.get('methodology_marker')}。"
            f"局限披露：{synthetic_policy.get('limitation_disclosure')}"
            f"{synthetic_policy.get('limitation_marker')}。"
        )
    if packet.get("case_analyses"):
        system += (
            " 案例分析必须按 packet.case_analyses 的 analysis_contract_text 实现："
            "authentic_revision 按历史初译→finding/文本差异→实际修订→历史终译；"
            "synthetic_contrast 按翻译难点→合理模拟错误→错误诱因与诊断→意义/功能失真→"
            "当前正式译文的修复对照→有界结论。备选方案必须标注 historical_alternative / analytical_comparison / "
            "counterfactual_rendering；没有证据的备选一律 counterfactual_rendering）、"
            "最终决策与理由、翻译效果（指明具体维度与文本特征，禁止‘更自然/更准确’式"
            "空泛判断）、理论连接（仅当 theory_mapping 存在；否则禁止提及任何理论名称）、"
            "证据边界与有界结论（只限本案例，禁止外推为一般规则）。这些内部字段只用于"
            "组织和约束分析措辞，不得逐项渲染成可见标题。必须使用与 case_type 对应的"
            "模板字段，并使正文描述的变化与 artifact 一致。禁止：编造译者意图或"
            "过程历史；提及 packet 之外任何 seg 段号；把反事实备选写成历史事实。证据不足"
            "时明确写‘本项目证据不足以支持…’，并列出 recommended_human_evidence 所需"
            "的人工证据。"
            " 若案例带 human_evidence（作者事后解释），可在 decision_rationale 中引用，"
            "表述为‘作者后来解释/译者后来说明’，并保留 <!--human-ev:HE-...--> marker；"
            "不得把作者事后解释写成项目同期过程；human_evidence 仅限该案例使用，"
            "不得推广为全局翻译原则。"
        )
    if repair:
        system += ("这是定点修订：仅修复给定 issues，保持当前章节的有效论点、证据和 marker，"
                   "输出完整修订后章节，不写修订说明。按 issue 的 repair_action 处理："
                   "add_missing_problem_analysis 补具体翻译问题与证据；add_process_evidence "
                   "只用 packet 中可用过程证据；narrow_claim / narrow 缩小论点范围；"
                   "replace_strategy_label_with_mechanism 用机制解释替换策略标签；"
                   "add_theory_case_mapping 仅在 packet 提供 theory_mapping 时补充映射；"
                   "add_translation_effect_explanation 补效果维度与文本证据；"
                   "remove_fake_process_history 删除无证据的过程/意图断言；"
                   "downgrade_unsupported_quality_claim 删除或降级无据质量判断；"
                   "bound_case_conclusion 将结论限定为本案例。")
    user = {"packet": packet}
    if repair:
        user.update({"existing_section": existing, "issues": repair_issues})
    raw = None
    for attempt in range(2):
        try:
            raw = call_llm(provider, api_key, model, system,
                           json.dumps(user, ensure_ascii=False), temperature=0.2)
            break
        except Exception as exc:
            if attempt == 1:
                raise
            if not _is_transient_llm_error(exc):
                raise
            # Transient network/provider failure: one bounded retry.
            if repair:
                user["retry_notice"] = (
                    "上次调用失败，本次请只输出章节正文，不要输出任何解释。")
            else:
                user["retry_notice"] = "上次调用失败，本次请直接输出章节正文。"
    text = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", (raw or "").strip(),
                  flags=re.DOTALL)
    if not text:
        raise RuntimeError("学术写作模型返回空章节")
    text = _ensure_section_contract(text, packet.get("current_section") or {})
    return academic_validator.expand_evidence_tokens(text, packet_to_evidence(packet))


def _write_missing_case_example(
    packet: Dict[str, Any], case_id: str, call_llm: Callable,
    provider: str, api_key: str, model: str,
) -> str:
    """Assemble one missing block through the shared presentation adapter."""
    case = next((item for item in packet.get("cases") or []
                 if str(item.get("case_id")) == case_id), None)
    plan = next((item for item in packet.get("case_analyses") or []
                 if str(item.get("case_id")) == case_id), None)
    assignment = next((item for item in packet.get("case_assignments") or []
                       if str(item.get("case_id")) == case_id), None)
    if not case or not plan or not assignment:
        raise ValueError(f"missing required case contract: {case_id}")
    case_type = str(case.get("case_type") or "authentic_revision")
    evidence = case.get("evidence") or {}
    source = str(evidence.get("source") or "").strip()
    initial = str(evidence.get("initial_target") or "").strip()
    target = str(evidence.get("final_target") or "").strip()
    if not source or not target or (case_type == "authentic_revision" and not initial):
        raise ValueError(f"missing focused case evidence: {case_id}")
    focus = case.get("focus") or {}
    presentation = case_presentation.build_case_presentation({
        "case_id": case_id,
        "case_type": case_type,
        "example_number": 1,
        "focus": {
            "source": focus.get("source_span") or {"text": source},
            "initial": focus.get("initial_span") or ({"text": initial} if initial else None),
            "target": focus.get("target_span") or {"text": target},
            "issue": focus.get("issue"),
        },
        "translation_delta": plan.get("translation_delta") or {},
        "analysis_fields": {
            "difficulty": plan.get("problem"),
            "rationale": plan.get("decision_rationale"),
            "effect": plan.get("translation_effect"),
            "bounded_claim": plan.get("bounded_conclusion"),
        },
    })
    return case_presentation.render_case_presentation_markdown(presentation)


def _insert_case_example(
    section_text: str, subsection_id: str, block: str, heading_title: str = "案例分析",
) -> str:
    heading = re.search(
        rf"^(#{{3,6}})\s+{re.escape(subsection_id)}\b.*$",
        section_text, re.MULTILINE)
    if not heading:
        parent_id = subsection_id.rpartition(".")[0]
        parent = re.search(
            rf"^(#{{3,6}})\s+{re.escape(parent_id)}\b.*$",
            section_text, re.MULTILINE) if parent_id else None
        if parent:
            level = len(parent.group(1))
            following = re.search(
                rf"^#{{1,{level}}}\s+", section_text[parent.end():], re.MULTILINE)
            insert_at = parent.end() + following.start() if following else len(section_text)
            addition = (f"{'#' * min(6, level + 1)} {subsection_id} "
                        f"{heading_title}\n\n{block.strip()}")
            return (section_text[:insert_at].rstrip() + "\n\n" + addition + "\n\n" +
                    section_text[insert_at:].lstrip()).strip()
        parent_block = f"### {parent_id} 翻译策略与解决方案\n\n" if parent_id else ""
        return (section_text.rstrip() + "\n\n" + parent_block +
                f"#### {subsection_id} {heading_title}\n\n{block.strip()}").strip()
    level = len(heading.group(1))
    following = re.search(
        rf"^#{{1,{level}}}\s+", section_text[heading.end():], re.MULTILINE)
    insert_at = heading.end() + following.start() if following else len(section_text)
    return (section_text[:insert_at].rstrip() + "\n\n" + block.strip() + "\n\n" +
            section_text[insert_at:].lstrip()).strip()


def _repair_missing_case_examples(
    section_text: str, packet: Dict[str, Any], missing_case_ids: Iterable[str],
    call_llm: Callable, provider: str, api_key: str, model: str,
) -> str:
    assignments = {str(item.get("case_id")): item
                   for item in packet.get("case_assignments") or []}
    repaired = section_text
    for case_id in missing_case_ids:
        case_id = str(case_id)
        assignment = assignments.get(case_id) or {}
        block = _write_missing_case_example(
            packet, case_id, call_llm, provider, api_key, model)
        repaired = _insert_case_example(
            repaired, str(assignment.get("target_subsection") or "3.3"), block,
            str(assignment.get("group_title") or "案例分析"))
    return repaired


def _is_transient_llm_error(exc: Exception) -> bool:
    module = type(exc).__module__ or ""
    if module.startswith("openai"):
        return True
    message = str(exc).lower()
    return any(keyword in message for keyword in (
        "timeout", "connection", "rate limit", "network"))


def _packet_provenance(packet: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "global_claim_ids": [x.get("claim_id") for x in packet.get("claims", [])],
        "project_evidence_ids": [x.get("case_id") for x in packet.get("cases", [])
                                 if x.get("case_type") == "authentic_revision"],
        "synthetic_case_ids": [x.get("case_id") for x in packet.get("cases", [])
                               if x.get("case_type") == "synthetic_contrast"],
        "literature_claim_ids": [x.get("literature_claim_id")
                                 for x in packet.get("literature_claims", [])],
        "literature_evidence_ids": [x.get("evidence_id")
                                    for x in packet.get("literature_evidence", [])],
        "literature_source_ids": [x.get("source_id")
                                  for x in packet.get("literature_sources", [])],
        "support_categories": sorted({
            str(x.get("support_category")) for x in packet.get("claims", [])
            if x.get("support_category")
        }),
    }


def packet_to_evidence(packet: Dict[str, Any]) -> Dict[str, Any]:
    """Minimal evidence shape used for token expansion in a scoped packet."""
    glossary = list(packet.get("terminology_decisions") or [])
    for case in packet.get("cases", []):
        for term in (case.get("evidence") or {}).get("process_evidence", {}).get(
                "terminology_decisions", []):
            if term not in glossary:
                glossary.append(term)
    return {"project_evidence": {"statistics": packet.get("statistics", {}),
                                  "glossary": glossary},
            "literature_sources": packet.get("literature_sources", [])}


def _compose_report(sections: List[Dict[str, Any]]) -> str:
    return "\n\n".join(
        f"## {item['section_id']} {item['title']}\n\n{item['content'].strip()}"
        for item in sections) + "\n"


def _english_report_metadata(genre: str, domain: str) -> Tuple[str, str]:
    """Translate report metadata without leaking Chinese labels into ABSTRACT."""
    genre_key = re.sub(r"\s+", "", str(genre or ""))
    domain_key = re.sub(r"\s+", "", str(domain or ""))
    genre_en = {
        "学术专著": "an excerpt from an academic monograph",
        "学术专著/理论章节": "a theoretical chapter from an academic monograph",
        "学术文本": "an academic text",
    }.get(genre_key, "an academic text")
    domain_en = {
        "传播学/环境人文学": "media and communication studies and environmental humanities",
        "媒体研究/文化理论/技术哲学": "media studies, cultural theory, and philosophy of technology",
        "翻译实践": "academic translation practice",
    }.get(domain_key, "the humanities")
    return genre_en, domain_en


def build_report_matter(
    research_model: Mapping[str, Any], evidence: Mapping[str, Any],
    selected_cases: Mapping[str, Any], template_contract: Optional[Mapping[str, Any]],
    literature_sources_artifact: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build front/back matter only from recorded project and source metadata."""
    project = research_model.get("project_metadata") or {}
    project_name = str(project.get("project_name") or "当前翻译项目")
    profile = evidence.get("project_evidence", {}).get("document_profile") or {}
    stats = evidence.get("project_evidence", {}).get("statistics") or {}
    cases = selected_cases.get("cases") or []
    rqs = [str(x.get("question") or "") for x in research_model.get(
        "research_questions") or [] if x.get("question")]
    glossary = evidence.get("project_evidence", {}).get("glossary") or []
    genre = str(profile.get("genre") or "学术文本")
    domain = str(profile.get("domain") or "翻译实践")
    genre_en, domain_en = _english_report_metadata(genre, domain)
    abstract_zh = (
        f"本报告基于《{project_name}》英汉翻译项目。项目源文本属于{genre}，"
        f"涉及{domain}，共记录 {stats.get('total_segments', 0)} 个翻译片段。"
        f"报告围绕{('；'.join(rqs)) if rqs else '项目中可观察的翻译难点'}展开，"
        f"并在模板规定的案例分析章中使用 {len(cases)} 个可追溯案例讨论长句信息结构、"
        "概念术语与修辞表达的处理。分析只依据已保存的原文、译文、术语、审校与流程记录；"
        "未记录的译者意图、客户反馈或工具使用情况不作推断。"
    )
    abstract_en = (
        f"This report examines the English-Chinese translation project {project_name}. "
        f"The source text is {genre_en} in {domain_en}; the translated portion contains "
        f"{stats.get('total_segments', 0)} segments. Through {len(cases)} textually "
        "traceable examples, the report examines information structure in complex "
        "sentences, the contextual treatment of key concepts, and the reproduction of "
        "metaphor and evaluative meaning. The discussion distinguishes observable "
        "source-target relations from undocumented revision motives and reader effects."
    )
    keywords_zh = [x for x in (genre, domain, "英汉翻译", "案例分析") if x][:4]
    keywords_en = ["English-Chinese translation", "translation practice",
                   "case analysis", "academic translation"]
    structure = (template_contract or {}).get("document_structure") or {}
    front_by_role = {
        "abstract_zh": {"content": abstract_zh},
        "keywords_zh": {"keywords": keywords_zh},
        "abstract_en": {"content": abstract_en},
        "keywords_en": {"keywords": keywords_en},
    }
    front = [{**item, **front_by_role.get(str(item.get("role")), {})}
             for item in structure.get("front_matter") or []]

    references = []
    literature_sources = [source for source in
                          (literature_sources_artifact or {}).get("sources") or []
                          if source.get("citation_allowed")]
    for source in literature_sources:
        citation = source.get("citation_metadata") or {}
        visible = citation.get("bibliography") or citation.get("full")
        if visible:
            references.append(str(visible))
    source_filename = str(project.get("source_filename") or "").strip()
    if source_filename:
        references.insert(0, f"[1] {source_filename}（项目源文献；出版信息待用户补充）")
    segments = evidence.get("project_evidence", {}).get("segments") or []
    appendix_pairs = "\n\n".join(
        f"原文：{item.get('source') or ''}\n\n译文：{item.get('final_target') or ''}"
        for item in segments if item.get("source") and item.get("final_target"))
    appendix_terms = "\n".join(
        f"{item.get('source') or ''}：{item.get('preferred') or item.get('target') or ''}"
        for item in glossary if item.get("source") and (
            item.get("preferred") or item.get("target")))
    back = []
    for item in structure.get("back_matter") or []:
        title = str(item.get("title") or "")
        role = str(item.get("role") or "")
        content = "需要用户补充。"
        if role == "references":
            content = "\n".join(references) if references else "需要用户补充可核验的参考文献。"
        elif role == "acknowledgements":
            content = "需要用户补充致谢正文。"
        elif role == "appendix" and "原文与译文" in title:
            content = appendix_pairs or "当前项目没有可用于附录的原译文对照记录。"
        elif role == "appendix" and "术语" in title:
            content = appendix_terms or "本项目未记录适用的主要术语表。"
        visible_title = title.replace("《XXX》", f"《{project_name}》")
        visible_title = re.sub(
            r"\s*[（(]如果有\s*[，,、]?\s*另起一页[）)]\s*$", "", visible_title)
        back.append({**item, "title": visible_title, "content": content})
    literature_status = "complete" if literature_sources else "literature_required"
    return {
        "project_title": project_name,
        "front_matter": front,
        "back_matter": back,
        "report": {
            "abstract_zh": abstract_zh,
            "keywords_zh": keywords_zh,
            "abstract_en": abstract_en,
            "keywords_en": keywords_en,
            "references": references,
            "acknowledgements": "需要用户补充致谢正文。",
            "appendices": back,
            "literature_status": literature_status,
            "literature_source_count": len(literature_sources),
        },
        "literature_status": literature_status,
    }


def build_report_artifact(
    report_md: str,
    written: Sequence[Mapping[str, Any]],
    outline: Mapping[str, Any],
    constraints: Mapping[str, Any],
    matter: Optional[Mapping[str, Any]] = None,
    selected_cases: Optional[Mapping[str, Any]] = None,
    evidence: Optional[Mapping[str, Any]] = None,
    case_analysis_plans: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Create the structured report consumed by template-aware renderers."""
    case_nodes: List[Dict[str, Any]] = []
    if selected_cases is not None and evidence is not None:
        report_md, case_nodes = _realize_visible_case_examples(
            report_md, dict(evidence), dict(selected_cases),
            dict(case_analysis_plans or {}))
    report_content_by_id: Dict[str, str] = {}
    chapter_matches = list(re.finditer(
        r"^##\s+([^\s]+)(?:\s+.*?)?\s*$", report_md, re.MULTILINE))
    for index, match in enumerate(chapter_matches):
        end = chapter_matches[index + 1].start() \
            if index + 1 < len(chapter_matches) else len(report_md)
        report_content_by_id[match.group(1).rstrip(".．、")] = report_md[
            match.end():end].strip()
    written_by_id = {str(x.get("section_id")): x for x in written}
    sections = []
    for plan in outline.get("sections") or []:
        section_id = str(plan.get("section_id"))
        item = written_by_id.get(section_id) or {}
        content = report_content_by_id.get(section_id, str(item.get("content") or ""))
        heading_matches = list(re.finditer(
            r"^#{3,6}\s+([^\s]+)(?:\s+(.+?))?\s*$", content, re.MULTILINE))
        subsections = []
        intro_content = content[:heading_matches[0].start()].strip() \
            if heading_matches else content.strip()
        for index, match in enumerate(heading_matches):
            end = heading_matches[index + 1].start() \
                if index + 1 < len(heading_matches) else len(content)
            payload = re.sub(r"\s+", " ", match.group(2) or match.group(1)).strip()
            subsections.append({
                "heading_id": match.group(1),
                "title": payload,
                "level": len(match.group(0).split()[0]),
                "content": content[match.end():end].strip(),
            })
        sections.append({
            "section_id": section_id,
            "role": plan.get("role") or "generic_section",
            "title": plan.get("title") or item.get("title") or section_id,
            "level": int(plan.get("level") or 1),
            "required_subsections": list(plan.get("required_subsections") or []),
            "content": content,
            "intro_content": intro_content,
            "subsections": subsections,
            "cases": list(plan.get("cases") or []),
            "case_nodes": [node for node in case_nodes
                           if str(node.get("chapter_id")) == section_id],
        })
    template_contract = constraints.get("template_contract")
    identity = (template_contract or {}).get("template_identity") or {}
    matter = dict(matter or {})
    case_order = [str(node.get("case_id")) for node in case_nodes]
    if not case_order:
        for plan in outline.get("sections") or []:
            if plan.get("role") != "case_analysis":
                continue
            for case_id in plan.get("cases") or []:
                if case_id not in case_order:
                    case_order.append(case_id)
    artifact = {
        "schema_version": VERSIONS["report_artifact_version"],
        "template_hash": constraints.get("template_hash") or identity.get("sha256"),
        "template_id": constraints.get("template_id") or identity.get("template_id"),
        "template_contract_version": constraints.get("template_contract_version") or
        (template_contract or {}).get("schema_version"),
        "renderer_version": report_template.RENDERER_VERSION,
        "case_presentation_version": case_presentation.VERSION,
        "report_stage": constraints.get("report_stage") or "final_report",
        "case_policy": dict(constraints.get("case_policy") or {}),
        "final_case_policy": {
            "final_case_eligible_field": True,
            "contrast_ready_field": True,
            "contrast_types": ["authentic", "synthetic"],
            "formal_case_types": ["authentic_revision", "synthetic_contrast"],
            "translation_decision_visible_allowed": False,
        } if (constraints.get("report_stage") or "final_report") == "final_report" else {},
        "template_contract": template_contract,
        "project_title": matter.get("project_title"),
        "front_matter": list(matter.get("front_matter") or
                             constraints.get("front_matter") or []),
        "sections": sections,
        "back_matter": list(matter.get("back_matter") or
                            constraints.get("back_matter") or []),
        "report": dict(matter.get("report") or {}),
        "case_labels": {case_id: f"例[{index}]"
                        for index, case_id in enumerate(case_order, start=1)},
        "case_types": {str(x.get("case_id")): str(x.get("case_type") or
                                                    "authentic_revision")
                       for x in (selected_cases or {}).get("cases") or []},
        "case_origins": {str(x.get("case_id")): x.get("case_origin")
                         for x in (selected_cases or {}).get("cases") or []},
        "text_roles": {str(x.get("case_id")): dict(x.get("text_role") or {})
                        for x in (selected_cases or {}).get("cases") or []},
        "case_review_statuses": {str(x.get("case_id")): x.get(
            "review_status", "unreviewed")
            for x in (selected_cases or {}).get("cases") or []},
        "report_status": "draft",
        "source_markdown_hash": academic_evidence.stable_hash(report_md),
    }
    if selected_cases is not None and evidence is not None:
        artifact["case_nodes"] = case_nodes
        artifact["case_presentations"] = [dict(node.get("presentation") or {})
                                          for node in case_nodes]
        artifact["case_counts"] = {
            "selected_case_count": len((selected_cases or {}).get("cases") or []),
            "structured_case_node_count": len(case_nodes),
            "unique_case_count": len({str(node.get("case_id")) for node in case_nodes}),
            "focused_case_count": sum(bool((node.get("focus") or {}).get("source")
                                              and (node.get("focus") or {}).get("target"))
                                      for node in case_nodes),
            "provenance_safe_case_count": len({
                str(node.get("case_id")) for node in case_nodes
                if node.get("visible") and node.get("provenance_bound")}),
            "unique_provenance_bound_visible_case_count": len({
                str(node.get("case_id")) for node in case_nodes
                if node.get("visible") and node.get("provenance_bound")}),
        }
        selected_type_counts = Counter(
            str(item.get("case_type") or "authentic_revision")
            for item in (selected_cases or {}).get("cases") or [])
        structured_type_counts = Counter(
            str(node.get("case_type") or "authentic_revision")
            for node in case_nodes)
        artifact["case_counts"].update({
            "authentic_revision_case_count": selected_type_counts.get(
                "authentic_revision", 0),
            "translation_decision_case_count": selected_type_counts.get(
                "translation_decision", 0),
            "synthetic_contrast_case_count": selected_type_counts.get(
                "synthetic_contrast", 0),
            "legacy_synthetic_contrast_case_count": sum(
                item.get("case_type") == "synthetic_contrast"
                and item.get("baseline_origin") == "legacy_analytical_draft"
                for item in (selected_cases or {}).get("cases") or []),
            "newly_generated_synthetic_contrast_case_count": sum(
                item.get("case_type") == "synthetic_contrast"
                and item.get("baseline_origin") == "newly_generated"
                for item in (selected_cases or {}).get("cases") or []),
            "structured_authentic_revision_case_count": structured_type_counts.get(
                "authentic_revision", 0),
            "structured_translation_decision_case_count": structured_type_counts.get(
                "translation_decision", 0),
            "structured_synthetic_contrast_case_count": structured_type_counts.get(
                "synthetic_contrast", 0),
        })
        final_cases = [item for item in (selected_cases or {}).get("cases") or []
                       if item.get("case_type") in {
                           "authentic_revision", "synthetic_contrast"}]
        final_nodes = [node for node in case_nodes if node.get("case_type") in {
            "authentic_revision", "synthetic_contrast"}]
        synthetic_nodes = [node for node in final_nodes
                           if node.get("case_type") == "synthetic_contrast"]
        authentic_nodes = [node for node in final_nodes
                           if node.get("case_type") == "authentic_revision"]
        def exact_label_count(nodes: Iterable[Mapping[str, Any]], label: str) -> int:
            pattern = re.compile(rf"^\s*\*{{0,2}}{re.escape(label)}\*{{0,2}}\s*[：:]",
                                 re.MULTILINE)
            return sum(bool(pattern.search(str(node.get("content") or ""))) for node in nodes)
        artifact["case_counts"].update({
            "final_case_count": len(final_cases),
            "contrast_case_count": sum(bool(item.get("contrast_ready"))
                                         for item in final_cases),
            "contrast_ready_case_count": sum(bool(item.get("contrast_ready"))
                                               for item in final_cases),
            "translation_decision_visible_count": structured_type_counts.get(
                "translation_decision", 0),
            "synthetic_label_count": exact_label_count(
                synthetic_nodes, "模拟初译"),
            "authentic_initial_label_count": exact_label_count(
                authentic_nodes, "初译"),
            "rewrite_label_count": exact_label_count(final_nodes, "改译"),
        })
    artifact["content_hash"] = academic_evidence.stable_hash(
        {k: v for k, v in artifact.items() if k != "content_hash"})
    return artifact


_QUOTE_LINE = re.compile(
    r"^>\s*\[(SOURCE|INITIAL|TARGET|SYNTHETIC_SOURCE|SIMULATED|OPTIMIZED)\s+"
    r"([A-Za-z0-9_-]+)\]:\s*(.*)$", re.MULTILINE)


def _case_focus_for_assembly(
    case: Mapping[str, Any], segment: Mapping[str, Any], evidence: Mapping[str, Any],
) -> Dict[str, Any]:
    if case.get("case_type") == "synthetic_contrast":
        baseline = (case.get("synthetic_baseline") or {}).get("text")
        segment = {
            **segment,
            "source": case.get("source_text") or segment.get("source"),
            "initial_target": baseline,
            "final_target": case.get("target_contrast_text") or
            case.get("final_target") or segment.get("final_target"),
        }
    return dict(case.get("focus") or academic_evidence.build_case_focus(
        dict(case), dict(segment),
        (evidence.get("project_evidence") or {}).get("glossary") or []))


def normalize_report_quotes(
    report_md: str, evidence: Dict[str, Any],
    selected_cases: Optional[Dict[str, Any]] = None,
) -> str:
    """Deterministically replace case quotes with exact provenance-bound focus text.

    The writer is instructed to copy quotes verbatim, but a bounded repair loop
    cannot guarantee byte-exact output from every provider.  This pass makes
    the final report quote-consistent by construction while the saved sections
    artifact keeps the model's original prose for auditability.
    """
    segs = academic_evidence.segment_index(evidence)
    selected = {str(x.get("case_id")): x
                for x in (selected_cases or {}).get("cases", [])}

    def repl(match: re.Match) -> str:
        kind, case_id, _ = match.groups()
        if kind in {"SOURCE", "INITIAL", "TARGET"}:
            selected_case = selected.get(case_id) or {}
            segment = segs.get(str(selected_case.get("source_segment_id") or case_id))
            if not segment:
                return match.group(0)
            focus = _case_focus_for_assembly(selected_case, segment, evidence)
            span = focus.get({"SOURCE": "source_span", "INITIAL": "initial_span",
                              "TARGET": "target_span"}[kind]) or {}
            if kind == "INITIAL" and selected_case.get(
                    "case_type") == "translation_decision":
                return ""
            exact = span.get("text") or segment[{
                "SOURCE": "source", "INITIAL": "initial_target",
                "TARGET": "final_target"}[kind]]
        else:
            case = selected.get(case_id) or {}
            exact = {
                "SYNTHETIC_SOURCE": case.get("source_text"),
                "SIMULATED": case.get("synthetic_baseline", {}).get("text"),
                "OPTIMIZED": case.get("final_target") or
                case.get("optimized_translation", {}).get("text"),
            }[kind]
            if not exact:
                return match.group(0)
        return f"> [{kind} {case_id}]: {exact}"

    return _QUOTE_LINE.sub(repl, report_md)


def _expand_report_stat_tokens(
    report_md: str, evidence: Dict[str, Any],
    selected_cases: Optional[Dict[str, Any]],
    outline: Optional[Dict[str, Any]],
) -> str:
    """Expand global metrics and only unambiguous section-scoped metrics."""
    selected_cases = selected_cases or {}
    if not outline:
        return academic_validator.expand_evidence_tokens(
            report_md, evidence, academic_validator.case_statistic_overrides(
                {"cases": [x.get("case_id") for x in selected_cases.get("cases", [])]},
                selected_cases, evidence))

    planned = {str(x.get("section_id")): x
               for x in outline.get("sections", [])}
    headings = list(re.finditer(
        r"^##\s+([^\s]+)(?:\s+.*)?$", report_md, re.MULTILINE))
    if not headings:
        return academic_validator.expand_evidence_tokens(report_md, evidence)

    pieces: List[str] = []
    cursor = 0
    for index, heading in enumerate(headings):
        body_end = headings[index + 1].start() if index + 1 < len(headings) else len(report_md)
        pieces.append(report_md[cursor:heading.end()])
        section_id = heading.group(1).rstrip(".．、")
        overrides = academic_validator.case_statistic_overrides(
            planned.get(section_id) or {}, selected_cases, evidence)
        pieces.append(academic_validator.expand_evidence_tokens(
            report_md[heading.end():body_end], evidence, overrides))
        cursor = body_end
    pieces.append(report_md[cursor:])
    return "".join(pieces)


def _ensure_case_group_headings(
    report_md: str, selected_cases: Optional[Dict[str, Any]],
    outline: Optional[Dict[str, Any]],
) -> str:
    """Ensure evidence-derived difficulty/strategy groups remain visible."""
    portfolio = (selected_cases or {}).get("case_portfolio") or {}
    groups = list(portfolio.get("groups") or [])
    if not groups:
        return report_md
    planned = next((x for x in (outline or {}).get("sections", [])
                    if x.get("role") == "case_analysis"), None)
    section_id = str((planned or {}).get("section_id") or "3")
    problem_root, solution_root = thesis_constraints.case_subsection_roots(planned or {})
    section_match = re.search(
        rf"^##\s+{re.escape(section_id)}(?:\s|[.．、]|$).*?$",
        report_md, re.MULTILINE)
    if not section_match:
        return report_md
    next_section = re.search(r"^##\s+", report_md[section_match.end():], re.MULTILINE)
    body_end = section_match.end() + (next_section.start() if next_section else
                                      len(report_md) - section_match.end())
    body = report_md[section_match.end():body_end]
    difficulty_root = re.search(
        rf"^###\s+{re.escape(problem_root)}(?:\s|$).*?$", body, re.MULTILINE)
    strategy_root = re.search(
        rf"^###\s+{re.escape(solution_root)}(?:\s|$).*?$", body, re.MULTILINE)
    if strategy_root is None:
        return report_md
    if any(x.get("case_type") == "synthetic_contrast"
           for x in (selected_cases or {}).get("cases") or []) \
            and "<!--synthetic-methodology-->" not in body:
        disclosure = (
            "<!--synthetic-methodology-->\n"
            "本项目仅保存了少量可核实的历史初译—改译记录。为使翻译策略分析具备可比较基础，"
            "对于缺乏历史初译但具有典型分析价值的案例，本文使用经验证的模拟初译作为受控"
            "对比材料；其中部分译法来自前期论文案例设计，并已与当前源文和当前译文重新核对。"
            "这些模拟初译旨在呈现普通译者在初步处理过程中可能采用的合理译法，不属于"
            "项目真实翻译历史，也不作为实际修订记录使用。\n\n"
            "<!--synthetic-limitation-->\n"
            "下列模拟对比只说明一种可分析的处理差异，不据此声称该处理在人类译者中的发生频率。\n\n")
        insert_at = difficulty_root.start() if difficulty_root else 0
        body = body[:insert_at] + disclosure + body[insert_at:]
        difficulty_root = re.search(
            rf"^###\s+{re.escape(problem_root)}(?:\s|$).*?$", body, re.MULTILINE)
        strategy_root = re.search(
            rf"^###\s+{re.escape(solution_root)}(?:\s|$).*?$", body, re.MULTILINE)
    if difficulty_root and strategy_root:
        insert_at = strategy_root.start()
        missing = []
        for group in groups:
            subsection = _scope_case_assignment({
                "target_subsection": group.get("strategy_subsection"),
            }, planned or {}).get("difficulty_subsection", "")
            if subsection and not re.search(
                    rf"^#{{4,6}}\s+{re.escape(subsection)}(?:\s|$)", body,
                    re.MULTILINE):
                missing.append(
                    f"#### {subsection} {group.get('difficulty_group')}\n\n"
                    f"该类难点由 {int(group.get('case_count') or 0)} 个可追溯例证支持。\n\n")
        if missing:
            body = body[:insert_at] + "".join(missing) + body[insert_at:]

    def add_strategy_heading(group: Mapping[str, Any], text: str) -> str:
        subsection = _scope_case_assignment({
            "target_subsection": group.get("strategy_subsection"),
        }, planned or {}).get("strategy_subsection", "")
        if not subsection or re.search(
                rf"^#{{4,6}}\s+{re.escape(subsection)}(?:\s|$)", text,
                re.MULTILINE):
            return text
        case_ids = [str(x) for x in group.get("case_ids") or []]
        positions = [position for case_id in case_ids
                     for position in (text.find(f"<!--case:{case_id}-->"),
                                      text.find(case_id)) if position >= 0]
        position = min(positions) if positions else 0
        insert_at = text.rfind("\n\n", 0, position) + 2
        heading = f"#### {subsection} {group.get('strategy_group')}\n\n"
        return text[:insert_at] + heading + text[insert_at:]

    for group in groups:
        body = add_strategy_heading(group, body)
    return report_md[:section_match.end()] + body + report_md[body_end:]


_VISIBLE_EXAMPLE = re.compile(
    r"^(?P<label>[ \t]*(?:[-*][ \t]*)?\*{1,2}例\[\d+\][^\n]*?\*{0,2})[ \t]*$",
    re.MULTILINE)
_VISIBLE_CASE_QUOTE = re.compile(
    r"^(?P<indent>\s*)[-*]\s+\*{1,2}(?P<label>SOURCE|INITIAL|TARGET|"
    r"原文|源语(?:（SOURCE）|\s*\(SOURCE\))?|初译|终译|改译|译文(?:（TARGET）|"
    r"\s*\(TARGET\))?|模拟初译|模拟译法|优化译文|最终译文)\*{1,2}\s*[：:]\s*"
    r"(?P<value>.+?)\s*$",
    re.MULTILINE | re.IGNORECASE)


def _quote_fragments(value: Any) -> List[str]:
    text = str(value or "").strip().strip('“”"')
    fragments = []
    for excerpt in re.split(r"(?:\.{3,}|…+)", text):
        fragments.extend(re.split(
            r"[\"”']\s*(?:以及|及|和)\s*[\"“']", excerpt))
    return [fragment.strip().strip('“”"') for fragment in fragments
            if len(fragment.strip().strip('“”"')) >= 8]


def _source_match_score(quoted: str, source: str) -> int:
    fragments = _quote_fragments(quoted)
    if not fragments:
        return 0
    def match_norm(value: str) -> str:
        value = str(value or "").casefold()
        value = re.sub(r"(?<=[a-z])-\s*(?=[a-z])", "", value)
        value = value.replace("’", "'").replace("‘", "'")
        value = value.replace("“", '"').replace("”", '"')
        return re.sub(r"[^a-z0-9\u3400-\u9fff]+", " ", value).strip()

    source_norm = match_norm(source)
    score = 0
    for fragment in fragments:
        fragment_norm = match_norm(fragment)
        if fragment_norm not in source_norm:
            return 0
        score += len(fragment_norm)
    return score


def _realize_visible_case_examples(
    report_md: str, evidence: Dict[str, Any], selected_cases: Dict[str, Any],
    case_analysis_plans: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Bind, number and materialize visible examples as canonical case nodes."""
    matches = list(_VISIBLE_EXAMPLE.finditer(report_md))
    if not matches:
        return report_md, []
    segments = academic_evidence.segment_index(evidence)
    selected_by_id = {str(x.get("case_id")): x
                      for x in selected_cases.get("cases") or []}
    plan_by_id = case_analysis.plan_index(case_analysis_plans or {})
    candidates = []
    for case_id, case in selected_by_id.items():
        segment_id = str(case.get("source_segment_id") or case_id)
        segment = segments.get(segment_id) or {}
        if case.get("case_type") == "synthetic_contrast":
            segment = {
                **segment,
                "segment_id": segment_id,
                "source": case.get("source_text") or segment.get("source"),
                "final_target": case.get("target_contrast_text") or
                case.get("final_target") or (
                    (case.get("optimized_translation") or {}).get("text")
                    if isinstance(case.get("optimized_translation"), Mapping)
                    else case.get("optimized_translation")),
            }
        if case_id and segment.get("source"):
            candidates.append((case_id, segment))
    chunks = []
    nodes = []
    cursor = 0
    for index, match in enumerate(matches):
        next_example = matches[index + 1].start() \
            if index + 1 < len(matches) else len(report_md)
        next_heading = re.search(r"^#{2,6}\s+", report_md[match.end():], re.MULTILINE)
        heading_end = match.end() + next_heading.start() if next_heading else len(report_md)
        next_summary = re.search(
            r"^\s*\*{1,2}本组小结\*{1,2}", report_md[match.end():], re.MULTILINE)
        summary_end = match.end() + next_summary.start() \
            if next_summary else len(report_md)
        end = min(next_example, heading_end, summary_end)
        block = report_md[match.start():end]
        block = re.sub(r"例\[\d+\]", f"例[{index + 1}]", block, count=1)
        explicit = [case_id for case_id in re.findall(
            r"<!--case:([A-Za-z0-9_.:-]+)-->", block) if case_id in selected_by_id]
        case_id = explicit[0] if len(set(explicit)) == 1 else ""
        segment = None
        if case_id:
            selected_case = selected_by_id[case_id]
            segment = segments.get(str(selected_case.get("source_segment_id") or case_id))
        if not segment:
            source_line = next((item for item in _VISIBLE_CASE_QUOTE.finditer(block)
                                if str(item.group("label")).upper() in {
                                    "SOURCE", "原文", "源语（SOURCE）", "源语(SOURCE)"}), None)
            scored = sorted((
                (_source_match_score(source_line.group("value"), item.get("source")),
                 candidate_id, item)
                for candidate_id, item in candidates), reverse=True) if source_line else []
            if scored and scored[0][0] > 0 and not (
                    len(scored) > 1 and scored[0][0] == scored[1][0]):
                _score, case_id, segment = scored[0]
        if not case_id or not segment:
            chunks.append(report_md[cursor:match.start()])
            chunks.append(block)
            cursor = end
            continue
        selected_case = case_provenance.with_provenance(selected_by_id[case_id])
        case_type = str(selected_case.get("case_type") or "authentic_revision")
        focus = _case_focus_for_assembly(selected_case, segment, evidence)
        plan = plan_by_id.get(case_id) or {}

        def replace_quote(item: re.Match) -> str:
            label = str(item.group("label") or "").upper()
            if label in {"SOURCE", "原文", "源语（SOURCE）", "源语(SOURCE)"}:
                kind, value = "SOURCE", (focus.get("source_span") or {}).get("text")
            elif label in {"INITIAL", "初译", "模拟初译", "模拟译法"}:
                if case_type == "translation_decision":
                    return ""
                kind, value = "INITIAL", (focus.get("initial_span") or {}).get("text")
            else:
                kind, value = "TARGET", (focus.get("target_span") or {}).get("text")
            return f"> [{kind} {case_id}]: {value}" if value else item.group(0)

        block = _VISIBLE_CASE_QUOTE.sub(replace_quote, block)
        heading_ids = re.findall(
            r"^#{3,6}\s+(\d+(?:\.\d+)*)\b", report_md[:match.start()], re.MULTILINE)
        actual_subsection = heading_ids[-1] if heading_ids else ""
        assignment = _case_assignment_for_plan(
            case_id, plan, selected_case)
        extracted = case_presentation.analysis_fragments_from_markdown(block)
        analysis_fields = {
            "difficulty": plan.get("problem") or {"statement": focus.get("issue")},
            "strategy": selected_case.get("strategy_group"),
            "rationale": plan.get("decision_rationale"),
            "effect": plan.get("translation_effect"),
            "bounded_claim": plan.get("bounded_conclusion"),
            "evidence": {
                "level": plan.get("evidence_level"),
                "can_support": list(plan.get("can_support") or []),
                "cannot_support": list(plan.get("cannot_support") or []),
            },
            "visible_analysis": extracted.get("analysis") or [],
            "limits": extracted.get("limits") or [],
            "note": extracted.get("note"),
        }
        node = {
            "type": "case_example",
            "case_id": case_id,
            "case_type": case_type,
            "case_origin": selected_case.get("case_origin"),
            "text_role": dict(selected_case.get("text_role") or {}),
            "review_status": selected_case.get("review_status", "unreviewed"),
            "baseline_origin": selected_case.get("baseline_origin")
            if case_type == "synthetic_contrast" else None,
            "chapter_id": actual_subsection.split(".", 1)[0] if actual_subsection else "3",
            "subsection_id": actual_subsection or assignment["target_subsection"],
            "example_number": index + 1,
            "research_question_ids": list(selected_case.get("research_questions") or []),
            "source": (focus.get("source_span") or {}).get("text"),
            "initial_target": (focus.get("initial_span") or {}).get("text")
            if case_type == "authentic_revision" else None,
            "synthetic_baseline": {
                **dict(selected_case.get("synthetic_baseline") or {}),
                "text": (focus.get("initial_span") or {}).get("text") or
                (selected_case.get("synthetic_baseline") or {}).get("text"),
            } if case_type == "synthetic_contrast" else None,
            "target": (focus.get("target_span") or {}).get("text"),
            "focus": {
                "source": focus.get("source_span"),
                "initial": focus.get("initial_span")
                if case_type != "translation_decision" else None,
                "target": focus.get("target_span"),
                "issue": focus.get("issue"),
                "signal": focus.get("signal"),
            },
            "difficulty": analysis_fields["difficulty"],
            "strategy": analysis_fields["strategy"],
            "effect": analysis_fields["effect"],
            "bounded_claim": analysis_fields["bounded_claim"],
            "evidence": analysis_fields["evidence"],
            "translation_delta": plan.get("translation_delta") or {},
            "final_case_eligible": bool(selected_case.get("final_case_eligible")),
            "contrast_ready": bool(selected_case.get("contrast_ready")),
            "contrast_type": selected_case.get("contrast_type"),
            "synthetic_evidence": dict(selected_case.get("synthetic_evidence") or {})
            if case_type == "synthetic_contrast" else None,
            "analysis_fields": analysis_fields,
            **assignment,
            "visible": True,
            "provenance_bound": bool(
                (focus.get("source_span") or {}).get("text") and
                (focus.get("target_span") or {}).get("text")),
            "provenance": {
                "case_id": case_id,
                "source_segment_id": str(
                    selected_case.get("source_segment_id") or case_id),
                **dict(selected_case.get("provenance") or {}),
            },
        }
        presentation = case_presentation.build_case_presentation(node)
        block = case_presentation.render_case_presentation_markdown(presentation)
        hidden = []
        for marker in re.findall(
                r"<!--(?!(?:case|rq):)[A-Za-z0-9_-]+:[A-Za-z0-9_.:-]+-->",
                report_md[match.start():end]):
            if marker not in hidden:
                hidden.append(marker)
        hidden.extend(
            f"<!--rq:{rq_id}-->" for rq_id in selected_case.get(
                "research_questions") or [])
        if hidden:
            block += "\n" + "\n".join(hidden)
        node.update(
            presentation=presentation,
            analysis=presentation["analysis"],
            content=block.strip(),
        )
        nodes.append(node)
        chunks.append(report_md[cursor:match.start()])
        chunks.append(block.rstrip() + "\n\n")
        cursor = end
    chunks.append(report_md[cursor:])
    return "".join(chunks), nodes


def _normalize_visible_case_examples(
    report_md: str, evidence: Dict[str, Any], selected_cases: Dict[str, Any],
) -> str:
    """Backward-compatible string surface for case realization."""
    return _realize_visible_case_examples(report_md, evidence, selected_cases)[0]


_USER_FACING_LANGUAGE_REPLACEMENTS = (
    ("句法 core cases", "句法类主要例证"),
    ("rhetoric core cases", "修辞类主要例证"),
    ("core 与 supporting 案例", "主要例证与补充例证"),
    ("core cases", "主要例证"),
    ("core case", "主要例证"),
    ("translation-decision cases", "翻译决策类案例"),
    ("authentic revision", "真实修订案例"),
    ("source/target", "原文与译文"),
    ("source 与 target", "原文与译文"),
    ("最小充分 focus", "最小充分语境片段"),
    ("完整 segment", "完整文本片段"),
)


def _normalize_user_facing_language(text: Any) -> str:
    """Translate planner/debug labels into ordinary thesis wording."""
    normalized = str(text or "")
    for old, new in _USER_FACING_LANGUAGE_REPLACEMENTS:
        normalized = normalized.replace(old, new)
    return normalized


def normalize_report_rendering(text: Any) -> str:
    """Repair reachable transport/presentation artefacts in report prose.

    ``>。`` is not a meaningful quotation: it is the remnant of a writer
    label being passed through the case renderer.  Likewise, some legacy
    report blocks contain a bold subsection title glued to the previous
    paragraph.  Repair only these known shapes so legitimate Markdown
    blockquotes and bold prose remain untouched.
    """
    normalized = str(text or "")
    normalized = re.sub(
        r"((?:\*{0,2}分析\*{0,2})\s*[：:]\s*)>\s*[。．]\s*",
        r"\1", normalized)
    normalized = re.sub(
        r"(?P<lead>[。！？])\s*(?P<title>\d+(?:\.\d+)+\s+[^。\n*]{2,100})"
        r"\*{2}\s*[。！？]",
        r"\g<lead>\n\n### \g<title>\n\n",
        normalized,
    )
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized


def finalize_report_tokens(
    report_md: str, evidence: Dict[str, Any],
    selected_cases: Optional[Dict[str, Any]] = None,
    outline: Optional[Dict[str, Any]] = None,
) -> str:
    """Apply quote normalisation plus full-evidence token expansion.

    The scoped packet carries planned global statistics and any unambiguous
    case-scoped metric. Writers sometimes emit other globally valid
    {{STAT:key}} tokens; expanding against the full evidence store keeps the
    final report self-consistent while the scoped packet remains the writer's
    authority during drafting.
    """
    normalized = normalize_report_quotes(report_md, evidence, selected_cases)
    normalized = _normalize_visible_case_examples(
        normalized, evidence, selected_cases or {})
    normalized = normalize_report_quotes(normalized, evidence, selected_cases)
    normalized = _ensure_case_group_headings(normalized, selected_cases, outline)
    normalized = _expand_report_stat_tokens(normalized, evidence, selected_cases, outline)
    normalized = re.sub(r"基于\s*基于", "基于", normalized)
    # Internal portfolio labels stay in structured artifacts.  The visible
    # thesis should use ordinary academic wording instead of planner/debug
    # vocabulary, while source excerpts and internal JSON remain untouched.
    return normalize_report_rendering(_normalize_user_facing_language(normalized))


def _semantic_review(
    report_md: str, research_model: Dict[str, Any], argument_plan: Dict[str, Any],
    outline: Dict[str, Any], selected_cases: Dict[str, Any],
    call_llm: Callable, provider: str, api_key: str, model: str,
) -> Dict[str, Any]:
    system = (
        "你是独立的学术审稿人，不是写作者。检查不受确定性验证覆盖的推理问题："
        "unsupported_conclusion、weak_evidence、case_claim_mismatch、theory_case_mismatch、"
        "overgeneralization、duplicate_argument、contradiction、descriptive_not_analytical、"
        "chapter_drift、conclusion_too_strong、synthetic_case_presented_as_historical、"
        "unsupported_human_error_frequency_claim。synthetic_contrast 只能作为明确标注的"
        "分析实验，不能支持作者历史过程。还要按 report_constraints 检查已配置的 section 功能与"
        "论证链条：研究问题、文本特征、案例证据、策略/方案、效果和结论是否贯通，"
        "以及结论部分是否引入了新案例。"
        "只输出 JSON：{\"issues\":[{\"issue_id\":"
        "\"AR-001\",\"section_id\":\"3\",\"type\":\"weak_evidence\","
        "\"claim_id\":\"C1\",\"evidence_ids\":[\"seg-...\"],"
        "\"severity\":\"low|medium|high\",\"reason\":\"...\","
        "\"suggested_action\":\"...\"}]}。不得改写正文。"
    )
    payload = {
        "research_model": research_model,
        "report_constraints": research_model.get("report_constraints") or {},
        "argument_plan": argument_plan,
        "outline": outline,
        "selected_cases": [
            {"case_id": x.get("case_id"), "case_type": x.get("case_type"),
             "provenance": x.get("provenance")}
            for x in selected_cases.get("cases", [])],
        "report": report_md,
    }
    try:
        raw = _call_json(call_llm, provider, api_key, model, system,
                         json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        if not _is_transient_llm_error(exc):
            raise
        raw = None
    valid_sections = {str(x["section_id"]) for x in outline.get("sections", [])}
    valid_claims = {str(x["claim_id"]) for x in argument_plan.get("claims", [])}
    valid_evidence = {str(x["case_id"]) for x in selected_cases.get("cases", [])}
    for claim in argument_plan.get("claims", []):
        valid_evidence.update(str(x) for x in claim.get("project_evidence") or [])
        valid_evidence.update(str(x) for x in claim.get("literature_evidence") or [])
    issues = []
    if raw is None:
        issues.append({
            "issue_id": "AR-001", "section_id": None, "type": "review_failed",
            "claim_id": None, "evidence_ids": [], "severity": "medium",
            "reason": "语义学术审稿未返回可解析的结构化结果。",
            "suggested_action": "重新运行学术审稿。",
        })
    else:
        for i, item in enumerate(raw.get("issues") or []):
            if not isinstance(item, dict):
                continue
            section_id = str(item.get("section_id") or "") or None
            claim_id = str(item.get("claim_id") or "") or None
            if section_id not in valid_sections:
                section_id = None
            if claim_id not in valid_claims:
                claim_id = None
            severity = str(item.get("severity") or "medium").lower()
            if severity not in ("low", "medium", "high"):
                severity = "medium"
            reason = str(item.get("reason") or "").strip()
            action = str(item.get("suggested_action") or "").strip()
            evidence_ids = [x for x in _as_list(item.get("evidence_ids"))
                            if x in valid_evidence]
            if not section_id or not reason or not action:
                continue
            issues.append({
                "issue_id": f"AR-{len(issues) + 1:03d}",
                "section_id": section_id,
                "type": str(item.get("type") or "weak_evidence"),
                "claim_id": claim_id,
                "evidence_ids": evidence_ids,
                "severity": severity,
                "reason": reason,
                "suggested_action": action,
            })
        if raw.get("issues") and not issues:
            issues.append({
                "issue_id": "AR-001", "section_id": None, "type": "review_failed",
                "claim_id": None, "evidence_ids": [], "severity": "medium",
                "reason": "语义审稿只返回了无法定位或不完整的意见。",
                "suggested_action": "重新运行审稿并要求绑定有效 section/claim/evidence id。",
            })
    status = "review_required" if any(x["severity"] in ("medium", "high") for x in issues) \
        else ("pass_with_warnings" if issues else "pass")
    artifact = {"schema_version": VERSIONS["reviewer_version"], "status": status,
                "issues": issues}
    artifact["content_hash"] = academic_evidence.stable_hash(
        {k: v for k, v in artifact.items() if k != "content_hash"})
    return artifact


def _literature_support_review(
    report_md: str, argument_plan: Dict[str, Any], outline: Dict[str, Any],
    literature_sources_artifact: Dict[str, Any],
    literature_evidence_artifact: Dict[str, Any],
    literature_claims_artifact: Dict[str, Any],
    call_llm: Callable, provider: str, api_key: str, model: str,
) -> Dict[str, Any]:
    issue_types = {
        "unsupported_by_evidence", "support_too_weak", "claim_too_broad",
        "claim_stronger_than_source", "quotation_context_mismatch",
        "paraphrase_distorts_source", "theory_case_mismatch",
        "citation_present_but_not_supportive",
    }
    source_ids = set(literature_evidence.source_index(literature_sources_artifact))
    evidence_ids = set(literature_evidence.evidence_index(literature_evidence_artifact))
    literature_claim_ids = set(literature_evidence.claim_index(literature_claims_artifact))
    global_claim_ids = {str(x.get("claim_id")) for x in argument_plan.get("claims", [])}
    section_ids = {str(x.get("section_id")) for x in outline.get("sections", [])}
    used_claim_ids = {
        str(x) for claim in argument_plan.get("claims", [])
        for x in claim.get("literature_claims") or []
    }
    if not used_claim_ids:
        artifact = {
            "schema_version": VERSIONS["literature_reviewer_version"],
            "status": "not_applicable", "issues": [],
            "reviewed_literature_claims": 0,
        }
        artifact["content_hash"] = academic_evidence.stable_hash(
            {k: v for k, v in artifact.items() if k != "content_hash"})
        return artifact
    all_claims = literature_evidence.claim_index(literature_claims_artifact)
    scoped_claims = [all_claims[x] for x in sorted(used_claim_ids) if x in all_claims]
    scoped_evidence_ids = {
        evidence_id for claim in scoped_claims
        for evidence_id in claim.get("supporting_evidence_ids") or []
    }
    all_evidence = literature_evidence.evidence_index(literature_evidence_artifact)
    scoped_evidence = [all_evidence[x] for x in sorted(scoped_evidence_ids)
                       if x in all_evidence]
    scoped_source_ids = {x.get("source_id") for x in scoped_evidence}
    all_sources = literature_evidence.source_index(literature_sources_artifact)
    scoped_sources = [
        {k: v for k, v in all_sources[x].items() if k != "content_blocks"}
        for x in sorted(scoped_source_ids) if x in all_sources]
    system = (
        "你是独立的 Literature Support Reviewer，以低推断强度核对 Literature Claim、逐字"
        "Literature Evidence、Global Claim 与实际章节。不要改写正文，不检查一般文风。只输出"
        "JSON：{\"issues\":[{\"type\":\"unsupported_by_evidence|support_too_weak|"
        "claim_too_broad|claim_stronger_than_source|quotation_context_mismatch|"
        "paraphrase_distorts_source|theory_case_mismatch|citation_present_but_not_supportive\","
        "\"section_id\":\"3\",\"global_claim_id\":\"C1\","
        "\"literature_claim_id\":\"LC-001\",\"literature_evidence_ids\":[\"LE-...\"],"
        "\"source_id\":\"source-id\",\"severity\":\"low|medium|high\","
        "\"reason\":\"...\",\"repair_action\":\"narrow|replace_evidence|remove|rewrite|"
        "downgrade|mark_author_interpretation\"}]}。每条意见必须能定位到章节和文献主张。"
    )
    payload = {
        "literature_sources": scoped_sources,
        "literature_evidence": scoped_evidence,
        "literature_claims": scoped_claims,
        "argument_plan": argument_plan,
        "outline": outline,
        "report": report_md,
    }
    try:
        raw = _call_json(call_llm, provider, api_key, model, system,
                         json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        if not _is_transient_llm_error(exc):
            raise
        raw = None
    issues = []
    if raw is None:
        issues.append({
            "issue_id": "LR-001", "type": "unsupported_by_evidence",
            "section_id": None, "global_claim_id": None,
            "literature_claim_id": None, "literature_evidence_ids": [],
            "source_id": None, "severity": "medium",
            "reason": "文献支持审校未返回可解析的结构化结果。",
            "repair_action": "downgrade",
        })
    else:
        for item in raw.get("issues") or []:
            if not isinstance(item, dict):
                continue
            section_id = str(item.get("section_id") or "")
            global_claim_id = str(item.get("global_claim_id") or "")
            literature_claim_id = str(item.get("literature_claim_id") or "")
            source_id = str(item.get("source_id") or "")
            if section_id not in section_ids or literature_claim_id not in literature_claim_ids:
                continue
            if global_claim_id not in global_claim_ids:
                global_claim_id = None
            if source_id not in source_ids:
                source_id = None
            item_evidence = [str(x) for x in item.get("literature_evidence_ids") or []
                             if str(x) in evidence_ids]
            issue_type = str(item.get("type") or "unsupported_by_evidence")
            if issue_type not in issue_types:
                issue_type = "unsupported_by_evidence"
            severity = str(item.get("severity") or "medium").lower()
            if severity not in {"low", "medium", "high"}:
                severity = "medium"
            action = str(item.get("repair_action") or "downgrade")
            if action not in {"narrow", "replace_evidence", "remove", "rewrite",
                              "downgrade", "mark_author_interpretation"}:
                action = "downgrade"
            reason = str(item.get("reason") or "").strip()
            if not reason:
                continue
            issues.append({
                "issue_id": f"LR-{len(issues) + 1:03d}", "type": issue_type,
                "section_id": section_id, "global_claim_id": global_claim_id,
                "literature_claim_id": literature_claim_id,
                "literature_evidence_ids": item_evidence,
                "source_id": source_id, "severity": severity,
                "reason": reason, "repair_action": action,
            })
    status = "review_required" if any(x["severity"] in {"medium", "high"}
                                      for x in issues) else (
        "pass_with_warnings" if issues else "pass")
    artifact = {
        "schema_version": VERSIONS["literature_reviewer_version"],
        "status": status, "issues": issues,
        "reviewed_literature_claims": len(used_claim_ids),
    }
    artifact["content_hash"] = academic_evidence.stable_hash(
        {k: v for k, v in artifact.items() if k != "content_hash"})
    return artifact


def _locate_validation_issues(
    validation: Dict[str, Any], sections: List[Dict[str, Any]],
) -> Dict[str, Any]:
    for issue in validation.get("issues", []):
        if issue.get("section_id"):
            continue
        needle = issue.get("evidence_id")
        if needle:
            needles = [str(needle)]
            if str(needle).startswith("metric:"):
                needles.append(str(needle).split(":", 1)[1])
            for section in sections:
                if any(x in section.get("content", "") for x in needles):
                    issue["section_id"] = section["section_id"]
                    break
    return validation


def _apply_case_replacements(
    replacements: List[Dict[str, Any]], selected_cases: Dict[str, Any],
    argument_plan: Dict[str, Any], outline: Dict[str, Any],
    evidence: Dict[str, Any],
    synthetic_validation_artifact: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Replace weak/misaligned cases and propagate to plan/outline/sections."""
    cases = list(selected_cases.get("cases", []))
    case_by_id = {str(x.get("case_id")): x for x in cases}
    claims_by_id = {x["claim_id"]: x for x in argument_plan.get("claims", [])}
    affected_sections: set = set()
    performed: List[Dict[str, Any]] = []
    for replacement in replacements:
        old_id = str(replacement.get("case_id") or "")
        old = case_by_id.get(old_id)
        if not old:
            continue
        claim_ids = [str(x) for x in old.get("supports_claims") or []]
        new_candidate = academic_quality.select_replacement_case(
            old_id, claim_ids, selected_cases, argument_plan, evidence,
            synthetic_validation_artifact)
        if not new_candidate:
            continue
        new_id = str(new_candidate["case_id"])
        if new_id in case_by_id:
            continue
        new_case = {
            **new_candidate,
            "supports_claims": sorted(set(claim_ids)),
            "research_questions": sorted(set(old.get("research_questions") or [])),
            "selection_rationale": (
                f"replacement of {old_id}: {replacement.get('reason', '')[:160]}"),
        }
        cases = [new_case if str(x.get("case_id")) == old_id else x for x in cases]
        case_by_id = {str(x.get("case_id")): x for x in cases}
        for claim_id in claim_ids:
            claim = claims_by_id.get(claim_id)
            if not claim:
                continue
            project = claim.get("project_evidence") or []
            claim["project_evidence"] = [
                new_id if str(x) == old_id else x for x in project]
        for section in outline.get("sections", []):
            section_cases = section.get("cases") or []
            if old_id in section_cases:
                section["cases"] = [new_id if x == old_id else x for x in section_cases]
                affected_sections.add(str(section["section_id"]))
        performed.append({
            "old_case_id": old_id, "new_case_id": new_id,
            "claim_ids": claim_ids, "reason": replacement.get("reason", ""),
            "issue_id": replacement.get("issue_id", ""),
        })
    selected_cases["cases"] = cases
    return selected_cases, argument_plan, outline, performed


def _run_quality_repair_round(
    written: List[Dict[str, Any]], report_md: str, evidence: Dict[str, Any],
    research_model: Dict[str, Any], argument_plan: Dict[str, Any],
    selected_cases: Dict[str, Any], outline: Dict[str, Any],
    literature_sources_artifact: Dict[str, Any],
    literature_evidence_artifact: Dict[str, Any],
    literature_claims_artifact: Dict[str, Any],
    synthetic_validation_artifact: Dict[str, Any],
    case_analysis_plans: Dict[str, Any],
    human_evidence_entries: Iterable[Dict[str, Any]],
    quality: Dict[str, Any], validation: Dict[str, Any],
    prior_summaries: List[Dict[str, str]],
    call_llm: Callable, provider: str, api_key: str, model: str,
) -> Tuple[List[Dict[str, Any]], str, Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any], List[Dict[str, Any]],
           List[Dict[str, Any]]]:
    """One bounded quality-repair round: replace weak cases, rewrite affected
    sections, re-validate and re-review. Returns updated artifacts and the
    round ledger (before/after hashes)."""
    plan = academic_quality.quality_repair_plan(quality, outline)
    affected_sections: set = set()
    performed_replacements: List[Dict[str, Any]] = []
    if plan["case_replacements"]:
        selected_cases, argument_plan, outline, performed = _apply_case_replacements(
            plan["case_replacements"], selected_cases, argument_plan, outline, evidence,
            synthetic_validation_artifact)
        performed_replacements = performed
        new_ids = {x["new_case_id"] for x in performed}
        affected_sections.update(
            str(x["section_id"]) for x in outline.get("sections", [])
            if new_ids & set(x.get("cases") or []))
    text_by_section: Dict[str, List[Dict[str, Any]]] = {}
    for item in plan["text_repairs"]:
        if item["repair_action"] == "remove":
            continue
        text_by_section.setdefault(item["section_id"], []).append(item)
    affected_sections.update(text_by_section)
    affected_sections = {x for x in affected_sections if x}

    by_id = {x["section_id"]: x for x in written}
    plan_by_id = {x["section_id"]: x for x in outline.get("sections", [])}
    round_ledger: List[Dict[str, Any]] = []
    for sid in sorted(affected_sections):
        if sid not in plan_by_id:
            continue
        packet = _section_packet(
            plan_by_id[sid], research_model, argument_plan, selected_cases, evidence,
            outline, prior_summaries, literature_sources_artifact,
            literature_evidence_artifact, literature_claims_artifact,
            case_analysis_plans)
        issues = [x for x in plan["text_repairs"] if x.get("section_id") == sid]
        # Merge current deterministic validation errors so a quality rewrite
        # cannot silently drop markers, quotes or statistic placeholders.
        validation_errors = [x for x in (validation.get("issues") or [])
                             if x.get("severity") == "error"
                             and str(x.get("section_id")) == sid]
        seen = {x.get("issue_id") for x in issues}
        for issue in validation_errors:
            if issue.get("issue_id") not in seen:
                issues.append(issue)
                seen.add(issue.get("issue_id"))
        old_content = by_id[sid]["content"]
        new_content = _write_section(
            packet, call_llm, provider, api_key, model,
            repair_issues=issues, existing=old_content)
        by_id[sid]["content"] = new_content
        by_id[sid]["summary"] = re.sub(r"<!--.*?-->", "", new_content)[:240]
        by_id[sid]["provenance"] = _packet_provenance(packet)
        round_ledger.append({
            "section_id": sid,
            "issue_ids": [x.get("issue_id") for x in issues],
            "before_hash": academic_evidence.stable_hash(old_content),
            "after_hash": academic_evidence.stable_hash(new_content),
            "repaired_at": _now(),
        })
    written = [by_id[x["section_id"]] for x in outline.get("sections", [])]
    report_md = _compose_report(written)
    report_md = finalize_report_tokens(report_md, evidence, selected_cases, outline)
    validation = academic_validator.validate_academic_report(
        report_md, evidence, research_model, argument_plan, selected_cases, outline,
        literature_sources_artifact, literature_evidence_artifact,
        literature_claims_artifact, human_evidence_entries,
        synthetic_validation_artifact)
    validation = _locate_validation_issues(validation, written)
    review = _semantic_review(
        report_md, research_model, argument_plan, outline, selected_cases,
        call_llm, provider, api_key, model)
    literature_review = _literature_support_review(
        report_md, argument_plan, outline, literature_sources_artifact,
        literature_evidence_artifact, literature_claims_artifact,
        call_llm, provider, api_key, model)
    quality = academic_quality.evaluate_quality(
        research_model, argument_plan, selected_cases, outline, written, evidence,
        literature_sources_artifact, literature_evidence_artifact,
        literature_claims_artifact, validation, call_llm, provider, api_key, model,
        case_analysis_plans)
    return (written, report_md, validation, review, literature_review, quality,
            performed_replacements, round_ledger)


def _quality_status(
    validation: Dict[str, Any], review: Dict[str, Any], evidence: Dict[str, Any],
    literature_sources_artifact: Dict[str, Any],
    literature_evidence_artifact: Dict[str, Any],
    literature_claims_artifact: Dict[str, Any],
    literature_support_review: Dict[str, Any], argument_plan: Dict[str, Any],
) -> Tuple[str, Dict[str, str]]:
    sources = literature_sources_artifact.get("sources") or []
    lit_items = [x for x in literature_evidence_artifact.get("items") or []
                 if x.get("eligible_for_claim")]
    lit_claims = literature_claims_artifact.get("items") or []
    if not sources:
        metadata_status = grounding_status = "not_applicable"
    else:
        metadata_status = "pass" if all(
            x.get("verification_status") == "metadata_verified"
            and (x.get("allowed_citation_status") != "allowed"
                 or x.get("citation_allowed"))
            for x in sources) else "pass_with_warnings"
        if not lit_items or not lit_claims:
            grounding_status = "pass_with_warnings"
        elif any(x.get("evidence_grounded_status") == "needs_review" for x in lit_claims):
            grounding_status = "review_required"
        else:
            grounding_status = "pass"
    dimensions = {
        "project_evidence": "pass" if evidence.get(
            "project_evidence", {}).get("segments") else "fail",
        "literature_metadata": metadata_status,
        "literature_grounding": grounding_status,
        "argument_support": "fail" if any(
            x.get("support_category") in {"literature_supported", "mixed_evidence"}
            and not (x.get("literature_claims") and x.get("literature_evidence"))
            for x in argument_plan.get("claims", [])) else "pass",
        "citation_validation": academic_validator.citation_validation_status(
            validation, literature_sources_artifact, literature_evidence_artifact,
            literature_claims_artifact),
        "statistics_validation": academic_validator.statistics_validation_status(
            validation),
        "case_eligibility": academic_validator.case_eligibility_status(validation),
        "template_compliance": (validation.get("template_compliance") or {}).get(
            "status", "not_configured"),
        "deterministic_validation": validation.get("status", "fail"),
        "general_review": review.get("status", "review_required"),
        "literature_support_review": literature_support_review.get(
            "status", "not_applicable"),
    }
    template_status = dimensions["template_compliance"]
    if validation.get("status") == "fail" or template_status == "fail":
        return "fail", dimensions
    if template_status == "review_required" or review.get("status") == "review_required" \
            or grounding_status == "review_required" \
            or literature_support_review.get("status") == "review_required":
        return "review_required", dimensions
    if validation.get("status") == "pass_with_warnings" or template_status == "pass_with_warnings" \
            or review.get("issues") \
            or evidence.get("limitations") or metadata_status == "pass_with_warnings" \
            or grounding_status == "pass_with_warnings" \
            or literature_support_review.get("issues"):
        return "pass_with_warnings", dimensions
    return "pass", dimensions


def _legacy_backup(state: Dict[str, Any], artifact_dir: Path) -> None:
    academic = _state(state)
    if academic["artifacts"] or not (state.get("p3_md") or state.get("p3_sections")):
        return
    path = artifact_dir / "legacy-report-before-academic-v1.md"
    if not path.exists() and state.get("p3_md"):
        path.write_text(state["p3_md"], encoding="utf-8")
    sections_path = artifact_dir / "legacy-report-sections-before-academic-v1.json"
    if not sections_path.exists() and state.get("p3_sections"):
        _write_json(sections_path, {"sections": state["p3_sections"]})
    state["p3_md"] = ""
    state["p3_sections"] = []
    state["p3_done"] = False
    academic["stale_reasons"].append("legacy prompt-only report invalidated and backed up")


def run_academic_pipeline(
    state: Dict[str, Any], job_id: str, theory: str,
    provider: str, api_key: str, model: str, artifact_dir: Path,
    call_llm: Callable, save_state: Callable[[Dict[str, Any]], None],
    research_settings: Optional[Dict[str, Any]] = None,
    literature_sources: Optional[Iterable[Dict[str, Any]]] = None,
    on_status: Optional[Callable[[str], None]] = None,
    auto_repair_rounds: int = 1,
    auto_quality_repair_rounds: int = 1,
    human_evidence_sources: Optional[Iterable[Dict[str, Any]]] = None,
) -> str:
    """Run or resume the complete academic evidence-to-repair pipeline."""
    artifact_dir = Path(artifact_dir)
    academic = _state(state)
    validation_runs: List[Dict[str, Any]] = []
    quality_runs: List[Dict[str, Any]] = []
    _legacy_backup(state, artifact_dir)
    sync_versions(state)
    academic.update(status="in_progress", last_error="", updated_at=_now())
    settings, literature = prepare_academic_inputs(
        state, theory, research_settings, literature_sources)
    human_entries = list(
        human_evidence_sources if human_evidence_sources is not None
        else state.get("human_evidence") or [])
    state["human_evidence"] = human_entries

    def stage(name: str, label: str) -> None:
        academic["current_stage"] = name
        academic["status"] = "in_progress"
        if on_status:
            on_status(label)
        save_state(state)

    try:
        stage("evidence", "【学术写作 1/11】构建全语料项目证据库...")
        evidence_new = academic_evidence.build_academic_evidence(
            state, job_id)
        evidence_dep = academic_evidence.stable_hash({
            "translation": evidence_new["content_hash"],
            "version": VERSIONS["evidence_version"],
        })
        evidence = _load_valid_artifact(state, artifact_dir, "evidence", evidence_dep,
                                        VERSIONS["evidence_version"])
        if evidence is None:
            evidence = _save_artifact(state, artifact_dir, "evidence", evidence_new,
                                      evidence_dep, VERSIONS["evidence_version"])

        legacy_recovery: Dict[str, Any] = {
            "schema_version": VERSIONS["legacy_recovery_version"],
            "pipeline_status": "not_configured", "metrics": {}, "items": [],
            "content_hash": academic_evidence.stable_hash([]),
        }
        legacy_document = str(settings.get("legacy_case_document") or
                              settings.get("legacy_case_document_path") or "").strip()
        if legacy_document:
            stage("legacy_case_inventory", "【学术写作】恢复旧论文中的分析案例...")
            legacy_path = Path(legacy_document).expanduser().resolve()
            if not legacy_path.is_file():
                raise FileNotFoundError(f"legacy case document not found: {legacy_path}")
            inventory_new = legacy_cases.parse_legacy_case_inventory(legacy_path)
            inventory_dep = academic_evidence.stable_hash({
                "document": str(legacy_path),
                "size": legacy_path.stat().st_size,
                "mtime_ns": legacy_path.stat().st_mtime_ns,
                "version": VERSIONS["legacy_inventory_version"],
            })
            legacy_inventory = _load_valid_artifact(
                state, artifact_dir, "legacy_inventory", inventory_dep,
                VERSIONS["legacy_inventory_version"])
            if legacy_inventory is None:
                legacy_inventory = _save_artifact(
                    state, artifact_dir, "legacy_inventory", inventory_new,
                    inventory_dep, VERSIONS["legacy_inventory_version"])
            qa_case_ids = {"TD-0126", "TD-0047", "TD-0003"}
            qa_source_ids = {str(item.get("source_segment_id") or "")
                             for item in evidence.get(
                                 "translation_decision_candidates") or []
                             if str(item.get("case_id") or "") in qa_case_ids}
            manual_review_value = str(settings.get(
                "legacy_case_manual_review") or "").strip()
            manual_review_path = Path(manual_review_value).expanduser().resolve() \
                if manual_review_value else None
            recovery_dep = academic_evidence.stable_hash({
                "inventory": legacy_inventory["content_hash"],
                "evidence": evidence["content_hash"],
                "qa_source_ids": sorted(qa_source_ids),
                "manual_review": ({
                    "path": str(manual_review_path),
                    "size": manual_review_path.stat().st_size,
                    "mtime_ns": manual_review_path.stat().st_mtime_ns,
                } if manual_review_path and manual_review_path.is_file() else None),
                "version": VERSIONS["legacy_recovery_version"],
            })
            legacy_recovery = _load_valid_artifact(
                state, artifact_dir, "legacy_recovery", recovery_dep,
                VERSIONS["legacy_recovery_version"])
            if legacy_recovery is None:
                legacy_recovery = legacy_cases.recover_legacy_cases(
                    legacy_inventory, evidence, call_llm, provider, api_key, model,
                    qa_source_segment_ids=qa_source_ids)
                if manual_review_path and manual_review_path.is_file():
                    manual_review = _read_json(manual_review_path) or {}
                    legacy_recovery = legacy_cases.apply_manual_reviews(
                        legacy_recovery, manual_review)
                legacy_recovery = _save_artifact(
                    state, artifact_dir, "legacy_recovery", legacy_recovery,
                    recovery_dep, VERSIONS["legacy_recovery_version"])
            recovery_report_path = artifact_dir / "legacy-case-recovery-report.md"
            recovery_report_path.write_text(
                legacy_cases.recovery_report_markdown(legacy_recovery), encoding="utf-8")
            _state(state)["artifacts"]["legacy_recovery_report"] = {
                "file": recovery_report_path.name,
                "version": VERSIONS["legacy_recovery_version"],
                "updated_at": _now(),
            }

        synthetic_policy = str(settings.get("case_selection_policy") or "mixed")
        if synthetic_policy not in {"authentic_only", "synthetic_only", "mixed"}:
            synthetic_policy = "mixed"
        synthetic_enabled = synthetic_policy != "authentic_only"
        pause_new_synthetic = bool(settings.get("pause_new_synthetic_generation"))
        max_scan = max(1, int(settings.get("synthetic_max_scan") or 16))
        max_opportunities = max(1, int(settings.get(
            "synthetic_max_opportunities") or 8))
        report_policy = thesis_constraints.case_policy(settings)
        if report_policy.get("report_stage") == "final_report" and synthetic_enabled \
                and not pause_new_synthetic:
            # Final cases cannot fall back to decision-only examples. Give the
            # four-gate pipeline a bounded replacement pool larger than the
            # requested portfolio; rejected baselines are never repaired in place.
            candidate_pool_size = len(evidence.get("candidate_cases") or []) + len(
                evidence.get("translation_decision_candidates") or [])
            requested_target = int(report_policy.get("target_cases") or 24)
            generation_budget = min(
                max(candidate_pool_size, 1), max(requested_target + 8, requested_target * 3))
            max_scan = max(max_scan, generation_budget)
            max_opportunities = max(max_opportunities, generation_budget)

        stage("synthetic_opportunities", "【学术写作】挖掘合成对比案例的翻译难点...")
        synthetic_opportunity_dep = academic_evidence.stable_hash({
            "evidence": evidence["content_hash"], "enabled": synthetic_enabled,
            "max_scan": max_scan, "max_opportunities": max_opportunities,
            "version": VERSIONS["synthetic_opportunity_version"],
        })
        synthetic_opportunities = _load_valid_artifact(
            state, artifact_dir, "synthetic_opportunities", synthetic_opportunity_dep,
            VERSIONS["synthetic_opportunity_version"])
        if synthetic_opportunities is None:
            synthetic_opportunities = synthetic_cases.mine_error_opportunities(
                evidence, call_llm, provider, api_key, model, max_scan, max_opportunities) \
                if synthetic_enabled and not pause_new_synthetic else {
                    "schema_version": VERSIONS["synthetic_opportunity_version"],
                    "items": [], "content_hash": academic_evidence.stable_hash([]),
                    "total_source_segments": len(evidence.get(
                        "project_evidence", {}).get("segments", [])),
                    "screened_segments": 0, "opportunities_found": 0,
                }
            synthetic_opportunities = _save_artifact(
                state, artifact_dir, "synthetic_opportunities", synthetic_opportunities,
                synthetic_opportunity_dep, VERSIONS["synthetic_opportunity_version"])

        stage("synthetic_baselines", "【学术写作】生成分析用模拟初译...")
        synthetic_baseline_dep = academic_evidence.stable_hash({
            "opportunities": synthetic_opportunities["content_hash"],
            "version": VERSIONS["synthetic_baseline_version"],
        })
        synthetic_baselines = _load_valid_artifact(
            state, artifact_dir, "synthetic_baselines", synthetic_baseline_dep,
            VERSIONS["synthetic_baseline_version"])
        if synthetic_baselines is None:
            synthetic_baselines = synthetic_cases.generate_baselines(
                synthetic_opportunities, call_llm, provider, api_key, model) \
                if not pause_new_synthetic else {
                    "schema_version": VERSIONS["synthetic_baseline_version"],
                    "items": [], "generated": 0, "pipeline_status": "paused",
                    "content_hash": academic_evidence.stable_hash([]),
                }
            synthetic_baselines = _save_artifact(
                state, artifact_dir, "synthetic_baselines", synthetic_baselines,
                synthetic_baseline_dep, VERSIONS["synthetic_baseline_version"])

        stage("synthetic_error_manifest", "【学术写作】独立检查模拟初译并诊断错误...")
        synthetic_error_dep = academic_evidence.stable_hash({
            "baselines": synthetic_baselines["content_hash"],
            "version": VERSIONS["synthetic_error_manifest_version"],
        })
        synthetic_error_manifest = _load_valid_artifact(
            state, artifact_dir, "synthetic_error_manifest", synthetic_error_dep,
            VERSIONS["synthetic_error_manifest_version"])
        if synthetic_error_manifest is None:
            synthetic_error_manifest = synthetic_cases.build_error_manifest(
                synthetic_baselines, call_llm, provider, api_key, model) \
                if not pause_new_synthetic else {
                    "schema_version": VERSIONS["synthetic_error_manifest_version"],
                    "items": [], "pipeline_status": "paused",
                    "content_hash": academic_evidence.stable_hash([]),
                }
            synthetic_error_manifest = _save_artifact(
                state, artifact_dir, "synthetic_error_manifest",
                synthetic_error_manifest, synthetic_error_dep,
                VERSIONS["synthetic_error_manifest_version"])

        stage("synthetic_optimization", "【学术写作】绑定项目当前正式译文并进行对照...")
        synthetic_optimizer_dep = _synthetic_optimizer_dependency_hash(
            synthetic_error_manifest, evidence)
        synthetic_optimized = _load_valid_artifact(
            state, artifact_dir, "synthetic_optimized", synthetic_optimizer_dep,
            VERSIONS["synthetic_optimizer_version"])
        if synthetic_optimized is None:
            synthetic_optimized = synthetic_cases.optimize_translations(
                synthetic_error_manifest, call_llm, provider, api_key, model,
                evidence.get("project_evidence", {}).get("glossary", []),
                evidence=evidence) if not pause_new_synthetic else {
                    "schema_version": VERSIONS["synthetic_optimizer_version"],
                    "items": [], "pipeline_status": "paused",
                    "content_hash": academic_evidence.stable_hash([]),
                }
            synthetic_optimized = _save_artifact(
                state, artifact_dir, "synthetic_optimized", synthetic_optimized,
                synthetic_optimizer_dep, VERSIONS["synthetic_optimizer_version"])

        stage("synthetic_validation", "【学术写作】独立验证错误实质性与修复有效性...")
        synthetic_validation_dep = academic_evidence.stable_hash({
            "optimized": synthetic_optimized["content_hash"],
            "version": VERSIONS["synthetic_validation_version"],
        })
        synthetic_validation = _load_valid_artifact(
            state, artifact_dir, "synthetic_validation", synthetic_validation_dep,
            VERSIONS["synthetic_validation_version"])
        if synthetic_validation is None:
            synthetic_validation = synthetic_cases.validate_synthetic_cases(
                synthetic_optimized, call_llm, provider, api_key, model, evidence) \
                if not pause_new_synthetic else {
                    "schema_version": VERSIONS["synthetic_validation_version"],
                    "items": [], "metrics": {}, "pipeline_status": "paused",
                    "content_hash": academic_evidence.stable_hash([]),
                }
            synthetic_validation = _save_artifact(
                state, artifact_dir, "synthetic_validation", synthetic_validation,
                synthetic_validation_dep, VERSIONS["synthetic_validation_version"])

        stage("literature_evidence", "【学术写作 2/11】固化文献来源与逐字证据...")
        literature_sources_new = literature_evidence.build_literature_sources(literature)
        literature_sources_dep = academic_evidence.stable_hash({
            "source_snapshot": literature_sources_new["content_hash"],
            "version": VERSIONS["literature_sources_version"],
        })
        literature_sources_artifact = _load_valid_artifact(
            state, artifact_dir, "literature_sources", literature_sources_dep,
            VERSIONS["literature_sources_version"])
        if literature_sources_artifact is None:
            literature_sources_artifact = _save_artifact(
                state, artifact_dir, "literature_sources", literature_sources_new,
                literature_sources_dep, VERSIONS["literature_sources_version"])

        literature_evidence_new = literature_evidence.build_literature_evidence(
            literature_sources_artifact)
        literature_evidence_dep = academic_evidence.stable_hash({
            "source_content": literature_sources_artifact["sources_content_hash"],
            "version": VERSIONS["literature_evidence_version"],
        })
        literature_evidence_artifact = _load_valid_artifact(
            state, artifact_dir, "literature_evidence", literature_evidence_dep,
            VERSIONS["literature_evidence_version"])
        if literature_evidence_artifact is None:
            literature_evidence_artifact = _save_artifact(
                state, artifact_dir, "literature_evidence", literature_evidence_new,
                literature_evidence_dep, VERSIONS["literature_evidence_version"])

        stage("research_model", "【学术写作 3/11】建立研究问题与理论框架...")
        model_new = build_research_model(evidence, theory, settings)
        research_dep = academic_evidence.stable_hash({
            "settings": model_new["content_hash"], "evidence_profile":
            evidence.get("project_evidence", {}).get("document_profile"),
            "version": VERSIONS["research_model_version"],
        })
        research_model = _load_valid_artifact(
            state, artifact_dir, "research_model", research_dep,
            VERSIONS["research_model_version"])
        if research_model is None:
            research_model = _save_artifact(
                state, artifact_dir, "research_model", model_new, research_dep,
                VERSIONS["research_model_version"])

        stage("literature_claims", "【学术写作 4/11】从文献证据抽取受限主张...")
        literature_claims_dep = academic_evidence.stable_hash({
            "evidence": literature_evidence_artifact["content_hash"],
            "version": VERSIONS["literature_claims_version"],
        })
        literature_claims_artifact = _load_valid_artifact(
            state, artifact_dir, "literature_claims", literature_claims_dep,
            VERSIONS["literature_claims_version"])
        if literature_claims_artifact is None:
            literature_claims_new = literature_evidence.build_literature_claims(
                literature_sources_artifact, literature_evidence_artifact,
                call_llm, provider, api_key, model)
            literature_claims_artifact = _save_artifact(
                state, artifact_dir, "literature_claims", literature_claims_new,
                literature_claims_dep, VERSIONS["literature_claims_version"])

        stage("argument_plan", "【学术写作 5/11】规划研究论点与证据关系...")
        argument_dep = academic_evidence.stable_hash({
            "evidence": evidence["content_hash"], "research": research_model["content_hash"],
            "literature_source_policy": literature_sources_artifact[
                "sources_metadata_hash"],
            "literature_evidence": literature_evidence_artifact["content_hash"],
            "literature_claims": literature_claims_artifact["content_hash"],
            "human_evidence": human_evidence.evidence_hash(human_entries),
            "version": VERSIONS["argument_plan_version"],
        })
        argument_plan = _load_valid_artifact(
            state, artifact_dir, "argument_plan", argument_dep,
            VERSIONS["argument_plan_version"])
        if argument_plan is None:
            argument_plan = build_argument_plan(
                research_model, evidence, call_llm, provider, api_key, model,
                literature_sources_artifact, literature_evidence_artifact,
                literature_claims_artifact, human_entries)
            argument_plan = _save_artifact(
                state, artifact_dir, "argument_plan", argument_plan, argument_dep,
                VERSIONS["argument_plan_version"])

        report_case_policy = {
            **thesis_constraints.case_policy(settings),
            **dict((research_model.get("report_constraints") or {}).get(
                "case_policy") or {}),
        }
        report_stage = str(report_case_policy.get("report_stage") or "final_report")
        template_requirement = (
            ((research_model.get("template_contract") or {}).get(
                "document_structure") or {}).get("case_requirement") or {})
        template_case_minimum = int(template_requirement.get("minimum_cases") or 0) \
            if template_requirement.get("applies_to_report_stage") == report_stage else 0
        effective_case_limit = max(
            1, int(settings.get(f"{report_stage}_target_cases") or
                   report_case_policy.get("target_cases") or 1),
            template_case_minimum)
        combined_synthetic = legacy_cases.merge_synthetic_artifacts(
            legacy_recovery, synthetic_validation)
        case_dep = academic_evidence.stable_hash({
            "argument": argument_plan["content_hash"], "evidence": evidence["content_hash"],
            "synthetic": combined_synthetic["content_hash"],
            "policy": synthetic_policy,
            "limit": effective_case_limit,
            "report_case_policy": report_case_policy,
            "version": VERSIONS["case_selection_version"],
        })
        stale_case_ids = {
            str(record.get("artifact_id", "").split(":", 1)[-1])
            for name, record in _artifact_records(state).items()
            if name.startswith("case:") and record.get("status") == "stale"
        }
        selected_cases = _load_valid_artifact(
            state, artifact_dir, "selected_cases", case_dep,
            VERSIONS["case_selection_version"])
        if selected_cases is None:
            selected_cases = select_academic_cases(
                research_model, argument_plan, evidence,
                limit=effective_case_limit,
                synthetic_artifact=combined_synthetic, policy=synthetic_policy,
                preferred_authentic_count=max(1, int(settings.get(
                    "preferred_authentic_case_count") or 3)),
                minimum_authentic_count=max(1, int(settings.get(
                    "minimum_authentic_case_count") or 2)),
                report_case_policy=report_case_policy)
            selected_cases = _save_artifact(
                state, artifact_dir, "selected_cases", selected_cases, case_dep,
                VERSIONS["case_selection_version"])
        # Human case decisions live in state.json, while the generated
        # selection artifact remains the reproducible candidate record.  Apply
        # the overlay before every downstream consumer so approval/exclusion
        # is visible without ever changing case_origin or text_role.
        selected_cases = apply_case_review_overlays(selected_cases, state)

        if report_stage == "final_report":
            portfolio_path = artifact_dir / "final-contrast-case-portfolio.md"
            portfolio_path.write_text(
                final_contrast_portfolio_markdown(selected_cases), encoding="utf-8")
            _state(state)["artifacts"]["final_contrast_portfolio"] = {
                "file": portfolio_path.name,
                "version": "final-contrast-portfolio-v1",
                "updated_at": _now(),
            }

            # A final report must not be rendered in a knowingly incomplete
            # case shape.  The portfolio preview remains available for
            # replacement-candidate review; Chapter 3 and DOCX generation
            # stop here until the hard contrast contract is satisfied.
            if report_policy.get("contrast_required"):
                final_count = int(selected_cases.get("final_case_count") or 0)
                contrast_count = int(selected_cases.get(
                    "contrast_ready_case_count") or 0)
                minimum = int(report_policy.get("minimum_cases") or 20)
                decision_visible = int(selected_cases.get(
                    "translation_decision_visible_count") or 0)
                countable_count = int(selected_cases.get(
                    "final_countable_case_count", selected_cases.get(
                        "countable_case_count", final_count)) or 0)
                if countable_count < minimum or contrast_count != final_count \
                        or decision_visible:
                    message = (
                        f"Final Report case contract blocked: final={final_count}, "
                        f"countable={countable_count}, "
                        f"contrast_ready={contrast_count}, minimum={minimum}, "
                        f"translation_decision_visible={decision_visible}."
                    )
                    academic.update(
                        status="blocked", quality_status="fail",
                        current_stage="final_case_policy_gate",
                        report_status="blocked_final_case_policy",
                        last_error=message, updated_at=_now())
                    state["report_status"] = "blocked_final_case_policy"
                    state["p3_done"] = False
                    save_state(state)
                    return ""

        # Role assignment happens inside case selection, after the argument
        # planner has named candidates. Rebind major claims to the final
        # selected core portfolio before any downstream artifact consumes the
        # plan, preventing stale candidate IDs from reaching the outline,
        # report, or validator.
        argument_plan, plan_changed = _reconcile_argument_plan_with_portfolio(
            argument_plan, selected_cases)
        if plan_changed:
            argument_plan = _save_artifact(
                state, artifact_dir, "argument_plan", argument_plan, argument_dep,
                VERSIONS["argument_plan_version"])
            case_dep = academic_evidence.stable_hash({
                "argument": argument_plan["content_hash"],
                "evidence": evidence["content_hash"],
                "synthetic": combined_synthetic["content_hash"],
                "policy": synthetic_policy,
                "limit": effective_case_limit,
                "report_case_policy": report_case_policy,
                "version": VERSIONS["case_selection_version"],
            })
            selected_cases = _save_artifact(
                state, artifact_dir, "selected_cases", selected_cases, case_dep,
                VERSIONS["case_selection_version"])
            save_state(state)

        stage("case_analysis", "【学术写作】规划案例分析证据契约（提纲子步骤）...")
        human_evidence_artifact = {
            "schema_version": VERSIONS["human_evidence_version"],
            "items": human_entries,
        }
        human_evidence_artifact["content_hash"] = academic_evidence.stable_hash(
            human_entries)
        _save_artifact(state, artifact_dir, "human_evidence",
                       human_evidence_artifact,
                       academic_evidence.stable_hash(human_entries),
                       VERSIONS["human_evidence_version"])
        human_evidence_hash = human_evidence.evidence_hash(human_entries)
        case_analysis_dep = academic_evidence.stable_hash({
            "evidence": evidence["content_hash"],
            "argument": argument_plan["content_hash"],
            "cases": selected_cases["content_hash"],
            "literature_claims": literature_claims_artifact["content_hash"],
            "human_evidence": human_evidence_hash,
            "version": VERSIONS["case_analysis_version"],
        })
        case_plans = _load_valid_artifact(
            state, artifact_dir, "case_analysis_plans", case_analysis_dep,
            VERSIONS["case_analysis_version"])
        if case_plans is None:
            old_case_plans = _read_artifact(
                artifact_dir / ARTIFACT_FILES["case_analysis_plans"])
            case_plans = _rebuild_targeted_case_plans(
                old_case_plans, selected_cases, stale_case_ids, evidence,
                argument_plan, literature_claims_artifact,
                call_llm, provider, api_key, model, human_entries)
            if case_plans is None:
                case_plans = case_analysis.build_case_analysis_plans(
                    evidence, selected_cases, argument_plan,
                    literature_claims_artifact, call_llm, provider, api_key,
                    model, human_entries)
            case_plans = _save_artifact(
                state, artifact_dir, "case_analysis_plans", case_plans,
                case_analysis_dep, VERSIONS["case_analysis_version"])

        stage("outline", "【学术写作 6/11】生成证据约束型学术提纲...")
        outline_dep = academic_evidence.stable_hash({
            "research": research_model["content_hash"],
            "report_constraints": academic_evidence.stable_hash(
                research_model.get("report_constraints") or {}),
            "argument": argument_plan["content_hash"],
            "cases": selected_cases["content_hash"],
            "literature_claims": literature_claims_artifact["content_hash"],
            "literature_evidence": literature_evidence_artifact["content_hash"],
            "version": VERSIONS["outline_version"],
        })
        outline = _load_valid_artifact(
            state, artifact_dir, "outline", outline_dep, VERSIONS["outline_version"])
        if outline is None:
            outline = build_academic_outline(
                research_model, argument_plan, selected_cases, evidence,
                call_llm, provider, api_key, model,
                literature_sources_artifact, literature_evidence_artifact,
                literature_claims_artifact)
            outline = _save_artifact(state, artifact_dir, "outline", outline, outline_dep,
                                     VERSIONS["outline_version"])

        stage("writing", "【学术写作 7/11】按论点与分节证据撰写正文...")
        unit_plans = []
        for chapter in outline.get("sections", []):
            if str(chapter.get("role") or "") == "case_analysis":
                unit_plans.extend(_case_analysis_writing_units(
                    chapter, case_plans, selected_cases))
            else:
                unit_plans.append(dict(chapter))
        unit_keys = [_section_dependency_hash(
            unit, argument_plan, selected_cases, evidence,
            literature_sources_artifact, literature_evidence_artifact,
            literature_claims_artifact, case_plans, human_entries)
                     for unit in unit_plans]
        sections_dep = academic_evidence.stable_hash({
            "outline": outline["content_hash"], "writing_units": unit_keys,
            "writer": VERSIONS["writer_version"],
        })
        section_artifact = _load_valid_artifact(
            state, artifact_dir, "sections", sections_dep, VERSIONS["writer_version"])
        existing = (_section_cache_index(section_artifact)
                    if section_artifact else _load_reusable_sections(artifact_dir))
        forced = set(academic.get("forced_sections") or [])
        written, writing_units = _write_writing_units(
            state, artifact_dir, outline, research_model, argument_plan,
            selected_cases, evidence, literature_sources_artifact,
            literature_evidence_artifact, literature_claims_artifact, case_plans,
            human_entries, sections_dep, existing, forced, call_llm, provider,
            api_key, model, save_state, on_status)
        prior_summaries = [{"section_id": str(item.get("section_id")),
                            "summary": str(item.get("summary") or "")}
                           for item in written]
        academic["forced_sections"] = []
        report_md = _compose_report(written)
        report_md = finalize_report_tokens(report_md, evidence, selected_cases, outline)
        matter = build_report_matter(
            research_model, evidence, selected_cases,
            research_model.get("template_contract"), literature_sources_artifact)
        report_artifact = build_report_artifact(
            report_md, written, outline, research_model.get("report_constraints") or {},
            matter, selected_cases, evidence, case_plans)

        stage("validation", "【学术写作 8/11】执行确定性证据与结构验证...")
        validation = academic_validator.validate_academic_report(
            report_md, evidence, research_model, argument_plan, selected_cases, outline,
            literature_sources_artifact, literature_evidence_artifact,
            literature_claims_artifact, human_entries, combined_synthetic,
            report_artifact.get("template_contract"), report_artifact)
        validation = _locate_validation_issues(validation, written)
        validation_runs.append(validation)
        validation_dep = academic_evidence.stable_hash({
            "report": academic_evidence.stable_hash(report_md),
            "evidence": evidence["content_hash"],
            "validator": VERSIONS["validator_version"],
            "synthetic": combined_synthetic["content_hash"],
            "literature_sources": literature_sources_artifact["content_hash"],
            "literature_evidence": literature_evidence_artifact["content_hash"],
            "literature_claims": literature_claims_artifact["content_hash"],
        })
        validation_checkpoint = {**validation, "runs": validation_runs[-2:]}
        validation_checkpoint["content_hash"] = academic_evidence.stable_hash(
            {k: v for k, v in validation_checkpoint.items() if k != "content_hash"})
        _save_artifact(state, artifact_dir, "validation", validation_checkpoint,
                       validation_dep, VERSIONS["validator_version"])

        stage("review", "【学术写作 9/11】执行独立语义与文献支持审稿...")
        review_dep = academic_evidence.stable_hash({
            "report": academic_evidence.stable_hash(report_md),
            "argument": argument_plan["content_hash"],
            "reviewer": VERSIONS["reviewer_version"],
        })
        review = _load_valid_artifact(
            state, artifact_dir, "review", review_dep, VERSIONS["reviewer_version"])
        if review is None:
            review = _semantic_review(
                report_md, research_model, argument_plan, outline, selected_cases,
                call_llm, provider, api_key, model)
            _save_artifact(state, artifact_dir, "review", review, review_dep,
                           VERSIONS["reviewer_version"])
        literature_review_dep = academic_evidence.stable_hash({
            "report": academic_evidence.stable_hash(report_md),
            "argument": argument_plan["content_hash"],
            "literature_sources": literature_sources_artifact["content_hash"],
            "literature_evidence": literature_evidence_artifact["content_hash"],
            "literature_claims": literature_claims_artifact["content_hash"],
            "reviewer": VERSIONS["literature_reviewer_version"],
        })
        literature_support_review = _load_valid_artifact(
            state, artifact_dir, "literature_support_review", literature_review_dep,
            VERSIONS["literature_reviewer_version"])
        if literature_support_review is None:
            literature_support_review = _literature_support_review(
                report_md, argument_plan, outline, literature_sources_artifact,
                literature_evidence_artifact, literature_claims_artifact,
                call_llm, provider, api_key, model)
            _save_artifact(
                state, artifact_dir, "literature_support_review",
                literature_support_review, literature_review_dep,
                VERSIONS["literature_reviewer_version"])

        repair_history = {"schema_version": "academic-repair-v1", "rounds": []}
        if auto_repair_rounds > 0:
            repair_issues = [x for x in validation.get("issues", []) if x["severity"] == "error"]
            repair_issues += [x for x in review.get("issues", [])
                              if x["severity"] in ("medium", "high")]
            repair_issues += [x for x in literature_support_review.get("issues", [])
                              if x["severity"] in ("medium", "high")]
            affected = sorted({str(x.get("section_id")) for x in repair_issues
                               if x.get("section_id")})
            if affected:
                stage("repair", "【学术写作 10/11】定点修订受影响章节并重新验证...")
                by_id = {x["section_id"]: x for x in written}
                plan_by_id = {x["section_id"]: x for x in outline.get("sections", [])}
                for sid in affected:
                    if on_status:
                        on_status(f"【学术写作 10/11】正在修复第 {sid} 节...")
                    packet = _section_packet(plan_by_id[sid], research_model, argument_plan,
                                             selected_cases, evidence, outline,
                                             prior_summaries,
                                             literature_sources_artifact,
                                             literature_evidence_artifact,
                                             literature_claims_artifact, case_plans)
                    issues = [x for x in repair_issues if str(x.get("section_id")) == sid]
                    old_content = by_id[sid]["content"]
                    try:
                        missing_case_ids = sorted({
                            str(case_id) for issue in issues
                            if issue.get("type") == "case_presentation_count_mismatch"
                            for case_id in issue.get("missing_case_ids") or []})
                        available_cases = {str(item.get("case_id"))
                                           for item in packet.get("cases") or []}
                        available_analyses = {str(item.get("case_id"))
                                             for item in packet.get("case_analyses") or []}
                        available_assignments = {str(item.get("case_id"))
                                                 for item in packet.get(
                                                     "case_assignments") or []}
                        targeted_ready = set(missing_case_ids) <= (
                            available_cases & available_analyses & available_assignments)
                        case_only = missing_case_ids and all(
                            issue.get("type") in {
                                "case_presentation_count_mismatch", "missing_selected_case"}
                            for issue in issues) and targeted_ready
                        if case_only:
                            new_content = _repair_missing_case_examples(
                                old_content, packet, missing_case_ids,
                                call_llm, provider, api_key, model)
                        else:
                            new_content = _write_section(
                                packet, call_llm, provider, api_key, model,
                                repair_issues=issues, existing=old_content)
                    except Exception as exc:
                        if not _is_transient_llm_error(exc):
                            raise
                        repair_history["rounds"].append({
                            "round": 1, "section_id": sid,
                            "issue_ids": [x.get("issue_id") for x in issues],
                            "status": "deferred_external_error",
                            "reason": str(exc)[:240], "repaired_at": _now(),
                        })
                        continue
                    by_id[sid]["content"] = new_content
                    by_id[sid]["summary"] = re.sub(r"<!--.*?-->", "", new_content)[:240]
                    by_id[sid]["provenance"] = _packet_provenance(packet)
                    repair_history["rounds"].append({
                        "round": 1, "section_id": sid,
                        "issue_ids": [x.get("issue_id") for x in issues],
                        "global_claim_ids": sorted({str(x.get("global_claim_id")
                                                        or x.get("claim_id")) for x in issues
                                                    if x.get("global_claim_id")
                                                    or x.get("claim_id")}),
                        "literature_claim_ids": sorted({str(x.get(
                            "literature_claim_id")) for x in issues
                            if x.get("literature_claim_id")}),
                        "repair_actions": sorted({str(x.get("repair_action")) for x in issues
                                                  if x.get("repair_action")}),
                        "before_hash": academic_evidence.stable_hash(old_content),
                        "after_hash": academic_evidence.stable_hash(new_content),
                        "repaired_at": _now(),
                    })
                written = [by_id[x["section_id"]] for x in outline.get("sections", [])]
                section_artifact = _sections_container(written)
                section_artifact["content_hash"] = academic_evidence.stable_hash(
                    {k: v for k, v in section_artifact.items() if k != "content_hash"})
                _save_artifact(state, artifact_dir, "sections", section_artifact,
                               sections_dep, VERSIONS["writer_version"])
                report_md = _compose_report(written)
                report_md = finalize_report_tokens(report_md, evidence, selected_cases, outline)
                report_artifact = build_report_artifact(
                    report_md, written, outline,
                    research_model.get("report_constraints") or {}, matter,
                    selected_cases, evidence, case_plans)
                if on_status:
                    on_status("【学术写作 10/11】重新验证修订章节…")
                validation = academic_validator.validate_academic_report(
                    report_md, evidence, research_model, argument_plan, selected_cases, outline,
                    literature_sources_artifact, literature_evidence_artifact,
                    literature_claims_artifact, human_entries, combined_synthetic,
                    report_artifact.get("template_contract"), report_artifact)
                validation = _locate_validation_issues(validation, written)
                validation_runs.append(validation)
                if on_status:
                    on_status("【学术写作 10/11】重新执行学术复核…")
                review = _semantic_review(
                    report_md, research_model, argument_plan, outline, selected_cases,
                    call_llm, provider, api_key, model)
                literature_support_review = _literature_support_review(
                    report_md, argument_plan, outline, literature_sources_artifact,
                    literature_evidence_artifact, literature_claims_artifact,
                    call_llm, provider, api_key, model)

        validation_artifact = {**validation, "runs": validation_runs[-2:]}
        validation_artifact["content_hash"] = academic_evidence.stable_hash(
            {k: v for k, v in validation_artifact.items() if k != "content_hash"})
        validation_dep = academic_evidence.stable_hash({
            "report": academic_evidence.stable_hash(report_md),
            "evidence": evidence["content_hash"], "validator": VERSIONS["validator_version"],
            "synthetic": combined_synthetic["content_hash"],
            "literature_sources": literature_sources_artifact["content_hash"],
            "literature_evidence": literature_evidence_artifact["content_hash"],
            "literature_claims": literature_claims_artifact["content_hash"],
        })
        _save_artifact(state, artifact_dir, "validation", validation_artifact,
                       validation_dep, VERSIONS["validator_version"])
        review_dep = academic_evidence.stable_hash({
            "report": academic_evidence.stable_hash(report_md),
            "argument": argument_plan["content_hash"], "reviewer": VERSIONS["reviewer_version"],
        })
        _save_artifact(state, artifact_dir, "review", review, review_dep,
                       VERSIONS["reviewer_version"])
        literature_review_dep = academic_evidence.stable_hash({
            "report": academic_evidence.stable_hash(report_md),
            "argument": argument_plan["content_hash"],
            "literature_sources": literature_sources_artifact["content_hash"],
            "literature_evidence": literature_evidence_artifact["content_hash"],
            "literature_claims": literature_claims_artifact["content_hash"],
            "reviewer": VERSIONS["literature_reviewer_version"],
        })
        _save_artifact(state, artifact_dir, "literature_support_review",
                       literature_support_review, literature_review_dep,
                       VERSIONS["literature_reviewer_version"])
        repair_history["content_hash"] = academic_evidence.stable_hash(
            {k: v for k, v in repair_history.items() if k != "content_hash"})
        _save_artifact(state, artifact_dir, "repair_history", repair_history,
                       academic_evidence.stable_hash(repair_history["rounds"]), "academic-repair-v1")

        # ---- Academic quality evaluation + bounded structural repair ----
        stage("academic_quality", "【学术写作 11/11】评估学术质量并执行结构性修复...")
        quality_evaluation = academic_quality.evaluate_quality(
            research_model, argument_plan, selected_cases, outline, written, evidence,
            literature_sources_artifact, literature_evidence_artifact,
            literature_claims_artifact, validation, call_llm, provider, api_key, model,
            case_plans)
        quality_runs.append(quality_evaluation)
        quality_repair_history = {"schema_version": "academic-quality-repair-v1",
                                  "rounds": []}
        quality_round = 0
        while auto_quality_repair_rounds > 0 \
                and quality_round < auto_quality_repair_rounds:
            plan = academic_quality.quality_repair_plan(quality_evaluation, outline)
            if not plan["case_replacements"] and not plan["text_repairs"]:
                break
            quality_round += 1
            (written, report_md, validation, review, literature_support_review,
             quality_evaluation, performed_replacements, round_ledger) = _run_quality_repair_round(
                written, report_md, evidence, research_model, argument_plan,
                selected_cases, outline, literature_sources_artifact,
                literature_evidence_artifact, literature_claims_artifact,
                combined_synthetic, case_plans, human_entries, quality_evaluation,
                validation, prior_summaries, call_llm, provider, api_key, model)
            _save_artifact(state, artifact_dir, "selected_cases", selected_cases,
                           case_dep, VERSIONS["case_selection_version"])
            _save_artifact(state, artifact_dir, "argument_plan", argument_plan,
                           argument_dep, VERSIONS["argument_plan_version"])
            _save_artifact(state, artifact_dir, "outline", outline, outline_dep,
                           VERSIONS["outline_version"])
            section_artifact = _sections_container(written)
            section_artifact["content_hash"] = academic_evidence.stable_hash(
                {k: v for k, v in section_artifact.items() if k != "content_hash"})
            _save_artifact(state, artifact_dir, "sections", section_artifact,
                           sections_dep, VERSIONS["writer_version"])
            validation_runs.append(validation)
            quality_runs.append(quality_evaluation)
            quality_repair_history["rounds"].append({
                "round": quality_round,
                "case_replacements": performed_replacements,
                "section_rewrites": round_ledger,
                "issue_ids": [x.get("issue_id") for x in plan["case_replacements"]]
                             + [x.get("issue_id") for x in plan["text_repairs"]],
                "completed_at": _now(),
            })
        # Quality repair may change chapter text after the first validation;
        # rebuild the structured artifact and run the deterministic template
        # gate on the final report before recording completion.
        report_artifact = build_report_artifact(
            report_md, written, outline,
            research_model.get("report_constraints") or {}, matter,
            selected_cases, evidence, case_plans)
        validation = academic_validator.validate_academic_report(
            report_md, evidence, research_model, argument_plan, selected_cases, outline,
            literature_sources_artifact, literature_evidence_artifact,
            literature_claims_artifact, human_entries, combined_synthetic,
            report_artifact.get("template_contract"), report_artifact)
        validation = _locate_validation_issues(validation, written)
        validation_runs.append(validation)
        report_dep = academic_evidence.stable_hash({
            "report": report_artifact["content_hash"],
            "template": report_artifact.get("template_hash"),
            "version": VERSIONS["report_artifact_version"],
        })
        _save_artifact(state, artifact_dir, "report", report_artifact,
                       report_dep, VERSIONS["report_artifact_version"])
        validation_artifact = {**validation, "runs": validation_runs[-2:]}
        validation_artifact["content_hash"] = academic_evidence.stable_hash(
            {k: v for k, v in validation_artifact.items() if k != "content_hash"})
        validation_dep = academic_evidence.stable_hash({
            "report": academic_evidence.stable_hash(report_md),
            "evidence": evidence["content_hash"],
            "validator": VERSIONS["validator_version"],
            "template": report_artifact.get("template_hash"),
            "synthetic": combined_synthetic["content_hash"],
            "literature_sources": literature_sources_artifact["content_hash"],
            "literature_evidence": literature_evidence_artifact["content_hash"],
            "literature_claims": literature_claims_artifact["content_hash"],
        })
        _save_artifact(state, artifact_dir, "validation", validation_artifact,
                       validation_dep, VERSIONS["validator_version"])
        quality_dep = academic_evidence.stable_hash({
            "report": academic_evidence.stable_hash(report_md),
            "argument": argument_plan["content_hash"],
            "quality_version": VERSIONS["academic_quality_version"],
        })
        quality_artifact = {**quality_evaluation, "runs": quality_runs[-2:]}
        quality_artifact["content_hash"] = academic_evidence.stable_hash(
            {k: v for k, v in quality_artifact.items() if k != "content_hash"})
        _save_artifact(state, artifact_dir, "academic_quality", quality_artifact,
                       quality_dep,
                       VERSIONS["academic_quality_version"])
        (artifact_dir / "academic-quality-report.md").write_text(
            academic_quality.render_quality_report(quality_evaluation), encoding="utf-8")
        (artifact_dir / "academic-quality-findings.jsonl").write_text(
            "\n".join(json.dumps(x, ensure_ascii=False, sort_keys=True)
                      for x in quality_evaluation.get("findings", [])) + "\n",
            encoding="utf-8")
        quality_repair_history["content_hash"] = academic_evidence.stable_hash(
            {k: v for k, v in quality_repair_history.items() if k != "content_hash"})
        _save_artifact(state, artifact_dir, "quality_repair_history",
                       quality_repair_history,
                       academic_evidence.stable_hash(quality_repair_history["rounds"]),
                       "academic-quality-repair-v1")

        # ---- Human evidence needs and questions (no LLM: deterministic) ----
        needs_artifact = human_evidence.build_evidence_needs(
            evidence, case_plans, quality_evaluation)
        _save_artifact(state, artifact_dir, "human_evidence_needs", needs_artifact,
                       academic_evidence.stable_hash({
                           "case_plans": case_plans["content_hash"],
                           "quality": quality_evaluation["content_hash"],
                           "version": VERSIONS["human_evidence_version"],
                       }), VERSIONS["human_evidence_version"])
        questions_artifact = human_evidence.generate_questions(
            needs_artifact, evidence, case_plans)
        _save_artifact(state, artifact_dir, "human_evidence_questions",
                       questions_artifact,
                       academic_evidence.stable_hash({
                           "needs": needs_artifact["content_hash"],
                           "version": VERSIONS["human_evidence_version"],
                       }), VERSIONS["human_evidence_version"])
        open_questions = [q for q in questions_artifact.get("questions", [])
                          if q.get("status") == "open"]
        critical_open = [q for q in open_questions
                         if q.get("priority") == "critical"]
        human_evidence_status = {
            "cases_needing_human_evidence": len({
                q.get("case_id") for q in open_questions}),
            "questions_generated": len(open_questions),
            "critical_questions": len(critical_open),
            "unanswered": len(open_questions),
            "answered": sum(1 for q in questions_artifact.get("questions", [])
                            if q.get("status") == "answered"),
            "unavailable_after_check": sum(
                1 for x in human_entries
                if x.get("status") == "unavailable_after_human_check"),
            "conflicted": sum(1 for x in human_entries
                              if x.get("status") == "conflicted"),
            "cases_improved_after_evidence": sum(
                1 for x in human_entries if x.get("status") == "user_confirmed"),
        }
        academic["human_evidence_status"] = human_evidence_status

        quality, quality_dimensions = _quality_status(
            validation, review, evidence, literature_sources_artifact,
            literature_evidence_artifact, literature_claims_artifact,
            literature_support_review, argument_plan)
        aq_status = "pass"
        dimension_values = list((quality_evaluation.get("dimensions") or {}).values())
        if any(x == "fail" for x in dimension_values):
            aq_status = "fail"
        elif any(x == "review_required" for x in dimension_values):
            aq_status = "review_required"
        elif any(x == "pass_with_warnings" for x in dimension_values):
            aq_status = "pass_with_warnings"
        if critical_open:
            aq_status = "review_required"
        template_status = (validation.get("template_compliance") or {}).get(
            "status", "not_configured")
        literature_required = (
            str((research_model.get("report_constraints") or {}).get(
                "report_stage") or "final_report") == "final_report"
            and not (literature_sources_artifact.get("sources") or []))
        if template_status == "fail":
            report_status = "failed_template_validation"
        elif validation.get("status") == "fail" or quality == "fail" \
                or aq_status == "fail":
            report_status = "incomplete"
        elif literature_required:
            report_status = "literature_required"
        elif quality == "review_required" or aq_status == "review_required" \
                or template_status == "review_required" or critical_open:
            report_status = "review_required"
        else:
            report_status = "generated"
        report_artifact.update(
            report_status=report_status,
            template_compliance=template_status,
            validation_status=validation.get("status", "fail"),
            quality_status=quality,
        )
        report_artifact["content_hash"] = academic_evidence.stable_hash(
            {k: v for k, v in report_artifact.items() if k != "content_hash"})
        report_dep = academic_evidence.stable_hash({
            "report": report_artifact["content_hash"],
            "template": report_artifact.get("template_hash"),
            "version": VERSIONS["report_artifact_version"],
        })
        _save_artifact(state, artifact_dir, "report", report_artifact,
                       report_dep, VERSIONS["report_artifact_version"])
        warning_md = academic_validator.render_warnings_markdown(
            validation, review, literature_support_review, evidence, quality_dimensions)
        (artifact_dir / "academic-evidence-warnings.md").write_text(
            warning_md, encoding="utf-8")
        state["p3_md"] = report_md
        state["p3_sections"] = [[x["title"], x["content"]] for x in written]
        state["p3_done"] = True
        state["report_status"] = report_status
        state["theory"] = theory
        completion_stage = {
            "fail": "validation_failed",
            "review_required": "review_required",
        }.get(quality, "completed")
        academic.update(
            status=quality, quality_status=quality, current_stage=completion_stage,
            quality_dimensions=quality_dimensions,
            academic_quality_status=aq_status,
            report_status=report_status,
            last_error="", updated_at=_now(),
            warnings_file="academic-evidence-warnings.md",
            quality_report_file="academic-quality-report.md",
        )
        save_state(state)
        return report_md
    except Exception as exc:
        academic.update(status="failed", quality_status="fail",
                        last_error=str(exc)[:500], updated_at=_now())
        state["p3_done"] = False
        save_state(state)
        raise RuntimeError(f"学术写作阶段失败：{exc}") from exc
