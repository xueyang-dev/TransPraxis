"""任务状态机与旧 state.json 迁移。

阶段（stage）：
    INGESTED -> PROFILED -> TERMS_PREPARED -> GLOSSARY_FROZEN -> TRANSLATING -> TRANSLATED
    -> ANNOTATED -> ACADEMIC_WRITING -> REPORT_GENERATED -> REVIEW_REQUIRED / FINAL

兼容性：
- 旧任务只有 p1_done / p2_done / p3_done / annotations_done；
- migrate_state 只补默认值，不把旧任务虚假标记为 glossary 已冻结；
- 交付状态（delivery_status）默认 draft；旧任务即使全部完成也保持 draft，
  需要人工确认后才进入 final。
"""
from __future__ import annotations

from typing import Any, Dict

STAGES = (
    "INGESTED", "PROFILED", "TERMS_PREPARED", "GLOSSARY_FROZEN", "TRANSLATING", "TRANSLATED",
    "ANNOTATED", "ACADEMIC_WRITING", "ACADEMIC_REVIEW_REQUIRED",
    "ACADEMIC_FAILED", "REPORT_GENERATED", "REVIEW_REQUIRED", "FINAL",
)

DELIVERY_STATUSES = ("draft", "review_required", "approved", "final")


def _default_new_fields() -> Dict[str, Any]:
    """新增字段的默认值（旧任务加载时补齐，避免 KeyError）。"""
    from .academic_writer import default_academic_state
    from .finalization import default_dependency_impact, default_final_qa
    return {
        "stage": "INGESTED",
        "delivery_status": "draft",
        "document_profile": None,
        "profile_done": False,
        "profile_warnings": [],
        "semantic_units": [],
        "section_digests": [],
        "document_synopsis": None,
        "understanding_done": False,
        "understanding_warnings": [],
        "context_packet_log": [],
        "knowledge_candidates": [],
        "translation_continuity": [],
        "knowledge_events": [],
        "knowledge_feedback_failures": 0,
        "entity_registry": [],
        "translation_failures": [],
        "review_evidence": [],
        "repair_overlays": [],
        "tm_recovered_count": 0,
        "auto_term_entries": [],
        "glossary": [],
        "glossary_draft": [],
        "glossary_frozen": None,
        "glossary_versions": [],
        "glossary_injection_log": [],
        "human_actions": [],
        "delivery_manifest": {},
        "delivery_approved_by_human": False,
        "delivery_approval": None,
        "delivery_snapshots": [],
        "latest_delivery_snapshot_version": None,
        "exported_assets": [],
        "pipeline_config": {},
        "translator_config": {},
        "reviewer_config": {},
        "delivery_config": {},
        "quality_mode": False,
        "quality_bypass": False,
        "delivery_notes": "",
        "delivery_validation": {},
        "research_settings": {},
        "literature_sources": [],
        "report_template": None,
        "report_template_contract": None,
        # v0.4 finalization state.  These are intentionally plain records in
        # state.json so older jobs can be opened without a migration step.
        "translation_truth": {
            "authority": "CURRENT_TRANSLATION",
            "version": 0,
            "last_changed_at": None,
            "last_change": None,
        },
        "dependency_impact": default_dependency_impact(),
        "case_reviews": {},
        "case_review_overrides": {},
        "final_qa": default_final_qa(),
        "compliance_profile_id": "MTI_PRACTICE_REPORT_DEFAULT",
        "compliance_record": {},
        "language_constraint_record": {},
        "academic_state": default_academic_state(),
    }


def derive_stage(state: Dict[str, Any]) -> str:
    """由现有里程碑标志推导当前阶段（不修改状态）。"""
    if not state.get("p1_done"):
        return "INGESTED"

    # 1) 翻译已开始但尚未完成 → TRANSLATING
    if state.get("p1_done") and not state.get("p2_done"):
        pairs = state.get("pairs") or []
        if pairs and (state.get("glossary_frozen") or state.get("quality_bypass")):
            return "TRANSLATING"
    # 2) 术语表已冻结 → GLOSSARY_FROZEN
    if not state.get("p2_done") and state.get("glossary_frozen"):
        return "GLOSSARY_FROZEN"
    # 3) 术语已提取但未冻结 → TERMS_PREPARED（优先于 profile_done 检查）
    if not state.get("p2_done") and (state.get("auto_term_entries") or state.get("auto_terms") \
            or state.get("glossary") or state.get("glossary_draft")):
        return "TERMS_PREPARED"
    # 4) 画像完成 → PROFILED
    if not state.get("p2_done") and state.get("profile_done"):
        return "PROFILED"
    # 5) p1 完成但画像未完成 → PROFILED（仍可进入术语准备）
    if not state.get("p2_done"):
        return "PROFILED"
    if state.get("has_blocking"):
        return "REVIEW_REQUIRED"
    academic = state.get("academic_state") or {}
    if academic.get("status") == "failed" or academic.get("quality_status") == "fail":
        return "ACADEMIC_FAILED"
    if academic.get("quality_status") == "review_required":
        return "ACADEMIC_REVIEW_REQUIRED"
    if academic.get("status") == "in_progress":
        return "ACADEMIC_WRITING"
    if state.get("p3_done") or not state.get("report_enabled", True):
        return "REPORT_GENERATED"
    if state.get("annotations_done"):
        return "ANNOTATED"
    return "TRANSLATED"


def derive_delivery_status(state: Dict[str, Any]) -> str:
    """由现有状态推导交付状态。

    规则：翻译完成且有 blocking -> review_required；
    其余保持 draft（final 只能由人工确认产生，旧任务不得自动变 final）。
    """
    if state.get("p2_done") and state.get("has_blocking"):
        return "review_required"
    return "draft"


def migrate_state(state: Any) -> Dict[str, Any]:
    """迁移旧任务状态：补默认字段、推导 stage 与 delivery_status。

    不修改 p1/p2/p3 等旧字段；不清空旧数据；glossary_frozen 保持 None。
    """
    if not isinstance(state, dict):
        return dict(_default_new_fields())
    out = dict(state)
    for key, default in _default_new_fields().items():
        if key not in out or out[key] is None:
            out[key] = default
    # v0.4 exposes one anonymous default profile. Unknown or private profile
    # identifiers are not preserved in public-facing state until custom
    # profile import exists.
    out["compliance_profile_id"] = "MTI_PRACTICE_REPORT_DEFAULT"

    # 旧任务可能把新字段存成空串/空 dict，统一归一化
    if out.get("glossary") == {}:
        out["glossary"] = []
    if out.get("auto_term_entries") == {}:
        out["auto_term_entries"] = []
    if not out.get("translation_continuity") and out.get("knowledge_candidates"):
        out["translation_continuity"] = list(out.get("knowledge_candidates") or [])
    for candidate in out.get("knowledge_candidates") or []:
        if isinstance(candidate, dict):
            candidate.setdefault("provenance", "generated_continuity")
            candidate.setdefault("scope", "document")
            candidate.setdefault("confidence", 0.35)
    from . import entity_registry
    out["entity_registry"] = entity_registry.normalize_registry(
        out.get("entity_registry") or [])

    # An explicitly approved delivery is a durable milestone, not a value to
    # recompute from the mutable processing flags on reload.
    out["stage"] = "FINAL" if out.get("delivery_status") == "final" \
        else derive_stage(out)
    # 只在不显式设置过交付状态时推导；显式 final/approved 不覆盖
    if out.get("delivery_status") not in ("approved", "final"):
        out["delivery_status"] = derive_delivery_status(out)
    return out
