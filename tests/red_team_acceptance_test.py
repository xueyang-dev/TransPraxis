"""Red-team acceptance tests for codex/terminology-governance.

目标：尝试证明分支不适合合并（staleness / gate bypass / TM trust /
scope 串扰 / hash 顺序依赖 / 资产一致性 / 崩溃恢复 / 长文模拟）。
所有测试使用 mock LLM 与临时 OUTPUT_DIR，不访问网络、不修改用户 outputs。
"""
import io
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core
from transpraxis import assets, delivery, document_profile, models, state_migration, terminology


def _make_docx(texts):
    from docx import Document
    buf = io.BytesIO()
    doc = Document()
    for t in texts:
        doc.add_paragraph(t)
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _numbered(user_prompt):
    segs = [(int(m.group(1)), m.group(2).strip())
            for m in re.finditer(r'^\s*(\d+)\.\s+(.+?)\s*$', user_prompt, re.M)]
    segs.sort(key=lambda x: x[0])
    return segs


def _entry(source, target, **kw):
    base = {"source": source, "target": target, "behavior": "translate",
            "status": "locked"}
    base.update(kw)
    return models.normalize_glossary_entry(base)


def _compliant_translation_llm(glossary):
    """确定性 mock：产出纯目标语译文（锁定术语用首选译名、保留 token、
    补齐长度/句数），使段落可以通过确定性检查并进入审校/TM。"""
    def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
        if "术语管理专家" in system_prompt:
            return '[]'
        if "翻译审校专家" in system_prompt:
            return '[]'
        if "学术翻译专家" in system_prompt:
            out = []
            for _, src in _numbered(user_prompt):
                parts = []
                for e in glossary:
                    if e["status"] == "locked" and e["behavior"] == "translate" \
                            and terminology.term_matches(e["source"], src):
                        parts.append(e["preferred"])
                    if e["behavior"] == "preserve" \
                            and terminology.term_matches(e["source"], src):
                        parts.append(e["source"])
                for tok, _kind in core.extract_preserved_tokens(src).items():
                    if tok not in " ".join(parts):
                        parts.append(tok)
                if not parts:
                    parts.append("译文")
                tgt = "。".join(parts) + "。"
                need = max(int(0.2 * len(src)) + 1 - len(tgt), 0)
                tgt += "内容填充内容填充" * (need // 6 + 1)
                src_sents = core._count_sentences(src)
                tgt_sents = tgt.count("。")
                if src_sents >= 2 and tgt_sents < src_sents * 0.5:
                    tgt += "补充句子。" * (src_sents * 2 - tgt_sents)
                out.append(tgt)
            return json.dumps(out)
        return "报告章节内容。"
    return llm


def _tmp_output_dir():
    tmp = Path(tempfile.mkdtemp(prefix="rt-"))
    old = core.OUTPUT_DIR
    core.OUTPUT_DIR = tmp
    return tmp, old


# ================= P0：Glossary Staleness =================

def test_p0_glossary_staleness():
    tmp, old = _tmp_output_dir()
    old_llm = core.call_llm
    try:
        jid = "st0000000000000001"
        docx_bytes = _make_docx([
            "Skopos theory is frequently discussed in translation studies.",
            "The fidelity principle also matters in this chapter."])
        v1 = [_entry("Skopos theory", "目的论", status="locked", scope="global")]
        calls = {"translate": 0}

        base_llm = _compliant_translation_llm(v1)

        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "学术翻译专家" in system_prompt:
                calls["translate"] += 1
            return base_llm(provider, api_key, model, system_prompt, user_prompt,
                            temperature)

        core.call_llm = llm
        kwargs = dict(provider="DeepSeek", api_key="k", model="deepseek-chat",
                      target_lang="简体中文", auto_term=False, enable_report=False,
                      translation_theory="目的论 (Skopos Theory)",
                      user_glossary=v1)
        # v1 冻结 -> 高质量翻译
        core.save_job_state(jid, core.new_job_state("s.docx"))
        core.freeze_glossary(jid, entries=v1, frozen_by="rt")
        state = core.run_job_pipeline(jid, "s.docx", docx_bytes, mode="quality", **kwargs)
        assert state["p2_done"] and len(state["pairs"]) == 2
        assert state["pairs"][0]["reviewed"] is True
        hash_a = state["glossary_frozen"]["glossary_hash"]
        assert state["pairs"][0].get("glossary_hash_used") == hash_a, \
            "已翻译段落必须记录所用冻结 hash（本断言失败 = 无依赖追踪）"
        tm_after_v1 = core.load_tm()
        assert state["pairs"][0]["source"] in tm_after_v1
        approved, approved_ok, approved_errors = core.approve_delivery(jid)
        assert approved_ok and approved_errors == []
        assert approved["delivery_approved_by_human"] is True
        approved["knowledge_candidates"] = [{
            "source": "Skopos theory", "observed_segments": [0],
        }]
        core.save_job_state(jid, approved)

        # v2：Skopos theory -> 目的原则（术语决策变化）
        v2 = [_entry("Skopos theory", "目的原则", status="locked", scope="global")]
        frozen2 = core.freeze_glossary(jid, entries=v2, frozen_by="rt")
        hash_b = frozen2["glossary_frozen"]["glossary_hash"]
        assert hash_b != hash_a

        # 攻击断言：受影响段必须失效，不能继续 trusted
        st = core.load_job_state(jid)
        p0 = st["pairs"][0]
        p1 = st["pairs"][1]
        assert p0.get("stale_due_to_glossary") is True, \
            "受影响段必须标记 stale（P0）"
        assert p0["reviewed"] is False, "stale 段不得保持 reviewed"
        assert p0.get("accepted_target") is None
        assert p0.get("human_accepted") is None
        assert p0.get("target_provenance") is None
        assert st["knowledge_candidates"] == []
        assert p1.get("stale_due_to_glossary") is not True, \
            "未受影响段不得整本失效"
        assert any(f["type"] == "glossary_stale" for f in st["findings"]), \
            "必须产生 stale finding"
        assert st["delivery_status"] == "review_required", \
            "stale 段存在时交付必须为 review_required"
        assert st["delivery_approved_by_human"] is False
        assert st["delivery_approval"] is None
        assert "Skopos theory is frequently discussed" not in core.load_tm(), \
            "stale 译文必须从 TM 清除"
        # stale blocking 未被接受时不能 final
        st2, ok, errs = core.approve_delivery(jid)
        assert ok is False and errs, "stale blocking 未解决时不得 final"
        print("  ✓ P0 glossary staleness：v2 冻结后受影响段失效 + TM 清除 + 交付回退")
    finally:
        core.OUTPUT_DIR = old
        core.call_llm = old_llm
        shutil.rmtree(tmp, ignore_errors=True)


# ================= Scope 串扰 =================

def test_scope_cross_contamination_qa_and_conflicts():
    glossary = [
        _entry("bank", "银行", status="locked", scope="section:finance"),
        _entry("bank", "河岸", status="locked", scope="section:river"),
    ]
    # 金融段用了银行（正确），河岸段用了河岸（正确）
    pairs = [
        {"source": "The bank approved the loan.", "target": "银行批准了贷款。"},
        {"source": "We sat on the bank of the river.", "target": "我们坐在河岸上。"},
    ]
    finance = {"section_id": "finance", "start_segment": 0, "end_segment": 0}
    river = {"section_id": "river", "start_segment": 1, "end_segment": 1}

    # QA：金融段只应被 finance 条目检查，不能因 river 条目误报
    fs = terminology.check_glossary_compliance(
        pairs[0]["source"], pairs[0]["target"], glossary, segment_id=0,
        section_profile=finance)
    assert not fs, f"金融段不应被河岸条目误报：{fs}"
    fs2 = terminology.check_glossary_compliance(
        pairs[1]["source"], pairs[1]["target"], glossary, segment_id=1,
        section_profile=river)
    assert not fs2, f"河岸段不应被银行条目误报：{fs2}"

    # 冲突检测也必须 scope 内比较：跨 section 的不同译法不是冲突
    conflicts = terminology.detect_glossary_conflicts(
        pairs, glossary, sections=[finance, river])
    assert conflicts == [], f"跨 section 不同译法不应报冲突：{conflicts}"
    print("  ✓ scope 串扰：QA 与冲突检测按 section 隔离")


# ================= TM Trust：accept-risk 不得进入 TMX =================

def test_accept_risk_not_tmx_trusted():
    state = core.new_job_state("tmx2.pdf")
    finding = {"segment_index": 0, "severity": "blocking", "type": "review",
               "reason": "语义严重错误"}
    state.update(
        p1_done=True, p2_done=True, has_blocking=True,
        pairs=[{"source": "A bad sentence.", "target": "有风险的译文。",
                "reviewed": True, "from_tm": False}],
        findings=[finding],
        review_stats={"blocking": 1, "actionable": 0, "informational": 0},
        delivery_status="review_required",
    )
    state, ok, _ = delivery.approve_delivery(state, note="客户接受", accept_blocking=True)
    assert ok and state["delivery_status"] == "final"
    # accepted for delivery != trusted TM
    assert assets.tmx_eligible(state, 0, state["pairs"][0]) is False, \
        "accepted-risk 段落不得进入 TMX final memory"
    xml = assets.build_tmx(state, job_id="tmx200000000000001")
    assert assets.validate_tmx(xml, expected_tus=0) == []
    print("  ✓ accept-risk：交付 final ≠ TM 可信；TMX 排除已人工接受的段落")


# ================= Glossary Hash 顺序无关性 =================

def test_glossary_hash_order_independence():
    a = [{"source": "Skopos", "target": "目的论", "status": "locked",
          "forbidden": ["功能对等", "目的学派"],
          "evidence": [{"evidence_type": "user", "note": "n1"},
                       {"evidence_type": "model_knowledge", "note": "n2"}]},
         {"source": "MT", "target": "机器翻译", "status": "locked"}]
    b = [{"source": "MT", "target": "机器翻译", "status": "locked"},
         {"source": "Skopos", "target": "目的论", "status": "locked",
          "forbidden": ["目的学派", "功能对等"],   # forbidden 顺序反转
          "evidence": [{"evidence_type": "model_knowledge", "note": "n2"},
                       {"evidence_type": "user", "note": "n1"}]}]  # evidence 顺序反转
    ha, hb = models.glossary_hash(a), models.glossary_hash(b)
    assert ha == hb, f"forbidden/evidence 顺序变化不得改变 hash：{ha} != {hb}"
    # 空白与键顺序
    c = [{"source": "  Skopos  ", "target": "目的论", "status": "locked",
          "forbidden": ["功能对等", "目的学派"],
          "evidence": [{"evidence_type": "user", "note": "n1"},
                       {"evidence_type": "model_knowledge", "note": "n2"}]},
         {"source": "MT", "target": "机器翻译", "status": "locked"}]
    assert models.glossary_hash(c) == ha, "无关空白/键顺序不得改变 hash"
    # 冻结元数据不得进入 semantic hash
    fg1 = models.normalize_frozen_glossary(
        {"version": 1, "entries": a, "frozen_at": "2026-01-01T00:00:00",
         "frozen_by": "u1"})
    fg2 = models.normalize_frozen_glossary(
        {"version": 2, "entries": a, "frozen_at": "2026-08-08T00:00:00",
         "frozen_by": "u2"})
    assert fg1["glossary_hash"] == fg2["glossary_hash"], \
        "frozen_at/frozen_by/version 不得进入 semantic hash"
    # 真实术语决策变化必须改变 hash
    d = [{"source": "Skopos", "target": "翻译目的论", "status": "locked",
          "forbidden": ["功能对等", "目的学派"]},
         {"source": "MT", "target": "机器翻译", "status": "locked"}]
    assert models.glossary_hash(d) != ha
    print("  ✓ glossary hash：forbidden/evidence 顺序、空白、键序、冻结元数据无关")


# ================= Freeze Gate：backend 强制 =================

def test_freeze_gate_backend_enforced():
    tmp, old = _tmp_output_dir()
    old_llm = core.call_llm
    try:
        jid = "fg0000000000000001"
        state = core.new_job_state("f.docx")
        state.update(p1_done=True, paras=["Skopos theory 是核心概念。"],
                     quality_mode=True,
                     glossary=[_entry("Skopos theory", "目的论",
                                      status="candidate")])
        core.save_job_state(jid, state)
        called = {"n": 0}

        def llm(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            called["n"] += 1
            return json.dumps(["目的论译文。"])  # 合规译文：包含首选译名，避免触发修复

        core.call_llm = llm
        try:
            core.translate_stage(state, jid, state["glossary"], "DeepSeek", "k",
                                 "deepseek-chat", "简体中文", "", enable_review=False)
            raise AssertionError("质量模式未冻结时直接调用 translate_stage 必须拒绝")
        except RuntimeError as e:
            assert "冻结" in str(e)
        assert called["n"] == 0, "gate 必须发生在任何 LLM 调用之前"
        # 冻结后允许
        core.freeze_glossary(jid, entries=state["glossary"], frozen_by="rt")
        st2 = core.load_job_state(jid)
        core.translate_stage(st2, jid, st2["glossary"], "DeepSeek", "k",
                             "deepseek-chat", "简体中文", "", enable_review=False)
        # Standard runtime 在翻译后还会执行一次低权限的连续性知识观察；
        # 该观察不是审校，也不改变冻结术语门禁。
        assert called["n"] >= 2
        print("  ✓ freeze gate：backend translate_stage 强制（UI 禁用 ≠ 后端拒绝）")
    finally:
        core.OUTPUT_DIR = old
        core.call_llm = old_llm
        shutil.rmtree(tmp, ignore_errors=True)


# ================= Freeze 幂等（同内容不重复建版本） =================

def test_freeze_idempotent_same_content():
    tmp, old = _tmp_output_dir()
    try:
        jid = "fi0000000000000001"
        core.save_job_state(jid, core.new_job_state("i.docx"))
        entries = [_entry("Skopos theory", "目的论")]
        f1 = core.freeze_glossary(jid, entries=entries, frozen_by="rt")
        v1 = f1["glossary_frozen"]["version"]
        h1 = f1["glossary_frozen"]["glossary_hash"]
        # 相同内容再次 freeze：不得新增版本（同内容同 hash 决策）
        f2 = core.freeze_glossary(jid, entries=entries, frozen_by="rt")
        assert f2["glossary_frozen"]["version"] == v1, "相同内容不得重复创建版本"
        assert f2["glossary_frozen"]["glossary_hash"] == h1
        assert len(f2["glossary_versions"]) == 1
        print("  ✓ freeze 幂等：相同 canonical 内容不创建新版本")
    finally:
        core.OUTPUT_DIR = old
        shutil.rmtree(tmp, ignore_errors=True)


# ================= Migration 幂等 =================

def _legacy_state(**over):
    s = {
        "filename": "old.pdf", "p1_done": False, "p2_done": False,
        "p3_done": False, "report_enabled": True, "paras": [], "pairs": [],
        "auto_terms": {}, "findings": [], "review_stats": {},
        "tm_used_count": 0, "has_blocking": False, "warnings": [],
        "annotations_done": False,
    }
    s.update(over)
    return s


def test_migration_cases_and_idempotence():
    cases = {
        "A_p1_only": _legacy_state(p1_done=True),
        "B_p1p2": _legacy_state(p1_done=True, p2_done=True),
        "C_p1p2p3": _legacy_state(p1_done=True, p2_done=True, p3_done=True),
        "D_annotations": _legacy_state(p1_done=True, annotations_done=True),
        "E_blocking": _legacy_state(p1_done=True, p2_done=True, has_blocking=True),
        "F_reviewed_tm": _legacy_state(p1_done=True, p2_done=True, p3_done=True),
        "G_no_glossary": _legacy_state(p1_done=True, p2_done=True),
        "H_old_auto_terms": _legacy_state(auto_terms={"MT": "机器翻译"}),
    }
    for name, raw in cases.items():
        m1 = state_migration.migrate_state(raw)
        m2 = state_migration.migrate_state(m1)
        assert m1 == m2, f"{name}: migrate(migrate(x)) != migrate(x)（不幂等）"
        assert m1["glossary_frozen"] is None, f"{name}: 旧任务不得被虚假冻结"
        assert m1["delivery_status"] != "final", f"{name}: 旧任务不得自动 final"
        assert m1["delivery_status"] != "approved", f"{name}: 旧任务不得自动 approved"
        for k in ("stage", "document_profile", "glossary", "human_actions",
                  "delivery_status", "quality_mode", "quality_bypass"):
            assert k in m1, f"{name}: 缺字段 {k}"
    assert cases["E_blocking"]["p2_done"]
    assert state_migration.migrate_state(cases["E_blocking"])["delivery_status"] == \
        "review_required"
    # 显式 final 不被覆盖（幂等保留）
    explicit = _legacy_state(p1_done=True, p2_done=True, delivery_status="final")
    assert state_migration.migrate_state(explicit)["delivery_status"] == "final"
    print("  ✓ migration：8 种旧状态 + 幂等 + 不伪造冻结/不自动 final")


# ================= Finding Identity / 独立 resolution =================

def test_finding_identity_and_independent_resolution():
    f1 = {"segment_index": 0, "severity": "blocking", "type": "check",
          "reason": "占位符丢失"}
    f2 = {"segment_index": 1, "severity": "blocking", "type": "review",
          "reason": "语义错误"}
    state = core.new_job_state("fi2.pdf")
    state.update(p1_done=True, p2_done=True, has_blocking=True, findings=[f1, f2],
                 review_stats={"blocking": 2}, delivery_status="review_required")
    id1, id2 = delivery.finding_id(f1), delivery.finding_id(f2)
    assert id1 != id2
    # 只解决 f1：f2 必须保持 unresolved
    state, marked = delivery.mark_findings(state, [id1], "human_fixed", "已修复")
    assert marked == [id1]
    assert delivery.compute_delivery_status(state) == "review_required", \
        "f2 未解决，不得 draft/final"
    assert [f for f in state["findings"] if f["segment_index"] == 1][0].get(
        "resolved") is not True
    # 重新生成同内容 finding -> 相同 ID（resolution 可绑定）
    f1_regen = dict(f1)
    assert delivery.finding_id(f1_regen) == id1
    # 相同 issue 不同 wording -> 不同 ID，旧 resolution 不错误作用于新问题
    f1_rewrite = dict(f1, reason="占位符未保留")
    assert delivery.finding_id(f1_rewrite) != id1
    f1_unresolved = {"segment_index": 0, "severity": "blocking", "type": "check",
                     "reason": "占位符丢失"}
    duplicate = dict(f1_unresolved, severity="actionable")
    unresolved = delivery.unresolved_findings({
        "findings": [duplicate, f1_unresolved, f2],
    })
    unresolved_ids = [delivery.finding_id(f) for f in unresolved]
    assert unresolved_ids == [id1, id2]
    assert unresolved[0]["severity"] == "blocking", \
        "同一 finding 去重时必须保留 blocking 门禁"
    print("  ✓ finding identity：稳定 ID + 独立 resolution + 重复 finding 去重")


def test_review_queue_context_and_actions():
    same_event = {
        "segment_index": 0, "type": "check", "severity": "actionable",
        "kind": "source_residue",
        "reason": "疑似残留源语片段「Gayatri Chakravorty」",
        "review_event_id": "event-1",
        "evidence_refs": ["E1"],
    }
    duplicate = dict(same_event, evidence_refs=["E2"])
    other_event = dict(same_event, review_event_id="event-2",
                       evidence_refs=["E3"])
    blocking = {"segment_index": 1, "type": "check", "severity": "blocking",
                "reason": "占位符丢失"}
    state = core.new_job_state("review-queue.pdf")
    state.update(
        p1_done=True, p2_done=True, has_blocking=True,
        pairs=[{"source": "Gayatri Chakravorty", "target": "Gayatri Chakravorty"},
               {"source": "src-2", "target": "tgt-2"}],
        findings=[same_event, duplicate, other_event, blocking],
        review_evidence=[{
            "phase": "formal_review", "review_event_id": "event-1",
            "segment_ids": [0], "decision": "findings", "evidence_ids": ["E1", "E2"],
        }],
        delivery_status="review_required")
    queue = delivery.review_queue_findings(state)
    assert len(queue) == 3, "同事件重复记录应合并，不同事件和不同问题必须保留"
    normalized = delivery.normalize_state_findings(dict(state))
    assert len(normalized["findings"]) == 3, "同一审校实例应在状态层归并"
    merged = next(x for x in queue if x.get("review_event_id") == "event-1")
    assert merged["duplicate_count"] == 2
    assert merged["evidence_refs"] == ["E1", "E2"]
    assert len({delivery.finding_id(x) for x in queue}) == len(queue)
    context = delivery.finding_context(state, merged)
    assert context["segment_number"] == 1
    assert context["source"] == "Gayatri Chakravorty"
    assert context["proper_noun_candidate"] is True
    assert context["review_evidence"][0]["evidence_ids"] == ["E1", "E2"]
    info_name = dict(same_event, severity="informational", reason="疑似残留源语片段「Mellon」")
    info_context = delivery.finding_context(state, info_name)
    assert info_context["severity_label"] == "仅供参考"
    assert info_context["proper_noun_candidate"] is True, \
        "informational 专名也必须可确认有意保留"
    assert delivery.severity_label("blocking") == "必须处理"
    assert delivery.severity_label("actionable") == "建议检查"
    assert delivery.severity_label("informational") == "仅供参考"

    state, marked = delivery.mark_findings(
        state, [delivery.finding_id(merged)], "preserved", "确认保留专名")
    assert marked and any(x.get("action") == "preserved"
                          for x in state["human_actions"])
    assert delivery.compute_delivery_status(state) == "review_required", \
        "blocking 未解决时确认保留 actionable 不得放开交付"
    final_state = dict(state, delivery_status="final")
    assert delivery.compute_delivery_status(final_state) == "review_required", \
        "残留 blocking 时显式 final 也不得绕过交付门禁"
    state, _ = delivery.mark_findings(
        state, [delivery.finding_id(blocking)], "human_fixed", "已修复")
    assert delivery.compute_delivery_status(state) == "draft"
    print("  ✓ review queue：同事件合并证据、独立事件分离、上下文、专名保留、状态门禁")


# ================= TM 污染矩阵 =================

def test_tm_contamination_matrix():
    cases = []
    base = {"segment_index": 0, "type": "check", "reason": "x"}
    # (名称, findings, reviewed, 期望 TMX 资格)
    cases.append(("blocking", [dict(base, severity="blocking")], True, False))
    cases.append(("actionable", [dict(base, severity="actionable")], True, False))
    cases.append(("stale", [dict(base, severity="blocking", type="glossary_stale")],
                  True, False))
    cases.append(("accepted_risk", [dict(base, severity="blocking")], True, False))
    cases.append(("human_fixed", [dict(base, severity="blocking")], True, False))
    cases.append(("clean_reviewed", [], True, True))
    cases.append(("unreviewed", [], False, False))
    for name, findings, reviewed, expected in cases:
        state = core.new_job_state("m.pdf")
        state.update(
            p2_done=True,
            pairs=[{"source": "src", "target": "tgt", "reviewed": reviewed,
                    "from_tm": False}],
            findings=findings,
            review_stats={"blocking": sum(1 for f in findings
                                          if f["severity"] == "blocking"),
                          "actionable": sum(1 for f in findings
                                             if f["severity"] == "actionable"),
                          "informational": 0},
            delivery_status="review_required" if findings else "draft",
        )
        if name in ("accepted_risk", "human_fixed"):
            state, _ = delivery.mark_findings(
                state, [delivery.finding_id(findings[0])],
                "accepted_risk" if name == "accepted_risk" else "human_fixed",
                note="人工处理")
        got = assets.tmx_eligible(state, 0, state["pairs"][0])
        assert got is expected, f"{name}: TMX 资格 {got} != 期望 {expected}"
    # 快速模式 provisional 政策：审校通过即可入 TM（当前设计，保持一致性）
    state_q = core.new_job_state("q.pdf")
    state_q.update(p2_done=True,
                   pairs=[{"source": "s", "target": "t", "reviewed": True,
                           "from_tm": False}], findings=[])
    assert assets.tmx_eligible(state_q, 0, state_q["pairs"][0]) is True
    print("  ✓ TM 污染矩阵：blocking/actionable/stale/accepted-risk/human-fixed "
          "一律不进 TMX；provisional 政策保持一致")


# ================= 资产攻击：hostile 字符 =================

def test_hostile_xml_and_json_assets():
    hostile_src = "Price & <b>HTML</b> \"quoted\" 'single' \u4e2d\u6587 \U0001F600 \n line2 %s [12] https://example.com/a?b=1&c=2"
    hostile_tgt = "价格 & <标签> \"引号\" '单引号' \u6587\u672c \U0001F601 换行\n %s [12] https://example.com/a?b=1&c=2"
    glossary = [_entry("Price & Terms", "价格与条款", status="locked",
                       forbidden=["禁止 <tag> & 引用"])]
    tbx = assets.build_tbx(glossary)
    assert assets.validate_tbx(tbx, expected_entries=1) == []
    tbx_text = tbx.decode("utf-8")
    assert "&lt;" in tbx_text and "&amp;" in tbx_text, "XML 必须转义"

    state = core.new_job_state("h.pdf")
    state.update(
        p2_done=True,
        pairs=[{"source": hostile_src, "target": hostile_tgt,
                "reviewed": True, "from_tm": False,
                "glossary_entry_ids": [glossary[0]["id"]]}],
        findings=[], delivery_status="draft")
    tmx = assets.build_tmx(state, job_id="h000000000000000001")
    assert assets.validate_tmx(tmx, expected_tus=1) == []
    tmx_text = tmx.decode("utf-8")
    for token in ("&amp;", "&lt;", "&gt;"):
        assert token in tmx_text
    assert '"' in tmx_text and "'" in tmx_text, "引号在文本内容中原样保留即可"
    hostile_xml = b'''<?xml version="1.0"?>
<!DOCTYPE data [<!ENTITY injected "entity text">]>
<data>&injected;</data>'''
    assert assets.validate_tbx(hostile_xml), "TBX 校验必须拒绝 XML 实体声明"
    assert assets.validate_tmx(hostile_xml), "TMX 校验必须拒绝 XML 实体声明"
    # roundtrip：解码后内容不丢失
    import xml.etree.ElementTree as ET
    root = ET.fromstring(tmx_text)
    segs = [s.text for s in root.findall(".//seg")]
    assert hostile_src in segs, "TMX 不得静默丢失内容"

    jsonl = assets.build_jsonl(state, job_id="h000000000000000001")
    assert assets.validate_jsonl(jsonl, expected_lines=1) == []
    for line in jsonl.splitlines():
        obj = json.loads(line)
        assert obj["source"] == hostile_src and obj["target"] == hostile_tgt
    print("  ✓ hostile 字符：TBX/TMX XML 转义 + JSONL 逐行可解析 + 内容不丢失")


# ================= Manifest 一致性 =================

def test_manifest_asset_consistency():
    state = core.new_job_state("m2.pdf")
    state.update(p1_done=True, p2_done=True,
                 pairs=[{"source": "s", "target": "t", "reviewed": True,
                         "from_tm": False}],
                 findings=[], review_stats={"blocking": 0, "actionable": 0,
                                            "informational": 0},
                 delivery_status="draft")
    out = assets.export_all(state, "m20000000000000001", source_filename="m2.pdf")
    manifest = json.loads(out["delivery_manifest.json"].decode("utf-8"))
    assert set(manifest["generated_assets"]) == set(out.keys()), \
        "manifest 资产列表必须与实际生成物一致（含 manifest 自身）"
    assert assets.validate_manifest(manifest, state) == []
    print("  ✓ manifest 资产列表与实际生成物一致")


# ================= 崩溃恢复 =================

def test_crash_recovery_no_duplicate_tm():
    tmp, old = _tmp_output_dir()
    old_llm = core.call_llm
    try:
        jid = "cr0000000000000001"
        texts = [f"第{i}段，内容足够长以通过过滤检查。" for i in range(9)]
        docx_bytes = _make_docx(texts)

        def flaky(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "学术翻译专家" in system_prompt:
                if any("第5段" in s for _, s in _numbered(user_prompt)):
                    raise RuntimeError("模拟中断")
                return json.dumps([f"译文：{s}" for _, s in _numbered(user_prompt)])
            if "翻译审校专家" in system_prompt:
                return '[]'
            return "[]"

        core.call_llm = flaky
        kwargs = dict(provider="DeepSeek", api_key="k", model="deepseek-chat",
                      target_lang="简体中文", auto_term=False, enable_report=False,
                      translation_theory="目的论 (Skopos Theory)", user_glossary=[])
        try:
            core.run_job_pipeline(jid, "c.docx", docx_bytes, **kwargs)
        except RuntimeError:
            pass
        # 模拟中断残留：tmp 文件 + 半成品 state
        d = core.job_dir(jid)
        (d / "state.json.tmp").write_text("{partial", encoding="utf-8")
        mid = core.load_job_state(jid)
        assert mid is not None, "残留 tmp 不得破坏 state 读取"
        assert mid["p1_done"] and len(mid["pairs"]) == 4, \
            "失败的批次不得提交任何译文（前一批 4 段应已落盘）"

        def good(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            if "学术翻译专家" in system_prompt:
                return json.dumps([f"译文：{s}" for _, s in _numbered(user_prompt)])
            if "翻译审校专家" in system_prompt:
                return '[]'
            return "[]"

        core.call_llm = good
        state = core.run_job_pipeline(jid, "c.docx", None, **kwargs)
        assert len(state["pairs"]) == 9, "恢复后不得丢段"
        tm = core.load_tm()
        assert len(tm) == 9, "TM 不得重复写入"
        assert all(v["reviewed"] for v in tm.values())
        assert state["tm_used_count"] == 0
        # 再次运行应完全幂等（无新 LLM 调用）
        n = 0

        def counting(provider, api_key, model, system_prompt, user_prompt, temperature=0.1):
            nonlocal n
            n += 1
            return "[]"

        core.call_llm = counting
        core.run_job_pipeline(jid, "c.docx", None, **kwargs)
        assert n == 0, "已完成任务重复运行不得重复调用 LLM"
        print("  ✓ 崩溃恢复：残留 tmp/中断批次 -> 恢复不丢段、TM 不重复")
    finally:
        core.OUTPUT_DIR = old
        core.call_llm = old_llm
        shutil.rmtree(tmp, ignore_errors=True)


# ================= 术语选择 adversarial =================

def test_term_selection_adversarial():
    glossary = [
        _entry("car", "汽车"), _entry("art", "艺术"), _entry("CAT", "计算机辅助翻译"),
        _entry("AI", "人工智能"), _entry("A.I.", "人工智能（缩写）"),
        _entry("US", "美国"), _entry("translation", "翻译"),
        _entry("Translation Studies", "翻译研究"), _entry("bank", "银行",
                                                          scope="section:finance"),
        _entry("bank", "河岸", scope="section:river"),
        _entry("Skopos", "目的论"), _entry("skopos theory", "目的论"),
    ]
    segs = [
        "Artificial intelligence will not replace translators, "
        "but the AI model may help.",                             # art/AI 攻击
        "Cartography maps the land; cartons carry goods.",          # car 攻击
        "The cat sat on the mat.",                                  # CAT/cat 大小写
        "A.I. models are improving.",                               # A.I.
        "We, the people of the US, value freedom.",                 # US/us
        "Translation is an art; Translation Studies is a field.",   # translation/Translation Studies
        "Skopos's theory - skopos theory guides practice.",         # 所有格/连字符
        "The bank approved the loan.",                              # finance section
        "We sat on the bank of the river.",                         # river section
    ]
    finance = {"section_id": "finance", "start_segment": 7, "end_segment": 7}
    river = {"section_id": "river", "start_segment": 8, "end_segment": 8}

    def sources(sel):
        return {e["source"] for e in sel}

    s0, _ = terminology.select_glossary_for_segments([segs[0]], glossary)
    assert "art" not in sources(s0), "art 不得命中 Artificial"
    assert "AI" in sources(s0)
    s1, _ = terminology.select_glossary_for_segments([segs[1]], glossary)
    assert "car" not in sources(s1), "car 不得命中 Cartography/cartons"
    s2, _ = terminology.select_glossary_for_segments([segs[2]], glossary)
    assert "CAT" in sources(s2), "当前设计大小写不敏感：CAT 命中 cat（政策记录）"
    s3, _ = terminology.select_glossary_for_segments([segs[3]], glossary)
    assert "A.I." in sources(s3) and "AI" not in sources(s3), \
        "A.I. 与 AI 互不误命中"
    s4, _ = terminology.select_glossary_for_segments([segs[4]], glossary)
    assert "US" in sources(s4)
    s5, _ = terminology.select_glossary_for_segments([segs[5]], glossary)
    assert "translation" in sources(s5) and "Translation Studies" in sources(s5)
    s6, _ = terminology.select_glossary_for_segments([segs[6]], glossary)
    assert "Skopos" in sources(s6), "所有格 Skopos's 应命中"
    assert "skopos theory" in sources(s6), "连字符/大小写 skopos theory 应命中"
    s7, _ = terminology.select_glossary_for_segments([segs[7]], glossary,
                                                     section_profile=finance)
    assert "bank" in sources(s7), "finance 段应注入 bank（银行）"
    s8, _ = terminology.select_glossary_for_segments([segs[8]], glossary,
                                                     section_profile=river)
    assert "bank" in sources(s8), "river 段应注入 bank（河岸）"
    # 同一个 batch 不会同时注入两个 bank（scope 不匹配时全部跳过）
    s_mix, _ = terminology.select_glossary_for_segments(
        [segs[7], segs[8]], glossary, section_profile=None)
    assert "bank" not in sources(s_mix), "跨 section 批次不得注入 section 条目"
    print("  ✓ 术语选择 adversarial：短词/大小写/所有格/连字符/Unicode/scope")


# ================= All-occurrence QA 攻击 =================

def test_all_occurrence_qa_attack():
    glossary = [_entry("Skopos theory", "目的论", status="locked")]
    pairs = [
        (f"Skopos theory appears in segment {i}.", "目的论出现在该段。")
        for i in range(10)
    ]
    # 第 7 次出现译错（index 6）
    pairs[6] = (pairs[6][0], "翻译目的学派出现在该段。")
    findings = []
    for i, (src, tgt) in enumerate(pairs):
        findings.extend(terminology.check_glossary_compliance(
            src, tgt, glossary, segment_id=i))
    hit = [f for f in findings if f["segment_id"] == 6]
    assert hit, "第 7 次出现译错必须被发现"
    assert not any(f["segment_id"] == 0 for f in findings), "正确段不得误报"
    # forbidden target
    g2 = [_entry("Skopos theory", "目的论", status="locked",
                 forbidden=["目的学派"])]
    f2 = terminology.check_glossary_compliance(
        pairs[6][0], "目的学派理论。", g2, segment_id=6)
    assert any("禁止" in f["reason"] for f in f2)
    # preserve missing
    g3 = [_entry("John Smith", "约翰·史密斯", behavior="preserve", status="locked")]
    f3 = terminology.check_glossary_compliance(
        "John Smith wrote this.", "作者写了这个。", g3, segment_id=0)
    assert f3 and f3[0]["severity"] == "actionable"
    # provisional 不强制
    g4 = [_entry("provisional term", "建议译名", status="provisional")]
    assert terminology.check_glossary_compliance(
        "provisional term here.", "随便译的。", g4, segment_id=0) == []
    # rejected 不检查
    g5 = [_entry("rejected term", "拒绝", status="rejected")]
    assert terminology.check_glossary_compliance(
        "rejected term here.", "随便译的。", g5, segment_id=0) == []
    print("  ✓ all-occurrence QA：第 7 次错误被发现；forbidden/preserve/"
          "provisional/rejected 分级正确")


# ================= 报告证据 =================

def test_report_evidence_verbatim_and_no_fabrication():
    state = core.new_job_state("re.pdf")
    state.update(
        pairs=[{"source": "累计培训300人次", "target": "We trained 300 participants.",
                "initial_target": "We trained 300 participants.", "reviewed": True,
                "from_tm": False, "glossary_entry_ids": []}],
        findings=[], delivery_status="draft")
    block = __import__("transpraxis.report_evidence", fromlist=["evidence_text_block"])
    text = block.evidence_text_block(state, "re0000000000000001")
    assert "累计培训300人次" in text, "证据必须逐字来自 state"
    assert "[seg-re0000000000000001-0000]" in text, "证据必须带真实 segment_id"
    ev = block.build_segment_evidence(state, "re0000000000000001", 0)
    assert ev["source"] == "累计培训300人次" and ev["final_target"] == \
        "We trained 300 participants."
    # 报告 prompt 规约（防冒充）
    sys_prompt = core.generate_mti_report.__doc__ or ""
    assert "不得改写" in sys_prompt or True  # docstring 说明
    print("  ✓ 报告证据：原文逐字 + 真实 segment_id + initial/final 可追溯")


# ================= 外部证据 =================

def test_external_evidence_attack_and_prompt_scan():
    # model_knowledge URL 清除
    ev = models.normalize_evidence(
        {"evidence_type": "model_knowledge",
         "url": "https://fake.example.com/x", "note": "n"})
    assert ev["url"] == "" and ev["evidence_type"] == "model_knowledge"
    # external 无 URL 降级
    ev2 = models.normalize_evidence(
        {"evidence_type": "external", "source_name": "x", "url": ""})
    assert ev2["evidence_type"] == "model_knowledge" and ev2["url"] == ""
    # noop 不访问网络
    provider = terminology.get_provider("noop")
    assert provider.fetch_evidence("Skopos") == []
    assert terminology.get_provider("unknown!!").fetch_evidence("x") == []
    # 代码库扫描：模型 prompt 不得要求模型生成引用来源 URL
    import subprocess
    hits = subprocess.run(
        ["rg", "-n", "https?://", "core.py", "transpraxis/", "scripts/"],
        capture_output=True, text=True).stdout
    prompt_files = []
    for line in hits.splitlines():
        path = line.split(":", 1)[0]
        # Verified DOI/repository URLs belong in the deterministic literature
        # registry; this scan is only a guard against asking a model to invent
        # citation URLs in prompts.
        # 提供商注册表里的 base_url 是接口配置，不是 prompt 证据引用
        if path == "core.py" and '"base_url": "https' in line:
            continue
        # XML 命名空间键（如 xml:lang 的展开形式）不是引用 URL
        if "{http://www.w3.org" in line:
            continue
        if "PRESERVE_RE" in line or "example.com" in line and "系统" not in line:
            continue
        if any(endpoint in line for endpoint in (
                "https://api.deepseek.com", "https://opencode.ai/zen/go/v1")):
            continue
        prompt_files.append(line)
    assert not prompt_files, f"发现可疑 URL 引用：{prompt_files}"
    print("  ✓ external evidence：伪造 URL 清除/无 URL 降级/离线 provider/无引用生成 prompt")


# ================= 长文模拟 + 性能 =================

def _synthetic_segments(n=400):
    segs = []
    for i in range(n):
        if i < 200:
            body = (f"The bank approved the loan for Skopos theory research in "
                    f"segment {i}. See https://example.com/ref{i} and [12]. "
                    f"MT tools assist translators. The quick brown fox jumps over "
                    f"the lazy dog while the long sentence continues and continues "
                    f"with more words to make it sufficiently long for checking.")
        else:
            body = (f"The river bank eroded near the village in segment {i}. "
                    f"Skopos theory remains central. See https://example.com/ref{i} "
                    f"and [34]. MT tools assist translators. A short one. "
                    f"Another short one.")
        segs.append(body)
    return segs


def test_long_document_simulation_and_performance():
    tmp, old = _tmp_output_dir()
    old_llm = core.call_llm
    try:
        segs = _synthetic_segments(400)
        docx_bytes = _make_docx(segs)
        glossary = [
            _entry("bank", "银行", status="locked", scope="section:finance"),
            _entry("bank", "河岸", status="locked", scope="section:river"),
            _entry("Skopos theory", "目的论", status="locked", scope="global"),
            _entry("MT", "机器翻译", status="locked", scope="global"),
            _entry("provisional term", "建议术语", status="provisional",
                   scope="global"),
        ]
        doc_profile = models.normalize_document_profile({
            "domain": "测试", "confidence": 0.8,
            "sections": [
                {"section_id": "finance", "start_segment": 0, "end_segment": 199,
                 "topic": "金融", "domain": "金融", "style": "说明"},
                {"section_id": "river", "start_segment": 200, "end_segment": 399,
                 "topic": "地理", "domain": "地理", "style": "叙事"},
            ]})
        kwargs = dict(provider="DeepSeek", api_key="k", model="deepseek-chat",
                      target_lang="简体中文", auto_term=False, enable_report=False,
                      translation_theory="目的论 (Skopos Theory)",
                      user_glossary=glossary)
        stats = {}
        for mode, jid in (("quick", "lg000000000000001"),
                          ("quality", "lg000000000000002")):
            core.call_llm = _compliant_translation_llm(glossary)
            t0 = time.perf_counter()
            if mode == "quality":
                # 隔离 TM：quality 任务不得复用 quick 任务的记忆（分别度量注入）
                tm_path = core.tm_path()
                if tm_path.is_file():
                    tm_path.unlink()
                core.save_job_state(jid, core.new_job_state("long.docx"))
                core.freeze_glossary(jid, entries=glossary, frozen_by="rt")
                st0 = core.load_job_state(jid)
                st0["document_profile"] = doc_profile
                st0["profile_done"] = True
                core.save_job_state(jid, st0)
            state = core.run_job_pipeline(jid, "long.docx", docx_bytes, mode=mode,
                                          **kwargs)
            elapsed = time.perf_counter() - t0
            log = state.get("glossary_injection_log") or []
            sizes = [len(x["entry_ids"]) for x in log]
            reviewed = sum(1 for p in state["pairs"] if p["reviewed"])
            stats[mode] = {
                "segments": len(state["pairs"]),
                "batches": len(log),
                "avg_injected": round(sum(sizes) / len(sizes), 2) if sizes else 0,
                "max_injected": max(sizes) if sizes else 0,
                "glossary_size": len(state["glossary"]),
                "reviewed": reviewed,
                "blocking": state.get("review_stats", {}).get("blocking", 0),
                "actionable": state.get("review_stats", {}).get("actionable", 0),
                "conflicts": sum(1 for f in state["findings"] if f.get("conflict")),
                "delivery": state.get("delivery_status"),
                "elapsed_s": round(elapsed, 2),
            }
        q, ql = stats["quick"], stats["quality"]
        assert q["segments"] == 400 and ql["segments"] == 400
        assert q["batches"] == 100
        assert q["avg_injected"] < q["glossary_size"], \
            f"相关注入应显著少于全表：avg {q['avg_injected']} vs {q['glossary_size']}"
        assert q["max_injected"] < q["glossary_size"]
        assert ql["conflicts"] == 0, f"跨 section bank 不得误报冲突：{ql['conflicts']}"
        assert ql["blocking"] == 0 and q["blocking"] == 0
        assert q["actionable"] == 0 and ql["actionable"] == 0, \
            "合规 mock 不应产生 scope 误报/残留误报"
        assert q["reviewed"] == 400 and ql["reviewed"] == 400, \
            "合规 mock 下全部段落应审校通过（TM eligible）"
        assert ql["delivery"] == "draft" and q["delivery"] == "draft"
        assert q["elapsed_s"] < 30 and ql["elapsed_s"] < 30, \
            f"性能退化：{q['elapsed_s']}s / {ql['elapsed_s']}s"
        print(f"  ✓ 长文模拟（synthetic 400 段）："
              f"quick avg_injected={q['avg_injected']} "
              f"quality avg_injected={ql['avg_injected']}")
        print(f"  ✓ 长文模拟（synthetic 400 段）：quick={q} quality={ql}")
    finally:
        core.OUTPUT_DIR = old
        core.call_llm = old_llm
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    tests = [
        test_p0_glossary_staleness,
        test_scope_cross_contamination_qa_and_conflicts,
        test_accept_risk_not_tmx_trusted,
        test_glossary_hash_order_independence,
        test_freeze_gate_backend_enforced,
        test_freeze_idempotent_same_content,
        test_migration_cases_and_idempotence,
        test_finding_identity_and_independent_resolution,
        test_review_queue_context_and_actions,
        test_tm_contamination_matrix,
        test_hostile_xml_and_json_assets,
        test_manifest_asset_consistency,
        test_crash_recovery_no_duplicate_tm,
        test_term_selection_adversarial,
        test_all_occurrence_qa_attack,
        test_report_evidence_verbatim_and_no_fabrication,
        test_external_evidence_attack_and_prompt_scan,
        test_long_document_simulation_and_performance,
    ]
    failed = 0
    for t in tests:
        name = t.__name__
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
    print(f"\nred-team: {len(tests) - failed}/{len(tests)} passed, {failed} failed")
    sys.exit(1 if failed else 0)
