"""Offline regressions for independent rendered-QA facts."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

import core
from transpraxis import academic_writer, finalization, rendered_qa


@pytest.fixture(autouse=True)
def _restore_output_dir():
    previous = core.OUTPUT_DIR
    yield
    core.OUTPUT_DIR = previous


def _state(tmp_path, job_id="stage5qa000001"):
    core.OUTPUT_DIR = tmp_path
    state = core.new_job_state("report.docx")
    state.update(
        p1_done=True, p2_done=True, p3_done=True, report_enabled=True,
        paras=["Source paragraph"],
        pairs=[{"source": "Source paragraph", "target": "源文段落",
                "initial_target": "初译段落", "segment_id": "seg-1"}],
        p3_md="# Report\n\n正文。",
    )
    core.save_source(job_id, b"source")
    core.save_job_state(job_id, state)
    return job_id, state


def _pdf_bytes(*, blank=False):
    document = fitz.open()
    page = document.new_page()
    if not blank:
        page.insert_text((72, 72), "Rendered QA fixture", fontsize=12)
    output = BytesIO()
    document.save(output)
    document.close()
    return output.getvalue()


def test_libreoffice_unavailable_is_not_run_and_keeps_docx_binding(tmp_path, monkeypatch):
    job_id, _state_value = _state(tmp_path)
    monkeypatch.setattr(core, "report_docx_bytes", lambda *args, **kwargs: b"docx")
    monkeypatch.setattr(core.shutil, "which", lambda _name: None)

    state, qa = core.run_libreoffice_render_qa(job_id)

    assert qa["libreoffice_render"] == "NOT_RUN"
    record = core.load_academic_artifact(job_id, "libreoffice_render")
    assert record["qa_status"] == "NOT_RUN"
    assert record["source_docx_hash"] == rendered_qa.sha256(b"docx")
    assert record["rendered_pdf_hash"] is None
    assert record["page_count"] is None
    assert core.load_academic_artifact(job_id, "report_qa")
    assert state["final_qa"]["author_visual_review"] == "NOT_CONFIRMED"


def test_successful_render_records_engine_hashes_and_pdf_facts(tmp_path, monkeypatch):
    job_id, _state_value = _state(tmp_path, "stage5qa000002")
    pdf = _pdf_bytes()
    monkeypatch.setattr(core, "report_docx_bytes", lambda *args, **kwargs: b"docx-pass")
    monkeypatch.setattr(core.shutil, "which", lambda _name: "/fake/soffice")

    def fake_run(command, **_kwargs):
        if command[1] == "--version":
            return SimpleNamespace(returncode=0, stdout="LibreOffice 24.2\n", stderr="")
        outdir = Path(command[command.index("--outdir") + 1])
        (outdir / "current.pdf").write_bytes(pdf)
        return SimpleNamespace(returncode=0, stdout="convert ok", stderr="")

    monkeypatch.setattr(core.subprocess, "run", fake_run)
    state, qa = core.run_libreoffice_render_qa(job_id)

    assert qa["libreoffice_render"] == "PASS"
    record = core.load_academic_artifact(job_id, "libreoffice_render")
    assert record["render_engine"] == "libreoffice"
    assert record["render_engine_version"] == "LibreOffice 24.2"
    assert record["source_docx_hash"] == rendered_qa.sha256(b"docx-pass")
    assert record["rendered_pdf_hash"] == rendered_qa.sha256(pdf)
    assert record["page_count"] == 1
    assert record["analysis"]["pages"][0]["text_block_count"] >= 1
    assert state["final_qa"]["author_visual_review"] == "NOT_CONFIRMED"
    assert "LibreOffice PASS is not Microsoft Word final truth." in (
        core.load_academic_artifact(job_id, "report_qa")["markdown"])


def test_pdf_suspicious_blank_page_is_warning_not_render_fail(tmp_path):
    del tmp_path
    analysis = rendered_qa.analyze_pdf(_pdf_bytes())
    blank_analysis = rendered_qa.analyze_pdf(_pdf_bytes(blank=True))

    assert analysis["page_count"] == 1
    assert blank_analysis["page_count"] == 1
    assert any(item["type"] == "suspected_blank_page"
               for item in blank_analysis["warnings"])
    assert blank_analysis["definite_failures"] == []
    assert blank_analysis["status"] == "warning"


def test_pdf_facts_include_fonts_sizes_and_page_regions(tmp_path):
    del tmp_path
    analysis = rendered_qa.analyze_pdf(_pdf_bytes())
    page = analysis["pages"][0]
    assert page["image_block_count"] == 0
    assert page["drawing_block_count"] >= 0
    assert page["font_names"]
    assert page["font_sizes"]
    assert "header_region_chars" in page
    assert "footer_region_chars" in page
    assert "page_number_region" in page


def test_docx_hash_change_resets_human_reviews_and_stales_render(tmp_path, monkeypatch):
    job_id, state = _state(tmp_path, "stage5qa000003")
    report = {"report_status": "generated", "template_compliance": "pass",
              "report": {}, "content_hash": "report-hash"}
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "report", report, "report-dep", "report-v1")
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "final_docx_validation",
        {"status": "pass", "content_hash": "old-docx-validation",
         "source_docx_hash": rendered_qa.sha256(b"docx-v1")},
        "docx-dep", "docx-v1", input_artifact_ids=["report"])
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "libreoffice_render",
        {"status": "pass", "qa_status": "PASS",
         "source_docx_hash": rendered_qa.sha256(b"docx-v1"),
         "rendered_pdf_hash": "pdf-v1"},
        "render-dep", "render-v1", input_artifact_ids=["final_docx_validation"])
    state["final_qa"] = finalization.normalize_final_qa({
        "structural_qa": "PASS", "libreoffice_render": "PASS",
        "author_visual_review": "CONFIRMED", "word_final_review": "CONFIRMED",
        "source_docx_hash": rendered_qa.sha256(b"docx-v1"),
    })
    core.save_job_state(job_id, state)
    monkeypatch.setattr(core, "load_report_template", lambda _job: {
        "bytes": b"template", "contract": {"template_identity": {}}
    })
    monkeypatch.setattr(
        "transpraxis.report_template.render_report_docx",
        lambda *args, **kwargs: b"docx-v2")
    monkeypatch.setattr(
        "transpraxis.final_docx.validate_final_docx",
        lambda *_args, **_kwargs: {"status": "pass", "content_hash": "validation"})
    monkeypatch.setattr(
        "transpraxis.compliance.inspect_docx_layout",
        lambda _bytes: {"sections": 1, "paragraph_styles": []})

    result = core.report_docx_bytes(job_id)

    assert result == b"docx-v2"
    persisted = core.load_job_state(job_id)
    assert persisted["final_qa"]["author_visual_review"] == "NOT_CONFIRMED"
    assert persisted["final_qa"]["word_final_review"] == "NOT_CONFIRMED"
    assert persisted["final_qa"]["source_docx_hash"] == rendered_qa.sha256(b"docx-v2")
    assert core.load_academic_artifact(job_id, "final_docx_validation")[
        "source_docx_hash"] == rendered_qa.sha256(b"docx-v2")
    assert persisted["academic_state"]["artifacts"]["libreoffice_render"][
        "status"] == "stale"


def test_word_review_is_independent_of_libreoffice_pass(tmp_path, monkeypatch):
    job_id, state = _state(tmp_path, "stage5qa000004")
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "final_docx_validation",
        {"status": "pass", "content_hash": "docx"}, "docx-dep", "v1")
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "libreoffice_render",
        {"status": "pass", "qa_status": "PASS", "rendered_pdf_hash": "pdf"},
        "render-dep", "v1", input_artifact_ids=["final_docx_validation"])
    core.save_job_state(job_id, state)
    monkeypatch.setattr(core, "compliance_profile_view", lambda *_args: {
        "status": "pass", "profile_compliance": {"status": "pass"},
        "project_constraints": {"status": "pass"}, "counts": {},
    })
    core.record_final_qa(job_id, "author_visual_review", "CONFIRMED")

    _loaded, approved, errors = core.approve_delivery(job_id)

    assert not approved
    assert any("Word Final Review=NOT_CONFIRMED" in item for item in errors)


def test_report_qa_binds_translation_docx_pdf_and_state_facts(tmp_path):
    job_id, state = _state(tmp_path, "stage5qa000005")
    report = {"content_hash": "report-hash", "report": {}}
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "report", report, "report-dep", "v1")
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "final_docx_validation",
        {"status": "pass", "source_docx_hash": "docx-hash",
         "content_hash": "docx-validation"}, "docx-dep", "v1")
    academic_writer._save_artifact(
        state, core.job_dir(job_id), "libreoffice_render",
        {"status": "pass", "qa_status": "PASS", "source_docx_hash": "docx-hash",
         "rendered_pdf_hash": "pdf-hash", "analysis": {"warnings": [],
         "manual_reviews": []}}, "render-dep", "v1",
        input_artifact_ids=["final_docx_validation"])
    core.save_job_state(job_id, state)

    value = core.generate_report_qa(job_id, state, save_file=True)

    assert value["translation_truth_hash"] == core.current_translation_hash(state)
    assert value["source_docx_hash"] == "docx-hash"
    assert value["rendered_pdf_hash"] == "pdf-hash"
    record = core.load_academic_artifact(job_id, "report_qa")
    assert record["content_hash"] == value["content_hash"]
    artifact_record = state["academic_state"]["artifacts"]["report_qa"]
    assert set(artifact_record["input_artifact_ids"]) >= {
        "report", "final_docx_validation", "libreoffice_render"
    }
    assert (core.job_dir(job_id) / "report-qa.md").is_file()
