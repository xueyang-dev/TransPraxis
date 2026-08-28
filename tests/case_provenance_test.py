"""Canonical case provenance and deterministic presentation contracts."""
from transpraxis import case_presentation, case_provenance, thesis_constraints


def test_legacy_case_types_normalize_to_orthogonal_public_dimensions():
    authentic = case_provenance.with_provenance({
        "case_type": "authentic_revision",
        "provenance": {"historical": True, "generated_for_analysis": False},
    })
    synthetic = case_provenance.with_provenance({
        "case_type": "synthetic_contrast",
        "provenance": {"historical": False, "generated_for_analysis": True},
    })

    assert authentic["case_origin"] == case_provenance.REAL_REVISION
    assert authentic["text_role"]["initial"] == case_provenance.HISTORICAL_INITIAL
    assert authentic["review_status"] == "unreviewed"
    assert synthetic["case_origin"] == case_provenance.SYNTHETIC_BASELINE
    assert synthetic["text_role"]["initial"] == case_provenance.SYNTHETIC_BASELINE
    assert synthetic["text_role"]["target"] == case_provenance.CURRENT_TRANSLATION


def test_approval_changes_review_status_without_promoting_synthetic_provenance():
    case = case_provenance.with_provenance({
        "case_type": "synthetic_contrast",
        "synthetic_baseline": {"text": "模拟初译"},
    })
    approved = case_provenance.review_case(case, "approved", "四门 gate 通过")

    assert case["review_status"] == "unreviewed"
    assert approved["review_status"] == "approved"
    assert approved["case_origin"] == case_provenance.SYNTHETIC_BASELINE
    assert approved["text_role"]["initial"] == case_provenance.SYNTHETIC_BASELINE
    assert case_provenance.provenance_issues(approved) == []

    tampered = {**approved, "text_role": {
        **approved["text_role"], "initial": case_provenance.HISTORICAL_INITIAL}}
    assert "text_role_mismatch" in case_provenance.provenance_issues(tampered)


def test_real_and_synthetic_rendering_use_distinct_deterministic_labels():
    base = {
        "example_number": 1, "case_id": "fixture", "source": "原文",
        "initial": "初始译文", "target": "当前译文", "analysis": "分析。",
    }
    authentic = case_presentation.render_case_presentation_markdown({
        **base, "case_type": "authentic_revision"})
    synthetic = case_presentation.render_case_presentation_markdown({
        **base, "case_type": "synthetic_contrast"})

    assert "**初译**：初始译文" in authentic
    assert "**改译**：当前译文" in authentic
    assert "**初译**：" not in synthetic
    assert "**模拟初译**：初始译文" in synthetic
    assert "**改译**：当前译文" in synthetic


def test_strict_compliance_profile_makes_synthetic_cases_supplement_only():
    generic = thesis_constraints.case_policy({"report_stage": "final_report"})
    strict = thesis_constraints.case_policy({
        "report_stage": "final_report", "strict_compliance_profile": True})
    synthetic = {"case_type": "synthetic_contrast"}

    assert generic["synthetic_count_policy"] == "counts_toward_minimum"
    assert case_provenance.counts_toward_minimum(synthetic, generic)
    assert strict["synthetic_count_policy"] == "supplement_only"
    assert not case_provenance.counts_toward_minimum(synthetic, strict)
