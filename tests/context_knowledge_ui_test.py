"""Context visibility and human knowledge-promotion regressions."""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core
from transpraxis import knowledge


def _candidate(source="continuity", target="连续性", segment=0):
    return {
        "source": source,
        "observed_target": target,
        "first_observed_segment": segment,
        "occurrences": [segment],
        "observed_segments": [segment],
        "status": "emergent_candidate",
        "origin": "translation_observation",
        "kind": "term",
        "confidence": 0.5,
    }


def test_context_artifacts_load_and_missing_artifacts_are_safe():
    tmp = Path(tempfile.mkdtemp(prefix="context-artifacts-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        job_id = "contextartifact0001"
        state = core.new_job_state("context.docx")
        state.update(
            semantic_units=[{
                "unit_id": "unit-0001", "label": "导论",
                "start_segment": 0, "end_segment": 1,
            }],
            section_digests=[{
                "unit_id": "unit-0001", "start_segment": 0,
                "end_segment": 1, "summary": "导论摘要",
            }],
            document_synopsis={"summary": "全文概要", "status": "model"},
        )
        core.save_job_state(job_id, state)
        artifacts = core.load_context_artifacts(job_id)
        assert artifacts["semantic_units"][0]["label"] == "导论"
        assert artifacts["section_digests"][0]["summary"] == "导论摘要"
        assert artifacts["document_synopsis"]["summary"] == "全文概要"

        missing = core.load_context_artifacts("missing-context-job")
        assert missing == {
            "semantic_units": [], "section_digests": [],
            "document_synopsis": {}, "warnings": [],
        }
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_knowledge_decisions_preserve_scope_conflicts_and_invalidation():
    tmp = Path(tempfile.mkdtemp(prefix="knowledge-decisions-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        promoted_id = "knowledgepromote0001"
        state = core.new_job_state("promote.docx")
        state.update(
            p1_done=True, p2_done=True, paras=["The continuity matters."],
            pairs=[{
                "source": "The continuity matters.", "target": "连续性很重要。",
                "reviewed": True, "from_tm": False,
            }],
            glossary=[], delivery_status="draft",
            knowledge_candidates=[_candidate()],
        )
        core.save_job_state(promoted_id, state)
        candidate_id = knowledge.candidate_id(state["knowledge_candidates"][0])
        promoted, ok, message = core.review_knowledge_candidate(
            promoted_id, candidate_id, "project_term")
        assert ok, message
        assert promoted["glossary_frozen"]["version"] == 1
        assert promoted["glossary"][0]["status"] == "locked"
        assert promoted["knowledge_candidates"][0]["decision"] == "project_term"
        assert promoted["knowledge_candidates"][0]["promotion_entry_id"]
        assert promoted["pairs"][0]["stale_due_to_glossary"] is True
        assert any(event["decision"] == "project_term"
                   for event in promoted["knowledge_events"])
        assert any(action["action"] == "knowledge_project_term"
                   for action in promoted["human_actions"])
        repeated, repeated_ok, _ = core.review_knowledge_candidate(
            promoted_id, candidate_id, "task_only")
        assert not repeated_ok and repeated["knowledge_candidates"][0]["decision"] == "project_term"

        conflict_id = "knowledgeconflict0001"
        conflict = core.new_job_state("conflict.docx")
        locked = {
            "source": "continuity", "target": "连续性", "preferred": "连续性",
            "behavior": "translate", "status": "locked", "scope": "document",
        }
        conflict.update(
            p1_done=True, glossary=[locked], knowledge_candidates=[_candidate(target="连贯性")])
        core.save_job_state(conflict_id, conflict)
        core.freeze_glossary(conflict_id, entries=conflict["glossary"])
        conflict = core.load_job_state(conflict_id)
        conflict_candidate_id = knowledge.candidate_id(conflict["knowledge_candidates"][0])
        unchanged, conflict_ok, conflict_message = core.review_knowledge_candidate(
            conflict_id, conflict_candidate_id, "project_term")
        assert not conflict_ok and "冲突" in conflict_message
        assert unchanged["glossary"][0]["preferred"] == "连续性"
        assert not unchanged["knowledge_candidates"][0].get("decision")

        task_id = "knowledgetask000001"
        task = core.new_job_state("task.docx")
        task.update(knowledge_candidates=[_candidate("task term", "任务术语")])
        core.save_job_state(task_id, task)
        task_candidate_id = knowledge.candidate_id(task["knowledge_candidates"][0])
        accepted, accepted_ok, accepted_message = core.review_knowledge_candidate(
            task_id, task_candidate_id, "task_only")
        assert accepted_ok, accepted_message
        assert accepted["glossary"] == []
        assert accepted["knowledge_candidates"][0]["status"] == "accepted_task"

        rejected_id = "knowledgereject0001"
        rejected = core.new_job_state("reject.docx")
        rejected.update(knowledge_candidates=[_candidate("reject term", "拒绝术语")])
        core.save_job_state(rejected_id, rejected)
        rejected_candidate_id = knowledge.candidate_id(rejected["knowledge_candidates"][0])
        rejected_state, rejected_ok, rejected_message = core.review_knowledge_candidate(
            rejected_id, rejected_candidate_id, "rejected")
        assert rejected_ok, rejected_message
        assert rejected_state["knowledge_candidates"][0]["status"] == "rejected"
        assert knowledge.provisional_hints(rejected_state["knowledge_candidates"]) == []
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_context_and_knowledge_surfaces_rerun_without_widget_identity_errors():
    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parent.parent
    tmp = Path(tempfile.mkdtemp(prefix="context-knowledge-ui-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        job_id = "contextknowledgeui01"
        state = core.new_job_state("context-ui.docx")
        state.update(
            p1_done=True, p2_done=True, report_enabled=False,
            stage="TRANSLATED", delivery_status="draft",
            paras=["The continuity matters.", "The next section continues."],
            pairs=[{
                "source": "The continuity matters.", "target": "连续性很重要。",
                "reviewed": True, "target_provenance": "reviewed",
                "accepted_target": "连续性很重要。",
            }, {
                "source": "The next section continues.", "target": "下一节继续。",
                "reviewed": False, "target_provenance": "generated",
            }],
            semantic_units=[{
                "unit_id": "unit-0001", "kind": "section", "label": "导论",
                "start_segment": 0, "end_segment": 1,
            }],
            section_digests=[{
                "unit_id": "unit-0001", "start_segment": 0,
                "end_segment": 1, "summary": "介绍上下文连续性。",
                "key_terms": ["连续性"],
                "translation_notes": ["保持术语一致"],
            }],
            document_synopsis={
                "summary": "全文讨论上下文连续性。", "document_arc": "从概念到应用。",
                "themes": ["连续性"], "status": "model",
            },
            context_packet_log=[{
                "batch": 0, "previous_target_segments": [0],
                "previous_target_levels": ["reviewed"],
            }],
            knowledge_candidates=[_candidate()],
        )
        core.save_job_state(job_id, state)

        at = AppTest.from_file(str(root / "app.py"), default_timeout=30)
        at.run()
        at.session_state["app_view"] = "workspace"
        at.session_state["workspace_mode"] = True
        at.session_state["active_job_id"] = job_id
        at.session_state["workspace_section"] = "translation"
        at.run()
        assert not at.exception, f"翻译工作台页面异常：{at.exception}"
        assert any("浏览、检查和编辑双语段落" in item.value for item in at.markdown)

        next(button for button in at.sidebar.button if button.label == "术语库与记忆").click()
        at.run()
        assert not at.exception, f"待确认词条页面异常：{at.exception}"
        assert any(item.value == "待确认词条" for item in at.subheader)
        assert any(button.label == "仅本任务采用" for button in at.button)
        next(button for button in at.button if button.label == "仅本任务采用").click()
        at.run()
        assert not at.exception, f"处理知识词条后异常：{at.exception}"
        at.run()
        assert not at.exception, f"重复运行待确认词条页面异常：{at.exception}"
        print("  ✓ context/knowledge UI：上下文可见、知识决策持久化、重复 rerun 无 key 冲突")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_knowledge_library_bounds_large_pending_lists_and_supports_search():
    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parent.parent
    tmp = Path(tempfile.mkdtemp(prefix="knowledge-library-ui-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        job_id = "knowledgeboundui01"
        state = core.new_job_state("large-knowledge.docx")
        state.update(knowledge_candidates=[
            _candidate(f"term {index}", f"术语 {index}", index)
            for index in range(25)
        ])
        core.save_job_state(job_id, state)

        at = AppTest.from_file(str(root / "app.py"), default_timeout=30)
        at.run()
        next(button for button in at.sidebar.button
             if button.label == "术语库与记忆").click()
        at.run()
        assert not at.exception, at.exception
        assert any(text.label == "搜索待确认词条" for text in at.text_input)
        assert any("显示 20 / 25 条待确认词条" in item.value
                   for item in at.caption)

        at.session_state["knowledge_library_search"] = "term 24"
        at.run()
        assert not at.exception, at.exception
        assert any("显示 1 / 1 条待确认词条" in item.value
                   for item in at.caption)
        assert any("术语 24" in item.value for item in at.markdown)
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)
