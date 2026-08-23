"""Immutable final-delivery snapshot regressions."""
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from zipfile import ZipFile
from io import BytesIO

import core
from transpraxis import snapshots


def _job(job_id, *, target="译文", findings=None, glossary=None):
    state = core.new_job_state("snapshot.docx")
    state.update(
        p1_done=True, p2_done=True, report_enabled=False,
        paras=["Source text"],
        pairs=[{
            "source": "Source text", "target": target,
            "initial_target": "初译", "reviewed": True,
            "target_provenance": "reviewed",
        }],
        findings=findings or [],
        glossary=glossary or [],
        delivery_status="review_required" if findings else "draft",
        has_blocking=bool(findings),
    )
    core.save_source(job_id, b"source document bytes")
    core.save_job_state(job_id, state)
    if glossary:
        state = core.freeze_glossary(job_id, entries=glossary, frozen_by="test")
    return state


def test_first_approval_freezes_assets_manifest_and_identity():
    tmp = Path(tempfile.mkdtemp(prefix="delivery-snapshot-first-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        job_id = "snapshotfirst00001"
        state = _job(job_id, glossary=[{
            "source": "Other term", "target": "其他术语",
            "preferred": "其他术语", "status": "locked", "scope": "document",
        }])
        approved, ok, errors = core.approve_delivery(
            job_id, note="首版确认", actor="reviewer")
        assert ok, errors
        assert approved["delivery_status"] == "final"
        assert approved["latest_delivery_snapshot_version"] == 1
        reloaded = core.load_job_state(job_id)
        assert reloaded["delivery_status"] == "final"
        assert core.delivery_snapshot_status(job_id, reloaded)["current"]

        manifest = core.list_delivery_snapshots(job_id)[0]
        assert manifest["job_identity"]["job_id"] == job_id
        assert manifest["approval"]["actor"] == "reviewer"
        assert manifest["approval"]["note"] == "首版确认"
        assert manifest["source_identity"]["source_hash"] == hashlib.sha256(
            b"source document bytes").hexdigest()
        assert manifest["active_terminology_version"]["version"] == 1
        assert manifest["translation_state_identity"]
        assert manifest["assets"]
        for item in manifest["assets"]:
            data = core.delivery_snapshot_assets(job_id, 1)[item["name"]]
            assert data is not None
            assert item["sha256"] == hashlib.sha256(data).hexdigest()
        archive = core.delivery_snapshot_archive(job_id, 1)
        assert archive
        with ZipFile(BytesIO(archive)) as bundle:
            assert "snapshot_manifest.json" in bundle.namelist()
            assert "delivery_manifest.json" in bundle.namelist()
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_mutation_keeps_old_bytes_and_second_approval_creates_new_version():
    tmp = Path(tempfile.mkdtemp(prefix="delivery-snapshot-versions-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        job_id = "snapshotversions01"
        _job(job_id)
        first, ok, errors = core.approve_delivery(job_id, note="v1")
        assert ok, errors
        old_manifest = core.list_delivery_snapshots(job_id)[0]
        old_bytes = core.delivery_snapshot_assets(job_id, 1)["bilingual.jsonl"]

        changed = core.load_job_state(job_id)
        changed["pairs"][0]["target"] = "工作版本新译文"
        core.save_job_state(job_id, changed)
        working = core.load_job_state(job_id)
        assert working["delivery_status"] == "draft"
        assert core.delivery_snapshot_assets(job_id, 1)["bilingual.jsonl"] == old_bytes
        assert core.delivery_snapshot_status(job_id, working)["diverged"]

        second, ok, errors = core.approve_delivery(job_id, note="v2")
        assert ok, errors
        assert second["latest_delivery_snapshot_version"] == 2
        assert len(core.list_delivery_snapshots(job_id)) == 2
        assert core.list_delivery_snapshots(job_id)[0] == old_manifest
        assert core.delivery_snapshot_assets(job_id, 1)["bilingual.jsonl"] == old_bytes
        assert core.delivery_snapshot_assets(job_id, 2)["bilingual.jsonl"] != old_bytes
        reloaded = core.load_job_state(job_id)
        assert reloaded["latest_delivery_snapshot_version"] == 2
        assert len(core.list_delivery_snapshots(job_id)) == 2
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_terminology_change_invalidates_current_but_preserves_snapshot():
    tmp = Path(tempfile.mkdtemp(prefix="delivery-snapshot-terms-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        job_id = "snapshotterms00001"
        _job(job_id, glossary=[{
            "source": "Other term", "target": "其他术语",
            "preferred": "其他术语", "status": "locked", "scope": "document",
        }])
        _, ok, errors = core.approve_delivery(job_id, note="旧术语版")
        assert ok, errors
        old_manifest = core.list_delivery_snapshots(job_id)[0]
        old_bytes = core.delivery_snapshot_assets(job_id, 1)["delivery_manifest.json"]
        changed = core.freeze_glossary(job_id, entries=[{
            "source": "Changed term", "target": "变更术语",
            "preferred": "变更术语", "status": "locked", "scope": "document",
        }], frozen_by="terminologist")
        assert changed["delivery_status"] == "draft"
        assert changed["delivery_approved_by_human"] is False
        assert core.list_delivery_snapshots(job_id)[0] == old_manifest
        assert core.delivery_snapshot_assets(job_id, 1)["delivery_manifest.json"] == old_bytes
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_retranslation_invalidates_current_but_preserves_snapshot(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="delivery-snapshot-retranslate-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        job_id = "snapshotretranslate1"
        state = _job(job_id)
        state["paras"] = ["Source text"]
        core.save_job_state(job_id, state)
        _, ok, errors = core.approve_delivery(job_id, note="原译文")
        assert ok, errors
        old_bytes = core.delivery_snapshot_assets(job_id, 1)["bilingual.jsonl"]
        monkeypatch.setattr(core, "translate_batch", lambda *args, **kwargs: ["重新翻译"])
        updated, fixed = core.retranslate_segments(
            job_id, [0], "DeepSeek", "key", "model", "简体中文", glossary=[])
        assert fixed == [0]
        assert updated["delivery_status"] == "draft"
        assert updated["delivery_approval"] is None
        assert core.delivery_snapshot_assets(job_id, 1)["bilingual.jsonl"] == old_bytes
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_blocking_requires_explicit_risk_acceptance_and_snapshot_records_it():
    tmp = Path(tempfile.mkdtemp(prefix="delivery-snapshot-risk-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        job_id = "snapshotrisk00001"
        state = _job(job_id, findings=[{
            "segment_index": 0, "severity": "blocking", "type": "check",
            "reason": "需要人工确认",
        }])
        _, ok, errors = core.approve_delivery(job_id)
        assert not ok and errors
        assert core.list_delivery_snapshots(job_id) == []
        approved, ok, errors = core.approve_delivery(
            job_id, note="明确接受风险", actor="risk-owner", accept_blocking=True)
        assert ok, errors
        manifest = core.list_delivery_snapshots(job_id)[0]
        assert approved["findings"][0]["resolution"]["action"] == "accepted_risk"
        assert manifest["accepted_risks"]
        assert manifest["accepted_risks"][0]["actor"] == "risk-owner"
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_snapshot_storage_is_local_output_data_not_package_input():
    root = Path(__file__).resolve().parent.parent
    assert "outputs/" in (root / ".gitignore").read_text(encoding="utf-8")
    assert snapshots.SNAPSHOT_DIR == "delivery_snapshots"


def test_frozen_snapshot_is_visible_in_workspace_and_history():
    from streamlit.testing.v1 import AppTest

    tmp = Path(tempfile.mkdtemp(prefix="delivery-snapshot-ui-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        job_id = "snapshotsui00001"
        state = core.new_job_state("ui-fixture.docx")
        state.update(
            p1_done=True, p2_done=True, stage="DONE", paras=["Source text"],
            pairs=[{"source": "Source text", "target": "译文", "reviewed": True}],
            report_enabled=False, delivery_status="draft")
        core.save_source(job_id, b"ui source bytes")
        core.save_job_state(job_id, state)
        _, ok, errors = core.approve_delivery(job_id, note="UI smoke", actor="reviewer")
        assert ok, errors

        at = AppTest.from_file(
            str(Path(__file__).resolve().parent.parent / "app.py"),
            default_timeout=30)
        at.run()
        at.session_state["active_job_id"] = job_id
        at.session_state["app_view"] = "workspace"
        at.session_state["workspace_mode"] = True
        at.session_state["workspace_section"] = "delivery"
        at.run()
        assert not at.exception, at.exception
        assert any("最终交付版本 v1" in item.value for item in at.success)
        assert any(button.label == "下载最终交付版本 v1"
                   for button in at.download_button)

        at.session_state["app_view"] = "history"
        at.session_state["workspace_mode"] = False
        at.run()
        assert not at.exception, at.exception
        assert any(button.label == "下载最终交付版本 v1"
                   for button in at.download_button)
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)
