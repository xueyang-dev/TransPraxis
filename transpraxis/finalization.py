"""Small, durable state helpers for the MTI finalization workspace.

This module deliberately stays close to the existing ``state.json`` and
academic-artifact records.  It does not introduce a second graph or a
database; it gives the UI and the business layer one vocabulary for the
states that v0.4 must make visible.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Sequence

from . import case_provenance


VERSION = "finalization-state-v1"
CURRENT_TRANSLATION = "CURRENT_TRANSLATION"
REAL_REVISION = case_provenance.REAL_REVISION
SYNTHETIC_BASELINE = case_provenance.SYNTHETIC_BASELINE

QA_FIELDS = (
    "structural_qa",
    "libreoffice_render",
    "author_visual_review",
    "word_final_review",
)

QA_DEFAULTS = {
    "structural_qa": "NOT_RUN",
    "libreoffice_render": "NOT_RUN",
    "author_visual_review": "NOT_CONFIRMED",
    "word_final_review": "NOT_CONFIRMED",
}

ARTIFACT_LABELS = {
    "evidence": "项目证据库",
    "synthetic_opportunities": "合成案例机会",
    "synthetic_baselines": "合成基线",
    "synthetic_error_manifest": "合成错误清单",
    "synthetic_optimized": "合成优化译文",
    "synthetic_validation": "合成案例验证",
    "research_model": "研究模型",
    "argument_plan": "论证计划",
    "selected_cases": "案例选择",
    "case_analysis_plans": "案例分析计划",
    "outline": "报告提纲",
    "sections": "写作单元",
    "report": "报告稿",
    "validation": "结构与证据验证",
    "review": "独立语义复核",
    "literature_support_review": "文献支持复核",
    "academic_quality": "学术质量评估",
    "compliance": "学校合规结果",
    "language_constraints": "项目语言约束",
    "report_qa": "报告 QA",
    "final_docx_validation": "DOCX 结构验证",
    "delivery_assets": "最终交付文件",
    "libreoffice_render": "LibreOffice 渲染",
}

EXECUTION_ACTION_LABELS = {
    "reuse": "复用",
    "llm_rewrite": "LLM 重写",
    "deterministic_reassemble": "确定性重组",
    "reexport": "重新导出",
    "rerun_qa": "重新 QA",
    "blocked": "阻塞",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_final_qa() -> Dict[str, Any]:
    return {
        "schema_version": VERSION,
        **QA_DEFAULTS,
        "translation_truth_version": 0,
        "source_docx_hash": None,
        "rendered_pdf_hash": None,
        "rendered_at": None,
        "page_count": None,
        "page_metrics": [],
        "notes": {},
        "updated_at": None,
    }


def normalize_final_qa(value: Any) -> Dict[str, Any]:
    out = default_final_qa()
    if isinstance(value, Mapping):
        out.update({key: value[key] for key in out if key in value})
        notes = value.get("notes")
        out["notes"] = dict(notes) if isinstance(notes, Mapping) else {}
    for key, allowed in {
        "structural_qa": {"PASS", "FAIL", "NOT_RUN"},
        "libreoffice_render": {"PASS", "FAIL", "NOT_RUN"},
        "author_visual_review": {"CONFIRMED", "NOT_CONFIRMED"},
        "word_final_review": {"CONFIRMED", "NOT_CONFIRMED"},
    }.items():
        if out.get(key) not in allowed:
            out[key] = QA_DEFAULTS[key]
    return out


def default_dependency_impact() -> Dict[str, Any]:
    return {
        "schema_version": VERSION,
        "status": "not_recorded",
        "reason": "",
        "changed_segment_ids": [],
        "changed_segment_indexes": [],
        "affected_case_ids": [],
        "affected_section_ids": [],
        "affected_subsection_ids": [],
        "chain": [],
        "affected": [],
        "reusable": [],
        "recorded_at": None,
    }


def normalize_dependency_impact(value: Any) -> Dict[str, Any]:
    out = default_dependency_impact()
    if isinstance(value, Mapping):
        out.update({key: deepcopy(value[key]) for key in out if key in value})
    for key in ("changed_segment_ids", "changed_segment_indexes",
                "affected_case_ids", "affected_section_ids", "affected_subsection_ids", "chain",
                "affected", "reusable"):
        if not isinstance(out.get(key), list):
            out[key] = []
    return out


def segment_id(job_id: str, index: int, pair: Mapping[str, Any] | None = None) -> str:
    pair = pair or {}
    for key in ("segment_id", "segment_uid", "seg_id"):
        if pair.get(key) is not None:
            return str(pair[key])
    return f"seg-{job_id}-{int(index):04d}"


def _case_segment_ids(case: Mapping[str, Any]) -> set[str]:
    ids = set()
    for key in ("segment_id", "source_segment_id", "source_id"):
        if case.get(key) is not None:
            ids.add(str(case[key]))
    alignment = case.get("source_alignment") or {}
    if alignment.get("segment_id") is not None:
        ids.add(str(alignment["segment_id"]))
    return ids


def case_section_id(case: Mapping[str, Any]) -> str:
    for key in ("section_id", "chapter_id", "subsection_id", "target_subsection"):
        value = str(case.get(key) or "").strip()
        if value:
            return value.split(".", 1)[0] if key == "target_subsection" else value
    return ""


def case_status(case: Mapping[str, Any], state: Mapping[str, Any] | None = None) -> str:
    case_id = str(case.get("case_id") or "")
    reviews = (state or {}).get("case_reviews") or {}
    record = reviews.get(case_id) if isinstance(reviews, Mapping) else None
    if isinstance(record, Mapping) and record.get("review_status") in {
            "approved", "rejected", "unreviewed"}:
        return str(record["review_status"])
    return case_provenance.with_provenance(case).get("review_status", "unreviewed")


def mark_case_reviews_stale(
    state: Mapping[str, Any], case_ids: Iterable[str], reason: str,
) -> None:
    """Mark human review decisions stale without changing their decisions."""
    reviews = state.setdefault("case_reviews", {})
    now = now_iso()
    for case_id in {str(value) for value in case_ids if str(value)}:
        record = reviews.get(case_id)
        if not isinstance(record, Mapping):
            continue
        reviews[case_id] = {
            **dict(record),
            "content_stale": True,
            "stale_reason": str(reason or "输入已变化")[:700],
            "stale_at": now,
        }


def case_baseline(case: Mapping[str, Any], state: Mapping[str, Any] | None = None) -> str:
    case_id = str(case.get("case_id") or "")
    overrides = (state or {}).get("case_review_overrides") or {}
    record = overrides.get(case_id) if isinstance(overrides, Mapping) else None
    if isinstance(record, Mapping) and record.get("synthetic_baseline_text") is not None:
        return str(record.get("synthetic_baseline_text") or "")
    baseline = case.get("synthetic_baseline")
    if isinstance(baseline, Mapping):
        return str(baseline.get("text") or "")
    return str(baseline or "")


def case_review_view(case: Mapping[str, Any], state: Mapping[str, Any] | None = None,
                     job_id: str = "") -> Dict[str, Any]:
    """Return one case with live translation truth and review overlays."""
    state = state or {}
    out = case_provenance.with_provenance(case)
    pairs = state.get("pairs") or []
    index = out.get("segment_index")
    try:
        index = int(index) if index is not None else None
    except (TypeError, ValueError):
        index = None
    pair = pairs[index] if index is not None and 0 <= index < len(pairs) else None
    source_full = str((pair or {}).get("source") or out.get("source_text") or
                      out.get("source") or (out.get("focus") or {}).get("source_text") or "")
    if not source_full:
        focus = out.get("focus") or {}
        span = focus.get("source_span") or focus.get("source") or {}
        source_full = str(span.get("text") if isinstance(span, Mapping) else span or "")
    current_full = str((pair or {}).get("target") or out.get("final_target") or
                       out.get("target_contrast_text") or out.get("target") or "")
    focus = out.get("focus") or {}
    source_span = focus.get("source_span") or focus.get("source") or {}
    target_span = focus.get("target_span") or focus.get("target") or {}
    source_span_text = str(source_span.get("text") or "") if isinstance(source_span, Mapping) else str(source_span or "")
    target_span_text = str(target_span.get("text") or "") if isinstance(target_span, Mapping) else str(target_span or "")
    source = source_span_text if source_span_text and source_span_text in source_full else source_full
    current = target_span_text if target_span_text and target_span_text in current_full else current_full
    if not current:
        current = target_span_text
    origin = out.get("case_origin")
    baseline = case_baseline(out, state) if origin == case_provenance.SYNTHETIC_BASELINE else str(
        (focus.get("initial_span") or {}).get("text") or out.get("initial_target") or
        out.get("legacy_initial") or "")
    record = (state.get("case_reviews") or {}).get(str(out.get("case_id"))) or {}
    override = (state.get("case_review_overrides") or {}).get(str(out.get("case_id"))) or {}
    academic = state.get("academic_state") or {}
    artifacts = academic.get("artifacts") or {}
    artifact_record = artifacts.get(f"case:{str(out.get('case_id'))}") or {}
    artifact_status = str(artifact_record.get("status") or "not_available")
    if artifact_status not in {"valid", "stale", "missing", "failed"}:
        artifact_status = "not_available"
    return {
        **out,
        "source_text": source,
        "segment_source_text": source_full,
        "initial_text": baseline,
        "current_text": current,
        "segment_current_text": current_full,
        "review_status": case_status(out, state),
        "review_note": record.get("note") if isinstance(record, Mapping) else "",
        "review_reason": record.get("review_reason") or record.get("note") or ""
        if isinstance(record, Mapping) else "",
        "reviewed_at": record.get("reviewed_at") or record.get("updated_at")
        if isinstance(record, Mapping) else None,
        "review_actor": record.get("actor") if isinstance(record, Mapping) else None,
        "content_stale": bool(record.get("content_stale"))
        if isinstance(record, Mapping) else False,
        "artifact_status": artifact_status,
        "baseline_status": override.get("baseline_status", "unreviewed")
        if isinstance(override, Mapping) else "unreviewed",
        "segment_id": segment_id(str(job_id or state.get("job_id") or ""), index or 0, pair or {}),
        "segment_index": index,
        "section_id": case_section_id(out),
        "analysis_fields": dict(out.get("analysis_fields") or {}),
        "synthetic_evidence": dict(out.get("synthetic_evidence") or {}),
    }


def case_review_gate(
    state: Mapping[str, Any], selected_cases: Mapping[str, Any] | None = None,
    *, require_artifact_status: bool = False,
) -> Dict[str, Any]:
    """Evaluate the author quality gate for cases used by the current report.

    All selected cases are reviewable.  Profile policy remains attached to
    ``selected_cases.report_case_policy`` so Stage 4 can decide whether a
    synthetic case counts toward an institutional minimum without changing
    whether the author has reviewed the case actually used in the report.
    """
    selected = selected_cases if isinstance(selected_cases, Mapping) else {}
    cases = [x for x in selected.get("cases") or [] if isinstance(x, Mapping)]
    reviews = state.get("case_reviews") or {}
    overrides = state.get("case_review_overrides") or {}
    academic = state.get("academic_state") or {}
    artifacts = academic.get("artifacts") or {}
    rows = []
    blocked = []
    for case in cases:
        out = case_review_view(case, state)
        case_id = str(out.get("case_id") or "")
        review = reviews.get(case_id) if isinstance(reviews, Mapping) else None
        override = overrides.get(case_id) if isinstance(overrides, Mapping) else None
        review_status = str(out.get("review_status") or "unreviewed")
        artifact_status = str(out.get("artifact_status") or "not_available")
        synthetic = case_provenance.is_synthetic(out)
        baseline_status = str(out.get("baseline_status") or "unreviewed")
        evidence = out.get("synthetic_evidence") or {}
        validation = out.get("validation") or {}
        if synthetic and isinstance(validation, Mapping) and \
                "academic_case_eligible" in validation:
            # Reuse the existing synthetic pipeline's eligibility decision;
            # human review is a separate gate and never replaces it.
            machine_valid = bool(validation.get("academic_case_eligible"))
        else:
            machine_valid = not synthetic or all(
                str(evidence.get(key) or "not_checked") in {"pass", "true", "high"}
                for key in ("baseline_plausibility", "material_difference",
                            "repair_correctness")
            )
        reasons = []
        provenance_errors = case_provenance.provenance_issues(case)
        if provenance_errors:
            reasons.append("case provenance invalid: " + ", ".join(provenance_errors))
        if review_status != "approved":
            reasons.append(f"review_status={review_status}")
        if review_status == "approved" and bool(out.get("content_stale")):
            reasons.append("approved content is stale")
        if artifact_status in {"stale", "missing", "failed"} or (
                require_artifact_status and artifact_status == "not_available"):
            reasons.append("case artifact is stale or unavailable")
        if synthetic and baseline_status == "rejected":
            reasons.append("synthetic baseline rejected")
        if synthetic and not machine_valid:
            reasons.append("synthetic machine validation incomplete")
        row = {
            "case_id": case_id,
            "case_origin": out.get("case_origin"),
            "review_status": review_status,
            "artifact_status": artifact_status,
            "content_stale": bool(out.get("content_stale")),
            "baseline_status": baseline_status,
            "machine_valid": machine_valid,
            "target_subsection": out.get("target_subsection") or
            out.get("subsection_id") or "",
            "required": True,
            "blocked": bool(reasons),
            "reasons": reasons,
        }
        rows.append(row)
        if reasons:
            blocked.append(case_id)
    policy = dict(selected.get("report_case_policy") or {})
    return {
        "schema_version": VERSION,
        "policy_id": policy.get("compliance_profile_id") or
        state.get("compliance_profile_id") or "default",
        "synthetic_counts_toward_minimum": bool(
            policy.get("synthetic_counts_toward_minimum", True)),
        "required_count": len(rows),
        "approved_count": sum(x["review_status"] == "approved" and not x["blocked"]
                              for x in rows),
        "blocked_count": len(blocked),
        "blocked_case_ids": sorted(blocked),
        "cases": rows,
        "status": "blocked" if blocked else
        "pass" if rows else "not_required",
    }


def _artifact_status_value(academic: Mapping[str, Any], name: str) -> str:
    artifacts = academic.get("artifacts") or {}
    record = artifacts.get(name) if isinstance(artifacts, Mapping) else None
    if isinstance(record, Mapping) and record.get("status"):
        return str(record["status"])
    statuses = academic.get("artifact_status") or {}
    item = statuses.get(name) if isinstance(statuses, Mapping) else None
    if isinstance(item, Mapping) and item.get("status"):
        return str(item["status"])
    return "valid" if name in (academic.get("artifacts") or {}) else "not_available"


def _impact_item(name: str, status: str, reason: str, **extra: Any) -> Dict[str, Any]:
    name = str(name)
    if name.startswith("subsection:"):
        label = f"写作单元 {name.split(':', 1)[1]}"
    elif name.startswith("chapter:"):
        label = f"章节组合 {name.split(':', 1)[1]}"
    elif name.startswith("case:"):
        label = f"案例 {name.split(':', 1)[1]}"
    elif name == "report":
        label = "报告组合"
    elif name == "final_docx_validation":
        label = "DOCX 导出"
    elif name == "libreoffice_render":
        label = "渲染 QA"
    else:
        label = ARTIFACT_LABELS.get(name, name)
    return {
        "id": name,
        "kind": "artifact",
        "label": label,
        "status": status,
        "reason": reason,
        **extra,
    }


def build_dependency_impact(
    state: Mapping[str, Any], job_id: str, changed_indexes: Sequence[int],
    reason: str, *, changed_case_ids: Iterable[str] = (),
) -> Dict[str, Any]:
    """Build the explainable dependency slice for one mutation.

    The result is intentionally a compact impact record, not a general DAG.
    It is persisted in state so a user can see what is stale and what remains
    reusable after the operation.
    """
    academic = state.get("academic_state") or {}
    changed = sorted({int(x) for x in changed_indexes if str(x).lstrip("-").isdigit()})
    pairs = state.get("pairs") or []
    changed_ids = [segment_id(job_id, index, pairs[index] if 0 <= index < len(pairs) else {})
                   for index in changed]
    # Stage 2 records carry the actual direct edges.  Use those edges for the
    # impact view; the legacy inference below remains only for old state files
    # that predate lifecycle metadata.
    from . import academic_writer
    raw_records = (academic.get("artifacts") or {}) if isinstance(academic, Mapping) else {}
    has_canonical_edges = any(
        isinstance(raw, Mapping) and any(key in raw for key in (
            "artifact_id", "artifact_type", "status", "input_segment_ids",
            "input_artifact_ids")) for raw in raw_records.values())
    if has_canonical_edges:
        changed_case_ids = {str(x) for x in changed_case_ids if x}
        changed_artifact_ids = {f"case:{x}" for x in changed_case_ids}
        impacted = academic_writer._artifact_impact_slice(
            state, input_segment_ids=changed_ids,
            input_artifact_ids=changed_artifact_ids)
        selected = {}
        if isinstance(state.get("_finalization_artifacts"), Mapping):
            selected = state.get("_finalization_artifacts", {}).get(
                "selected_cases") or {}
        cases = list(selected.get("cases") or [])
        case_by_id = {str(x.get("case_id")): x for x in cases}
        affected_case_ids = set(changed_case_ids)
        for case in cases:
            cid = str(case.get("case_id") or "")
            if (_case_segment_ids(case) & set(changed_ids)
                    or f"case:{cid}" in changed_artifact_ids):
                affected_case_ids.add(cid)
        for item in impacted.values():
            for artifact_id in item["record"].get("input_artifact_ids") or []:
                if str(artifact_id).startswith("case:"):
                    affected_case_ids.add(str(artifact_id).split(":", 1)[1])
        affected_case_ids.discard("")
        affected_subsection_ids = set()
        affected_section_ids = set()
        for name, item in impacted.items():
            record = item["record"]
            artifact_id = str(record.get("artifact_id") or name)
            if artifact_id.startswith("subsection:"):
                subsection_id = artifact_id.split(":", 1)[1]
                affected_subsection_ids.add(subsection_id)
                affected_section_ids.add(subsection_id.split(".", 1)[0])
            elif artifact_id.startswith("chapter:"):
                affected_section_ids.add(artifact_id.split(":", 1)[1])
        for cid in affected_case_ids:
            case = case_by_id.get(cid) or {}
            chapter = case_section_id(case)
            if chapter:
                affected_section_ids.add(chapter)
            subsection = str(case.get("target_subsection") or case.get(
                "subsection_id") or "").strip()
            if subsection:
                affected_subsection_ids.add(subsection)

        chain = [{
            "id": item,
            "kind": "translation_segment",
            "label": f"当前译文 · 第 {index + 1} 段",
            "status": "changed", "reason": reason,
            "segment_index": index,
        } for index, item in zip(changed, changed_ids)]
        for cid in sorted(affected_case_ids):
            chain.append({
                "id": cid, "kind": "case", "label": f"案例 {cid}",
                "status": "stale", "reason": reason,
            })
        for name, item in impacted.items():
            record = item["record"]
            artifact_id = str(record.get("artifact_id") or name)
            kind = "subsection" if artifact_id.startswith("subsection:") else "artifact"
            projected = {**record, "status": "stale",
                         "stale_reason": item["stale_reason"]}
            chain.append({
                "id": artifact_id, "kind": kind,
                "label": _impact_item(artifact_id, "stale", "")["label"],
                "status": "stale", "reason": item["stale_reason"],
                "action": academic_writer.artifact_execution_action(name, projected),
            })
        affected = []
        for name, item in impacted.items():
            record = item["record"]
            affected.append(_impact_item(
                str(record.get("artifact_id") or name), "stale", reason,
                artifact_type=record.get("artifact_type"),
                stale_reason=item["stale_reason"],
                action=academic_writer.artifact_execution_action(
                    name, {**record, "status": "stale",
                           "stale_reason": item["stale_reason"]}),
                input_segment_ids=list(record.get("input_segment_ids") or []),
                input_artifact_ids=list(record.get("input_artifact_ids") or []),
            ))
        reusable = []
        for name, record in academic_writer._artifact_records(state).items():
            if name in impacted or record.get("status") != "valid":
                continue
            reusable.append(_impact_item(
                str(record.get("artifact_id") or name), "reusable",
                "未落入本次变更的 direct dependency 范围",
                artifact_type=record.get("artifact_type"), action="reuse",
                input_segment_ids=list(record.get("input_segment_ids") or []),
                input_artifact_ids=list(record.get("input_artifact_ids") or []),
            ))
        return {
            "schema_version": VERSION,
            "status": "stale" if affected else "unchanged",
            "reason": reason,
            "changed_segment_ids": changed_ids,
            "changed_segment_indexes": changed,
            "affected_case_ids": sorted(affected_case_ids),
            "affected_section_ids": sorted(affected_section_ids, key=str),
            "affected_subsection_ids": sorted(affected_subsection_ids, key=str),
            "chain": chain, "affected": affected, "reusable": reusable,
            "recorded_at": now_iso(),
        }
    artifacts = {}
    # The core layer can pass loaded values under this private read-only key;
    # the fallback keeps the helper useful for state-only tests.
    if isinstance(state.get("_finalization_artifacts"), Mapping):
        artifacts = state.get("_finalization_artifacts") or {}
    selected = artifacts.get("selected_cases") or {}
    cases = list(selected.get("cases") or [])
    changed_case_ids = {str(x) for x in changed_case_ids if x}
    affected_ids = set(changed_case_ids)
    for case in cases:
        case_ids = _case_segment_ids(case)
        if case_ids & set(changed_ids):
            affected_ids.add(str(case.get("case_id") or ""))
        if case.get("segment_index") in changed:
            affected_ids.add(str(case.get("case_id") or ""))
    affected_ids.discard("")
    affected_sections = {
        case_section_id(case) for case in cases
        if str(case.get("case_id") or "") in affected_ids and case_section_id(case)
    }
    outline = artifacts.get("outline") or {}
    argument = artifacts.get("argument_plan") or {}
    for plan in outline.get("sections") or []:
        plan_segments = set()
        for claim_id in plan.get("claims") or []:
            claim = next((x for x in argument.get("claims") or []
                          if str(x.get("claim_id")) == str(claim_id)), {})
            plan_segments.update(str(x) for x in claim.get("project_evidence") or [])
        if plan_segments & set(changed_ids):
            affected_sections.add(str(plan.get("section_id") or ""))
    affected_sections.discard("")

    chain = [{
        "id": item,
        "kind": "translation_segment",
        "label": f"当前译文 · 第 {index + 1} 段",
        "status": "changed",
        "reason": reason,
        "segment_index": index,
    } for index, item in zip(changed, changed_ids)]
    for case in cases:
        case_id = str(case.get("case_id") or "")
        if case_id in affected_ids:
            chain.append({
                "id": case_id, "kind": "case", "label": f"案例 {case_id}",
                "status": "stale",
                "reason": reason if case_id in changed_case_ids else
                    "依赖的 CURRENT_TRANSLATION 已改变",
            })
    for section_id in sorted(affected_sections, key=str):
        chain.append({
            "id": section_id, "kind": "section", "label": f"写作单元 {section_id}",
            "status": "stale", "reason": "包含已改变的案例或项目证据",
        })

    stale_names = []
    if changed:
        stale_names.extend(["evidence", "validation", "review", "academic_quality",
                            "final_docx_validation", "delivery_assets", "libreoffice_render"])
    if affected_ids:
        stale_names.extend(["selected_cases", "case_analysis_plans", "outline", "sections", "report"])
    if not affected_ids and not affected_sections:
        # A direct translation edit still invalidates the evidence and final
        # outputs, but existing academic case/literature assets can remain a
        # reusable cache until the planner proves otherwise.
        stale_names.extend(["sections", "report"])
    stale_names = list(dict.fromkeys(stale_names))
    affected = []
    for name in stale_names:
        affected.append(_impact_item(
            name, "stale", reason,
            input_segment_ids=list(changed_ids),
            input_artifact_ids=[],
        ))
    reusable = []
    case_ids = {str(case.get("case_id")) for case in cases}
    reusable_case_ids = sorted(case_ids - affected_ids)
    if reusable_case_ids:
        reusable.append({
            "id": "cases", "kind": "cases", "label": "未受影响的案例",
            "status": "reusable", "count": len(reusable_case_ids),
            "case_ids": reusable_case_ids,
        })
    section_ids = {str(x.get("section_id")) for x in outline.get("sections") or []}
    reusable_section_ids = sorted(section_ids - affected_sections)
    if reusable_section_ids:
        reusable.append({
            "id": "sections", "kind": "sections", "label": "未受影响的写作单元",
            "status": "reusable", "count": len(reusable_section_ids),
            "section_ids": reusable_section_ids,
        })
    lit_names = ["literature_sources", "literature_evidence", "literature_claims",
                 "literature_support_review"]
    for name in lit_names:
        if name in (academic.get("artifacts") or {}):
            reusable.append(_impact_item(name, "reusable", "本次变更未修改文献输入"))
    for name in (academic.get("artifacts") or {}):
        if name not in stale_names and name not in lit_names:
            reusable.append(_impact_item(name, "reusable", "未落入本次变更的影响范围"))
    return {
        "schema_version": VERSION,
        "status": "stale" if stale_names else "unchanged",
        "reason": reason,
        "changed_segment_ids": changed_ids,
        "changed_segment_indexes": changed,
        "affected_case_ids": sorted(affected_ids),
        "affected_section_ids": sorted(affected_sections, key=str),
        "chain": chain,
        "affected": affected,
        "reusable": reusable,
        "recorded_at": now_iso(),
    }


def final_qa_label(field: str, value: str) -> str:
    labels = {
        "PASS": "通过", "FAIL": "失败", "NOT_RUN": "未运行",
        "CONFIRMED": "已确认", "NOT_CONFIRMED": "未确认",
    }
    return labels.get(str(value), str(value or "—"))


def artifact_label(name: str) -> str:
    return ARTIFACT_LABELS.get(name, name)


def execution_action_label(action: str) -> str:
    return EXECUTION_ACTION_LABELS.get(str(action or ""), str(action or "—"))


def _cjk_count(value: Any) -> int:
    import re
    return len(re.findall(r"[\u3400-\u9fff]", str(value or "")))


def _english_word_count(value: Any) -> int:
    import re
    return len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", str(value or "")))


def _rule_result(rule: Mapping[str, Any], status: str, message: str,
                 location: str = "") -> Dict[str, Any]:
    return {
        **dict(rule),
        "status": status,
        "message": message,
        "location": location or "—",
        "source": dict(rule.get("source") or {}),
    }


def evaluate_compliance(
    state: Mapping[str, Any], artifacts: Mapping[str, Any],
    profile: Mapping[str, Any], report_text: str = "",
) -> Dict[str, Any]:
    """Evaluate the configured MTI profile without producing a holistic score."""
    if any(isinstance(rule, Mapping) and "rule_id" in rule
           for rule in profile.get("rules") or []):
        # Keep one authoritative evaluator for the source-backed profile;
        # the legacy branch below only serves pre-v0.4 profile records.
        from . import compliance
        return compliance.evaluate_compliance(
            state, artifacts, profile, report_text)
    import re

    report_artifact = artifacts.get("report") or {}
    report = report_artifact.get("report") or {}
    validation = artifacts.get("validation") or {}
    final_docx = artifacts.get("final_docx_validation") or {}
    selected = artifacts.get("selected_cases") or {}
    outline = artifacts.get("outline") or {}
    enabled = bool(state.get("report_enabled", True)) and bool(
        state.get("p3_done") or report_text or report_artifact)
    text = str(report_text or state.get("p3_md") or "")
    sources = (artifacts.get("literature_sources") or {}).get("sources") or []
    rules = []
    for rule in profile.get("rules") or []:
        rule_id = rule.get("id")
        if not enabled:
            rules.append(_rule_result(rule, "not_checked", "报告尚未启用或尚未生成。"))
            continue
        if rule_id == "abstract_zh_length":
            value = report.get("abstract_zh")
            count = _cjk_count(value)
            status = "pass" if 400 <= count <= 600 else "fail"
            rules.append(_rule_result(rule, status, f"中文摘要 {count} 个汉字（要求 400—600）。",
                                      "中文摘要"))
        elif rule_id == "keywords_count":
            zh = list(report.get("keywords_zh") or [])
            en = list(report.get("keywords_en") or [])
            status = "pass" if 5 <= len(zh) <= 8 and 5 <= len(en) <= 8 else "fail"
            rules.append(_rule_result(rule, status,
                                      f"中文 {len(zh)} 个、英文 {len(en)} 个（各要求 5—8）。",
                                      "中文关键词 / Keywords"))
        elif rule_id == "toc_depth":
            depths = [len(match.group(1)) - 1 for match in
                      re.finditer(r"^(#{1,6})\s+", text, re.MULTILINE)]
            maximum = max(depths, default=0)
            status = "pass" if maximum <= 3 else "fail"
            rules.append(_rule_result(rule, status, f"检测到的最大目录层级为 {maximum}。",
                                      "报告标题"))
        elif rule_id == "citation_reference_bidirectional":
            citations = set(re.findall(r"<!--cite:([A-Za-z0-9_.:-]+)-->", text))
            source_ids = {str(x.get("source_id")) for x in sources if x.get("source_id")}
            if not citations and not source_ids:
                status, message = "not_checked", "当前没有可核对的正式文献引用。"
            else:
                missing = sorted(citations - source_ids)
                unused = sorted(source_ids - citations)
                status = "pass" if not missing and not unused else "fail"
                message = f"正文引用 {len(citations)} 条、参考文献 {len(source_ids)} 条。"
                if missing or unused:
                    message += f" 未对应引用 {len(missing)} 条，未被正文使用 {len(unused)} 条。"
            rules.append(_rule_result(rule, status, message, "正文引用 / 参考文献"))
        elif rule_id == "figure_table_numbering":
            # Match numbered figure/table labels only; ordinary prose such as
            # “图像” or “表明” is not a caption and must not become a failure.
            labels = re.findall(r"(?:图|表)\s*\d+(?:\.\d+)?", text)
            invalid = [label for label in labels
                       if not re.search(r"(?:图|表)\s*\d+\.\d+", label)]
            status = "not_checked" if not labels else "fail" if invalid else "pass"
            rules.append(_rule_result(rule, status,
                                      "未检测到图表。" if not labels else
                                      f"检测到 {len(labels)} 个图表标签。",
                                      "图题 / 表题"))
        elif rule_id == "front_back_matter":
            appendices = list(report.get("appendices") or [])
            has_case = any("原文" in str(x) or "译文" in str(x)
                           for x in appendices)
            status = "pass" if has_case else "fail"
            rules.append(_rule_result(rule, status,
                                      "已发现双语附录角色。" if has_case else
                                      "报告结构中没有可识别的双语附录角色。",
                                      "报告 back matter / 附录"))
        elif rule_id == "bilingual_appendix":
            appendices = list(report.get("appendices") or [])
            has_case = any("原文" in str(x) and "译文" in str(x)
                           for x in appendices)
            status = "pass" if has_case else "fail"
            rules.append(_rule_result(rule, status,
                                      "双语对照附录已登记。" if has_case else
                                      "尚未登记双语对照附录。", "附录一"))
        elif rule_id == "source_word_count":
            source = "\n".join(str(x.get("source") or "")
                                for x in (artifacts.get("evidence") or {}).get(
                                    "project_evidence", {}).get("segments", []))
            source = source or "\n".join(str(x or "") for x in state.get("paras") or [])
            count = _english_word_count(source)
            status = "pass" if count >= 10000 else "fail"
            rules.append(_rule_result(rule, status, f"检测到约 {count:,} 个英文词（原则上不少于 10,000）。",
                                      "源文统计"))
        elif rule_id == "case_conclusion_coverage":
            roles = {str(x.get("role")) for x in outline.get("sections") or []}
            has_case = "case_analysis" in roles
            has_conclusion = bool({"conclusion_reflection", "conclusion"} & roles)
            rq_count = len(re.findall(r"\bRQ\d+\b", text))
            status = "pass" if has_case and has_conclusion and rq_count else "fail"
            rules.append(_rule_result(rule, status,
                                      f"案例分析={'有' if has_case else '无'}，结论={'有' if has_conclusion else '无'}，"
                                      f"研究问题标记 {rq_count} 个。", "案例分析章 / 结论章"))
        elif rule_id == "layout_structure":
            status = "manual_review"
            if final_docx.get("status") == "fail":
                status = "fail"
            elif final_docx.get("status") in {"pass", "pass_with_warnings"}:
                status = "manual_review"
            rules.append(_rule_result(rule, status,
                                      "DOCX 结构检查已记录；页面视觉与样式仍需人工核对。"
                                      if status == "manual_review" else
                                      "DOCX 结构检查未通过。", "最终 DOCX"))
        elif rule_id == "synthetic_case_policy":
            cases = list(selected.get("cases") or [])
            synthetic = [x for x in cases if case_provenance.is_synthetic(x)]
            rejected = []
            reviews = state.get("case_reviews") or {}
            overrides = state.get("case_review_overrides") or {}
            for item in synthetic:
                case_id = str(item.get("case_id"))
                if isinstance(reviews.get(case_id), Mapping) and reviews[case_id].get(
                        "review_status") == "rejected":
                    rejected.append(case_id)
                if isinstance(overrides.get(case_id), Mapping) and overrides[case_id].get(
                        "baseline_status") == "rejected":
                    rejected.append(case_id)
            if not synthetic:
                status, message = "not_checked", "当前没有合成对照案例。"
            elif rejected:
                status, message = "fail", f"有 {len(set(rejected))} 个合成案例或模拟基线被拒绝。"
            elif not reviews:
                status, message = "manual_review", f"已发现 {len(synthetic)} 个合成案例，但尚无逐例人工纳入记录。"
            else:
                status, message = "pass", f"{len(synthetic)} 个合成案例已按对照用途登记，未改变历史 provenance。"
            rules.append(_rule_result(rule, status, message, "案例分析章"))
        elif rule_id == "author_placeholders":
            unresolved = bool(re.search(r"【待作者填写】|需要用户补充|待用户补充", text))
            status = "manual_review"
            message = "仍有人工确认或补充项。" if unresolved else "未发现明显占位文本；作者仍需逐项确认。"
            rules.append(_rule_result(rule, status, message, "致谢 / 声明 / 人工证据"))
        else:
            rules.append(_rule_result(rule, "not_checked", "规则尚未实现。"))
    counts = {status: sum(1 for item in rules if item.get("status") == status)
              for status in ("pass", "fail", "manual_review", "not_checked")}
    return {
        "schema_version": VERSION,
        "profile_id": profile.get("profile_id"),
        "rules": rules,
        "counts": counts,
        "status": "fail" if counts["fail"] else
        "manual_review" if counts["manual_review"] else
        "pass" if counts["pass"] else "not_checked",
    }
