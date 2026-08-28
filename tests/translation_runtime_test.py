"""Regression tests for the long-document translation runtime additions."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core
from transpraxis import checkpoint, context, delivery, knowledge, models, repair
from transpraxis.translation_evidence import TranslationEvidenceIndex, review_translation_batch_with_evidence


def test_context_understanding_and_target_priority(tmp_path):
    paragraphs = ["The first ecological succession appears here.",
                  "The second section continues the ecological succession."]
    profile = {"sections": [{"section_id": "s1", "start_segment": 0,
                              "end_segment": 1, "topic": "生态过程"}]}

    def llm(provider, key, model, system, user, temperature=0.1):
        if "全书理解器" in system:
            return json.dumps({"summary": "全文概要", "document_arc": "发展", "themes": ["生态"]})
        return json.dumps({"summary": "单元概要", "translation_notes": ["保持术语连续"]})

    units, digests, synopsis, warnings = context.build_document_understanding(
        paragraphs, profile, "DeepSeek", "k", "m", "简体中文", call_llm=llm,
        max_workers=1)
    assert len(units) == 1 and len(digests) == 1
    assert synopsis["summary"] == "全文概要" and not warnings
    context.write_understanding_artifacts(tmp_path, units, digests, synopsis)
    assert (tmp_path / "section_digests.json").is_file()
    assert (tmp_path / "document_synopsis.json").is_file()

    pairs = [
        {"source": "a", "target": "甲", "reviewed": False},
        {"source": "b", "target": "乙", "reviewed": True},
        {"source": "c", "target": "丙", "human_accepted": True, "reviewed": True},
    ]
    selected = context.select_target_context(pairs, 3, limit=2)
    assert [item["level"] for item in selected] == ["reviewed", "human_accepted"]
    packet = context.compile_context_packet(profile, synopsis, digests[0], "glossary",
                                            ["before"], selected, ["after"], ["now"])
    assert "【全文概要】" in context.render_context_packet(packet)
    assert context.context_metadata(packet)["previous_target_levels"] == [
        "reviewed", "human_accepted"]


def test_knowledge_candidate_first_occurrence_and_locked_conflict():
    paragraphs = ["The river bank is old.", "The river bank is wide."]
    existing = [models.normalize_glossary_entry({
        "source": "river bank", "target": "河岸", "status": "locked"})]

    def llm(*args, **kwargs):
        return json.dumps([{"source_expression": "river bank",
                            "observed_target": "河流银行", "kind": "term"}])

    candidates, events, warning = knowledge.observe_batch(
        [paragraphs[1]], ["河流银行很宽。"], paragraphs,
        [{"source": paragraphs[0], "target": "河岸很老。"}], existing, 1,
        "DeepSeek", "k", "m", call_llm=llm)
    assert candidates == []
    assert warning is None
    assert events[0]["type"] == "target_conflict"
    assert events[0]["preferred_target"] == "河岸"

    candidates, events, warning = knowledge.observe_batch(
        ["Ecological succession continues."], ["生态演替很快。"],
        ["Ecological succession starts.", "Ecological succession continues."],
        [{"source": "Ecological succession starts.", "target": "生态演替开始。"}],
        [], 1, "DeepSeek", "k", "m",
        call_llm=lambda *args, **kwargs: json.dumps([{
            "segment_id": 1, "source_expression": "ecological succession",
            "observed_target": "生态演替"}]))
    assert candidates[0]["first_observed_segment"] == 1
    assert candidates[0]["occurrences"] == [0, 1]
    assert knowledge.provisional_hints(candidates)[0]["status"] == "provisional"
    assert knowledge.discard_candidates_for_segments(
        [{"source": "river bank", "observed_segments": [1]}], [1]) == []


def test_evidence_requests_are_bounded_and_traced():
    index = TranslationEvidenceIndex(
        ["The field matters.", "The field repeats."],
        [{"source": "The field matters.", "target": "田野很重要。"},
         {"source": "The field repeats.", "target": "田野重复。"}],
        [], document_synopsis={"summary": "全文"})
    replies = iter([
        json.dumps({"findings": [], "evidence_requests": [{
            "tool": "find_occurrences",
            "arguments": {"source_expression": "field", "selectors": ["first", "last"]},
        }]}),
        "[]",
    ])
    findings, failed, trace = review_translation_batch_with_evidence(
        ["The field matters."], ["田野很重要。"], "", "", "中文",
        "DeepSeek", "k", "m", index,
        call_llm=lambda *args, **kwargs: next(replies))
    assert findings == [] and not failed
    assert len(index.requests) == 1
    assert trace["requests"][0]["result"][0]["segment_id"] == 0


def test_review_findings_keep_actionable_diagnostics_and_exact_spans():
    index = TranslationEvidenceIndex(
        ["The source span matters."],
        [{"source": "The source span matters.", "target": "这个片段很重要。"}],
        [])
    reply = json.dumps({"findings": [{
        "segment_id": 0,
        "category": "semantic_accuracy",
        "severity": "blocking",
        "summary": "译文遗漏限制条件",
        "source_span": "source span",
        "target_span": "这个片段",
        "explanation": "原文中的限定关系没有在译文中保留。",
        "recommendation": "检查限定范围并补回必要表达。",
        "confidence": 0.91,
        "detector": "Semantic QA",
        "evidence_refs": [],
    }]})
    findings, failed, _ = review_translation_batch_with_evidence(
        ["The source span matters."], ["这个片段很重要。"], "", "", "中文",
        "DeepSeek", "k", "m", index, call_llm=lambda *args, **kwargs: reply)
    assert not failed and len(findings) == 1
    finding = findings[0]
    assert finding["diagnostic_version"] == 1
    assert finding["category"] == "semantic_accuracy"
    assert finding["source_span"] == "source span"
    assert finding["target_span"] == "这个片段"
    assert finding["confidence"] == 0.91


def test_deterministic_findings_explain_rule_failures_without_fake_confidence():
    findings = core.check_translation_batch(
        ["The source contains a placeholder %s."], [""], [], "中文")
    assert findings[0]["category"] == "completeness"
    assert findings[0]["summary"] == "译文为空"
    assert findings[0]["explanation"]
    assert findings[0]["recommendation"]
    assert findings[0]["confidence"] is None


def test_incomplete_new_diagnostic_payload_is_not_accepted_as_complete():
    index = TranslationEvidenceIndex(["source"], [{"target": "target"}], [])
    findings, failed, trace = review_translation_batch_with_evidence(
        ["source"], ["target"], "", "", "中文", "DeepSeek", "k", "m", index,
        call_llm=lambda *args, **kwargs: json.dumps({"findings": [{
            "segment_id": 0, "category": "semantic_accuracy",
            "severity": "blocking", "summary": "摘要",
        }] }))
    assert findings == [] and failed
    assert trace["completion_receipt"]["status"] == "failed"


def test_shadow_overlay_and_checkpoint_recovery(tmp_path):
    overlay = repair.create_overlay(
        ["初译"], ["修复"], [{"segment_index": 0}], "deterministic",
        sources=["source"], finding_segment_ids=[36])
    assert overlay["input_hash"] and overlay["candidate_hash"]
    assert overlay["finding_segment_ids"] == [36]
    assert overlay["input_findings"] == [{"segment_id": 36}]
    assert "finding_indexes" not in overlay
    assert overlay["candidate_hash"] != repair.create_overlay(
        ["初译"], ["另一修复"], [], "deterministic")["candidate_hash"]
    accepted = repair.evaluate_overlay(
        overlay, [], [], review_identity={
            "input_hash": overlay["input_hash"],
            "candidate_hash": overlay["candidate_hash"],
        })
    assert accepted["status"] == "accepted"
    assert repair.promoted_targets(accepted) == ["修复"]

    mismatched_identity = repair.create_overlay(
        ["初译"], ["修复"], [], "deterministic", sources=["source"])
    rejected_identity = repair.evaluate_overlay(
        mismatched_identity, [], [], review_identity={
            "input_hash": "different-input",
            "candidate_hash": mismatched_identity["candidate_hash"],
        })
    assert rejected_identity["status"] == "rejected"
    assert rejected_identity["rejection"] == "blind_review_identity_mismatch"

    mutated_input = repair.create_overlay(
        ["初译"], ["修复"], [], "deterministic", sources=["source"])
    mutated_input["input_sources"] = ["different source"]
    rejected_input = repair.evaluate_overlay(mutated_input, [], [])
    assert rejected_input["status"] == "rejected"
    assert rejected_input["rejection"] == "input_hash_mismatch"

    mutated_candidate = repair.create_overlay(
        ["初译"], ["修复"], [], "deterministic", sources=["source"])
    mutated_candidate["shadow_targets"] = ["被篡改"]
    rejected_candidate = repair.evaluate_overlay(mutated_candidate, [], [])
    assert rejected_candidate["status"] == "rejected"
    assert rejected_candidate["rejection"] == "candidate_hash_mismatch"

    rejected = repair.evaluate_overlay(
        repair.create_overlay(["初译"], ["坏修复"], [], "deterministic"),
        [{"severity": "blocking", "reason": "结构损坏"}], [])
    assert rejected["status"] == "rejected"
    assert repair.promoted_targets(rejected) == ["初译"]

    state = {"pairs": [{"source": "s", "target": "t", "reviewed": True}]}
    tm = {}
    checkpoint.append_event(tmp_path, {
        "batch": 0, "phase": "tm_promotion_pending",
        "entries": [{"source": "s", "target": "t"}],
    })
    changed, pending = checkpoint.reconcile_translation_memory(tm, state, tmp_path)
    assert changed and pending == 1 and tm["s"]["target"] == "t"
    checkpoint.append_event(tmp_path, {
        "batch": 1, "phase": "tm_promotion_pending",
        "entries": [{"source": "u", "target": "v"}],
    })
    changed, pending = checkpoint.reconcile_translation_memory(tm, state, tmp_path)
    assert changed and pending == 1 and tm["u"]["target"] == "v"
    changed, pending = checkpoint.reconcile_translation_memory(tm, state, tmp_path)
    assert not changed and pending == 0
    assert checkpoint.batch_entries([{
        "source": "◇◇◇", "target": "◇◇◇", "reviewed": True,
    }]) == []


def test_review_failed_must_not_mark_segment_reviewed_or_promote_tm_or_knowledge(tmp_path):
    old_output, old_call = core.OUTPUT_DIR, core.call_llm
    try:
        core.OUTPUT_DIR = tmp_path

        def llm(provider, key, model, system, user, temperature=0.1):
            if "独立的翻译审校专家" in system:
                raise RuntimeError("review provider timeout")
            if "学术翻译专家" in system:
                return json.dumps(["这是译文。"])
            return "[]"

        core.call_llm = llm
        core.save_tm({
            "The cached sentence is safe.": {"target": "已有译文", "reviewed": True}
        })
        state = core.new_job_state("failed-review.docx")
        state["paras"] = [
            "The source sentence is safe.",
            "The cached sentence is safe.",
        ]
        result = core.translate_stage(
            state, "failed-review-job", [], "DeepSeek", "k", "m", "简体中文", "",
            enable_review=True, use_tm=True)
        pair = result["pairs"][0]
        assert pair["review_status"] == "review_failed"
        assert pair["reviewed"] is False
        assert result["pairs"][1]["from_tm"] is True
        assert result["review_stats"]["review_failed"] == 1
        assert result["knowledge_candidates"] == []
        assert core.load_tm() == {
            "The cached sentence is safe.": {"target": "已有译文", "reviewed": True}
        }
        events = checkpoint.read_events(tmp_path / "failed-review-job")
        assert not any(event.get("phase") in {
            "tm_promotion_pending", "tm_promotion_done"
        } for event in events)
    finally:
        core.OUTPUT_DIR, core.call_llm = old_output, old_call


def test_translate_stage_records_current_translation_truth(tmp_path):
    old_output, old_call = core.OUTPUT_DIR, core.call_llm
    try:
        core.OUTPUT_DIR = tmp_path

        def llm(provider, key, model, system, user, temperature=0.1):
            if "学术翻译专家" in system:
                return json.dumps(["流水线译文。"])
            return "[]"

        core.call_llm = llm
        job_id = "translationtruthpipeline"
        state = core.new_job_state("truth.docx")
        state["paras"] = ["The pipeline writes the current translation."]

        result = core.translate_stage(
            state, job_id, [], "DeepSeek", "k", "m", "简体中文", "",
            enable_review=False, use_tm=False)

        assert result["pairs"][0]["target"] == "流水线译文。"
        assert result["translation_truth"]["authority"] == "CURRENT_TRANSLATION"
        assert result["translation_truth"]["version"] == 1
        assert result["translation_truth"]["last_change"]["action"] == \
            "translation_batch"
        assert result["translation_truth"]["last_change"]["segment_indexes"] == [0]
        assert core.load_job_state(job_id)["translation_truth"]["version"] == 1
    finally:
        core.OUTPUT_DIR, core.call_llm = old_output, old_call


def test_evidence_segment_id_is_global_across_later_batches():
    paragraphs = [f"source {index}" for index in range(40)]
    pairs = [{"source": source, "target": f"target {index}"}
             for index, source in enumerate(paragraphs)]
    index = TranslationEvidenceIndex(paragraphs, pairs, [])
    replies = iter([
        json.dumps({"findings": [], "evidence_requests": [{
            "tool": "get_segment", "arguments": {"segment_id": 36},
        }]}),
        json.dumps({"findings": [{
            "segment_id": 36, "severity": "actionable", "reason": "问题",
            "evidence_refs": ["E1"],
        }]}),
    ])
    findings, failed, trace = review_translation_batch_with_evidence(
        [paragraphs[36]], ["candidate"], "", "", "中文", "p", "k", "m", index,
        call_llm=lambda *args, **kwargs: next(replies), segment_ids=[36])
    assert not failed and findings[0]["segment_id"] == 36
    assert trace["requests"][0]["result"]["segment_id"] == 36
    assert trace["completion_receipt"]["reviewed_segment_ids"] == [36]


def test_repair_findings_are_document_global():
    findings = core._globalize_batch_findings([{
        "segment_id": 0, "segment_index": 0, "severity": "actionable",
    }], 36)
    assert findings[0]["segment_id"] == 36
    assert findings[0]["segment_index"] == 36


def test_blind_review_cannot_read_formal_or_initial_target():
    index = TranslationEvidenceIndex(
        ["source"], [{"source": "source", "target": "formal",
                      "initial_target": "initial", "accepted_target": "accepted",
                      "target_provenance": "reviewed", "reviewed": True}], [],
        blind=True, candidate_targets={0: "candidate"})
    segment = index.request("get_segment", segment_id=0)
    history = index.request("get_translation_history", segment_id=0)
    assert segment == {"segment_id": 0, "source": "source", "target": "candidate"}
    assert history == segment
    assert "formal" not in json.dumps(segment, ensure_ascii=False)
    assert "initial" not in json.dumps(history, ensure_ascii=False)
    assert index.request("get_findings") == []


def test_delivery_approval_does_not_imply_segment_human_acceptance():
    state = {"p2_done": True, "pairs": [{"source": "s", "target": "t"}]}
    state, ok, errors = delivery.approve_delivery(state)
    assert ok and not errors
    assert state["delivery_approved_by_human"] is True
    assert state["pairs"][0].get("human_accepted") is None
    assert state["pairs"][0].get("target_provenance") is None


def test_multiple_observations_from_one_segment_keep_correct_provenance():
    payload = json.dumps([
        {"segment_id": 5, "source_expression": "alpha",
         "observed_target": "阿尔法", "kind": "term"},
        {"segment_id": 5, "source_expression": "beta",
         "observed_target": "贝塔", "kind": "term"},
    ])
    candidates, events, warning = knowledge.observe_batch(
        ["alpha beta"], ["阿尔法和贝塔"], ["alpha beta"],
        [{}, {}, {}, {}, {}], [], 5, "p", "k", "m",
        call_llm=lambda *args, **kwargs: payload, segment_ids=[5])
    assert warning is None and len(candidates) == 2
    assert {item["first_observed_segment"] for item in candidates} == {5}
    assert {item["segment_id"] for item in events} == {5}


def test_batch_must_not_cross_semantic_unit_boundary():
    batches = core.make_batches(
        ["a", "b", "c", "d"], batch_size=4, max_chars=100,
        semantic_units=[{"start_segment": 0, "end_segment": 1},
                        {"start_segment": 2, "end_segment": 3}])
    assert batches == [["a", "b"], ["c", "d"]]


def test_understanding_resume_reuses_completed_unit_digests(tmp_path):
    paragraphs = ["First unit.", "Second unit."]
    profile = {"sections": [
        {"section_id": "one", "start_segment": 0, "end_segment": 0},
        {"section_id": "two", "start_segment": 1, "end_segment": 1},
    ]}
    units = context.build_semantic_units(paragraphs, profile)
    saved_digest = {
        "unit_id": units[0]["unit_id"], "kind": units[0]["kind"],
        "label": units[0]["label"], "start_segment": 0, "end_segment": 0,
        "summary": "already saved", "key_entities": [], "key_terms": [],
        "open_threads": [], "translation_notes": [], "status": "model",
    }
    context.write_understanding_artifacts(
        tmp_path, units, [saved_digest], {"summary": "", "status": "pending"})
    calls = []

    def llm(provider, key, model, system, user, temperature=0.1):
        calls.append(system)
        if "全书理解器" in system:
            return json.dumps({"summary": "book"})
        return json.dumps({"summary": "new unit"})

    _, digests, synopsis, warnings = context.build_document_understanding(
        paragraphs, profile, "p", "k", "m", "中文", call_llm=llm,
        max_workers=1, checkpoint_dir=tmp_path)
    assert digests[0]["summary"] == "already saved"
    assert len(calls) == 2  # only the missing unit digest plus synopsis
    assert synopsis["summary"] == "book" and not warnings


def test_synopsis_uses_hierarchical_reduce_for_long_digest_list():
    digests = [{
        "unit_id": f"unit-{index}", "start_segment": index, "end_segment": index,
        "summary": "x" * 300, "key_entities": [], "key_terms": [],
        "translation_notes": [],
    } for index in range(8)]
    calls = []

    def llm(provider, key, model, system, user, temperature=0.1):
        calls.append(user)
        return json.dumps({"summary": "reduced", "document_arc": "arc"})

    synopsis, warnings = context.generate_document_synopsis(
        digests, "p", "k", "m", "中文", call_llm=llm, max_chunk_chars=700)
    assert synopsis["summary"] == "reduced" and not warnings
    assert len(calls) > 1

    bounded_calls = []

    def bounded_llm(provider, key, model, system, user, temperature=0.1):
        bounded_calls.append(user.split("语义摘要块：\n", 1)[1])
        return json.dumps({"summary": "reduced"})

    context.generate_document_synopsis(
        [{"unit_id": "large", "start_segment": 0, "end_segment": 0,
          "summary": "x" * 2500}], "p", "k", "m", "中文",
        call_llm=bounded_llm, max_chunk_chars=1000)
    assert len(bounded_calls[0]) <= 1000


def test_evidence_final_round_cannot_request_more_evidence():
    replies = iter([
        json.dumps({"findings": [], "evidence_requests": [{
            "tool": "get_segment", "arguments": {"segment_id": 0},
        }]}),
        json.dumps({"findings": [], "evidence_requests": [{
            "tool": "get_segment", "arguments": {"segment_id": 0},
        }]}),
    ])
    index = TranslationEvidenceIndex(["source"], [{"target": "target"}], [])
    findings, failed, trace = review_translation_batch_with_evidence(
        ["source"], ["target"], "", "", "中文", "p", "k", "m", index,
        call_llm=lambda *args, **kwargs: next(replies))
    assert findings == [] and failed
    assert trace["completion_receipt"]["status"] == "failed"


def test_malformed_review_payload_is_not_clean_acceptance():
    index = TranslationEvidenceIndex(["source"], [{"target": "target"}], [])
    findings, failed, trace = review_translation_batch_with_evidence(
        ["source"], ["target"], "", "", "中文", "p", "k", "m", index,
        call_llm=lambda *args, **kwargs: "{}")
    assert findings == [] and failed
    assert trace["completion_receipt"]["status"] == "failed"

    findings, failed, trace = review_translation_batch_with_evidence(
        ["source"], ["target"], "", "", "中文", "p", "k", "m", index,
        call_llm=lambda *args, **kwargs: json.dumps({
            "findings": [], "evidence_requests": {},
        }))
    assert findings == [] and failed
    assert trace["completion_receipt"]["status"] == "failed"

    replies = iter([
        json.dumps({"findings": [], "evidence_requests": [{
            "tool": "get_segment", "arguments": {"segment_id": 0},
        }]}),
        json.dumps({"findings": [{
            "segment_id": 99, "severity": "actionable", "reason": "wrong segment",
        }]}),
    ])
    findings, failed, trace = review_translation_batch_with_evidence(
        ["source"], ["target"], "", "", "中文", "p", "k", "m", index,
        call_llm=lambda *args, **kwargs: next(replies))
    assert findings == [] and failed
    assert trace["completion_receipt"]["status"] == "failed"


def test_malformed_section_ranges_are_skipped_not_crashed():
    units = context.build_semantic_units(
        ["a", "b"], {"sections": [
            {"start_segment": None, "end_segment": 1},
            {"start_segment": "unknown", "end_segment": 1},
            {"start_segment": 0, "end_segment": 1},
        ]})
    assert len(units) == 1 and units[0]["start_segment"] == 0
    assert core._batch_section_profile(
        {"sections": [{"start_segment": "unknown", "end_segment": 1},
                       {"start_segment": 0, "end_segment": 1}]}, 0, 2
    )["start_segment"] == 0
    assert context.digest_for_segment(
        [None, {"start_segment": "unknown", "end_segment": 1}], 0) is None
    index = TranslationEvidenceIndex(
        ["a"], [{"target": "b"}], [], section_digests=[None, {
            "start_segment": "unknown", "end_segment": 1,
        }])
    assert index.request("get_section_digest", segment_id=0) == {}
