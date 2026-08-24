"""Runtime presentation and resume transition regressions."""
import shutil
import tempfile
from pathlib import Path

import core


def test_resume_transition_hides_no_worker_copy_and_keeps_technical_details():
    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parent.parent
    tmp = Path(tempfile.mkdtemp(prefix="runtime-resume-ui-"))
    old_dir = core.OUTPUT_DIR
    try:
        core.OUTPUT_DIR = tmp
        job_id = "runtimeuiresume1"
        state = core.new_job_state("report.docx")
        state.update(p1_done=True, p2_done=True, report_enabled=True,
                     enable_annotate=False)
        state["academic_state"]["current_stage"] = "repair"
        state["academic_state"]["artifacts"] = {
            name: {"file": f"{name}.json"} for name in (
                "evidence", "research_model", "argument_plan", "selected_cases",
                "outline", "sections", "validation")
        }
        core.save_job_state(job_id, state)
        now = core._utc_now_iso()
        core.update_runtime_state(
            job_id, status="resume_requested", phase="resume_requested",
            phase_label="正在恢复任务", resume_request_id="resume-ui-1",
            started_at=now, operation_started_at=now, last_progress_at=now,
            completed_units=7, total_units=11,
            **core._academic_resume_context(state),
            event="已从断点恢复任务", event_name="resume_requested",
            event_visibility="user", event_category="lifecycle")
        core.update_runtime_state(
            job_id, event="worker claimed", event_name="worker_started",
            event_visibility="technical", event_category="orchestration")

        at = AppTest.from_file(str(root / "app.py"), default_timeout=30)
        at.session_state["active_job_id"] = job_id
        at.session_state["app_view"] = "workspace"
        at.session_state["workspace_mode"] = True
        at.run()
        assert not at.exception
        panel = next(item.value for item in at.markdown
                     if '<div class="tp-runtime-panel">' in item.value)
        assert "正在恢复任务" in panel
        assert "7 / 11" in panel
        assert "当前没有后台 worker" not in panel
        assert "worker" not in panel and "lease" not in panel and "PID" not in panel
        resuming = [button for button in at.button if button.label == "正在恢复…"]
        assert len(resuming) == 1 and resuming[0].disabled
        assert any(expander.label == "运行详情" for expander in at.expander)
        assert any("worker_started · worker claimed" in item.value for item in at.markdown)
        assert sum(event["event"] == "resume_requested" for event in
                   core.read_runtime_events(job_id, visibility="user")) == 1

        at.run()
        assert sum(event["event"] == "resume_requested" for event in
                   core.read_runtime_events(job_id, visibility="user")) == 1
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_continue_uses_the_task_saved_configuration(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    captured = []
    try:
        job_id = "runtimeuisavedcfg"
        state = core.new_job_state("saved-config.docx")
        state.update(
            p1_done=True, p2_done=False,
            pipeline_config={
                "target_lang": "العربية", "auto_term": True,
                "enable_report": False, "translation_theory": "目的论",
                "style_rules": "保存的风格", "enable_review": True,
                "enable_annotate": True, "use_tm": False,
                "strict_terminology_governance": False,
            },
            delivery_config=core.normalize_delivery_config({
                "deliver_plain_docx": False, "deliver_pdf": True,
            }, enable_report=False, enable_annotate=True),
        )
        core.save_job_state(job_id, state)
        monkeypatch.setattr(
            core, "resume_job",
            lambda job, filename, kwargs, base_url=None:
            captured.append(kwargs) or True)

        at = AppTest.from_file(
            str(Path(__file__).resolve().parent.parent / "app.py"),
            default_timeout=30)
        at.run()
        at.session_state["active_job_id"] = job_id
        at.session_state["app_view"] = "workspace"
        at.session_state["workspace_mode"] = True
        at.session_state["workspace_section"] = "overview"
        at.run()
        next(button for button in at.button if button.label == "继续处理").click()
        at.run()
        assert not at.exception, at.exception
        assert len(captured) == 1
        kwargs = captured[0]
        assert kwargs["target_lang"] == "العربية"
        assert kwargs["auto_term"] is True
        assert kwargs["style_rules"] == "保存的风格"
        assert kwargs["enable_review"] is True
        assert kwargs["enable_annotate"] is True
        assert kwargs["use_tm"] is False
        assert kwargs["delivery_config"]["deliver_pdf"] is True
        assert kwargs["delivery_config"]["deliver_plain_docx"] is False
    finally:
        core.OUTPUT_DIR = old_dir
