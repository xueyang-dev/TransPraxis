"""Focused checks for Synthetic Contrast Case generation and rejection.

Run: .venv/bin/python tests/synthetic_cases_test.py
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docx import Document

import core
from transpraxis import academic_evidence, academic_quality, academic_validator, academic_writer
from transpraxis import case_analysis, case_presentation, human_evidence, synthetic_cases


JOB = "syntheticfixture"


def _state() -> dict:
    sources = [
        "He did not stop short of calling the plan a failure.",
        "When David told Avi that he had won, he smiled.",
        "The room was cold.",
    ]
    return {
        "paras": sources,
        "pairs": [{"source": source, "target": f"真实终译{i}",
                   "initial_target": f"真实初译{i}" if i < 2 else f"真实终译{i}",
                   "reviewed": True,
                   "from_tm": False, "glossary_entry_ids": []}
                  for i, source in enumerate(sources)],
        "findings": [], "human_actions": [], "glossary": [],
    }


class SuccessfulModel:
    def __init__(self):
        self.baseline_payload = None

    def __call__(self, provider, api_key, model, system, user, temperature=0.1):
        payload = json.loads(user)
        if "translation-error opportunities" in system:
            return json.dumps({"opportunities": [{
                "segment_id": f"seg-{JOB}-0000",
                "error_category": "negation_scope",
                "trigger_span": "did not stop short of",
                "difficulty_reason": "The nested negation reverses the apparent polarity.",
                "likely_failure_mode": "Read stop short of as simply stop.",
                "academic_value": "high", "confidence": "high",
            }]})
        if "simulated Chinese initial translation" in system:
            self.baseline_payload = payload
            return json.dumps({"baselines": [{
                "case_id": "SC-0000", "text": "他没有把这个计划称为失败。",
                "why_tempting": "把 stop short of 按字面理解为停止。",
            }]}, ensure_ascii=False)
        if "plausibly be" in system:
            return json.dumps({"reviews": [{
                "case_id": "SC-0000", "status": "plausible",
                "reason": "译文流畅，错误来自可理解的否定范围误判。",
            }]}, ensure_ascii=False)
        if "Diagnose each plausible" in system:
            return json.dumps({"diagnoses": [{
                "case_id": "SC-0000", "category": "negation_scope",
                "diagnosis": "基线把双重否定关系处理成没有批评。",
                "why_tempting": "stop 与 not 的表层组合容易诱发误读。",
                "meaning_or_function_distortion": "原文实际表示他几乎直言该计划失败。",
                "materiality": "major", "baseline_already_adequate": False,
                "source_evidence_span": "did not stop short of",
                "source_evidence": "did not stop short of",
            }]}, ensure_ascii=False)
        if "independently optimized" in system:
            return json.dumps({"optimizations": [{
                "case_id": "SC-0000", "text": "他甚至直言这个计划是失败的。",
                "repair_decision": "恢复双重否定表达的肯定语义。",
                "addresses_error": "明确呈现其已经作出批评。",
            }]}, ensure_ascii=False)
        if "Independently validate" in system:
            return json.dumps({"validations": [{
                "case_id": "SC-0000", "diagnosis_grounding": "confirmed",
                "error_materiality": "confirmed",
                "repair_correctness": "confirmed", "repair_value": "confirmed",
                "academic_analysis_value": "confirmed",
                "baseline_issue_span": "没有把这个计划称为失败",
                "final_repair_span": "甚至直言这个计划是失败的",
                "academic_analysis_value_reason": "The contrast isolates the negation mechanism.",
                "baseline_already_correct": False, "unrelated_meaning_change": False,
                "reason": "优化译文恢复了否定范围和语用力度。",
            }]}, ensure_ascii=False)
        raise AssertionError(system)


def test_successful_staged_pipeline_preserves_history():
    state = _state()
    before = copy.deepcopy(state)
    pair_hash_before = academic_evidence.stable_hash(state["pairs"])
    evidence = academic_evidence.build_academic_evidence(state, JOB)
    model = SuccessfulModel()
    opportunities = synthetic_cases.mine_error_opportunities(
        evidence, model, "fake", "key", "model")
    baselines = synthetic_cases.generate_baselines(
        opportunities, model, "fake", "key", "model")
    manifest = synthetic_cases.build_error_manifest(
        baselines, model, "fake", "key", "model")
    optimized = synthetic_cases.optimize_translations(
        manifest, model, "fake", "key", "model")
    validated = synthetic_cases.validate_synthetic_cases(
        optimized, model, "fake", "key", "model", evidence)
    case = validated["items"][0]
    assert case["case_type"] == "synthetic_contrast"
    assert case["provenance"]["historical"] is False
    assert case["provenance"]["generated_for_analysis"] is True
    assert case["case_origin"] == "SYNTHETIC_BASELINE"
    assert case["text_role"]["initial"] == "SYNTHETIC_BASELINE"
    assert case["review_status"] == "unreviewed"
    assert case["validation"]["academic_case_eligible"]
    assert case["opportunity_id"] == "EO-0000"
    assert case["optimized_translation"]["repairs_error_id"] == \
        case["error"]["error_id"]
    assert "initial_target" not in case and "final_target" not in case
    assert state == before
    assert academic_evidence.stable_hash(state["pairs"]) == pair_hash_before
    baseline_payload = json.dumps(model.baseline_payload, ensure_ascii=False)
    assert "真实初译" not in baseline_payload and "真实终译" not in baseline_payload
    print("  ✓ staged synthetic case passes without historical-state contamination")


def test_project_target_binding_is_read_only_and_uses_three_gates():
    state, evidence, validated = _validated_fixture()
    before_pairs = copy.deepcopy(state["pairs"])

    class NoGeneration:
        def __call__(self, *_args, **_kwargs):
            raise AssertionError("project target binding must not call a generator")

    bound = synthetic_cases.optimize_translations(
        validated, NoGeneration(), "fake", "key", "model", evidence=evidence)
    row = bound["items"][0]
    segment = academic_evidence.segment_index(evidence)[row["source_segment_id"]]
    assert row["final_target"] == segment["final_target"]
    assert row["optimized_translation"]["text"] == segment["final_target"]
    assert row["optimized_translation"]["generation_status"] == "project_target"
    assert row["optimized_translation"]["provenance"] == "project_current_target"
    assert row["provenance"]["historical"] is False
    assert row["provenance"]["generated_for_analysis"] is True
    assert row["case_origin"] == "SYNTHETIC_BASELINE"
    assert row["text_role"]["target"] == "CURRENT_TRANSLATION"

    class GateReviewer:
        def __call__(self, _provider, _api_key, _model, system, user, temperature=0.1):
            assert "current project target" in system
            cases = json.loads(user)["cases"]
            return json.dumps({"validations": [{
                "case_id": case["case_id"],
                "diagnosis_grounding": "confirmed",
                "material_difference": "confirmed",
                "repair_correctness": "confirmed",
                "repair_value": "confirmed",
                "academic_analysis_value": "confirmed",
                "baseline_issue_span": case["synthetic_baseline"]["text"],
                "final_repair_span": case["optimized_translation"]["text"],
                "academic_analysis_value_reason": "The contrast isolates the project-target repair.",
                "baseline_already_correct": False,
                "unrelated_meaning_change": False,
                "reason": "The project target addresses the diagnosed issue.",
            } for case in cases]})

    checked = synthetic_cases.validate_synthetic_cases(
        bound, GateReviewer(), "fake", "key", "model", evidence)
    checked_row = checked["items"][0]
    assert checked_row["validation"]["academic_case_eligible"]
    assert checked_row["synthetic_evidence"] == {
        "historical": False,
        "generated_for_analysis": True,
        "baseline_plausibility": "pass",
        "material_difference": "pass",
        "repair_correctness": "pass",
        "academic_analysis_value": "pass",
        "generation_reason": checked_row["generation_reason"],
        "targeted_issue": checked_row["targeted_issue"],
        "academic_analysis_reason": checked_row["synthetic_evidence"][
            "academic_analysis_reason"],
    }
    assert state["pairs"] == before_pairs
    assert bound["generated"] == 0
    assert bound["model_call_status"] == "not_called_project_target"

    tampered = copy.deepcopy(bound)
    tampered["items"][0]["target_contrast_text"] = "不是项目正式译文"
    rejected = synthetic_cases.validate_synthetic_cases(
        tampered, GateReviewer(), "fake", "key", "model", evidence)
    assert not rejected["items"][0]["validation"]["academic_case_eligible"]
    assert "project_target_grounded" in rejected["items"][0]["validation"][
        "rejected_reasons"]
    print("  ✓ current target is read-only; plausibility, materiality and repair gates stay separate")


def test_visible_synthetic_schema_uses_simulated_initial_and_revised_target():
    node = {
        "case_id": "SC-0001", "case_type": "synthetic_contrast", "example_number": 1,
        "focus": {
            "source_span": {"text": "The source sentence contains a metaphor."},
            "target_span": {"text": "正式译文保留了其修辞功能。"},
            "issue": "metaphor → 修辞功能",
        },
        "synthetic_baseline": {"text": "正式译文把它直译了。"},
        "analysis_fields": {"visible_analysis": [
            "模拟译法基本可通，但把隐喻功能压平；改译在当前语境中恢复了该功能。"]},
    }
    presentation = case_presentation.build_case_presentation(node)
    rendered = case_presentation.render_case_presentation_markdown(presentation)
    assert "**模拟初译**：" in rendered
    assert "**改译**：" in rendered
    assert "**初译**：" not in rendered
    assert "**译文**：" not in rendered
    print("  ✓ synthetic visible schema is 原文/模拟初译/改译/分析")


def test_review_grounding_requires_an_explicit_matching_trigger():
    state = _state()
    state["findings"] = [{
        "segment_index": 0, "type": "review", "severity": "actionable",
        "reason": "原文 did not stop short of 涉及否定范围，按字面处理会颠倒语义。",
    }]
    evidence = academic_evidence.build_academic_evidence(state, JOB)
    grounded = synthetic_cases.mine_error_opportunities(
        evidence, SuccessfulModel(), "fake", "key", "model")["items"][0]
    assert grounded["error_pattern_grounding"]["type"] == "project_review_pattern"

    state["findings"][0]["reason"] = "本段标点可进一步统一。"
    evidence = academic_evidence.build_academic_evidence(state, JOB)
    inferred = synthetic_cases.mine_error_opportunities(
        evidence, SuccessfulModel(), "fake", "key", "model")["items"][0]
    assert inferred["error_pattern_grounding"]["type"] == "model_inference"
    print("  ✓ review-pattern grounding requires an explicit same-trigger finding")


def _validated_fixture():
    state = _state()
    evidence = academic_evidence.build_academic_evidence(state, JOB)
    model = SuccessfulModel()
    opportunities = synthetic_cases.mine_error_opportunities(
        evidence, model, "fake", "key", "model")
    baselines = synthetic_cases.generate_baselines(
        opportunities, model, "fake", "key", "model")
    manifest = synthetic_cases.build_error_manifest(
        baselines, model, "fake", "key", "model")
    optimized = synthetic_cases.optimize_translations(
        manifest, model, "fake", "key", "model")
    validated = synthetic_cases.validate_synthetic_cases(
        optimized, model, "fake", "key", "model", evidence)
    return state, evidence, validated


def _candidate(case_id: str, *, plausibility="plausible", materiality="major",
               adequate=False, optimized="他甚至直言这个计划就是失败的。") -> dict:
    return {
        "case_id": case_id, "case_type": "synthetic_contrast",
        "source_segment_id": f"seg-{JOB}-0000",
        "source_text": "He did not stop short of calling the plan a failure.",
        "context_before": "The surrounding paragraph frames the speaker's evaluation.",
        "context_after": "The following sentence explains the consequence.",
        "difficulty": {"category": "lexical_polysemy", "trigger": "stop short of",
                       "academic_value": "high",
                       "reason": "A grounded ambiguity."},
        "synthetic_baseline": {"text": "模拟译文", "generation_status": "generated",
                               "provenance": "model_generated_for_analysis"},
        "baseline_plausibility": {"status": plausibility, "reason": "review"},
        "error": {"error_id": f"ERR-{case_id.removeprefix('SC-')}",
                  "category": "lexical_polysemy", "diagnosis": "material diagnosis",
                  "source_evidence_span": "stop short of",
                  "source_evidence": "stop short of",
                  "materiality": materiality, "baseline_already_adequate": adequate},
        "optimized_translation": {"text": optimized, "generation_status": "generated",
                                  "provenance": "ai_optimized_for_analysis",
                                  "repairs_error_id": f"ERR-{case_id.removeprefix('SC-')}",
                                  "repair_decision": "repair the diagnosed error",
                                  "addresses_error": "restores the source meaning"},
        "provenance": {"historical": False, "generated_for_analysis": True},
    }


class RejectionValidator:
    def __call__(self, provider, api_key, model, system, user, temperature=0.1):
        cases = json.loads(user)["cases"]
        rows = []
        for case in cases:
            case_id = case["case_id"]
            rows.append({
                "case_id": case_id,
                "diagnosis_grounding": "not_confirmed" if case_id == "SC-DIAG"
                else "confirmed",
                "error_materiality": "not_confirmed" if case_id == "SC-MINOR"
                else "confirmed",
                "repair_correctness": "not_confirmed" if case_id == "SC-REPAIR"
                else "confirmed",
                "repair_value": "not_confirmed" if case_id == "SC-REPAIR"
                else "confirmed",
                "academic_analysis_value": "confirmed",
                "baseline_issue_span": case["synthetic_baseline"]["text"],
                "final_repair_span": case["optimized_translation"]["text"],
                "academic_analysis_value_reason": "The case exposes a non-surface mechanism.",
                "baseline_already_correct": case_id == "SC-CORRECT",
                "unrelated_meaning_change": case_id == "SC-UNRELATED",
                "reason": "independent decision",
            })
        return json.dumps({"validations": rows})


def test_rejection_gates():
    items = [
        _candidate("SC-ABSURD", plausibility="implausible"),
        _candidate("SC-MINOR", materiality="minor"),
        _candidate("SC-CORRECT", adequate=True),
        _candidate("SC-REPAIR"),
        _candidate("SC-DIAG"),
        _candidate("SC-UNRELATED"),
        _candidate("SC-GOOD"),
    ]
    artifact = {"items": items}
    result = synthetic_cases.validate_synthetic_cases(
        artifact, RejectionValidator(), "fake", "key", "model",
        academic_evidence.build_academic_evidence(_state(), JOB))
    eligibility = {x["case_id"]: x["validation"]["academic_case_eligible"]
                   for x in result["items"]}
    assert eligibility == {
        "SC-ABSURD": False, "SC-MINOR": False, "SC-CORRECT": False,
        "SC-REPAIR": False, "SC-DIAG": False, "SC-UNRELATED": False,
        "SC-GOOD": True,
    }
    assert result["metrics"]["academically_eligible_synthetic_cases"] == 1
    print("  ✓ absurd, non-material, already-correct and unrepaired cases are rejected")


def test_mixed_selection_and_human_evidence_never_promote_synthetic():
    _, evidence, synthetic = _validated_fixture()
    selected = academic_writer.select_academic_cases(
        {}, {"claims": []}, evidence, limit=3,
        synthetic_artifact=synthetic, policy="mixed")
    assert selected["authentic_revision_cases"] == 2
    assert selected["synthetic_contrast_cases"] == 1
    assert selected["selection_status"] == "mixed_case_selection"
    assert sum(x["case_type"] == "authentic_revision" for x in selected["cases"]) == 2
    assert sum(x["case_type"] == "synthetic_contrast" for x in selected["cases"]) == 1
    assert {x["case_type"] for x in selected["cases"]} == {
        "authentic_revision", "synthetic_contrast"}
    assert len({x["case_id"] for x in selected["cases"]}) == len(selected["cases"])

    case = next(x for x in selected["cases"] if x["case_type"] == "synthetic_contrast")
    adequacy = case_analysis.synthetic_evidence_adequacy(case)
    enriched = human_evidence.case_capabilities(case["case_id"], [{
        "human_evidence_id": "HE-SYNTH", "case_id": case["case_id"],
        "question_type": "synthetic_baseline_plausibility", "status": "user_confirmed",
    }], adequacy)
    assert enriched["case_type"] == "synthetic_contrast"
    assert not enriched["capabilities"]["has_meaningful_revision"]
    assert enriched["capabilities"]["has_author_synthetic_judgment"]
    print("  ✓ mixed pools remain distinct; Human Evidence cannot promote synthetic history")


def _transparent_report(case: dict) -> str:
    case_id = case["case_id"]
    return f"""### 真实修订案例

真实修订案例依据保存的历史版本分析。

### 合成对比案例

合成对比案例使用模拟初译；模拟初译与优化译文均为分析阶段生成，不代表作者的历史译文。
<!--synthetic-methodology-->
<!--case-count-policy:two_case_fallback-->

[{case_id}]
> [SYNTHETIC_SOURCE {case_id}]: {case['source_text']}
> [SIMULATED {case_id}]: {case['synthetic_baseline']['text']}
> [OPTIMIZED {case_id}]: {case['optimized_translation']['text']}

本例只展示一种合理的翻译失败模式，不能证明其在人类译者中的实际发生频率。
<!--synthetic-limitation-->
"""


def test_validator_blocks_historical_language_and_requires_disclosure():
    _, evidence, synthetic = _validated_fixture()
    selected = academic_writer.select_academic_cases(
        {}, {"claims": []}, evidence, limit=3,
        synthetic_artifact=synthetic, policy="mixed")
    case = next(x for x in selected["cases"] if x["case_type"] == "synthetic_contrast")
    report = _transparent_report(case)
    result = academic_validator.validate_academic_report(
        report, evidence, {"research_questions": []}, {"claims": []}, selected,
        {"sections": []}, synthetic_artifact=synthetic)
    relevant = {x["type"] for x in result["issues"]}
    assert not ({"synthetic_case_presented_as_historical",
                 "missing_synthetic_methodology_disclosure",
                 "missing_synthetic_limitation_disclosure",
                 "wrong_synthetic_case_quote"} & relevant)

    laundered = report + f"\n\n[{case['case_id']}] 笔者初译为上述版本，经审校后修改为优化译文。"
    bad = academic_validator.validate_academic_report(
        laundered, evidence, {"research_questions": []}, {"claims": []}, selected,
        {"sections": []}, synthetic_artifact=synthetic)
    assert "synthetic_case_presented_as_historical" in {
        x["type"] for x in bad["issues"]}

    hidden = academic_validator.validate_academic_report(
        report.replace("<!--synthetic-methodology-->", ""), evidence,
        {"research_questions": []}, {"claims": []}, selected,
        {"sections": []}, synthetic_artifact=synthetic)
    assert "missing_synthetic_methodology_disclosure" in {
        x["type"] for x in hidden["issues"]}
    print("  ✓ provenance laundering fails; methodology and limitation are mandatory")


def test_outline_accepts_selected_synthetic_case():
    _, evidence, synthetic = _validated_fixture()
    selected = academic_writer.select_academic_cases(
        {}, {"claims": []}, evidence, limit=3,
        synthetic_artifact=synthetic, policy="mixed")
    case = next(x for x in selected["cases"] if x["case_type"] == "synthetic_contrast")
    result = academic_validator.validate_academic_report(
        "## 3 案例分析\n\n" + _transparent_report(case), evidence,
        {"research_questions": []}, {"claims": []}, selected,
        {"sections": [{"section_id": "3", "title": "案例分析",
                       "cases": [case["case_id"]], "minimum_chars": 100}]},
        synthetic_artifact=synthetic)
    assert "outline_unknown_case" not in {x["type"] for x in result["issues"]}
    print("  ✓ outline validation recognizes selected synthetic cases")


def test_outline_accepts_numbered_heading_with_period():
    _, evidence, synthetic = _validated_fixture()
    selected = academic_writer.select_academic_cases(
        {}, {"claims": []}, evidence, limit=3,
        synthetic_artifact=synthetic, policy="mixed")
    case = next(x for x in selected["cases"] if x["case_type"] == "synthetic_contrast")
    result = academic_validator.validate_academic_report(
        "## 3. 案例分析\n\n" + _transparent_report(case), evidence,
        {"research_questions": []}, {"claims": []}, selected,
        {"sections": [{"section_id": "3", "title": "案例分析",
                       "cases": [case["case_id"]], "minimum_chars": 100}]},
        synthetic_artifact=synthetic)
    assert "missing_required_section" not in {x["type"] for x in result["issues"]}
    print("  ✓ numbered heading with a period maps to the planned section")


def test_synthetic_delta_is_not_checked_as_authentic_history():
    _, evidence, synthetic = _validated_fixture()
    selected = academic_writer.select_academic_cases(
        {}, {"claims": []}, evidence, limit=3,
        synthetic_artifact=synthetic, policy="mixed")
    case = next(x for x in selected["cases"] if x["case_type"] == "synthetic_contrast")
    report = "## 3 案例分析\n\n" + _transparent_report(case) + \
        "\n\n将“你为什么需要”改为“你要……干什么”。"
    result = academic_validator.validate_academic_report(
        report, evidence, {"research_questions": []}, {"claims": []}, selected,
        {"sections": [{"section_id": "3", "title": "案例分析",
                       "cases": [x["case_id"] for x in selected["cases"]],
                       "minimum_chars": 100}]}, synthetic_artifact=synthetic)
    assert "described_revision_not_in_stored_delta" not in {
        x["type"] for x in result["issues"]}
    print("  ✓ synthetic delta is validated in its own provenance pool")


def test_docx_labels_and_tm_isolation():
    _, _, synthetic = _validated_fixture()
    case = synthetic["items"][0]
    report = _transparent_report(case)
    doc = Document(BytesIO(core.markdown_to_word(report, "功能对等理论").getvalue()))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "模拟初译" in text and "优化译文" in text
    assert "SYNTHETIC_SOURCE" not in text and "SIMULATED" not in text \
        and "OPTIMIZED" not in text
    assert "synthetic-methodology" not in text

    with tempfile.TemporaryDirectory() as tmp:
        tm = Path(tmp) / "translation_memory.json"
        tm.write_text('{"real source":"real target"}', encoding="utf-8")
        before = tm.read_bytes()
        synthetic_cases.select_diverse_cases(synthetic, 3)
        assert tm.read_bytes() == before
    print("  ✓ DOCX keeps transparent labels; synthetic selection does not touch TM")


def test_synthetic_stage_staleness_is_local():
    artifact_names = set(academic_writer.ARTIFACT_FILES)
    state = {"academic_state": {
        "versions": {**academic_writer.VERSIONS,
                     "synthetic_baseline_version": "old-baseline"},
        "artifacts": {name: {"content_hash": name} for name in artifact_names},
    }, "p3_done": True}
    academic_writer.sync_versions(state)
    remaining = set(state["academic_state"]["artifacts"])
    assert {"evidence", "literature_sources", "literature_evidence",
            "literature_claims", "synthetic_opportunities"}.issubset(remaining)
    assert not ({"synthetic_baselines", "synthetic_error_manifest",
                 "synthetic_optimized", "synthetic_validation", "selected_cases",
                 "sections"} & remaining)
    print("  ✓ baseline-version change invalidates only synthetic downstream and writing")


def test_synthetic_optimizer_dependency_invalidates_bound_segment(tmp_path):
    evidence = academic_evidence.build_academic_evidence(_state(), JOB)
    manifest = {"pipeline_status": "complete", "items": [_candidate("SC-15")]}
    before = academic_writer._synthetic_optimizer_dependency_hash(manifest, evidence)
    changed = copy.deepcopy(evidence)
    changed["project_evidence"]["segments"][0]["final_target"] = "当前译文已改变"
    after = academic_writer._synthetic_optimizer_dependency_hash(manifest, changed)
    assert after != before

    state = {"academic_state": academic_writer.default_academic_state()}
    items = [{"case_id": "cached"}]
    value = {"items": items, "content_hash": academic_evidence.stable_hash(items)}
    version = academic_writer.VERSIONS["synthetic_optimizer_version"]
    academic_writer._save_artifact(
        state, tmp_path, "synthetic_optimized", value, before, version)
    assert academic_writer._load_valid_artifact(
        state, tmp_path, "synthetic_optimized", after, version) is None


def test_synthetic_optimizer_dependency_reuses_unrelated_segment(tmp_path):
    evidence = academic_evidence.build_academic_evidence(_state(), JOB)
    manifest = {"pipeline_status": "complete", "items": [_candidate("SC-15")]}
    before = academic_writer._synthetic_optimizer_dependency_hash(manifest, evidence)
    unrelated = copy.deepcopy(evidence)
    unrelated["project_evidence"]["segments"][2]["final_target"] = "无关段落已改变"
    after = academic_writer._synthetic_optimizer_dependency_hash(manifest, unrelated)
    assert after == before

    state = {"academic_state": academic_writer.default_academic_state()}
    items = [{"case_id": "cached"}]
    value = {"items": items, "content_hash": academic_evidence.stable_hash(items)}
    version = academic_writer.VERSIONS["synthetic_optimizer_version"]
    academic_writer._save_artifact(
        state, tmp_path, "synthetic_optimized", value, before, version)
    assert academic_writer._load_valid_artifact(
        state, tmp_path, "synthetic_optimized", after, version) == value


def test_section_dependencies_only_follow_relevant_synthetic_cases():
    evidence = academic_evidence.build_academic_evidence(_state(), JOB)
    argument = {"content_hash": "argument"}
    literature_sources = {"sources_metadata_hash": "sources"}
    literature_evidence = {"content_hash": "evidence"}
    literature_claims = {"content_hash": "claims"}
    selected_before = {
        "authentic_selection_status": "two_case_fallback",
        "synthetic_contrast_cases": 0, "cases": []}
    selected_after = copy.deepcopy(selected_before)
    selected_after["synthetic_contrast_cases"] = 1
    selected_after["cases"] = [_candidate("SC-0000")]
    section2 = {"section_id": "2", "cases": [], "claims": []}
    section3_before = {"section_id": "3", "cases": [], "claims": []}
    section3_after = {"section_id": "3", "cases": ["SC-0000"], "claims": []}

    def key(plan, selected):
        return academic_writer._section_dependency_hash(
            plan, argument, selected, evidence, literature_sources,
            literature_evidence, literature_claims, {"plans": []}, [])

    assert key(section2, selected_before) == key(section2, selected_after)
    assert key(section3_before, selected_before) != key(section3_after, selected_after)
    assert key({"section_id": "1", "cases": [], "claims": []}, selected_before) != \
        key({"section_id": "1", "cases": [], "claims": []}, selected_after)
    print("  ✓ synthetic changes invalidate case/disclosure sections, not unrelated sections")


def test_mixed_analysis_contracts_are_distinct():
    _, evidence, synthetic = _validated_fixture()
    selected = academic_writer.select_academic_cases(
        {}, {"claims": []}, evidence, limit=3,
        synthetic_artifact=synthetic, policy="mixed")
    plans = case_analysis.build_case_analysis_plans(
        evidence, selected, {"claims": []}, {"items": []},
        lambda *args, **kwargs: "{}", "fake", "key", "model")
    by_type = {x["case_type"]: x for x in plans["plans"]}
    assert {"authentic_revision", "synthetic_contrast"}.issubset(by_type)
    synthetic_contract = case_analysis.render_analysis_contract(
        by_type["synthetic_contrast"])
    authentic_contract = case_analysis.render_analysis_contract(
        by_type["authentic_revision"])
    assert "模拟初译" in synthetic_contract and "非历史证据" in synthetic_contract
    assert "历史初译" not in synthetic_contract
    assert "初译不足" in authentic_contract and "终译" in authentic_contract
    print("  ✓ authentic and synthetic analysis contracts use different reasoning chains")


def test_provenance_red_team():
    _, evidence, synthetic = _validated_fixture()
    selected = academic_writer.select_academic_cases(
        {}, {"claims": []}, evidence, limit=3,
        synthetic_artifact=synthetic, policy="mixed")
    case = next(x for x in selected["cases"] if x["case_type"] == "synthetic_contrast")
    base = _transparent_report(case)
    attacks = {
        "reviewer_history": f"[{case['case_id']}] 经审校后修改为优化译文。",
        "common_error": f"[{case['case_id']}] 这是常见的人类翻译错误。",
    }
    expected = {
        "reviewer_history": "synthetic_case_presented_as_historical",
        "common_error": "unsupported_human_error_frequency_claim",
    }
    for name, attack in attacks.items():
        result = academic_validator.validate_academic_report(
            base + "\n\n" + attack, evidence, {"research_questions": []},
            {"claims": []}, selected, {"sections": []},
            synthetic_artifact=synthetic)
        assert expected[name] in {x["type"] for x in result["issues"]}

    section_laundering = base.replace(
        f"[{case['case_id']}]\n", "") + "\n笔者初译为上述版本。"
    result = academic_validator.validate_academic_report(
        section_laundering, evidence, {"research_questions": []}, {"claims": []},
        selected, {"sections": []}, synthetic_artifact=synthetic)
    assert "synthetic_case_presented_as_historical" in {
        x["type"] for x in result["issues"]}

    tampered = copy.deepcopy(selected)
    next(x for x in tampered["cases"] if x["case_type"] == "synthetic_contrast")[
        "provenance"]["historical"] = True
    result = academic_validator.validate_academic_report(
        base, evidence, {"research_questions": []}, {"claims": []}, tampered,
        {"sections": []}, synthetic_artifact=synthetic)
    assert "synthetic_case_provenance_mismatch" in {
        x["type"] for x in result["issues"]}
    print("  ✓ red-team laundering, reviewer history, frequency and provenance tampering fail")


def test_canonical_source_identity_is_required():
    evidence = academic_evidence.build_academic_evidence(_state(), JOB)
    case = _candidate("SC-TAMPER")
    case["source_text"] = "Invented source text."
    result = synthetic_cases.validate_synthetic_cases(
        {"items": [case]}, RejectionValidator(), "fake", "key", "model", evidence)
    validated = result["items"][0]
    assert not validated["validation"]["academic_case_eligible"]
    assert "real_source_exists" in validated["validation"]["rejected_reasons"]

    passage = _candidate("SC-PASSAGE")
    passage["source_text"] = "did not stop short of calling the plan a failure."
    result = synthetic_cases.validate_synthetic_cases(
        {"items": [passage]}, RejectionValidator(), "fake", "key", "model", evidence)
    assert result["items"][0]["validation"]["academic_case_eligible"]
    print("  ✓ final eligibility accepts only exact passages from canonical source")


def test_quality_replacement_never_crosses_case_pools():
    _, evidence, synthetic = _validated_fixture()
    selected = academic_writer.select_academic_cases(
        {}, {"claims": []}, evidence, limit=3,
        synthetic_artifact=synthetic, policy="mixed")
    synthetic_case = next(x for x in selected["cases"]
                          if x["case_type"] == "synthetic_contrast")
    replacement = academic_quality.select_replacement_case(
        synthetic_case["case_id"], [], selected, {"claims": []}, evidence,
        synthetic)
    assert replacement is None or replacement["case_type"] == "synthetic_contrast"
    print("  ✓ quality repair cannot replace synthetic cases from authentic pool")


def test_synthetic_human_evidence_is_judgment_not_history():
    _, evidence, synthetic = _validated_fixture()
    case = synthetic["items"][0]
    plan = {
        "case_id": case["case_id"], "case_type": "synthetic_contrast",
        "source_segment_id": case["source_segment_id"],
        "source_text": case["source_text"],
        "translation_delta": case["actual_delta"],
        "synthetic_baseline": case["synthetic_baseline"],
        "optimized_translation": case["optimized_translation"],
        "problem": {"statement": "否定范围", "grounded": True},
        "evidence_level": "validated_synthetic_contrast",
        "cannot_support": ["historical_revision_reasoning"],
    }
    plans = {"plans": [plan]}
    needs = human_evidence.build_evidence_needs(evidence, plans)
    questions = human_evidence.generate_questions(needs, evidence, plans)
    assert {x["question_type"] for x in questions["questions"]} == {
        "synthetic_baseline_plausibility", "synthetic_optimization_preference"}
    entries = []
    current = questions
    for question in questions["questions"]:
        entry, current = human_evidence.record_human_answer(
            current, question["question_id"], "仅作为分析判断，此方案具有可讨论性。",
            evidence, interface="unit_test", existing=entries)
        entries.append(entry)
    enriched = human_evidence.case_capabilities(
        case["case_id"], entries, case_analysis.synthetic_evidence_adequacy(case))
    assert enriched["capabilities"]["has_author_synthetic_judgment"]
    assert not enriched["capabilities"]["has_meaningful_revision"]
    assert "historical_revision_reasoning" in enriched["cannot_support"]
    print("  ✓ Human Evidence enriches synthetic judgment without creating history")


def test_synthetic_only_requires_an_eligible_case():
    evidence = academic_evidence.build_academic_evidence(_state(), JOB)
    selected = academic_writer.select_academic_cases(
        {}, {"claims": []}, evidence, limit=3,
        synthetic_artifact={"items": [], "pipeline_status": "complete"},
        policy="synthetic_only")
    assert selected["selection_status"] == "no_eligible_synthetic_cases"
    validation = academic_validator.validate_academic_report(
        "", evidence, {"research_questions": []}, {"claims": []}, selected,
        {"sections": []}, synthetic_artifact={"items": []})
    assert "synthetic_only_without_eligible_cases" in {
        x["type"] for x in validation["issues"]}
    assert validation["status"] == "fail"
    print("  ✓ synthetic-only cannot silently succeed with an empty eligible pool")


def test_provider_failure_is_not_reported_as_zero_difficulty():
    evidence = academic_evidence.build_academic_evidence(_state(), JOB)

    def unavailable(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    opportunities = synthetic_cases.mine_error_opportunities(
        evidence, unavailable, "fake", "key", "model")
    baselines = synthetic_cases.generate_baselines(
        opportunities, unavailable, "fake", "key", "model")
    manifest = synthetic_cases.build_error_manifest(
        baselines, unavailable, "fake", "key", "model")
    optimized = synthetic_cases.optimize_translations(
        manifest, unavailable, "fake", "key", "model")
    validated = synthetic_cases.validate_synthetic_cases(
        optimized, unavailable, "fake", "key", "model", evidence)
    assert opportunities["pipeline_status"] == "failed"
    assert "provider unavailable" in opportunities["model_call_error"]
    assert validated["pipeline_status"] == "failed"
    print("  ✓ provider failure propagates explicitly instead of masquerading as no difficulty")


if __name__ == "__main__":
    print("合成对比案例测试：")
    test_successful_staged_pipeline_preserves_history()
    test_review_grounding_requires_an_explicit_matching_trigger()
    test_rejection_gates()
    test_mixed_selection_and_human_evidence_never_promote_synthetic()
    test_validator_blocks_historical_language_and_requires_disclosure()
    test_outline_accepts_selected_synthetic_case()
    test_outline_accepts_numbered_heading_with_period()
    test_synthetic_delta_is_not_checked_as_authentic_history()
    test_docx_labels_and_tm_isolation()
    test_synthetic_stage_staleness_is_local()
    test_section_dependencies_only_follow_relevant_synthetic_cases()
    test_mixed_analysis_contracts_are_distinct()
    test_provenance_red_team()
    test_canonical_source_identity_is_required()
    test_quality_replacement_never_crosses_case_pools()
    test_synthetic_human_evidence_is_judgment_not_history()
    test_synthetic_only_requires_an_eligible_case()
    test_provider_failure_is_not_reported_as_zero_difficulty()
    print("\n全部通过 ✅")
