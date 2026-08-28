"""Long-document understanding and translation context compilation.

The module keeps five kinds of context separate:
document meaning, local section meaning, terminology, source neighbors, and
accepted target continuity.  It is deliberately JSON-shaped so the result can
be persisted beside a job and reused after a restart.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


DEFAULT_UNIT_CHARS = 12000
DEFAULT_DIGEST_WORKERS = 4
MAX_SYNOPSIS_CHARS = 12000
TARGET_CONTEXT_LEVELS = (
    "human_accepted",
    "reviewed",
    "tm_approved",
    "generated",
)


def _clean(value: Any, limit: int = 1200) -> str:
    text = "" if value is None else str(value).strip()
    return text[:limit].rstrip()


def _string_list(value: Any, limit: int = 12, item_limit: int = 160) -> List[str]:
    if isinstance(value, str):
        value = re.split(r"[,，;；\n]", value)
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for item in value:
        item = _clean(item, item_limit)
        if item and item not in out:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _parse_object(text: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(text, str) or not text.strip():
        return None
    candidate = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.DOTALL)
    candidate = re.sub(r"\s*```$", "", candidate, flags=re.DOTALL).strip()
    try:
        value = json.loads(candidate)
        return value if isinstance(value, dict) else None
    except (TypeError, ValueError):
        pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", candidate):
        try:
            value, _ = decoder.raw_decode(candidate[match.start():])
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _call(call_llm: Callable, provider: str, api_key: str, model: str,
          system_prompt: str, user_prompt: str) -> Any:
    try:
        return call_llm(provider, api_key, model, system_prompt, user_prompt,
                        temperature=0.1)
    except TypeError:
        # Small test/dry-run providers sometimes expose the five-argument form.
        return call_llm(provider, api_key, model, system_prompt, user_prompt)


def _chunk_range(paragraphs: Sequence[str], start: int, end: int,
                 max_chars: int, unit_prefix: str, label: str,
                 kind: str) -> List[Dict[str, Any]]:
    units = []
    chunk_start = start
    chars = 0
    for index in range(start, end + 1):
        size = len(paragraphs[index])
        if index > chunk_start and chars + size > max_chars:
            units.append(_make_unit(paragraphs, chunk_start, index - 1,
                                    unit_prefix, len(units), label, kind))
            chunk_start, chars = index, 0
        chars += size
    if chunk_start <= end:
        units.append(_make_unit(paragraphs, chunk_start, end,
                                unit_prefix, len(units), label, kind))
    return units


def _make_unit(paragraphs: Sequence[str], start: int, end: int,
               prefix: str, number: int, label: str, kind: str) -> Dict[str, Any]:
    return {
        "unit_id": f"{prefix}-{number + 1}",
        "kind": kind,
        "label": _clean(label, 240),
        "start_segment": start,
        "end_segment": end,
        "source": "\n".join(paragraphs[start:end + 1]),
    }


def _section_sort_key(section: Dict[str, Any]) -> Tuple[int, int]:
    """Sort malformed profile ranges after valid ranges without raising."""
    try:
        start = int(section.get("start_segment"))
        end = int(section.get("end_segment"))
    except (TypeError, ValueError):
        return (10**12, 10**12)
    return start, end


def build_semantic_units(
    paragraphs: Sequence[str],
    document_profile: Optional[Dict[str, Any]] = None,
    max_chars: int = DEFAULT_UNIT_CHARS,
) -> List[Dict[str, Any]]:
    """Build section/cluster units from deterministic paragraph ranges.

    Profile ranges are preferred.  Gaps and documents without reliable section
    boundaries become contiguous semantic clusters, so every source paragraph
    belongs to exactly one unit.
    """
    paragraphs = [str(p or "") for p in paragraphs]
    if not paragraphs:
        return []
    max_chars = max(200, int(max_chars or DEFAULT_UNIT_CHARS))
    ranges: List[Tuple[int, int, str, str, str]] = []
    used = set()
    sections = sorted(
        (s for s in (document_profile or {}).get("sections") or []
         if isinstance(s, dict)),
        key=_section_sort_key,
    )
    for section in sections:
        try:
            start = max(0, int(section.get("start_segment")))
            end = min(len(paragraphs) - 1, int(section.get("end_segment")))
        except (TypeError, ValueError):
            continue
        if start > end or any(i in used for i in range(start, end + 1)):
            continue
        used.update(range(start, end + 1))
        sid = _clean(section.get("section_id"), 120) or f"section-{start + 1}"
        label = _clean(section.get("topic"), 240) or sid
        ranges.append((start, end, f"section-{sid}", label, "section"))

    # Fill uncovered ranges with clusters.  This also handles sparse LLM
    # section output without silently dropping source text.
    gap_start = None
    for index in range(len(paragraphs) + 1):
        covered = index < len(paragraphs) and index in used
        if index < len(paragraphs) and not covered and gap_start is None:
            gap_start = index
        if gap_start is not None and (index == len(paragraphs) or covered):
            ranges.append((gap_start, index - 1, "cluster", "", "semantic_cluster"))
            gap_start = None
    ranges.sort(key=lambda item: item[0])

    units: List[Dict[str, Any]] = []
    for start, end, prefix, label, kind in ranges:
        chunks = _chunk_range(paragraphs, start, end, max_chars, prefix, label, kind)
        for chunk in chunks:
            chunk["unit_id"] = f"unit-{len(units) + 1:04d}"
            chunk["source_range_id"] = prefix
            units.append(chunk)
    return units


def _digest_system_prompt() -> str:
    return (
        "你是长文翻译的文档理解器。只依据给出的语义单元原文，输出一个合法 JSON 对象。"
        "不要补写原文没有的事实；不确定的字段留空数组或空字符串。"
        "字段：summary（单元主旨）、key_entities（人物/地点/机构/作品）、"
        "key_terms（重要概念）、open_threads（需要后文确认的指代或叙事线索）、"
        "translation_notes（对语气、指代、术语连续性的翻译提示）。"
    )


def _normalize_digest(unit: Dict[str, Any], raw: Optional[Dict[str, Any]],
                     status: str = "model") -> Dict[str, Any]:
    raw = raw or {}
    return {
        "unit_id": unit["unit_id"],
        "kind": unit["kind"],
        "label": unit.get("label", ""),
        "start_segment": unit["start_segment"],
        "end_segment": unit["end_segment"],
        "summary": _clean(raw.get("summary") or raw.get("digest"), 1600),
        "key_entities": _string_list(raw.get("key_entities") or raw.get("entities")),
        "key_terms": _string_list(raw.get("key_terms") or raw.get("terms")),
        "open_threads": _string_list(raw.get("open_threads") or raw.get("threads")),
        "translation_notes": _string_list(raw.get("translation_notes") or raw.get("notes")),
        "status": status,
    }


def _fallback_digest(unit: Dict[str, Any]) -> Dict[str, Any]:
    source = unit.get("source", "")
    first = re.split(r"(?<=[.!?。！？])\s+", source.strip(), maxsplit=1)[0]
    digest = _normalize_digest(unit, {"summary": first or source[:600]},
                               status="deterministic_fallback")
    digest["warning"] = "模型未返回结构化语义摘要；仅使用单元首句作为临时上下文。"
    return digest


def generate_section_digests(
    units: Sequence[Dict[str, Any]],
    provider: str,
    api_key: str,
    model: str,
    target_lang: str = "",
    call_llm: Optional[Callable] = None,
    max_workers: int = DEFAULT_DIGEST_WORKERS,
    existing_digests: Optional[Sequence[Dict[str, Any]]] = None,
    on_progress: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Generate independent unit digests; results retain source order."""
    if not units:
        return [], ["语义摘要跳过：没有可用语义单元"]
    if call_llm is None:
        import core
        call_llm = core.call_llm
    system_prompt = _digest_system_prompt()

    def work(unit: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
        user_prompt = (
            f"目标语言：{target_lang}\n"
            f"语义单元：{unit['unit_id']}（段落 {unit['start_segment']}-"
            f"{unit['end_segment']}）\n原文：\n{unit['source']}"
        )
        try:
            raw = _parse_object(_call(call_llm, provider, api_key, model,
                                      system_prompt, user_prompt))
            if raw is None:
                return _fallback_digest(unit), f"{unit['unit_id']}：返回不是结构化 JSON"
            return _normalize_digest(unit, raw), None
        except Exception as exc:  # provider failures must not corrupt the job
            return _fallback_digest(unit), f"{unit['unit_id']}：语义摘要失败（{str(exc)[:160]}）"

    existing_by_id = {
        str(item.get("unit_id")): dict(item)
        for item in existing_digests or []
        if isinstance(item, dict) and item.get("unit_id")
    }
    results: List[Optional[Dict[str, Any]]] = []
    for unit in units:
        saved = existing_by_id.get(str(unit["unit_id"]))
        if saved and saved.get("start_segment") == unit.get("start_segment") \
                and saved.get("end_segment") == unit.get("end_segment") \
                and saved.get("source") in (None, unit.get("source")):
            results.append(saved)
        else:
            results.append(None)
    warnings: List[str] = []
    pending = [(index, unit) for index, unit in enumerate(units)
               if results[index] is None]
    if pending:
        workers = max(1, min(int(max_workers or 1), len(pending)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(work, unit): index for index, unit in pending}
            for future in as_completed(futures):
                index = futures[future]
                try:
                    digest, warning = future.result()
                except Exception as exc:  # defensive around custom executors/providers
                    digest = _fallback_digest(units[index])
                    warning = f"{units[index]['unit_id']}：语义摘要失败（{str(exc)[:160]}）"
                results[index] = digest
                if warning:
                    warnings.append(warning)
                if on_progress is not None:
                    on_progress([item for item in results if item is not None])
    return [item for item in results if item is not None], warnings


def _synopsis_system_prompt() -> str:
    return (
        "你是长文翻译的全书理解器。根据多个语义单元摘要，输出一个合法 JSON 对象。"
        "只综合摘要中已有的信息，不臆造情节或事实。字段：summary（全书概要）、"
        "document_arc（论证/叙事发展）、themes（主题）、entities（跨单元实体）、"
        "terms（全书关键概念）、translation_notes（全书翻译连续性提示）。"
    )


def _normalize_synopsis(raw: Dict[str, Any], status: str = "model") -> Dict[str, Any]:
    return {
        "summary": _clean(raw.get("summary") or raw.get("synopsis"), 2400),
        "document_arc": _clean(raw.get("document_arc") or raw.get("arc"), 1600),
        "themes": _string_list(raw.get("themes")),
        "entities": _string_list(raw.get("entities")),
        "terms": _string_list(raw.get("terms") or raw.get("key_terms")),
        "translation_notes": _string_list(raw.get("translation_notes") or raw.get("notes")),
        "status": status,
    }


def _digest_text(digest: Dict[str, Any]) -> str:
    return (
        f"[{digest.get('unit_id', '')} · 段 {digest.get('start_segment', '')}-"
        f"{digest.get('end_segment', '')}]\n"
        f"主旨：{digest.get('summary', '')}\n"
        f"实体：{'、'.join(digest.get('key_entities') or [])}\n"
        f"概念：{'、'.join(digest.get('key_terms') or [])}\n"
        f"提示：{'、'.join(digest.get('translation_notes') or [])}"
    )


def _synopsis_text(synopsis: Dict[str, Any], index: int) -> str:
    return (
        f"[中间概要 {index + 1}]\n概要：{synopsis.get('summary', '')}\n"
        f"发展：{synopsis.get('document_arc', '')}\n"
        f"主题：{'、'.join(synopsis.get('themes') or [])}\n"
        f"实体：{'、'.join(synopsis.get('entities') or [])}\n"
        f"概念：{'、'.join(synopsis.get('terms') or [])}\n"
        f"翻译提示：{'、'.join(synopsis.get('translation_notes') or [])}"
    )


def _text_chunks(items: Sequence[str], max_chars: int) -> List[str]:
    chunks: List[str] = []
    current: List[str] = []
    chars = 0
    for item in items:
        item = str(item or "")
        if len(item) > max_chars:
            if current:
                chunks.append("\n\n".join(current))
                current, chars = [], 0
            chunks.extend(item[index:index + max_chars]
                          for index in range(0, len(item), max_chars))
            continue
        if current and chars + len(item) > max_chars:
            chunks.append("\n\n".join(current))
            current, chars = [], 0
        current.append(item)
        chars += len(item)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _reduce_synopsis(
    items: Sequence[str],
    provider: str,
    api_key: str,
    model: str,
    target_lang: str,
    call_llm: Callable,
    max_chars: int,
) -> Dict[str, Any]:
    chunk_limit = min(MAX_SYNOPSIS_CHARS, max(1000, int(max_chars or 12000)))
    chunks = _text_chunks(items, chunk_limit)
    if not chunks:
        return {"summary": "", "status": "unavailable"}
    reduced: List[Dict[str, Any]] = []
    for chunk in chunks:
        raw = _parse_object(_call(
            call_llm, provider, api_key, model, _synopsis_system_prompt(),
            f"目标语言：{target_lang}\n语义摘要块：\n{chunk}"))
        if raw is None:
            raise ValueError("模型未返回结构化 JSON")
        reduced.append(_normalize_synopsis(raw))
    if len(reduced) == 1:
        return reduced[0]
    return _reduce_synopsis(
        [_synopsis_text(item, index) for index, item in enumerate(reduced)],
        provider, api_key, model, target_lang, call_llm,
        min(MAX_SYNOPSIS_CHARS, chunk_limit * 2))


def generate_document_synopsis(
    digests: Sequence[Dict[str, Any]],
    provider: str,
    api_key: str,
    model: str,
    target_lang: str = "",
    call_llm: Optional[Callable] = None,
    max_chunk_chars: int = 12000,
) -> Tuple[Dict[str, Any], List[str]]:
    """Map unit digests into a hierarchical document-level synopsis."""
    if not digests:
        return {"summary": "", "status": "unavailable"}, ["全文概要跳过：没有语义摘要"]
    if call_llm is None:
        import core
        call_llm = core.call_llm
    try:
        return _reduce_synopsis(
            [_digest_text(digest) for digest in digests],
            provider, api_key, model, target_lang, call_llm, max_chunk_chars), []
    except Exception as exc:
        warning = f"全文概要失败（{str(exc)[:160]}）"
    else:
        warning = "全文概要失败：模型未返回结构化 JSON"

    fallback = _normalize_synopsis({
        "summary": "；".join(d.get("summary", "") for d in digests if d.get("summary"))[:2400],
        "translation_notes": [
            note for d in digests for note in (d.get("translation_notes") or [])
        ],
    }, status="deterministic_fallback")
    fallback["warning"] = warning
    return fallback, [warning]


def build_document_understanding(
    paragraphs: Sequence[str],
    document_profile: Optional[Dict[str, Any]],
    provider: str,
    api_key: str,
    model: str,
    target_lang: str = "",
    call_llm: Optional[Callable] = None,
    max_chars: int = DEFAULT_UNIT_CHARS,
    max_workers: int = DEFAULT_DIGEST_WORKERS,
    checkpoint_dir: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], List[str]]:
    """Build understanding artifacts with durable per-unit digest checkpoints."""
    units = build_semantic_units(paragraphs, document_profile, max_chars=max_chars)

    stored_digests: List[Dict[str, Any]] = []
    stored_synopsis: Optional[Dict[str, Any]] = None
    stored_complete = False
    if checkpoint_dir:
        root = Path(checkpoint_dir)
        try:
            saved_units = json.loads((root / "semantic_units.json").read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            saved_units = None
        if saved_units != units:
            saved_units = None
        try:
            candidate_digests = json.loads(
                (root / "section_digests.json").read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            candidate_digests = []
        if saved_units is not None and isinstance(candidate_digests, list):
            stored_digests = candidate_digests
        try:
            candidate_synopsis = json.loads(
                (root / "document_synopsis.json").read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            candidate_synopsis = None
        if isinstance(candidate_synopsis, dict):
            stored_synopsis = candidate_synopsis
        digest_by_id = {
            str(item.get("unit_id")): item for item in stored_digests
            if isinstance(item, dict) and item.get("unit_id")
        }
        stored_complete = len(digest_by_id) == len(units) and all(
            unit["unit_id"] in digest_by_id
            and unit.get("start_segment") == digest_by_id[unit["unit_id"]].get("start_segment")
            and unit.get("end_segment") == digest_by_id[unit["unit_id"]].get("end_segment")
            for unit in units
        )
        if not stored_complete:
            stored_synopsis = None
        write_understanding_artifacts(
            root, units, stored_digests,
            stored_synopsis if stored_synopsis and stored_synopsis.get("status") != "pending"
            and stored_complete else {"summary": "", "status": "pending"})

    def checkpoint(digests: List[Dict[str, Any]]) -> None:
        if checkpoint_dir:
            write_understanding_artifacts(
                Path(checkpoint_dir), units, digests,
                {"summary": "", "status": "pending"})

    digests, warnings = generate_section_digests(
        units, provider, api_key, model, target_lang, call_llm,
        max_workers=max_workers, existing_digests=stored_digests,
        on_progress=checkpoint if checkpoint_dir else None)
    if stored_synopsis and stored_synopsis.get("status") != "pending" \
            and len(digests) == len(units) and stored_complete:
        synopsis, synopsis_warnings = stored_synopsis, []
    else:
        synopsis, synopsis_warnings = generate_document_synopsis(
            digests, provider, api_key, model, target_lang, call_llm)
    if checkpoint_dir:
        write_understanding_artifacts(Path(checkpoint_dir), units, digests, synopsis)
    return units, digests, synopsis, warnings + synopsis_warnings


def write_understanding_artifacts(
    job_root: Path,
    units: Sequence[Dict[str, Any]],
    digests: Sequence[Dict[str, Any]],
    synopsis: Dict[str, Any],
) -> None:
    """Persist the named understanding artifacts without touching state.json."""
    job_root.mkdir(parents=True, exist_ok=True)
    for name, value in (
        ("semantic_units.json", list(units)),
        ("section_digests.json", list(digests)),
        ("document_synopsis.json", synopsis),
    ):
        tmp = job_root / f"{name}.tmp"
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(job_root / name)


def digest_for_segment(digests: Sequence[Dict[str, Any]], segment_index: int) -> Optional[Dict[str, Any]]:
    for digest in digests or []:
        if not isinstance(digest, dict):
            continue
        try:
            index = int(segment_index)
            start = int(digest.get("start_segment"))
            end = int(digest.get("end_segment"))
        except (TypeError, ValueError):
            continue
        if start <= index <= end:
            return digest
    return None


def target_context_level(pair: Dict[str, Any]) -> str:
    """Return the strongest provenance available for target continuity."""
    if pair.get("human_accepted") or pair.get("accepted_by_human"):
        return "human_accepted"
    provenance = str(pair.get("target_provenance") or "")
    if provenance in ("human_accepted", "human"):
        return "human_accepted"
    if pair.get("reviewed") and (pair.get("from_tm") or provenance == "tm_approved"):
        return "tm_approved"
    if pair.get("reviewed") or provenance == "reviewed":
        return "reviewed"
    return "generated"


def select_target_context(
    pairs: Sequence[Dict[str, Any]],
    before_index: int,
    limit: int = 2,
) -> List[Dict[str, Any]]:
    """Select recent target context with explicit provenance priority."""
    candidates = []
    for index, pair in enumerate(list(pairs)[:max(0, before_index)]):
        target = pair.get("accepted_target") or pair.get("target")
        if target:
            candidates.append({
                "segment_index": index,
                "source": _clean(pair.get("source"), 800),
                "target": _clean(target, 1200),
                "level": target_context_level(pair),
            })
    selected: List[Dict[str, Any]] = []
    for level in TARGET_CONTEXT_LEVELS:
        selected.extend(item for item in reversed(candidates) if item["level"] == level)
        if len(selected) >= max(0, limit):
            break
    return sorted(selected[:max(0, limit)], key=lambda item: item["segment_index"])


def compile_context_packet(
    document_profile: Optional[Dict[str, Any]],
    document_synopsis: Optional[Dict[str, Any]],
    section_digest: Optional[Dict[str, Any]],
    glossary_text: str,
    previous_source: Sequence[str],
    previous_target: Sequence[Dict[str, Any]],
    next_source: Sequence[str],
    current_batch: Sequence[str],
    style_rules: str = "",
    entity_hints: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compile a stable-order packet for generation/review prompts."""
    return {
        "document_profile": document_profile or {},
        "document_synopsis": document_synopsis or {},
        "section_digest": section_digest or {},
        "locked_glossary": glossary_text or "",
        "style_rules": style_rules or "",
        "previous_source_context": list(previous_source or []),
        "previous_accepted_target_context": list(previous_target or []),
        "next_source_context": list(next_source or []),
        "current_batch": list(current_batch or []),
        "entity_hints": [dict(item) for item in entity_hints or []],
    }


def _compact_profile(profile: Dict[str, Any]) -> str:
    """Render high-value profile fields without repeating raw JSON noise."""
    if not isinstance(profile, dict) or not profile:
        return "{}"
    fields = (
        ("domain", "领域"), ("subdomain", "细分领域"), ("genre", "文类"),
        ("audience", "读者"), ("register", "语域"),
        ("style_constraints", "风格约束"),
    )
    lines = [
        f"{label}：{_clean(profile.get(key), 260)}"
        for key, label in fields
        if _clean(profile.get(key), 260)
    ]
    sections = profile.get("sections") or []
    labels = [
        _clean(item.get("topic") or item.get("section_id"), 100)
        for item in sections if isinstance(item, dict)
    ]
    labels = [item for item in labels if item]
    if labels:
        lines.append("章节：" + "；".join(labels[:12]))
    return "\n".join(lines)[:1800] or "{}"


def render_context_packet(packet: Dict[str, Any]) -> str:
    """Render the packet with a stable prefix and current batch at the end."""
    profile = _compact_profile(packet.get("document_profile") or {})
    synopsis = packet.get("document_synopsis") or {}
    digest = packet.get("section_digest") or {}
    lines = [
        "【文档画像】\n" + profile,
        "【文体与翻译规则】\n" + (packet.get("style_rules") or ""),
        "【全文概要】\n" + _clean(synopsis.get("summary"), 2400),
        "【全文发展/论证】\n" + _clean(synopsis.get("document_arc"), 1600),
        "【当前语义单元摘要】\n" + _clean(digest.get("summary"), 1600),
        "【当前单元翻译提示】\n" + "、".join(digest.get("translation_notes") or []),
        "【锁定术语与范围规则（项目人工锁定优先）】\n"
        + (packet.get("locked_glossary") or ""),
        "【专名/实体连续性提示（仅作建议；人工实体选择优先）】\n" + "\n".join(
            f"- {item.get('source_form', '')} -> {item.get('preferred_target', '')}"
            f"（{item.get('entity_type', 'proper noun')}；"
            f"{item.get('provenance', 'generated_observation')}；"
            f"优先级：{item.get('precedence', 'entity_continuity_hint')}）"
            for item in packet.get("entity_hints") or []
        ),
        "【前文原文上下文】\n" + "\n".join(
            f"- {item}" for item in packet.get("previous_source_context") or []),
        "【前文已接受译文连续性】\n" + "\n".join(
            f"- 段 {item.get('segment_index', '?')} [{item.get('level', 'generated')}] "
            f"原文：{item.get('source', '')}\n  译文：{item.get('target', '')}"
            for item in packet.get("previous_accepted_target_context") or []),
        "【后文原文上下文】\n" + "\n".join(
            f"- {item}" for item in packet.get("next_source_context") or []),
        "【待翻译段落（按序号返回等长数组）】",
    ]
    lines.extend(f"{index + 1}. {source}" for index, source in
                 enumerate(packet.get("current_batch") or []))
    return "\n\n".join(lines)


def context_metadata(packet: Dict[str, Any]) -> Dict[str, Any]:
    """Small audit record; do not persist full prompt text in job state."""
    rendered = render_context_packet(packet)
    marker = "【待翻译段落（按序号返回等长数组）】"
    prefix_chars = rendered.find(marker)
    if prefix_chars < 0:
        prefix_chars = len(rendered)
    return {
        "section_id": (packet.get("section_digest") or {}).get("unit_id"),
        "previous_source_count": len(packet.get("previous_source_context") or []),
        "previous_target_segments": [
            item.get("segment_index") for item in packet.get("previous_accepted_target_context") or []
        ],
        "previous_target_levels": [
            item.get("level") for item in packet.get("previous_accepted_target_context") or []
        ],
        "next_source_count": len(packet.get("next_source_context") or []),
        "current_batch_count": len(packet.get("current_batch") or []),
        "prompt_chars": len(rendered),
        "context_prefix_chars": prefix_chars,
        "current_batch_chars": sum(len(item) for item in packet.get("current_batch") or []),
        "entity_hint_count": len(packet.get("entity_hints") or []),
    }
