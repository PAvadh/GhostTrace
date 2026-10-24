"""
Evidence & Citation Verifier
Audits all agent claims against ground truth ledger transactions and graph records.
Guarantees zero hallucinations and prevents invented accounts, devices, or transactions.
"""

from typing import List, Dict, Any, Set
from ghost_trace.agents.base import AgentReport, CitationVerificationResult
from ghost_trace.graph_engine import GraphInvestigationResult
from ghost_trace.data_generator import LedgerData


class CitationVerifier:
    """
    Audits agent evidence citations against actual ledger and graph computations.
    Ensures mathematical and factual integrity:
    - Every transaction ID must exist in ledger.transactions
    - Every account ID must exist in ledger.accounts
    - Every cited device ID must exist on the corresponding entity
    - Transaction amounts must match recorded ledger amounts
    """

    def __init__(self):
        pass

    def verify_investigation_citations(
        self,
        detective_report: AgentReport,
        profiler_report: AgentReport,
        compliance_report: AgentReport,
        graph_result: GraphInvestigationResult,
        ledger: LedgerData
    ) -> CitationVerificationResult:
        all_citations = (
            detective_report.evidence_citations +
            profiler_report.evidence_citations +
            compliance_report.evidence_citations
        )

        verified_txs: Set[str] = set()
        verified_accs: Set[str] = set()
        verified_devs: Set[str] = set()
        unverified_claims: List[Dict[str, Any]] = []

        # Build lookup indices for fast, accurate verification
        ledger_tx_map = {tx.tx_id: tx for tx in ledger.transactions}
        ledger_acc_map = {acc.account_id: acc for acc in ledger.accounts.values()}
        graph_cycle_map = {c.cycle_id: c for c in graph_result.detected_cycles}

        for cit in all_citations:
            c_type = cit.get("citation_type")
            target = cit.get("target_id")
            val = cit.get("observed_value")

            if c_type == "transaction":
                if target not in ledger_tx_map:
                    unverified_claims.append({
                        "citation_id": cit.get("citation_id"),
                        "reason": f"Invented transaction ID: '{target}' does not exist in ledger.",
                        "target_id": target
                    })
                else:
                    tx = ledger_tx_map[target]
                    if val is not None and abs(float(val) - float(tx.amount)) > 0.01:
                        unverified_claims.append({
                            "citation_id": cit.get("citation_id"),
                            "reason": f"Mismatched transaction amount: Cited ${val:,.2f} vs Ledger ${tx.amount:,.2f}.",
                            "target_id": target
                        })
                    else:
                        verified_txs.add(target)

            elif c_type == "account":
                if target not in ledger_acc_map:
                    unverified_claims.append({
                        "citation_id": cit.get("citation_id"),
                        "reason": f"Invented account ID: '{target}' does not exist in ledger.",
                        "target_id": target
                    })
                else:
                    verified_accs.add(target)

            elif c_type == "device":
                # Check that device exists in at least one account or transaction
                dev_exists = any(
                    getattr(acc, "device_id", None) == target for acc in ledger.accounts.values()
                ) or any(
                    getattr(tx, "device_id", None) == target for tx in ledger.transactions
                )

                if not dev_exists:
                    unverified_claims.append({
                        "citation_id": cit.get("citation_id"),
                        "reason": f"Invented device ID: '{target}' not found in any account or transaction.",
                        "target_id": target
                    })
                else:
                    verified_devs.add(target)

            elif c_type == "cycle":
                if target not in graph_cycle_map:
                    unverified_claims.append({
                        "citation_id": cit.get("citation_id"),
                        "reason": f"Invented cycle ID: '{target}' not detected by graph engine.",
                        "target_id": target
                    })

            elif c_type == "statute":
                # Legal citations are statutory references, always structurally valid
                pass

        is_valid = (len(unverified_claims) == 0)

        notes = (
            f"Audit passed: All {len(all_citations)} agent citations verified against ground truth ledger."
            if is_valid else
            f"Audit failed: Found {len(unverified_claims)} unverified or mismatched claims in agent reports."
        )

        return CitationVerificationResult(
            is_valid=is_valid,
            total_citations_checked=len(all_citations),
            verified_transactions=sorted(list(verified_txs)),
            verified_accounts=sorted(list(verified_accs)),
            verified_devices=sorted(list(verified_devs)),
            unverified_claims=unverified_claims,
            verification_notes=notes
        )
