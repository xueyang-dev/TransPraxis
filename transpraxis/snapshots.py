"""Immutable, versioned final-delivery snapshots."""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


SNAPSHOT_DIR = "delivery_snapshots"
MANIFEST_FILE = "snapshot_manifest.json"
_VERSION_RE = re.compile(r"^v(\d+)$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def translation_truth_hash(state: Mapping[str, Any]) -> str:
    """Hash only the persisted source/initial/current translation triples."""
    pairs = state.get("pairs") or []
    payload = {
        "pairs": [
            {key: pair.get(key) for key in ("source", "initial_target", "target")}
            for pair in pairs if isinstance(pair, Mapping)
        ],
    }
    return _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")).encode("utf-8"))


def _artifact_payload(job_root: Path, record: Mapping[str, Any]) -> Dict[str, Any]:
    filename = str(record.get("file") or "")
    if not filename:
        return {}
    try:
        value = json.loads((Path(job_root) / filename).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def state_identity(state: Dict[str, Any]) -> str:
    """Hash the approved translation state without snapshot bookkeeping."""
    value = deepcopy(state)
    # QA confirmations, impact explanations and artifact bookkeeping are
    # review metadata, not the frozen document bytes.  They must not make an
    # otherwise identical frozen snapshot appear divergent after a reviewer
    # records a visual/Word check.
    for key in ("_source_bin", "delivery_snapshots",
                "latest_delivery_snapshot_version", "final_qa",
                "dependency_impact"):
        value.pop(key, None)
    academic = value.get("academic_state")
    if isinstance(academic, dict):
        academic.pop("artifact_status", None)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    return _sha256(payload.encode("utf-8"))


def snapshot_root(job_root: Path) -> Path:
    return Path(job_root) / SNAPSHOT_DIR


def _next_version(root: Path) -> int:
    versions = []
    if root.is_dir():
        for child in root.iterdir():
            match = _VERSION_RE.match(child.name)
            if match:
                versions.append(int(match.group(1)))
    return max(versions, default=0) + 1


def create_snapshot(
    job_root: Path,
    job_id: str,
    state: Dict[str, Any],
    assets: Mapping[str, bytes],
    source_identity: Dict[str, Any],
    active_terminology_version: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Write a new snapshot atomically; never replace an existing version."""
    root = snapshot_root(job_root)
    root.mkdir(parents=True, exist_ok=True)
    version = _next_version(root)
    final_dir = root / f"v{version}"
    temp_dir = root / f".v{version}.tmp"
    if temp_dir.exists():
        raise FileExistsError(f"snapshot temporary directory already exists: {temp_dir}")
    temp_dir.mkdir()
    try:
        asset_records = []
        for name, data in assets.items():
            if not isinstance(name, str) or not name or Path(name).name != name:
                raise ValueError(f"非法快照资产名称：{name!r}")
            if not isinstance(data, bytes):
                raise TypeError(f"快照资产必须是 bytes：{name}")
            (temp_dir / name).write_bytes(data)
            asset_records.append({
                "name": name,
                "size": len(data),
                "sha256": _sha256(data),
            })
        approval = dict(state.get("delivery_approval") or {})
        approval.setdefault("timestamp", _now_iso())
        accepted_risks = [
            dict(action) for action in state.get("human_actions") or []
            if action.get("action") == "accepted_risk"
        ]
        artifact_records = deepcopy((state.get("academic_state") or {}).get(
            "artifacts") or {})
        final_docx_record = artifact_records.get("final_docx_validation") or {}
        render_record = artifact_records.get("libreoffice_render") or {}
        report_qa_record = artifact_records.get("report_qa") or {}
        compliance_record = artifact_records.get("compliance") or {}
        final_docx_payload = _artifact_payload(job_root, final_docx_record)
        render_payload = _artifact_payload(job_root, render_record)
        truth_hash = translation_truth_hash(state)
        manifest = {
            "snapshot_version": version,
            "created_at": approval.get("timestamp") or _now_iso(),
            "job_identity": {"job_id": job_id},
            "approval": approval,
            "accepted_risks": accepted_risks,
            "source_identity": dict(source_identity or {}),
            "translation_state_identity": state_identity(state),
            "active_terminology_version": dict(active_terminology_version or {}),
            "delivery_status": "final",
            "case_reviews": deepcopy(state.get("case_reviews") or {}),
            "case_review_overrides": deepcopy(state.get("case_review_overrides") or {}),
            "compliance_state": deepcopy(state.get("compliance_record") or {}),
            "qa_state": deepcopy(state.get("final_qa") or {}),
            "translation_truth_hash": truth_hash,
            "translation_truth": deepcopy(state.get("translation_truth") or {}),
            "artifact_records": artifact_records,
            "finalization_bindings": {
                "translation_truth_hash": truth_hash,
                "compliance_hash": compliance_record.get("content_hash"),
                "qa_hash": report_qa_record.get("content_hash") or _sha256(
                    json.dumps(state.get("final_qa") or {}, ensure_ascii=False,
                               sort_keys=True, separators=(",", ":")).encode("utf-8")),
                "report_docx_hash": final_docx_payload.get("source_docx_hash") or
                final_docx_record.get("source_docx_hash"),
                "rendered_pdf_hash": render_payload.get("rendered_pdf_hash") or
                render_record.get("rendered_pdf_hash"),
                "report_qa_hash": report_qa_record.get("content_hash"),
            },
            "assets": sorted(asset_records, key=lambda item: item["name"]),
            "artifact_hashes": {
                item["name"]: item["sha256"] for item in asset_records
            },
        }
        (temp_dir / MANIFEST_FILE).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        temp_dir.rename(final_dir)
        return manifest
    except Exception:
        if temp_dir.exists():
            for child in temp_dir.iterdir():
                child.unlink()
            temp_dir.rmdir()
        raise


def list_snapshots(job_root: Path):
    root = snapshot_root(job_root)
    if not root.is_dir():
        return []
    found = []
    for child in root.iterdir():
        match = _VERSION_RE.match(child.name)
        if not match or not child.is_dir():
            continue
        try:
            manifest = json.loads((child / MANIFEST_FILE).read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            continue
        if isinstance(manifest, dict) and manifest.get("snapshot_version") == int(match.group(1)):
            found.append(manifest)
    return sorted(found, key=lambda item: int(item["snapshot_version"]))


def latest_snapshot(job_root: Path):
    snapshots = list_snapshots(job_root)
    return snapshots[-1] if snapshots else None


def load_asset(job_root: Path, version: int, name: str) -> Optional[bytes]:
    manifest = next((item for item in list_snapshots(job_root)
                     if item.get("snapshot_version") == int(version)), None)
    if manifest is None or name not in {
            item.get("name") for item in manifest.get("assets") or []}:
        return None
    path = snapshot_root(job_root) / f"v{int(version)}" / name
    try:
        data = path.read_bytes()
    except OSError:
        return None
    expected = manifest.get("artifact_hashes", {}).get(name)
    return data if expected == _sha256(data) else None


def archive(job_root: Path, version: int) -> Optional[bytes]:
    manifest = next((item for item in list_snapshots(job_root)
                     if item.get("snapshot_version") == int(version)), None)
    if manifest is None:
        return None
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for item in manifest.get("assets") or []:
            data = load_asset(job_root, version, item["name"])
            if data is None:
                return None
            bundle.writestr(item["name"], data)
        bundle.writestr(MANIFEST_FILE, json.dumps(
            manifest, ensure_ascii=False, indent=2) + "\n")
    return output.getvalue()
