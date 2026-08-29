"""核心逻辑冒烟测试：解析、持久化、术语表/确定性检查、审校、翻译记忆、断点续传。

运行方式（项目根目录）：python tests/smoke_test.py
"""
import io
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core
from docx import Document


def test_opencode_go_provider_route():
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            message = type("Message", (), {"content": '{"ok":true}'})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    original = core.OpenAI
    core.OpenAI = FakeOpenAI
    try:
        result = core.call_llm(
            "OpenCode Go", "secret", "deepseek-v4-flash", "system", "user")
    finally:
        core.OpenAI = original
    assert result == '{"ok":true}'
    assert calls[0]["base_url"] == "https://opencode.ai/zen/go/v1"
    assert calls[0]["http_client"]._trust_env is False
    assert calls[0]["http_client"].is_closed
    assert calls[1]["model"] == "deepseek-v4-flash"
    print("  ✓ OpenCode Go provider route")


def test_parse_json_array():
    assert core.parse_json_array('["a", "b"]') == ["a", "b"]
    assert core.parse_json_array('```json\n["a"]\n```') == ["a"]
    assert core.parse_json_array('好的，结果如下：\n[{"Source": "MT", "Target": "机器翻译"}] 请查收') \
        == [{"Source": "MT", "Target": "机器翻译"}]
    assert core.parse_json_array('[1, 2] [3, 4]') == [1, 2]
    assert core.parse_json_array('不是 JSON') is None
    assert core.parse_json_array('') is None
    assert core.parse_json_array(None) is None
    print("  ✓ parse_json_array")


def test_misc_helpers():
    assert core.clean_xml_chars("a\x00b\x1fc") == "abc"
    assert core.clean_xml_chars(123) == "123"
    assert core.is_rate_limited(Exception("429 Too Many Requests"))
    assert core.is_rate_limited(Exception("RESOURCE_EXHAUSTED"))
    assert core.is_rate_limited(Exception("rate limit exceeded"))
    assert not core.is_rate_limited(Exception("boom"))
    assert core.call_llm("Nope", "k", "m", "s", "u") == ""
    assert core.file_job_id(b"x") == core.file_job_id(b"x")
    assert core.file_job_id(b"x") != core.file_job_id(b"y")
    print("  ✓ misc helpers")


def test_parse_translation_array():
    assert core.parse_translation_array('["a", "b"]', 2) == ["a", "b"]
    assert core.parse_translation_array('[{"translation": "甲"}, {"translation": "乙"}]', 2) == ["甲", "乙"]
    assert core.parse_translation_array('[{"target": "甲"}, {"text": "乙"}]', 2) == ["甲", "乙"]
    assert core.parse_translation_array('[{"译文": "甲"}, 42]', 1) is None
    assert core.parse_translation_array('{"1": "甲", "2": "乙"}', 2) == ["甲", "乙"]
    assert core.parse_translation_array('```json\n{"1": "甲"}\n```', 1) == ["甲"]
    assert core.parse_translation_array('1. 甲\n2. 乙', 2) == ["甲", "乙"]
    assert core.parse_translation_array('以下是译文：\n1、甲\n2、乙', 2) == ["甲", "乙"]
    assert core.parse_translation_array('1. “单段译文。”', 1) == ["“单段译文。”"]
    assert core.parse_translation_array('裸文本译文', 1) == ["裸文本译文"]
    assert core.parse_translation_array('["a"]', 2) is None
    assert core.parse_translation_array("普通文本", 2) is None
    assert core.parse_translation_array(None, 1) is None
    print("  ✓ parse_translation_array（数组/对象/降级）")


def test_doc_generation():
    for buf in (core.paragraphs_to_word(["段落一"]),
                core.pairs_to_word([{"source": "a", "target": "b"}]),
                core.markdown_to_word("# 标题\n\n**加粗** 正文\n\n- 列表项", "目的论")):
        assert buf.getvalue().startswith(b"PK"), "生成的 docx 应为有效 zip"
    assert core.dict_to_excel({"MT": "机器翻译"}).getvalue().startswith(b"PK")
    print("  ✓ docx / xlsx 生成")


def test_docx_fonts():
    import zipfile
    buf = core.pairs_to_word([{"source": "Hello 世界", "target": "你好 world"}])
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        xml = z.read("word/document.xml").decode("utf-8")
        styles = z.read("word/styles.xml").decode("utf-8")
    assert "Times New Roman" in styles, "默认西文字体应为 Times New Roman"
    assert "宋体" in styles, "默认中文字体应为宋体"
    assert "Times New Roman" in xml and "宋体" in xml, "表格 run 也应带字体声明"
    print("  ✓ docx 默认字体（Times New Roman + 宋体）")


def test_find_span():
    text = "The “quick” brown–fox jumps.  And runs."
    assert core._find_span(text, "“quick”") == (4, 11)
    assert core._find_span(text, '"quick"') == (4, 11), "弯引号应可匹配"
    assert core._find_span(text, "brown–fox") == (12, 21)
    assert core._find_span(text, "brown-fox") == (12, 21), "破折号应可匹配"
    assert core._find_span(text, "jumps. And") == (22, 33), "空白应可折叠匹配"
    assert core._find_span(text, "不存在") is None
    print("  ✓ 标注片段宽容定位（引号/破折号/空白）")


def test_compose_spans():
    # 难点句整段 + 词级标注重叠：边界切分，rare 覆盖 hard
    spans = [(0, 20, "hard"), (4, 10, "rare"), (10, 14, "domain")]
    out = core._compose_spans(spans, 20)
    assert out == [(0, 4, "hard"), (4, 10, "rare"), (10, 14, "domain"), (14, 20, "hard")], out
    assert core._compose_spans([(1, 5, "rare")], 8) == [(1, 5, "rare")]
    assert core._compose_spans([], 8) == []
    print("  ✓ 高亮区间合成（优先级覆盖 + 边界切分）")


def test_annotate_stage():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-annot-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        state = {
            "filename": "a.pdf", "p1_done": True, "p2_done": True,
            "paras": [], "pairs": [
                {"source": "The Mirage was an obsolete aircraft by then. The cacophony of the engines was unbearable.",
                 "target": "到那时，幻影战斗机已经过时了。发动机的刺耳噪声令人难以忍受。"},
                {"source": "He refused to kowtow to the bureaucracy.",
                 "target": "他拒绝向官僚作风屈膝。"},
            ],
            "auto_terms": {"Mirage": "幻影战斗机"},
            "findings": [], "review_stats": {},
        }

        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "翻译教学专家" in system_prompt:
                return json.dumps([
                    {"seg": 1, "type": "domain", "src": "Mirage", "tgt": "幻影战斗机",
                     "note": "机型专名译法"},
                    {"seg": 1, "type": "rare", "src": "cacophony", "tgt": "刺耳噪声",
                     "note": "生僻词"},
                    {"seg": 1, "type": "hard", "src": "was an obsolete aircraft by then",
                     "tgt": "到那时，幻影战斗机已经过时了",
                     "note": "语序调整"},
                    {"seg": 2, "type": "rare", "src": "kowtow", "tgt": "屈膝",
                     "note": "文化负载词"},
                    {"seg": 9, "type": "rare", "src": "x", "tgt": "y", "note": "越界应丢弃"},
                ])
            return "[]"

        core.call_llm = llm
        glossary = core.normalize_glossary(
            [{"source": k, "target": v, "behavior": "translate", "status": "provisional"}
             for k, v in state["auto_terms"].items()])
        core.annotate_stage(state, "an0000000000000001", glossary, "DeepSeek", "k",
                            "deepseek-chat", "简体中文")
        ann = state["annotations"]
        assert state["annotations_done"] is True
        assert 0 in ann and 1 in ann
        types0 = {it["type"] for it in ann[0]}
        assert types0 == {"domain", "rare", "hard"}, types0
        assert ann[0][0]["src_span"] == [4, 10], "Mirage 应定位在原文中"
        assert ann[1][0]["src_span"] is not None and ann[1][0]["tgt_span"] is not None
        # 术语表确定性覆盖 + 数量上限
        assert any(it["type"] == "domain" for it in ann[0])
        assert len(ann[0]) <= 6
        # JSON 落盘后键为字符串：从磁盘加载再渲染，三种颜色都应出现
        import zipfile
        state_disk = core.load_job_state("an0000000000000001")
        buf = core.pairs_to_word(state_disk["pairs"],
                                 annotations=state_disk.get("annotations"))
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        for color in ("C00000", "BF8F00", "008080"):
            assert f'w:val="{color}"' in xml, f"缺少颜色 {color}"
        assert "图例" in xml
        print("  ✓ 三色自动标注（LLM + 术语表覆盖 + 区间定位 + docx 渲染）")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_annotation_filters():
    # 常用词判定（含词形还原）
    assert core._is_common_word("production")
    assert core._is_common_word("grin")
    assert core._is_common_word("rooster")
    assert core._is_common_word("speedily"), "speedily 应还原为 speedy 判为常用"
    assert core._is_common_word("grinning"), "grinning 应还原为 grin"
    assert core._is_common_word("elementary")
    assert not core._is_common_word("chicory")
    assert not core._is_common_word("muezzin")

    freq = {"chicory": 1, "grin": 20, "speedily": 2}
    assert core._rare_ok("Chicory", freq)
    assert not core._rare_ok("grin", freq), "常用词 + 高频出现都不算生僻"
    assert not core._rare_ok("Production", freq)
    assert not core._rare_ok("Speedily", freq), "speedily 是常用词 speedy 的副词形式"
    assert not core._rare_ok("Elementary, my dear Watson", freq), "短语/名句不算生僻词"
    assert not core._rare_ok("muezzin", {"muezzin": 20}), "全书反复出现不算生僻"

    assert core._domain_ok("Spastic Bronchitis")
    assert core._domain_ok("War of Attrition")
    assert not core._domain_ok("Grandma Sarah and Grandpa Yaakov")
    assert not core._domain_ok("Translation from Hebrew"), "全常用词短语不算专业名词"

    # 术语表覆盖的 domain 不过滤（note 以"术语："开头）
    pairs = [
        {"source": "Compost is good for the soil. The chicory bloomed in spring.",
         "target": "堆肥对土壤有益。春天菊苣开花了。"},
        {"source": "Translation from Hebrew by the author.",
         "target": "由作者自希伯来语译出。"},
    ]
    ann = {
        0: [
            {"type": "domain", "src_span": [0, 7], "tgt_span": [0, 2],
             "note": "术语：Compost -> 堆肥"},
            {"type": "rare", "src_span": [34, 41], "tgt_span": [13, 15],
             "note": "生僻词"},
            {"type": "rare", "src_span": [53, 59], "tgt_span": [19, 21],
             "note": "滥标常用词"},
        ],
        1: [
            {"type": "domain", "src_span": [0, 23], "tgt_span": [6, 9],
             "note": "LLM 滥标"},
        ],
    }
    cleaned = core._clean_annotations(ann, pairs)
    types0 = [it["type"] for it in cleaned[0]]
    assert types0 == ["domain", "rare"], types0  # 术语覆盖保留，chicory 保留，production 被挡
    assert cleaned[0][0]["note"].startswith("术语：")
    assert 1 not in cleaned, "全常用词短语 domain 应被过滤"
    print("  ✓ 标注确定性过滤（常用词表/词形还原/称谓/全常用词短语/术语表豁免）")


def test_termbase_parsing():
    buf = core.dict_to_excel({"MT": "机器翻译", "CAT": "计算机辅助翻译"})
    entries = core.normalize_glossary(core.parse_termbase(buf))
    assert len(entries) == 2
    assert all(e["behavior"] == "translate" and e["status"] == "provisional" for e in entries)

    # 概念化列：Behavior / Status / Preferred / Forbidden
    buf2 = io.BytesIO()
    import pandas as pd
    pd.DataFrame([
        {"Source": "Skopos", "Target": "目的论", "Behavior": "translate", "Status": "locked",
         "Preferred": "目的论", "Forbidden": "功能对等;目的学派"},
        {"Source": "John Smith", "Target": "约翰·史密斯", "Behavior": "preserve", "Status": "locked"},
    ]).to_excel(buf2, index=False)
    buf2.seek(0)
    entries2 = core.normalize_glossary(core.parse_termbase(buf2))
    assert entries2[0]["status"] == "locked"
    assert entries2[0]["forbidden"] == ["功能对等", "目的学派"]
    assert entries2[1]["behavior"] == "preserve"

    try:
        core.parse_termbase(io.BytesIO(b"not an excel"))
        raise AssertionError("应抛出 ValueError")
    except ValueError:
        pass
    print("  ✓ 术语库解析（概念化条目 + 锁定/禁止译名）")


def test_glossary_and_checks():
    g = core.normalize_glossary([
        {"source": "Skopos", "target": "目的论", "status": "locked", "forbidden": ["功能对等"]},
        {"source": "John Smith", "target": "约翰·史密斯", "behavior": "preserve", "status": "locked"},
        {"source": "MT", "target": "机器翻译"},
        {"source": "", "target": "x"},
        "garbage",
    ])
    assert len(g) == 3
    assert g[0]["status"] == "locked" and g[0]["preferred"] == "目的论"
    assert g[1]["behavior"] == "preserve"
    assert g[2]["status"] == "provisional"
    assert core.glossary_to_terms(g) == {"Skopos": "目的论", "MT": "机器翻译"}
    block = core.glossary_block(g)
    assert "Skopos -> 目的论" in block and "功能对等" in block
    assert "John Smith" in block

    src = "价格 %s 元，详见 https://example.com/ref，引用 [12]。John Smith 提出了 Skopos 理论。"
    tgt = "价格 元，详见 见文档，引用 12。约翰·史密斯提出了功能对等理论。"
    fs = core.check_translation_batch([src], [tgt], g, "简体中文")
    assert any(f["severity"] == "blocking" for f in fs), "占位符丢失应为 blocking"
    assert any("https://example.com/ref" in f["reason"] for f in fs)
    assert any("John Smith" in f["reason"] for f in fs)
    assert any("Skopos" in f["reason"] for f in fs)
    assert any("功能对等" in f["reason"] for f in fs)

    fs2 = core.check_translation_batch(
        ["Theoretical Framework 理论框架"], ["理论框架 Theoretical Framework"], [], "简体中文")
    assert any("Theoretical" in f["reason"] for f in fs2), "应检测到源语残留"
    fs3 = core.check_translation_batch(
        ["理论框架"], ["Theoretical Framework 理论"], [], "English")
    assert any("理论" in f["reason"] for f in fs3)

    fs4 = core.check_translation_batch(["abc"], [""], [], "简体中文")
    assert fs4[0]["severity"] == "blocking" and "为空" in fs4[0]["reason"]
    print("  ✓ 概念化术语表 + 确定性检查（占位符/保留项/残留/锁定合规）")


def test_batches():
    assert core.make_batches(["a", "b", "c", "d", "e", "f"]) == [["a", "b", "c", "d"], ["e", "f"]]
    assert core.make_batches(["x" * 900, "y" * 900, "z"]) == [["x" * 900], ["y" * 900, "z"]]
    assert core.make_batches(["x" * 900, "y" * 1700, "z"]) == [["x" * 900], ["y" * 1700], ["z"]]
    print("  ✓ 语义批次")


def _make_pdf():
    """构造一个带缩进段落、连字符换行、跨页段落、页码与对白行的小 PDF。"""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    body_x, indent_x = 72, 84
    page.insert_text((indent_x, 72), "Chapter One", fontsize=11)
    page.insert_text((indent_x, 100), "The quick brown fox jumps over the lazy dog while the kit-", fontsize=11)
    page.insert_text((body_x, 114), "ten slept on the mat, completely unaware of the world around", fontsize=11)
    page.insert_text((body_x, 128), "and humming a quiet tune that drifted softly through", fontsize=11)
    page.insert_text((body_x, 160), "*", fontsize=11)  # 章节分隔装饰符
    page.insert_text((306, 780), "1", fontsize=9)
    page2 = doc.new_page()
    page2.insert_text((body_x, 72), "the empty rooms of the old house.", fontsize=11)
    page2.insert_text((indent_x, 100), '"What are you doing?" she asked, looking up from the book.', fontsize=11)
    page2.insert_text((indent_x, 128), '"Nothing much," he replied with a shrug.', fontsize=11)
    page2.insert_text((body_x, 160), "* * *", fontsize=11)
    page2.insert_text((306, 780), "2", fontsize=9)
    buf = io.BytesIO(doc.tobytes())
    doc.close()
    return buf.getvalue()


def test_pdf_extraction():
    paras = core.extract_pdf_paragraphs(_make_pdf())
    joined = "\n".join(paras)
    assert any("kitten slept" in p for p in paras), "连字符换行应修复为 kitten"
    assert not any(p.strip() in ("1", "2") for p in paras), "独立页码应被剔除"
    assert any(p.startswith('"What are you doing?"') for p in paras), "对白应为独立段落"
    assert any(p.startswith('"Nothing much,"') for p in paras), "对白换段应保持独立"
    assert any("softly through the empty rooms" in p for p in paras), "跨页未完结段落应合并"
    assert not any(p.strip() == "*" or p.strip() == "* * *" for p in paras), \
        "纯符号装饰行（*）应被剔除"
    assert not any(p[:1].islower() for p in paras), "不应残留小写开头的碎句"
    assert "Chapter One" in joined
    print("  ✓ PDF 确定性段落提取（缩进分段/连字符/跨页合并/页码剔除/碎片兜底）")


def test_symbol_segment_passthrough_and_tm_gate():
    assert not core._tm_eligible("*", "我脸红了。")
    assert not core._tm_eligible("— — —", "某某译文")
    assert not core._tm_eligible("* * * *", "某某译文")
    assert not core._tm_eligible("◇◇◇", "某某译文")
    assert core._tm_eligible("I blushed.", "我脸红了。")
    assert not core._tm_eligible("hello", "")

    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-sym-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        docx_bytes = _make_docx(["OK.", "* * * *", "◇◇◇", "这是长段落。"])

        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "术语管理专家" in system_prompt:
                return '[]'
            if "翻译审校专家" in system_prompt:
                return '[]'
            if "学术翻译专家" in system_prompt:
                return json.dumps([f"译文：{s}" for s, _ in _numbered_sources(user_prompt)])
            return "报告章节内容。"

        core.call_llm = llm
        state = core.run_job_pipeline(
            "sy0000000000000001", "s.docx", docx_bytes,
            provider="DeepSeek", api_key="k", model="deepseek-chat",
            target_lang="简体中文", auto_term=False, enable_report=False,
            translation_theory="目的论 (Skopos Theory)", user_glossary=[])
        assert [p["source"] for p in state["pairs"]] == ["OK.", "◇◇◇", "这是长段落。"], \
            "装饰行应剔除，短段保留，非装饰纯符号段直通"
        assert state["pairs"][1]["target"] == "◇◇◇", "纯符号段应原样保留，不调模型"
        tm = core.load_tm()
        assert "◇◇◇" not in tm, "纯符号段不应进入翻译记忆"
        assert len(tm) == 2, "只有 OK. 与长段落入 TM"
        print("  ✓ 纯符号段直通 + 翻译记忆资格门槛")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_tm_sanitize_on_load():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-tmsan-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        poison = {
            "*": {"target": "我脸红了。", "reviewed": True},          # 无字母源文
            "hello": {"target": "你好", "reviewed": True},            # 合格
            "good": {"target": "", "reviewed": True},                 # 空译文
            "bad": {"target": "糟糕", "reviewed": False},             # 未过审校
            "nonsense": "不是字典",                                   # 结构非法
        }
        core.save_tm(poison)
        tm = core.load_tm()
        assert tm == {"hello": {"target": "你好", "reviewed": True}}, tm
        print("  ✓ 翻译记忆加载自清洗（污染条目自动剔除）")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_annotations_normalize_and_bounds():
    ann = {"0": [{"type": "rare", "src_span": [0, 4], "tgt_span": [0, 2]}],
           3: [{"type": "hard", "src_span": [0, 4], "tgt_span": [0, 2]}],
           "x": [{"type": "domain"}], "999": [{"type": "rare", "src_span": [0, 4],
                                               "tgt_span": [0, 2]}],
           "5": "不是列表"}
    norm = core._normalize_annotations(ann)
    assert set(norm) == {0, 3, 999}, "归一化只处理键类型与非列表值"
    pairs = [{"source": "abcd", "target": "一二"}] * 4
    cleaned = core._clean_annotations(norm, pairs)
    assert set(cleaned) == {0, 3}, "越界键 999 应被丢弃"
    print("  ✓ 标注键归一化 + 越界保护")


def test_annotate_resume_by_offset():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-annres-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        pairs = [{"source": f"The quick brown fox jumps over the lazy dog number {i}.",
                  "target": f"第{i}句的译文，内容足够长。"} for i in range(25)]
        state = {"filename": "r.pdf", "p1_done": True, "p2_done": True, "paras": [],
                 "pairs": pairs, "auto_terms": {}, "findings": [], "review_stats": {},
                 "annotations": {"0": [{"type": "hard", "src_span": [0, 10],
                                        "tgt_span": [0, 3], "note": "预置"}]},
                 "annotations_done_offset": 10}
        calls = {"n": 0}

        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "翻译教学专家" in system_prompt:
                calls["n"] += 1
                return json.dumps([{"seg": 1, "type": "hard", "src": "The quick brown fox",
                                    "tgt": "第0句的译文", "note": "x"}])
            return "[]"

        core.call_llm = llm
        core.annotate_stage(state, "ar0000000000000001", [], "DeepSeek", "k",
                            "deepseek-chat", "简体中文")
        assert calls["n"] == 2, f"应从第 10 段后续跑（2 批），实际 {calls['n']} 批"
        assert state["annotations_done"] is True
        assert state["annotations_done_offset"] == 25
        assert state["annotations"][0][0]["note"] == "预置", "已标注段不应被覆盖"
        assert len(state["annotations"]) >= 2
        print("  ✓ 标注断点按段偏移续跑（批大小变化不串位）")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_completeness_check():
    long_src = "The flight course lasted only twenty months. " * 6  # >120 字符
    assert core.is_incomplete_translation(long_src, "一句话。")
    assert not core.is_incomplete_translation(long_src, "译" * 100)
    assert core.is_incomplete_translation("短句", ""), "空译文恒为不完整"
    # 实测案例：完整但凝练的译文不应误报
    legal = ("All rights reserved; No parts of this book may be reproduced or transmitted "
             "in any form or by any means, electronic or mechanical, including photocopying, "
             "recording, taping, or by any information storage and retrieval system, "
             "without permission in writing from the publisher.")
    assert not core.is_incomplete_translation(
        legal, "保留所有权利；未经出版方书面许可，本书任何部分不得以任何形式或任何方式"
               "（电子或机械，包括影印、录制、磁带或任何信息存储检索系统）复制或传播。")
    dialogue = ('"What mud?" I asked. "It was summer."')
    assert not core.is_incomplete_translation(dialogue, '"什么泥？"我问。"那是夏天。"')
    # 实测案例：2 句原文只译 1 句 => 截断
    two_sent = ("When Kibbutz Geva celebrated forty years, Grandpa took me on a compost tour "
                "of the kibbutzim. I believe he was one of the first farmers in the country "
                "to understand the great benefits of organic fertilization and the dangers "
                "of chemical fertilizers.")
    assert core.is_incomplete_translation(
        two_sent, "当基布兹格瓦庆祝成立四十周年时，祖父带我参加了一次对各基布兹的堆肥考察。")
    fs = core.check_translation_batch([long_src], ["一句话。"], [], "简体中文")
    assert any(f["severity"] == "blocking" and "漏译" in f["reason"] for f in fs), \
        "截断译文应判 blocking"
    fs_ok = core.check_translation_batch([long_src], ["译" * 100], [], "简体中文")
    assert not any("漏译" in f["reason"] for f in fs_ok)
    print("  ✓ 译文完整性检查（截断判 blocking）")


def test_review_truncated_suggestion_rollback():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-trunc-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        long_para = "The squadron prepared for the long-range mission. " * 5  # >120 字符
        docx_bytes = _make_docx([long_para])

        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "术语管理专家" in system_prompt:
                return '[]'
            if "翻译审校专家" in system_prompt:
                return json.dumps([
                    {"segment_index": 0, "severity": "actionable", "reason": "术语应统一",
                     "suggested_target": "只修正了一句。"}])
            if "学术翻译专家" in system_prompt:
                return json.dumps(["译" * 100])
            return "报告章节内容。"

        core.call_llm = llm
        state = core.run_job_pipeline(
            "tr0000000000000001", "t.docx", docx_bytes,
            provider="DeepSeek", api_key="k", model="deepseek-chat",
            target_lang="简体中文", auto_term=False, enable_report=False,
            translation_theory="目的论 (Skopos Theory)", user_glossary=[])
        assert state["pairs"][0]["target"] == "译" * 100, \
            "截断的审校建议应被完整性复验拦截并回滚"
        assert any("suggested_target" in f for f in state["findings"]), \
            "被拦截的建议应记入 findings 供人工参考"
        print("  ✓ 审校截断建议 -> 完整性复验 -> 自动回滚")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_job_store():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-test-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        jid = "abcdef1234567890"
        assert core.load_job_state(jid) is None
        state = core.new_job_state("demo.pdf")
        state["paras"] = ["p1", "p2"]
        core.save_job_state(jid, state)
        loaded = core.load_job_state(jid)
        assert loaded["paras"] == ["p1", "p2"]
        assert loaded["filename"] == "demo.pdf"
        assert any(j["job_id"] == jid for j in core.list_jobs())
        assert core.progress_label(loaded) == "待处理"
        loaded.update(p1_done=True, p2_done=True, p3_done=True)
        assert core.progress_label(loaded) == "已完成"
        (core.job_dir(jid) / "state.json").write_text("{broken", encoding="utf-8")
        assert core.load_job_state(jid) is None
        core.delete_job(jid)
        assert core.load_job_state(jid) is None
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)
    print("  ✓ 任务持久化（落盘/读取/列出/删除）")


def _make_docx(texts):
    buf = io.BytesIO()
    doc = Document()
    for t in texts:
        doc.add_paragraph(t)
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _numbered_sources(user_prompt):
    """从翻译/修复 prompt 中提取编号段落（按序号排序）。"""
    segs = [(int(m.group(1)), m.group(2).strip())
            for m in re.finditer(r'^\s*(\d+)\.\s+(.+?)\s*$', user_prompt, re.M)]
    segs.sort(key=lambda x: x[0])
    return segs


def _fake_llm_factory():
    """返回 (fake_llm, calls)：术语/翻译/审校/报告均返回固定内容。"""
    calls = []

    def fake_llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
        calls.append(system_prompt[:10])
        if "术语管理专家" in system_prompt:
            return '[{"Source": "MT", "Target": "机器翻译"}, {"Source": "CAT", "Target": "计算机辅助翻译"}, 123, {"Source": null, "Target": "坏数据"}]'
        if "翻译审校专家" in system_prompt:
            return '[]'  # 审校无问题
        if "学术翻译专家" in system_prompt:
            return json.dumps([f"译文：{s}" for _, s in _numbered_sources(user_prompt)])
        return "这是报告章节内容，包含 **加粗** 与列表。\n\n- 要点一\n- 要点二"

    return fake_llm, calls


def test_e2e_pipeline():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-e2e-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        fake_llm, calls = _fake_llm_factory()
        core.call_llm = fake_llm
        docx_bytes = _make_docx(["这是第一段，涉及术语 MT。", "这是第二段，涉及术语 CAT。"])
        jid = "e2e0000000000001"
        state = core.run_job_pipeline(
            jid, "demo.docx", docx_bytes,
            provider="DeepSeek", api_key="test-key", model="deepseek-chat",
            target_lang="简体中文", auto_term=True, enable_report=True,
            translation_theory="目的论 (Skopos Theory)", user_glossary=[],
            research_settings={"report_stage": "proposal"})
        assert state["p1_done"] and len(state["paras"]) == 2
        assert state["auto_terms"] == {"MT": "机器翻译", "CAT": "计算机辅助翻译"}
        assert state["p2_done"] and len(state["pairs"]) == 2
        assert state["pairs"][0]["target"].startswith("译文：")
        assert state["pairs"][0]["reviewed"] is True, "审校通过段落应标记 reviewed"
        stats = state["review_stats"]
        assert stats["reviewed_segments"] == 2 and stats["batches_reviewed"] == 1
        assert stats["blocking"] == 0 and stats["actionable"] == 0
        assert state["has_blocking"] is False
        assert state["p3_done"] and len(re.findall(
            r"^## ", state["p3_md"], re.MULTILINE)) == 4
        # 审校通过的段落应已写入翻译记忆
        tm = core.load_tm()
        assert len(tm) == 2 and all(v["reviewed"] for v in tm.values())
        # 幂等：已完成任务再次运行不产生额外 LLM 调用
        n_before = len(calls)
        state2 = core.run_job_pipeline(
            jid, "demo.docx", None,
            provider="DeepSeek", api_key="test-key", model="deepseek-chat",
            target_lang="简体中文", auto_term=True, enable_report=True,
            translation_theory="目的论 (Skopos Theory)", user_glossary=[],
            research_settings={"report_stage": "proposal"})
        assert len(calls) == n_before
        assert state2["p3_md"] == state["p3_md"]
        assert core.load_source(jid) == docx_bytes
        print("  ✓ 端到端流水线（清洗/术语/批次翻译/审校/报告/幂等/TM 入库）")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_deterministic_repair():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-repair-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        docx_bytes = _make_docx(["请参考 https://example.com/ref 获取详细信息。"])

        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "术语管理专家" in system_prompt:
                return '[]'
            if "翻译审校专家" in system_prompt:
                return '[]'
            if "学术翻译专家" in system_prompt:
                if "以下译文未通过检查" in user_prompt:
                    targets = re.findall(r'^\s*译文：(.*)$', user_prompt, re.M)
                    return json.dumps([t.strip() + " https://example.com/ref" for t in targets])
                return json.dumps(["译文：请参考 获取详细信息。"])  # 故意丢失 URL
            return "报告章节内容。"

        core.call_llm = llm
        state = core.run_job_pipeline(
            "rp0000000000000001", "r.docx", docx_bytes,
            provider="DeepSeek", api_key="k", model="deepseek-chat",
            target_lang="简体中文", auto_term=False, enable_report=False,
            translation_theory="目的论 (Skopos Theory)", user_glossary=[])
        assert "https://example.com/ref" in state["pairs"][0]["target"], "自动修复应补回 URL"
        assert state["findings"] == []
        assert state["has_blocking"] is False
        print("  ✓ 确定性检查 -> 自动修复 -> 复验通过")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_review_fix_and_blocking():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-review-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        docx_bytes = _make_docx(["这是第一段，内容足够长以通过过滤。",
                                 "这是第二段，内容足够长以通过过滤。"])

        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "术语管理专家" in system_prompt:
                return '[]'
            if "这是盲审" in system_prompt:
                return '[]'
            if "翻译审校专家" in system_prompt:
                return json.dumps([
                    {"segment_index": 0, "severity": "actionable",
                     "category": "terminology_consistency",
                     "summary": "术语不一致",
                     "source_span": "第一段",
                     "target_span": "修正后的译文",
                     "explanation": "当前译法没有遵循项目术语约定。",
                     "recommendation": "对照术语表确认并统一译法。",
                     "confidence": 0.88,
                     "detector": "Semantic QA",
                     "reason": "术语不一致",
                     "suggested_target": "修正后的译文"},
                    {"segment_index": 1, "severity": "blocking",
                     "category": "semantic_accuracy",
                     "summary": "语义可能发生严重偏移",
                     "source_span": "第二段",
                     "target_span": "译文：这是第二段，内容足够长以通过过滤。",
                     "explanation": "当前译文可能改变原文的核心关系。",
                     "recommendation": "回到原文核对核心语义后再决定处理方式。",
                     "confidence": 0.92,
                     "detector": "Semantic QA",
                     "reason": "语义严重错误，需人工确认"},
                ])
            if "学术翻译专家" in system_prompt:
                return json.dumps([f"译文：{s}" for _, s in _numbered_sources(user_prompt)])
            return "报告章节内容。"

        core.call_llm = llm
        state = core.run_job_pipeline(
            "rv0000000000000001", "v.docx", docx_bytes,
            provider="DeepSeek", api_key="k", model="deepseek-chat",
            target_lang="简体中文", auto_term=False, enable_report=False,
            translation_theory="目的论 (Skopos Theory)", user_glossary=[])
        pairs = state["pairs"]
        assert pairs[0]["target"] == "修正后的译文", "actionable 建议应复验后应用"
        assert pairs[0]["reviewed"] is True
        assert pairs[1]["reviewed"] is False, "blocking 段落不应进入翻译记忆"
        assert len(state["findings"]) == 1
        assert state["findings"][0]["severity"] == "blocking"
        assert state["findings"][0]["type"] == "review"
        assert state["findings"][0]["explanation"]
        assert state["findings"][0]["recommendation"]
        assert state["has_blocking"] is True
        report = core.findings_report_md(state)
        assert "blocking" in report and "待处理问题" in report
        print("  ✓ 独立审校：actionable 修复 + blocking 留待确认 + 审查报告")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_tm_reuse():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-tm-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        docx_bytes = _make_docx(["这是第一段，内容足够长以通过过滤。",
                                 "这是第二段，内容足够长以通过过滤。"])
        counting = {"translate": 0, "review": 0}

        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "术语管理专家" in system_prompt:
                return '[]'
            if "翻译审校专家" in system_prompt:
                counting["review"] += 1
                return '[]'
            if "学术翻译专家" in system_prompt:
                counting["translate"] += 1
                return json.dumps([f"译文：{s}" for _, s in _numbered_sources(user_prompt)])
            return "报告章节内容。"

        core.call_llm = llm
        kwargs = dict(provider="DeepSeek", api_key="k", model="deepseek-chat",
                      target_lang="简体中文", auto_term=False, enable_report=False,
                      translation_theory="目的论 (Skopos Theory)", user_glossary=[])
        core.run_job_pipeline("tm0000000000000001", "a.docx", docx_bytes, **kwargs)
        assert counting["translate"] == 1, "任务 A 应翻译一个批次"
        state_b = core.run_job_pipeline("tm0000000000000002", "b.docx", docx_bytes, **kwargs)
        assert counting["translate"] == 1, "任务 B 应全部命中翻译记忆，不再调用翻译"
        assert state_b["tm_used_count"] == 2
        assert all(p["from_tm"] and p["reviewed"] for p in state_b["pairs"])
        print("  ✓ 翻译记忆：审校通过段落跨任务精确复用")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_resume_translation():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-resume-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        docx_bytes = _make_docx(["这是第一段，内容足够长以通过过滤。",
                                 "这是第二段，内容足够长以通过过滤。",
                                 "这是第三段，内容足够长以通过过滤。"])
        jid = "e2e0000000000002"

        def flaky_llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "学术翻译专家" in system_prompt:
                if "第二段" in user_prompt:
                    raise RuntimeError("模拟网络中断")
                return json.dumps([f"译文：{s}" for _, s in _numbered_sources(user_prompt)])
            if "术语管理专家" in system_prompt:
                return '[]'  # 空术语表
            if "翻译审校专家" in system_prompt:
                return '[]'
            return "报告章节内容。"

        core.call_llm = flaky_llm
        try:
            core.run_job_pipeline(
                jid, "demo.docx", docx_bytes,
                provider="DeepSeek", api_key="test-key", model="deepseek-chat",
                target_lang="简体中文", auto_term=True, enable_report=True,
                translation_theory="目的论 (Skopos Theory)", user_glossary=[],
                research_settings={"report_stage": "proposal"})
            raise AssertionError("应在批次翻译处抛出异常")
        except RuntimeError as e:
            assert "模拟网络中断" in str(e)

        mid = core.load_job_state(jid)
        assert mid["p1_done"] and len(mid["pairs"]) == 0, "失败的批次不应提交任何译文"
        assert any("术语抽取失败" in w for w in mid["warnings"])
        assert sum("术语抽取失败" in w for w in mid["warnings"]) == 1

        fake_llm, _ = _fake_llm_factory()
        core.call_llm = fake_llm
        state = core.run_job_pipeline(
            jid, "demo.docx", None,
            provider="DeepSeek", api_key="test-key", model="deepseek-chat",
            target_lang="简体中文", auto_term=True, enable_report=True,
            translation_theory="目的论 (Skopos Theory)", user_glossary=[],
            research_settings={"report_stage": "proposal"})
        assert state["p2_done"] and len(state["pairs"]) == 3
        assert state["pairs"][0]["target"] == "译文：这是第一段，内容足够长以通过过滤。"
        assert state["pairs"][1]["target"] == "译文：这是第二段，内容足够长以通过过滤。"
        assert state["p3_done"]
        print("  ✓ 批次翻译中断 -> 磁盘断点续传")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_resume_report_sections():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-report-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        docx_bytes = _make_docx(["这是第一段，内容足够长以通过过滤。"])
        jid = "e2e0000000000003"

        class FlakyReport:
            def __init__(self):
                self.report_calls = 0

            def __call__(self, provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
                if "学术翻译专家" in system_prompt:
                    return json.dumps([f"译文：{s}" for _, s in _numbered_sources(user_prompt)])
                if "术语管理专家" in system_prompt:
                    return '[]'
                if "翻译审校专家" in system_prompt:
                    return '[]'
                if "证据约束型学术写作者" in system_prompt:
                    self.report_calls += 1
                    if self.report_calls == 1:
                        raise RuntimeError("模拟报告中断")
                return "报告章节内容。"

        flaky = FlakyReport()
        core.call_llm = flaky
        try:
            core.run_job_pipeline(
                jid, "demo.docx", docx_bytes,
                provider="DeepSeek", api_key="test-key", model="deepseek-chat",
                target_lang="简体中文", auto_term=True, enable_report=True,
                translation_theory="目的论 (Skopos Theory)", user_glossary=[],
                research_settings={"report_stage": "proposal"})
            raise AssertionError("应在第一节处抛出异常")
        except RuntimeError as e:
            assert "学术写作阶段失败" in str(e)

        mid = core.load_job_state(jid)
        artifact_path = tmp / jid / "academic-sections.json"
        if artifact_path.is_file():
            partial = json.loads(artifact_path.read_text(encoding="utf-8"))
            assert len(partial["sections"]) == 0, "中断前不应写入未完成的 section"
        assert not mid["p3_done"]

        fake_llm, _ = _fake_llm_factory()
        core.call_llm = fake_llm
        state = core.run_job_pipeline(
            jid, "demo.docx", None,
            provider="DeepSeek", api_key="test-key", model="deepseek-chat",
            target_lang="简体中文", auto_term=True, enable_report=True,
            translation_theory="目的论 (Skopos Theory)", user_glossary=[],
            research_settings={"report_stage": "proposal"})
        assert state["p3_done"]
        artifact = json.loads((tmp / jid / "academic-sections.json").read_text(
            encoding="utf-8"))
        assert len(artifact["sections"]) == 4
        assert len(re.findall(r"^## ", state["p3_md"], re.MULTILINE)) == 4
        assert flaky.report_calls == 1, "首次中断应只调用一次未完成的 section"
        print("  ✓ 报告章节级断点续写")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_missing_source():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-missing-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        try:
            core.run_job_pipeline(
                "e2e0000000000004", "x.pdf", None,
                provider="DeepSeek", api_key="k", model="deepseek-chat",
                target_lang="简体中文", auto_term=True, enable_report=True,
                translation_theory="目的论 (Skopos Theory)", user_glossary=[])
            raise AssertionError("缺少源文件时应抛出 ValueError")
        except ValueError:
            pass
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)
    print("  ✓ 缺少源文件的防护")


if __name__ == "__main__":
    print("core 冒烟测试：")
    test_opencode_go_provider_route()
    test_parse_json_array()
    test_misc_helpers()
    test_parse_translation_array()
    test_doc_generation()
    test_docx_fonts()
    test_find_span()
    test_compose_spans()
    test_annotate_stage()
    test_annotation_filters()
    test_termbase_parsing()
    test_glossary_and_checks()
    test_batches()
    test_pdf_extraction()
    test_symbol_segment_passthrough_and_tm_gate()
    test_tm_sanitize_on_load()
    test_annotations_normalize_and_bounds()
    test_annotate_resume_by_offset()
    test_completeness_check()
    test_review_truncated_suggestion_rollback()
    test_job_store()
    test_e2e_pipeline()
    test_deterministic_repair()
    test_review_fix_and_blocking()
    test_tm_reuse()
    test_resume_translation()
    test_resume_report_sections()
    test_missing_source()
    print("\n全部通过 ✅")
