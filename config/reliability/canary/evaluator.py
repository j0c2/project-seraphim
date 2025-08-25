"""Canary evaluator comparing baseline vs candidate model responses.
Criteria: latency p95, error rate, optional accuracy proxy.
"""
from dataclasses import dataclass

@dataclass
class Metrics:
    p95_latency_ms: float
    error_rate: float
    score: float | None = None  # optional accuracy proxy


def passes_canary(baseline: Metrics, candidate: Metrics,
                  max_latency_regress_ms: float = 25,
                  max_error_regress: float = 0.005,
                  min_score_delta: float | None = None) -> bool:
    if candidate.p95_latency_ms > baseline.p95_latency_ms + max_latency_regress_ms:
        return False
    if candidate.error_rate > baseline.error_rate + max_error_regress:
        return False
    if min_score_delta is not None and (candidate.score or 0) < (baseline.score or 0) + min_score_delta:
        return False
    return True
