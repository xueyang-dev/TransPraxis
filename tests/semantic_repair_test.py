"""Regression checks for evidence-bound semantic repair gates."""

from __future__ import annotations

from transpraxis import (
    academic_evidence, academic_validator, academic_writer, claim_strength,
)


def test_claim_strength_allows_bounded_negation_but_flags_positive_effect():
    bounded = "本文不能证明该处理具有普遍规律，也不声称会提升读者理解。"
    assert claim_strength.claim_strength_violations(
        bounded, evidence_level="B") == []

    positive = "该处理确保读者理解并显著提升了译文质量。"
    findings = claim_strength.claim_strength_violations(
        positive, evidence_level="B")
    assert "proof_or_certainty" in {item["claim_kind"] for item in findings}
    reader_findings = claim_strength.claim_strength_violations(
        "该处理提升读者理解。", evidence_level="B")
    assert "reader_effect" in {item["claim_kind"] for item in reader_findings}


def test_claim_strength_allows_explicit_avoidance_of_generalization():
    assert claim_strength.claim_strength_violations(
        "本节避免把一个语段的作用推广为普遍效果。", evidence_level="B") == []


def test_translation_decision_disclaimer_is_not_historical_revision():
    assert not academic_validator._asserted_revision_language(
        "没有可验证的历史初译，本文只比较原文与当前译文。")
    assert academic_validator._asserted_revision_language(
        "经审校后改为当前译文。")


def test_focus_alignment_distinguishes_local_match_from_displacement():
    aligned = {
        "canonical_evidence": {"source": "Term appears here.",
                               "target": "术语出现在这里。"},
        "focus": {
            "issue": "Term → 术语",
            "source_span": {"start": 0, "end": 17, "text": "Term appears here."},
            "target_span": {"start": 0, "end": 8, "text": "术语出现在这里。"},
        },
    }
    result = academic_evidence.semantic_focus_alignment(
        aligned, {"source": aligned["canonical_evidence"]["source"],
                  "final_target": aligned["canonical_evidence"]["target"]})
    assert result["status"] == "aligned"

    displaced = {
        "canonical_evidence": {"source": "A. B. C.",
                               "target": "甲。乙。丙。"},
        "focus": {
            "issue": "",
            "source_span": {"start": 0, "end": 1, "text": "A"},
            "target_span": {"start": 6, "end": 7, "text": "丙"},
        },
    }
    result = academic_evidence.semantic_focus_alignment(
        displaced, {"source": "A. B. C.", "final_target": "甲。乙。丙。"})
    assert result["status"] == "misaligned"


def test_core_case_role_cannot_hide_misaligned_focus():
    selected = {
        "report_case_policy": {"report_stage": "proposal"},
        "cases": [{
            "case_id": "TD-0001",
            "case_type": "translation_decision",
            "segment_id": "seg-0001",
            "canonical_evidence": {"source": "A.", "target": "甲。"},
            "focus": {
                "source_span": {"start": 0, "end": 2, "text": "A."},
                "target_span": {"start": 0, "end": 2, "text": "甲。"},
            },
            "argument_role": "core",
            "semantic_alignment": {"status": "misaligned", "reason": "fixture"},
        }],
    }
    result = academic_validator.validate_case_portfolio(
        selected, report_stage="proposal")
    assert "misaligned_core_case" in {item["type"] for item in result["issues"]}
    assert result["status"] == "fail"


def test_argument_plan_rebinds_major_claim_to_final_core_portfolio():
    plan = {
        "claims": [{
            "claim_id": "C1", "research_question": "RQ1",
            "project_evidence": ["seg-old"],
            "core_case_ids": ["TD-OLD"],
        }],
    }
    selected = {"cases": [
        {"case_id": "TD-SYNTAX-1", "segment_id": "seg-1",
         "argument_role": "core", "research_questions": ["RQ1"],
         "semantic_alignment": {"status": "aligned"},
         "analytical_value_score": 12},
        {"case_id": "TD-SYNTAX-2", "segment_id": "seg-2",
         "argument_role": "core", "research_questions": ["RQ1"],
         "semantic_alignment": {"status": "aligned"},
         "analytical_value_score": 11},
        {"case_id": "TD-SYNTAX-SUPPORT", "segment_id": "seg-3",
         "argument_role": "supporting", "research_questions": ["RQ1"],
         "semantic_alignment": {"status": "aligned"},
         "analytical_value_score": 99},
    ]}
    repaired, changed = academic_writer._reconcile_argument_plan_with_portfolio(
        plan, selected)
    assert changed
    assert repaired["claims"][0]["core_case_ids"] == [
        "TD-SYNTAX-1", "TD-SYNTAX-2"]
    assert repaired["claims"][0]["project_evidence"] == ["seg-1", "seg-2"]


def test_user_facing_language_hides_planner_labels():
    visible = academic_writer._normalize_user_facing_language(
        "core 与 supporting 案例；core cases；source/target；最小充分 focus；完整 segment")
    assert visible == "主要例证与补充例证；主要例证；原文与译文；最小充分语境片段；完整文本片段"
    assert not any(term in visible for term in (
        "core", "supporting", "source/target", "focus", "segment"))
