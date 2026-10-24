"""
Tests for Benchmark Suite Runner and Metric Computations
"""

import pytest
from ghost_trace.benchmark import BenchmarkRunner


def test_benchmark_runner_mixed_ledger():
    runner = BenchmarkRunner(seed=42)
    res = runner.run_benchmark("mixed_ledger")

    assert res.ghost_trace_metrics.f1_score > 0.80
    assert res.ghost_trace_metrics.recall >= 0.80
    assert res.ghost_trace_metrics.precision >= 0.80

    # Single-event baseline must suffer from low recall due to structured mule transactions (< $10k)
    assert res.baseline_metrics.recall < res.ghost_trace_metrics.recall
    assert res.baseline_metrics.f1_score < res.ghost_trace_metrics.f1_score

    df = res.to_dataframe()
    assert len(df) == 2
    assert "F1 Score" in df.columns
