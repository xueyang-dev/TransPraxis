"""标准资产导出：TBX / TMX / JSONL / delivery_manifest.json。

- TBX：source term、preferred target、forbidden、status、domain、scope、
  note、evidence type（合法 XML + 结构校验）；
- TMX：仅导出“最终译文”或“审校通过且无 blocking/actionable”的段落；
- JSONL：每行一个双语 segment（segment_id/source/target/reviewed/from_tm/
  glossary_entry_ids/findings/delivery_status）；
- delivery_manifest.json：任务级统计与交付信息；
- 所有导出都带条目数量与基本结构校验函数。
"""
from __future__ import annotations

import hashlib
import json
# The standard module is used only to construct XML; parsing uses defusedxml.
import xml.etree.ElementTree as ET  # nosec B405
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from defusedxml.ElementTree import fromstring as safe_xml_fromstring

from . import delivery as _delivery
from . import model_roles
from . import models
from . import translation_target

XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>\n'


# ---------------- 公共工具 ----------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _source_hash(state: Dict[str, Any]) -> str:
    """源文件哈希：优先 source.bin，其次冻结术语表的 source_hash，最后空串。"""
    src = state.get("_source_bin")
    if isinstance(src, bytes) and src:
        return hashlib.sha256(src).hexdigest()
    fg = state.get("glossary_frozen") or {}
    return str(fg.get("source_hash") or "")


def segment_id(job_id: str, index: int) -> str:
    return f"seg-{job_id}-{index:04d}"


# ---------------- TBX ----------------

def build_tbx(glossary: List[models.GlossaryEntry],
              src_lang: str = "en",
              tgt_lang: str = "zh-CN") -> bytes:
    """术语表 -> TBX 2.0 风格 XML。"""
    entries = models.normalize_glossary(glossary)
    root = ET.Element("martif", {"type": "TBX", "xml:lang": src_lang})
    header = ET.SubElement(root, "martifHeader")
    filedesc = ET.SubElement(header, "fileDesc")
    srcd = ET.SubElement(filedesc, "sourceDesc")
    ET.SubElement(srcd, "p").text = "TransPraxis / 译践 glossary export"
    enc = ET.SubElement(header, "encodingDesc")
    ET.SubElement(enc, "p", {"type": "XCSURI"}).text = "TransPraxis / 译践 default XCS"
    text = ET.SubElement(root, "text")
    body = ET.SubElement(text, "body")

    for e in entries:
        term_entry = ET.SubElement(body, "termEntry", {"id": e["id"]})
        # 源术语
        langset_src = ET.SubElement(term_entry, "langSet", {"xml:lang": src_lang})
        tig_src = ET.SubElement(langset_src, "tig")
        ET.SubElement(tig_src, "term").text = e["source"]
        # 目标术语（首选 + 禁止）
        langset_tgt = ET.SubElement(term_entry, "langSet", {"xml:lang": tgt_lang})
        if e["behavior"] == "preserve":
            tig_tgt = ET.SubElement(langset_tgt, "tig")
            ET.SubElement(tig_tgt, "term").text = e["source"]
            ET.SubElement(tig_tgt, "termNote", {"type": "transpraxis:behavior"}).text = "preserve"
        else:
            tig_tgt = ET.SubElement(langset_tgt, "tig")
            ET.SubElement(tig_tgt, "term").text = e["preferred"] or e["target"]
            ET.SubElement(tig_tgt, "termNote", {"type": "termStatus"}).text = e["status"]
            for fb in e["forbidden"]:
                ntig = ET.SubElement(langset_tgt, "ntig")
                grp = ET.SubElement(ntig, "termGrp")
                ET.SubElement(grp, "term").text = fb
                ET.SubElement(grp, "termNote", {"type": "termStatus"}).text = "prohibited"
        # 元数据
        descrip_grp = ET.SubElement(term_entry, "descripGrp")
        if e.get("domain"):
            ET.SubElement(descrip_grp, "descrip", {"type": "subjectField"}).text = e["domain"]
        if e.get("scope"):
            ET.SubElement(descrip_grp, "descrip", {"type": "transpraxis:scope"}).text = e["scope"]
        if e.get("note"):
            ET.SubElement(descrip_grp, "descrip", {"type": "definition"}).text = e["note"]
        ev = (e.get("evidence") or [{}])[0]
        if ev.get("evidence_type"):
            ET.SubElement(descrip_grp, "descrip",
                          {"type": "transpraxis:evidence_type"}).text = ev["evidence_type"]
    return (XML_DECL + ET.tostring(root, encoding="unicode")).encode("utf-8")


def validate_tbx(xml_bytes: bytes,
                 expected_entries: Optional[int] = None) -> List[str]:
    """TBX 结构校验：可解析、根元素正确、termEntry 数量匹配。"""
    problems = []
    try:
        root = safe_xml_fromstring(xml_bytes.decode("utf-8"))
    except Exception as e:
        return [f"TBX 不是合法 XML：{e}"]
    if root.tag != "martif":
        return [f"TBX 根元素应为 martif，实际 {root.tag}"]
    entries = root.findall(".//termEntry")
    if expected_entries is not None and len(entries) != expected_entries:
        problems.append(f"termEntry 数量 {len(entries)} != 期望 {expected_entries}")
    for te in entries:
        langs = te.findall("langSet")
        if len(langs) < 2:
            problems.append(f"termEntry {te.get('id')} 缺少语言集")
        if not te.findall(".//term"):
            problems.append(f"termEntry {te.get('id')} 缺少 term")
    return problems


# ---------------- TMX ----------------

def tmx_eligible(state: Dict[str, Any], index: int, pair: Dict[str, Any]) -> bool:
    """TMX 入库资格：审校通过，且该段无未解决的 blocking/actionable。

    accepted_for_delivery != trusted TM：
    通过人工“接受风险 / 标记已修复”解决的 finding 不代表译文经审校验证，
    该类段落不得进入 TMX final memory。stale 段同样排除。
    """
    if not pair.get("reviewed") or pair.get("stale_due_to_glossary"):
        return False
    if not translation_target.validate_translation_target(
            pair.get("source"), pair.get("target"),
            segment_index=index)["ok"]:
        return False
    for f in state.get("findings") or []:
        if f.get("segment_index") == index \
                and f.get("severity") in ("blocking", "actionable"):
            if f.get("resolved"):
                res = f.get("resolution") or {}
                if res.get("action") in ("accepted_risk", "human_fixed"):
                    return False
                continue
            return False
    return True


def build_tmx(state: Dict[str, Any],
              src_lang: str = "en",
              tgt_lang: str = "zh-CN",
              job_id: str = "") -> bytes:
    """双语对照 -> TMX 1.4 风格 XML（仅合格段落）。"""
    root = ET.Element("tmx", {"version": "1.4"})
    header = ET.SubElement(root, "header", {
        "creationtool": "TransPraxis / 译践",
        "segtype": "paragraph",
        "adminlang": "en",
        "srclang": src_lang,
        "datatype": "plaintext",
        "creationdate": _now_iso(),
    })
    ET.SubElement(header, "note").text = f"job_id={job_id}"
    body = ET.SubElement(root, "body")
    for i, pair in enumerate(state.get("pairs") or []):
        if not tmx_eligible(state, i, pair):
            continue
        tu = ET.SubElement(body, "tu", {"segid": segment_id(job_id, i)})
        ET.SubElement(tu, "prop", {"type": "transpraxis:segment_id"}).text = str(i)
        ET.SubElement(tu, "prop", {"type": "transpraxis:job_id"}).text = job_id
        ET.SubElement(tu, "prop", {"type": "transpraxis:from_tm"}).text = str(
            bool(pair.get("from_tm"))).lower()
        tuv_src = ET.SubElement(tu, "tuv", {"xml:lang": src_lang})
        ET.SubElement(tuv_src, "seg").text = pair["source"]
        tuv_tgt = ET.SubElement(tu, "tuv", {"xml:lang": tgt_lang})
        ET.SubElement(tuv_tgt, "seg").text = pair["target"]
    return (XML_DECL + ET.tostring(root, encoding="unicode")).encode("utf-8")


def validate_tmx(xml_bytes: bytes, expected_tus: Optional[int] = None) -> List[str]:
    problems = []
    try:
        root = safe_xml_fromstring(xml_bytes.decode("utf-8"))
    except Exception as e:
        return [f"TMX 不是合法 XML：{e}"]
    if root.tag != "tmx":
        return [f"TMX 根元素应为 tmx，实际 {root.tag}"]
    header = root.find("header")
    if header is None or not header.get("srclang"):
        problems.append("TMX 缺少 header/srclang")
    tus = root.findall(".//tu")
    if expected_tus is not None and len(tus) != expected_tus:
        problems.append(f"tu 数量 {len(tus)} != 期望 {expected_tus}")
    for tu in tus:
        if len(tu.findall("tuv")) != 2:
            problems.append(f"tu {tu.get('segid')} 缺少双语 tuv")
        if not tu.findall(".//seg"):
            problems.append(f"tu {tu.get('segid')} 缺少 seg")
    return problems


# ---------------- JSONL ----------------

def build_jsonl(state: Dict[str, Any], job_id: str = "",
                delivery_status: Optional[str] = None) -> str:
    """每行一个双语 segment 的 JSONL。"""
    validation = translation_target.validate_translation_pairs(
        state.get("pairs") or [])
    if validation["blocking"]:
        raise ValueError("JSONL 导出被 Translation Target Invariant 阻止")
    status = delivery_status or state.get("delivery_status") or "draft"
    findings_by_seg: Dict[int, List[Dict[str, Any]]] = {}
    for f in state.get("findings") or []:
        idx = f.get("segment_index")
        if isinstance(idx, int):
            findings_by_seg.setdefault(idx, []).append(f)
    lines = []
    for i, pair in enumerate(state.get("pairs") or []):
        record = {
            "segment_id": segment_id(job_id, i),
            "source": pair.get("source", ""),
            "target": pair.get("target", ""),
            "reviewed": bool(pair.get("reviewed")),
            "from_tm": bool(pair.get("from_tm")),
            "glossary_entry_ids": list(pair.get("glossary_entry_ids") or []),
            "findings": findings_by_seg.get(i, []),
            "delivery_status": status,
        }
        lines.append(json.dumps(record, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


def validate_jsonl(text: str, expected_lines: Optional[int] = None) -> List[str]:
    problems = []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if expected_lines is not None and len(lines) != expected_lines:
        problems.append(f"JSONL 行数 {len(lines)} != 期望 {expected_lines}")
    for ln in lines:
        try:
            obj = json.loads(ln)
        except Exception as e:
            problems.append(f"JSONL 非法 JSON：{e}")
            continue
        for key in ("segment_id", "source", "target", "reviewed", "from_tm",
                    "glossary_entry_ids", "findings", "delivery_status"):
            if key not in obj:
                problems.append(f"JSONL 行缺少字段 {key}")
    return problems


# ---------------- delivery_manifest.json ----------------

def build_delivery_manifest(
    state: Dict[str, Any],
    job_id: str,
    target_lang: str = "",
    provider: str = "",
    model: str = "",
    generated_assets: Optional[List[str]] = None,
    source_filename: str = "",
    translator_config: Optional[Dict[str, Any]] = None,
    reviewer_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """生成交付清单（统计与任务状态一致）。"""
    stats = state.get("review_stats") or {}
    fg = state.get("glossary_frozen") or {}
    unresolved = _delivery.unresolved_findings(state)
    translator = model_roles.public_role_config(
        translator_config or {
            "provider": provider, "model": model,
        })
    reviewer = model_roles.public_role_config(
        reviewer_config or state.get("reviewer_config") or {
            "provider": provider, "model": model,
        })
    return {
        "source_filename": source_filename or state.get("filename", ""),
        "source_hash": _source_hash(state),
        "job_id": job_id,
        "target_language": target_lang,
        "model": model,
        "provider": provider,
        "translator": translator,
        "reviewer": reviewer,
        "translation_target_validation": state.get("delivery_validation") or {
            "status": "not_run",
            "blocking": False,
        },
        "document_profile": state.get("document_profile"),
        "frozen_glossary": {
            "version": fg.get("version"),
            "glossary_hash": fg.get("glossary_hash"),
            "entry_count": len(fg.get("entries") or []),
        } if fg else None,
        "segment_count": len(state.get("pairs") or []),
        "tm_reused_count": state.get("tm_used_count", 0),
        "blocking": stats.get("blocking", 0),
        "actionable": stats.get("actionable", 0),
        "informational": stats.get("informational", 0),
        "unresolved_findings": [
            {
                "finding_id": _delivery.finding_id(f),
                "segment_index": f.get("segment_index"),
                "segment_id": segment_id(
                    job_id, f.get("segment_index"))
                if isinstance(f.get("segment_index"), int) else None,
                "severity": f.get("severity"),
                "reason": f.get("reason"),
            }
            for f in unresolved
        ],
        "delivery_status": state.get("delivery_status") or "draft",
        "generated_assets": list(generated_assets or []),
        "created_at": _now_iso(),
    }


def validate_manifest(manifest: Dict[str, Any], state: Dict[str, Any]) -> List[str]:
    """manifest 与任务状态一致性校验。"""
    problems = []
    stats = state.get("review_stats") or {}
    if manifest.get("segment_count") != len(state.get("pairs") or []):
        problems.append("segment_count 与任务 pairs 数量不一致")
    if manifest.get("tm_reused_count") != state.get("tm_used_count", 0):
        problems.append("tm_reused_count 与任务状态不一致")
    if manifest.get("blocking") != stats.get("blocking", 0):
        problems.append("blocking 统计与任务状态不一致")
    if manifest.get("actionable") != stats.get("actionable", 0):
        problems.append("actionable 统计与任务状态不一致")
    if manifest.get("informational") != stats.get("informational", 0):
        problems.append("informational 统计与任务状态不一致")
    if manifest.get("delivery_status") not in _delivery.DELIVERY_STATUSES:
        problems.append(f"非法 delivery_status：{manifest.get('delivery_status')}")
    unresolved = _delivery.unresolved_findings(state)
    if len(manifest.get("unresolved_findings") or []) != len(unresolved):
        problems.append("unresolved_findings 数量与任务状态不一致")
    fg = state.get("glossary_frozen") or {}
    if fg and manifest.get("frozen_glossary", {}).get("glossary_hash") != \
            fg.get("glossary_hash"):
        problems.append("frozen_glossary hash 与任务状态不一致")
    return problems


def export_all(state: Dict[str, Any], job_id: str, target_lang: str = "",
               provider: str = "", model: str = "",
               source_filename: str = "",
               source_bin: Optional[bytes] = None) -> Dict[str, bytes]:
    """一键导出全部标准资产。返回 {文件名: 内容}。"""
    if source_bin is not None:
        state = dict(state)
        state["_source_bin"] = source_bin
    tbx = build_tbx(state.get("glossary") or [])
    tmx = build_tmx(state, job_id=job_id)
    jsonl = build_jsonl(state, job_id=job_id).encode("utf-8")
    manifest = build_delivery_manifest(
        state, job_id, target_lang, provider, model,
        generated_assets=["terms.tbx", "memory.tmx", "bilingual.jsonl",
                          "delivery_manifest.json"],
        source_filename=source_filename,
        translator_config=state.get("translator_config"),
        reviewer_config=state.get("reviewer_config"))
    return {
        "terms.tbx": tbx,
        "memory.tmx": tmx,
        "bilingual.jsonl": jsonl,
        "delivery_manifest.json": (
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    }
