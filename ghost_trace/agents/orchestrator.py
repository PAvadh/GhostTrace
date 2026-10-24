"""
Investigation Orchestrator
Coordinates the tri-agent investigative pipeline:
Detective -> Entity Profiler -> Compliance Officer -> Citation Verifier.
"""

from datetime import datetime
from typing import Optional, List

from ghost_trace.agents.base import TriAgentInvestigationReport
from ghost_trace.agents.detective import DetectiveAgent
from ghost_trace.agents.profiler import EntityProfilerAgent
from ghost_trace.agents.compliance import ComplianceOfficerAgent
from ghost_trace.agents.verifier import CitationVerifier
from ghost_trace.graph_engine import GraphInvestigationResult
from ghost_trace.data_generator import LedgerData
from ghost_trace.config import COMPLIANCE_DISCLAIMER


class GhostTraceInvestigationOrchestrator:
    """
    Coordinates multi-agent deliberation, factual cross-verification,
    and structured dossier assembly for AML compliance review.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.detective = DetectiveAgent(api_key=api_key)
        self.profiler = EntityProfilerAgent(api_key=api_key)
        self.compliance = ComplianceOfficerAgent(api_key=api_key)
        self.verifier = CitationVerifier()

    def run_investigation(
        self,
        graph_result: GraphInvestigationResult,
        ledger: LedgerData
    ) -> TriAgentInvestigationReport:
        t_start = datetime.now()

        # Step 1: Detective Agent summarizes graph topology & flow evidence
        det_report = self.detective.investigate(graph_result, ledger)

        # Step 2: Entity Profiler interprets device, dormancy, and KYC indicators
        prof_report = self.profiler.investigate(graph_result, ledger)

        # Step 3: Compliance Officer drafts regulatory assessment & statutory violations
        comp_report = self.compliance.investigate(det_report, prof_report, graph_result, ledger)

        # Step 4: Strict Citation & Evidence Verification
        verification = self.verifier.verify_investigation_citations(
            det_report, prof_report, comp_report, graph_result, ledger
        )

        t_end = datetime.now()
        latency = (t_end - t_start).total_seconds()

        # Determine overall verdict & risk score
        flagged_cycles = graph_result.flagged_cycles
        smurfing = graph_result.smurfing_clusters
        max_score = 0.15
        if flagged_cycles:
            max_score = max(max_score, max(c.suspicion_score for c in flagged_cycles))
        if smurfing:
            max_score = max(max_score, max(s.suspicion_score for s in smurfing))

        if max_score >= 0.70:
            verdict = "CRITICAL: ORGANIZED MONEY LAUNDERING RING DETECTED"
        elif max_score >= 0.45:
            verdict = "HIGH: SUSPICIOUS STRUCTURING & VELOCITY SPIKE"
        elif max_score >= 0.30:
            verdict = "MEDIUM: ELEVATED TRANSACTION MONITORING"
        else:
            verdict = "LOW: ROUTINE COMMERCIAL & RETAIL FLOW"

        human_actions = [
            "Conduct Enhanced Due Diligence (EDD) interview with designated account owners.",
            "Inspect physical / digital registration documents for flagged shell corporate entities.",
            "Validate authenticity of shared device hardware identifiers across multiple accounts.",
            "Review generated draft FinCEN SAR narrative prior to regulatory submission.",
            "Determine whether to place temporary administrative protective hold on suspect accounts (Human Signature Required)."
        ]

        inv_id = f"GT-INV-{int(t_start.timestamp())}"

        return TriAgentInvestigationReport(
            scenario_name=getattr(ledger, "scenario_name", "Financial Scenario"),
            investigation_id=inv_id,
            overall_verdict=verdict,
            overall_risk_score=max_score,
            detective_report=det_report,
            profiler_report=prof_report,
            compliance_report=comp_report,
            flagged_entities=graph_result.flagged_accounts,
            flagged_transactions=graph_result.flagged_tx_ids,
            citation_verification=verification,
            human_action_checklist=human_actions,
            disclaimer=COMPLIANCE_DISCLAIMER,
            total_latency_seconds=latency
        )
