"""提供商路由 / 中转站 / 多格式导入 / 模式语义 / 自定义标注颜色测试。"""
import io
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core


def test_provider_registry_sane():
    for name, cfg in core.PROVIDERS.items():
        assert cfg["kind"] in ("openai", "openai_compat", "gemini"), name
        if cfg.get("custom_base_url"):
            assert cfg["base_url"] is None and name == "自定义中转站"
        if name == "OpenCode Go":
            assert cfg["models"] == [
                "glm-5.2", "glm-5.1", "deepseek-v4-pro", "deepseek-v4-flash",
                "kimi-k3", "kimi-k2.7-code", "kimi-k2.6",
                "mimo-v2.5-pro", "mimo-v2.5", "hy3", "grok-4.5",
            ], "OpenCode Go 只能列出 /chat/completions 模型"
        if name == "DeepSeek":
            assert cfg["models"] == ["deepseek-v4-flash", "deepseek-v4-pro"]
        if name == "Gemini":
            assert "gemini-2.0-flash" not in cfg["models"]
    print("  ✓ PROVIDERS 注册表（openai_compat / 模型目录完整）")


def test_custom_relay_base_url():
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            message = type("Message", (), {"content": "OK"})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls.append(("client", kwargs))
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    original = core.OpenAI
    core.OpenAI = FakeOpenAI
    try:
        core.set_llm_base_url("https://relay.example.com/v1")
        out = core.call_llm("自定义中转站", "k", "relay-model", "s", "u")
        assert out == "OK"
        client_kwargs = next(k for tag, k in calls if tag == "client")
        assert client_kwargs["base_url"] == "https://relay.example.com/v1"
        create_kwargs = next(k for k in calls if not isinstance(k, tuple))
        assert create_kwargs["model"] == "relay-model"

        calls.clear()
        core.call_llm("自定义中转站", "k", "relay-model", "s", "u",
                      base_url="https://relay.example.com/v1/chat/completions")
        client_kwargs = next(k for tag, k in calls if tag == "client")
        assert client_kwargs["base_url"] == "https://relay.example.com/v1"

        # 预设中转站使用注册表默认 base_url
        calls.clear()
        core.call_llm("OpenRouter", "k", "anthropic/claude-sonnet-4", "s", "u")
        client_kwargs = next(k for tag, k in calls if tag == "client")
        assert client_kwargs["base_url"] == "https://openrouter.ai/api/v1"

        # 清除线程级地址后，自定义中转站不再注入 base_url
        core.set_llm_base_url(None)
        calls.clear()
        core.call_llm("自定义中转站", "k", "m", "s", "u")
        client_kwargs = next(k for tag, k in calls if tag == "client")
        assert "base_url" not in client_kwargs
    finally:
        core.OpenAI = original
        core.set_llm_base_url(None)
    print("  ✓ 自定义中转站 base_url（线程级上下文 + 预设中转站）")


def test_provider_probe():
    class FakeCompletions:
        def create(self, **kwargs):
            message = type("Message", (), {"content": "OK"})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    original = core.OpenAI
    core.OpenAI = FakeOpenAI
    try:
        ok, msg = core.test_provider("DeepSeek", "k", "deepseek-v4-flash")
        assert ok and "OK" in msg
    finally:
        core.OpenAI = original

    class Boom:
        def __init__(self, **kwargs):
            raise RuntimeError("401 Unauthorized")

    core.OpenAI = Boom
    try:
        ok, msg = core.test_provider("DeepSeek", "bad", "deepseek-v4-flash")
        assert not ok and "401" in msg
    finally:
        core.OpenAI = original
    print("  ✓ test_provider（成功 / 失败路径）")


def test_fetch_provider_models():
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "model-z"}, {"id": "model-a"},
                              {"id": "model-a"}]}

    def fake_get(url, headers, timeout):
        calls.append((url, headers, timeout))
        return FakeResponse()

    original_get = core.httpx.get
    core.httpx.get = fake_get
    try:
        ok, models, msg = core.fetch_provider_models(
            "自定义中转站", "k", "https://relay.example.com/v1/chat/completions")
        assert ok and models == ["model-a", "model-z"] and "2" in msg
        assert calls[0][0] == "https://relay.example.com/v1/models"
        assert calls[0][1]["Authorization"] == "Bearer k"
    finally:
        core.httpx.get = original_get
    print("  ✓ 自定义中转站模型目录获取")


def test_exchange_formats():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-exchange-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    try:
        # CSV
        csv = io.BytesIO("Source,Target,Behavior,Status,Preferred\n"
                         "MT,machine translation,translate,locked,机器翻译\n".encode())
        entries = core.parse_termbase_csv(csv)
        assert len(entries) == 1 and entries[0]["preferred"] == "机器翻译"
        assert entries[0]["status"] == "locked"

        # TBX（带命名空间，Trados MultiTerm 风格）
        tbx = io.BytesIO('''<?xml version="1.0"?>
<martif type="TBX" xml:lang="en">
  <text><body>
    <termEntry id="1">
      <langSet xml:lang="en"><tig><term>Skopos theory</term></tig></langSet>
      <langSet xml:lang="zh-CN"><tig><term>目的论</term></tig></langSet>
    </termEntry>
    <termEntry id="2">
      <langSet xml:lang="en"><tig><term>fidelity</term></tig></langSet>
      <langSet xml:lang="zh-CN"><tig><term>忠实性</term></tig></langSet>
    </termEntry>
  </body></text>
</martif>'''.encode("utf-8"))
        entries = core.parse_termbase_tbx(tbx)
        assert len(entries) == 2
        assert entries[0] == {"source": "Skopos theory", "target": "目的论",
                              "behavior": "translate", "status": "locked"}

        # TMX：入库 + 与现有记忆冲突时跳过
        core.save_tm({"existing": {"target": "已有译文", "reviewed": True}})
        tmx = io.BytesIO('''<?xml version="1.0"?>
<tmx version="1.4">
  <body>
    <tu><tuv xml:lang="en"><seg>Hello world</seg></tuv><tuv xml:lang="zh-CN"><seg>你好世界</seg></tuv></tu>
    <tu><tuv xml:lang="en"><seg>existing</seg></tuv><tuv xml:lang="zh-CN"><seg>冲突跳过</seg></tuv></tu>
  </body>
</tmx>'''.encode("utf-8"))
        result = core.import_tmx(tmx)
        assert result == {"added": 1, "skipped": 1}
        tm = core.load_tm()
        assert tm["Hello world"]["target"] == "你好世界"
        assert tm["existing"]["target"] == "已有译文", "冲突源文不得覆盖项目内记忆"

        hostile_xml = b'''<?xml version="1.0"?>
<!DOCTYPE data [<!ENTITY injected "entity text">]>
<data>&injected;</data>'''
        for parser in (core.parse_termbase_tbx, core.import_tmx):
            try:
                parser(io.BytesIO(hostile_xml))
            except ValueError:
                pass
            else:
                raise AssertionError("TBX/TMX 导入必须拒绝 XML 实体声明")
    finally:
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)
    print("  ✓ CSV / TBX / TMX 导入（含冲突跳过）")


def _numbered(user_prompt):
    import re
    segs = [(int(m.group(1)), m.group(2).strip())
            for m in re.finditer(r'^\s*(\d+)\.\s+(.+?)\s*$', user_prompt, re.M)]
    segs.sort(key=lambda x: x[0])
    return segs


def _make_docx(texts):
    from docx import Document
    doc = Document()
    for t in texts:
        doc.add_paragraph(t)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_mode_semantics():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-mode-"))
    old_dir = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    prompts = []
    original_llm = core.call_llm
    original_report = core.generate_mti_report
    try:
        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            prompts.append(system_prompt)
            return json.dumps([f"译文：{s}" for _, s in _numbered(user_prompt)])

        core.call_llm = llm
        docx_bytes = _make_docx(["The Skopos theory is important.", "Fidelity matters."])

        # 标准运行时把全文理解与严格术语治理解耦：即使不启用冻结门禁，
        # 也应生成画像和语义理解产物。
        jid = "qm000000000000001"
        state = core.run_job_pipeline(
            jid, "q.docx", docx_bytes, provider="DeepSeek", api_key="k",
            model="deepseek-chat", target_lang="简体中文", auto_term=False,
            enable_report=False, enable_review=False, enable_annotate=False,
            translation_theory="目的论 (Skopos Theory)", user_glossary=[],
            strict_terminology_governance=False)
        assert state["p2_done"] and state["profile_done"], \
            "Standard runtime 不应因关闭严格术语治理而跳过文档画像"
        assert state["understanding_done"]

        # 严格术语治理 + 导入锁定术语 + 无自动候选：无需冻结直接翻译
        jid2 = "qm000000000000002"
        user_glossary = [{"source": "Skopos theory", "target": "目的论",
                          "status": "locked", "behavior": "translate"}]
        state2 = core.run_job_pipeline(
            jid2, "q.docx", docx_bytes, provider="DeepSeek", api_key="k",
            model="deepseek-chat", target_lang="简体中文", auto_term=False,
            enable_report=False, enable_review=False, enable_annotate=False,
            translation_theory="目的论 (Skopos Theory)", user_glossary=user_glossary,
            strict_terminology_governance=True)
        assert state2["p2_done"], "导入锁定术语后不应被冻结门禁卡住"
        assert state2["profile_done"], "严格术语治理应执行文档画像"

        # 实践报告属于输出配置，不能隐式开启画像或术语冻结门禁。
        core.generate_mti_report = lambda *args, **kwargs: "# 测试实践报告"
        jid3 = "qm000000000000003"
        state3 = core.run_job_pipeline(
            jid3, "q.docx", docx_bytes, provider="DeepSeek", api_key="k",
            model="deepseek-chat", target_lang="简体中文", auto_term=False,
            enable_report=True, enable_review=False, enable_annotate=False,
            translation_theory="自动推荐", user_glossary=[],
            strict_terminology_governance=False)
        assert state3["p2_done"] and state3["p3_done"], \
            "开启实践报告后应完成翻译与报告"
        assert state3["profile_done"] and state3["understanding_done"] \
            and not state3["quality_mode"], \
            "实践报告不应控制文档理解或严格术语治理"
    finally:
        core.call_llm = original_llm
        core.generate_mti_report = original_report
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)
    print("  ✓ 术语治理语义（与实践报告解耦；仅有锁定术语时免冻结）")


def test_translation_memory_switch():
    tmp = Path(tempfile.mkdtemp(prefix="transpraxis-tm-switch-"))
    old_dir = core.OUTPUT_DIR
    old_llm = core.call_llm
    core.OUTPUT_DIR = tmp
    try:
        source = "Translation memory should be optional."
        core.save_tm({source: {"target": "不应复用的旧译文", "reviewed": True}})

        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            return json.dumps(["本次新译文"])

        core.call_llm = llm
        state = core.new_job_state("tm-off.docx")
        state.update(p1_done=True, paras=[source])
        core.translate_stage(
            state, "tmoff000000000001", [], "DeepSeek", "k", "deepseek-chat",
            "简体中文", "", enable_review=False, use_tm=False)
        assert state["pairs"][0]["target"] == "本次新译文"
        assert not state["pairs"][0]["from_tm"], "关闭翻译记忆后不应复用历史译文"
    finally:
        core.call_llm = old_llm
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)
    print("  ✓ 翻译记忆开关（关闭后不读取历史译文）")


def test_custom_annotation_colors():
    pairs = [{"source": "Skopos theory", "target": "目的论"}]
    annotations = {0: [{"type": "rare", "src_span": [0, 5], "tgt_span": [0, 1]},
                       {"type": "domain", "src_span": [6, 12], "tgt_span": [1, 2]},
                       {"type": "hard", "src_span": [12, 13], "tgt_span": [2, 3]}]}
    buf = core.pairs_to_word(pairs, annotations=annotations,
                             colors={"rare": "FF0000", "domain": "00FF00",
                                     "hard": "0000FF"})
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    for color in ("FF0000", "00FF00", "0000FF"):
        assert f'w:val="{color}"' in xml, f"缺少自定义颜色 {color}"
    assert "FF0000" in xml and "图例" in xml
    print("  ✓ 自定义标注颜色（docx 渲染 + 图例）")


def main():
    test_provider_registry_sane()
    test_custom_relay_base_url()
    test_provider_probe()
    test_fetch_provider_models()
    test_exchange_formats()
    test_mode_semantics()
    test_translation_memory_switch()
    test_custom_annotation_colors()
    print("提供商 / 交换格式 / 模式 / 颜色测试通过 ✅")


if __name__ == "__main__":
    main()
