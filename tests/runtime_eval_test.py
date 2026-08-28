import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.runtime_regression import run_runtime_regression


def test_runtime_regression_fixture_shows_runtime_gain():
    result = run_runtime_regression()
    assert result["baseline"]["term_unique_forms"]["volumetric sensing"] == 2
    assert result["runtime"]["term_unique_forms"]["volumetric sensing"] == 1
    assert result["baseline"]["entity_unique_forms"]["The Repellent Fence"] == 2
    assert result["runtime"]["entity_unique_forms"]["The Repellent Fence"] == 1
    assert result["runtime"]["segment_alignment"]
    assert result["runtime"]["source_structural_integrity"]
    assert result["malformed_output_rejected"]
