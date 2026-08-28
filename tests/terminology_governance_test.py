"""术语治理新增能力测试（阶段 1：数据模型 / 状态迁移 / 文档画像）。

运行方式（项目根目录）：python tests/terminology_governance_test.py
"""
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core
from transpraxis import document_profile, models, state_migration, terminology
from transpraxis import assets, delivery
from transpraxis import report_evidence


def test_document_profile_normalize_validate():
    raw = {
        "domain": "生物学",
        "subdomain": "行为生态学",
        "genre": "科普著作",
        "audience": "大众读者",
        "register": "半正式书面语",
        "style_constraints": "保留隐喻与叙事语气",
        "confidence": 0.8,
        "sections": [
            {"section_id": "s1", "start_segment": 0, "end_segment": 9,
             "topic": "引言", "domain": "生态学", "style": "叙事"},
            {"section_id": "bad", "start_segment": 9, "end_segment": 2,
             "topic": "非法区间应丢弃"},
            {"section_id": "s2", "start_segment": 10, "end_segment": 20,
             "topic": "实验方法", "domain": "行为学", "style": "说明"},
        ],
    }
    p = models.normalize_document_profile(raw)
    assert p["domain"] == "生物学"
    assert p["confidence"] == 0.8
    assert [s["section_id"] for s in p["sections"]] == ["s1", "s2"]
    assert models.validate_document_profile(p) == []

    # 垃圾输入 -> 全默认值，不抛异常
    p2 = models.normalize_document_profile("garbage")
    assert p2["domain"] == "" and p2["sections"] == []
    assert models.validate_document_profile(p2), "缺少 domain 应报问题"
    assert models.validate_document_profile(None)
    print("  ✓ DocumentProfile normalize/validate")


def test_profile_json_parse_and_degrades():
    # 合法 JSON 包裹在解释文字中也能解析
    ok = '好的：\n```json\n{"domain": "历史学", "confidence": 0.7, "sections": []}\n```'
    parsed = document_profile._parse_profile_json(ok)
    assert parsed and parsed["domain"] == "历史学"
    assert document_profile._parse_profile_json("不是 JSON") is None

    # 失败必须返回 warning + None，不能静默伪造
    paras = [f"第{i}段生物学文本。" for i in range(30)]

    def bad_llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
        return "抱歉，我无法完成这个任务。"

    profile, warnings = document_profile.profile_document(
        paras, "DeepSeek", "k", "deepseek-chat", call_llm=bad_llm)
    assert profile is None
    assert warnings and any("文档画像失败" in w for w in warnings)

    # 空文本 -> 失败 warning
    profile2, warnings2 = document_profile.profile_document([], "DeepSeek", "k", "m",
                                                            call_llm=bad_llm)
    assert profile2 is None and warnings2

    # 合法输出 -> 画像成功
    def good_llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
        return json.dumps({"domain": "动物行为学", "subdomain": "鸟类学",
                           "genre": "回忆录", "audience": "成人读者",
                           "register": "文学性书面语", "style_constraints": "保留诗意比喻",
                           "confidence": 0.9, "sections": []})

    profile3, warnings3 = document_profile.profile_document(
        paras, "DeepSeek", "k", "deepseek-chat", call_llm=good_llm)
    assert profile3 is not None and profile3["domain"] == "动物行为学"
    assert not any("失败" in w for w in warnings3)
    print("  ✓ 画像 JSON 解析 / 失败降级 / 成功校验")


def test_distributed_sample_covers_head_middle_tail():
    paras = [f"paragraph-{i}" for i in range(100)]
    wins = document_profile.distributed_sample(paras, n_windows=3, chars_per_window=10)
    assert len(wins) == 3
    starts = [w["start_segment"] for w in wins]
    assert starts[0] == 0, "必须覆盖开头"
    assert starts[-1] <= 99 and wins[-1]["end_segment"] == 99, "必须覆盖结尾"
    # 中间窗口确实落在中间区域（而不是只取开头）
    assert wins[1]["start_segment"] > 0
    assert any(40 <= w["start_segment"] <= 60 for w in wins)
    # 每窗口都带文本且字符不超上限太多
    for w in wins:
        assert w["text"]
        assert len(w["text"]) <= 10 * 3, "窗口文本应受字符上限约束"

    # 段落很少时退化为单窗口全量采样
    small = document_profile.distributed_sample(["a", "b"])
    assert len(small) == 1 and small[0]["start_segment"] == 0
    assert document_profile.distributed_sample([]) == []
    print("  ✓ 分布式采样覆盖首/中/尾")


def test_glossary_entry_normalize_excel_compat():
    raw = {"Source": "Skopos", "Target": "目的论", "Behavior": "translate",
           "Status": "locked", "Preferred": "目的论", "Forbidden": "功能对等;目的学派",
           "Scope": "global", "Note": "核心理论", "occurrences": [0, 3, 7, 3, "x"]}
    e = models.normalize_glossary_entry(raw)
    assert e["source"] == "Skopos" and e["status"] == "locked"
    assert e["forbidden"] == ["功能对等", "目的学派"]
    assert e["occurrences"] == [0, 3, 7], "occurrences 应去重排序并丢弃非法值"
    assert e["id"].startswith("t-")
    # 相同内容 -> 相同 ID
    assert models.entry_id("Skopos", "目的论", "translate") == e["id"]
    assert models.normalize_glossary_entry(None) is None
    assert models.normalize_glossary_entry({"Source": "  "}) is None
    print("  ✓ GlossaryEntry normalize（Excel 列兼容 + occurrences 归一）")


def test_evidence_no_fake_url():
    # model_knowledge 不允许带 URL：自动清除并注明
    ev = models.normalize_evidence(
        {"evidence_type": "model_knowledge", "url": "https://fake.example/x",
         "note": "模型知识"})
    assert ev["evidence_type"] == "model_knowledge"
    assert ev["url"] == ""
    assert "伪造" in ev["note"]
    assert models.validate_evidence(ev) == []

    # external 必须有真实来源 URL；没有 -> 降级为 model_knowledge
    ev2 = models.normalize_evidence(
        {"evidence_type": "external", "source_name": "某外部工具", "url": ""})
    assert ev2["evidence_type"] == "model_knowledge"
    assert ev2["url"] == "" and "降级" in ev2["note"]

    # 真实外部来源 -> 保留 URL
    ev3 = models.normalize_evidence(
        {"evidence_type": "external", "source_name": "termbase.io",
         "url": "https://termbase.io/term/123"})
    assert ev3["evidence_type"] == "external"
    assert ev3["url"].startswith("https://termbase.io")
    assert models.validate_evidence(ev3) == []

    # 非法类型 -> model_knowledge
    ev4 = models.normalize_evidence({"evidence_type": "瞎编", "url": "https://x"})
    assert ev4["evidence_type"] == "model_knowledge" and ev4["url"] == ""
    print("  ✓ 证据模型：model_knowledge 禁伪造 URL / external 来源约束")


def test_glossary_hash_deterministic():
    a = [{"source": "Skopos", "target": "目的论", "status": "locked"},
         {"source": "John Smith", "target": "约翰·史密斯", "behavior": "preserve",
          "status": "locked"}]
    b = [{"source": "John Smith", "target": "约翰·史密斯", "behavior": "preserve",
          "status": "locked"},
         {"source": "Skopos", "target": "目的论", "status": "locked"}]
    ha = models.glossary_hash(a)
    hb = models.glossary_hash(b)
    assert ha == hb, "条目顺序变化不应改变 glossary_hash"
    assert len(ha) == 64
    # 内容变化 -> 哈希变化
    c = [{"source": "Skopos", "target": "翻译目的论", "status": "locked"},
         {"source": "John Smith", "target": "约翰·史密斯", "behavior": "preserve",
          "status": "locked"}]
    assert models.glossary_hash(c) != ha

    fg = models.normalize_frozen_glossary(
        {"version": 1, "source_hash": "abc", "entries": a,
         "frozen_at": "2026-08-06T00:00:00", "frozen_by": "tester"})
    assert fg["glossary_hash"] == ha
    assert models.validate_frozen_glossary(fg) == []
    assert models.validate_frozen_glossary(None)
    # 篡改条目 -> 校验失败
    fg2 = dict(fg)
    fg2["entries"] = models.normalize_glossary(c)
    assert models.validate_frozen_glossary(fg2)
    print("  ✓ 冻结术语表哈希确定性 + 篡改校验")


def test_state_migration_old_job():
    # 模拟旧版本 state.json（只有旧字段）
    old = {
        "filename": "book.pdf",
        "p1_done": True,
        "p2_done": False,
        "p3_done": False,
        "report_enabled": True,
        "paras": ["a", "b"],
        "pairs": [],
        "auto_terms": {"MT": "机器翻译"},
        "findings": [],
        "review_stats": {},
        "tm_used_count": 0,
        "has_blocking": False,
        "warnings": [],
        "annotations_done": False,
    }
    m = state_migration.migrate_state(old)
    assert m["stage"] in ("TERMS_PREPARED", "PROFILED"), m["stage"]
    assert m["delivery_status"] == "draft"
    assert m["glossary_frozen"] is None, "旧任务不得虚假标记为已冻结"
    assert m["document_profile"] is None
    assert m["glossary"] == [] and m["auto_term_entries"] == []
    assert m["human_actions"] == []
    assert m["p1_done"] is True, "旧字段不得被改动"

    # 翻译完成但有 blocking -> review_required
    old2 = dict(old, p2_done=True, p3_done=True, has_blocking=True)
    m2 = state_migration.migrate_state(old2)
    assert m2["delivery_status"] == "review_required"
    assert m2["stage"] == "REVIEW_REQUIRED"

    # 全部完成且无 blocking -> 保持 draft，绝不自动 final
    old3 = dict(old, p2_done=True, p3_done=True, has_blocking=False,
                annotations_done=True)
    m3 = state_migration.migrate_state(old3)
    assert m3["delivery_status"] == "draft"
    assert m3["stage"] == "REPORT_GENERATED"

    # 显式 final 不被覆盖
    old4 = dict(old, delivery_status="final")
    assert state_migration.migrate_state(old4)["delivery_status"] == "final"
    print("  ✓ 旧 state 迁移（默认值 / stage / delivery / 不伪造冻结）")


def test_core_load_job_state_migrates():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-mig-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        jid = "mig00000000000001"
        d = core.job_dir(jid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(json.dumps(
            {"filename": "old.pdf", "p1_done": True, "p2_done": True, "p3_done": True,
             "auto_terms": {}}), encoding="utf-8")
        state = core.load_job_state(jid)
        assert state is not None
        assert state["stage"] == "REPORT_GENERATED"
        assert state["delivery_status"] == "draft"
        assert state["glossary_frozen"] is None
        # 新任务默认字段齐全
        ns = core.new_job_state("new.pdf")
        for key in ("stage", "delivery_status", "document_profile", "glossary",
                    "glossary_frozen", "human_actions"):
            assert key in ns
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)
    print("  ✓ core.load_job_state 迁移 + new_job_state 新字段")


def test_term_matches_word_boundary():
    assert terminology.term_matches("Skopos", "The Skopos theory is central.")
    assert terminology.term_matches("skopos", "The SKOPOS theory is central."), "大小写不敏感"
    assert terminology.term_matches("MT", "MT is machine translation.")
    assert not terminology.term_matches("MT", "The MTI tool translates books."), \
        "短词不得在更长词内部误命中"
    assert not terminology.term_matches("AI", "The mountain is high in the main range."), \
        "AI 不得命中 MAIN/mountain 等普通词"
    assert terminology.term_matches("AI", "The AI model works.")
    assert terminology.term_matches("目的论", "翻译目的论是核心概念。"), "CJK 术语按子串匹配"
    assert not terminology.term_matches("", "text")
    assert not terminology.term_matches("x", None)
    print("  ✓ 术语匹配（大小写 + 词边界 + CJK + 短词防误命中）")


def test_find_occurrences_all_segments():
    paras = [
        "The Skopos theory guides the translation.",
        "This chapter discusses Skopos and fidelity.",
        "No term here.",
        "SKOPOS appears again at the end.",
    ]
    occ = terminology.find_occurrences("Skopos", paras)
    assert occ == [0, 1, 3], "必须记录全部出现位置，而不是只记第一次"
    assert terminology.find_occurrences("不存在的术语", paras) == []
    assert terminology.find_occurrences("MT", ["MTI is a tool"]) == [], "短词不应命中 MTI"
    print("  ✓ occurrences 记录全部 segment_id")


def test_extract_auto_terms_v2():
    paras = [f"第{i}段：The Skopos theory and the fidelity principle 是本章核心。"
             for i in range(12)]
    profile = models.normalize_document_profile(
        {"domain": "翻译学", "confidence": 0.8, "sections": []})
    calls = {"n": 0}

    def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
        calls["n"] += 1
        return json.dumps([
            {"Source": "Skopos theory", "Target": "目的论"},
            {"Source": "fidelity principle", "Target": "忠实原则"},
            {"Source": "Skopos theory", "Target": "翻译目的论", "domain": "翻译学"},
            {"Source": "MT", "Target": "机器翻译"},   # 短词但仍合法
            123,
            {"Source": None, "Target": "坏数据"},
        ])

    entries, warnings = terminology.extract_auto_terms_v2(
        paras, "简体中文", "DeepSeek", "k", "deepseek-chat",
        document_profile=profile, call_llm=llm)
    assert calls["n"] == 1
    assert warnings == []
    by_source = {e["source"]: e for e in entries}
    assert "Skopos theory" in by_source and "fidelity principle" in by_source
    # 去重：同 source 只保留一条，occurrences 取并集
    assert by_source["Skopos theory"]["target"] == "目的论", "保留首次译名"
    assert by_source["Skopos theory"]["occurrences"] == list(range(12)), \
        "重复候选应合并全部 occurrence"
    # 垃圾条目被丢弃；candidate 状态；evidence 为 model_knowledge 且无 URL
    assert "MT" in by_source and len(by_source) == 3
    assert all(e["status"] == "candidate" for e in entries), "自动术语不得自动 locked"
    assert all(e["evidence"][0]["evidence_type"] == "model_knowledge" for e in entries)
    assert all(not e["evidence"][0]["url"] for e in entries), "model_knowledge 禁 URL"
    assert by_source["Skopos theory"]["domain"] == "翻译学", "domain 来自画像/模型"
    assert all(e["scope"] == "document" for e in entries)

    # 失败：返回垃圾 -> warning，不静默宣称成功
    def bad_llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
        return "很抱歉，我无法输出 JSON。"

    entries2, warnings2 = terminology.extract_auto_terms_v2(
        paras, "简体中文", "DeepSeek", "k", "m", call_llm=bad_llm)
    assert entries2 == [] and any("术语抽取失败" in w for w in warnings2)
    print("  ✓ 分布式术语抽取（去重 / 全量 occurrences / candidate / 证据 / 失败 warning）")


def _make_docx(texts):
    import io
    from docx import Document
    buf = io.BytesIO()
    doc = Document()
    for t in texts:
        doc.add_paragraph(t)
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def test_review_state_persist_and_restore():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-termstate-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        docx_bytes = _make_docx(["The Skopos theory 是本章核心。",
                                 "The fidelity principle 也很重要。"])
        jid = "ts000000000000001"
        calls = {"extract": 0, "translate": 0}

        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "术语管理专家" in system_prompt:
                calls["extract"] += 1
                return json.dumps([
                    {"Source": "Skopos theory", "Target": "目的论"},
                    {"Source": "fidelity principle", "Target": "忠实原则"},
                ])
            if "学术翻译专家" in system_prompt:
                calls["translate"] += 1
                return json.dumps([f"译文：{s}" for _, s in _numbered(user_prompt)])
            if "翻译审校专家" in system_prompt:
                return '[]'
            return "报告章节内容。"

        core.call_llm = llm
        kwargs = dict(provider="DeepSeek", api_key="k", model="deepseek-chat",
                      target_lang="简体中文", auto_term=True, enable_report=False,
                      translation_theory="目的论 (Skopos Theory)", user_glossary=[])

        # 高质量模式：术语抽取后停在审核阶段，不得翻译
        state = core.run_job_pipeline(jid, "t.docx", docx_bytes, mode="quality", **kwargs)
        assert state["p1_done"] and state["p2_done"] is False
        assert state["stage"] == "TERMS_PREPARED"
        assert state["delivery_status"] == "draft"
        assert calls["translate"] == 0
        assert len(state["glossary"]) == 2
        assert all(e["status"] == "candidate" for e in state["glossary"])
        assert any("尚未冻结" in w for w in state["warnings"])

        # 刷新/重启：从磁盘恢复，不得重新抽取，也不得翻译
        state2 = core.run_job_pipeline(jid, "t.docx", None, mode="quality", **kwargs)
        assert calls["extract"] == 1, "恢复时不得重新抽取术语"
        assert calls["translate"] == 0
        assert state2["stage"] == "TERMS_PREPARED"
        assert len(state2["glossary"]) == 2
        assert state2["auto_term_entries"][0]["occurrences"] == [0], \
            "occurrences 已持久化"

        # 冻结后：允许翻译
        frozen = core.freeze_glossary(jid, frozen_by="测试用户")
        assert frozen["glossary_frozen"]["version"] == 1
        assert frozen["glossary_frozen"]["glossary_hash"]
        state3 = core.run_job_pipeline(jid, "t.docx", None, mode="quality", **kwargs)
        assert state3["p2_done"] is True and len(state3["pairs"]) == 2

        # 修改术语再冻结 -> 新版本 + 新哈希，旧版本保留
        entries = list(frozen["glossary"])
        entries[0]["target"] = "翻译目的论"
        frozen2 = core.freeze_glossary(jid, entries=entries, frozen_by="测试用户")
        assert frozen2["glossary_frozen"]["version"] == 2
        assert frozen2["glossary_frozen"]["glossary_hash"] != \
            frozen["glossary_frozen"]["glossary_hash"]
        assert len(frozen2["glossary_versions"]) == 2
        assert frozen2["glossary_versions"][0]["glossary_hash"] == \
            frozen["glossary_frozen"]["glossary_hash"], "旧冻结状态不得被覆盖"

        # 快速模式：直接翻译，自动术语为 provisional
        jid2 = "ts000000000000002"
        state_q = core.run_job_pipeline(jid2, "q.docx", docx_bytes, mode="quick", **kwargs)
        assert state_q["p2_done"] is True
        assert all(e["status"] == "provisional" for e in state_q["glossary"])
        print("  ✓ 审核状态持久化/恢复 + 冻结门禁 + 版本化 + 快速模式")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def _numbered(user_prompt):
    import re
    segs = [(int(m.group(1)), m.group(2).strip())
            for m in re.finditer(r'^\s*(\d+)\.\s+(.+?)\s*$', user_prompt, re.M)]
    segs.sort(key=lambda x: x[0])
    return segs


def test_apptest_term_review_panel():
    from streamlit.testing.v1 import AppTest
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-apptest-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        jid = "qt000000000000001"
        state = core.new_job_state("quality.docx")
        state.update(
            p1_done=True, p2_done=False, quality_mode=True, profile_done=True,
            paras=["The Skopos theory 是核心概念。",
                   "The fidelity principle 也很重要。"],
            auto_terms={"Skopos theory": "目的论"},
            glossary=[{
                "id": "t-abc123", "source": "Skopos theory", "target": "目的论",
                "proposed_target": "目的论", "preferred": "目的论", "forbidden": [],
                "behavior": "translate", "status": "candidate", "domain": "翻译学",
                "scope": "document", "note": "", "confidence": 0.5,
                "occurrences": [0],
                "evidence": [{"evidence_type": "model_knowledge", "source_name": "",
                              "note": "自动抽取", "quote": "", "url": "",
                              "confidence": 0.5}],
            }],
            stage="TERMS_PREPARED", delivery_status="draft",
        )
        core.save_job_state(jid, state)

        at = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"),
                               default_timeout=30)
        at.run()
        assert not at.exception, f"应用启动异常：{at.exception}"
        assert any(widget.label == "目标语言" for widget in at.selectbox), \
            "旧版 Streamlit 也必须渲染目标语言选择框"
        assert at.session_state["app_view"] == "new" \
            and not at.session_state["workspace_mode"], \
            "打开应用时不应自动进入未完成任务"
        next(b for b in at.sidebar.button if b.label == "历史任务").click()
        at.run()
        assert any("quality.docx" in m.value for m in at.markdown), \
            "未完成任务应保留在历史任务列表"
        assert any("tp-history-copy" in m.value for m in at.markdown), \
            "历史任务名称与进度应使用可读的任务信息容器"
        next(b for b in at.button if b.label == "打开").click()
        at.session_state["workspace_section"] = "terms"
        at.run()
        assert not at.exception, f"术语工作区渲染异常：{at.exception}"
        assert any("<h2>术语</h2>" in m.value for m in at.markdown)
        labels = [b.label for b in at.button]
        assert "冻结并继续翻译" in labels, labels
        assert any("provisional" in m.value or "术语" in m.value for m in at.markdown)
        print("  ✓ AppTest：术语工作区显示 + 冻结入口可见")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def _entry(source, target, **kw):
    base = {"source": source, "target": target, "behavior": "translate",
            "status": "provisional"}
    base.update(kw)
    return models.normalize_glossary_entry(base)


def test_select_glossary_for_segments():
    glossary = [
        _entry("Skopos theory", "目的论", status="locked", scope="global"),
        _entry("John Smith", "约翰·史密斯", behavior="preserve", status="locked",
               scope="global"),
        _entry("fidelity principle", "忠实原则", status="locked", scope="section:s1"),
        _entry("MT", "机器翻译", status="locked", scope="document"),
        _entry("AI", "人工智能", status="locked", scope="global"),
        _entry("rejected term", "拒绝", status="rejected", scope="global"),
        _entry("provisional term", "建议译名", status="provisional", scope="global"),
        _entry("section2 term", "第二节术语", status="locked", scope="section:s2"),
        _entry("segment0 term", "段0术语", status="locked", scope="segment:0"),
    ]
    for i in range(6):
        glossary.append(_entry(f"prov{i}", f"建议{i}", status="provisional",
                               scope="global"))
    segs = ["The Skopos theory guides John Smith, the fidelity principle and segment0 term.",
            "No locked terms here except provisional term prov0 prov1 prov2 prov3 prov4 prov5."]
    section_profile = {"section_id": "s1", "start_segment": 0, "end_segment": 1}

    selected, ids = terminology.select_glossary_for_segments(
        segs, glossary, section_profile=section_profile)
    by_source = {e["source"]: e for e in selected}
    assert "Skopos theory" in by_source, "locked 术语应被注入"
    assert "John Smith" in by_source, "preserve 条目应被注入"
    assert "fidelity principle" in by_source, "section:s1 匹配时应注入"
    assert "MT" not in by_source, "无关术语不得注入"
    assert "AI" not in by_source, "短词不得因 substring 误命中（Mountain 等）"
    assert "rejected term" not in by_source, "rejected 永不注入"
    assert "section2 term" not in by_source, "scope 不匹配时不得注入"
    assert "segment0 term" in by_source, "segment:0 应命中批次第 0 段"
    prov_count = sum(1 for e in selected if e["status"] == "provisional")
    assert prov_count == 5, f"provisional 建议数量应受限，实际 {prov_count}"
    assert ids == sorted(e["id"] for e in selected)

    # 无 section_profile 时 section scope 不注入
    selected2, _ = terminology.select_glossary_for_segments(segs, glossary)
    assert "fidelity principle" not in {e["source"] for e in selected2}
    # 空输入
    assert terminology.select_glossary_for_segments([], glossary) == ([], [])
    assert terminology.select_glossary_for_segments(["x"], []) == ([], [])
    print("  ✓ 相关术语选择（locked/preserve 注入、scope、provisional 上限、短词防误命中）")


def test_glossary_qa_all_occurrences():
    glossary = [
        _entry("Skopos theory", "目的论", status="locked", scope="global"),
        _entry("John Smith", "约翰·史密斯", behavior="preserve", status="locked"),
        _entry("RT-52", "RT-52", behavior="preserve", status="locked"),
        _entry("provisional term", "建议译名", status="provisional"),
    ]
    pairs = [
        ("The Skopos theory matters here.", "目的论在这里很重要。"),
        ("The Skopos theory appears again.", "这里没有使用首选译名。"),
        ("John Smith and the RT-52 unit.", "约翰·史密斯和那个装置。"),
        ("The RT-52 unit was removed.", "该装置已被移除。"),
        ("provisional term is fine.", "建议译名没问题。"),
    ]
    findings = []
    for i, (src, tgt) in enumerate(pairs):
        findings.extend(terminology.check_glossary_compliance(src, tgt, glossary,
                                                              segment_id=i))
    # 第 1 段未用首选译名（第二个 occurrence 也要检查）
    miss = [f for f in findings if f["entry_id"] == glossary[0]["id"]
            and f["segment_id"] == 1]
    assert miss and miss[0]["severity"] == "actionable"
    assert not any(f["segment_id"] == 0 for f in miss), "正确段落不应误报"
    # John Smith 丢失 -> actionable；RT-52（结构标识）丢失 -> blocking
    js = [f for f in findings if f["entry_id"] == glossary[1]["id"]]
    assert js and js[0]["severity"] == "actionable"
    rt = [f for f in findings if f["entry_id"] == glossary[2]["id"]]
    assert any(f["segment_id"] == 3 and f["severity"] == "blocking" for f in rt), \
        "结构标识类保留项丢失应为 blocking"
    # provisional 不产生强制 finding
    assert not any(f["entry_id"] == glossary[3]["id"] for f in findings)
    # 所有 finding 都带 entry_id / segment_id
    assert all(f.get("entry_id") and f.get("segment_id") is not None for f in findings)
    print("  ✓ 术语 QA（全部 occurrence / preferred / forbidden / preserve 分级 / entry_id）")


def test_conflict_detection():
    glossary = [
        _entry("Skopos theory", "目的论", status="locked", scope="global"),
    ]
    # 段 0 用首选，段 1 用其他译法 -> 冲突
    pairs = [
        {"source": "The Skopos theory is central.", "target": "目的论是核心。"},
        {"source": "Skopos theory again.", "target": "翻译目的学派再次出现。"},
    ]
    findings = terminology.detect_glossary_conflicts(pairs, glossary)
    assert findings
    assert all(f["conflict"] and f["entry_id"] == glossary[0]["id"] for f in findings)
    assert {f["segment_id"] for f in findings} == {0, 1}
    assert all(f["severity"] == "actionable" for f in findings)
    # 全部一致 -> 无冲突
    pairs2 = [
        {"source": "The Skopos theory is central.", "target": "目的论是核心。"},
        {"source": "Skopos theory again.", "target": "目的论再次出现。"},
    ]
    assert terminology.detect_glossary_conflicts(pairs2, glossary) == []
    print("  ✓ 同范围多译法冲突检测")


def test_batch_injection_log_and_prompt():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-inject-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        docx_bytes = _make_docx(["The Skopos theory 是本章核心，其他术语未出现。",
                                 "John Smith 也在讨论范围内。"])
        user_glossary = [
            {"Source": "Skopos theory", "Target": "目的论", "Status": "locked",
             "Preferred": "目的论"},
            {"Source": "John Smith", "Target": "约翰·史密斯", "Behavior": "preserve",
             "Status": "locked"},
            {"Source": "unrelated term", "Target": "无关术语", "Status": "locked",
             "Preferred": "无关术语"},
            {"Source": "MT", "Target": "机器翻译", "Status": "locked",
             "Preferred": "机器翻译"},
        ]
        prompts = []

        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "学术翻译专家" in system_prompt:
                prompts.append(system_prompt + "\n" + user_prompt)
                return json.dumps([f"译文：{s}" for _, s in _numbered(user_prompt)])
            if "翻译审校专家" in system_prompt:
                return '[]'
            return "报告章节内容。"

        core.call_llm = llm
        state = core.run_job_pipeline(
            "in0000000000000001", "i.docx", docx_bytes,
            provider="DeepSeek", api_key="k", model="deepseek-chat",
            target_lang="简体中文", auto_term=False, enable_report=False,
            translation_theory="目的论 (Skopos Theory)", user_glossary=user_glossary,
            mode="quick")
        # 只注入实际出现的 locked 术语，无关术语不进入 prompt
        assert prompts, "应有一次翻译调用"
        prompt_text = prompts[0]
        assert "Skopos theory -> 目的论" in prompt_text
        assert "John Smith" in prompt_text
        assert "unrelated term" not in prompt_text, "无关术语不得注入 prompt"
        assert "MT" not in prompt_text, "未出现的术语不得注入 prompt"
        # 注入日志 + 每段 entry_ids
        log = state["glossary_injection_log"]
        assert len(log) == 1 and log[0]["batch"] == 0
        injected = log[0]["entry_ids"]
        assert all(e["id"] in injected for e in state["glossary"]
                   if e["source"] in ("Skopos theory", "John Smith"))
        assert all(p.get("glossary_entry_ids") == injected for p in state["pairs"])
        print("  ✓ 批次注入：仅相关术语注入 prompt + 审计日志 + 每段 entry_ids")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_delivery_gate_blocking_review_required():
    # 翻译完成但有 blocking -> review_required，绝不自动 final
    state = core.new_job_state("d.pdf")
    state.update(p1_done=True, p2_done=True, has_blocking=True,
                 delivery_status="review_required",
                 findings=[{"segment_index": 0, "severity": "blocking",
                            "type": "review", "reason": "语义严重错误"}])
    assert delivery.compute_delivery_status(state) == "review_required"

    # 未接受风险 -> 拒绝 final
    state2, ok, errors = delivery.approve_delivery(dict(state))
    assert ok is False and errors and "blocking" in errors[0]
    assert state2["delivery_status"] == "review_required"

    # 接受风险并填写说明 -> final + 人工处理记录
    state3, ok3, errors3 = delivery.approve_delivery(
        dict(state), note="客户确认可接受该风险", accept_blocking=True)
    assert ok3 is True and errors3 == []
    assert state3["delivery_status"] == "final" and state3["stage"] == "FINAL"
    assert state3["findings"][0]["resolved"] is True
    assert state3["findings"][0]["resolution"]["action"] == "accepted_risk"
    records = state3["human_actions"]
    assert any(r["action"] == "accepted_risk" and r["finding_id"].startswith("f-")
               and r["note"] and r["timestamp"] for r in records)
    assert any(r["action"] == "approve_final" for r in records)
    print("  ✓ 交付门禁：blocking -> review_required；接受风险 -> final + 记录")


def test_mark_fixed_then_final():
    state = core.new_job_state("d2.pdf")
    finding = {"segment_index": 3, "severity": "blocking", "type": "check",
               "reason": "占位符丢失"}
    state.update(p1_done=True, p2_done=True, has_blocking=True, findings=[finding])
    fid = delivery.finding_id(finding)
    state2, marked = delivery.mark_findings(dict(state), [fid], "human_fixed",
                                            note="已人工补回占位符")
    assert marked == [fid]
    assert delivery.compute_delivery_status(state2) == "draft"
    state3, ok, _ = delivery.approve_delivery(state2)
    assert ok is True and state3["delivery_status"] == "final"
    actions = [r["action"] for r in state3["human_actions"]]
    assert actions == ["human_fixed", "approve_final"]
    # finding_id 稳定：内容相同 -> 相同 ID；内容不同 -> 不同 ID
    assert delivery.finding_id(finding) == fid
    assert delivery.finding_id(dict(finding, reason="另一个原因")) != fid
    assert delivery.finding_id({"id": "custom-1"}) == "custom-1"
    print("  ✓ 人工修复 -> draft -> 确认 final；finding_id 稳定")


def test_retranslate_segments():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-rt-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        long_src = "The squadron prepared for the long-range mission. " * 5
        state = core.new_job_state("r2.docx")
        state.update(
            p1_done=True, p2_done=True, has_blocking=True,
            paras=[long_src, "第二段足够长以通过检查。"],
            pairs=[
                {"source": long_src, "target": "只译了一句。", "reviewed": False,
                 "from_tm": False, "review_status": "reviewed_clean",
                 "initial_target": "旧初译", "accepted_target": "旧接受译文",
                 "human_accepted": True, "target_provenance": "human_accepted",
                 "glossary_entry_ids": []},
                {"source": "第二段足够长以通过检查。", "target": "第二段的译文。",
                 "reviewed": True, "from_tm": False, "glossary_entry_ids": []},
            ],
            findings=[
                {"segment_index": 0, "severity": "blocking", "type": "check",
                 "reason": "疑似漏译/截断：原文 250 字符，译文仅 6 字符"},
            ],
            review_stats={"blocking": 1, "actionable": 0, "informational": 0},
            delivery_status="final", stage="FINAL",
            delivery_approved_by_human=True,
            delivery_approval={"actor": "previous-reviewer"},
        )
        core.save_job_state("rt0000000000000001", state)

        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "学术翻译专家" in system_prompt:
                return json.dumps(["完整译文：中队已经为远程任务做好了充分准备。" * 5])
            return "[]"

        core.call_llm = llm
        state2, fixed = core.retranslate_segments(
            "rt0000000000000001", [0], "DeepSeek", "k", "deepseek-chat",
            "简体中文", glossary=[])
        assert fixed == [0]
        assert state2["pairs"][0]["target"].startswith("完整译文：")
        assert state2["pairs"][0]["reviewed"] is False, "重译段需重新审校"
        old = [f for f in state2["findings"] if f["segment_index"] == 0]
        assert old and all(f.get("resolved") for f in old), \
            "重译段的旧 finding 应保留并标记已解决"
        assert state2["has_blocking"] is False
        assert state2["delivery_status"] == "draft"
        assert state2["stage"] == "TRANSLATED"
        assert state2["delivery_approved_by_human"] is False
        assert state2["delivery_approval"] is None
        assert state2["pairs"][0]["initial_target"] == state2["pairs"][0]["target"]
        assert state2["pairs"][0]["review_status"] == "not_reviewed"
        assert state2["pairs"][0]["target_provenance"] == "generated"
        assert state2["pairs"][0].get("accepted_target") is None
        assert state2["pairs"][0].get("human_accepted") is None
        assert any(r["action"] == "retranslated" for r in state2["human_actions"])
        # 落盘后可恢复
        on_disk = core.load_job_state("rt0000000000000001")
        assert on_disk["pairs"][0]["target"].startswith("完整译文：")
        print("  ✓ 定点重译（fix_segments 能力复用）：替换译文/清 finding/重算交付")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_retranslate_keeps_postcheck_findings():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-rt-postcheck-"))
    old_dir = core.OUTPUT_DIR
    old_call = core.call_llm
    core.OUTPUT_DIR = tmp
    try:
        source = "RIOT IN CELL BLOCK 11"
        state = core.new_job_state("title.docx")
        state.update(
            p1_done=True, p2_done=True, paras=[source],
            pairs=[{"source": source, "target": "错位译文。", "reviewed": False,
                    "from_tm": False, "glossary_entry_ids": []}],
            findings=[{"segment_index": 0, "severity": "actionable", "type": "review",
                       "reason": "旧问题"}], review_stats={})
        core.save_job_state("rtpostcheck000001", state)
        core.call_llm = lambda *_args, **_kwargs: json.dumps([source])
        updated, fixed = core.retranslate_segments(
            "rtpostcheck000001", [0], "DeepSeek", "k", "model", "简体中文",
            glossary=[])
        assert fixed == [0]
        assert any(f.get("segment_index") == 0 and f.get("severity") == "actionable"
                   and "未翻译" in f.get("reason", "") for f in updated["findings"])
        assert updated["review_stats"]["actionable"] == 1
        assert any(f.get("resolved") and f.get("reason") == "旧问题"
                   for f in updated["findings"])
        print("  ✓ 定点重译保留最终复验 finding")
    finally:
        core.call_llm = old_call
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_pipeline_blocking_delivery_status():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-deliv-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        docx_bytes = _make_docx(["这是第一段，内容足够长以通过过滤。",
                                 "这是第二段，内容足够长以通过过滤。"])

        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "翻译审校专家" in system_prompt:
                return json.dumps([{"segment_index": 1, "severity": "blocking",
                                    "reason": "语义严重错误，需人工确认"}])
            if "学术翻译专家" in system_prompt:
                return json.dumps([f"译文：{s}" for _, s in _numbered(user_prompt)])
            return "报告章节内容。"

        core.call_llm = llm
        state = core.run_job_pipeline(
            "dl0000000000000001", "d.docx", docx_bytes,
            provider="DeepSeek", api_key="k", model="deepseek-chat",
            target_lang="简体中文", auto_term=False, enable_report=False,
            translation_theory="目的论 (Skopos Theory)", user_glossary=[])
        assert state["delivery_status"] == "review_required", \
            "翻译完成但有 blocking -> review_required，而不是 final"
        assert state["stage"] == "REVIEW_REQUIRED"
        # 通过 core 包装接受风险 -> final
        state2, ok, _ = core.approve_delivery("dl0000000000000001",
                                              note="人工确认", accept_blocking=True)
        assert ok and state2["delivery_status"] == "final"
        print("  ✓ 流水线 blocking -> review_required -> 接受风险 -> final")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_tbx_valid_xml():
    glossary = models.normalize_glossary([
        {"source": "Skopos theory", "target": "目的论", "status": "locked",
         "preferred": "目的论", "forbidden": ["功能对等"], "domain": "翻译学",
         "scope": "global", "note": "核心理论",
         "evidence": [{"evidence_type": "user", "source_name": "导师批注",
                       "note": "教学确认"}]},
        {"source": "John Smith", "target": "约翰·史密斯", "behavior": "preserve",
         "status": "locked", "scope": "document"},
    ])
    xml_bytes = assets.build_tbx(glossary)
    assert xml_bytes.startswith(b"<?xml")
    assert assets.validate_tbx(xml_bytes, expected_entries=2) == []
    text = xml_bytes.decode("utf-8")
    assert "Skopos theory" in text and "目的论" in text
    assert "功能对等" in text and "prohibited" in text
    assert "翻译学" in text and "global" in text and "核心理论" in text
    assert "user" in text, "evidence type 应写入 TBX"
    assert assets.validate_tbx(b"not xml", 1), "非法 XML 应报错"
    assert assets.validate_tbx(xml_bytes, expected_entries=99), "数量不符应报错"
    print("  ✓ TBX 导出（合法 XML + forbidden/status/domain/scope/note/evidence + 校验）")


def test_tmx_only_reviewed_segments():
    state = core.new_job_state("tmx.pdf")
    state.update(
        pairs=[
            {"source": "A good sentence.", "target": "好句子。",
             "reviewed": True, "from_tm": False},
            {"source": "Blocked sentence.", "target": "被阻塞的句子。",
             "reviewed": False, "from_tm": False},
            {"source": "Reviewed but flagged.", "target": "已审但有 finding。",
             "reviewed": True, "from_tm": False},
        ],
        findings=[{"segment_index": 2, "severity": "blocking", "type": "review",
                   "reason": "语义错误"}],
        delivery_status="review_required",
    )
    xml_bytes = assets.build_tmx(state, src_lang="en", tgt_lang="zh-CN",
                                 job_id="tmx00000000000001")
    assert assets.validate_tmx(xml_bytes, expected_tus=1) == [], \
        "只有审校通过且无 blocking/actionable 的段落才能进入 TMX"
    text = xml_bytes.decode("utf-8")
    assert "A good sentence." in text and "好句子。" in text
    assert "Blocked sentence." not in text
    assert "Reviewed but flagged." not in text
    assert 'srclang="en"' in text and 'xml:lang="zh-CN"' in text
    assert "seg-tmx00000000000001-0000" in text, "应带 segment ID"
    # 无审校通过段落 -> 空 TMX 也合法
    empty_state = core.new_job_state("e.pdf")
    empty_state["pairs"] = [{"source": "x", "target": "y", "reviewed": False,
                             "from_tm": False}]
    empty = assets.build_tmx(empty_state, job_id="e0000000000000000")
    assert assets.validate_tmx(empty, expected_tus=0) == []
    print("  ✓ TMX 导出（仅审校通过 + 无 blocking/actionable；含语言与 segment ID）")


def test_jsonl_count_and_fields():
    state = core.new_job_state("j.pdf")
    state.update(
        pairs=[
            {"source": "Term A appears.", "target": "术语A出现。",
             "reviewed": True, "from_tm": False,
             "glossary_entry_ids": ["t-aaa", "t-bbb"]},
            {"source": "Term B appears.", "target": "术语B出现。",
             "reviewed": False, "from_tm": True, "glossary_entry_ids": []},
        ],
        findings=[{"segment_index": 1, "severity": "actionable", "type": "check",
                   "reason": "残留"}],
        delivery_status="draft",
    )
    text = assets.build_jsonl(state, job_id="json00000000000001")
    assert assets.validate_jsonl(text, expected_lines=2) == []
    lines = [json.loads(ln) for ln in text.splitlines()]
    assert lines[0]["segment_id"] == "seg-json00000000000001-0000"
    assert lines[0]["glossary_entry_ids"] == ["t-aaa", "t-bbb"]
    assert lines[1]["findings"][0]["reason"] == "残留"
    assert lines[1]["from_tm"] is True and lines[0]["reviewed"] is True
    assert all(l["delivery_status"] == "draft" for l in lines)
    # 数量校验
    assert assets.validate_jsonl(text, expected_lines=3)
    assert assets.validate_jsonl("{broken", 1)
    print("  ✓ JSONL 导出（每段一行 + 字段完整 + 数量校验）")


def test_manifest_matches_state():
    state = core.new_job_state("m.pdf")
    frozen = models.normalize_frozen_glossary({
        "version": 2, "source_hash": "abc123",
        "entries": [{"source": "Skopos", "target": "目的论", "status": "locked"}],
        "frozen_at": "2026-08-06T00:00:00", "frozen_by": "tester"})
    state.update(
        p1_done=True, p2_done=True,
        pairs=[{"source": "s1", "target": "t1", "reviewed": True, "from_tm": False},
               {"source": "s2", "target": "t2", "reviewed": False, "from_tm": True},
               {"source": "s3", "target": "t3", "reviewed": False, "from_tm": False}],
        findings=[
            {"segment_index": 2, "severity": "blocking", "type": "review",
             "reason": "严重错误"},
            {"segment_index": 0, "severity": "actionable", "type": "check",
             "reason": "小问题"},
            {"segment_index": 1, "severity": "informational", "type": "check",
             "reason": "建议"},
        ],
        review_stats={"blocking": 1, "actionable": 1, "informational": 1},
        tm_used_count=1,
        delivery_status="review_required",
        document_profile=models.normalize_document_profile(
            {"domain": "历史", "confidence": 0.6}),
        glossary_frozen=frozen,
        _source_bin=b"source-bytes",
    )
    manifest = assets.build_delivery_manifest(
        state, "man000000000000001", target_lang="简体中文",
        provider="DeepSeek", model="deepseek-chat",
        source_filename="m.pdf")
    assert assets.validate_manifest(manifest, state) == []
    assert manifest["segment_count"] == 3
    assert manifest["tm_reused_count"] == 1
    assert manifest["blocking"] == 1 and manifest["actionable"] == 1
    assert manifest["informational"] == 1
    assert manifest["delivery_status"] == "review_required"
    assert len(manifest["unresolved_findings"]) == 2
    assert manifest["frozen_glossary"]["glossary_hash"] == frozen["glossary_hash"]
    assert manifest["source_hash"] == hashlib.sha256(b"source-bytes").hexdigest()
    # 状态被篡改 -> 校验失败
    bad = dict(manifest, segment_count=99)
    assert assets.validate_manifest(bad, state)
    print("  ✓ delivery_manifest 统计与任务状态一致")


def test_export_all_assets():
    state = core.new_job_state("all.pdf")
    state.update(
        p1_done=True, p2_done=True,
        pairs=[{"source": "Term X is here.", "target": "术语X在此。",
                "reviewed": True, "from_tm": False,
                "glossary_entry_ids": ["t-x"]}],
        glossary=models.normalize_glossary(
            [{"source": "Term X", "target": "术语X", "status": "locked"}]),
        findings=[], review_stats={"blocking": 0, "actionable": 0,
                                   "informational": 0},
        delivery_status="draft",
    )
    out = assets.export_all(state, "all000000000000001",
                            target_lang="简体中文", provider="DeepSeek",
                            model="deepseek-chat", source_filename="all.pdf",
                            source_bin=b"pdf")
    assert set(out) == {"terms.tbx", "memory.tmx", "bilingual.jsonl",
                        "delivery_manifest.json"}
    assert assets.validate_tbx(out["terms.tbx"], expected_entries=1) == []
    assert assets.validate_tmx(out["memory.tmx"], expected_tus=1) == []
    assert assets.validate_jsonl(out["bilingual.jsonl"].decode("utf-8"),
                                 expected_lines=1) == []
    manifest = json.loads(out["delivery_manifest.json"].decode("utf-8"))
    assert assets.validate_manifest(manifest, state) == []
    print("  ✓ export_all：四类标准资产 + 全部校验通过")


def test_segment_evidence_bundle():
    state = core.new_job_state("ev.pdf")
    fg = models.normalize_frozen_glossary({
        "version": 1, "source_hash": "h",
        "entries": [{"source": "Term X", "target": "术语X", "status": "locked"}],
        "frozen_at": "2026-08-06T00:00:00", "frozen_by": "u"})
    state.update(
        pairs=[
            {"source": "Term X appears here.", "target": "最终译文。",
             "initial_target": "初译版本。", "reviewed": True, "from_tm": False,
             "glossary_entry_ids": [fg["entries"][0]["id"]]},
        ],
        findings=[
            {"segment_index": 0, "type": "check", "severity": "actionable",
             "reason": "残留", "entry_id": fg["entries"][0]["id"]},
            {"segment_index": 0, "type": "review", "severity": "actionable",
             "reason": "建议调整", "suggested_target": "建议译文"},
        ],
        human_actions=[
            {"finding_id": "segment:0", "action": "retranslated",
             "note": "人工重译", "timestamp": "2026-08-06T00:00:00"},
        ],
        glossary_frozen=fg,
        delivery_status="draft",
    )
    ev = report_evidence.build_segment_evidence(state, "ev0000000000000001", 0)
    assert ev["available"] is True
    assert ev["segment_id"] == "seg-ev0000000000000001-0000"
    assert ev["source"] == "Term X appears here.", "原文必须逐字来自任务状态"
    assert ev["final_target"] == "最终译文。"
    assert ev["initial_target"] == "初译版本。"
    assert ev["glossary_decisions"]["injected_entry_ids"] == [fg["entries"][0]["id"]]
    assert ev["glossary_decisions"]["frozen_glossary_hash"] == fg["glossary_hash"]
    assert ev["deterministic_findings"][0]["reason"] == "残留"
    assert ev["review_findings"][0]["suggested_target"] == "建议译文"
    assert ev["repair_history"][0]["suggested_target"] == "建议译文"
    assert ev["human_actions"][0]["action"] == "retranslated"
    # 越界段 -> available False
    assert report_evidence.build_segment_evidence(state, "ev", 99)["available"] is False
    # JSONL 导出：行数 = 段落数
    text = report_evidence.export_segment_evidence_jsonl(
        state, "ev0000000000000001")
    assert len(text.splitlines()) == 1
    print("  ✓ 段落证据包（segment_id/原文逐字/初译/术语决策/发现/修复/人工记录）")


def test_report_prompt_evidence_contract():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-rep-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        docx_bytes = _make_docx(["The Skopos theory 是核心概念。",
                                 "第二段也足够长以通过检查。"])
        report_prompts = []

        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "学术论证规划器" in system_prompt or "学术提纲规划器" in system_prompt:
                report_prompts.append((system_prompt, user_prompt))
                return "非 JSON，触发保守规划"
            if "独立的 MTI 学术审稿人" in system_prompt:
                report_prompts.append((system_prompt, user_prompt))
                return '{"issues": []}'
            if "证据约束型学术写作者" in system_prompt:
                report_prompts.append((system_prompt, user_prompt))
                packet = json.loads(user_prompt)["packet"]
                section = packet["current_section"]
                content = "".join(
                    f"<!--rq:{x}-->" for x in section["research_questions"])
                content += "".join(f"<!--claim:{x}-->" for x in section["claims"])
                content += "\n" + "\n".join(
                    f"{x['markdown_prefix']} {x['heading_id']} {x['title']}\n本小节按已配置结构展开。"
                    for x in (packet.get("writing_constraints") or {}).get(
                        "required_subsections", []))
                content += "本节严格依据项目证据展开，不把作者分析冒充译者真实意图。"
                for key in section["required_statistics"]:
                    content += f"本项目指标为 {{{{STAT:{key}}}}}，仅描述当前任务。"
                for case in packet["cases"]:
                    ev = case["evidence"]
                    content += (f"\n[{ev['segment_id']}]\n"
                                f"> [SOURCE {ev['segment_id']}]: {ev['source']}\n"
                                f"> [TARGET {ev['segment_id']}]: {ev['final_target']}\n"
                                "从结果看，该译文可解释为证据范围内的翻译处理。")
                return content + "该结论不超出当前项目。" * 30
            if "翻译审校专家" in system_prompt:
                return '[]'
            if "学术翻译专家" in system_prompt:
                return json.dumps([f"译文：{s}" for _, s in _numbered(user_prompt)])
            return "报告章节内容。"

        core.call_llm = llm
        state = core.run_job_pipeline(
            "rp000000000000001", "r.docx", docx_bytes,
            provider="DeepSeek", api_key="k", model="deepseek-chat",
            target_lang="简体中文", auto_term=False, enable_report=True,
            translation_theory="目的论 (Skopos Theory)", user_glossary=[],
            mode="quick", research_settings={"report_stage": "proposal"})
        assert report_prompts, "报告应被调用"
        writer_prompts = [x for x in report_prompts if "证据约束型学术写作者" in x[0]]
        assert writer_prompts and "从结果看可解释为" in writer_prompts[0][0]
        assert "不得新增主要论点" in writer_prompts[0][0]
        all_user = "\n".join(up for _, up in report_prompts)
        assert "seg-rp000000000000001-0000" in all_user, \
            "分节 packet 必须带真实 segment_id"
        assert "The Skopos theory 是核心概念。" in all_user, \
            "原文必须逐字来自任务状态"
        assert state["p3_done"] and state["p3_md"].count("## ") >= 1
        validation = json.loads((tmp / "rp000000000000001" /
                                 "academic-validation.json").read_text(encoding="utf-8"))
        assert not any(x["type"] == "invented_segment_id" for x in validation["issues"])
        print("  ✓ 学术写作 packet + runtime 验证（真实 segment_id/逐字证据/防冒充）")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_initial_target_recorded():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-init-"))
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
                    return json.dumps(["修正译文：请参考 https://example.com/ref 获取详细信息。"])
                return json.dumps(["初译译文：请参考 获取详细信息。"])  # 故意丢失 URL
            return "报告章节内容。"

        core.call_llm = llm
        state = core.run_job_pipeline(
            "in0000000000000002", "i.docx", docx_bytes,
            provider="DeepSeek", api_key="k", model="deepseek-chat",
            target_lang="简体中文", auto_term=False, enable_report=False,
            translation_theory="目的论 (Skopos Theory)", user_glossary=[])
        pair = state["pairs"][0]
        assert pair["initial_target"] == "初译译文：请参考 获取详细信息。"
        assert "https://example.com/ref" in pair["target"], "修复后的最终译文应含 URL"
        assert pair["initial_target"] != pair["target"]
        print("  ✓ initial_target 记录（初译 -> 修复后最终译文可追溯）")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_evidence_provider_interface():
    # 默认离线：noop provider 不发起调用
    provider = terminology.get_provider("noop")
    assert provider.fetch_evidence("Skopos") == []
    # 未知 provider 回退 noop，保证无网络也正常工作
    assert terminology.get_provider("不存在的服务").fetch_evidence("x") == []

    class FakeExternal(terminology.TermEvidenceProvider):
        name = "fake-external"

        def fetch_evidence(self, term, domain=""):
            return [{
                "evidence_type": "external",
                "source_name": "termbase.io",
                "url": f"https://termbase.io/term/{term}",
                "note": "真实来源返回",
                "confidence": 0.9,
            }]

    evs = FakeExternal().fetch_evidence("Skopos")
    assert len(evs) == 1
    norm = models.normalize_evidence(evs[0])
    assert norm["evidence_type"] == "external" and norm["url"], \
        "真实 provider 返回的来源可保存 URL"
    assert models.validate_evidence(norm) == []
    print("  ✓ external evidence provider 接口（预留）+ 离线回退")


def test_unfreeze_back_to_edit():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-unfreeze-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        jid = "uf0000000000000001"
        state = core.new_job_state("u.docx")
        state["glossary"] = models.normalize_glossary(
            [{"source": "Term X", "target": "术语X"}])
        core.save_job_state(jid, state)
        frozen = core.freeze_glossary(jid, frozen_by="用户")
        assert frozen["glossary_frozen"] is not None
        assert len(frozen["glossary_versions"]) == 1
        # 返回修改：解除冻结但保留条目与版本历史
        back = core.unfreeze_glossary(jid)
        assert back["glossary_frozen"] is None
        assert back["stage"] == "TERMS_PREPARED"
        assert len(back["glossary_versions"]) == 1
        assert back["glossary"][0]["source"] == "Term X"
        # 翻译开始后不允许解除冻结
        refrozen = core.freeze_glossary(jid, frozen_by="用户")
        refrozen["p2_done"] = True
        core.save_job_state(jid, refrozen)
        assert core.unfreeze_glossary(jid)["glossary_frozen"] is not None
        print("  ✓ 返回修改（解除冻结 -> TERMS_PREPARED，版本历史保留）")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    print("术语治理测试（模型/迁移/画像/术语候选）：")
    test_document_profile_normalize_validate()
    test_profile_json_parse_and_degrades()
    test_distributed_sample_covers_head_middle_tail()
    test_glossary_entry_normalize_excel_compat()
    test_evidence_no_fake_url()
    test_glossary_hash_deterministic()
    test_state_migration_old_job()
    test_core_load_job_state_migrates()
    test_term_matches_word_boundary()
    test_find_occurrences_all_segments()
    test_extract_auto_terms_v2()
    test_review_state_persist_and_restore()
    test_apptest_term_review_panel()
    test_select_glossary_for_segments()
    test_glossary_qa_all_occurrences()
    test_conflict_detection()
    test_batch_injection_log_and_prompt()
    test_delivery_gate_blocking_review_required()
    test_mark_fixed_then_final()
    test_retranslate_segments()
    test_retranslate_keeps_postcheck_findings()
    test_pipeline_blocking_delivery_status()
    test_tbx_valid_xml()
    test_tmx_only_reviewed_segments()
    test_jsonl_count_and_fields()
    test_manifest_matches_state()
    test_export_all_assets()
    test_segment_evidence_bundle()
    test_report_prompt_evidence_contract()
    test_initial_target_recorded()
    test_evidence_provider_interface()
    test_unfreeze_back_to_edit()
    print("\n全部通过 ✅")
