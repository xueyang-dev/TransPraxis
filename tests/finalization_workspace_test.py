"""Focused v0.4 finalization truth, provenance, scope and QA regressions."""
import json

import core
from transpraxis import finalization


def _write_artifact(job_id, filename, payload):
    path = core.job_dir(job_id) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _artifact_records(*names):
    return {name: {"file": f"{name}.json", "content_hash": f"hash-{name}"}
            for name in names}


def test_translation_edit_records_truth_and_targeted_scope(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "finalizationtruth01"
        state = core.new_job_state("scope.docx")
        state.update(
            p1_done=True, p2_done=True, p3_done=True, report_enabled=True,
            paras=["first source", "second source"],
            pairs=[
                {"source": "first source", "target": "第一段", "reviewed": True},
                {"source": "second source", "target": "第二段", "reviewed": True},
            ],
            delivery_status="final", delivery_approved_by_human=True,
            academic_state={
                "artifacts": _artifact_records(
                    "evidence", "selected_cases", "outline", "sections",
                    "report", "validation", "literature_sources"),
            },
        )
        _write_artifact(job_id, "selected-cases.json", {
            "cases": [{
                "case_id": "SC-15", "case_type": "synthetic_contrast",
                "source_segment_id": f"seg-{job_id}-0001",
                "segment_index": 1, "target_subsection": "3.3.2",
            }, {
                "case_id": "SC-3", "case_type": "synthetic_contrast",
                "source_segment_id": f"seg-{job_id}-0000",
                "segment_index": 0, "target_subsection": "3.3.1",
            }],
        })
        _write_artifact(job_id, "argument-plan.json", {
            "claims": [{
                "claim_id": "C1", "project_evidence": [f"seg-{job_id}-0001"],
            }],
        })
        _write_artifact(job_id, "academic-outline.json", {
            "sections": [{"section_id": "3", "claims": ["C1"], "cases": ["SC-15"]}],
        })
        core.save_job_state(job_id, state)

        edited = core.save_translation_edit(job_id, 1, "第二段（人工修订）")
        assert edited["pairs"][1]["target"] == "第二段（人工修订）"
        assert edited["translation_truth"]["authority"] == "CURRENT_TRANSLATION"
        assert edited["translation_truth"]["version"] == 1
        impact = edited["dependency_impact"]
        assert impact["changed_segment_indexes"] == [1]
        assert "SC-15" in impact["affected_case_ids"]
        assert impact["affected_section_ids"] == ["3"]
        assert any(item["id"] == "report" and item["status"] == "stale"
                   for item in impact["affected"])
        assert any(item["id"] == "cases" and item["status"] == "reusable"
                   and "SC-3" in item["case_ids"] for item in impact["reusable"])
        assert edited["delivery_status"] == "draft"
        assert edited["delivery_approved_by_human"] is False
        assert edited["final_qa"]["word_final_review"] == "NOT_CONFIRMED"
    finally:
        core.OUTPUT_DIR = old_output


def test_translation_edit_rechecks_old_target_invariant(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "finalizationrecheck01"
        state = core.new_job_state("recheck.docx")
        state.update(
            p1_done=True, p2_done=True, paras=["source"],
            pairs=[{"source": "source", "target": '["旧包装"]'}],
        )
        report = core.validate_delivery_translation_state(state)
        core._record_delivery_validation_findings(state, report)
        assert report["blocking"] is True
        core.save_job_state(job_id, state)

        edited = core.save_translation_edit(job_id, 0, "已修复译文")
        assert edited["delivery_validation"]["blocking"] is False
        assert not any(
            item.get("type") == "delivery_invariant"
            and not item.get("resolved")
            for item in edited["findings"]
        )
        assert edited["delivery_status"] == "draft"
    finally:
        core.OUTPUT_DIR = old_output


def test_synthetic_review_and_baseline_decisions_keep_provenance_separate(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "finalizationcase01"
        state = core.new_job_state("case.docx")
        state.update(
            p1_done=True, p2_done=True, paras=["source"],
            pairs=[{"source": "source", "target": "当前译文", "reviewed": True}],
        )
        _write_artifact(job_id, "selected-cases.json", {
            "cases": [{
                "case_id": "SC-1", "case_type": "synthetic_contrast",
                "source_segment_id": f"seg-{job_id}-0000", "segment_index": 0,
                "synthetic_baseline": {"text": "模拟初译"},
            }],
        })
        core.save_job_state(job_id, state)

        approved, ok, message = core.review_academic_case(
            job_id, "SC-1", "approved", actor="reviewer")
        assert ok, message
        review = approved["case_reviews"]["SC-1"]
        assert review["review_status"] == "approved"
        assert review["case_origin"] == finalization.SYNTHETIC_BASELINE
        assert review["text_role"]["initial"] == finalization.SYNTHETIC_BASELINE
        assert approved["pairs"][0]["target"] == "当前译文"

        modified, ok, message = core.update_synthetic_baseline(
            job_id, "SC-1", "修改后的模拟初译", actor="reviewer")
        assert ok, message
        assert modified["pairs"][0]["target"] == "当前译文"
        assert modified["case_review_overrides"]["SC-1"]["baseline_status"] == "modified"
        assert modified["dependency_impact"]["affected_case_ids"] == ["SC-1"]

        rejected, ok, message = core.update_synthetic_baseline(
            job_id, "SC-1", "修改后的模拟初译", status="rejected", actor="reviewer")
        assert ok, message
        assert rejected["case_reviews"]["SC-1"]["review_status"] == "approved"
        assert rejected["case_review_overrides"]["SC-1"]["baseline_status"] == "rejected"
        assert rejected["translation_truth"]["version"] == 0
    finally:
        core.OUTPUT_DIR = old_output


def test_final_qa_metadata_does_not_make_frozen_content_diverge(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "finalizationqa01"
        state = core.new_job_state("qa.docx")
        state.update(
            p1_done=True, p2_done=True, report_enabled=False,
            paras=["Source"], pairs=[{"source": "Source", "target": "译文"}])
        core.save_source(job_id, b"source")
        core.save_job_state(job_id, state)
        approved, ok, errors = core.approve_delivery(job_id, note="qa test")
        assert ok, errors
        recorded = core.record_final_qa(
            job_id, "author_visual_review", "CONFIRMED", "看过关键页")
        assert recorded["final_qa"]["author_visual_review"] == "CONFIRMED"
        recorded = core.record_final_qa(
            job_id, "word_final_review", "CONFIRMED", "Word 已确认")
        assert recorded["final_qa"]["word_final_review"] == "CONFIRMED"
        snapshot = core.delivery_snapshot_status(job_id)
        assert snapshot["current"] is True
        assert snapshot["diverged"] is False
    finally:
        core.OUTPUT_DIR = old_output


def test_task_status_label_uses_precise_freeze_lifecycle(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "finalizationlabel01"
        state = core.new_job_state("lifecycle.docx")
        state.update(
            p1_done=True, p2_done=True, report_enabled=False,
            paras=["Source"], pairs=[{"source": "Source", "target": "译文"}])
        core.save_source(job_id, b"source")
        core.save_job_state(job_id, state)

        assert core.task_status_label(state, job_id) == "可以冻结交付"
        frozen, ok, errors = core.approve_delivery(job_id)
        assert ok, errors
        assert core.task_status_label(frozen, job_id) == "已冻结交付 v1"

        diverged = core.save_translation_edit(job_id, 0, "新译文")
        assert core.task_status_label(diverged, job_id) == "工作版本已偏离冻结交付 v1"

        report_state = core.new_job_state("review-required.docx")
        report_state.update(
            p1_done=True, p2_done=True, p3_done=True, report_enabled=True,
            report_status="generated", final_qa=finalization.normalize_final_qa(None),
            paras=["Source"], pairs=[{"source": "Source", "target": "译文"}])
        assert core.task_status_label(report_state) == "暂不满足交付条件"
    finally:
        core.OUTPUT_DIR = old_output


def test_case_and_qa_workspace_surfaces_render_without_conflating_states(tmp_path):
    from streamlit.testing.v1 import AppTest

    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "finalizationui01"
        state = core.new_job_state("ui-finalization.docx")
        state.update(
            p1_done=True, p2_done=True, p3_done=True, report_enabled=True,
            paras=["Source paragraph"],
            pairs=[{"source": "Source paragraph", "target": "源文段落"}],
            p3_md="# 翻译实践报告\n\n正文。分析：>。内容。",
        )
        impact = finalization.default_dependency_impact()
        impact.update(
            status="stale",
            reason="人工修改 CURRENT_TRANSLATION；相关案例与学术下游需要重建",
            changed_segment_indexes=[0],
            affected=[{"id": f"affected-{index}", "label": f"受影响产物 {index}"}
                      for index in range(9)],
            reusable=[{"id": f"reusable-{index}", "label": f"未受影响单元 {index}"}
                      for index in range(25)],
        )
        state["dependency_impact"] = impact
        core.save_job_state(job_id, state)
        _write_artifact(job_id, "selected-cases.json", {
            "cases": [{
                "case_id": "SC-UI", "case_type": "synthetic_contrast",
                "source_segment_id": f"seg-{job_id}-0000", "segment_index": 0,
                "synthetic_baseline": {"text": "模拟初译"},
                "synthetic_evidence": {"baseline_plausibility": "pass"},
            }],
        })
        _write_artifact(job_id, "academic-outline.json", {
            "sections": [{"section_id": "3", "role": "case_analysis"},
                          {"section_id": "4", "role": "conclusion_reflection"}],
        })
        _write_artifact(job_id, "academic-report.json", {
            "report": {"abstract_zh": "摘要", "keywords_zh": [], "keywords_en": [],
                       "appendices": []},
        })
        _write_artifact(job_id, "final-docx-validation.json", {"status": "pass"})

        at = AppTest.from_file(str(core.Path(__file__).resolve().parent.parent / "app.py"),
                               default_timeout=30)
        at.run()
        at.session_state["active_job_id"] = job_id
        at.session_state["app_view"] = "workspace"
        at.session_state["workspace_mode"] = True
        at.session_state["workspace_section"] = "cases"
        at.run()
        assert not at.exception, at.exception
        assert any("案例终审" in item.value for item in at.markdown)
        assert any("模拟初译仅用于分析对照" in item.value for item in at.markdown)

        at.session_state["workspace_section"] = "qa"
        at.run()
        assert not at.exception, at.exception
        assert any("MTI_PRACTICE_REPORT_DEFAULT" in item.value for item in at.markdown)
        assert any("DOCX 结构检查" in item.value for item in at.markdown)
        assert any("Word 最终复核" in item.value for item in at.markdown)

        at.session_state["workspace_section"] = "delivery"
        at.run()
        assert not at.exception, at.exception
        assert any("暂不满足交付条件" in item.value for item in at.markdown)
        assert any("当前译文真值" in item.value for item in at.markdown)
        assert any("冻结交付" in item.value for item in at.markdown)
        delivery_markup = "\n".join(item.value for item in at.markdown)
        for label in ("学术产物同步", "案例复核", "合规检查", "DOCX 结构检查",
                      "LibreOffice 页面渲染", "作者视觉复核", "Word 最终复核"):
            assert label in delivery_markup
        assert "9 个下游产物" in delivery_markup
        assert "25 个未受影响单元/资产" in delivery_markup
    finally:
        core.OUTPUT_DIR = old_output
