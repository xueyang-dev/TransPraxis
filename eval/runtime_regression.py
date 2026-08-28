"""Deterministic runtime-vs-raw regression eval; no paid provider required."""
from __future__ import annotations

import json
import re
from pathlib import Path
import sys
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core
from transpraxis.entity_registry import EntityRegistry
from transpraxis.translation_protocol import parse_translation_array


FIXTURE = Path(__file__).parent / "fixtures" / "runtime_regression.json"


def load_fixture() -> Dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _mock_provider_response(user_prompt: str, fixture: Dict[str, Any]) -> str:
    """A stable provider double that still obeys the runtime call boundary."""
    current = user_prompt.split("【待翻译段落（按序号返回等长数组）】", 1)[-1]
    sources = re.findall(r"(?m)^\d+\.\s+(.+)$", current)
    targets = []
    for source in sources:
        for item in fixture["segments"]:
            if item["source"] == source:
                targets.append(item["runtime_target"])
                break
        else:
            targets.append("这是完整的中文译文。")
    return json.dumps(targets, ensure_ascii=False)


def run_runtime_regression() -> Dict[str, Any]:
    """Compare deterministic raw and runtime contract metrics."""
    fixture = load_fixture()
    sources = [item["source"] for item in fixture["segments"]]
    raw_targets = [item["raw_target"] for item in fixture["segments"]]
    runtime_targets = core.translate_batch(
        sources, [], [], "", "", fixture["target_language"],
        "runtime-mock", "key", "mock-model",
        call_llm_fn=lambda provider, key, model, system, user, **kwargs:
            _mock_provider_response(user, fixture),
    )

    def values(field: str, targets: List[str], target_field: str = "") -> Dict[str, List[str]]:
        output = {}
        for index, item in enumerate(fixture["segments"]):
            key = item.get(field)
            if key:
                output.setdefault(key, []).append(
                    fixture["segments"][index].get(target_field) or targets[index]
                    if target_field else targets[index]
                )
        return output

    raw_term_values = values("term", raw_targets, "raw_term_target")
    runtime_term_values = values("term", runtime_targets, "runtime_term_target")
    raw_entity_values = values("entity", raw_targets, "raw_entity_target")
    runtime_entity_values = values("entity", runtime_targets, "runtime_entity_target")
    registry = EntityRegistry()
    for index, item in enumerate(fixture["segments"]):
        if item.get("entity"):
            registry.observe(
                item["entity"], item.get("runtime_entity_target") or runtime_targets[index],
                entity_type="artwork",
                segment_id=index, provenance="generated_observation",
            )
    invariant = core.validate_translation_pairs([
        {"source": source, "target": target}
        for source, target in zip(sources, runtime_targets)
    ], target_lang=fixture["target_language"])
    return {
        "baseline": {
            "term_unique_forms": {
                key: len(set(values)) for key, values in raw_term_values.items()
            },
            "entity_unique_forms": {
                key: len(set(values)) for key, values in raw_entity_values.items()
            },
        },
        "runtime": {
            "term_unique_forms": {
                key: len(set(values)) for key, values in runtime_term_values.items()
            },
            "entity_unique_forms": {
                key: len(set(values)) for key, values in runtime_entity_values.items()
            },
            "segment_alignment": len(runtime_targets) == len(sources),
            "source_structural_integrity": not invariant["blocking"],
            "entity_findings": registry.consistency_findings(),
        },
        "malformed_output_rejected": (
            parse_translation_array(fixture["malformed_response"], 1) is None
        ),
    }


if __name__ == "__main__":
    print(json.dumps(run_runtime_regression(), ensure_ascii=False, indent=2))
