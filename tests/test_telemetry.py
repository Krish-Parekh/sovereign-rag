import json

import pytest

from rag.telemetry import Metric, metrics, record


def test_metrics_have_no_dimensions(capsys: pytest.CaptureFixture[str]) -> None:
    record(Metric.RETRIEVE_MS, 12)
    record(Metric.ASK_ERRORS, 1)
    metrics.flush_metrics()

    emf = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    directive = emf["_aws"]["CloudWatchMetrics"][0]

    assert directive["Namespace"] == "SovereignRag"
    assert directive["Dimensions"] == [[]]
    assert {m["Name"]: m["Unit"] for m in directive["Metrics"]} == {"RetrieveMs": "Milliseconds", "AskErrors": "Count"}
    assert emf["RetrieveMs"] == [12.0]


def test_project_uses_seven_metrics() -> None:
    assert sorted(Metric) == sorted(
        ["RetrieveMs", "TTFTMs", "GenerateMs", "TotalMs", "TokensOut", "TopScore", "AskErrors"]
    )


def test_top_score_has_no_unit() -> None:
    assert Metric.TOP_SCORE.unit.value == "None"
