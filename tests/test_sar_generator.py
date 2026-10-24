"""
Tests for FinCEN SAR Generator & Human Review Gate
"""

import pytest
from ghost_trace.data_generator import SyntheticLedgerGenerator
from ghost_trace.graph_engine import FinancialGraphEngine
from ghost_trace.agents import GhostTraceInvestigationOrchestrator
from ghost_trace.sar_generator import SARGenerator


def test_sar_generation_completeness():
    gen = SyntheticLedgerGenerator(seed=42)
    ledger = gen.generate_scenario("vampire_ring")

    engine = FinancialGraphEngine()
    result = engine.run_investigation(ledger)

    orchestrator = GhostTraceInvestigationOrchestrator()
    inv_report = orchestrator.run_investigation(result, ledger)

    sar_gen = SARGenerator()
    sar_doc = sar_gen.generate_sar(inv_report, result, ledger)

    # Validate FinCEN SAR Structure
    assert sar_doc.sar_tracking_id.startswith("SAR-2026-GT-")
    assert sar_doc.human_review_required is True
    assert sar_doc.review_status == "PENDING_HUMAN_SIGN_OFF"
    assert len(sar_doc.suspect_subjects) == 4
    assert len(sar_doc.chronological_audit_trail) == 4
    assert sar_doc.total_suspicious_amount > 30000.0
    assert len(sar_doc.regulatory_statutes) >= 3
    assert len(sar_doc.limitations) >= 2
    assert len(sar_doc.human_recommendations) >= 3

    # Validate Markdown Output
    md = sar_doc.to_markdown()
    assert "SUSPICIOUS ACTIVITY REPORT" in md
    assert "PART I: REPORTING FINANCIAL INSTITUTION INFORMATION" in md
    assert "PART II: SUSPECT ENTITY & SUBJECT IDENTIFICATION" in md
    assert "PART III: SUMMARY OF SUSPICIOUS ACTIVITY" in md
    assert "PART IV: CHRONOLOGICAL TRANSACTION AUDIT TRAIL" in md
    assert "PART V: COMPLIANCE OFFICER NARRATIVE" in md
    assert "PART VI: FACTUAL VERIFICATION & EVIDENCE INTEGRITY" in md
    assert "PART VII: TECHNICAL & LEGAL LIMITATIONS" in md
    assert "PART VIII: HUMAN COMPLIANCE REVIEW & AUTHORIZATION GATE" in md
    assert "HUMAN SIGN-OFF MANDATE" in md
    assert "31 U.S.C. 5318(g)" in md
