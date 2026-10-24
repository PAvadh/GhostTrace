"""
Tests for Synthetic Transaction & Scenario Generator
"""

import pytest
from ghost_trace.data_generator import SyntheticLedgerGenerator, LedgerData


def test_vampire_ring_generation():
    gen = SyntheticLedgerGenerator(seed=42)
    ledger = gen.generate_scenario("vampire_ring")

    assert ledger.scenario_name == "Vampire Mule Ring (Circular Layering)"
    assert len(ledger.accounts) > 15
    assert len(ledger.transactions) > 20
    assert len(ledger.ground_truth_rings) >= 1

    # Check for vampire ring transactions
    vamp_txs = [tx for tx in ledger.transactions if tx.pattern_type == "vampire_ring"]
    assert len(vamp_txs) == 4

    # Check structuring band (< $10,000)
    for tx in vamp_txs:
        assert 8500.0 <= tx.amount <= 10000.0
        assert tx.is_ground_truth_fraud is True


def test_smurfing_generation():
    gen = SyntheticLedgerGenerator(seed=42)
    ledger = gen.generate_scenario("smurfing")

    assert len(ledger.ground_truth_rings) >= 1
    smurf_ring = ledger.ground_truth_rings[0]
    assert smurf_ring["type"] == "smurfing_fan_out_in"

    smurf_txs = [tx for tx in ledger.transactions if "smurfing" in tx.pattern_type]
    assert len(smurf_txs) == 8  # 4 fan-out, 4 fan-in


def test_legit_rebate_generation():
    gen = SyntheticLedgerGenerator(seed=42)
    ledger = gen.generate_scenario("legit_rebate")

    rebate_txs = [tx for tx in ledger.transactions if tx.pattern_type == "legit_rebate"]
    assert len(rebate_txs) == 3
    # Check that they are not marked as fraud
    for tx in rebate_txs:
        assert tx.is_ground_truth_fraud is False


def test_mixed_ledger_generation():
    gen = SyntheticLedgerGenerator(seed=99)
    ledger = gen.generate_scenario("mixed_ledger")

    assert len(ledger.accounts) >= 30
    assert len(ledger.transactions) >= 50
    assert len(ledger.ground_truth_rings) >= 2
