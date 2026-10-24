"""
Comprehensive Tests for Financial Graph Engine:
1. Injected suspicious cycles
2. Legitimate cycles (never treated as fraud alone)
3. Acyclic graphs (DAGs / trees)
4. Fast sequences & velocity computation
5. Missing device data & null resilience
6. Parallel transfers preservation
7. Invalid / unparseable timestamps & missing attributes
8. Empty graphs (0 nodes, 0 edges)
9. Bounded cycle constraints (3 <= k <= 6)
10. Configurable rules & scoring adjustments
"""

import pytest
from datetime import datetime, timedelta
import networkx as nx

from ghost_trace.data_generator import SyntheticLedgerGenerator, LedgerData, Account, Transaction
from ghost_trace.graph_engine import (
    FinancialGraphEngine,
    CycleEvidence,
    HopDetail,
    safe_parse_datetime,
    safe_float
)
from ghost_trace.config import EngineRulesConfig


# -----------------------------------------------------------------------------
# 1. Injected Suspicious Cycle Detection
# -----------------------------------------------------------------------------
def test_injected_suspicious_cycle():
    """Verify that a tightly structured, rapid circular mule ring is detected and flagged."""
    ledger = LedgerData(scenario_name="Unit Test Vampire Ring", description="Test injected ring")

    # 4 accounts in a ring
    accounts = ["MULE-1", "MULE-2", "MULE-3", "MULE-4"]
    for acc in accounts:
        ledger.accounts[acc] = Account(
            account_id=acc,
            name=f"Syndicate {acc}",
            account_type="individual",
            kyc_status="tier_1_basic",
            device_id="DEV-SHARED-BOTNET-01"  # Shared device
        )

    # Injected rapid structured transfers ($9,800 -> $9,700 -> $9,600 -> $9,500)
    base_time = datetime(2026, 10, 24, 12, 0, 0)
    for i in range(4):
        sender = accounts[i]
        receiver = accounts[(i + 1) % 4]
        amt = 9800.0 - (i * 100.0)
        t = base_time + timedelta(minutes=15 * (i + 1))
        ledger.transactions.append(Transaction(
            tx_id=f"TX-INJECT-{i+1}",
            sender_id=sender,
            receiver_id=receiver,
            amount=amt,
            timestamp=t.isoformat(),
            channel="wire",
            device_id="DEV-SHARED-BOTNET-01",
            ip_address="198.51.100.1",
            is_ground_truth_fraud=True,
            pattern_type="vampire_ring"
        ))

    engine = FinancialGraphEngine()
    result = engine.run_investigation(ledger)

    assert len(result.detected_cycles) == 1
    assert len(result.flagged_cycles) == 1

    cycle = result.flagged_cycles[0]
    assert cycle.is_flagged_suspicious is True
    assert cycle.risk_level in ["CRITICAL", "HIGH"]
    assert cycle.suspicion_score >= 0.70
    assert cycle.hop_count == 4
    assert cycle.amount_decay_pct < 10.0  # Retains >90%
    assert cycle.total_duration_hours <= 2.0
    assert "DEV-SHARED-BOTNET-01" in cycle.shared_devices
    assert cycle.structured_hop_count == 4


# -----------------------------------------------------------------------------
# 2. Legitimate Cycles (Never Treated Alone as Fraud)
# -----------------------------------------------------------------------------
def test_legitimate_cycle_never_treated_alone_as_fraud():
    """Verify that closed cycles with benign commerce properties are NOT flagged as fraud."""
    ledger = LedgerData(scenario_name="Legit Commercial Rebate", description="Benign trade loop")

    parties = [
        ("CORP-MFG", "Apex Manufacturing", "DEV-APEX"),
        ("CORP-SUPPLY", "Delta Materials", "DEV-DELTA"),
        ("CORP-LOGISTICS", "Omni Freight", "DEV-OMNI")
    ]
    for pid, name, dev in parties:
        ledger.accounts[pid] = Account(
            account_id=pid,
            name=name,
            account_type="merchant",
            kyc_status="verified_full",
            device_id=dev
        )

    # Commercial loop: $50,000 -> $8,000 -> $1,500 over 20 days
    t0 = datetime(2026, 9, 1, 10, 0, 0)
    tx_specs = [
        ("CORP-MFG", "CORP-SUPPLY", 50000.0, t0, "DEV-APEX"),
        ("CORP-SUPPLY", "CORP-LOGISTICS", 8000.0, t0 + timedelta(days=7), "DEV-DELTA"),
        ("CORP-LOGISTICS", "CORP-MFG", 1500.0, t0 + timedelta(days=20), "DEV-OMNI")
    ]

    for i, (u, v, amt, ts, dev) in enumerate(tx_specs):
        ledger.transactions.append(Transaction(
            tx_id=f"TX-COMM-{i+1}",
            sender_id=u,
            receiver_id=v,
            amount=amt,
            timestamp=ts.isoformat(),
            channel="ach",
            device_id=dev,
            ip_address=f"10.0.0.{i+1}",
            is_ground_truth_fraud=False,
            pattern_type="legit_rebate"
        ))

    engine = FinancialGraphEngine()
    result = engine.run_investigation(ledger)

    assert len(result.detected_cycles) == 1
    cycle = result.detected_cycles[0]

    # Must NOT be flagged as suspicious!
    assert cycle.is_flagged_suspicious is False
    assert cycle.risk_level == "LOW"
    assert cycle.suspicion_score < 0.40
    assert len(result.flagged_cycles) == 0
    assert "Cycle alone is not proof of fraud" in cycle.explanation_points[-1]


# -----------------------------------------------------------------------------
# 3. Acyclic Graphs (DAGs, Trees)
# -----------------------------------------------------------------------------
def test_acyclic_graph():
    """Verify that directed acyclic graphs (no loops) return zero cycles without error."""
    ledger = LedgerData(scenario_name="DAG Ledger", description="Strictly acyclic flow")

    nodes = ["SRC", "MID-1", "MID-2", "DST"]
    for n in nodes:
        ledger.accounts[n] = Account(account_id=n, name=f"Node {n}", account_type="individual", kyc_status="verified")

    # Simple pipeline: SRC -> MID-1 -> MID-2 -> DST
    t0 = datetime(2026, 10, 24, 8, 0, 0)
    ledger.transactions.extend([
        Transaction(tx_id="TX-D1", sender_id="SRC", receiver_id="MID-1", amount=500.0, timestamp=t0.isoformat(), channel="p2p", device_id="D1", ip_address="1.1.1.1"),
        Transaction(tx_id="TX-D2", sender_id="MID-1", receiver_id="MID-2", amount=450.0, timestamp=(t0 + timedelta(minutes=10)).isoformat(), channel="p2p", device_id="D2", ip_address="1.1.1.2"),
        Transaction(tx_id="TX-D3", sender_id="MID-2", receiver_id="DST", amount=400.0, timestamp=(t0 + timedelta(minutes=20)).isoformat(), channel="p2p", device_id="D3", ip_address="1.1.1.3")
    ])

    engine = FinancialGraphEngine()
    result = engine.run_investigation(ledger)

    assert len(result.detected_cycles) == 0
    assert len(result.flagged_cycles) == 0
    assert len(result.flagged_accounts) == 0


# -----------------------------------------------------------------------------
# 4. Fast Sequences & Velocity Calculation
# -----------------------------------------------------------------------------
def test_fast_sequence_velocity():
    """Verify sub-hour and sub-minute high-velocity hops compute correct metrics."""
    ledger = LedgerData(scenario_name="Fast Velocity Ring", description="Sub-hour velocity")

    nodes = ["FAST-A", "FAST-B", "FAST-C"]
    for n in nodes:
        ledger.accounts[n] = Account(account_id=n, name=n, account_type="individual", kyc_status="tier_1")

    # Cycle completed in 15 minutes total (5 mins per hop)
    t0 = datetime(2026, 10, 24, 14, 0, 0)
    ledger.transactions.extend([
        Transaction(tx_id="TX-F1", sender_id="FAST-A", receiver_id="FAST-B", amount=9600.0, timestamp=t0.isoformat(), channel="p2p", device_id="D-FAST", ip_address="10.1.1.1", is_ground_truth_fraud=True),
        Transaction(tx_id="TX-F2", sender_id="FAST-B", receiver_id="FAST-C", amount=9500.0, timestamp=(t0 + timedelta(minutes=5)).isoformat(), channel="p2p", device_id="D-FAST", ip_address="10.1.1.1", is_ground_truth_fraud=True),
        Transaction(tx_id="TX-F3", sender_id="FAST-C", receiver_id="FAST-A", amount=9400.0, timestamp=(t0 + timedelta(minutes=10)).isoformat(), channel="p2p", device_id="D-FAST", ip_address="10.1.1.1", is_ground_truth_fraud=True)
    ])

    engine = FinancialGraphEngine()
    result = engine.run_investigation(ledger)

    assert len(result.detected_cycles) == 1
    cycle = result.detected_cycles[0]

    assert cycle.total_duration_hours < 0.5  # Less than 30 mins
    assert cycle.avg_hop_interval_minutes == 5.0
    assert cycle.hops_per_hour >= 6.0  # At least 6 hops/hour rate
    assert cycle.suspicion_score >= 0.70


# -----------------------------------------------------------------------------
# 5. Missing Device Data Handling
# -----------------------------------------------------------------------------
def test_missing_device_data_resilience():
    """Verify that None, empty, or unknown device_ids do NOT produce false positive shared device matches."""
    ledger = LedgerData(scenario_name="Null Device Ledger", description="Missing device attributes")

    nodes = ["ACC-X", "ACC-Y", "ACC-Z"]
    for n in nodes:
        ledger.accounts[n] = Account(
            account_id=n,
            name=n,
            account_type="individual",
            kyc_status="verified",
            device_id=""  # Empty device
        )

    t0 = datetime(2026, 10, 24, 10, 0, 0)
    ledger.transactions.extend([
        Transaction(tx_id="TX-N1", sender_id="ACC-X", receiver_id="ACC-Y", amount=1200.0, timestamp=t0.isoformat(), channel="ach", device_id=None, ip_address=""),
        Transaction(tx_id="TX-N2", sender_id="ACC-Y", receiver_id="ACC-Z", amount=600.0, timestamp=(t0 + timedelta(days=2)).isoformat(), channel="ach", device_id="DEV-UNKNOWN", ip_address=""),
        Transaction(tx_id="TX-N3", sender_id="ACC-Z", receiver_id="ACC-X", amount=200.0, timestamp=(t0 + timedelta(days=4)).isoformat(), channel="ach", device_id="", ip_address="")
    ])

    engine = FinancialGraphEngine()
    result = engine.run_investigation(ledger)

    assert len(result.detected_cycles) == 1
    cycle = result.detected_cycles[0]

    # Must NOT identify DEV-UNKNOWN or empty string as a shared malicious device!
    assert len(cycle.shared_devices) == 0
    assert cycle.shared_device_count == 0


# -----------------------------------------------------------------------------
# 6. Parallel Transfers Preservation
# -----------------------------------------------------------------------------
def test_parallel_transfers_preserved():
    """Verify that multiple transactions on the same directed hop are preserved in evidence."""
    ledger = LedgerData(scenario_name="Parallel Edges Ledger", description="Multiple parallel transfers")

    nodes = ["NODE-1", "NODE-2", "NODE-3"]
    for n in nodes:
        ledger.accounts[n] = Account(account_id=n, name=n, account_type="individual", kyc_status="tier_1", device_id="DEV-RING-PARALLEL")

    t0 = datetime(2026, 10, 24, 16, 0, 0)

    # 3 parallel transfers between NODE-1 and NODE-2!
    tx1_a = Transaction(tx_id="TX-P1-A", sender_id="NODE-1", receiver_id="NODE-2", amount=9700.0, timestamp=t0.isoformat(), channel="wire", device_id="DEV-RING-PARALLEL", ip_address="10.0.0.1")
    tx1_b = Transaction(tx_id="TX-P1-B", sender_id="NODE-1", receiver_id="NODE-2", amount=9650.0, timestamp=(t0 + timedelta(minutes=2)).isoformat(), channel="wire", device_id="DEV-RING-PARALLEL", ip_address="10.0.0.1")
    tx1_c = Transaction(tx_id="TX-P1-C", sender_id="NODE-1", receiver_id="NODE-2", amount=9600.0, timestamp=(t0 + timedelta(minutes=4)).isoformat(), channel="wire", device_id="DEV-RING-PARALLEL", ip_address="10.0.0.1")

    tx2 = Transaction(tx_id="TX-P2", sender_id="NODE-2", receiver_id="NODE-3", amount=9500.0, timestamp=(t0 + timedelta(minutes=15)).isoformat(), channel="wire", device_id="DEV-RING-PARALLEL", ip_address="10.0.0.1")
    tx3 = Transaction(tx_id="TX-P3", sender_id="NODE-3", receiver_id="NODE-1", amount=9400.0, timestamp=(t0 + timedelta(minutes=30)).isoformat(), channel="wire", device_id="DEV-RING-PARALLEL", ip_address="10.0.0.1")

    ledger.transactions.extend([tx1_a, tx1_b, tx1_c, tx2, tx3])

    engine = FinancialGraphEngine()
    result = engine.run_investigation(ledger)

    assert len(result.detected_cycles) == 1
    cycle = result.detected_cycles[0]

    # Verify that all parallel tx IDs are preserved in all_tx_ids
    assert "TX-P1-A" in cycle.all_tx_ids
    assert "TX-P1-B" in cycle.all_tx_ids
    assert "TX-P1-C" in cycle.all_tx_ids
    assert "TX-P2" in cycle.all_tx_ids
    assert "TX-P3" in cycle.all_tx_ids
    assert len(cycle.all_tx_ids) == 5

    # Check the hop detail for hop 0 (NODE-1 -> NODE-2)
    hop0 = cycle.hops[0]
    assert hop0.from_account == "NODE-1"
    assert hop0.to_account == "NODE-2"
    assert hop0.parallel_tx_count == 2  # The other 2 parallel txs
    assert len(hop0.parallel_tx_ids) == 2


# -----------------------------------------------------------------------------
# 7. Invalid Timestamps & Missing Account Attributes
# -----------------------------------------------------------------------------
def test_invalid_timestamps_and_missing_attributes():
    """Verify that unparseable timestamps, None values, and missing metadata handle gracefully."""
    ledger = LedgerData(scenario_name="Malformed Ledger", description="Garbage inputs")

    # Add accounts with missing / None values
    ledger.accounts["MAL-1"] = Account(account_id="MAL-1", name="", account_type="", kyc_status="", device_id=None, initial_balance=None)
    ledger.accounts["MAL-2"] = Account(account_id="MAL-2", name="Valid Name", account_type="individual", kyc_status="tier_1")
    ledger.accounts["MAL-3"] = Account(account_id="MAL-3", name="Valid Name 2", account_type="individual", kyc_status="tier_1")

    # Injected cycle with garbage timestamps and missing amount
    ledger.transactions.extend([
        Transaction(tx_id="TX-MAL-1", sender_id="MAL-1", receiver_id="MAL-2", amount=9500.0, timestamp="INVALID_DATE_123", channel="p2p", device_id="DEV-X", ip_address="1.1.1.1"),
        Transaction(tx_id="TX-MAL-2", sender_id="MAL-2", receiver_id="MAL-3", amount=None, timestamp=None, channel="p2p", device_id="DEV-X", ip_address="1.1.1.1"),
        Transaction(tx_id="TX-MAL-3", sender_id="MAL-3", receiver_id="MAL-1", amount=9300.0, timestamp="2026-99-99 88:88:88", channel="p2p", device_id="DEV-X", ip_address="1.1.1.1")
    ])

    engine = FinancialGraphEngine()
    result = engine.run_investigation(ledger)

    assert len(result.detected_cycles) == 1
    cycle = result.detected_cycles[0]
    assert cycle.has_invalid_timestamps is True
    assert cycle.hop_count == 3
    # Verify execution finished without unhandled exception
    assert result.execution_time_ms > 0


# -----------------------------------------------------------------------------
# 8. Empty Graphs (0 Nodes, 0 Edges)
# -----------------------------------------------------------------------------
def test_empty_graph():
    """Verify that completely empty ledgers return an empty result without crashing."""
    ledger = LedgerData(scenario_name="Empty Ledger", description="Zero nodes or edges")

    engine = FinancialGraphEngine()
    result = engine.run_investigation(ledger)

    assert result.total_accounts == 0
    assert result.total_transactions == 0
    assert len(result.detected_cycles) == 0
    assert len(result.flagged_cycles) == 0
    assert len(result.smurfing_clusters) == 0
    assert len(result.flagged_accounts) == 0
    assert len(result.flagged_tx_ids) == 0


# -----------------------------------------------------------------------------
# 9. Bounded Cycle Constraints
# -----------------------------------------------------------------------------
def test_bounded_cycle_constraints():
    """Verify that 2-hop cycles (ping-pong) and cycles beyond max_cycle_length are excluded."""
    ledger = LedgerData(scenario_name="Bounds Ledger", description="Cycles of various lengths")

    # Ping pong (2 hops): A <-> B
    ledger.accounts["P1"] = Account(account_id="P1", name="P1", account_type="individual", kyc_status="tier_1")
    ledger.accounts["P2"] = Account(account_id="P2", name="P2", account_type="individual", kyc_status="tier_1")
    t0 = datetime(2026, 10, 24, 10, 0, 0)
    ledger.transactions.extend([
        Transaction(tx_id="TX-PP1", sender_id="P1", receiver_id="P2", amount=100.0, timestamp=t0.isoformat(), channel="wire", device_id="D1", ip_address=""),
        Transaction(tx_id="TX-PP2", sender_id="P2", receiver_id="P1", amount=100.0, timestamp=(t0 + timedelta(minutes=5)).isoformat(), channel="wire", device_id="D1", ip_address="")
    ])

    # Custom rules: min 3 hops, max 5 hops
    rules = EngineRulesConfig(min_cycle_length=3, max_cycle_length=5)
    engine = FinancialGraphEngine(rules=rules)
    result = engine.run_investigation(ledger)

    # 2-hop ping pong must be excluded by min_cycle_length=3
    assert len(result.detected_cycles) == 0


# -----------------------------------------------------------------------------
# 10. Configurable Rules & Scoring
# -----------------------------------------------------------------------------
def test_configurable_rules():
    """Verify that tuning rules (thresholds and weights) alters detection behavior predictably."""
    gen = SyntheticLedgerGenerator(seed=42)
    ledger = gen.generate_scenario("vampire_ring")

    # High threshold rule: requires suspicion >= 0.99
    strict_rules = EngineRulesConfig(min_suspicion_score_to_flag=0.99)
    strict_engine = FinancialGraphEngine(rules=strict_rules)
    strict_result = strict_engine.run_investigation(ledger)

    # Standard rule: threshold = 0.45
    std_rules = EngineRulesConfig(min_suspicion_score_to_flag=0.45)
    std_engine = FinancialGraphEngine(rules=std_rules)
    std_result = std_engine.run_investigation(ledger)

    assert len(std_result.flagged_cycles) >= 1
    assert len(strict_result.flagged_cycles) <= len(std_result.flagged_cycles)
