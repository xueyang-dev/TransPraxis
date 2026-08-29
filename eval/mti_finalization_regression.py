"""Offline structural regression for the anonymous MTI finalization fixture."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


FIXTURE = Path(__file__).parent / "fixtures" / "mti_finalization_regression.json"


def load_fixture() -> Dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def run_regression() -> Dict[str, Any]:
    fixture = load_fixture()
    cases = fixture.get("cases") or []
    authentic = [case for case in cases
                 if case.get("case_type") == "authentic_revision"]
    synthetic = [case for case in cases
                 if case.get("case_type") == "synthetic_contrast"]
    private_markers = ("PRIVATE_INSTITUTION", "论文_MTI", "state.json", "outputs/")
    serialized = json.dumps(fixture, ensure_ascii=False)
    approved_synthetic_is_non_historical = all(
        case.get("review_status") == "approved"
        and case.get("case_origin") == "SYNTHETIC_BASELINE"
        and (case.get("text_role") or {}).get("initial") == "SYNTHETIC_BASELINE"
        and (case.get("text_role") or {}).get("target") == "CURRENT_TRANSLATION"
        and "historical_initial" not in case
        and bool(case.get("synthetic_baseline"))
        for case in synthetic
    )
    result = {
        "authentic_case_count": len(authentic),
        "synthetic_case_count": len(synthetic),
        "approved_synthetic_remains_non_historical": (
            approved_synthetic_is_non_historical
        ),
        "contains_private_paper_text": any(marker in serialized
                                             for marker in private_markers),
    }
    expected = fixture.get("expected") or {}
    assert result["authentic_case_count"] == expected["authentic_case_count"]
    assert result["synthetic_case_count"] == expected["synthetic_case_count"]
    assert result["approved_synthetic_remains_non_historical"] == expected[
        "approved_synthetic_remains_non_historical"]
    assert result["contains_private_paper_text"] == expected[
        "contains_private_paper_text"]
    return result


if __name__ == "__main__":
    print(json.dumps(run_regression(), ensure_ascii=False, indent=2))
