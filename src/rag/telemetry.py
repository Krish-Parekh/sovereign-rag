from enum import StrEnum

from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger(service="sovereign-rag")
metrics = Metrics(namespace="SovereignRag", service="")


class Metric(StrEnum):
    RETRIEVE_MS = "RetrieveMs"
    TTFT_MS = "TTFTMs"
    GENERATE_MS = "GenerateMs"
    TOTAL_MS = "TotalMs"
    TOKENS_OUT = "TokensOut"
    TOP_SCORE = "TopScore"
    ASK_ERRORS = "AskErrors"

    @property
    def unit(self) -> MetricUnit:
        if self.endswith("Ms"):
            return MetricUnit.Milliseconds
        if self is Metric.TOP_SCORE:
            return MetricUnit.NoUnit
        return MetricUnit.Count


def record(metric: Metric, value: float) -> None:
    metrics.add_metric(name=metric, unit=metric.unit, value=value)
