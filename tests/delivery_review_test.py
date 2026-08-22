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
            "reason": "审校发现问题", "review_event_id": "event-1",
            "evidence_refs": ["E1"],
        }
        duplicate = dict(same_event, evidence_refs=["E2"])
        state.update(
            p1_done=True, p2_done=True, paras=["Name source", "Other source"],
            pairs=[
                {"source": "Name source", "target": "Name source"},
                {"source": "Other source", "target": "其他文本"},
            ],
            findings=[
                same_event, duplicate,
                {"segment_index": 0, "type": "check", "severity": "blocking",
                 "reason": "占位符丢失"},
                {"segment_index": 1, "type": "check", "severity": "informational",
                 "kind": "source_residue",
                 "reason": "疑似残留源语片段「Mellon」"},
            ],
            has_blocking=True, delivery_status="review_required",
            review_stats={"reviewed_segments": 1, "blocking": 1,
                          "actionable": 2, "informational": 0},
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
        at.run()
        assert not at.exception, f"交付队列渲染异常：{at.exception}"
        assert any(x.value == "人工审查队列" for x in at.subheader)
        assert any(x.label == "必须处理" for x in at.metric)
        queue_filter = next(x for x in at.radio if x.label == "筛选发现")
        queue_filter.set_value("全部")
        at.run()
        assert sum(x.label == "选择此问题" for x in at.checkbox) >= 3, \
            "blocking/actionable 与可能的 informational 专名都应可选择"
        assert any(x.label == "当前工作区" for x in at.radio)

        surface = next(x for x in at.radio if x.label == "当前工作区")
        surface.set_value("实践报告")
        at.run()
        assert not at.exception, f"切换实践报告后异常：{at.exception}"
        assert not any(x.value == "人工审查队列" for x in at.subheader), \
            "实践报告工作区不应执行交付审查控件"

        surface = next(x for x in at.radio if x.label == "当前工作区")
        surface.set_value("资产与交付")
        at.run()
        assert not at.exception, f"切回资产与交付后异常：{at.exception}"
        assert any(x.value == "人工审查队列" for x in at.subheader)
        print("  ✓ Streamlit review queue：重复 finding、tab 切换与重复 rerun 均无 key 冲突")
    finally:
        core.OUTPUT_DIR = old_dir


if __name__ == "__main__":
    test_delivery_review_ui()
