"""Report reader, review actions, and DOCX export regressions."""
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import core


def _report_state(filename="report-fixture.docx", *, generated=True, quality="pass"):
    state = core.new_job_state(filename)
    state.update(
        p1_done=True,
        p2_done=True,
        p3_done=generated,
        report_enabled=True,
        paras=["Source paragraph"],
        pairs=[{"source": "Source paragraph", "target": "源文段落"}],
        p3_md=(
            "# 翻译实践报告\n\n## 1 引言\n<!--rq:RQ1-->\n\n"
            "### 1 引言\n\n正文。\n\n## 3 案例分析\n\n案例。"
            if generated else ""
        ),
        academic_state={
            "status": quality,
            "quality_status": quality,
            "updated_at": "2026-08-23T12:00:00+00:00",
            "artifacts": {},
        },
        delivery_status="draft",
    )
    return state


def _write_artifact(job_id, filename, payload):
    path = core.job_dir(job_id) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _render_report(tmp_path, state, artifacts=None):
    from streamlit.testing.v1 import AppTest

    job_id = "reportui0000001"
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    core.save_job_state(job_id, state)
    for filename, payload in (artifacts or {}).items():
        _write_artifact(job_id, filename, payload)
    at = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"),
                           default_timeout=30)
    at.run()
    at.session_state["active_job_id"] = job_id
    at.session_state["app_view"] = "workspace"
    at.session_state["workspace_mode"] = True
    at.session_state["workspace_section"] = "report"
    at.run()
    return at, old_output


def _base_artifacts():
    return {
        "selected-cases.json": {
            "cases": [{"case_id": "seg-report-0001", "case_type": "authentic_revision"}],
            "authentic_selection_status": "sufficient_revision_cases",
            "minimum_core_case_count": 1,
        },
        "academic-outline.json": {
            "sections": [{"section_id": "1", "title": "引言"},
                          {"section_id": "3", "title": "案例分析"}],
        },
        "academic-validation.json": {"status": "pass", "issues": []},
    }


def test_report_without_generation_is_empty_and_has_no_export(tmp_path):
    at, old_output = _render_report(tmp_path, _report_state(generated=False), {})
    try:
        assert not at.exception, at.exception
        assert any("报告尚未生成" in item.value for item in at.markdown)
        assert not at.download_button
    finally:
        core.OUTPUT_DIR = old_output


def test_report_pass_has_outline_exports_and_stable_reruns(tmp_path):
    at, old_output = _render_report(tmp_path, _report_state(), _base_artifacts())
    try:
        assert not at.exception, at.exception
        assert any(button.label == "导出 DOCX" for button in at.download_button)
        assert any(button.label == "导出 Markdown" for button in at.download_button)
        assert not any(button.label == "导出当前草稿 DOCX" for button in at.download_button)
        assert any("报告目录" in item.value and "3 案例分析" in item.value
                   for item in at.markdown)
        body = next(item.value for item in at.markdown
                    if '<a id="report-heading-1">' in item.value)
        assert body.count("引言") == 1, body
        at.run()
        assert not at.exception, at.exception
    finally:
        core.OUTPUT_DIR = old_output


def test_report_review_is_draft_exportable_and_maps_user_facing_reasons(tmp_path):
    state = _report_state(quality="review_required")
    artifacts = _base_artifacts()
    artifacts["selected-cases.json"]["authentic_selection_status"] = "insufficient_revision_cases"
    artifacts["academic-validation.json"] = {
        "status": "fail",
        "issues": [{
            "issue_id": "AV-001",
            "type": "insufficient_core_revision_cases",
            "severity": "error",
            "reason": "只有 0 个合格修订案例，少于最低要求 1 个。",
        }],
    }
    at, old_output = _render_report(tmp_path, state, artifacts)
    try:
        assert not at.exception, at.exception
        assert any(button.label == "导出当前草稿 DOCX" for button in at.download_button)
        assert any(button.label == "查看复核问题" for button in at.button)
        next(button for button in at.button if button.label == "查看复核问题").click()
        at.run()
        assert not at.exception, at.exception
        assert any("案例不足" in item.value for item in at.markdown)
        assert not any("insufficient_core_revision_cases" in item.value
                       for item in at.markdown)
        next(button for button in at.button if button.label == "查看案例选择").click()
        at.run()
        assert not at.exception, at.exception
        assert any("选择状态：insufficient_revision_cases" in item.value
                   for item in at.caption)
        assert any(button.label == "重新选择案例并继续生成"
                   for button in at.button)
    finally:
        core.OUTPUT_DIR = old_output


def test_report_case_repair_invalidates_planning_and_resumes(tmp_path, monkeypatch):
    state = _report_state(quality="review_required")
    state["academic_state"]["artifacts"] = {
        "selected_cases": {"file": "selected-cases.json"},
        "outline": {"file": "academic-outline.json"},
        "validation": {"file": "academic-validation.json"},
    }
    artifacts = _base_artifacts()
    artifacts["selected-cases.json"]["authentic_selection_status"] = \
        "insufficient_revision_cases"
    artifacts["academic-validation.json"] = {
        "status": "fail",
        "issues": [{"type": "insufficient_core_revision_cases"}],
    }
    resumed = []
    monkeypatch.setattr(core, "resume_job", lambda job_id, filename, kwargs,
                        base_url=None: resumed.append((job_id, filename)) or True)
    at, old_output = _render_report(tmp_path, state, artifacts)
    try:
        at.session_state["api_key_DeepSeek"] = "test-key"
        at.run()
        next(button for button in at.button if button.label == "查看复核问题").click()
        at.run()
        next(button for button in at.button if button.label == "查看案例选择").click()
        at.run()
        next(button for button in at.button
             if button.label == "重新选择案例并继续生成").click()
        at.run()
        assert not at.exception, at.exception
        assert resumed == [("reportui0000001", "report-fixture.docx")]
        repaired = core.load_job_state("reportui0000001")
        assert not repaired["p3_done"]
        assert "selected_cases" not in repaired["academic_state"]["artifacts"]
        assert repaired["p2_done"]
    finally:
        core.OUTPUT_DIR = old_output


def test_report_missing_literature_evidence_is_actionable(tmp_path):
    state = _report_state(quality="review_required")
    artifacts = _base_artifacts()
    artifacts["literature-sources.json"] = {
        "sources": [{"source_id": "source-1", "title": "测试来源"}],
    }
    artifacts["literature-evidence.json"] = {"items": []}
    artifacts["literature-claims.json"] = {"items": []}
    at, old_output = _render_report(tmp_path, state, artifacts)
    try:
        assert not at.exception, at.exception
        next(button for button in at.button if button.label == "查看复核问题").click()
        at.run()
        assert any("文献证据缺失" in item.value for item in at.markdown)
    finally:
        core.OUTPUT_DIR = old_output


def test_report_docx_is_editable_ooxml_with_academic_formatting():
    report = (
        "# 翻译实践报告\n\n## 1 引言\n\n### 1.1 背景\n\n"
        "这一段包含 **Latin** 与中文。\n\n"
        "> 原文：Although the text is short.\n\n"
        "| 原文 | 译文 |\n| --- | --- |\n| source | 目标 |"
    )
    data = core.markdown_to_word(report, "功能对等理论").getvalue()
    assert data.startswith(b"PK")
    with ZipFile(BytesIO(data)) as archive:
        assert "[Content_Types].xml" in archive.namelist()
        assert "word/document.xml" in archive.namelist()
        styles = archive.read("word/styles.xml").decode("utf-8")
        document = archive.read("word/document.xml").decode("utf-8")
    assert "Times New Roman" in styles and "宋体" in styles
    assert "w:firstLine" in styles and "w:line" in styles
    assert "w:tbl" in document
    assert document.count("1 引言") == 1
