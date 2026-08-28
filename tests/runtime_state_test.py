"""Persistent runtime state, lease, cancellation, and retry semantics."""
import os
import threading
import time

import core


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _pipeline_kwargs():
    return {"enable_report": False, "enable_annotate": False}


def test_runtime_migration_and_worker_lease(tmp_path, monkeypatch):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    entered = threading.Event()
    release = threading.Event()
    original = core.run_job_pipeline

    def fake_pipeline(job_id, filename, file_bytes, **kwargs):
        entered.set()
        release.wait(2)
        state = core.load_job_state(job_id) or core.new_job_state(filename)
        state.update(p1_done=True, p2_done=True, p3_done=False,
                     report_enabled=False, enable_annotate=False)
        core.save_job_state(job_id, state)
        return state

    try:
        monkeypatch.setattr(core, "run_job_pipeline", fake_pipeline)
        job_id = "runtimelease0001"
        core.save_job_state(job_id, core.new_job_state("fixture.docx"))
        assert core.build_job_runtime_view(job_id)["runtime_status"] == "idle_incomplete"
        assert core.start_job_worker(job_id, "fixture.docx", None, _pipeline_kwargs())
        assert _wait_for(entered.is_set)
        assert not core.start_job_worker(job_id, "fixture.docx", None, _pipeline_kwargs())
        runtime = core.load_runtime_state(job_id)
        assert runtime["schema_version"] == core.RUNTIME_SCHEMA_VERSION
        assert runtime["worker"]["owner_pid"] == os.getpid()
        assert runtime["worker"]["worker_id"]
        assert (core.runtime_events_path(job_id)).is_file()
        release.set()
        assert _wait_for(lambda: core.get_job_runtime_status(job_id)["status"] == "completed")
    finally:
        release.set()
        _wait_for(lambda: not core.is_job_worker_alive(job_id))
        monkeypatch.setattr(core, "run_job_pipeline", original)
        core._RUNTIME_WORKERS.clear()
        core.OUTPUT_DIR = old_output


def test_runtime_failure_and_cancel_are_persisted(tmp_path, monkeypatch):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    original = core.run_job_pipeline
    try:
        def fail_pipeline(*args, **kwargs):
            raise TimeoutError("provider timeout")

        monkeypatch.setattr(core, "run_job_pipeline", fail_pipeline)
        failed_id = "runtimefailed01"
        core.start_job_worker(failed_id, "fixture.docx", None, _pipeline_kwargs())
        assert _wait_for(lambda: core.get_job_runtime_status(failed_id)["status"] == "failed")
        failed = core.load_runtime_state(failed_id)
        assert failed["error"]["type"] == "TimeoutError"
        assert failed["error"]["operation"] == "pipeline"
        assert core.runtime_technical_log_path(failed_id).is_file()

        entered = threading.Event()
        release = threading.Event()

        def slow_pipeline(*args, **kwargs):
            entered.set()
            release.wait(2)
            return core.load_job_state(args[0])

        monkeypatch.setattr(core, "run_job_pipeline", slow_pipeline)
        cancelled_id = "runtimecancel001"
        core.start_job_worker(cancelled_id, "fixture.docx", None, _pipeline_kwargs())
        assert _wait_for(entered.is_set)
        assert core.request_job_cancel(cancelled_id)
        release.set()
        assert _wait_for(lambda: core.get_job_runtime_status(cancelled_id)["status"] == "cancelled")
        assert core.load_runtime_state(cancelled_id)["cancel_requested"]
    finally:
        monkeypatch.setattr(core, "run_job_pipeline", original)
        core._RUNTIME_WORKERS.clear()
        core.OUTPUT_DIR = old_output


def test_worker_heartbeat_renews_lease_while_pipeline_waits(tmp_path, monkeypatch):
    old_output = core.OUTPUT_DIR
    old_interval = core.RUNTIME_HEARTBEAT_SECONDS
    core.OUTPUT_DIR = tmp_path
    core.RUNTIME_HEARTBEAT_SECONDS = 0.1
    entered = threading.Event()
    release = threading.Event()
    original = core.run_job_pipeline

    def slow_pipeline(*args, **kwargs):
        entered.set()
        release.wait(3)
        return core.load_job_state(args[0])

    try:
        monkeypatch.setattr(core, "run_job_pipeline", slow_pipeline)
        job_id = "runtimeheartbt01"
        core.start_job_worker(job_id, "fixture.docx", None, _pipeline_kwargs())
        assert _wait_for(entered.is_set)
        runtime = core.load_runtime_state(job_id)
        initial_lease = runtime["worker"]["lease_expires_at"]
        time.sleep(1.1)
        renewed = core.load_runtime_state(job_id)
        assert renewed["last_heartbeat_at"] != runtime["last_heartbeat_at"]
        assert renewed["worker"]["lease_expires_at"] != initial_lease
    finally:
        release.set()
        _wait_for(lambda: not core.is_job_worker_alive(job_id))
        monkeypatch.setattr(core, "run_job_pipeline", original)
        core._RUNTIME_WORKERS.clear()
        core.RUNTIME_HEARTBEAT_SECONDS = old_interval
        core.OUTPUT_DIR = old_output


def test_dead_lease_becomes_interrupted(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "runtimeinterrup1"
        core.save_job_state(job_id, core.new_job_state("fixture.docx"))
        core.update_runtime_state(
            job_id, status="running", worker={"owner_pid": 99999999,
            "worker_id": "dead-worker", "lease_expires_at": "2099-01-01T00:00:00+00:00"},
            last_heartbeat_at="2099-01-01T00:00:00+00:00", event="开始运行")
        view = core.build_job_runtime_view(job_id)
        assert view["runtime_status"] == "interrupted"
        assert "resume" in view["available_actions"]
    finally:
        core.OUTPUT_DIR = old_output


def test_retry_section_invalidates_only_academic_downstream(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "runtimeretry001"
        state = core.new_job_state("fixture.docx")
        state.update(p1_done=True, p2_done=True, report_enabled=True)
        state["academic_state"]["artifacts"] = {
            "evidence": {"file": "academic-evidence.json"},
            "validation": {"file": "academic-validation.json"},
            "review": {"file": "academic-review.json"},
        }
        core.save_job_state(job_id, state)
        core.update_runtime_state(
            job_id, status="failed", stage="academic_writing",
            stage_id="quality_repair", operation_id="section_rewrite", section_id="3",
            event="第 3 节失败")
        assert core.retry_job_step(job_id)
        retried = core.load_job_state(job_id)
        assert retried["academic_state"]["forced_sections"] == ["3"]
        assert "evidence" in retried["academic_state"]["artifacts"]
        assert "validation" not in retried["academic_state"]["artifacts"]
        assert "review" not in retried["academic_state"]["artifacts"]
    finally:
        core.OUTPUT_DIR = old_output


def test_retry_structural_section_failure_rebuilds_case_outline(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "runtimeretrystructure"
        state = core.new_job_state("fixture.docx")
        state.update(p1_done=True, p2_done=True, report_enabled=True)
        state["academic_state"]["artifacts"] = {
            name: {"file": f"{name}.json"} for name in (
                "evidence", "case_analysis_plans", "outline", "sections", "validation")
        }
        core.save_job_state(job_id, state)
        core.update_runtime_state(
            job_id, status="failed", stage="academic_writing",
            operation_id="section_rewrite", section_id="3",
            error={"message": (
                "学术写作阶段失败：missing case target subsection: 3.3.4")})

        assert core.retry_job_step(job_id)
        artifacts = core.load_job_state(job_id)["academic_state"]["artifacts"]
        assert "evidence" in artifacts
        assert "case_analysis_plans" not in artifacts
        assert "outline" not in artifacts
        assert "sections" not in artifacts
    finally:
        core.OUTPUT_DIR = old_output


def test_event_visibility_and_checkpoint_noise_are_normalized(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "runtimeevents001"
        core.update_runtime_state(
            job_id, event="已从断点恢复任务", event_name="resume_requested",
            event_visibility="user", event_category="lifecycle",
            event_metadata={"resume_request_id": "resume-1"})
        # Polling/rerender may repeat the same normalized user event.
        core.update_runtime_state(
            job_id, event="已从断点恢复任务", event_name="resume_requested",
            event_visibility="user", event_category="lifecycle",
            event_metadata={"resume_request_id": "resume-1"})
        for _ in range(10):
            core.update_runtime_state(
                job_id, event="checkpoint persisted", event_name="checkpoint_saved",
                event_visibility="technical", event_category="checkpoint")

        user_events = core.read_runtime_events(job_id, visibility="user")
        technical_events = core.read_runtime_events(job_id, visibility="technical")
        assert [(event["visibility"], event["category"]) for event in user_events] == [
            ("user", "lifecycle")]
        assert len(technical_events) == 10
        assert all(event["category"] == "checkpoint" for event in technical_events)
        view = core.build_job_runtime_view(job_id)
        assert [event["message"] for event in view["user_events"]] == ["已从断点恢复任务"]
        assert "checkpoint" not in " ".join(
            event["message"] for event in view["user_events"])
    finally:
        core.OUTPUT_DIR = old_output


def test_resume_is_idempotent_and_preserves_academic_progress(tmp_path, monkeypatch):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    entered = threading.Event()
    release = threading.Event()
    original = core.run_job_pipeline

    def paused_pipeline(job_id, filename, file_bytes, **kwargs):
        assert kwargs["enable_report"] is True
        entered.set()
        release.wait(2)
        return core.load_job_state(job_id)

    try:
        monkeypatch.setattr(core, "run_job_pipeline", paused_pipeline)
        job_id = "runtimeresume001"
        state = core.new_job_state("fixture.docx")
        state.update(p1_done=True, p2_done=True, report_enabled=True,
                     enable_annotate=False)
        state["academic_state"]["current_stage"] = "repair"
        state["academic_state"]["artifacts"] = {
            name: {"file": f"{name}.json"} for name in (
                "evidence", "research_model", "argument_plan", "selected_cases",
                "outline", "sections", "validation")
        }
        core.save_job_state(job_id, state)
        # A stale UI default must not disable an already-started academic graph.
        kwargs = {"enable_report": False, "enable_annotate": False}

        assert core.resume_job(job_id, "fixture.docx", kwargs)
        assert _wait_for(entered.is_set)
        assert not core.resume_job(job_id, "fixture.docx", kwargs)
        view = core.build_job_runtime_view(job_id, state)
        assert view["status"] in {"starting", "running", "waiting_external"}
        assert view["show_no_worker_warning"] is False
        assert view["progress"] == (7, 11)
        assert "修订" in view["headline"]
        assert [event["message"] for event in view["user_events"]].count(
            "已从断点恢复任务") == 1
        technical = core.read_runtime_events(job_id, visibility="technical")
        assert sum(event["event"] == "job_queued" for event in technical) == 1

        # Rebuilding the view during polling must not create another event.
        for _ in range(5):
            core.build_job_runtime_view(job_id, state)
        assert len(core.read_runtime_events(job_id, visibility="user")) == 1
    finally:
        release.set()
        _wait_for(lambda: not core.is_job_worker_alive("runtimeresume001"))
        monkeypatch.setattr(core, "run_job_pipeline", original)
        core._RUNTIME_WORKERS.clear()
        core.OUTPUT_DIR = old_output


def test_queued_to_running_uses_one_canonical_view(tmp_path, monkeypatch):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "runtimetransition"
        state = core.new_job_state("fixture.docx")
        core.save_job_state(job_id, state)
        now = core._utc_now_iso()
        monkeypatch.setattr(core, "_runtime_pid_alive", lambda pid: True)
        monkeypatch.setattr(core, "_runtime_worker_registered", lambda *args: True)
        worker = {"owner_pid": 123, "worker_id": "transition-worker",
                  "lease_expires_at": "2099-01-01T00:00:00+00:00"}
        core.update_runtime_state(
            job_id, status="queued", phase="starting", phase_label="准备中",
            worker=worker, last_progress_at=now, last_heartbeat_at=now)
        queued = core.build_job_runtime_view(job_id, state)
        assert queued["status_label"] == "正在恢复任务"
        assert queued["show_no_worker_warning"] is False
        core.update_runtime_state(
            job_id, status="running", phase="running", phase_label="正在执行",
            worker=worker, last_progress_at=now, last_heartbeat_at=now)
        running = core.build_job_runtime_view(job_id, state)
        assert running["status_label"] == "正在运行"
        assert running["detail"] == "正在执行"
        assert running["show_no_worker_warning"] is False
    finally:
        core.OUTPUT_DIR = old_output


def test_pipeline_persists_resume_and_delivery_configuration(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "runtimeconfig001"
        state = core.new_job_state("fixture.docx")
        state.update(p1_done=True, p2_done=True, annotations_done=True)
        core.save_job_state(job_id, state)
        delivery_config = core.default_delivery_config()
        delivery_config.update(deliver_pdf=True, deliver_bilingual_docx=False)
        result = core.run_job_pipeline(
            job_id, "fixture.docx", None,
            provider="DeepSeek", api_key="key", model="deepseek-chat",
            target_lang="العربية", auto_term=True, enable_report=False,
            translation_theory="功能对等理论", style_rules="保留正式语域",
            enable_review=True, enable_annotate=True, use_tm=False,
            strict_terminology_governance=False,
            delivery_config=delivery_config,
        )
        saved = core.load_job_state(job_id)
        assert result["pipeline_config"] == saved["pipeline_config"]
        assert saved["pipeline_config"] == {
            "target_lang": "العربية", "auto_term": True,
            "enable_report": False, "translation_theory": "功能对等理论",
            "style_rules": "保留正式语域", "enable_review": True,
            "enable_annotate": True, "use_tm": False,
            "strict_terminology_governance": False,
            "enable_understanding": False,
            "translator": {"provider": "DeepSeek", "model": "deepseek-chat",
                            "base_url": "", "configured": True},
            "reviewer": {"provider": "DeepSeek", "model": "deepseek-chat",
                          "base_url": "", "configured": True},
        }
        assert saved["target_lang"] == "العربية"
        assert saved["auto_term_enabled"] is True
        assert saved["enable_review"] is True and saved["use_tm"] is False
        assert saved["delivery_config"]["deliver_pdf"] is True
        assert saved["delivery_config"]["deliver_bilingual_docx"] is False
    finally:
        core.OUTPUT_DIR = old_output
