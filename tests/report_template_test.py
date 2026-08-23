"""Template contract, routing, dependency and renderer checks."""
from io import BytesIO

from docx import Document
from docx.shared import Inches

import core
from transpraxis import academic_validator, academic_writer, report_template, thesis_constraints


def _template_bytes():
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(1.25)
    section.header.paragraphs[0].text = "固定页眉"
    section.footer.paragraphs[0].text = "固定页脚"
    document.add_paragraph("封面固定文字")
    document.add_heading("摘要", level=1)
    document.add_heading("1 项目概况", level=1)
    document.add_heading("1.1 项目背景", level=2)
    document.add_paragraph("模板占位内容")
    document.add_heading("2 理论框架", level=1)
    document.add_heading("2.1 理论依据", level=2)
    document.add_paragraph("模板占位内容")
    document.add_heading("3 案例分析", level=1)
    document.add_heading("3.1 案例说明", level=2)
    document.add_paragraph("模板占位内容")
    document.add_heading("4 结论与反思", level=1)
    document.add_heading("参考文献", level=1)
    result = BytesIO()
    document.save(result)
    return result.getvalue()


def _contract():
    return report_template.parse_docx_template("fixture.docx", _template_bytes())


def _outline(contract, cases=None):
    return {
        "template_hash": contract["template_identity"]["sha256"],
        "sections": [
            {"section_id": "1", "title": "项目概况", "role": "project_overview", "cases": []},
            {"section_id": "2", "title": "理论框架", "role": "theoretical_framework", "cases": []},
            {"section_id": "3", "title": "案例分析", "role": "case_analysis", "cases": cases or []},
            {"section_id": "4", "title": "结论与反思", "role": "conclusion_reflection", "cases": []},
        ],
    }


def _report_artifact(contract):
    return {
        "template_hash": contract["template_identity"]["sha256"],
        "front_matter": [{"title": "摘要"}],
        "back_matter": [{"title": "参考文献"}],
    }


def _valid_markdown():
    return """## 1 项目概况

### 1.1 项目背景

项目背景正文。

## 2 理论框架

### 2.1 理论依据

理论依据正文。

## 3 案例分析

### 3.1 案例说明

案例正文。

## 4 结论与反思

结论正文。
"""


def test_parser_is_deterministic_and_captures_structure_and_style():
    raw = _template_bytes()
    first = report_template.parse_docx_template("fixture.docx", raw)
    second = report_template.parse_docx_template("fixture.docx", raw)
    assert first["content_hash"] == second["content_hash"]
    assert first["template_identity"]["sha256"]
    assert [x["role"] for x in first["document_structure"]["chapters"]] == [
        "project_overview", "theoretical_framework", "case_analysis",
        "conclusion_reflection",
    ]
    assert first["document_structure"]["front_matter"][0]["role"] == "abstract"
    assert first["document_structure"]["back_matter"][0]["role"] == "references"
    assert first["style_contract"]["headers"] == [["固定页眉"]]
    assert first["style_contract"]["footers"] == [["固定页脚"]]
    assert first["style_contract"]["sections"][0]["geometry"]["top_margin_emu"]


def test_constraints_and_outline_keep_template_chapters_and_route_cases_by_role():
    contract = _contract()
    settings = {"body_language": "zh-CN", "report_template_contract": contract}
    constraints = thesis_constraints.build_constraints(settings)
    assert constraints["structure_source"] == "parsed_template_contract"
    assert [x["section_id"] for x in constraints["chapters"]] == ["1", "2", "3", "4"]

    research_model = academic_writer.build_research_model(
        {"project_evidence": {"document_profile": {}, "statistics": {}}},
        "自动推荐理论", settings)
    selected = {"cases": [{"case_id": "seg-case-0001", "case_type": "authentic_revision"}],
                "authentic_selection_status": "sufficient_revision_cases"}
    argument = {"claims": []}

    def fake_llm(*_args, **_kwargs):
        return '{"sections":[{"section_id":"1"},{"section_id":"2"},{"section_id":"4"}]}'

    outline = academic_writer.build_academic_outline(
        research_model, argument, selected,
        {"project_evidence": {"statistics": {}}}, fake_llm, "test", "", "model")
    assert [x["section_id"] for x in outline["sections"]] == ["1", "2", "3", "4"]
    assert outline["sections"][2]["cases"] == ["seg-case-0001"]
    assert outline["sections"][3]["cases"] == []


def test_template_validator_has_independent_compliance_gate():
    contract = _contract()
    outline = _outline(contract, ["seg-case-0001"])
    valid = academic_validator.validate_template_compliance(
        _valid_markdown(), contract, outline, _report_artifact(contract),
        {"cases": [{"case_id": "seg-case-0001"}]})
    assert valid["status"] == "pass"

    invalid = academic_validator.validate_template_compliance(
        _valid_markdown().replace("## 4 结论与反思", "## 9 新增章节"),
        contract, outline, _report_artifact(contract),
        {"cases": [{"case_id": "seg-case-0001"}]})
    issue_types = {x["type"] for x in invalid["issues"]}
    assert invalid["status"] == "fail"
    assert "template_chapter_title_mismatch" in issue_types
    assert "template_chapter_order_mismatch" in issue_types

    wrong_hash = dict(_report_artifact(contract), template_hash="different")
    hashed = academic_validator.validate_template_compliance(
        _valid_markdown(), contract, outline, wrong_hash,
        {"cases": [{"case_id": "seg-case-0001"}]})
    assert "template_hash_mismatch" in {x["type"] for x in hashed["issues"]}


def test_template_hash_invalidates_downstream_academic_artifacts():
    state = core.new_job_state("source.docx")
    contract_a = _contract()
    contract_b = report_template.parse_docx_template("other.docx", _template_bytes() + b"x")
    academic_writer.prepare_academic_inputs(
        state, "理论", {"report_template_contract": contract_a}, [])
    academic = state["academic_state"]
    for name in ("research_model", "argument_plan", "selected_cases", "outline",
                 "sections", "validation", "review", "academic_quality", "report"):
        academic["artifacts"][name] = {"content_hash": "old"}
    academic_writer.prepare_academic_inputs(
        state, "理论", {"report_template_contract": contract_b}, [])
    assert not set(academic["artifacts"]) & {
        "research_model", "argument_plan", "selected_cases", "outline", "sections",
        "validation", "review", "academic_quality", "report",
    }
    assert state["p3_done"] is False


def test_template_bytes_and_contract_survive_state_reload(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "template-persist"
        core.save_job_state(job_id, core.new_job_state("source.docx"))
        contract = core.save_report_template(job_id, "uploaded.docx", _template_bytes())
        loaded = core.load_report_template(job_id)
        assert loaded["contract"]["content_hash"] == contract["content_hash"]
        assert loaded["metadata"]["filename"] == "uploaded.docx"
        assert (core.job_dir(job_id) / "template-contract.json").is_file()
        assert (core.job_dir(job_id) / "report-template.docx").is_file()
        state = core.load_job_state(job_id)
        assert state["report_template_contract"]["template_identity"]["sha256"]
        core.clear_report_template(job_id)
        assert core.load_report_template(job_id) is None
    finally:
        core.OUTPUT_DIR = old_output


def test_template_renderer_preserves_word_layout_and_removes_placeholders():
    raw = _template_bytes()
    contract = _contract()
    artifact = {
        "sections": [
            {"section_id": "1", "intro_content": "项目概况正文。",
             "subsections": [{"title": "项目背景", "content": "背景正文。"}]},
            {"section_id": "2", "content": "理论正文。", "subsections": []},
            {"section_id": "3", "content": "案例正文。", "subsections": []},
            {"section_id": "4", "content": "结论正文。", "subsections": []},
        ]
    }
    rendered = Document(report_template.render_report_docx(artifact, raw, contract))
    texts = [paragraph.text for paragraph in rendered.paragraphs]
    assert "模板占位内容" not in texts
    assert "固定页眉" == rendered.sections[0].header.paragraphs[0].text
    assert "固定页脚" == rendered.sections[0].footer.paragraphs[0].text
    assert rendered.sections[0].top_margin.inches == 1.25
    assert [text for text in texts if text.startswith("固定") or "正文" in text]


def test_minimal_template_to_structured_artifact_to_rendered_docx():
    raw = _template_bytes()
    contract = _contract()
    constraints = thesis_constraints.build_constraints({
        "body_language": "zh-CN", "report_template_contract": contract})
    outline = _outline(contract, ["seg-case-0001"])
    written = [
        {"section_id": "1", "title": "项目概况",
         "content": "### 1.1 项目背景\n\n背景正文。"},
        {"section_id": "2", "title": "理论框架",
         "content": "### 2.1 理论依据\n\n理论正文。"},
        {"section_id": "3", "title": "案例分析",
         "content": "### 3.1 案例说明\n\n案例正文。"},
        {"section_id": "4", "title": "结论与反思", "content": "结论正文。"},
    ]
    markdown = "\n\n".join(
        f"## {item['section_id']} {item['title']}\n\n{item['content']}"
        for item in written) + "\n"
    artifact = academic_writer.build_report_artifact(
        markdown, written, outline, constraints)
    assert artifact["template_hash"] == contract["template_identity"]["sha256"]
    compliance = academic_validator.validate_template_compliance(
        markdown, contract, outline, artifact,
        {"cases": [{"case_id": "seg-case-0001"}]})
    assert compliance["status"] == "pass"
    rendered = Document(report_template.render_report_docx(artifact, raw, contract))
    assert "案例正文。" in [paragraph.text for paragraph in rendered.paragraphs]


def test_legacy_report_uses_generic_renderer(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "legacy-report"
        state = core.new_job_state("source.docx")
        state.update(p3_md="# 翻译实践报告\n\n旧任务报告。", theory="理论")
        core.save_job_state(job_id, state)
        output = core.report_docx_bytes(job_id, state)
        assert output and output[:2] == b"PK"
        assert core.load_report_template(job_id) is None
    finally:
        core.OUTPUT_DIR = old_output
