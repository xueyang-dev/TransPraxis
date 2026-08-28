"""System-level regression coverage for the long-document runtime contract."""
import base64
import io
import json
import re
import sys

import fitz
import pytest
from docx import Document

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

import core
from transpraxis import assets, context, entity_registry, knowledge, model_roles
from transpraxis.translation_protocol import (
    TranslationProtocolError,
    parse_translation_array,
    parse_translation_response,
)


def _make_docx(paragraphs):
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def _make_layout_pdf():
    """Create a small real PDF with an image/caption interruption and furniture."""
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    document = fitz.open()
    for page_number in range(2):
        page = document.new_page(width=612, height=792)
        page.insert_text((72, 30), "TransPraxis running header", fontsize=9)
        page.insert_text((72, 100), "The winds, temperature, and", fontsize=11)
        if page_number == 0:
            page.insert_image(fitz.Rect(72, 115, 500, 250), stream=image)
            page.insert_text(
                (90, 265),
                "Figure 1. Odilon Redon, The Eye Like a Strange Balloon",
                fontsize=8,
            )
            page.insert_text(
                (72, 285), "air pressure all play a part, and", fontsize=11
            )
            page.insert_text(
                (72, 715), "1. This footnote must not enter the body.", fontsize=7
            )
        else:
            page.insert_text(
                (72, 115), "the experiment continues on the next page.", fontsize=11
            )
        page.insert_text((72, 780), str(page_number + 1), fontsize=9)
    try:
        return document.tobytes()
    finally:
        document.close()


def test_pdf_layout_roles_keep_caption_and_furniture_out_of_body():
    pdf_bytes = _make_layout_pdf()
    blocks = core._pdf_ingestion.extract_layout_blocks(pdf_bytes)
    assert blocks and {"page_number", "bbox", "font_size", "font_flags",
                       "font_style", "block_id", "reading_order",
                       "relative_width", "page_width", "page_height"} <= set(blocks[0])
    classified = core._pdf_ingestion.classify_blocks(blocks)
    roles = {block.get("role") for block in classified}
    assert {"caption", "footnote", "header", "page_number", "image"} <= roles

    paragraphs = core.extract_pdf_paragraphs(pdf_bytes)
    joined = " ".join(paragraphs)
    assert "The winds, temperature, and air pressure all play a part, and" in joined
    assert "the experiment continues on the next page." in joined
    assert "Odilon Redon" not in joined
    assert "This footnote must not enter the body" not in joined
    assert "running header" not in joined
    assert not any(re.fullmatch(r"\d{1,4}", paragraph) for paragraph in paragraphs)


def test_translation_protocol_has_one_canonical_rejection_point():
    with pytest.raises(TranslationProtocolError):
        parse_translation_response('["A", "B"]', 1)
    with pytest.raises(TranslationProtocolError):
        parse_translation_response('{"foo": "bar"}', 1)
    assert parse_translation_response("正常译文", 1) == ["正常译文"]
    assert parse_translation_response('["甲", "乙"]', 2) == ["甲", "乙"]
    assert parse_translation_response("1. 甲\n2. 乙", 2) == ["甲", "乙"]
    assert parse_translation_array('["A", "B"]', 1) is None


def test_malformed_translation_response_retries_and_never_becomes_target():
    calls = []

    def malformed(*args, **kwargs):
        calls.append((args, kwargs))
        return '["A", "B"]'

    with pytest.raises(RuntimeError, match="批次翻译失败"):
        core.translate_batch(
            ["One source sentence."], [], [], "", "", "中文",
            "unknown", "key", "model", call_llm_fn=malformed
        )
    assert len(calls) == 3


def test_delivery_gate_rechecks_injected_transport_wrapper(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        job_id = "target-invariant-0001"
        state = core.new_job_state("fixture.docx")
        state.update(
            p1_done=True,
            p2_done=True,
            paras=["A source paragraph."],
            pairs=[{"source": "A source paragraph.", "target": '["A", "B"]'}],
            target_lang="简体中文",
            delivery_status="final",
        )
        core.save_job_state(job_id, state)
        with pytest.raises(RuntimeError, match="Translation Target Invariant"):
            core.build_delivery_assets(job_id)
        loaded = core.load_job_state(job_id)
        assert loaded["delivery_validation"]["blocking"] is True
        assert loaded["delivery_status"] != "final"
        assert any(
            finding.get("type") == "delivery_invariant"
            and finding.get("invariant_code") == "transport_wrapper"
            for finding in loaded["findings"]
        )
        loaded, approved, reasons = core.approve_delivery(job_id)
        assert not approved and reasons
        assert loaded["delivery_status"] != "final"
    finally:
        core.OUTPUT_DIR = old_output


def test_standard_runtime_runs_understanding_and_injects_it_into_translation_context(tmp_path):
    old_output, old_llm = core.OUTPUT_DIR, core.call_llm
    core.OUTPUT_DIR = tmp_path
    prompts = []
    try:
        def llm(provider, key, model, system, user, temperature=0.1):
            prompts.append((system, user))
            if "文档画像" in system:
                return json.dumps({
                    "domain": "翻译学", "genre": "学术专著", "register": "正式书面语",
                    "confidence": 0.9,
                    "sections": [{"section_id": "s1", "start_segment": 0,
                                  "end_segment": 1, "topic": "理论"}],
                })
            if "文档理解器" in system and "全书理解器" not in system:
                return json.dumps({
                    "summary": "当前单元摘要内容",
                    "key_terms": ["理论连续性"],
                    "translation_notes": ["保持指代连续"],
                })
            if "全书理解器" in system:
                return json.dumps({
                    "summary": "全文概要内容", "document_arc": "全文论证发展",
                    "themes": ["理论"],
                })
            if "翻译流知识抽取器" in system:
                return "[]"
            if "学术翻译专家" in system:
                current = user.split("【待翻译段落（按序号返回等长数组）】", 1)[-1]
                count = len(re.findall(r"(?m)^\d+\.\s+", current))
                return json.dumps(["这是完整的中文译文。"] * count)
            raise AssertionError(f"unexpected mock prompt: {system[:80]}")

        core.call_llm = llm
        state = core.run_job_pipeline(
            "standard-understanding-0001", "fixture.docx",
            _make_docx(["The first theoretical sentence.", "The second sentence follows."]),
            provider="DeepSeek", api_key="key", model="model-standard",
            target_lang="简体中文", auto_term=False, enable_report=False,
            enable_review=False, enable_annotate=False,
            translation_theory="功能对等理论", strict_terminology_governance=False,
        )
        assert state["profile_done"] and state["understanding_done"]
        assert state["semantic_units"] and state["section_digests"]
        assert state["document_synopsis"]["summary"] == "全文概要内容"
        translation_prompts = [user for system, user in prompts if "学术翻译专家" in system]
        assert translation_prompts
        assert "全文概要内容" in translation_prompts[0]
        assert "当前单元摘要内容" in translation_prompts[0]
        assert state["context_packet_log"][0]["current_batch_count"] == 2
    finally:
        core.OUTPUT_DIR, core.call_llm = old_output, old_llm


def test_standard_continuity_observation_is_bounded_and_available_without_review(tmp_path):
    old_output, old_llm = core.OUTPUT_DIR, core.call_llm
    core.OUTPUT_DIR = tmp_path
    calls = []
    try:
        paragraphs = [
            "The volumetric sensing method appears in this paragraph."
            if index in (0, 4) else f"A contextual paragraph number {index}."
            for index in range(8)
        ]

        def llm(provider, key, model, system, user, temperature=0.1):
            calls.append((provider, model, system, user))
            if "翻译流知识抽取器" in system:
                observations = []
                for match in re.finditer(
                    r"segment_id:\s*(\d+)\n原文：(.*?)\n译文：(.*?)(?=\n\nsegment_id:|$)",
                    user, re.S,
                ):
                    segment_id, source, target = match.groups()
                    if "volumetric sensing" in source:
                        observations.append({
                            "segment_id": int(segment_id),
                            "source_expression": "volumetric sensing",
                            "observed_target": "体积感知",
                            "kind": "term",
                        })
                return json.dumps(observations)
            if "学术翻译专家" in system:
                current = user.split("【待翻译段落（按序号返回等长数组）】", 1)[-1]
                current_sources = re.findall(r"(?m)^\d+\.\s+(.+)$", current)
                return json.dumps([
                    "体积感知在这里。" if "volumetric sensing" in source
                    else "这是完整的中文译文。"
                    for source in current_sources
                ])
            raise AssertionError(f"unexpected prompt: {system[:80]}")

        core.call_llm = llm
        state = core.new_job_state("continuity.docx")
        state.update(p1_done=True, paras=paragraphs, quality_mode=False)
        result = core.translate_stage(
            state, "continuity-0001", [], "DeepSeek", "key", "model-standard",
            "简体中文", "", enable_review=False, use_tm=False,
        )
        assert result["pairs"] and len(result["pairs"]) == 8
        candidates = result["translation_continuity"]
        assert candidates and candidates[0]["provenance"] == "generated_continuity"
        later_translation_users = [
            user for _, _, system, user in calls if "学术翻译专家" in system
        ]
        assert len(later_translation_users) == 2
        assert "volumetric sensing -> 体积感知" in later_translation_users[1]
        assert all(item.get("scope") == "document" for item in candidates)
    finally:
        core.OUTPUT_DIR, core.call_llm = old_output, old_llm


def test_locked_glossary_and_human_entity_choice_outrank_generated_observations():
    candidates = [{
        "source": "volumetric sensing", "observed_target": "体积感知",
        "kind": "term", "provenance": "generated_continuity",
        "scope": "document", "confidence": 0.35,
    }]
    assert knowledge.provisional_hints(
        candidates,
        authoritative_entries=[{
            "source": "volumetric sensing", "target": "容积传感", "status": "locked",
        }],
    ) == []

    registry = entity_registry.EntityRegistry()
    registry.observe(
        "The Repellent Fence", "《驱离之篱》", entity_type="artwork",
        segment_id=10, provenance="generated_observation", confidence=0.35,
    )
    assert registry.hints_for(["The Repellent Fence"])[0]["preferred_target"] == "《驱离之篱》"
    registry.lock("The Repellent Fence", "《驱逐围栏》", entity_type="artwork")
    registry.observe(
        "The Repellent Fence", "《错误译名》", entity_type="artwork",
        segment_id=100, provenance="generated_observation", confidence=0.2,
    )
    hint = registry.hints_for(["The Repellent Fence"])[0]
    assert hint["preferred_target"] == "《驱逐围栏》"
    assert hint["status"] == "locked"
    assert registry.consistency_findings()


def test_translator_and_reviewer_role_routing_is_distinct(tmp_path):
    old_output, old_llm = core.OUTPUT_DIR, core.call_llm
    core.OUTPUT_DIR = tmp_path
    calls = []
    try:
        def llm(provider, key, model, system, user, temperature=0.1):
            calls.append((provider, model, system))
            if "独立的翻译审校专家" in system:
                return "[]"
            if "翻译流知识抽取器" in system:
                return "[]"
            if "学术翻译专家" in system:
                return '["这是完整的中文译文。"]'
            raise AssertionError(f"unexpected prompt: {system[:80]}")

        core.call_llm = llm
        state = core.new_job_state("roles.docx")
        state.update(p1_done=True, paras=["One source sentence."])
        result = core.translate_stage(
            state, "roles-0001", [], "translator-provider", "translator-key",
            "model-A", "简体中文", "", enable_review=True, use_tm=False,
            translator_config={"provider": "translator-provider", "api_key": "translator-key",
                               "model": "model-A"},
            reviewer_config={"provider": "reviewer-provider", "api_key": "reviewer-key",
                             "model": "model-B"},
        )
        assert result["pairs"][0]["reviewed"] is True
        translation_calls = [item for item in calls if "学术翻译专家" in item[2]]
        review_calls = [item for item in calls if "独立的翻译审校专家" in item[2]]
        assert translation_calls and all(item[:2] == ("translator-provider", "model-A")
                                         for item in translation_calls)
        assert review_calls and all(item[:2] == ("reviewer-provider", "model-B")
                                    for item in review_calls)
        manifest = assets.build_delivery_manifest(
            result, "roles-0001", "简体中文", "translator-provider", "model-A",
            translator_config={"provider": "translator-provider", "model": "model-A",
                               "api_key": "must-not-be-exported"},
            reviewer_config={"provider": "reviewer-provider", "model": "model-B",
                             "api_key": "must-not-be-exported"},
        )
        assert manifest["translator"]["model"] == "model-A"
        assert manifest["reviewer"]["model"] == "model-B"
        assert "api_key" not in json.dumps(manifest, ensure_ascii=False)
    finally:
        core.OUTPUT_DIR, core.call_llm = old_output, old_llm


def test_provider_capability_unknown_endpoint_safely_falls_back_to_parser():
    native = core._native_translation_response_format("OpenAI", "gpt-4.1", 2)
    assert native and native["type"] == "json_schema"
    assert core._native_translation_response_format("DeepSeek", "deepseek-v4", 2) is None
    assert model_roles.provider_capabilities(core.PROVIDERS, "unlisted-relay")["plain_text_only"]


def test_restart_preserves_context_registry_and_provenance(tmp_path):
    old_output = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp_path
    try:
        state = core.new_job_state("restart.docx")
        state.update(
            semantic_units=[{"unit_id": "unit-0001", "start_segment": 0,
                             "end_segment": 0, "source": "source"}],
            section_digests=[{"unit_id": "unit-0001", "start_segment": 0,
                              "end_segment": 0, "summary": "摘要"}],
            document_synopsis={"summary": "概要", "status": "model"},
            translation_continuity=[{
                "source": "volumetric sensing", "observed_target": "体积感知",
                "provenance": "generated_continuity", "scope": "document",
            }],
            entity_registry=[{
                "source_form": "The Repellent Fence", "preferred_target": "《驱离之篱》",
                "entity_type": "artwork", "provenance": "generated_observation",
                "status": "observed", "confidence": 0.35,
            }],
        )
        core.save_job_state("restart-0001", state)
        loaded = core.load_job_state("restart-0001")
        assert loaded["section_digests"][0]["summary"] == "摘要"
        assert loaded["document_synopsis"]["summary"] == "概要"
        assert loaded["translation_continuity"][0]["provenance"] == "generated_continuity"
        assert loaded["entity_registry"][0]["entity_type"] == "artwork"
    finally:
        core.OUTPUT_DIR = old_output


def test_malformed_translation_does_not_pollute_tm_knowledge_or_entities(tmp_path):
    old_output, old_llm = core.OUTPUT_DIR, core.call_llm
    core.OUTPUT_DIR = tmp_path
    try:
        def malformed(*args, **kwargs):
            return '["译文 A", "译文 B"]'

        core.call_llm = malformed
        state = core.new_job_state("malformed.docx")
        state.update(p1_done=True, paras=["One source sentence."])
        with pytest.raises(RuntimeError):
            core.translate_stage(
                state, "malformed-0001", [], "DeepSeek", "key", "model",
                "简体中文", "", enable_review=False, use_tm=True,
            )
        assert state["pairs"] == []
        assert state["knowledge_candidates"] == []
        assert state["entity_registry"] == []
        assert core.load_tm() == {}
        candidates, events, warning = knowledge.observe_batch(
            ["One source sentence."], ['["译文 A", "译文 B"]'],
            ["One source sentence."], [], [], 0, "DeepSeek", "key", "model",
            call_llm=lambda *args, **kwargs: '[{"source_expression":"source",'
            '"observed_target":"译文","kind":"term"}]',
        )
        assert candidates == [] and events == [] and warning
    finally:
        core.OUTPUT_DIR, core.call_llm = old_output, old_llm
