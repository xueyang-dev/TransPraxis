"""Stage 2 dependency, lifecycle and subsection reuse regressions."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import core
from eval.mti_finalization_regression import load_fixture
from transpraxis import academic_evidence, academic_writer


def _record(name, *, segments=(), inputs=(), artifact_type="deterministic_artifact"):
    return {
        "artifact_id": name,
        "artifact_type": artifact_type,
        "file": f"{name}.json",
        "content_hash": f"hash-{name}",
        "dependency_hash": f"dep-{name}",
        "input_segment_ids": list(segments),
        "input_artifact_ids": list(inputs),
        "version": "v1",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "status": "valid",
        "stale_reason": None,
    }


def _case15_state():
    academic = academic_writer.default_academic_state()
    academic["artifacts"] = {
        "case:15": _record("case:15", segments=["382"],
                           artifact_type="case_selection_unit"),
        "case:3": _record("case:3", segments=[" unrelated "],
                          artifact_type="case_selection_unit"),
        "case:8": _record("case:8", segments=["seg-8"],
                          artifact_type="case_selection_unit"),
        "subsection:3.3.1": _record(
            "subsection:3.3.1", segments=["unrelated"],
            inputs=["case:3"], artifact_type="writing_subsection"),
        "subsection:3.3.2": _record(
            "subsection:3.3.2", segments=["382"],
            inputs=["case:15"], artifact_type="writing_subsection"),
        "section:2.1": _record("section:2.1", segments=["seg-2"],
                               artifact_type="writing_section"),
        "chapter:3": _record("chapter:3", inputs=[
            "subsection:3.3.1", "subsection:3.3.2"],
            artifact_type="chapter_composite"),
        "report": _record("report", inputs=["chapter:3"],
                          artifact_type="report_composite"),
        "final_docx_validation": _record(
            "final_docx_validation", inputs=["report"],
            artifact_type="docx_export"),
        "libreoffice_render": _record(
            "libreoffice_render", inputs=["final_docx_validation"],
            artifact_type="render_qa"),
        "literature_evidence": _record("literature_evidence"),
    }
    return {"academic_state": academic}


def test_input_ids_are_normalized_and_identical_saves_do_not_rewrite(tmp_path):
    state = {"academic_state": academic_writer.default_academic_state()}
    value = {"items": [], "content_hash": academic_evidence.stable_hash({"items": []})}
    academic_writer._save_artifact(
        state, tmp_path, "argument_plan", value, "dep", "v1",
        input_segment_ids=["seg-b", "seg-a", "seg-a"],
        input_artifact_ids=["research_model", "evidence", "research_model"])
    before = copy.deepcopy(state["academic_state"]["artifacts"]["argument_plan"])
    before_file = (tmp_path / before["file"]).read_bytes()

    academic_writer._save_artifact(
        state, tmp_path, "argument_plan", value, "dep", "v1",
        input_segment_ids=["seg-a", "seg-b"],
        input_artifact_ids=["evidence", "research_model"])

    after = state["academic_state"]["artifacts"]["argument_plan"]
    assert after["input_segment_ids"] == ["seg-a", "seg-b"]
    assert after["input_artifact_ids"] == ["evidence", "research_model"]
    assert after == before
    assert (tmp_path / before["file"]).read_bytes() == before_file


def test_legacy_artifact_record_is_valid_and_lazy_upgrades_on_save(tmp_path):
    value = {"items": [1], "content_hash": academic_evidence.stable_hash([1])}
    path = tmp_path / "argument-plan.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    state = {"academic_state": academic_writer.default_academic_state()}
    state["academic_state"]["artifacts"]["argument_plan"] = {
        "file": "argument-plan.json",
        "content_hash": value["content_hash"],
        "dependency_hash": "old-dep",
        "version": "old",
        "updated_at": "old",
    }
    record = academic_writer.artifact_record(state, "argument_plan")
    assert record["status"] == "valid"
    assert record["input_segment_ids"] == []
    assert record["input_artifact_ids"] == []
    assert academic_writer._load_valid_artifact(
        state, tmp_path, "argument_plan", "old-dep", "old") == value

    academic_writer._save_artifact(
        state, tmp_path, "argument_plan", value, "new-dep", "new",
        input_segment_ids=["382"])
    upgraded = state["academic_state"]["artifacts"]["argument_plan"]
    assert upgraded["artifact_id"] == "argument_plan"
    assert upgraded["input_segment_ids"] == ["382"]


def test_selected_cases_expose_lightweight_case_nodes(tmp_path):
    state = {"academic_state": academic_writer.default_academic_state()}
    selected = {"cases": [
        {"case_id": "SC-15", "source_segment_id": "382",
         "target_subsection": "3.3.2"},
        {"case_id": "SC-03", "source_segment_id": "unrelated",
         "target_subsection": "3.3.1"},
    ]}
    academic_writer._save_artifact(
        state, tmp_path, "selected_cases", selected, "case-dep", "v1")
    assert state["academic_state"]["artifacts"]["case:SC-15"][
        "input_segment_ids"] == ["382"]
    assert state["academic_state"]["artifacts"]["case:SC-03"][
        "input_segment_ids"] == ["unrelated"]
    assert {"case:SC-15", "case:SC-03"} <= set(
        state["academic_state"]["artifacts"]["selected_cases"]["input_artifact_ids"])


def test_segment_propagation_targets_case15_chain_and_preserves_reuse():
    state = _case15_state()
    before = copy.deepcopy(state["academic_state"]["artifacts"])
    affected = academic_writer.propagate_artifact_staleness(
        state, input_segment_ids=["382"])
    records = state["academic_state"]["artifacts"]
    assert set(affected) == {
        "case:15", "subsection:3.3.2", "chapter:3", "report",
        "final_docx_validation", "libreoffice_render",
    }
    assert records["case:15"]["status"] == "stale"
    assert records["case:15"]["stale_reason"] == {
        "code": "translation_segment_changed", "source_type": "segment",
        "source_id": "382",
    }
    assert records["subsection:3.3.2"]["stale_reason"] == {
        "code": "translation_segment_changed", "source_type": "segment",
        "source_id": "382",
    }
    assert records["chapter:3"]["stale_reason"] == {
        "code": "dependency_stale", "source_type": "artifact",
        "source_id": "subsection:3.3.2",
    }
    for name in ("case:3", "case:8", "section:2.1", "subsection:3.3.1",
                 "literature_evidence"):
        assert records[name] == before[name]

    actions = {item["artifact_id"]: item["action"] for item in
               academic_writer.artifact_execution_plan(state)}
    assert actions["subsection:3.3.2"] == "llm_rewrite"
    assert actions["chapter:3"] == "deterministic_reassemble"
    assert actions["report"] == "deterministic_reassemble"
    assert actions["final_docx_validation"] == "reexport"
    assert actions["libreoffice_render"] == "rerun_qa"
    assert actions["subsection:3.3.1"] == "reuse"


def test_translation_truth_mutation_propagates_and_revokes_working_delivery(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        state = _case15_state()
        state.update(
            p3_done=True,
            p3_md="# report",
            p3_sections=[["Report", "# report"]],
            delivery_status="final",
            delivery_approved_by_human=True,
            delivery_approval={"actor": "user"},
            pairs=[{"source": "source", "target": "old", "segment_id": "382"}],
            final_qa={"word_final_review": "CONFIRMED"},
        )
        core._mark_translation_truth_changed(
            "stage2-job", state, [0], "targeted mutation",
            actor="tester", action="test_edit")
        records = state["academic_state"]["artifacts"]
        assert records["case:15"]["status"] == "stale"
        assert records["subsection:3.3.2"]["status"] == "stale"
        assert records["chapter:3"]["status"] == "stale"
        assert records["report"]["status"] == "stale"
        assert records["final_docx_validation"]["status"] == "stale"
        assert records["libreoffice_render"]["status"] == "stale"
        assert state["dependency_impact"]["affected_case_ids"] == ["15"]
        assert state["dependency_impact"]["affected_subsection_ids"] == ["3.3.2"]
        assert state["dependency_impact"]["affected_section_ids"] == ["3"]
        assert state["p3_md"] == ""
        assert state["delivery_status"] == "draft"
        assert state["delivery_approved_by_human"] is False
        assert state["final_qa"]["word_final_review"] == "NOT_CONFIRMED"
    finally:
        core.OUTPUT_DIR = old_output


def _writing_fixture():
    def segment(segment_id, target):
        return {"segment_id": segment_id, "source": "Source " + segment_id,
                "target": target}

    evidence = {"project_evidence": {"segments": [
        segment("382", "old fifteen"), segment("unrelated", "old three")]}}
    selected_cases = {"cases": [
        {"case_id": "SC-15", "case_type": "synthetic_contrast",
         "source_segment_id": "382", "target_subsection": "3.3.2",
         "target_contrast_text": "old fifteen",
         "focus": {"source_span": {"text": "Source 382"},
                   "target_span": {"text": "old fifteen"}}},
        {"case_id": "SC-03", "case_type": "synthetic_contrast",
         "source_segment_id": "unrelated", "target_subsection": "3.3.1",
         "target_contrast_text": "old three",
         "focus": {"source_span": {"text": "Source unrelated"},
                   "target_span": {"text": "old three"}}},
    ]}
    case_plans = {"plans": [
        {"case_id": "SC-15", "target_subsection": "3.3.2"},
        {"case_id": "SC-03", "target_subsection": "3.3.1"},
    ]}
    argument_plan = {"claims": []}
    outline = {"sections": [
        {"section_id": "1", "title": "Introduction", "role": "introduction",
         "claims": [], "cases": [], "required_subsections": []},
        {"section_id": "3", "title": "Case Analysis", "role": "case_analysis",
         "claims": [], "cases": ["SC-15", "SC-03"], "required_subsections": []},
    ]}
    return evidence, selected_cases, case_plans, argument_plan, outline


def test_incremental_writing_rewrites_only_affected_subsection(tmp_path):
    evidence, selected_cases, case_plans, argument_plan, outline = _writing_fixture()
    state = {"academic_state": academic_writer.default_academic_state()}
    calls = []

    def call_llm(provider, api_key, model, system, user, **kwargs):
        packet = json.loads(user).get("packet", {})
        current = packet.get("current_section") or {}
        unit = current.get("target_subsection") or current.get("section_id")
        calls.append(str(unit))
        return f"rewritten:{unit}"

    sections_dep = "sections-dep-v1"
    academic_writer._write_writing_units(
        state, tmp_path, outline, {}, argument_plan, selected_cases, evidence,
        {}, {}, {}, case_plans, [], sections_dep, {}, set(),
        call_llm, "provider", "key", "model", lambda current: None)
    first = academic_writer._read_artifact(tmp_path / "academic-sections.json")
    unchanged_unit = copy.deepcopy(next(
        item for item in first["writing_units"]
        if item["artifact_id"] == "subsection:3.3.1"))
    unchanged_section = copy.deepcopy(next(
        item for item in first["sections"] if item["section_id"] == "1"))

    evidence["project_evidence"]["segments"][0]["target"] = "new fifteen"
    selected_cases["cases"][0]["target_contrast_text"] = "new fifteen"
    academic_writer.propagate_artifact_staleness(
        state, input_segment_ids=["382"])
    existing = academic_writer._load_reusable_sections(tmp_path)
    calls.clear()
    academic_writer._write_writing_units(
        state, tmp_path, outline, {}, argument_plan, selected_cases, evidence,
        {}, {}, {}, case_plans, [], sections_dep + "-next", existing, set(),
        call_llm, "provider", "key", "model", lambda current: None)

    second_calls = list(calls)
    assert second_calls == ["3.3.2"]
    assert set(second_calls) == {"3.3.2"}
    assert "3.3.1" not in calls
    assert "1" not in calls
    second = academic_writer._read_artifact(tmp_path / "academic-sections.json")
    reused_unit = next(item for item in second["writing_units"]
                       if item["artifact_id"] == "subsection:3.3.1")
    reused_section = next(item for item in second["sections"]
                          if item["section_id"] == "1")
    assert reused_unit == unchanged_unit
    assert reused_section == unchanged_section
    chapter = next(item for item in second["sections"]
                   if item["section_id"] == "3")
    assert chapter["artifact_type"] == "chapter_composite"
    assert "rewritten:3.3.2" in chapter["content"]
    assert "rewritten:3.3.1" in chapter["content"]
    assert academic_writer.artifact_record(
        state, "subsection:3.3.2")["status"] == "valid"
    assert academic_writer.artifact_record(
        state, "subsection:3.3.1")["status"] == "valid"


def test_case_analysis_plans_rewrite_only_stale_cases():
    selected_cases = {"cases": [
        {"case_id": "SC-15", "case_type": "synthetic_contrast",
         "source_segment_id": "382", "target_subsection": "3.3.2"},
        {"case_id": "SC-03", "case_type": "synthetic_contrast",
         "source_segment_id": "unrelated", "target_subsection": "3.3.1"},
    ]}
    old_plans = {"schema_version": "test", "plans": [
        {"case_id": "SC-15", "decision_rationale": "old fifteen"},
        {"case_id": "SC-03", "decision_rationale": "unchanged three"},
    ]}
    calls = []

    def call_llm(provider, api_key, model, system, user, **kwargs):
        payload = json.loads(user)
        calls.extend(str(x.get("case_id")) for x in payload.get("cases") or [])
        return json.dumps({"plans": [{
            "case_id": "SC-15", "decision_rationale": "new fifteen"}]})

    merged = academic_writer._rebuild_targeted_case_plans(
        old_plans, selected_cases, ["SC-15"],
        {"project_evidence": {"segments": []}}, {"claims": []}, {},
        call_llm, "provider", "key", "model", [])
    assert calls == ["SC-15"]
    by_id = {x["case_id"]: x for x in merged["plans"]}
    assert by_id["SC-15"]["decision_rationale"] == "new fifteen"
    assert by_id["SC-03"] == {
        "case_id": "SC-03", "decision_rationale": "unchanged three"}


def test_anonymous_mti_case15_incremental_regression(tmp_path):
    fixture = load_fixture()["stage2"]
    raw_cases = load_fixture()["cases"]
    selected_cases = {"cases": []}
    segments = []
    plans = []
    for raw in raw_cases:
        segment_id = str(raw["segment_id"])
        case = {
            "case_id": raw["case_id"], "case_type": raw["case_type"],
            "source_segment_id": segment_id,
            "target_subsection": raw["target_subsection"],
            "focus": {
                "source_span": {"text": raw["source"]},
                "target_span": {"text": raw["current_translation"]},
            },
        }
        if raw["case_type"] == "authentic_revision":
            case["case_type"] = "authentic_revision"
            case["focus"]["initial_span"] = {"text": raw["historical_initial"]}
        else:
            case["case_type"] = "synthetic_contrast"
            case["target_contrast_text"] = raw["current_translation"]
        selected_cases["cases"].append(case)
        segments.append({"segment_id": segment_id, "source": raw["source"],
                         "target": raw["current_translation"]})
        plans.append({"case_id": raw["case_id"],
                      "target_subsection": raw["target_subsection"]})
    evidence = {"project_evidence": {"segments": segments}}
    case_plans = {"plans": plans}
    argument_plan = {"claims": []}
    outline = {"sections": [
        {"section_id": "2", "title": "Project", "role": "project_overview",
         "claims": [], "cases": [], "required_subsections": []},
        {"section_id": "3", "title": "Case Analysis",
         "role": "case_analysis", "claims": [],
         "cases": [x["case_id"] for x in selected_cases["cases"]],
         "required_subsections": []},
    ]}
    state = {"academic_state": academic_writer.default_academic_state()}
    calls = []
    academic_writer._save_artifact(
        state, tmp_path, "selected_cases", selected_cases, "fixture-cases-v1",
        "fixture-v1")

    def call_llm(provider, api_key, model, system, user, **kwargs):
        current = json.loads(user).get("packet", {}).get("current_section") or {}
        unit = current.get("target_subsection") or current.get("section_id")
        calls.append(str(unit))
        return f"rewritten:{unit}"

    academic_writer._write_writing_units(
        state, tmp_path, outline, {}, argument_plan, selected_cases, evidence,
        {}, {}, {}, case_plans, [], "fixture-sections-v1", {}, set(),
        call_llm, "provider", "key", "model", lambda current: None)
    written, writing_units = academic_writer._write_writing_units(
        state, tmp_path, outline, {}, argument_plan, selected_cases, evidence,
        {}, {}, {}, case_plans, [], "fixture-sections-v1",
        academic_writer._load_reusable_sections(tmp_path), set(),
        call_llm, "provider", "key", "model", lambda current: None)
    calls.clear()
    report_md = academic_writer._compose_report(written)
    report_artifact = academic_writer.build_report_artifact(
        report_md, written, outline, {}, {}, selected_cases, evidence, case_plans)
    report_artifact["content_hash"] = academic_evidence.stable_hash(
        {k: v for k, v in report_artifact.items() if k != "content_hash"})

    def save_node(name, value, inputs, artifact_type):
        academic_writer._save_artifact(
            state, tmp_path, name, value,
            academic_evidence.stable_hash(value.get("content_hash") or name),
            "fixture-v1", input_artifact_ids=inputs)

    save_node("report", report_artifact, ["sections"], "report_composite")
    save_node("final_docx_validation", {"status": "pass"}, ["report"],
              "docx_export")
    save_node("libreoffice_render", {"status": "pass"}, ["final_docx_validation"],
              "render_qa")
    before = copy.deepcopy(state["academic_state"]["artifacts"])

    affected_segment = fixture["affected_segment_id"]
    segment = next(x for x in segments if x["segment_id"] == affected_segment)
    segment["target"] += " (stage 2 revision)"
    affected_case = next(x for x in selected_cases["cases"]
                         if x["source_segment_id"] == affected_segment)
    affected_case["target_contrast_text"] = segment["target"]
    affected_case["focus"]["target_span"]["text"] = segment["target"]
    # Keep the stale graph state produced by truth mutation; the production
    # pipeline rebuilds selected_cases later, not before propagation.
    state["pairs"] = [{"source": "fixture", "target": segment["target"],
                       "segment_id": affected_segment}]
    core._mark_translation_truth_changed(
        "anonymous-case15", state, [0], "Case 15-style segment revision")

    affected_records = state["academic_state"]["artifacts"]
    assert affected_records[f"case:{fixture['affected_case_id']}"]["status"] == "stale"
    assert affected_records[
        f"subsection:{fixture['affected_subsection_id']}"]["status"] == "stale"
    assert affected_records[f"chapter:{fixture['chapter_id']}"]["status"] == "stale"
    assert affected_records["report"]["status"] == "stale"
    assert affected_records["final_docx_validation"]["status"] == "stale"
    assert affected_records["libreoffice_render"]["status"] == "stale"
    assert affected_records[f"chapter:{fixture['chapter_id']}"][
        "input_segment_ids"] == []
    assert affected_records["report"]["input_segment_ids"] == []

    written, _ = academic_writer._write_writing_units(
        state, tmp_path, outline, {}, argument_plan, selected_cases, evidence,
        {}, {}, {}, case_plans, [], "fixture-sections-v2",
        academic_writer._load_reusable_sections(tmp_path), set(),
        call_llm, "provider", "key", "model", lambda current: None)
    rebuilt_report = academic_writer._compose_report(written)
    assert rebuilt_report != report_md
    assert set(calls) == {fixture["affected_subsection_id"]}
    assert calls.count(fixture["affected_subsection_id"]) == 1

    unaffected_case = f"case:{fixture['unaffected_case_id']}"
    unaffected_unit = f"subsection:{fixture['unaffected_subsection_id']}"
    for name in (unaffected_case, unaffected_unit, "section:2"):
        assert state["academic_state"]["artifacts"][name] == before[name]
    second = academic_writer._read_artifact(
        tmp_path / academic_writer.ARTIFACT_FILES["sections"])
    assert next(x for x in second["writing_units"]
                if x["artifact_id"] == unaffected_unit)["content_hash"] == \
        next(x for x in writing_units if x["artifact_id"] == unaffected_unit)[
            "content_hash"]
