"""
Bounded cycle enumeration tests (GhostTrace part 3).

Covers cycles within / at / beyond the length limit, empty graphs, overlapping
cycles, duplicate results, equivalence with the old unbounded-then-filter approach,
and regression checks for missing-device and timestamp behaviour.

Written without pytest fixtures/parametrize so both `pytest` and `run_tests.py` work.
"""

import random
from datetime import datetime, timedelta
from unittest import mock

import networkx as nx

from ghost_trace.config import EngineRulesConfig, MAX_CYCLE_LENGTH, MIN_CYCLE_LENGTH
from ghost_trace.data_generator import Account, LedgerData, Transaction
from ghost_trace.graph_engine import FinancialGraphEngine

T0 = datetime(2026, 10, 24, 10, 0, 0)


def _ledger(edges, name="cycle-bounds", device="", step_minutes=10, amount=9500.0):
    """edges: list of (sender, receiver). Each edge becomes one transaction."""
    led = LedgerData(scenario_name=name, description="test")
    for s, r in edges:
        for n in (s, r):
            if n not in led.accounts:
                led.accounts[n] = Account(account_id=n, name=n, account_type="individual",
                                          kyc_status="verified_full", device_id=device)
    for i, (s, r) in enumerate(edges):
        led.transactions.append(Transaction(
            tx_id=f"TX-{i:03d}", sender_id=s, receiver_id=r, amount=amount,
            timestamp=(T0 + timedelta(minutes=step_minutes * i)).isoformat(),
            channel="ach", device_id=None, ip_address=""))
    return led


def _ring(prefix, n):
    nodes = [f"{prefix}{i}" for i in range(n)]
    return [(nodes[i], nodes[(i + 1) % n]) for i in range(n)]


def _paths(result):
    return sorted(frozenset(c.path) for c in result.detected_cycles)


def test_default_limits_unchanged():
    assert MIN_CYCLE_LENGTH == 3
    assert MAX_CYCLE_LENGTH == 6
    rules = EngineRulesConfig()
    assert (rules.min_cycle_length, rules.max_cycle_length) == (3, 6)


def test_cycles_within_limit_all_detected():
    for n in (3, 4, 5):
        res = FinancialGraphEngine().run_investigation(_ledger(_ring("W", n)))
        assert len(res.detected_cycles) == 1, n
        assert res.detected_cycles[0].hop_count == n


def test_cycle_at_max_limit_detected():
    res = FinancialGraphEngine().run_investigation(_ledger(_ring("M", 6)))
    assert len(res.detected_cycles) == 1
    assert res.detected_cycles[0].hop_count == 6


def test_cycle_beyond_max_limit_not_detected():
    for n in (7, 8, 12):
        res = FinancialGraphEngine().run_investigation(_ledger(_ring("B", n)))
        assert res.detected_cycles == [], n
        assert res.flagged_cycles == [], n


def test_cycle_below_min_limit_not_detected():
    two_cycle = [("A", "B"), ("B", "A")]
    self_loop = [("A", "A")]
    assert FinancialGraphEngine().run_investigation(_ledger(two_cycle)).detected_cycles == []
    assert FinancialGraphEngine().run_investigation(_ledger(self_loop)).detected_cycles == []


def test_custom_max_limit_is_respected():
    led = _ledger(_ring("C", 5))
    assert len(FinancialGraphEngine(EngineRulesConfig(max_cycle_length=5)).run_investigation(led).detected_cycles) == 1
    assert FinancialGraphEngine(EngineRulesConfig(max_cycle_length=4)).run_investigation(led).detected_cycles == []
    assert FinancialGraphEngine(EngineRulesConfig(max_cycle_length=2)).run_investigation(led).detected_cycles == []


def test_mixed_lengths_only_in_bound_cycles_returned():
    edges = _ring("A", 3) + _ring("B", 6) + _ring("C", 7) + _ring("D", 9)
    res = FinancialGraphEngine().run_investigation(_ledger(edges))
    assert sorted(c.hop_count for c in res.detected_cycles) == [3, 6]


def test_empty_graphs():
    empty = LedgerData(scenario_name="empty", description="")
    res = FinancialGraphEngine().run_investigation(empty)
    assert res.detected_cycles == [] and res.total_accounts == 0
    # accounts but no transactions
    led = LedgerData(scenario_name="no-tx", description="")
    led.accounts["A"] = Account(account_id="A", name="A", account_type="individual", kyc_status="x")
    res = FinancialGraphEngine().run_investigation(led)
    assert res.detected_cycles == []
    # helper on an empty graph
    assert FinancialGraphEngine()._enumerate_bounded_cycles(nx.DiGraph()) == []


def test_overlapping_cycles_sharing_nodes_and_edges():
    # Two triangles sharing node X, plus a 4-cycle sharing edge X->A with triangle 1
    edges = [("X", "A"), ("A", "B"), ("B", "X"),      # X-A-B
             ("X", "C"), ("C", "D"), ("D", "X"),      # X-C-D (shares node X)
             ("A", "E"), ("E", "F"), ("F", "X")]      # X-A-E-F (shares edge X->A)
    res = FinancialGraphEngine().run_investigation(_ledger(edges))
    got = _paths(res)
    assert set(got) == {frozenset("XAB"), frozenset("XCD"), frozenset("XAEF")}
    assert len(res.detected_cycles) == 3
    assert sorted(c.hop_count for c in res.detected_cycles) == [3, 3, 4]


def test_overlapping_cycles_same_node_set_different_order_kept_distinct():
    # Complete digraph on 3 nodes: 2 distinct directed triangles over the same node set.
    edges = [("A", "B"), ("B", "C"), ("C", "A"), ("A", "C"), ("C", "B"), ("B", "A")]
    res = FinancialGraphEngine().run_investigation(_ledger(edges))
    triangles = [c for c in res.detected_cycles if c.hop_count == 3]
    assert len(triangles) == 2
    assert len({tuple(c.path) for c in triangles}) == 2


def test_no_duplicate_results():
    edges = _ring("A", 4) + _ring("B", 5) + [("A0", "B0"), ("B0", "A0")]
    res = FinancialGraphEngine().run_investigation(_ledger(edges))
    canon = []
    for c in res.detected_cycles:
        i = c.path.index(min(c.path))
        canon.append(tuple(c.path[i:] + c.path[:i]))
    assert len(canon) == len(set(canon))
    ids = [c.cycle_id for c in res.detected_cycles]
    assert len(ids) == len(set(ids))


def test_parallel_transfers_do_not_duplicate_cycle():
    edges = _ring("P", 3)
    led = _ledger(edges)
    for k in range(4):  # 4 extra parallel transfers on first hop
        led.transactions.append(Transaction(
            tx_id=f"TX-PAR-{k}", sender_id="P0", receiver_id="P1", amount=9400.0,
            timestamp=(T0 + timedelta(hours=1 + k)).isoformat(), channel="ach",
            device_id=None, ip_address=""))
    res = FinancialGraphEngine().run_investigation(led)
    assert len(res.detected_cycles) == 1
    assert len(res.detected_cycles[0].all_tx_ids) == 7


def test_cycle_ids_are_deterministic_across_runs():
    edges = _ring("A", 3) + _ring("B", 4) + _ring("C", 5)
    runs = []
    for _ in range(3):
        res = FinancialGraphEngine().run_investigation(_ledger(edges))
        runs.append([(c.cycle_id, tuple(c.path)) for c in res.detected_cycles])
    assert runs[0] == runs[1] == runs[2]


def test_bound_is_passed_to_networkx():
    real = nx.simple_cycles
    seen = {}

    def spy(g, *a, **kw):
        seen.update(kw)
        return real(g, *a, **kw)

    with mock.patch("ghost_trace.graph_engine.nx.simple_cycles", side_effect=spy):
        FinancialGraphEngine().run_investigation(_ledger(_ring("S", 4)))
    assert seen.get("length_bound") == MAX_CYCLE_LENGTH


def test_fallback_when_length_bound_unsupported():
    real = nx.simple_cycles

    def legacy(g, *a, **kw):
        if "length_bound" in kw:
            raise TypeError("unexpected keyword argument 'length_bound'")
        return real(g, *a, **kw)

    edges = _ring("A", 3) + _ring("B", 6) + _ring("C", 8)
    with mock.patch("ghost_trace.graph_engine.nx.simple_cycles", side_effect=legacy):
        res = FinancialGraphEngine().run_investigation(_ledger(edges))
    assert sorted(c.hop_count for c in res.detected_cycles) == [3, 6]


def test_matches_old_unbounded_then_filter_on_random_graphs():
    rng = random.Random(1234)
    for trial in range(12):
        n = rng.randint(6, 12)
        pairs = {(f"N{rng.randrange(n)}", f"N{rng.randrange(n)}") for _ in range(rng.randint(8, 22))}
        edges = sorted(p for p in pairs if p[0] != p[1])
        engine = FinancialGraphEngine()
        res = engine.run_investigation(_ledger(edges))
        simple = nx.DiGraph(edges)
        expected = sorted(
            (tuple(sorted(c)), len(c)) for c in nx.simple_cycles(simple)
            if MIN_CYCLE_LENGTH <= len(c) <= MAX_CYCLE_LENGTH
        )
        got = sorted((tuple(sorted(c.path)), c.hop_count) for c in res.detected_cycles)
        # Compare as multisets of (node set, length); distinct directed cycles over the
        # same node set appear once each in both.
        assert got == expected, f"trial {trial}"


def test_dense_graph_with_long_cycles_terminates_and_stays_bounded():
    nodes = [f"D{i}" for i in range(9)]
    edges = [(a, b) for a in nodes for b in nodes if a != b]
    res = FinancialGraphEngine().run_investigation(_ledger(edges, step_minutes=1))
    assert res.detected_cycles
    assert all(MIN_CYCLE_LENGTH <= c.hop_count <= MAX_CYCLE_LENGTH for c in res.detected_cycles)


def test_scoring_and_output_format_preserved_for_known_ring():
    led = _ledger(_ring("R", 4), device="DEV-SHARED-1", step_minutes=10, amount=9500.0)
    res = FinancialGraphEngine().run_investigation(led)
    c = res.detected_cycles[0]
    d = c.to_dict()
    for key in ("cycle_id", "path", "hop_count", "hops", "all_tx_ids", "suspicion_score",
                "risk_level", "is_flagged_suspicious", "mathematical_rationale",
                "explanation_points", "has_invalid_timestamps"):
        assert key in d
    assert c.cycle_id == "RING-01"
    assert "DEV-SHARED-1" in c.shared_devices
    assert c.is_flagged_suspicious is True
    assert 0.0 <= c.suspicion_score <= 1.0
    assert res.to_dict()["total_cycles_detected"] == 1


def test_missing_device_handling_still_no_false_shared_device():
    for dev in ("", "DEV-UNKNOWN", "DEV-DEFAULT"):
        res = FinancialGraphEngine().run_investigation(_ledger(_ring("Q", 4), device=dev))
        assert res.detected_cycles[0].shared_devices == []
        assert res.detected_cycles[0].shared_device_count == 0


def test_invalid_timestamps_still_handled_in_bounded_cycles():
    led = _ledger(_ring("T", 3))
    for tx in led.transactions:  # all unparseable (mixed valid/invalid is a known pre-existing issue, see HANDOFF.md)
        tx.timestamp = "not-a-date"
    res = FinancialGraphEngine().run_investigation(led)
    assert len(res.detected_cycles) == 1
    assert res.detected_cycles[0].has_invalid_timestamps is True


def test_valid_timestamps_ordering_and_duration_preserved():
    res = FinancialGraphEngine().run_investigation(_ledger(_ring("V", 4), step_minutes=30))
    c = res.detected_cycles[0]
    assert c.has_invalid_timestamps is False
    assert c.start_time == T0.isoformat()
    assert abs(c.total_duration_hours - 1.5) < 1e-6
    assert c.time_gaps_minutes == [30.0, 30.0, 30.0]
