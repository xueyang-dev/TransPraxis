"""Bounded evidence access and evidence-guided translation review."""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import terminology

MAX_REQUESTS_PER_ROUND = 5
MAX_EVIDENCE_PAYLOAD_BYTES = 24000
DIAGNOSTIC_FIELDS = (
    "category", "summary", "source_span", "target_span", "explanation",
    "recommendation", "confidence", "detector",
)


def _bound_evidence(result: Any) -> Any:
    try:
        payload_bytes = len(json.dumps(
            result, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        return {"error": "证据结果不可序列化"}
    if payload_bytes <= MAX_EVIDENCE_PAYLOAD_BYTES:
        return result
    return {
        "error": "证据负载超过上限",
        "payload_bytes": payload_bytes,
        "max_bytes": MAX_EVIDENCE_PAYLOAD_BYTES,
    }


class TranslationEvidenceIndex:
    """Read-only, bounded evidence surface for a translation reviewer."""

    ALLOWED_TOOLS = {
        "get_segment", "get_neighbors", "find_occurrences", "get_term",
        "get_document_profile", "get_document_synopsis", "get_section_digest",
        "get_translation_history", "get_findings",
    }

    def __init__(
        self,
        paragraphs: Sequence[str],
        pairs: Sequence[Dict[str, Any]],
        glossary: Sequence[Dict[str, Any]],
        document_profile: Optional[Dict[str, Any]] = None,
        document_synopsis: Optional[Dict[str, Any]] = None,
        section_digests: Optional[Sequence[Dict[str, Any]]] = None,
        findings: Optional[Sequence[Dict[str, Any]]] = None,
        blind: bool = False,
        candidate_targets: Optional[Dict[int, str]] = None,
    ) -> None:
        self.paragraphs = list(paragraphs or [])
        self.pairs = list(pairs or [])
        self.glossary = list(glossary or [])
        self.document_profile = document_profile or {}
        self.document_synopsis = document_synopsis or {}
        self.section_digests = list(section_digests or [])
        self.findings = list(findings or [])
        self.blind = bool(blind)
        self.candidate_targets = {
            int(key): str(value or "")
            for key, value in (candidate_targets or {}).items()
        }
        self.requests: List[Dict[str, Any]] = []

    def get_segment(self, segment_id: int) -> Dict[str, Any]:
        try:
            index = int(segment_id)
        except (TypeError, ValueError):
            return {}
        if not 0 <= index < len(self.paragraphs):
            return {}
        pair = self.pairs[index] if index < len(self.pairs) else {}
        if self.blind:
            # Blind review may see the candidate and accepted neighbor context,
            # but never formal/initial targets or their provenance.
            target = self.candidate_targets.get(index, "")
            if not target:
                target = str(pair.get("accepted_target") or "")
            return {
                "segment_id": index,
                "source": self.paragraphs[index],
                "target": target,
            }
        return {
            "segment_id": index,
            "source": self.paragraphs[index],
            "target": pair.get("target", ""),
            "initial_target": pair.get("initial_target", ""),
            "accepted_target": pair.get("accepted_target", ""),
            "target_provenance": pair.get("target_provenance", ""),
            "reviewed": bool(pair.get("reviewed")),
            "from_tm": bool(pair.get("from_tm")),
        }

    def get_neighbors(self, segment_id: int, before: int = 3,
                      after: int = 3) -> List[Dict[str, Any]]:
        try:
            index = int(segment_id)
            before = max(0, min(5, int(before)))
            after = max(0, min(5, int(after)))
        except (TypeError, ValueError):
            return []
        if not 0 <= index < len(self.paragraphs):
            return []
        start = max(0, index - before)
        end = min(len(self.paragraphs), index + after + 1)
        return [self.get_segment(i) for i in range(start, end) if i != index]

    def find_occurrences(self, source_expression: str,
                         selectors: Sequence[str] = ("first", "middle", "last")) -> List[Dict[str, Any]]:
        indices = terminology.find_occurrences(source_expression, self.paragraphs)
        if not indices:
            return []
        chosen = []
        if "first" in selectors:
            chosen.append(indices[0])
        if "middle" in selectors:
            chosen.append(indices[len(indices) // 2])
        if "last" in selectors:
            chosen.append(indices[-1])
        return [self.get_segment(i) for i in dict.fromkeys(chosen)]

    def get_term(self, term_id: Optional[str] = None,
                 source: Optional[str] = None) -> Dict[str, Any]:
        for entry in self.glossary:
            if term_id and entry.get("id") == term_id:
                return dict(entry)
            if source and str(entry.get("source") or "").casefold() == str(source).casefold():
                return dict(entry)
        return {}

    def get_document_profile(self) -> Dict[str, Any]:
        return dict(self.document_profile)

    def get_document_synopsis(self) -> Dict[str, Any]:
        return dict(self.document_synopsis)

    def get_section_digest(self, section_id: Optional[str] = None,
                           segment_id: Optional[int] = None) -> Dict[str, Any]:
        for digest in self.section_digests:
            if not isinstance(digest, dict):
                continue
            if section_id and digest.get("unit_id") == section_id:
                return dict(digest)
            if segment_id is not None:
                try:
                    in_range = (digest.get("start_segment", 0) <= int(segment_id)
                                <= digest.get("end_segment", -1))
                except (TypeError, ValueError):
                    in_range = False
                if in_range:
                    return dict(digest)
        return {}

    def get_translation_history(self, segment_id: int) -> Dict[str, Any]:
        segment = self.get_segment(segment_id)
        if not segment:
            return {}
        if self.blind:
            return {key: segment.get(key) for key in (
                "segment_id", "source", "target")}
        return {key: segment.get(key) for key in (
            "segment_id", "source", "initial_target", "target", "accepted_target",
            "target_provenance", "reviewed", "from_tm")}

    def get_findings(self, segment_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if self.blind:
            return []
        if segment_id is None:
            return [dict(item) for item in self.findings]
        try:
            index = int(segment_id)
        except (TypeError, ValueError):
            return []
        return [dict(item) for item in self.findings
                if item.get("segment_index") == index or item.get("segment_id") == index]

    def request(self, tool: str, **arguments: Any) -> Any:
        """Execute one allow-listed evidence request and record its trace."""
        if tool not in self.ALLOWED_TOOLS:
            raise ValueError(f"不支持的证据工具：{tool}")
        if tool == "get_segment":
            result = self.get_segment(arguments.get("segment_id"))
        elif tool == "get_neighbors":
            result = self.get_neighbors(arguments.get("segment_id"),
                                         arguments.get("before", 3),
                                         arguments.get("after", 3))
        elif tool == "find_occurrences":
            result = self.find_occurrences(
                arguments.get("source_expression") or arguments.get("source") or "",
                arguments.get("selectors") or ("first", "middle", "last"))
        elif tool == "get_term":
            result = self.get_term(arguments.get("term_id"), arguments.get("source"))
        elif tool == "get_document_profile":
            result = self.get_document_profile()
        elif tool == "get_document_synopsis":
            result = self.get_document_synopsis()
        elif tool == "get_section_digest":
            result = self.get_section_digest(arguments.get("section_id"),
                                             arguments.get("segment_id"))
        elif tool == "get_translation_history":
            result = self.get_translation_history(arguments.get("segment_id"))
        else:
            result = self.get_findings(arguments.get("segment_id"))
        result = _bound_evidence(result)
        self.requests.append({"tool": tool, "arguments": dict(arguments), "result": result})
        return result


def _parse_payload(text: Any) -> Optional[Any]:
    if not isinstance(text, str) or not text.strip():
        return None
    candidate = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.DOTALL)
    candidate = re.sub(r"\s*```$", "", candidate, flags=re.DOTALL).strip()
    try:
        return json.loads(candidate)
    except (TypeError, ValueError):
        decoder = json.JSONDecoder()
        for marker in ("[", "{"):
            for match in re.finditer(re.escape(marker), candidate):
                try:
                    value, _ = decoder.raw_decode(candidate[match.start():])
                except (TypeError, ValueError):
                    continue
                return value
    return None


def _normalize_findings(
    items: Any,
    segment_ids: Optional[Sequence[int]] = None,
    invalid_segments: Optional[List[Any]] = None,
    invalid_refs: Optional[List[str]] = None,
    valid_evidence_ids: Optional[Sequence[str]] = None,
    invalid_diagnostics: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        if invalid_segments is not None:
            invalid_segments.append("findings_not_array")
        return []
    valid_ids = set(int(item) for item in segment_ids or [])
    valid_refs = set(str(item) for item in valid_evidence_ids or [])
    out = []
    for item in items:
        if not isinstance(item, dict):
            if invalid_segments is not None:
                invalid_segments.append("malformed_finding")
            continue
        severity = item.get("severity")
        if severity not in ("blocking", "actionable", "informational"):
            if invalid_segments is not None:
                invalid_segments.append("invalid_severity")
            continue
        segment_id = item.get("segment_id")
        # Read old responses only as a one-way compatibility shim: the prompt
        # and persisted records use global IDs, while an old local ordinal is
        # translated through this batch's explicit segment list.
        if segment_id is None and isinstance(item.get("segment_index"), int):
            local_ordinal = item["segment_index"]
            if segment_ids is not None and 0 <= local_ordinal < len(segment_ids):
                segment_id = segment_ids[local_ordinal]
        if isinstance(segment_id, bool) or not isinstance(segment_id, int):
            if invalid_segments is not None:
                invalid_segments.append("missing_segment_id")
            continue
        if segment_ids is not None and segment_id not in valid_ids:
            if invalid_segments is not None:
                invalid_segments.append(segment_id)
            continue
        raw_refs = item.get("evidence_refs") or item.get("evidence_ids") or []
        if not isinstance(raw_refs, list):
            if invalid_refs is not None:
                invalid_refs.append("evidence_refs_not_array")
            raw_refs = []
        evidence_refs = [str(ref) for ref in raw_refs if str(ref).strip()]
        if valid_evidence_ids is not None:
            for ref in evidence_refs:
                if ref not in valid_refs and invalid_refs is not None:
                    invalid_refs.append(ref)
        reason = str(item.get("reason") or item.get("summary") or "审校发现问题")
        record = {
            "segment_id": segment_id,
            "severity": severity,
            "reason": reason,
            "evidence_refs": evidence_refs,
        }
        if item.get("suggested_target"):
            record["suggested_target"] = str(item["suggested_target"])
        for field in DIAGNOSTIC_FIELDS:
            value = item.get(field)
            if field == "confidence":
                if isinstance(value, bool):
                    continue
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
                if not 0 <= value <= 1:
                    continue
            elif value is not None:
                value = str(value).strip()
                if not value:
                    continue
            if value is not None:
                record[field] = value
        has_diagnostics = any(field in item for field in DIAGNOSTIC_FIELDS)
        if has_diagnostics:
            record["diagnostic_version"] = 1
            if invalid_diagnostics is not None and any(
                    not str(item.get(field) or "").strip()
                    for field in ("summary", "explanation", "recommendation")):
                invalid_diagnostics.append(segment_id)
        out.append(record)
    return out


def _call(call_llm: Callable, provider: str, api_key: str, model: str,
          system_prompt: str, user_prompt: str) -> Any:
    try:
        return call_llm(provider, api_key, model, system_prompt, user_prompt,
                        temperature=0.2)
    except TypeError:
        return call_llm(provider, api_key, model, system_prompt, user_prompt)


def review_translation_batch_with_evidence(
    sources: Sequence[str],
    targets: Sequence[str],
    glossary_text: str,
    style_rules: str,
    target_lang: str,
    provider: str,
    api_key: str,
    model: str,
    evidence_index: TranslationEvidenceIndex,
    call_llm: Optional[Callable] = None,
    max_rounds: int = 2,
    blind: bool = False,
    segment_ids: Optional[Sequence[int]] = None,
    review_identity: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, Any]], bool, Dict[str, Any]]:
    """Review a batch with a bounded, two-state evidence protocol."""
    if call_llm is None:
        import core
        call_llm = core.call_llm
    segment_ids = list(segment_ids) if segment_ids is not None \
        else list(range(len(sources)))
    if len(targets) != len(sources) or len(segment_ids) != len(sources):
        return [], True, {
            "blind": blind, "rounds": [], "requests": [],
            "review_identity": dict(review_identity or {}),
            "decision": "failed", "error": "sources、targets、segment_ids 长度不一致",
            "completion_receipt": {
                "status": "failed", "reviewed_unit_count": 0,
                "review_identity": dict(review_identity or {}),
            },
        }
    numbered = "\n".join(
        f"local_ordinal: {i}\nsegment_id: {segment_id}\n原文：{source}\n译文：{target}"
        for i, (segment_id, source, target) in
        enumerate(zip(segment_ids, sources, targets))
    )
    system_prompt = (
        "你是一位独立的翻译审校专家，负责审查机器译文。"
        + ("这是盲审：不要提及修复候选或内部流程。" if blind else "")
        + "只报告真实存在的问题，不要为低风险或主观偏好制造 finding。"
        "severity 只允许 blocking、actionable、informational。"
        "如果需要全文证据，先在 evidence_requests 中请求工具；拿到证据后再作最终判断。"
        "严格输出 JSON 对象：{\"findings\": [...], \"evidence_requests\": "
        "[{\"tool\": \"get_segment\", \"arguments\": {}}]}。"
        "finding 必须使用给出的全局 segment_id；不要输出 segment_index。"
        "每个 finding 必须包含 category、severity、summary、explanation、recommendation；"
        "source_span 和 target_span 必须是原文/译文中的精确连续片段，无法可靠定位时为 null；"
        "confidence 仅在检测依据支持时填写 0 到 1 的数字，否则为 null；"
        "detector 填写检测器名称。没有充分证据不要生成 blocking finding。"
        "每个 finding 可带 evidence_refs（证据编号数组）和 suggested_target。"
        "推荐格式：{\"segment_id\": 0, \"category\": \"semantic_accuracy\", "
        "\"severity\": \"actionable\", \"summary\": \"具体问题摘要\", "
        "\"source_span\": \"原文中的精确片段或 null\", "
        "\"target_span\": \"译文中的精确片段或 null\", "
        "\"explanation\": \"为什么判定为问题\", "
        "\"recommendation\": \"建议人工如何检查或处理\", "
        "\"confidence\": 0.87, \"detector\": \"Semantic QA\", "
        "\"evidence_refs\": [\"E1\"]}。"
        "若无问题 findings 必须为空数组。\n" + glossary_text + "\n" + style_rules
    )
    base_prompt = f"待审校段落（目标语言：{target_lang}）：\n{numbered}"
    prompt = base_prompt
    trace: Dict[str, Any] = {
        "blind": blind, "segment_ids": segment_ids, "rounds": [],
        "requests": [], "evidence_ids": [], "decision": "",
        "review_identity": dict(review_identity or {}),
        "completion_receipt": None,
    }
    latest_findings: List[Dict[str, Any]] = []
    evidence_by_key: Dict[str, Dict[str, Any]] = {}

    def finish(findings: List[Dict[str, Any]], decision: str):
        trace["decision"] = decision
        trace["completion_receipt"] = {
            "status": "completed",
            "reviewed_segment_ids": list(segment_ids),
            "reviewed_unit_count": len(segment_ids),
            "finding_count": len(findings),
            "evidence_ids": list(trace["evidence_ids"]),
            "review_identity": dict(trace["review_identity"]),
        }
        return findings, False, trace

    def fail(message: Optional[str] = None):
        trace["decision"] = "failed"
        if message:
            trace["error"] = message[:240]
        trace["completion_receipt"] = {
            "status": "failed",
            "reviewed_segment_ids": [],
            "reviewed_unit_count": 0,
            "finding_count": 0,
            "evidence_ids": list(trace["evidence_ids"]),
            "review_identity": dict(trace["review_identity"]),
        }
        return [], True, trace

    for round_index in range(max(1, int(max_rounds or 1))):
        try:
            payload = _parse_payload(_call(
                call_llm, provider, api_key, model, system_prompt, prompt))
        except Exception as exc:
            return fail(str(exc))
        if isinstance(payload, list):
            invalid_segments: List[Any] = []
            invalid_refs: List[str] = []
            invalid_diagnostics: List[Any] = []
            latest_findings = _normalize_findings(
                payload, segment_ids, invalid_segments, invalid_refs,
                list(trace["evidence_ids"]), invalid_diagnostics)
            trace["rounds"].append({"round": round_index, "findings": latest_findings,
                                    "requests": []})
            if invalid_segments or invalid_refs or invalid_diagnostics:
                return fail("finding 引用了无效的定位、证据或诊断字段")
            return finish(latest_findings,
                          "clean" if not latest_findings else "findings")
        if not isinstance(payload, dict):
            return fail("审校返回不是 JSON 对象")
        invalid_segments = []
        latest_findings = _normalize_findings(
            payload.get("findings"), segment_ids, invalid_segments)
        if invalid_segments:
            return fail("findings 必须是数组且只能引用当前批次的全局 segment_id")
        if "evidence_requests" in payload:
            raw_requests = payload["evidence_requests"]
        else:
            raw_requests = payload.get("requests", [])
        if not isinstance(raw_requests, list) \
                or any(not isinstance(item, dict) for item in raw_requests):
            return fail("evidence_requests 必须是对象数组")
        requests = raw_requests[:MAX_REQUESTS_PER_ROUND]
        round_trace = {"round": round_index, "findings": latest_findings, "requests": []}
        if round_index > 0 and requests:
            trace["rounds"].append(round_trace)
            return fail("最终审校轮次禁止继续请求证据")
        evidence = []
        for request in requests:
            tool = str(request.get("tool") or request.get("type") or "")
            arguments = request.get("arguments") or request.get("args") or {}
            if not isinstance(arguments, dict):
                arguments = {}
            request_key = json.dumps({"tool": tool, "arguments": arguments},
                                     ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"))
            envelope = evidence_by_key.get(request_key)
            deduped = envelope is not None
            if envelope is None:
                try:
                    result = evidence_index.request(tool, **arguments)
                except (TypeError, ValueError) as exc:
                    result = {"error": str(exc)}
                result = _bound_evidence(result)
                evidence_id = f"E{len(evidence_by_key) + 1}"
                envelope = {
                    "evidence_id": evidence_id,
                    "tool": tool,
                    "arguments": arguments,
                    "result": result,
                }
                evidence_by_key[request_key] = envelope
                trace["evidence_ids"].append(evidence_id)
            round_request = {
                "evidence_id": envelope["evidence_id"],
                "tool": tool,
                "arguments": arguments,
                "result": envelope["result"],
            }
            if deduped:
                round_request["deduped"] = True
            round_trace["requests"].append(round_request)
            trace["requests"].append(round_request)
            evidence.append(envelope)
        trace["rounds"].append(round_trace)
        if not evidence:
            invalid_segments = []
            invalid_refs: List[str] = []
            invalid_diagnostics: List[Any] = []
            latest_findings = _normalize_findings(
                payload.get("findings"), segment_ids, invalid_segments, invalid_refs,
                list(trace["evidence_ids"]), invalid_diagnostics)
            if invalid_segments or invalid_refs or invalid_diagnostics:
                return fail("finding 或诊断字段无效")
            return finish(latest_findings,
                          "findings" if latest_findings else "clean")
        prompt = base_prompt + (
            "\n\n【按审校请求返回的证据】\n" +
            json.dumps(evidence, ensure_ascii=False, indent=2) +
            "\n请基于证据作最终判断；本轮不要再请求证据。")
    return fail("证据审校未收到最终判定")
