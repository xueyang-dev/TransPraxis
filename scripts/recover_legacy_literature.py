#!/usr/bin/env python3
"""Recover legacy literature candidates for the frozen Chapter 3 portfolio."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transpraxis import legacy_literature


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--legacy-docx", required=True, type=Path)
    args = parser.parse_args()
    job = args.job_dir.expanduser().resolve()
    docx = args.legacy_docx.expanduser().resolve()
    selected = _read(job / "selected-cases.json")
    research_model = _read(job / "research-model.json")
    inventory = legacy_literature.parse_legacy_literature_inventory(docx)
    plan = legacy_literature.build_chapter3_writing_plan(inventory, selected, research_model)
    report = legacy_literature.literature_recovery_report(inventory, plan, selected)
    (job / "legacy-literature-inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (job / "chapter3-writing-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (job / "literature-recovery-report.md").write_text(report, encoding="utf-8")
    print(json.dumps({
        "inventory": inventory["summary"],
        "plan": plan["summary"],
        "frozen_portfolio": plan["frozen_portfolio"],
        "artifacts": [
            str(job / "legacy-literature-inventory.json"),
            str(job / "literature-recovery-report.md"),
            str(job / "chapter3-writing-plan.md"),
        ],
    }, ensure_ascii=False, indent=2))
    # The human-readable plan is deliberately written after the JSON so it
    # can be reviewed without requiring a JSON viewer.
    lines = [
        "# Chapter 3 Writing Plan",
        "",
        plan["method_statement"],
        "",
        "## Portfolio freeze",
        "",
        f"- cases: {plan['frozen_portfolio']['selected_case_count']}",
        f"- selected-cases content hash: `{plan['frozen_portfolio']['selected_content_hash']}`",
        f"- translation pair hash: `{plan['frozen_portfolio']['translation_pair_hash']}`",
        "- 本计划只读 frozen selected-cases；不重新排名、不生成 baseline、不改变 provenance。",
        "",
        "## RQ coverage",
        "",
    ]
    for rq_id, info in plan["research_questions"].items():
        lines.append(f"- **{rq_id}**（{info['count']} cases）：{info['question']}")
    lines.extend(["", "## Case-by-case writing map", "", "| 例 | type | difficulty | strategy | RQ | baseline origin | literature | focus |", "|---:|---|---|---|---|---|---|---|"])
    for case in plan["cases"]:
        label = "初译" if case["case_type"] == "authentic_revision" else "模拟初译"
        lit = ", ".join(x["legacy_reference_id"] for x in case["literature_support"]) or "文本内部分析"
        lines.append("| {example_number} | {label} / {case_type} | {difficulty} | {strategy} | {rq} | {origin} | {lit} | {focus} |".format(
            example_number=case["example_number"], label=label, case_type=case["case_type"],
            difficulty=case["difficulty"], strategy=case["strategy"],
            rq="、".join(case["research_questions"]), origin=case["baseline_origin"],
            lit=lit, focus=case["analysis_focus"]))
    lines.extend([
        "",
        "## Writer rules",
        "",
        "- authentic case visible labels: `初译：` / `改译：`。",
        "- synthetic case visible labels: `模拟初译：` / `改译：`；正文不写“笔者最初译为”“审校后修改为”。",
        "- 先分析 source / initial / final 的具体差异，再调用 verified literature 解释语言机制；文献不能替代文本证据。",
        "- legacy analysis 只作为 seed；Chapter 3 必须基于 current source、frozen baseline、current canonical final、当前 RQ 和 verified literature 重写。",
        "- 只把实际在正文使用的 verified literature 写入最终 References。",
    ])
    (job / "chapter3-writing-plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
