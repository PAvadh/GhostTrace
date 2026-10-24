"""
Dashboard helpers (Streamlit-free so they can be unit-tested).

Everything the dashboard shows - graph, transactions, accounts, KPIs, findings and benchmark -
is derived from ONE DatasetBundle, so a selected dataset can never be silently swapped for a
regenerated synthetic ledger.
"""

import html
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from ghost_trace.amlsim_adapter import AMLSimAdapter, AMLSimLoadResult
from ghost_trace.benchmark import BenchmarkRunner, BenchmarkSuiteResult
from ghost_trace.data_generator import LedgerData, SyntheticLedgerGenerator
from ghost_trace.graph_engine import CycleEvidence, FinancialGraphEngine, GraphInvestigationResult
from ghost_trace.visualizer import GraphVisualizer

UNAVAILABLE = "Unavailable"
SOURCE_SYNTHETIC = "synthetic"
SOURCE_AMLSIM = "amlsim"


def esc(value: Any) -> str:
    """HTML-escape untrusted text (account names, memos, IDs, error messages...). None -> ''."""
    return html.escape("" if value is None else str(value), quote=True)


# -----------------------------------------------------------------------------
# Velocity / timestamp display
# -----------------------------------------------------------------------------
def fmt_duration(c: CycleEvidence) -> str:
    if not getattr(c, "velocity_available", True):
        return UNAVAILABLE
    if c.total_duration_hours <= 0.01:
        return "<0.01 h"
    return f"{c.total_duration_hours:.2f} h"


def fmt_hops_per_hour(c: CycleEvidence) -> str:
    if not getattr(c, "velocity_available", True):
        return UNAVAILABLE
    if c.total_duration_hours <= 0.01:
        return "Near-simultaneous"
    return f"{c.hops_per_hour:.2f} hops/hr"


def fmt_avg_hop(c: CycleEvidence) -> str:
    if not getattr(c, "velocity_available", True) or not c.time_gaps_minutes:
        return UNAVAILABLE
    return f"{c.avg_hop_interval_minutes:.1f} min"


def velocity_label(c: CycleEvidence) -> str:
    """Short descriptor for the delta line under the velocity KPI."""
    if not getattr(c, "velocity_available", True):
        return "Timestamps unavailable"
    return "Rapid Velocity" if c.hops_per_hour > 1.0 else "Slow Commercial"


# -----------------------------------------------------------------------------
# Dataset selection: one bundle drives every view
# -----------------------------------------------------------------------------
@dataclass
class DatasetBundle:
    source: str                       # SOURCE_SYNTHETIC | SOURCE_AMLSIM
    label: str                        # human-readable
    key: str                          # stable cache key identifying exactly this dataset
    ledger: Optional[LedgerData]
    result: Optional[GraphInvestigationResult]
    load_result: Optional[AMLSimLoadResult] = None
    scenario: Optional[str] = None
    seed: Optional[int] = None

    @property
    def ok(self) -> bool:
        return self.ledger is not None and self.result is not None

    @property
    def is_synthetic(self) -> bool:
        return self.source == SOURCE_SYNTHETIC


def synthetic_key(scenario: str, seed: int) -> str:
    return f"synthetic|{scenario}|{seed}"


def amlsim_path_key(path: str, max_rows: int) -> str:
    return f"amlsim-file|{path}|{max_rows}"


def amlsim_upload_key(filename: str, content_hash: str, max_rows: int) -> str:
    return f"amlsim-upload|{filename}|{content_hash}|{max_rows}"


def load_synthetic(scenario: str, seed: int) -> DatasetBundle:
    ledger = SyntheticLedgerGenerator(seed=seed).generate_scenario(scenario_type=scenario)
    result = FinancialGraphEngine().run_investigation(ledger)
    return DatasetBundle(SOURCE_SYNTHETIC, ledger.scenario_name, synthetic_key(scenario, seed),
                         ledger, result, None, scenario, seed)


def _bundle_from_load(load_result: AMLSimLoadResult, label: str, key: str) -> DatasetBundle:
    if not load_result.success:
        return DatasetBundle(SOURCE_AMLSIM, label, key, None, None, load_result)
    result = FinancialGraphEngine().run_investigation(load_result.ledger)
    return DatasetBundle(SOURCE_AMLSIM, label, key, load_result.ledger, result, load_result)


def load_amlsim_file(path: str, max_rows: int) -> DatasetBundle:
    lr = AMLSimAdapter(max_rows=max_rows).load_csv(path)
    return _bundle_from_load(lr, str(path).replace("\\", "/").split("/")[-1], amlsim_path_key(path, max_rows))


def load_amlsim_bytes(file_bytes: bytes, filename: str, max_rows: int) -> DatasetBundle:
    import hashlib
    lr = AMLSimAdapter(max_rows=max_rows).load_from_bytes(file_bytes, filename)
    return _bundle_from_load(lr, filename, amlsim_upload_key(filename, hashlib.sha1(file_bytes).hexdigest()[:12], max_rows))


# -----------------------------------------------------------------------------
# Views derived from the bundle (graph, benchmark)
# -----------------------------------------------------------------------------
def render_graph_html(bundle: DatasetBundle, filter_mode: str = "all",
                      selected_cycle_id: Optional[str] = None, height: str = "580px") -> str:
    """Graph for exactly the bundle's ledger/result. Identifiers are masked for synthetic data
    (its IDs/names can reveal labels); real AMLSim identifiers are shown as loaded."""
    vis = GraphVisualizer(height=height, width="100%", mask_identifiers=bundle.is_synthetic)
    return vis.generate_html(bundle.ledger, bundle.result, filter_mode=filter_mode,
                             selected_cycle_id=selected_cycle_id)


def run_benchmark(bundle: DatasetBundle) -> BenchmarkSuiteResult:
    """Benchmark on the bundle's own ledger and engine result (never a regenerated ledger)."""
    runner = BenchmarkRunner(seed=bundle.seed if bundle.seed is not None else 0)
    return runner.run_benchmark_on_ledger(
        bundle.ledger, graph_result=bundle.result,
        dataset_source=bundle.source, dataset_label=bundle.label, seed=bundle.seed,
    )


def kpi_summary(bundle: DatasetBundle) -> dict:
    """KPI numbers shown in the header cards, computed from the bundle only."""
    r, led = bundle.result, bundle.ledger
    return {
        "accounts": r.total_accounts,
        "transactions": r.total_transactions,
        "ledger_accounts": len(led.accounts),
        "ledger_transactions": len(led.transactions),
        "flagged_cycles": len(r.flagged_cycles),
        "total_cycles": len(r.detected_cycles),
        "smurfing_clusters": len(r.smurfing_clusters),
        "flagged_accounts": len(r.flagged_accounts),
        "flagged_transactions": len(r.flagged_tx_ids),
    }
