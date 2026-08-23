"""Streamlit smoke coverage for the segment-first translation workspace."""
from pathlib import Path

import core
from transpraxis import assets


def _ui_state():
    state = core.new_job_state("sensorium-part3.pdf")
    pairs = []
    for index in range(8):
        source = f"Source segment {index + 1}"
        if index == 2:
            source += " planetary"
        pairs.append({
            "source": source,
            "target": f"译文 {index + 1}",
            "initial_target": f"译文 {index + 1}",
            "reviewed": index in {0, 1, 3, 5},
            "from_tm": index == 4,
            "glossary_entry_ids": ["term-1"] if index == 2 else [],
        })
    state.update(
        p1_done=True,
        p2_done=True,
        paras=[pair["source"] for pair in pairs],
        pairs=pairs,
        glossary=[{
            "id": "term-1", "source": "planetary", "preferred": "行星性",
            "status": "locked",
        }],
        review_stats={"reviewed_segments": 4},
        delivery_status="draft",
    )
    return state


def _table_key(at, job_id):
    return next(key for key in at.session_state.filtered_state
                if key.startswith(f"translation_table_{job_id}_"))


def _select_display_row(at, job_id, display_row):
    key = _table_key(at, job_id)
    at.session_state[key] = {
        "selection": {"rows": [display_row], "columns": [], "cells": []}}
    at.run()


def test_translation_workspace_master_detail_selection_and_editing(tmp_path):
    from streamlit.testing.v1 import AppTest

    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "translationui00001"
        core.save_job_state(job_id, _ui_state())
        app_path = Path(__file__).resolve().parent.parent / "app.py"
        at = AppTest.from_file(str(app_path), default_timeout=30)
        at.run()
        at.session_state["active_job_id"] = job_id
        at.session_state["app_view"] = "workspace"
        at.session_state["workspace_mode"] = True
        at.session_state["workspace_section"] = "translation"
        at.run()

        assert not at.exception, at.exception
        assert at.session_state["selected_segment_id"] == assets.segment_id(job_id, 0)
        assert any("浏览、检查和编辑双语段落" in item.value for item in at.markdown)
        assert any("当前段落 · #1" in item.value for item in at.markdown)

        _select_display_row(at, job_id, 2)
        assert at.session_state["selected_segment_id"] == assets.segment_id(job_id, 2)
        assert any("当前段落 · #3" in item.value for item in at.markdown)
        assert any("planetary" in item.value and "行星性" in item.value
                   for item in at.markdown)

        _select_display_row(at, job_id, 7)
        assert at.session_state["selected_segment_id"] == assets.segment_id(job_id, 7)
        assert any("当前段落 · #8" in item.value for item in at.markdown)
        assert any("译文 8" in item.value for item in at.text_area)

        _select_display_row(at, job_id, 1)
        assert at.session_state["selected_segment_id"] == assets.segment_id(job_id, 1)
        assert any("当前段落 · #2" in item.value for item in at.markdown)

        at.session_state[f"translation_search_{job_id}"] = "planetary"
        at.run()
        assert at.session_state["selected_segment_id"] == assets.segment_id(job_id, 2)
        _select_display_row(at, job_id, 0)
        assert at.session_state["selected_segment_id"] == assets.segment_id(job_id, 2)
        assert any("当前段落 · #3" in item.value for item in at.markdown)

        at.session_state[f"translation_search_{job_id}"] = ""
        at.run()
        assert at.session_state["selected_segment_id"] == assets.segment_id(job_id, 2)

        _select_display_row(at, job_id, 0)
        assert at.session_state["selected_segment_id"] == assets.segment_id(job_id, 0)
        at.session_state[f"translation_filter_{job_id}"] = "待审"
        at.run()
        assert at.session_state["selected_segment_id"] == assets.segment_id(job_id, 2)
        assert any("当前段落 · #3" in item.value for item in at.markdown)

        at.session_state[f"translation_filter_{job_id}"] = "全部"
        at.run()
        _select_display_row(at, job_id, 7)
        editor_key = f"translation_editor_{assets.segment_id(job_id, 7)}"
        at.session_state[editor_key] = "保存后的第八段译文"
        next(button for button in at.button if button.label == "保存修改").click()
        at.run()
        assert at.session_state["selected_segment_id"] == assets.segment_id(job_id, 7)
        updated = core.load_job_state(job_id)
        assert updated["pairs"][7]["target"] == "保存后的第八段译文"
        assert updated["pairs"][7]["human_edited"] is True
        assert updated["pairs"][2]["target"] == "译文 3"
        assert any("保存后的第八段译文" in str(frame.value) for frame in at.dataframe)
        assert any("保存后的第八段译文" in item.value for item in at.text_area)
    finally:
        core.OUTPUT_DIR = old_output
