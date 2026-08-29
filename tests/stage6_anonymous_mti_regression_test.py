"""End-to-end v0.4 regressions over the anonymized MTI fixture."""
from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

import pytest

import core
from eval.mti_finalization_regression import load_fixture, run_regression
from transpraxis import academic_evidence, academic_writer, academic_validator
from transpraxis import case_provenance, finalization, rendered_qa, snapshots
from transpraxis import models


@pytest.fixture(autouse=True)
def _restore_output_dir():
    previous = core.OUTPUT_DIR
    yield
    core.OUTPUT_DIR = previous


def _record(name, *, segments=(), inputs=(), artifact_type="deterministic_artifact"):
    return {
        "artifact_id": name, "artifact_type": artifact_type,
        "file": f"{name.replace(':', '-')}.json",
        "content_hash": f"hash-{name}", "dependency_hash": f"dep-{name}",
        "input_segment_ids": list(segments), "input_artifact_ids": list(inputs),
        "version": "fixture-v1", "updated_at": "2026-01-01T00:00:00+00:00",
        "status": "valid", "stale_reason": None,
    }


def _graph_state():
    state = {"pairs": [
        {"source": "The image makes distance felt.", "target": "当前段落一",
         "segment_id": "382"},
        {"source": "Although the field appears stable.", "target": "当前段落二",
         "segment_id": "seg-0003"},
    ], "academic_state": academic_writer.default_academic_state()}
    state["academic_state"]["artifacts"] = {
        "case:SC-0015": _record("case:SC-0015", segments=["382"],
                                 artifact_type="case_selection_unit"),
        "case:AR-0382": _record("case:AR-0382", segments=["seg-0003"],
                                  artifact_type="case_selection_unit"),
        "subsection:3.3.2": _record(
            "subsection:3.3.2", segments=["382"], inputs=["case:SC-0015"],
            artifact_type="writing_subsection"),
        "subsection:3.3.1": _record(
            "subsection:3.3.1", segments=["seg-0003"], inputs=["case:AR-0382"],
            artifact_type="writing_subsection"),
        "chapter:3": _record(
            "chapter:3", inputs=["subsection:3.3.1", "subsection:3.3.2"],
            artifact_type="chapter_composite"),
        "report": _record("report", inputs=["chapter:3"],
                           artifact_type="report_composite"),
        "final_docx_validation": _record(
            "final_docx_validation", inputs=["report"], artifact_type="docx_export"),
        "libreoffice_render": _record(
            "libreoffice_render", inputs=["final_docx_validation"],
            artifact_type="render_qa"),
    }
    return state


def _synthetic_case(case_id="SC-0015", segment_index=0):
    return {
        "case_id": case_id, "case_type": "synthetic_contrast",
        "case_origin": finalization.SYNTHETIC_BASELINE,
        "text_role": {"source": "SOURCE", "initial": "SYNTHETIC_BASELINE",
                      "target": "CURRENT_TRANSLATION"},
        "source_segment_id": "382", "segment_index": segment_index,
        "synthetic_baseline": {"text": "更自然的模拟初译"},
        "target_contrast_text": "较弱的当前译文",
        "synthetic_evidence": {"baseline_plausibility": "pass",
                                "material_difference": "pass",
                                "repair_correctness": "pass"},
        "validation": {"academic_case_eligible": True},
    }


def test_anonymous_fixture_baseline_and_case15_human_failure():
    fixture_result = run_regression()
    assert fixture_result["contains_private_paper_text"] is False
    assert fixture_result["approved_synthetic_remains_non_historical"] is True

    fixture = load_fixture()
    case = next(item for item in fixture["cases"] if item["case_id"] == "SC-0015")
    rejected = case_provenance.with_provenance({
        **case, "review_status": "rejected",
    })
    assert rejected["case_origin"] == finalization.SYNTHETIC_BASELINE
    assert rejected["text_role"]["initial"] == finalization.SYNTHETIC_BASELINE
    assert rejected["review_status"] == "rejected"
    assert rejected["current_translation"] == case["current_translation"]


def test_translation_mutation_only_invalidates_case15_downstream():
    state = _graph_state()
    before = copy.deepcopy(state["academic_state"]["artifacts"])

    affected = academic_writer.propagate_artifact_staleness(
        state, input_segment_ids=["382"])

    assert set(affected) == {
        "case:SC-0015", "subsection:3.3.2", "chapter:3", "report",
        "final_docx_validation", "libreoffice_render",
    }
    assert state["academic_state"]["artifacts"]["subsection:3.3.1"] == \
        before["subsection:3.3.1"]
    assert state["academic_state"]["artifacts"]["case:AR-0382"] == \
        before["case:AR-0382"]
    assert academic_writer.artifact_execution_action(
        "subsection:3.3.2", state["academic_state"]["artifacts"]["subsection:3.3.2"]
    ) == "llm_rewrite"
    assert academic_writer.artifact_execution_action(
        "report", state["academic_state"]["artifacts"]["report"]
    ) == "deterministic_reassemble"


def test_literature_removal_invalidates_claim_chain_and_removes_dangling_reference():
    state = _graph_state()
    artifacts = state["academic_state"]["artifacts"]
    artifacts.update({
        "literature_sources": _record("literature_sources"),
        "literature_claims": _record("literature_claims", inputs=["literature_sources"]),
        "argument_plan": _record("argument_plan", inputs=["literature_claims"]),
        "subsection:3.3.1": _record(
            "subsection:3.3.1", segments=["seg-0003"], inputs=["argument_plan"],
            artifact_type="writing_subsection"),
    })
    state["p3_md"] = "<!--cite:lit-a-->"
    profile = __import__("transpraxis.compliance", fromlist=["compliance_profile"])
    profile = profile.compliance_profile()
    report_artifact = {"report": {"abstract_zh": "摘" * 400,
                                   "keywords_zh": ["甲"] * 5,
                                   "keywords_en": ["a"] * 5}}
    sources = {"sources": [{"source_id": "lit-a"}, {"source_id": "lit-b"}]}
    result = __import__("transpraxis.compliance", fromlist=["evaluate_compliance"])
    result = result.evaluate_compliance(
        state, {"report": report_artifact, "literature_sources": sources},
        profile, state["p3_md"])
    citation = next(x for x in result["rules"]
                    if x["rule_id"] == "citation_reference_bidirectional")
    assert citation["status"] == "fail"
    assert citation["actual"]["unused"] == ["lit-b"]

    affected = academic_writer.propagate_artifact_staleness(
        state, input_artifact_ids=["literature_sources"])
    assert all(artifacts[name]["status"] == "stale" for name in (
        "literature_sources", "literature_claims", "argument_plan"))
    assert artifacts["case:SC-0015"]["status"] == "valid"

    result_after_removal = __import__(
        "transpraxis.compliance", fromlist=["evaluate_compliance"]
    ).evaluate_compliance(
        state, {"report": report_artifact,
                "literature_sources": {"sources": [{"source_id": "lit-a"}]}},
        profile, state["p3_md"])
    citation_after = next(x for x in result_after_removal["rules"]
                          if x["rule_id"] == "citation_reference_bidirectional")
    assert citation_after["status"] == "pass"


def test_terminology_mutation_only_marks_segments_using_changed_entry(tmp_path):
    core.OUTPUT_DIR = tmp_path
    old_entry = models.normalize_glossary_entry({
        "id": "term-a", "source": "quantum field", "target": "量子场",
        "preferred": "量子场", "behavior": "translate", "status": "provisional",
    })
    new_entry = models.normalize_glossary_entry({
        "id": "term-a", "source": "quantum field", "target": "量子场论",
        "preferred": "量子场论", "behavior": "translate", "status": "locked",
    })
    old_hash = models.glossary_hash([old_entry])
    state = {
        "pairs": [
            {"source": "quantum field changes", "target": "旧一",
             "segment_id": "term-seg", "glossary_hash_used": old_hash,
             "glossary_entry_ids": ["term-a"]},
            {"source": "unrelated passage", "target": "旧二",
             "segment_id": "other-seg", "glossary_hash_used": old_hash,
             "glossary_entry_ids": []},
        ],
        "glossary_versions": [{"version": 1, "glossary_hash": old_hash,
                               "entries": [old_entry]}],
        "glossary_frozen": {"version": 2,
                            "glossary_hash": models.glossary_hash([new_entry]),
                            "entries": [new_entry]},
        "findings": [], "academic_state": academic_writer.default_academic_state(),
    }
    state["academic_state"]["artifacts"] = {
        "subsection:term": _record("subsection:term", segments=["term-seg"],
                                    artifact_type="writing_subsection"),
        "subsection:other": _record("subsection:other", segments=["other-seg"],
                                     artifact_type="writing_subsection"),
    }
    updated, stale = core._apply_glossary_staleness(state, "terminology-job")

    assert updated is state
    assert stale == [0]
    assert state["academic_state"]["artifacts"]["subsection:term"]["status"] == "stale"
    assert state["academic_state"]["artifacts"]["subsection:other"]["status"] == "valid"


def test_case_distribution_and_synthetic_count_policy_are_reported_without_generation():
    cases = [{"case_id": f"AR-{i:02d}", "case_type": "authentic_revision",
              "case_origin": finalization.REAL_REVISION,
              "text_role": {"source": "SOURCE", "initial": "HISTORICAL_INITIAL",
                            "target": "CURRENT_TRANSLATION"},
              "source_segment_id": f"seg-{i:02d}", "segment_index": i,
              "difficulty_group": group, "source_text": "source",
              "historical_initial": "initial", "final_target": "current",
              "argument_role": "core", "research_questions": ["RQ1"]}
             for i, group in enumerate(["3.3.1"] * 9 + ["3.3.2"] * 8 + ["3.3.3"] * 8)]
    selected = {"cases": cases, "report_case_policy": {
        "report_stage": "final_report", "target_cases": 25,
        "synthetic_counts_toward_minimum": False,
        "synthetic_count_policy": "supplement_only",
    }}
    portfolio = academic_validator.validate_case_portfolio(selected)
    assert portfolio["selected_case_count"] == 25
    assert portfolio["difficulty_distribution"] == {"3.3.1": 9, "3.3.2": 8, "3.3.3": 8}
    assert portfolio["synthetic_case_count_policy"] == "supplement_only"


def test_interrupted_translation_resume_keeps_truth_and_clears_false_approval(tmp_path):
    core.OUTPUT_DIR = tmp_path
    job_id = "stage6resume0001"
    state = _graph_state()
    state.update(p1_done=True, p2_done=True, p3_done=True, report_enabled=True,
                 paras=[pair["source"] for pair in state["pairs"]],
                 p3_md="# stale report", delivery_status="final",
                 delivery_approved_by_human=True,
                 case_reviews={"SC-0015": {"review_status": "approved",
                                            "content_stale": False}},
                 final_qa=finalization.normalize_final_qa({
                     "structural_qa": "PASS", "libreoffice_render": "PASS",
                     "author_visual_review": "CONFIRMED",
                     "word_final_review": "CONFIRMED"}))
    core.save_source(job_id, b"anonymous source")
    core.save_job_state(job_id, state)

    interrupted = core._mark_translation_truth_changed(
        job_id, state, [0], "interrupted translation batch", actor="worker",
        action="resume_truncation_save")
    core.save_job_state(job_id, interrupted)
    resumed = core.load_job_state(job_id)

    assert resumed["translation_truth"]["version"] == 1
    assert resumed["pairs"][0]["target"] == "当前段落一"
    assert resumed["delivery_status"] == "draft"
    assert resumed["delivery_approved_by_human"] is False
    assert resumed["final_qa"]["author_visual_review"] == "NOT_CONFIRMED"
    assert resumed["case_reviews"]["SC-0015"]["content_stale"] is True
    assert resumed["academic_state"]["artifacts"]["report"]["status"] == "stale"


def test_incremental_rebuild_reuses_unaffected_unit_exactly_and_calls_no_llm_for_it():
    state = {"academic_state": academic_writer.default_academic_state()}
    state["academic_state"]["artifacts"] = {
        "subsection:3.3.1": _record(
            "subsection:3.3.1", segments=["seg-0003"],
            artifact_type="writing_subsection"),
        "subsection:3.3.2": _record(
            "subsection:3.3.2", segments=["382"],
            artifact_type="writing_subsection"),
    }
    before = copy.deepcopy(state["academic_state"]["artifacts"])
    academic_writer.propagate_artifact_staleness(
        state, input_segment_ids=["382"])
    llm_calls = []
    for name in ("subsection:3.3.1", "subsection:3.3.2"):
        record = state["academic_state"]["artifacts"][name]
        if record["status"] == "stale":
            llm_calls.append(name)
            record["status"] = "valid"
            record["version"] = "fixture-v2"
    assert llm_calls == ["subsection:3.3.2"]
    assert state["academic_state"]["artifacts"]["subsection:3.3.1"] == \
        before["subsection:3.3.1"]


def test_placeholder_and_qa_split_are_explicit_before_final_delivery(tmp_path, monkeypatch):
    core.OUTPUT_DIR = tmp_path
    job_id = "stage6qasplit01"
    state = core.new_job_state("anonymous.docx")
    state.update(p1_done=True, p2_done=True, p3_done=True, report_enabled=True,
                 paras=["Source"], pairs=[{"source": "Source", "target": "译文"}],
                 p3_md="致谢：导师是【待作者填写】。")
    core.save_source(job_id, b"source")
    core.save_job_state(job_id, state)
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "report",
        {"report": {"abstract_zh": "摘" * 400, "keywords_zh": ["甲"] * 5,
                     "keywords_en": ["a"] * 5, "appendices": []},
         "content_hash": "report", "report_status": "generated"},
        "report-dep", "v1")
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "final_docx_validation",
        {"status": "pass", "source_docx_hash": "docx", "content_hash": "docx"},
        "docx-dep", "v1", input_artifact_ids=["report"])
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "libreoffice_render",
        {"status": "pass", "qa_status": "PASS", "source_docx_hash": "docx",
         "rendered_pdf_hash": "pdf"}, "render-dep", "v1",
        input_artifact_ids=["final_docx_validation"])
    core.save_job_state(job_id, state)
    compliance = core.compliance_profile_view(job_id, state)
    placeholder = next(x for x in compliance["rules"]
                       if x["rule_id"] == "author_placeholders")
    assert placeholder["status"] == "manual_review"

    monkeypatch.setattr(core, "compliance_profile_view", lambda *_args: {
        "status": "manual_review", "profile_compliance": {"status": "pass"},
        "project_constraints": {"status": "pass"}, "counts": {},
    })
    core.record_final_qa(job_id, "structural_qa", "PASS")
    core.record_final_qa(job_id, "libreoffice_render", "PASS")
    core.record_final_qa(job_id, "author_visual_review", "CONFIRMED")
    _state, approved, errors = core.approve_delivery(job_id)
    assert not approved
    assert any("Word Final Review=NOT_CONFIRMED" in item for item in errors)


def test_frozen_snapshot_binds_truth_case_compliance_qa_and_artifact_hashes(tmp_path):
    core.OUTPUT_DIR = tmp_path
    job_id = "stage6snapshot01"
    state = core.new_job_state("anonymous.docx")
    state.update(p1_done=True, p2_done=True, report_enabled=False,
                 paras=["Source"], pairs=[{"source": "Source", "target": "译文",
                                           "initial_target": "初译"}],
                 case_reviews={"SC-0015": {"review_status": "approved",
                                            "review_reason": "author",
                                            "reviewed_at": "fixture"}},
                 compliance_record={"status": "manual_review", "profile_id": "MTI_PRACTICE_REPORT_DEFAULT"},
                 final_qa=finalization.normalize_final_qa({
                     "structural_qa": "PASS", "libreoffice_render": "PASS",
                     "author_visual_review": "CONFIRMED",
                     "word_final_review": "CONFIRMED"}))
    core.save_source(job_id, b"anonymous source")
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "compliance",
        {"status": "manual_review", "content_hash": "compliance"}, "c", "v1")
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "report_qa",
        {"content_hash": "qa", "translation_truth_hash": core.current_translation_hash(state)},
        "qa-dep", "v1")
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "final_docx_validation",
        {"status": "pass", "source_docx_hash": "docx-hash", "content_hash": "docx"},
        "docx-dep", "v1")
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "libreoffice_render",
        {"status": "pass", "qa_status": "PASS", "source_docx_hash": "docx-hash",
         "rendered_pdf_hash": "pdf-hash"}, "render-dep", "v1")
    core.save_job_state(job_id, state)

    manifest = snapshots.create_snapshot(
        core.job_dir(job_id), job_id, state,
        {"report-qa.md": b"anonymous QA"}, {}, {})
    assert manifest["translation_truth_hash"] == snapshots.translation_truth_hash(state)
    assert manifest["finalization_bindings"]["report_docx_hash"] == "docx-hash"
    assert manifest["finalization_bindings"]["rendered_pdf_hash"] == "pdf-hash"
    assert manifest["finalization_bindings"]["report_qa_hash"] == "qa"
    frozen = json.loads((core.job_dir(job_id) / "delivery_snapshots" /
                         "v1" / "snapshot_manifest.json").read_text())
    state["case_reviews"]["SC-0015"]["review_status"] = "rejected"
    state["pairs"][0]["target"] = "后续工作版本"
    assert json.loads((core.job_dir(job_id) / "delivery_snapshots" /
                       "v1" / "snapshot_manifest.json").read_text()) == frozen


def test_anonymous_end_to_end_finalization_freezes_the_reviewed_workflow(tmp_path):
    core.OUTPUT_DIR = tmp_path
    job_id = "stage6e2e000001"
    state = core.new_job_state("anonymous-mti.docx")
    source_pair = {"source": "The image makes distance felt.",
                   "target": "当前译文一", "initial_target": "历史初译一",
                   "segment_id": "382"}
    second_pair = {"source": "Although the field appears stable.",
                   "target": "当前译文二", "initial_target": "历史初译二",
                   "segment_id": "seg-0003"}
    state.update(
        p1_done=True, p2_done=True, p3_done=True, report_enabled=True,
        paras=[source_pair["source"], second_pair["source"]],
        pairs=[source_pair, second_pair],
        p3_md="# 翻译实践报告\n\nRQ1\n\n案例分析与结论。",
        report_status="generated", compliance_profile_id="MTI_PRACTICE_REPORT_DEFAULT",
        case_reviews={
            "SC-0015": {"review_status": "approved", "review_reason": "作者确认",
                         "reviewed_at": "fixture", "content_stale": False},
            "AR-0382": {"review_status": "approved", "review_reason": "作者确认",
                         "reviewed_at": "fixture", "content_stale": False},
        },
        final_qa=finalization.normalize_final_qa({
            "structural_qa": "PASS", "libreoffice_render": "PASS",
            "author_visual_review": "CONFIRMED", "word_final_review": "CONFIRMED",
        }),
    )
    core.save_source(job_id, b"anonymous source")
    selected = {"cases": [
        {"case_id": "SC-0015", "case_type": "synthetic_contrast",
         "case_origin": finalization.SYNTHETIC_BASELINE,
         "text_role": {"source": "SOURCE", "initial": "SYNTHETIC_BASELINE",
                       "target": "CURRENT_TRANSLATION"},
         "source_segment_id": "382", "segment_index": 0,
         "target_subsection": "3.3.2", "synthetic_baseline": {"text": "模拟初译"},
         "synthetic_evidence": {"baseline_plausibility": "pass",
                                 "material_difference": "pass",
                                 "repair_correctness": "pass"},
         "validation": {"academic_case_eligible": True}},
        {"case_id": "AR-0382", "case_type": "authentic_revision",
         "case_origin": finalization.REAL_REVISION,
         "text_role": {"source": "SOURCE", "initial": "HISTORICAL_INITIAL",
                       "target": "CURRENT_TRANSLATION"},
         "source_segment_id": "seg-0003", "segment_index": 1,
         "target_subsection": "3.3.1", "initial_target": "历史初译二"},
    ], "report_case_policy": {"report_stage": "final_report",
                               "synthetic_counts_toward_minimum": True}}
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "selected_cases", selected,
        "selected-dep", "v1")
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "outline",
        {"sections": [{"section_id": "3", "role": "case_analysis"},
                      {"section_id": "4", "role": "conclusion_reflection"}]},
        "outline-dep", "v1")
    report = {"report_status": "generated", "template_compliance": "pass",
              "report": {"abstract_zh": "摘" * 400, "keywords_zh": ["甲"] * 5,
                         "keywords_en": ["a"] * 5,
                         "appendices": ["原文：source\n译文：target"]},
              "content_hash": "report-hash"}
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "report", report, "report-dep", "v1")
    docx = core._bytes(core.markdown_to_word(state["p3_md"], ""))
    docx_hash = rendered_qa.sha256(docx)
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "final_docx_validation",
        {"status": "pass", "source_docx_hash": docx_hash,
         "content_hash": "docx-validation"}, "docx-dep", "v1",
        input_artifact_ids=["report"])
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "libreoffice_render",
        {"status": "pass", "qa_status": "PASS", "source_docx_hash": docx_hash,
         "rendered_pdf_hash": "anonymous-pdf"}, "render-dep", "v1",
        input_artifact_ids=["final_docx_validation"])
    core.save_job_state(job_id, state)
    core.save_compliance_record(job_id, state)
    core.generate_report_qa(job_id, state, save_file=True)
    core.save_job_state(job_id, state)

    frozen, approved, errors = core.approve_delivery(
        job_id, note="匿名 MTI v0.4 fixture finalization", actor="author")

    assert approved, errors
    manifest = core.list_delivery_snapshots(job_id)[0]
    assert frozen["delivery_status"] == "final"
    assert manifest["translation_truth_hash"] == core.current_translation_hash(frozen)
    assert manifest["case_reviews"]["SC-0015"]["review_status"] == "approved"
    assert manifest["finalization_bindings"]["report_docx_hash"] == docx_hash
    assert manifest["finalization_bindings"]["report_qa_hash"]
