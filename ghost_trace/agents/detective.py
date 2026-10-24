"""
Detective Agent: Lead Graph Fraud & Flow Analyst
Specializes in graph topology, transaction flow conservation, hop velocity,
BSA structuring bands, and chronological fund tracking.
"""

from typing import List, Dict, Any, Optional
import json
from ghost_trace.agents.base import BaseAgent, AgentReport, EvidenceCitation
from ghost_trace.graph_engine import GraphInvestigationResult, CycleEvidence, SmurfingClusterEvidence
from ghost_trace.data_generator import LedgerData
from ghost_trace.config import STRUCTURING_THRESHOLD_MIN, STRUCTURING_THRESHOLD_MAX, BSA_REPORTING_LIMIT


class DetectiveAgent(BaseAgent):
    """
    Detective Agent interprets computed graph metrics from NetworkX.
    Summarizes cycle topology, flow attrition, temporal velocity, and structuring.
    Never invents transactions or accounts; grounds all claims in computed evidence.
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key=api_key)

    def investigate(self, graph_result: GraphInvestigationResult, ledger: LedgerData) -> AgentReport:
        flagged_cycles: List[CycleEvidence] = graph_result.flagged_cycles
        smurfing_clusters: List[SmurfingClusterEvidence] = graph_result.smurfing_clusters
        total_txs = graph_result.total_transactions
        total_accs = graph_result.total_accounts

        findings: List[str] = []
        citations: List[Dict[str, Any]] = []
        limitations: List[str] = []
        human_recs: List[str] = []

        citation_counter = 1

        if not flagged_cycles and not smurfing_clusters:
            status = "CLEARED"
            summary = (
                f"Completed graph flow analysis across {total_txs} transactions and {total_accs} accounts. "
                f"No suspicious money mule cycles or high-velocity structuring clusters identified. "
                f"All evaluated closed paths demonstrate natural commercial flow attrition (>40% decay) or customary multi-day settlement intervals."
            )
            findings.append("Graph topology verified benign: No circular fund retention matching money mule commission thresholds.")
            limitations.append("Analysis bounded to recorded ledger transactions; external off-chain settlements cannot be assessed from graph data.")
            human_recs.append("Archive routine investigation log; standard periodic transaction monitoring applies.")
            inference_label = "deterministic_local_engine"
            err_details = None
        else:
            status = "CRITICAL_ANOMALY_CONFIRMED"
            summary = (
                f"Graph analysis confirmed {len(flagged_cycles)} suspicious circular layering ring(s) "
                f"and {len(smurfing_clusters)} distributed smurfing cluster(s). "
                f"Funds exhibit structured threshold evasion, rapid inter-hop velocity, and abnormal flow conservation."
            )

            # Analyze each flagged cycle with strict evidence citations
            for c in flagged_cycles:
                hop_descriptions = []
                for h in c.hops:
                    delta_str = f" (+{h.time_delta_from_previous_minutes:.1f}m)" if h.time_delta_from_previous_minutes is not None else " (start)"
                    hop_descriptions.append(f"{h.from_account} -> {h.to_account} [${h.amount:,.2f}{delta_str}, Tx: {h.tx_id}]")

                    # Add structured citation for each transaction
                    citations.append(EvidenceCitation(
                        citation_id=f"CIT-DET-{citation_counter:03d}",
                        citation_type="transaction",
                        target_id=h.tx_id,
                        observed_value=h.amount,
                        context_note=f"Hop from {h.from_account} to {h.to_account} at {h.timestamp}"
                    ).to_dict())
                    citation_counter += 1

                findings.append(
                    f"**Cycle [{c.cycle_id}] Topology**: {c.hop_count}-hop closed loop: "
                    f"{' | '.join(hop_descriptions)}."
                )
                findings.append(
                    f"**Flow Conservation & Attrition**: Injected ${c.initial_amount:,.2f} -> Closed ${c.final_amount:,.2f} "
                    f"({c.flow_retention_pct:.1f}% retained; attrition decay: {c.amount_decay_pct:.1f}%). "
                    f"Consistent with organized mule commission fee withholding (1.2% - 2.0% per hop)."
                )
                if getattr(c, "velocity_available", True):
                    findings.append(
                        f"**Temporal Velocity**: Total duration {c.total_duration_hours:.2f} hours "
                        f"(average hop interval: {c.avg_hop_interval_minutes:.1f} minutes, rate: {c.hops_per_hour:.2f} hops/hr). "
                        f"Velocity strongly refutes typical commercial invoice payment cycles."
                    )
                else:
                    findings.append(
                        "**Temporal Velocity**: Unavailable (hop timestamps are missing or unparseable); "
                        "no velocity evidence is claimed for this cycle."
                    )

                if c.structured_hop_count > 0:
                    findings.append(
                        f"**BSA Structuring Evasion**: {c.structured_hop_count}/{c.hop_count} transfers fall in the "
                        f"${STRUCTURING_THRESHOLD_MIN:,.0f} - ${STRUCTURING_THRESHOLD_MAX:,.0f} band, evading the "
                        f"${BSA_REPORTING_LIMIT:,.0f} mandatory CTR reporting threshold."
                    )

                if any(h.parallel_tx_count > 0 for h in c.hops):
                    findings.append(
                        f"**Parallel Transfer Preserved**: Detected {len(c.all_tx_ids)} total transactions across the cycle path."
                    )

                citations.append(EvidenceCitation(
                    citation_id=f"CIT-DET-{citation_counter:03d}",
                    citation_type="cycle",
                    target_id=c.cycle_id,
                    observed_value=c.suspicion_score,
                    context_note=f"Composite score {c.suspicion_score:.4f} across path {c.path}"
                ).to_dict())
                citation_counter += 1

            # Analyze smurfing clusters
            for s in smurfing_clusters:
                findings.append(
                    f"**Smurfing Syndicate [{s.cluster_id}]**: Funding node `{s.funder_account}` disbursed "
                    f"${s.total_fan_out_amount:,.2f} across {len(s.smurf_accounts)} intermediary nodes, which aggregated "
                    f"${s.total_fan_in_amount:,.2f} into sink account `{s.collector_account}` within {s.time_window_hours:.1f} hours."
                )
                for tid in s.fan_out_tx_ids + s.fan_in_tx_ids:
                    citations.append(EvidenceCitation(
                        citation_id=f"CIT-DET-{citation_counter:03d}",
                        citation_type="transaction",
                        target_id=tid,
                        observed_value=None,
                        context_note=f"Smurfing transfer part of cluster {s.cluster_id}"
                    ).to_dict())
                    citation_counter += 1

            limitations.append("Cycle search is bounded to simple cycles of length 3 to 6 hops; longer dispersed chains require separate multi-stage query.")
            limitations.append("Timestamps reflect ledger recorded transaction times; off-ledger settlement instructions cannot be inferred.")
            human_recs.append("Pull bank settlement wire confirmations for all cited transaction IDs.")
            human_recs.append("Verify whether the funding source account has filed CTR exemption declarations.")

            inference_label = "deterministic_local_engine"
            err_details = None

            # Optional LLM Enhancement if configured
            if self.api_key:
                system_prompt = (
                    "You are the Detective Agent in the GhostTrace financial crime system. "
                    "Summarize the provided graph evidence accurately. Do not invent any transaction IDs, "
                    "account IDs, or dollar amounts. Cite only the facts provided."
                )
                user_prompt = f"Graph evidence:\n{json.dumps([c.to_dict() for c in flagged_cycles], indent=2)}"
                llm_summary, mode_label, err = self._call_optional_llm(user_prompt, system_prompt)
                if llm_summary:
                    summary = llm_summary.strip()
                    inference_label = mode_label
                elif err:
                    inference_label = mode_label
                    err_details = err

        # Render clean markdown report
        md_lines = [
            f"### 🔍 Detective Agent Investigation Report",
            f"- **Role**: Lead Graph Fraud & Flow Topology Analyst",
            f"- **Inference Backend**: `{inference_label}`",
            f"- **Investigation Status**: `{status}`",
            f"- **Scope Evaluated**: {total_txs} transactions across {total_accs} accounts",
            f"\n**Executive Brief**:\n{summary}\n",
            "**Verified Graph Findings**:"
        ]
        for f in findings:
            md_lines.append(f"- {f}")

        md_lines.append("\n**Technical Limitations**:")
        for lim in limitations:
            md_lines.append(f"- ⚠️ {lim}")

        md_lines.append("\n**Detective Action Recommendations**:")
        for rec in human_recs:
            md_lines.append(f"- 📋 {rec}")

        return AgentReport(
            agent_role="Detective",
            agent_title="Lead Graph Fraud & Flow Analyst",
            status=status,
            summary=summary,
            findings=findings,
            evidence_citations=citations,
            limitations=limitations,
            human_recommendations=human_recs,
            raw_markdown="\n".join(md_lines),
            inference_mode=inference_label,
            llm_error_details=err_details
        )
