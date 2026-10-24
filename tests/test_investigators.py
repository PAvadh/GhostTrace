"""
Comprehensive Tests for Modular Tri-Agent Investigation System:
1. Detective Agent claims verified against computed graph facts
2. Entity Profiler claims verified against entity KYC and device evidence
3. Compliance Officer statutory citations, limitations, and human recommendations
4. Citation Verifier detects invented / hallucinated facts
5. Deterministic local operation without API key & safe fallback on invalid credentials
"""

import pytest
from ghost_trace.data_generator import SyntheticLedgerGenerator
from ghost_trace.graph_engine import FinancialGraphEngine
from ghost_trace.agents import (
    DetectiveAgent,
    EntityProfilerAgent,
    ComplianceOfficerAgent,
    CitationVerifier,
    GhostTraceInvestigationOrchestrator
)


# -----------------------------------------------------------------------------
# 1. Detective Agent Claims Verified Against Computed Graph Facts
# -----------------------------------------------------------------------------
def test_detective_claims_match_source_evidence():
    gen = SyntheticLedgerGenerator(seed=42)
    ledger = gen.generate_scenario("vampire_ring")

    engine = FinancialGraphEngine()
    graph_result = engine.run_investigation(ledger)

    detective = DetectiveAgent()
    det_report = detective.investigate(graph_result, ledger)

    assert det_report.status == "CRITICAL_ANOMALY_CONFIRMED"
    assert det_report.inference_mode == "deterministic_local_engine"
    assert len(det_report.evidence_citations) > 0
    assert len(det_report.limitations) > 0
    assert len(det_report.human_recommendations) > 0

    # Verify every cited transaction exists and amounts match
    tx_map = {tx.tx_id: tx for tx in ledger.transactions}
    for cit in det_report.evidence_citations:
        if cit["citation_type"] == "transaction":
            tx_id = cit["target_id"]
            assert tx_id in tx_map, f"Detective cited non-existent transaction: {tx_id}"
            cited_amt = cit["observed_value"]
            if cited_amt is not None:
                assert abs(cited_amt - tx_map[tx_id].amount) < 0.01, (
                    f"Detective cited amount ${cited_amt} does not match ledger ${tx_map[tx_id].amount}"
                )


# -----------------------------------------------------------------------------
# 2. Entity Profiler Claims Verified Against Entity Evidence
# -----------------------------------------------------------------------------
def test_profiler_claims_match_entity_evidence():
    gen = SyntheticLedgerGenerator(seed=42)
    ledger = gen.generate_scenario("vampire_ring")

    engine = FinancialGraphEngine()
    graph_result = engine.run_investigation(ledger)

    profiler = EntityProfilerAgent()
    prof_report = profiler.investigate(graph_result, ledger)

    assert prof_report.status == "HIGH_RISK_SYNDICATE_DETECTED"
    assert prof_report.inference_mode == "deterministic_local_engine"
    assert len(prof_report.evidence_citations) > 0

    # Verify every cited account exists in ledger
    acc_map = ledger.accounts
    for cit in prof_report.evidence_citations:
        if cit["citation_type"] == "account":
            acc_id = cit["target_id"]
            assert acc_id in acc_map, f"Profiler cited non-existent account: {acc_id}"
        elif cit["citation_type"] == "device":
            dev_id = cit["target_id"]
            # Check device is used by at least one account in ledger
            accs_using_dev = [aid for aid, a in acc_map.items() if a.device_id == dev_id]
            assert len(accs_using_dev) > 0, f"Profiler cited non-existent device: {dev_id}"


# -----------------------------------------------------------------------------
# 3. Compliance Officer Statutory Citations & Limitations
# -----------------------------------------------------------------------------
def test_compliance_officer_statutes_limitations_and_recs():
    gen = SyntheticLedgerGenerator(seed=42)
    ledger = gen.generate_scenario("vampire_ring")

    engine = FinancialGraphEngine()
    graph_result = engine.run_investigation(ledger)

    detective = DetectiveAgent()
    det_report = detective.investigate(graph_result, ledger)

    profiler = EntityProfilerAgent()
    prof_report = profiler.investigate(graph_result, ledger)

    compliance = ComplianceOfficerAgent()
    comp_report = compliance.investigate(det_report, prof_report, graph_result, ledger)

    assert comp_report.status == "SAR_FILING_RECOMMENDED"
    assert comp_report.inference_mode == "deterministic_local_engine"

    # Verify statutory citations
    statute_citations = [c for c in comp_report.evidence_citations if c["citation_type"] == "statute"]
    assert len(statute_citations) >= 3
    statute_titles = [c["target_id"] for c in statute_citations]
    assert "31 U.S.C. 5318(g)" in statute_titles
    assert "31 U.S.C. 5324" in statute_titles

    # Verify explicit limitations and recommendations
    assert len(comp_report.limitations) >= 2
    assert len(comp_report.human_recommendations) >= 3
    assert any("STRICT POLICY" in rec for rec in comp_report.human_recommendations)


# -----------------------------------------------------------------------------
# 4. Citation Verifier Detects Hallucinated / Invented Facts
# -----------------------------------------------------------------------------
def test_citation_verifier_flags_invented_facts():
    gen = SyntheticLedgerGenerator(seed=42)
    ledger = gen.generate_scenario("vampire_ring")

    engine = FinancialGraphEngine()
    graph_result = engine.run_investigation(ledger)

    detective = DetectiveAgent()
    det_report = detective.investigate(graph_result, ledger)

    profiler = EntityProfilerAgent()
    prof_report = profiler.investigate(graph_result, ledger)

    compliance = ComplianceOfficerAgent()
    comp_report = compliance.investigate(det_report, prof_report, graph_result, ledger)

    verifier = CitationVerifier()

    # Clean verification first
    clean_verification = verifier.verify_investigation_citations(
        det_report, prof_report, comp_report, graph_result, ledger
    )
    assert clean_verification.is_valid is True
    assert len(clean_verification.unverified_claims) == 0

    # Now inject an invented transaction ID into detective report
    corrupted_det_report = DetectiveAgent().investigate(graph_result, ledger)
    corrupted_det_report.evidence_citations.append({
        "citation_id": "CIT-FAKE-001",
        "citation_type": "transaction",
        "target_id": "TX-INVENTED-FAKE-9999",
        "observed_value": 999999.0,
        "context_note": "Hallucinated transaction"
    })

    # Injected check must fail!
    corrupted_verification = verifier.verify_investigation_citations(
        corrupted_det_report, prof_report, comp_report, graph_result, ledger
    )
    assert corrupted_verification.is_valid is False
    assert len(corrupted_verification.unverified_claims) == 1
    assert "TX-INVENTED-FAKE-9999" in corrupted_verification.unverified_claims[0]["target_id"]
    assert "Invented transaction ID" in corrupted_verification.unverified_claims[0]["reason"]


# -----------------------------------------------------------------------------
# 5. Deterministic Local Operation & Safe LLM Fallback
# -----------------------------------------------------------------------------
def test_deterministic_local_operation_and_safe_fallback():
    gen = SyntheticLedgerGenerator(seed=42)
    ledger = gen.generate_scenario("vampire_ring")

    engine = FinancialGraphEngine()
    graph_result = engine.run_investigation(ledger)

    # 1. No API key: strictly deterministic local engine
    orch_local = GhostTraceInvestigationOrchestrator(api_key=None)
    report_local = orch_local.run_investigation(graph_result, ledger)
    assert report_local.detective_report.inference_mode == "deterministic_local_engine"
    assert report_local.profiler_report.inference_mode == "deterministic_local_engine"
    assert report_local.compliance_report.inference_mode == "deterministic_local_engine"
    assert report_local.citation_verification.is_valid is True

    # 2. Invalid API key: must safely fallback without throwing an exception
    orch_invalid_key = GhostTraceInvestigationOrchestrator(api_key="AIzaSy_INVALID_DUMMY_KEY_FOR_TESTING")
    report_fallback = orch_invalid_key.run_investigation(graph_result, ledger)
    assert report_fallback.detective_report.inference_mode in ["llm_fallback_to_local", "deterministic_local_engine"]
    assert report_fallback.citation_verification.is_valid is True
    assert report_fallback.overall_verdict.startswith("CRITICAL")


# -----------------------------------------------------------------------------
# 6. Negative Control Cleared
# -----------------------------------------------------------------------------
def test_agent_negative_control_cleared():
    gen = SyntheticLedgerGenerator(seed=42)
    ledger = gen.generate_scenario("legit_rebate")

    engine = FinancialGraphEngine()
    result = engine.run_investigation(ledger)

    orchestrator = GhostTraceInvestigationOrchestrator()
    report = orchestrator.run_investigation(result, ledger)

    assert report.overall_risk_score < 0.45
    assert report.detective_report.status == "CLEARED"
    assert report.profiler_report.status == "VERIFIED_LOW_RISK"
    assert report.compliance_report.status == "NO_ACTION_REQUIRED"
    assert report.citation_verification.is_valid is True
