import json

from transpraxis import academic_writer


def test_generic_outline_uses_chapter_titles_to_route_cases():
    research = {
        "report_constraints": {
            "template": {"configured": False}, "chapters": [],
            "report_stage": "final_report",
        },
        "research_questions": [{"rq_id": "RQ1"}],
    }
    selected = {
        "cases": [{"case_id": "SC-1", "case_type": "synthetic_contrast"}],
    }
    raw = {
        "sections": [
            {"section_id": "1", "title": "引言", "role": "case_analysis"},
            {"section_id": "2", "title": "项目与方法", "role": "case_analysis"},
            {"section_id": "3", "title": "案例分析", "role": "case_analysis"},
            {"section_id": "4", "title": "讨论与结论", "role": "case_analysis"},
        ]
    }

    outline = academic_writer.build_academic_outline(
        research, {"claims": []}, selected,
        {"project_evidence": {"statistics": {}}},
        lambda *_args, **_kwargs: json.dumps(raw), "test", "", "model")

    assert [item["role"] for item in outline["sections"]] == [
        "introduction", "project_overview", "case_analysis",
        "conclusion_reflection",
    ]
    assert outline["sections"][0]["cases"] == []
    assert outline["sections"][2]["cases"] == ["SC-1"]


def test_case_subsections_follow_actual_chapter_and_missing_headings_are_created():
    selected = {"cases": [{
        "case_id": "SC-1", "case_type": "synthetic_contrast",
        "target_subsection": "3.3.1",
    }]}
    fallback = academic_writer._fallback_outline(
        {"research_questions": [], "target_words": 1000}, {"claims": []}, selected)
    default_case_section = next(
        section for section in fallback["sections"]
        if section.get("role") == "case_analysis")
    sections = [
        (default_case_section, "3.2", "3.3"),
        ({"section_id": "2", "title": "案例分析", "role": "case_analysis",
          "cases": ["SC-1"], "required_subsections": []}, "2.2", "2.3"),
        ({"section_id": "4", "title": "案例分析", "role": "case_analysis",
          "cases": ["SC-1"], "required_subsections": [
              {"heading_id": "4.2", "title": "翻译难点", "level": 2,
               "markdown_prefix": "###"},
              {"heading_id": "4.3", "title": "翻译策略", "level": 2,
               "markdown_prefix": "###"},
          ]}, "4.2", "4.3"),
    ]
    base_assignment = {
        "case_id": "SC-1", "difficulty_subsection": "3.2.1",
        "strategy_subsection": "3.3.1", "target_subsection": "3.3.1",
    }

    for section, problem_root, solution_root in sections:
        assignment = academic_writer._scope_case_assignment(base_assignment, section)
        assert assignment["difficulty_subsection"] == f"{problem_root}.1"
        assert assignment["target_subsection"] == f"{solution_root}.1"
        normalized = academic_writer._ensure_section_contract("案例正文。", section)
        assert f"### {problem_root} 翻译难点" in normalized
        assert f"### {solution_root}" in normalized
        repaired = academic_writer._insert_case_example(
            normalized, assignment["target_subsection"], "<!--case:SC-1-->\n案例")
        assert f"#### {solution_root}.1" in repaired
        assert "<!--case:SC-1-->" in repaired
