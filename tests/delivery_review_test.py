"""Delivery review queue render checks, including the two workspace surfaces."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core
from transpraxis import delivery


def test_delivery_review_ui():
    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parent.parent
    tmp = Path(tempfile.mkdtemp(prefix="delivery-review-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        job_id = "reviewqueue0000001"
        state = core.new_job_state("review-queue-ui.pdf")
        same_event = {
            "segment_index": 0, "type": "review", "severity": "actionable",
            "category": "semantic_accuracy",
            "summary": "译文可能扩大原文概念的语义范围",
            "source_span": "Name source", "target_span": "Name source",
            "explanation": "当前译文没有保留原文的概念边界，可能造成语义扩张。",
            "recommendation": "回到原文核对概念关系，并决定是否需要收窄表达。",
            "confidence": 0.87, "detector": "Semantic QA",
            "diagnostic_version": 1,
            "reason": "审校发现问题", "review_event_id": "event-1",
            "evidence_refs": ["E1"],
        }
        duplicate = dict(same_event, evidence_refs=["E2"])
        state.update(
            p1_done=True, p2_done=True, paras=["Name source", "Other source"],
                pairs=[
                    {"source": "Name source", "target": "Name source"},
                    {"source": "Other source", "target": "Other text"},
                ],
                findings=[
                    same_event, duplicate,
                    {"segment_index": 0, "type": "check", "severity": "blocking",
                     "category": "format_integrity",
                     "summary": "占位符未被保留",
                     "source_span": "%s", "target_span": None,
                     "explanation": "原文包含必须保留的占位符，但当前译文中没有找到它。",
                     "recommendation": "补回占位符后重新检查格式完整性。",
                     "detector": "Deterministic QA", "diagnostic_version": 1,
                     "reason": "占位符丢失"},
                    {"segment_index": 1, "type": "check", "severity": "informational",
                     "kind": "source_residue", "category": "source_language_residue",
                     "summary": "译文残留源语片段",
                     "source_span": "Other", "target_span": "Other",
                     "explanation": "当前译文仍保留了原文语言片段，可能尚未完成翻译。",
                     "recommendation": "确认该片段是否为有意保留的专名；如果不是，请翻译后复核。",
                     "detector": "Deterministic QA", "diagnostic_version": 1,
                     "reason": "疑似残留源语片段「Other」"},
                    {"segment_index": 1, "type": "check", "severity": "informational",
                     "reason": "旧版基础问题"},
                ],
            has_blocking=True, delivery_status="review_required",
                review_stats={"reviewed_segments": 1, "blocking": 1,
                              "actionable": 1, "informational": 2},
        )
        same_semantics_different_evidence = [
            {"segment_index": 2, "type": "check", "severity": "actionable",
             "reason": "同一语义问题", "evidence_refs": ["E3"]},
            {"segment_index": 2, "type": "check", "severity": "actionable",
             "reason": "同一语义问题", "evidence_refs": ["E4"]},
        ]
        assert delivery.finding_fingerprint(same_semantics_different_evidence[0]) == \
            delivery.finding_fingerprint(same_semantics_different_evidence[1])
        independent_ids = {delivery.finding_id(f) for f in same_semantics_different_evidence}
        assert len(independent_ids) == 2, "不同证据实例不能共用 Streamlit widget ID"
        review_state = {"p2_done": True, "delivery_status": "review_required",
                        "findings": [dict(same_event),
                                     {"segment_index": 0, "type": "check",
                                      "severity": "blocking", "reason": "必须处理"}]}
        review_state, _ = delivery.mark_findings(
            review_state, [delivery.finding_id(same_event)], "human_fixed")
        assert delivery.compute_delivery_status(review_state) == "review_required"
        review_state, _ = delivery.mark_findings(
            review_state, [delivery.finding_id(review_state["findings"][1])], "human_fixed")
        assert delivery.compute_delivery_status(review_state) == "draft"
        core.save_job_state(job_id, state)

        at = AppTest.from_file(str(root / "app.py"), default_timeout=30)
        at.run()
        at.session_state["app_view"] = "workspace"
        at.session_state["workspace_mode"] = True
        at.session_state["active_job_id"] = job_id
        at.session_state["workspace_section"] = "review"
        at.run()
        assert not at.exception, f"交付队列渲染异常：{at.exception}"
        assert any("人工工作区" in x.value and "审校" in x.value for x in at.markdown)
        assert any(button.label == "返回任务列表" for button in at.button)
        assert any(button.label == "回到主页" for button in at.button)
        filter_control = next(x for x in at.segmented_control
                              if x.label == "筛选审校发现")
        assert "必须处理 1" in filter_control.options
        filter_control.set_value("全部 4")
        at.run()
        assert not at.exception, f"审校筛选重渲染异常：{at.exception}"
        queue = next(x for x in at.radio if x.label == "审校队列")
        assert len(queue.options) == 4
        assert any("译文可能扩大原文概念的语义范围" in option for option in queue.options)
        expected_finding_id = delivery.finding_id(same_event)
        semantic_label = next(option for option in queue.options
                              if "译文可能扩大原文概念的语义范围" in option)
        queue.set_value(semantic_label)
        at.run()
        assert at.session_state["selected_finding_id"] == expected_finding_id
        assert any("当前译文" in x.value for x in at.markdown)
        assert any("译文可能扩大原文概念的语义范围" in x.value for x in at.markdown)
        assert any("当前译文没有保留原文的概念边界" in x.value for x in at.markdown)
        assert any("回到原文核对概念关系" in x.value for x in at.markdown)
        assert any("0.87" in x.value for x in at.markdown)
        assert any('tp-review-span">Name source</mark>' in x.value for x in at.markdown)
        assert any("E1" in x.value and "E2" in x.value for x in at.markdown)
        assert "selected_finding_id" in at.session_state.filtered_state

        filter_control = next(x for x in at.segmented_control
                              if x.label == "筛选审校发现")
        filter_control.set_value("建议 1")
        at.run()
        assert not at.exception, f"建议筛选重渲染异常：{at.exception}"
        filtered_queue = next(x for x in at.radio if x.label == "审校队列")
        assert len(filtered_queue.options) == 1
        assert at.session_state["selected_finding_id"] == expected_finding_id

        filter_control = next(x for x in at.segmented_control
                              if x.label == "筛选审校发现")
        filter_control.set_value("全部 4")
        at.run()
        queue = next(x for x in at.radio if x.label == "审校队列")
        third_finding_id = delivery.finding_id(
            {"segment_index": 1, "type": "check", "severity": "informational",
             "kind": "source_residue", "category": "source_language_residue",
             "summary": "译文残留源语片段", "source_span": "Other",
             "target_span": "Other", "explanation": "当前译文仍保留了原文语言片段，可能尚未完成翻译。",
             "recommendation": "确认该片段是否为有意保留的专名；如果不是，请翻译后复核。",
             "detector": "Deterministic QA", "diagnostic_version": 1,
             "reason": "疑似残留源语片段「Other」"})
        residue_label = next(option for option in queue.options
                             if "译文残留源语片段" in option)
        queue.set_value(residue_label)
        at.run()
        assert at.session_state["selected_finding_id"] == third_finding_id
        location_blocks = [x.value for x in at.markdown
                           if '<div class="tp-review-long-text">' in x.value]
        assert any("Other" in value for value in location_blocks)
        assert any("text" in value for value in location_blocks)
        assert any("tp-review-span" in value for value in location_blocks)

        queue = next(x for x in at.radio if x.label == "审校队列")
        legacy_label = next(option for option in queue.options if "旧版基础问题" in option)
        queue.set_value(legacy_label)
        at.run()
        assert any("旧版本" in x.value for x in at.markdown)
        location_blocks = [x.value for x in at.markdown
                           if '<div class="tp-review-long-text">' in x.value]
        assert not any("tp-review-span" in value for value in location_blocks)

        at.session_state["workspace_section"] = "report"
        at.run()
        assert not at.exception, f"切换实践报告后异常：{at.exception}"
        assert any("<h2>报告</h2>" in x.value for x in at.markdown)

        at.session_state["workspace_section"] = "delivery"
        at.run()
        assert not at.exception, f"切换最终交付后异常：{at.exception}"
        assert any("最终交付" in x.value for x in at.markdown)

        next(button for button in at.button if button.label == "返回任务列表").click()
        at.run()
        assert not at.exception, f"返回任务列表异常：{at.exception}"
        assert at.session_state["app_view"] == "history"

        at.session_state["app_view"] = "workspace"
        at.session_state["workspace_mode"] = True
        at.session_state["workspace_section"] = "review"
        at.run()
        next(button for button in at.button if button.label == "回到主页").click()
        at.run()
        assert not at.exception, f"返回主页异常：{at.exception}"
        assert at.session_state["app_view"] == "new"
        assert at.session_state["workspace_mode"] is False
        print("  ✓ Streamlit review queue：重复 finding、工作区切换与重复 rerun 均无 key 冲突")
    finally:
        core.OUTPUT_DIR = old_dir


if __name__ == "__main__":
    test_delivery_review_ui()
