"""
Labelled Synthetic Benchmark Suite
Evaluates GhostTrace Graph Engine vs Traditional Single-Event Threshold Baseline
across diverse topologies: Vampire Mule Rings, Smurfing Structuring, Normal Noise,
and Legitimate Look-Alike Loops (Commercial Rebates).
Computes honest metrics: TP, FP, TN, FN, Precision, Recall, F1 Score, False Positive Rate (FPR), and Execution Latency.
"""

from dataclasses import dataclass, field
import time
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd

from ghost_trace.data_generator import SyntheticLedgerGenerator, LedgerData
from ghost_trace.graph_engine import FinancialGraphEngine, GraphInvestigationResult
from ghost_trace.config import BSA_REPORTING_LIMIT, EngineRulesConfig


@dataclass
class ModelMetrics:
    model_name: str
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float
    false_positive_rate: float  # FP / (FP + TN)
    execution_time_ms: float
    total_evaluated: int
    metrics_available: bool = True  # False when the dataset has no ground-truth labels

    def to_dict(self) -> Dict[str, Any]:
        if not self.metrics_available:
            na = "N/A (no labels)"
            return {
                "Model / Engine": self.model_name,
                "True Positives (TP)": na,
                "False Positives (FP)": na,
                "True Negatives (TN)": na,
                "False Negatives (FN)": na,
                "Precision": na,
                "Recall": na,
                "F1 Score": na,
                "False Positive Rate (FPR)": na,
                "Latency": f"{self.execution_time_ms:.1f} ms"
            }
        return {
            "Model / Engine": self.model_name,
            "True Positives (TP)": self.true_positives,
            "False Positives (FP)": self.false_positives,
            "True Negatives (TN)": self.true_negatives,
            "False Negatives (FN)": self.false_negatives,
            "Precision": f"{self.precision * 100:.1f}%",
            "Recall": f"{self.recall * 100:.1f}%",
            "F1 Score": f"{self.f1_score:.3f}",
            "False Positive Rate (FPR)": f"{self.false_positive_rate * 100:.1f}%",
            "Latency": f"{self.execution_time_ms:.1f} ms"
        }


@dataclass
class BenchmarkSuiteResult:
    scenario_tested: str
    ledger_size: Dict[str, int]
    ghost_trace_metrics: ModelMetrics
    baseline_metrics: ModelMetrics
    summary_analysis: str
    timestamp: float = field(default_factory=time.time)
    # Provenance: exactly what was evaluated
    dataset_source: str = "synthetic"      # 'synthetic' or 'amlsim'
    dataset_label: str = ""                # human-readable dataset / file / scenario name
    seed: Optional[int] = None             # generator seed (synthetic only)
    labelled_positive_count: int = 0       # transactions labelled as laundering in the dataset
    labels_available: bool = True          # False => precision/recall/F1/FPR not computable

    def provenance_caption(self) -> str:
        seed_txt = f" | seed {self.seed}" if self.seed is not None else ""
        src = "IBM AMLSim" if self.dataset_source == "amlsim" else "GhostTrace Synthetic"
        lbl = (f"{self.labelled_positive_count} labelled positive tx" if self.labels_available
               else "no ground-truth labels")
        return (f"Evaluated: {src} | {self.dataset_label or self.scenario_tested}{seed_txt} | "
                f"{self.ledger_size.get('accounts', 0)} accounts, {self.ledger_size.get('transactions', 0)} transactions | {lbl}")

    def to_dataframe(self) -> pd.DataFrame:
        data = [self.ghost_trace_metrics.to_dict(), self.baseline_metrics.to_dict()]
        return pd.DataFrame(data)


class BenchmarkRunner:
    """Orchestrates comprehensive comparative evaluation against legacy compliance baselines."""

    def __init__(self, seed: int = 1337, rules: EngineRulesConfig = None):
        self.seed = seed
        self.generator = SyntheticLedgerGenerator(seed=seed)
        self.rules = rules or EngineRulesConfig()
        self.graph_engine = FinancialGraphEngine(rules=self.rules)

    def run_benchmark(self, scenario_type: str = "mixed_ledger") -> BenchmarkSuiteResult:
        """Generates the synthetic scenario and evaluates it (see run_benchmark_on_ledger)."""
        ledger = self.generator.generate_scenario(scenario_type=scenario_type)
        return self.run_benchmark_on_ledger(
            ledger, dataset_source="synthetic", dataset_label=ledger.scenario_name, seed=self.seed
        )

    def run_benchmark_on_ledger(
        self,
        ledger: LedgerData,
        graph_result: Optional[GraphInvestigationResult] = None,
        dataset_source: str = "synthetic",
        dataset_label: str = "",
        seed: Optional[int] = None,
    ) -> BenchmarkSuiteResult:
        """
        Evaluates GhostTrace and the legacy baseline on the GIVEN ledger (e.g. the one the
        dashboard is currently showing). If `graph_result` is supplied it is reused so the
        benchmark and the dashboard cannot disagree; otherwise the engine is run here.
        Ground-truth labels are used only to score results, never as detection input.
        """
        positives = sum(1 for tx in ledger.transactions if tx.is_ground_truth_fraud)
        labels_available = (dataset_source == "synthetic") or positives > 0

        # ---------------------------------------------------------------------
        # 1. Evaluate GhostTrace Graph Engine
        # ---------------------------------------------------------------------
        t_gt_start = time.perf_counter()
        gt_result: GraphInvestigationResult = (
            graph_result if graph_result is not None else self.graph_engine.run_investigation(ledger)
        )
        t_gt_end = time.perf_counter()
        gt_exec_ms = (t_gt_end - t_gt_start) * 1000.0
        if graph_result is not None:
            gt_exec_ms = graph_result.execution_time_ms

        gt_flagged_txs = set(gt_result.flagged_tx_ids)

        gt_tp = 0
        gt_fp = 0
        gt_tn = 0
        gt_fn = 0

        for tx in ledger.transactions:
            is_ground_truth_fraud = tx.is_ground_truth_fraud
            is_model_flagged = tx.tx_id in gt_flagged_txs

            if is_ground_truth_fraud and is_model_flagged:
                gt_tp += 1
            elif not is_ground_truth_fraud and is_model_flagged:
                gt_fp += 1
            elif not is_ground_truth_fraud and not is_model_flagged:
                gt_tn += 1
            elif is_ground_truth_fraud and not is_model_flagged:
                gt_fn += 1

        gt_prec = gt_tp / (gt_tp + gt_fp) if (gt_tp + gt_fp) > 0 else 0.0
        gt_rec = gt_tp / (gt_tp + gt_fn) if (gt_tp + gt_fn) > 0 else 0.0
        gt_f1 = (2 * gt_prec * gt_rec) / (gt_prec + gt_rec) if (gt_prec + gt_rec) > 0 else 0.0
        gt_fpr = gt_fp / (gt_fp + gt_tn) if (gt_fp + gt_tn) > 0 else 0.0

        gt_metrics = ModelMetrics(
            model_name="GhostTrace Graph Engine (Multi-Agent)",
            true_positives=gt_tp,
            false_positives=gt_fp,
            true_negatives=gt_tn,
            false_negatives=gt_fn,
            precision=gt_prec,
            recall=gt_rec,
            f1_score=gt_f1,
            false_positive_rate=gt_fpr,
            execution_time_ms=gt_exec_ms,
            total_evaluated=len(ledger.transactions),
            metrics_available=labels_available
        )

        # ---------------------------------------------------------------------
        # 2. Evaluate Baseline: Legacy Single-Event Rule Engine
        # (Rule: Flag transaction if amount >= $10,000 BSA threshold)
        # ---------------------------------------------------------------------
        t_base_start = time.perf_counter()
        base_flagged_txs = set()
        for tx in ledger.transactions:
            if tx.amount >= BSA_REPORTING_LIMIT:
                base_flagged_txs.add(tx.tx_id)
        t_base_end = time.perf_counter()
        base_exec_ms = (t_base_end - t_base_start) * 1000.0

        base_tp = 0
        base_fp = 0
        base_tn = 0
        base_fn = 0

        for tx in ledger.transactions:
            is_ground_truth_fraud = tx.is_ground_truth_fraud
            is_base_flagged = tx.tx_id in base_flagged_txs

            if is_ground_truth_fraud and is_base_flagged:
                base_tp += 1
            elif not is_ground_truth_fraud and is_base_flagged:
                base_fp += 1
            elif not is_ground_truth_fraud and not is_base_flagged:
                base_tn += 1
            elif is_ground_truth_fraud and not is_base_flagged:
                base_fn += 1

        base_prec = base_tp / (base_tp + base_fp) if (base_tp + base_fp) > 0 else 0.0
        base_rec = base_tp / (base_tp + base_fn) if (base_tp + base_fn) > 0 else 0.0
        base_f1 = (2 * base_prec * base_rec) / (base_prec + base_rec) if (base_prec + base_rec) > 0 else 0.0
        base_fpr = base_fp / (base_fp + base_tn) if (base_fp + base_tn) > 0 else 0.0

        base_metrics = ModelMetrics(
            model_name="Legacy Rule Baseline (Single-Event >= $10k)",
            true_positives=base_tp,
            false_positives=base_fp,
            true_negatives=base_tn,
            false_negatives=base_fn,
            precision=base_prec,
            recall=base_rec,
            f1_score=base_f1,
            false_positive_rate=base_fpr,
            execution_time_ms=base_exec_ms,
            total_evaluated=len(ledger.transactions),
            metrics_available=labels_available
        )

        src_txt = "IBM AMLSim" if dataset_source == "amlsim" else "GhostTrace Synthetic"
        seed_txt = f", seed {seed}" if seed is not None else ""
        header = f"Benchmark on {src_txt} '{dataset_label or ledger.scenario_name}'{seed_txt} ({len(ledger.transactions)} transactions):\n"
        if labels_available:
            summary = (
                header +
                f"- GhostTrace: F1={gt_f1:.3f}, Recall={gt_rec*100:.1f}%, Precision={gt_prec*100:.1f}%, "
                f"FPR={gt_fpr*100:.1f}% in {gt_exec_ms:.1f}ms.\n"
                f"- Legacy Baseline: F1={base_f1:.3f}, Recall={base_rec*100:.1f}%, Precision={base_prec*100:.1f}%, "
                f"FPR={base_fpr*100:.1f}%.\n"
                f"Analysis: Legacy rules suffer high False Negative rates on structured mule transfers (<$10,000) "
                f"and high False Positive Rates on benign commercial high-value invoices."
            )
        else:
            summary = (
                header +
                "- This dataset contains no ground-truth laundering labels, so precision, recall, F1 and FPR "
                "are not computable and are shown as N/A (not 0).\n"
                f"- GhostTrace flagged {len(gt_flagged_txs)} transaction(s) in {gt_exec_ms:.1f}ms; "
                f"the legacy baseline flagged {len(base_flagged_txs)}."
            )

        return BenchmarkSuiteResult(
            scenario_tested=ledger.scenario_name,
            ledger_size={"accounts": len(ledger.accounts), "transactions": len(ledger.transactions)},
            ghost_trace_metrics=gt_metrics,
            baseline_metrics=base_metrics,
            summary_analysis=summary,
            dataset_source=dataset_source,
            dataset_label=dataset_label or ledger.scenario_name,
            seed=seed,
            labelled_positive_count=positives,
            labels_available=labels_available
        )


if __name__ == "__main__":
    runner = BenchmarkRunner(seed=42)
    print("=" * 80)
    print("GHOSTTRACE SYNTHETIC BENCHMARK SUITE (HONEST METRICS + FPR)")
    print("Track: The Vampire's Ledger | Aapthamitra Audits")
    print("=" * 80)

    for scen in ["vampire_ring", "smurfing", "legit_rebate", "mixed_ledger"]:
        res = runner.run_benchmark(scen)
        print(f"\nScenario: {res.scenario_tested}")
        print(res.to_dataframe().to_string(index=False))
        print(f"Analysis: {res.summary_analysis}\n" + "-" * 80)
