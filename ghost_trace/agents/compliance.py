"""
Compliance Officer Agent: Chief AML Legal & Regulatory Filings Officer
Evaluates statutory violations (BSA / FinCEN), cites verified evidence IDs,
documents technical limitations, and structures actionable human-review recommendations.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import json

from ghost_trace.agents.base import BaseAgent, AgentReport, EvidenceCitation
from ghost_trace.graph_engine import GraphInvestigationResult
from ghost_trace.data_generator import LedgerData
from ghost_trace.config import (
    REGULATORY_CITATIONS,
    COMPLIANCE_DISCLAIMER,
    BSA_REPORTING_LIMIT,
    STRUCTURING_THRESHOLD_MIN,
    STRUCTURING_THRESHOLD_MAX
)


class ComplianceOfficerAgent(BaseAgent):
    """
    Compliance Officer Agent generates a structured draft SAR assessment.
    Synthesizes factual findings from Detective and Profiler, cites evidence IDs,
    details regulatory statutes, documents limitations, and mandates human sign-off.
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key=api_key)

    def investigate(
        self,
        detective: AgentReport,
        profiler: AgentReport,
        graph_result: GraphInvestigationResult,
        ledger: LedgerData
    ) -> AgentReport:
        flagged_cycles = graph_result.flagged_cycles
        smurfing = graph_result.smurfing_clusters
        flagged_accounts = graph_result.flagged_accounts
        flagged_txs = graph_result.flagged_tx_ids

        citations: List[Dict[str, Any]] = []
        findings: List[str] = []
        limitations: List[str] = []
        human_recs: List[str] = []

        citation_counter = 1

        if not flagged_cycles and not smurfing:
            status = "NO_ACTION_REQUIRED"
            summary = (
                "Statutory AML review completed. No reasonable cause to suspect money laundering, "
                "structuring, or terrorist financing under 31 U.S.C. § 5318(g) or 31 CFR § 1020.320. "
                "No Suspicious Activity Report (SAR) filing or protective account restraint recommended."
            )
            findings.append("No violation of 31 U.S.C. § 5324 (Anti-Structuring): All transfers conform to standard amounts.")
            findings.append("No violation of 18 U.S.C. § 1956: Transaction paths exhibit valid commercial purpose and high flow decay.")
            limitations.append("Determination based strictly on current ledger batch; subsequent structuring bursts will trigger automated re-evaluation.")
            human_recs.append("Close compliance ticket without regulatory filing. Retain audit record in AML compliance archive.")
            inference_label = "deterministic_local_engine"
            err_details = None
        else:
            status = "SAR_FILING_RECOMMENDED"
            max_score = max([c.suspicion_score for c in flagged_cycles] + [s.suspicion_score for s in smurfing] + [0.0])
            total_flagged_vol = sum(c.initial_amount for c in flagged_cycles) + sum(s.total_fan_out_amount for s in smurfing)

            summary = (
                f"Statutory filing criteria satisfied under 31 U.S.C. § 5318(g) and 31 CFR § 1020.320. "
                f"The financial pattern demonstrates systematic structuring (31 U.S.C. § 5324) and multi-hop "
                f"circular money laundering layering (18 U.S.C. § 1956) aggregating ${total_flagged_vol:,.2f} "
                f"across {len(flagged_accounts)} accounts. Maximum network suspicion score: {max_score:.2f}/1.00."
            )

            # 1. Statutory Violations Citing Verified Evidence IDs
            cycle_ids = [c.cycle_id for c in flagged_cycles]
            findings.append(
                f"**Primary Violation: 31 U.S.C. § 5324 (Anti-Structuring)**: Transactions systematically clustered "
                f"between ${STRUCTURING_THRESHOLD_MIN:,.0f} and ${STRUCTURING_THRESHOLD_MAX:,.0f} to intentionally evade "
                f"Currency Transaction Report (CTR) filing. Supported by Evidence Cycles: {', '.join(cycle_ids) if cycle_ids else 'Smurfing Clusters'}."
            )
            findings.append(
                f"**Secondary Violation: 18 U.S.C. § 1956 (Laundering of Monetary Instruments - Layering)**: "
                f"Conducted multi-hop rapid circular transfers with minimal decay to conceal beneficial origin and destination of funds. "
                f"Supported by {len(flagged_txs)} flagged transaction records."
            )
            findings.append(
                f"**Mandatory Filing Timeline**: In accordance with 31 CFR § 1020.320, FinCEN SAR Form 111 must be filed "
                f"no later than 30 calendar days from initial detection ({datetime.now().strftime('%Y-%m-%d')})."
            )

            # Add structured citations for statutes
            for reg in REGULATORY_CITATIONS:
                citations.append(EvidenceCitation(
                    citation_id=f"CIT-CMP-{citation_counter:03d}",
                    citation_type="statute",
                    target_id=reg["title"],
                    observed_value=reg["law"],
                    context_note=reg["description"]
                ).to_dict())
                citation_counter += 1

            # 2. Honest Technical & Legal Limitations
            limitations.append(
                "GhostTrace operates as an automated decision-support system; graph algorithms cannot verify subjective intent or external contractual agreements."
            )
            limitations.append(
                "Cross-institutional counterparty accounts cannot be queried without FinCEN 314(b) voluntary information-sharing requests."
            )
            limitations.append(
                "Synthetic ledger data: While metrics reflect realistic AML topologies, physical law enforcement subpoenas are necessary to corroborate physical identity."
            )

            # 3. Actionable Human-Review Recommendations
            human_recs.append("Conduct certified AML Officer independent review of Detective and Profiler evidence logs.")
            human_recs.append("Pull KYC documentation, corporate registry records, and signature cards for all flagged accounts.")
            human_recs.append("Place administrative protective debit restriction (temporary hold) on suspect accounts pending officer verification.")
            human_recs.append("Transmit electronic Form 111 (FinCEN SAR) via the BSA E-Filing System upon compliance officer sign-off.")
            human_recs.append("STRICT POLICY: Do NOT automatically file or freeze accounts without human review.")

            inference_label = "deterministic_local_engine"
            err_details = None

            # Optional LLM Enhancement if configured
            if self.api_key:
                system_prompt = (
                    "You are the Compliance Officer Agent in GhostTrace. Synthesize the regulatory narrative for a SAR draft. "
                    "Cite the provided evidence IDs and statutes accurately. Do not invent facts or make definitive accusations. "
                    "Frame findings as 'reasonable cause to suspect' and emphasize mandatory human officer review."
                )
                user_prompt = f"Executive summary context:\n{summary}\nFindings:\n{findings}"
                llm_summary, mode_label, err = self._call_optional_llm(user_prompt, system_prompt)
                if llm_summary:
                    summary = llm_summary.strip()
                    inference_label = mode_label
                elif err:
                    inference_label = mode_label
                    err_details = err

        md_lines = [
            f"### ⚖️ AML Compliance Officer Regulatory Assessment",
            f"- **Role**: Chief AML Legal & Regulatory Filings Officer",
            f"- **Inference Backend**: `{inference_label}`",
            f"- **Statutory Filing Recommendation**: `{status}`",
            f"\n**Regulatory Brief**:\n{summary}\n",
            "**Factual Findings & Statutory Violations**:"
        ]
        for f in findings:
            md_lines.append(f"- {f}")

        md_lines.append("\n**Governing Federal Statutes**:")
        for reg in REGULATORY_CITATIONS:
            md_lines.append(f"- **{reg['title']}** (*{reg['law']}*): {reg['description']}")

        md_lines.append("\n**Compliance Limitations**:")
        for lim in limitations:
            md_lines.append(f"- ⚠️ {lim}")

        md_lines.append("\n**Mandatory Human Compliance Actions**:")
        for rec in human_recs:
            md_lines.append(f"- 📋 {rec}")

        md_lines.append(f"\n> **Compliance Mandate**: {COMPLIANCE_DISCLAIMER}")

        return AgentReport(
            agent_role="Compliance Officer",
            agent_title="Chief AML Legal & SAR Officer",
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
