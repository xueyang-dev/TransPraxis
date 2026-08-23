"""Translation workbench data and state-machine regressions."""
import json

import core


def _translation_state():
    state = core.new_job_state("translation-workbench.txt")
    state.update(
        p1_done=True,
        p2_done=True,
        paras=["Alpha source", "Beta source", "Gamma source"],
        pairs=[
            {
                "source": "Alpha source planetary",
                "target": "甲",
                "initial_target": "甲",
                "reviewed": True,
                "from_tm": False,
                "glossary_entry_ids": ["term-planetarity"],
            },
            {
                "source": "Beta source",
                "target": "乙",
                "initial_target": "乙",
                "reviewed": False,
                "from_tm": False,
                "glossary_entry_ids": [],
            },
            {
                "source": "Gamma source",
                "target": "丙",
                "initial_target": "丙",
                "reviewed": True,
                "from_tm": True,
                "glossary_entry_ids": [],
            },
        ],
        glossary=[{
            "id": "term-planetarity",
            "source": "planetarity",
            "preferred": "行星性",
            "status": "locked",
        }],
        # This must not become a segment term without pair provenance.
        auto_terms={"planetarity": "行星性", "scopic regime": "观看机制"},
        review_stats={"reviewed_segments": 2},
        delivery_status="draft",
    )
    return state


def test_translation_search_and_filters_are_read_only():
    state = _translation_state()
    before = json.dumps(state, ensure_ascii=False, sort_keys=True)

    assert core.translation_visible_indexes(state) == [0, 1, 2]
    assert core.translation_visible_indexes(state, search="beta") == [1]
    assert core.translation_visible_indexes(state, search="#3") == [2]
    assert core.translation_visible_indexes(state, status_filter="待审") == [1]
    assert core.translation_visible_indexes(state, status_filter="已审校") == [0, 2]
    assert core.translation_visible_indexes(state, filter_terms=True) == [0]
    assert core.translation_visible_indexes(state, filter_tm=True) == [2]
    assert core.translation_visible_indexes(state, filter_issues=True,
                                            issue_indexes={1}) == [1]

    assert json.dumps(state, ensure_ascii=False, sort_keys=True) == before


def test_segment_terms_use_provenance_and_empty_segments_stay_empty():
    state = _translation_state()
    assert core.translation_terms_for_pair(state, state["pairs"][0]) == [
        ("planetarity", "行星性", "项目术语")]
    assert core.translation_terms_for_pair(state, state["pairs"][1]) == []
    unresolved = dict(state["pairs"][1], source="Second scopic regime",
                      glossary_entry_ids=["missing-term-id"])
    assert core.translation_terms_for_pair(state, unresolved) == []


def test_manual_edit_invalidates_review_and_preserves_frozen_snapshot(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "translationedit0001"
        state = _translation_state()
        state["pairs"] = [state["pairs"][0]]
        state["paras"] = [state["paras"][0]]
        state["review_stats"]["reviewed_segments"] = 1
        core.save_source(job_id, b"translation source")
        core.save_job_state(job_id, state)
        _, ok, errors = core.approve_delivery(job_id, note="freeze before edit")
        assert ok, errors
        frozen_bytes = core.delivery_snapshot_assets(job_id, 1)["bilingual.jsonl"]

        edited = core.save_translation_edit(job_id, 0, "人工修改后的译文")
        assert edited["delivery_status"] == "draft"
        assert edited["pairs"][0]["target"] == "人工修改后的译文"
        assert edited["pairs"][0]["reviewed"] is False
        assert edited["pairs"][0]["human_edited"] is True
        assert edited["review_stats"]["reviewed_segments"] == 0
        assert core.delivery_snapshot_assets(job_id, 1)["bilingual.jsonl"] == frozen_bytes

        reloaded = core.load_job_state(job_id)
        assert reloaded["pairs"][0]["target"] == "人工修改后的译文"
        assert reloaded["delivery_status"] == "draft"

        restored = core.restore_translation_edit(job_id, 0)
        assert restored["pairs"][0]["target"] == "甲"
        assert restored["pairs"][0]["reviewed"] is True
        assert "human_edited" not in restored["pairs"][0]
        assert core.delivery_snapshot_assets(job_id, 1)["bilingual.jsonl"] == frozen_bytes
    finally:
        core.OUTPUT_DIR = old_output
