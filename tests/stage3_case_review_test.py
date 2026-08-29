"""Stage 3 human case review, replacement and finalization regressions."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import core
from transpraxis import academic_writer, case_provenance, finalization, snapshots


def _synthetic_case(case_id, segment_id, baseline, current, *, eligible=True):
    return {
        "case_id": case_id,
        "case_type": "synthetic_contrast",
        "case_origin": finalization.SYNTHETIC_BASELINE,
        "text_role": {"source": "SOURCE", "initial": "SYNTHETIC_BASELINE",
                      "target": "CURRENT_TRANSLATION"},
        "review_status": "unreviewed",
        "source_segment_id": segment_id,
        "segment_index": 0 if segment_id == "382" else 1,
        "target_subsection": "3.3.2" if segment_id == "382" else "3.3.1",
        "difficulty_group": "3.3.1",
        "supports_claims": ["C1"],
        "research_questions": ["RQ1"],
        "source_text": "Source " + segment_id,
        "synthetic_baseline": {"text": baseline},
        "target_contrast_text": current,
        "focus": {
            "source_span": {"text": "Source " + segment_id},
            "target_span": {"text": current},
        },
        "synthetic_evidence": {
            "baseline_plausibility": "pass",
            "material_difference": "pass",
            "repair_correctness": "pass",
            "academic_analysis_value": "high",
        },
        "validation": {"academic_case_eligible": eligible},
    }


def _setup(tmp_path, cases, synthetic_items=None):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    job_id = "stage3casereview01"
    state = core.new_job_state("case-review.docx")
    state.update(
        p1_done=True, p2_done=True, report_enabled=True,
        pairs=[
            {"source": "Source 382", "target": cases[0]["target_contrast_text"],
             "segment_id": "382"},
            {"source": "Source other",
             "target": cases[1]["target_contrast_text"] if len(cases) > 1
             else "另一段当前译文", "segment_id": "other"},
        ],
    )
    core.save_source(job_id, b"source")
    selected = {"cases": cases, "report_case_policy": {
        "report_stage": "final_report", "synthetic_counts_toward_minimum": True,
    }}
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "selected_cases", selected,
        "case-dep", "case-review-v1")
    if synthetic_items is not None:
        academic_writer._save_artifact(
            state, core.job_dir(job_id), "synthetic_validation",
            {"items": synthetic_items, "pipeline_status": "complete"},
            "synthetic-dep", "synthetic-validation-v1")
    core.save_job_state(job_id, state)
    return job_id, core.load_job_state(job_id), selected


def test_approval_keeps_synthetic_provenance_and_does_not_mutate_text(tmp_path):
    job_id, _state, _selected = _setup(
        tmp_path, [_synthetic_case("SC-15", "382", "较好的模拟初译", "较弱的当前译文")])
    approved, ok, message = core.review_academic_case(
        job_id, "SC-15", "approved", "作者确认可用于分析", actor="author")
    assert ok, message
    record = approved["case_reviews"]["SC-15"]
    assert record["review_status"] == "approved"
    assert record["review_reason"] == "作者确认可用于分析"
    assert record["reviewed_at"]
    assert record["case_origin"] == finalization.SYNTHETIC_BASELINE
    assert record["text_role"]["initial"] == finalization.SYNTHETIC_BASELINE
    assert record["content_stale"] is False
    persisted = core.load_academic_artifact(job_id, "selected_cases")
    case = persisted["cases"][0]
    assert case["case_origin"] == finalization.SYNTHETIC_BASELINE
    assert case["target_contrast_text"] == "较弱的当前译文"
    assert approved["pairs"][0]["target"] == "较弱的当前译文"
    assert approved["translation_truth"]["version"] == 0


def test_reject_blocks_gate_and_replacement_starts_unreviewed(tmp_path):
    old = _synthetic_case("SC-15", "382", "更自然的模拟初译", "不自然的当前译文")
    replacement = _synthetic_case("SC-99", "other", "另一模拟初译", "另一当前译文")
    job_id, state, _selected = _setup(
        tmp_path, [old], [old, replacement])
    rejected, ok, message = core.review_academic_case(
        job_id, "SC-15", "rejected", "当前译文劣于模拟基线", actor="author")
    assert ok, message
    selected = core.load_academic_artifact(job_id, "selected_cases")
    gate = finalization.case_review_gate(state, selected)
    assert gate["status"] == "blocked"
    assert gate["blocked_case_ids"] == ["SC-15"]

    replaced, ok, result = core.replace_rejected_case(
        job_id, "SC-15", actor="author")
    assert ok, result
    persisted = core.load_academic_artifact(job_id, "selected_cases")
    assert [x["case_id"] for x in persisted["cases"]] == ["SC-99"]
    new_record = replaced["case_reviews"]["SC-99"]
    assert new_record["review_status"] == "unreviewed"
    assert new_record["content_stale"] is False
    assert replaced["case_reviews"]["SC-15"]["review_status"] == "rejected"
    assert replaced["pairs"][0]["target"] == "不自然的当前译文"
    gate = finalization.case_review_gate(
        replaced, core.load_academic_artifact(job_id, "selected_cases"))
    assert gate["blocked_case_ids"] == ["SC-99"]
    assert replaced["academic_state"]["artifacts"]["case:SC-99"]["status"] == "valid"
    approved_new, ok, message = core.review_academic_case(
        job_id, "SC-99", "approved", "替换案例已重新核对", actor="author")
    assert ok, message
    assert finalization.case_review_gate(
        approved_new, core.load_academic_artifact(job_id, "selected_cases"))["status"] == "pass"


def test_provenance_mismatch_blocks_case_finalization(tmp_path):
    case = _synthetic_case("SC-BAD", "382", "模拟初译", "当前译文")
    case["text_role"]["initial"] = case_provenance.HISTORICAL_INITIAL
    _job_id, state, selected = _setup(tmp_path, [case])
    gate = finalization.case_review_gate(state, selected)
    assert gate["status"] == "blocked"
    assert any("case provenance invalid" in reason
               for reason in gate["cases"][0]["reasons"])


def test_case_translation_edit_marks_review_stale_and_stage2_chain(tmp_path):
    case = _synthetic_case("SC-15", "382", "模拟初译", "旧当前译文")
    job_id, state, _selected = _setup(tmp_path, [case])
    academic = state["academic_state"]
    academic["artifacts"].update({
        "subsection:3.3.2": {
            "artifact_id": "subsection:3.3.2", "artifact_type": "writing_subsection",
            "file": "academic-sections.json", "content_hash": "unit",
            "dependency_hash": "unit-dep", "input_segment_ids": ["382"],
            "input_artifact_ids": ["case:SC-15"], "version": "v1",
            "updated_at": "old", "status": "valid", "stale_reason": None,
        },
        "chapter:3": {
            "artifact_id": "chapter:3", "artifact_type": "chapter_composite",
            "file": "academic-sections.json", "content_hash": "chapter",
            "dependency_hash": "chapter-dep", "input_segment_ids": [],
            "input_artifact_ids": ["subsection:3.3.2"], "version": "v1",
            "updated_at": "old", "status": "valid", "stale_reason": None,
        },
        "report": {
            "artifact_id": "report", "artifact_type": "report_composite",
            "file": "academic-report.json", "content_hash": "report",
            "dependency_hash": "report-dep", "input_segment_ids": [],
            "input_artifact_ids": ["chapter:3"], "version": "v1",
            "updated_at": "old", "status": "valid", "stale_reason": None,
        },
        "final_docx_validation": {
            "artifact_id": "final_docx_validation", "artifact_type": "docx_export",
            "file": "final-docx-validation.json", "content_hash": "docx",
            "dependency_hash": "docx-dep", "input_segment_ids": [],
            "input_artifact_ids": ["report"], "version": "v1",
            "updated_at": "old", "status": "valid", "stale_reason": None,
        },
        "libreoffice_render": {
            "artifact_id": "libreoffice_render", "artifact_type": "render_qa",
            "file": "libreoffice-render-status.json", "content_hash": "render",
            "dependency_hash": "render-dep", "input_segment_ids": [],
            "input_artifact_ids": ["final_docx_validation"], "version": "v1",
            "updated_at": "old", "status": "valid", "stale_reason": None,
        },
    })
    core.save_job_state(job_id, state)
    approved, ok, message = core.review_academic_case(job_id, "SC-15", "approved")
    assert ok, message
    core.save_job_state(job_id, approved)
    edited = core.save_translation_edit(job_id, 0, "修订后的当前译文")
    records = edited["academic_state"]["artifacts"]
    for name in ("case:SC-15", "subsection:3.3.2", "chapter:3", "report",
                 "final_docx_validation", "libreoffice_render"):
        assert records[name]["status"] == "stale"
    assert edited["case_reviews"]["SC-15"]["content_stale"] is True
    gate = finalization.case_review_gate(
        edited, core.load_academic_artifact(job_id, "selected_cases"))
    assert gate["status"] == "blocked"
    assert "approved content is stale" in gate["cases"][0]["reasons"]


def test_synthetic_baseline_edit_does_not_change_translation_truth(tmp_path):
    case = _synthetic_case("SC-15", "382", "原模拟初译", "当前译文")
    job_id, state, _selected = _setup(tmp_path, [case])
    approved, ok, message = core.review_academic_case(job_id, "SC-15", "approved")
    assert ok, message
    state = approved
    academic = state["academic_state"]
    academic["artifacts"]["subsection:3.3.2"] = {
        "artifact_id": "subsection:3.3.2", "artifact_type": "writing_subsection",
        "file": "academic-sections.json", "content_hash": "unit",
        "dependency_hash": "unit-dep", "input_segment_ids": ["382"],
        "input_artifact_ids": ["case:SC-15"], "version": "v1",
        "updated_at": "old", "status": "valid", "stale_reason": None,
    }
    core.save_job_state(job_id, state)
    modified, ok, message = core.update_synthetic_baseline(
        job_id, "SC-15", "更自然的模拟初译", status="modified", actor="author")
    assert ok, message
    assert modified["pairs"][0]["target"] == "当前译文"
    assert modified["translation_truth"]["version"] == 0
    assert modified["case_review_overrides"]["SC-15"]["baseline_status"] == "modified"
    assert modified["case_reviews"].get("SC-15", {}).get("content_stale") is True
    assert modified["academic_state"]["artifacts"]["case:SC-15"]["status"] == "stale"
    assert modified["academic_state"]["artifacts"][
        "subsection:3.3.2"]["status"] == "stale"


def test_case15_human_rejection_overrides_passing_machine_validation(tmp_path):
    case = _synthetic_case("SC-15", "382", "更自然准确的模拟基线", "较弱含糊的当前译文")
    job_id, state, _selected = _setup(tmp_path, [case], [case])
    approved, ok, message = core.review_academic_case(
        job_id, "SC-15", "approved", actor="author")
    assert ok, message
    rejected, ok, message = core.review_academic_case(
        job_id, "SC-15", "rejected", "模拟基线优于当前译文，不能作为改译改进案例",
        actor="author")
    assert ok, message
    selected = core.load_academic_artifact(job_id, "selected_cases")
    persisted_case = selected["cases"][0]
    assert case_provenance.with_provenance(persisted_case)["case_origin"] == \
        finalization.SYNTHETIC_BASELINE
    assert persisted_case["synthetic_evidence"]["baseline_plausibility"] == "pass"
    gate = finalization.case_review_gate(rejected, selected)
    assert gate["status"] == "blocked"
    assert gate["blocked_case_ids"] == ["SC-15"]
    _, ok, errors = core.approve_delivery(job_id, "尝试绕过作者拒绝")
    assert not ok
    assert any("案例人工终审未通过" in error for error in errors)


def test_frozen_snapshot_preserves_review_state_without_future_writeback(tmp_path):
    case = _synthetic_case("SC-15", "382", "模拟初译", "当前译文")
    job_id, state, _selected = _setup(tmp_path, [case])
    approved, ok, message = core.review_academic_case(
        job_id, "SC-15", "approved", "冻结前作者确认", actor="author")
    assert ok, message
    manifest = snapshots.create_snapshot(
        core.job_dir(job_id), job_id, approved,
        {"delivery_manifest.json": b"{}\n"}, {}, {})
    assert manifest["case_reviews"]["SC-15"]["review_status"] == "approved"
    frozen_identity = manifest["translation_state_identity"]

    approved["case_reviews"]["SC-15"]["review_status"] = "rejected"
    approved["case_reviews"]["SC-15"]["review_reason"] = "冻结后改变工作版本"
    assert snapshots.state_identity(approved) != frozen_identity
    latest = snapshots.latest_snapshot(core.job_dir(job_id))
    assert latest["translation_state_identity"] == frozen_identity
    assert latest["case_reviews"]["SC-15"]["review_status"] == "approved"
