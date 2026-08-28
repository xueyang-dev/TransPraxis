"""Offline regression for the anonymous MTI finalization fixture."""
from eval.mti_finalization_regression import run_regression


def test_anonymous_mti_finalization_fixture():
    result = run_regression()
    assert result == {
        "authentic_case_count": 1,
        "synthetic_case_count": 1,
        "approved_synthetic_remains_non_historical": True,
        "contains_private_paper_text": False,
    }
