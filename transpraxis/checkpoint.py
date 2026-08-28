"""Crash-safe batch checkpoints and translation-memory reconciliation."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from . import translation_target


EVENTS_FILE = "events.jsonl"


def events_path(job_root: Path) -> Path:
    return Path(job_root) / EVENTS_FILE


def append_event(job_root: Path, event: Dict[str, Any]) -> None:
    """Append one durable, JSON-serializable workflow event."""
    path = events_path(job_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_events(job_root: Path) -> List[Dict[str, Any]]:
    path = events_path(job_root)
    if not path.is_file():
        return []
    events = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                events.append(value)
    except OSError:
        return []
    return events


def recovery_summary(job_root: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    """Summarize durable progress for the UI without changing resume semantics."""
    root = Path(job_root)
    events = read_events(root)
    started: Dict[int, Dict[str, Any]] = {}
    committed = set()
    last_completed_stage = "尚未开始"
    phase_labels = {
        "generation_done": "批次翻译完成",
        "deterministic_qa_done": "自动质量检查完成",
        "semantic_review_done": "独立审校完成",
        "semantic_review_skipped": "独立审校已跳过",
        "knowledge_feedback_done": "知识反馈完成",
        "state_commit_done": "进度已保存",
        "tm_promotion_done": "翻译记忆已同步",
    }
    for event in events:
        batch = event.get("batch")
        if isinstance(batch, int) and batch >= 0:
            if event.get("phase") == "generation_started":
                started[batch] = event
            elif event.get("phase") == "state_commit_done":
                committed.add(batch)
        label = phase_labels.get(event.get("phase"))
        if label:
            last_completed_stage = label

    all_batches = set(started) | committed
    total_batches = max(all_batches) + 1 if all_batches else 0
    completed_batches = sorted(committed)
    reviewed_batches = int((state.get("review_stats") or {}).get("batches_reviewed") or 0)
    if reviewed_batches:
        total_batches = max(total_batches, reviewed_batches)
    pairs = state.get("pairs") or []
    current = None
    for batch in sorted(started):
        event = started[batch]
        offset = event.get("offset")
        segment_count = event.get("segment_count")
        if not isinstance(offset, int) or not isinstance(segment_count, int):
            continue
        saved_in_batch = max(0, min(segment_count, len(pairs) - offset))
        if batch not in committed or saved_in_batch < segment_count:
            current = {
                "number": batch + 1,
                "start_segment": offset,
                "end_segment": offset + segment_count - 1,
                "completed_segments": saved_in_batch,
                "segment_count": segment_count,
                "regenerate_segments": segment_count - saved_in_batch,
            }
            break

    durable_times = []
    for name in ("state.json", EVENTS_FILE):
        try:
            durable_times.append((root / name).stat().st_mtime)
        except OSError:
            pass
    last_saved_at = None
    if durable_times:
        last_saved_at = datetime.fromtimestamp(max(durable_times)).astimezone().isoformat(
            timespec="seconds")

    stage = str(state.get("stage") or "")
    if last_completed_stage == "尚未开始":
        last_completed_stage = {
            "TERMS_PREPARED": "术语准备完成",
            "GLOSSARY_FROZEN": "术语已确认",
            "TRANSLATING": "术语已确认",
            "TRANSLATED": "批次翻译完成",
            "REVIEW_REQUIRED": "独立审校完成",
            "FINAL": "交付已确认",
        }.get(stage, last_completed_stage)
    can_resume = bool(current) or (
        bool(state.get("p1_done")) and not state.get("p2_done")
        and stage in {"GLOSSARY_FROZEN", "TRANSLATING"}
    )
    return {
        "auto_save_enabled": True,
        "last_saved_at": last_saved_at,
        "completed_batches": completed_batches,
        "completed_batch_count": max(len(completed_batches), reviewed_batches),
        "total_batches": total_batches,
        "current_batch": current,
        "can_resume": can_resume,
        "last_completed_stage": last_completed_stage,
        "recovered_tm_entries": int(state.get("tm_recovered_count") or 0),
        "event_count": len(events),
    }


def _eligible(source: str, target: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9\u4e00-\u9fff]", str(source or ""))) \
        and bool(str(target or "").strip()) \
        and not translation_target.is_translation_transport_wrapper(target)


def _state_entries(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    entries = {}
    for pair in state.get("pairs") or []:
        if not pair.get("reviewed") or pair.get("stale_due_to_glossary"):
            continue
        source, target = pair.get("source"), pair.get("target")
        if _eligible(source, target):
            entries[str(source)] = {"target": str(target), "reviewed": True}
    return entries


def reconcile_translation_memory(
    tm: Dict[str, Dict[str, Any]],
    state: Dict[str, Any],
    job_root: Path,
) -> Tuple[bool, int]:
    """Recover accepted state entries and pending TM promotions after restart."""
    desired = _state_entries(state)
    initial_tm = dict(tm)
    recovered_sources = set()
    events = read_events(job_root)
    promoted_batches = {event.get("batch") for event in events
                        if event.get("phase") in {"tm_promoted", "tm_promotion_done"}}
    for event in events:
        if event.get("phase") != "tm_promotion_pending":
            continue
        if event.get("batch") in promoted_batches:
            continue
        for item in event.get("entries") or []:
            source, target = item.get("source"), item.get("target")
            if _eligible(source, target):
                source = str(source)
                entry = {"target": str(target), "reviewed": True}
                desired[source] = entry
                if initial_tm.get(source) != entry:
                    recovered_sources.add(source)
    changed = False
    for source, entry in desired.items():
        if tm.get(source) != entry:
            tm[source] = entry
            changed = True
    return changed, len(recovered_sources)


def batch_entries(pairs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"source": str(pair.get("source") or ""),
         "target": str(pair.get("target") or "")}
        for pair in pairs
        if pair.get("reviewed") and not pair.get("stale_due_to_glossary")
        and _eligible(pair.get("source"), pair.get("target"))
    ]
