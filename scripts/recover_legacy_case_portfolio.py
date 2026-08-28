#!/usr/bin/env python3
"""Recover a legacy analytical case portfolio without running Chapter 3."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core
from transpraxis import academic_evidence, academic_writer, legacy_cases, thesis_constraints


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--legacy-docx", required=True, type=Path)
    parser.add_argument("--manual-review", type=Path)
    parser.add_argument("--target", type=int, default=24)
    args = parser.parse_args()
    job_dir = args.job_dir.resolve()
    state_path = job_dir / "state.json"
    state = _json(state_path)
    evidence = _json(job_dir / "academic-evidence.json")
    research_model = _json(job_dir / "research-model.json")
    argument_plan = _json(job_dir / "argument-plan.json")
    before = academic_evidence.stable_hash(state.get("pairs") or [])

    config = core.load_provider_config() or {}
    if not config.get("provider"):
        raise RuntimeError("No configured LLM provider for the four-gate review")
    core.set_llm_base_url(config.get("base_url") or None)

    inventory = legacy_cases.parse_legacy_case_inventory(args.legacy_docx)
    qa_case_ids = {"TD-0126", "TD-0047", "TD-0003"}
    qa_source_ids = {str(item.get("source_segment_id") or "")
                     for item in evidence.get("translation_decision_candidates") or []
                     if str(item.get("case_id") or "") in qa_case_ids}
    recovery_path = job_dir / "legacy-case-recovery.json"
    cached_recovery = _json(recovery_path) if recovery_path.exists() else None
    recovery = legacy_cases.recover_legacy_cases(
        inventory, evidence, core.call_llm,
        config["provider"], config.get("api_key", ""), config.get("model", ""),
        qa_source_segment_ids=qa_source_ids, cached_recovery=cached_recovery)
    manual_review_path = args.manual_review or (job_dir / "legacy-case-manual-review.json")
    if manual_review_path.is_file():
        recovery = legacy_cases.apply_manual_reviews(
            recovery, _json(manual_review_path))
    generated = academic_writer._read_jsonl(
        job_dir / "synthetic-case-validation.jsonl") or {"items": []}
    combined = legacy_cases.merge_synthetic_artifacts(recovery, generated)
    report_policy = {
        **thesis_constraints.case_policy({"report_stage": "final_report"}),
        **dict((research_model.get("report_constraints") or {}).get("case_policy") or {}),
    }
    selected = academic_writer.select_academic_cases(
        research_model, argument_plan, evidence, limit=max(20, args.target),
        synthetic_artifact=combined, policy="mixed",
        report_case_policy=report_policy)

    settings = dict(state.get("research_settings") or {})
    settings.update({
        "legacy_case_document": str(args.legacy_docx.expanduser().resolve()),
        "pause_new_synthetic_generation": True,
        "legacy_case_manual_review": str(manual_review_path.resolve())
        if manual_review_path.is_file() else "",
    })
    state["research_settings"] = settings
    academic_writer._write_json(state_path, state)
    after = academic_evidence.stable_hash(_json(state_path).get("pairs") or [])
    if before != after:
        raise RuntimeError("translation pair hash changed during legacy recovery")
    recovery["translation_pair_hash_before"] = before
    recovery["translation_pair_hash_after"] = after
    selected["legacy_recovery_metrics"] = recovery.get("metrics") or {}
    selected["translation_pair_hash_before"] = before
    selected["translation_pair_hash_after"] = after
    selected["content_hash"] = academic_evidence.stable_hash(
        {key: value for key, value in selected.items() if key != "content_hash"})

    academic_writer._write_json(job_dir / "legacy-case-inventory.json", inventory)
    academic_writer._write_json(job_dir / "legacy-case-recovery.json", recovery)
    (job_dir / "legacy-case-recovery-report.md").write_text(
        legacy_cases.recovery_report_markdown(recovery), encoding="utf-8")
    academic_writer._write_json(job_dir / "selected-cases.json", selected)
    (job_dir / "final-contrast-case-portfolio.md").write_text(
        academic_writer.final_contrast_portfolio_markdown(selected), encoding="utf-8")

    print(json.dumps({
        "inventory": inventory["summary"],
        "recovery": recovery["metrics"],
        "final_case_count": selected.get("final_case_count"),
        "authentic": selected.get("authentic_revision_cases"),
        "legacy_synthetic": selected.get("legacy_synthetic_contrast_cases"),
        "newly_generated_synthetic": selected.get(
            "newly_generated_synthetic_contrast_cases"),
        "translation_decision_visible": selected.get(
            "translation_decision_visible_count"),
        "difficulty_distribution": selected.get("difficulty_distribution"),
        "rq_distribution": selected.get("research_question_distribution"),
        "pair_hash": after,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
