"""
Part 4 regression tests: dashboard / visualization correctness.

Covers dataset switching (AMLSim must never be replaced by regenerated synthetic data), KPI and
benchmark consistency, "Unavailable" evidence for missing timestamps, ground-truth leakage in the
graph, and HTML escaping. No pytest fixtures/parametrize so both runners can execute it.
"""

import json
import os
import re
from datetime import datetime, timedelta

from ghost_trace.agents import GhostTraceInvestigationOrchestrator
from ghost_trace.benchmark import BenchmarkRunner
from ghost_trace.dashboard_helpers import (
    UNAVAILABLE,
    esc,
    fmt_avg_hop,
    fmt_duration,
    fmt_hops_per_hour,
    kpi_summary,
    load_amlsim_bytes,
    load_amlsim_file,
    load_synthetic,
    render_graph_html,
    run_benchmark,
)
from ghost_trace.data_generator import Account, LedgerData, Transaction
from ghost_trace.graph_engine import FinancialGraphEngine
from ghost_trace.visualizer import GraphVisualizer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AMLSIM_SAMPLE = os.path.join(ROOT, "data", "amlsim", "HI-Small_Sample.csv")
AMLSIM_NATIVE = os.path.join(ROOT, "data", "amlsim", "transactions_sample.csv")
T0 = datetime(2026, 10, 24, 10, 0, 0)

SYNTH_HINTS = ("SMURF", "LEGIT", "VAMPIRE", "Vampire", "Disposable Runner", "Shadow Syndicate",
               "Bermuda", "Apex Electronics", "Silicon Wafer", "DEV-SHARED")


# ----------------------------------------------------------------------------- helpers
def _ring_ledger(names=None, ts=None, labels=False, pattern="normal", memo="", dev=None,
                 amount=9500.0, acc_names=None):
    ids = names or ["R0", "R1", "R2", "R3"]
    led = LedgerData(scenario_name="ring", description="")
    for i in ids:
        led.accounts[i] = Account(account_id=i, name=(acc_names or {}).get(i, i), account_type="individual",
                                  kyc_status="verified_full", device_id=dev or "")
    for k, s in enumerate(ids):
        r = ids[(k + 1) % len(ids)]
        stamp = ts(k) if ts else (T0 + timedelta(minutes=10 * k)).isoformat()
        led.transactions.append(Transaction(
            tx_id=f"TX-{k}", sender_id=s, receiver_id=r, amount=amount, timestamp=stamp, channel="ach",
            device_id=dev, ip_address="", memo=memo, is_ground_truth_fraud=labels, pattern_type=pattern))
    return led


def _graph_data(html_text):
    nodes = json.loads(re.search(r"nodes = new vis\.DataSet\((\[.*?\])\);", html_text, re.S).group(1))
    edges = json.loads(re.search(r"edges = new vis\.DataSet\((\[.*?\])\);", html_text, re.S).group(1))
    return nodes, edges


def _style(html_text):
    nodes, edges = _graph_data(html_text)
    return (
        [(n["color"]["background"], n["color"]["border"], n["shape"], n["size"]) for n in nodes],
        [(e["color"], e["width"], e["dashes"], e["label"]) for e in edges],
    )


def _html_for(ledger, mask=True, **kw):
    res = FinancialGraphEngine().run_investigation(ledger)
    return GraphVisualizer(mask_identifiers=mask).generate_html(ledger, res, **kw)


def _norm(result):
    d = result.to_dict()
    d.pop("execution_time_ms", None)
    for c in d["cycles"]:
        c["all_tx_ids"] = sorted(c["all_tx_ids"])
    d["cycles"] = sorted(json.dumps(c, sort_keys=True) for c in d["cycles"])
    for s in d["smurfing"]:
        s["smurf_accounts"] = sorted(s["smurf_accounts"])
        s["shared_devices"] = sorted(s["shared_devices"])
    return json.dumps(d, sort_keys=True, default=str)


# ----------------------------------------------------------------------------- 1. dataset consistency
def test_amlsim_bundle_uses_amlsim_data_not_synthetic():
    b = load_amlsim_file(AMLSIM_SAMPLE, 2000)
    assert b.ok and b.source == "amlsim" and not b.is_synthetic
    assert b.label == "HI-Small_Sample.csv"
    assert "B11-800001" in b.ledger.accounts
    assert not any(a.startswith(("SMURF", "LEGIT")) for a in b.ledger.accounts)
    html_text = render_graph_html(b)
    for hint in SYNTH_HINTS:
        assert hint not in html_text, hint
    assert "B11-800001" in html_text  # real AMLSim identifier is shown (not masked)


def test_graph_node_and_edge_counts_match_selected_dataset():
    for b in (load_amlsim_file(AMLSIM_SAMPLE, 2000), load_synthetic("mixed_ledger", 42)):
        nodes, edges = _graph_data(render_graph_html(b, filter_mode="all"))
        assert len(nodes) == len(b.ledger.accounts)
        assert len(edges) == len(b.ledger.transactions)


def test_switching_datasets_back_and_forth_is_consistent():
    s1 = load_synthetic("vampire_ring", 42)
    a = load_amlsim_file(AMLSIM_SAMPLE, 2000)
    s2 = load_synthetic("vampire_ring", 42)
    assert s1.key != a.key
    assert _norm(s1.result) == _norm(s2.result)          # deterministic, not contaminated by AMLSim
    assert _norm(a.result) != _norm(s1.result)
    assert render_graph_html(s1) == render_graph_html(s2)
    assert render_graph_html(a) != render_graph_html(s1)


def test_different_amlsim_files_and_row_limits_get_distinct_keys_and_data():
    a = load_amlsim_file(AMLSIM_SAMPLE, 2000)
    n = load_amlsim_file(AMLSIM_NATIVE, 2000)
    small = load_amlsim_file(AMLSIM_SAMPLE, 5)
    assert len({a.key, n.key, small.key}) == 3
    assert n.ok and set(n.ledger.accounts) != set(a.ledger.accounts)
    assert len(small.ledger.transactions) == 5 and len(a.ledger.transactions) > 5


def test_upload_bundle_matches_file_bundle_and_keys_by_content():
    raw = open(AMLSIM_SAMPLE, "rb").read()
    up = load_amlsim_bytes(raw, "HI-Small_Sample.csv", 2000)
    fb = load_amlsim_file(AMLSIM_SAMPLE, 2000)
    assert up.ok and _norm(up.result) == _norm(fb.result)
    other = load_amlsim_bytes(raw + b"\n", "HI-Small_Sample.csv", 2000)
    assert other.key != up.key


def test_failed_amlsim_load_returns_error_bundle_not_synthetic_fallback():
    b = load_amlsim_bytes(b"not,a,valid\nfile,at,all\n", "bad.csv", 100)
    assert not b.ok and b.ledger is None and b.result is None
    assert b.load_result is not None and not b.load_result.success and b.load_result.error


def test_kpis_come_from_selected_dataset_and_agree_with_ledger():
    for b in (load_amlsim_file(AMLSIM_SAMPLE, 2000), load_synthetic("mixed_ledger", 7)):
        k = kpi_summary(b)
        assert k["transactions"] == k["ledger_transactions"] == len(b.ledger.transactions)
        assert k["accounts"] >= k["ledger_accounts"] >= 1
        assert k["flagged_cycles"] <= k["total_cycles"]
        assert k["flagged_transactions"] == len(b.result.flagged_tx_ids)
        assert set(b.result.flagged_tx_ids) <= {t.tx_id for t in b.ledger.transactions}


def test_findings_reference_only_selected_dataset_accounts():
    b = load_amlsim_file(AMLSIM_SAMPLE, 2000)
    inv = GhostTraceInvestigationOrchestrator().run_investigation(b.result, b.ledger)
    text = inv.detective_report.raw_markdown + inv.profiler_report.raw_markdown + inv.compliance_report.raw_markdown
    for hint in SYNTH_HINTS:
        assert hint not in text, hint
    for c in b.result.detected_cycles:
        assert set(c.path) <= set(b.ledger.accounts)


# ----------------------------------------------------------------------------- 2. benchmark consistency
def test_benchmark_is_run_on_the_selected_amlsim_ledger():
    b = load_amlsim_file(AMLSIM_SAMPLE, 2000)
    bm = run_benchmark(b)
    assert bm.dataset_source == "amlsim" and bm.dataset_label == "HI-Small_Sample.csv"
    assert bm.ledger_size == {"accounts": len(b.ledger.accounts), "transactions": len(b.ledger.transactions)}
    assert bm.ghost_trace_metrics.total_evaluated == len(b.ledger.transactions)
    assert bm.labelled_positive_count == sum(1 for t in b.ledger.transactions if t.is_ground_truth_fraud)
    cap = bm.provenance_caption()
    assert "IBM AMLSim" in cap and "HI-Small_Sample.csv" in cap and "GhostTrace Synthetic" not in cap
    # same engine result as the dashboard: flagged tx counted in TP+FP are exactly the dashboard's flagged txs
    g = bm.ghost_trace_metrics
    assert g.true_positives + g.false_positives == len(b.result.flagged_tx_ids)


def test_benchmark_synthetic_records_scenario_and_seed():
    b = load_synthetic("legit_rebate", 99)
    bm = run_benchmark(b)
    assert bm.dataset_source == "synthetic" and bm.seed == 99
    assert "GhostTrace Synthetic" in bm.provenance_caption() and "seed 99" in bm.provenance_caption()
    assert bm.scenario_tested == b.ledger.scenario_name
    direct = BenchmarkRunner(seed=99).run_benchmark("legit_rebate")
    assert direct.ghost_trace_metrics.true_positives == bm.ghost_trace_metrics.true_positives
    assert direct.ledger_size == bm.ledger_size and direct.seed == 99


def test_benchmark_results_differ_between_datasets():
    s = run_benchmark(load_synthetic("mixed_ledger", 42))
    a = run_benchmark(load_amlsim_file(AMLSIM_SAMPLE, 2000))
    assert s.ledger_size != a.ledger_size
    assert s.provenance_caption() != a.provenance_caption()


def test_benchmark_without_labels_reports_not_available_instead_of_zero():
    led = _ring_ledger(labels=False)
    bm = BenchmarkRunner(seed=1).run_benchmark_on_ledger(led, dataset_source="amlsim", dataset_label="unlabelled.csv")
    assert bm.labels_available is False and bm.labelled_positive_count == 0
    row = bm.ghost_trace_metrics.to_dict()
    assert row["Precision"].startswith("N/A") and row["Recall"].startswith("N/A") and row["F1 Score"].startswith("N/A")
    assert "no ground-truth" in bm.summary_analysis.lower()
    assert "no ground-truth labels" in bm.provenance_caption()


def test_benchmark_synthetic_negative_control_still_has_metrics():
    bm = run_benchmark(load_synthetic("legit_rebate", 42))   # 0 positives by design, labels exist
    assert bm.labels_available is True
    assert not bm.ghost_trace_metrics.to_dict()["Precision"].startswith("N/A")


def test_benchmark_reuses_dashboard_result_object():
    b = load_synthetic("vampire_ring", 42)
    bm = BenchmarkRunner(seed=42).run_benchmark_on_ledger(b.ledger, graph_result=b.result,
                                                          dataset_source="synthetic", dataset_label="x", seed=42)
    assert bm.ghost_trace_metrics.execution_time_ms == b.result.execution_time_ms


# ----------------------------------------------------------------------------- 3. unavailable evidence
def test_missing_timestamps_report_velocity_unavailable():
    led = _ring_ledger(ts=lambda k: "")
    c = FinancialGraphEngine().run_investigation(led).detected_cycles[0]
    assert c.velocity_available is False and c.has_invalid_timestamps is True
    assert fmt_duration(c) == UNAVAILABLE
    assert fmt_hops_per_hour(c) == UNAVAILABLE
    assert fmt_avg_hop(c) == UNAVAILABLE
    assert c.mathematical_rationale["temporal_velocity_component"] == 0.0
    assert any("Velocity: Unavailable" in p for p in c.explanation_points)
    assert not any("0.00h" in p or "0.00 hops/hr" in p for p in c.explanation_points)
    assert c.to_dict()["velocity_available"] is False


def test_missing_timestamp_is_not_replaced_by_current_time():
    led = _ring_ledger(ts=lambda k: None)
    res = FinancialGraphEngine().run_investigation(led)
    c = res.detected_cycles[0]
    assert all(t == "" for t in c.timestamps)
    assert c.start_time == "" and c.end_time == ""
    assert c.suspicion_score < 0.9  # no fabricated 'instant' velocity score


def test_unparseable_timestamps_report_velocity_unavailable():
    led = _ring_ledger(ts=lambda k: "not-a-date")
    c = FinancialGraphEngine().run_investigation(led).detected_cycles[0]
    assert c.velocity_available is False and fmt_duration(c) == UNAVAILABLE


def test_mixed_valid_and_invalid_timestamps_no_crash_and_unavailable():
    # Previously crashed with naive/aware datetime TypeError (HANDOFF Part 3, remaining issue #1)
    led = _ring_ledger(ts=lambda k: "garbage" if k == 1 else (T0 + timedelta(minutes=10 * k)).isoformat())
    c = FinancialGraphEngine().run_investigation(led).detected_cycles[0]
    assert c.velocity_available is False and c.has_invalid_timestamps is True
    assert c.start_time != "" and c.end_time != ""        # real timestamps still reported
    assert fmt_duration(c) == UNAVAILABLE


def test_timezone_aware_and_naive_timestamps_mix_without_crash():
    def ts(k):
        return (T0 + timedelta(minutes=10 * k)).isoformat() + ("Z" if k % 2 else "")
    c = FinancialGraphEngine().run_investigation(_ring_ledger(ts=ts)).detected_cycles[0]
    assert c.velocity_available is True and c.has_invalid_timestamps is False
    assert 0.4 < c.total_duration_hours < 0.6


def test_valid_timestamps_keep_numeric_velocity_display():
    c = FinancialGraphEngine().run_investigation(_ring_ledger()).detected_cycles[0]
    assert c.velocity_available is True
    assert fmt_duration(c) == "0.50 h"
    assert fmt_hops_per_hour(c) == "8.00 hops/hr"
    assert fmt_avg_hop(c) == "10.0 min"


def test_simultaneous_valid_timestamps_are_not_shown_as_zero():
    c = FinancialGraphEngine().run_investigation(_ring_ledger(ts=lambda k: T0.isoformat())).detected_cycles[0]
    assert c.velocity_available is True
    assert fmt_duration(c) == "<0.01 h" and fmt_duration(c) != "0.00 h"
    assert fmt_hops_per_hour(c) == "Near-simultaneous"


def test_detective_agent_says_unavailable_for_flagged_cycle_without_timestamps():
    led = _ring_ledger(ts=lambda k: "", dev="DEV-X", acc_names=None)
    for a in led.accounts.values():
        a.device_id = "DEV-X"
    res = FinancialGraphEngine().run_investigation(led)
    assert res.flagged_cycles, "fixture should be flagged via shared device + structuring"
    md = GhostTraceInvestigationOrchestrator().run_investigation(res, led).detective_report.raw_markdown
    assert "Temporal Velocity" in md and "Unavailable" in md
    assert "0.00 hours" not in md and "0.00 hops/hr" not in md


# ----------------------------------------------------------------------------- 4. visualization leakage
def test_ground_truth_labels_do_not_change_graph_styling():
    base = _style(_html_for(_ring_ledger(labels=False)))
    labelled = _style(_html_for(_ring_ledger(labels=True)))
    assert base == labelled


def test_pattern_type_does_not_change_graph_styling():
    a = _style(_html_for(_ring_ledger(pattern="normal")))
    b = _style(_html_for(_ring_ledger(pattern="legit_rebate")))
    c = _style(_html_for(_ring_ledger(pattern="vampire_ring")))
    assert a == b == c


def test_labelled_fraud_without_engine_evidence_is_not_highlighted():
    led = LedgerData(scenario_name="acyclic", description="")
    for i in "ABC":
        led.accounts[i] = Account(account_id=i, name=i, account_type="individual", kyc_status="v")
    for k, (s, r) in enumerate([("A", "B"), ("B", "C")]):
        led.transactions.append(Transaction(tx_id=f"T{k}", sender_id=s, receiver_id=r, amount=9500.0,
                                            timestamp=T0.isoformat(), channel="ach", device_id=None,
                                            ip_address="", is_ground_truth_fraud=True, pattern_type="vampire_ring"))
    nodes, edges = _style(_html_for(led))
    assert all(n == nodes[0] for n in nodes) and nodes[0][0] == "#1E293B"
    assert all(e == ("#334155", 1.0, False, "") for e in edges)


def test_account_id_substrings_do_not_drive_styling():
    plain = _style(_html_for(_ring_ledger(names=["A0", "A1", "A2", "A3"]), mask=False))
    smurfy = _style(_html_for(_ring_ledger(names=["SMURF-1", "SMURF-2", "LEGIT-3", "SMURF-4"]), mask=False))
    assert plain == smurfy
    # acyclic 'LEGIT' / 'SMURF' accounts are plain nodes
    led = LedgerData(scenario_name="n", description="")
    for i in ("LEGIT-X", "SMURF-Y"):
        led.accounts[i] = Account(account_id=i, name=i, account_type="individual", kyc_status="v")
    led.transactions.append(Transaction(tx_id="T", sender_id="LEGIT-X", receiver_id="SMURF-Y", amount=50.0,
                                        timestamp=T0.isoformat(), channel="ach", device_id=None, ip_address=""))
    nodes, _ = _style(_html_for(led, mask=False))
    assert {n[0] for n in nodes} == {"#1E293B"} and {n[2] for n in nodes} == {"dot"}


def test_synthetic_graph_reveals_no_label_bearing_names():
    for scen in ("mixed_ledger", "smurfing", "legit_rebate", "dormant_reactivation", "vampire_ring"):
        h = render_graph_html(load_synthetic(scen, 42), filter_mode="all")
        for hint in SYNTH_HINTS:
            assert hint not in h, (scen, hint)
        nodes, edges = _graph_data(h)
        assert all(re.fullmatch(r"n\d+", n["id"]) for n in nodes)


def test_masked_aliases_are_stable_and_distinct():
    v = GraphVisualizer(mask_identifiers=True)
    assert v._acc_disp("SMURF-1") == v._acc_disp("SMURF-1")
    assert v._acc_disp("SMURF-1") != v._acc_disp("SMURF-2")
    assert "SMURF" not in v._acc_disp("SMURF-1")


def test_styling_changes_follow_engine_evidence():
    led = _ring_ledger(dev="DEV-X")           # shared device + structured amounts => flagged by evidence
    res = FinancialGraphEngine().run_investigation(led)
    assert res.flagged_cycles
    nodes, edges = _style(GraphVisualizer().generate_html(led, res))
    assert {n[0] for n in nodes} == {"#FF3366"} and {n[3] for n in nodes} == {26}
    assert {e[0] for e in edges} == {"#FF3366"} and {e[1] for e in edges} == {3.5}
    benign = _ring_ledger(amount=120.0, ts=lambda k: (T0 + timedelta(days=5 * k)).isoformat())
    bres = FinancialGraphEngine().run_investigation(benign)
    assert bres.detected_cycles and not bres.flagged_cycles
    bn, be = _style(GraphVisualizer().generate_html(benign, bres))
    assert {n[0] for n in bn} == {"#10B981"}                  # cleared cycle: green by evidence
    assert all(e[0] == "#10B981" and e[2] == [5, 5] for e in be)


def test_ledger_inspector_and_explorer_do_not_expose_labels_in_app_source():
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8", newline="").read()
    assert '"Ground Truth Fraud"' not in src
    assert '"Pattern Type"' not in src


# ----------------------------------------------------------------------------- 5. safe rendering
XSS_NAME = '<script>alert(1)</script>"><img src=x onerror=alert(2)>'


def test_esc_helper():
    assert esc(None) == ""
    assert esc("<b>&\"'") == "&lt;b&gt;&amp;&quot;&#x27;"
    assert "<" not in esc(XSS_NAME)


ALLOWED_TAGS = {"div", "b", "br", "span", "code"}


def _decoded_tags(html_text):
    """Tag names present in the DECODED tooltips/labels (what the browser will actually render)."""
    nodes, edges = _graph_data(html_text)
    tags = set()
    for item in nodes + edges:
        for field in ("title", "label"):
            tags |= {t.lower() for t in re.findall(r"<\s*/?\s*([A-Za-z][A-Za-z0-9]*)", item.get(field) or "")}
    return tags


def test_untrusted_account_names_and_memos_are_escaped_in_graph_html():
    names = {"R0": XSS_NAME, "R1": "ok"}
    led = _ring_ledger(memo=XSS_NAME, acc_names=names)
    led.accounts["R3"].kyc_status = XSS_NAME
    led.accounts["R3"].device_id = XSS_NAME
    led.accounts["R3"].ip_address = XSS_NAME
    led.transactions[0].channel = XSS_NAME
    led.transactions[1].timestamp = XSS_NAME
    for mask in (False, True):
        h = _html_for(led, mask=mask)
        tags = _decoded_tags(h)
        assert tags <= ALLOWED_TAGS, (mask, tags - ALLOWED_TAGS)     # no script/img/etc. injected into tooltips
        assert "onerror=alert(2)>" not in h
        base = _html_for(_ring_ledger(), mask=mask)
        assert h.count("</script>") == base.count("</script>")       # nothing can close the embedding script tag
        nodes, edges = _graph_data(h)                                 # embedded JSON still parses
        assert len(nodes) == 4 and len(edges) == 4


def test_unmasked_tooltips_show_escaped_text_not_markup():
    led = _ring_ledger(memo=XSS_NAME, acc_names={"R0": XSS_NAME})
    nodes, edges = _graph_data(_html_for(led, mask=False))
    joined = " ".join(n["title"] for n in nodes) + " ".join(e["title"] for e in edges)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in joined
    assert "<script>" not in joined and "<img" not in joined


def test_untrusted_account_id_cannot_break_script_or_html():
    evil = '</script><script>alert(9)</script>'
    led = _ring_ledger(names=[evil, "B", "C", "D"])
    for mask in (False, True):
        h = _html_for(led, mask=mask)
        assert h.count("</script>") == _html_for(_ring_ledger(), mask=mask).count("</script>")
        assert _decoded_tags(h) <= ALLOWED_TAGS
        nodes, edges = _graph_data(h)
        assert len(nodes) == 4 and all("<" not in n["label"] and ">" not in n["label"] for n in nodes)


def test_malicious_text_does_not_break_engine_or_agents():
    led = _ring_ledger(acc_names={"R0": XSS_NAME}, memo=XSS_NAME, dev="DEV-X")
    res = FinancialGraphEngine().run_investigation(led)
    inv = GhostTraceInvestigationOrchestrator().run_investigation(res, led)
    assert inv.detective_report.raw_markdown


# ----------------------------------------------------------------------------- 6. end-to-end dashboard smoke
def _app_test():
    try:
        from streamlit.testing.v1 import AppTest
    except Exception:
        return None
    return AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=180)


def test_dashboard_end_to_end_dataset_switch():
    at = _app_test()
    if at is None:
        return  # streamlit not installed: covered by the helper-level tests above
    at.run()
    assert not at.exception
    md_syn = " ".join(m.value for m in at.markdown)
    assert "Benchmark scope" in md_syn and "GhostTrace Synthetic" in md_syn
    at.sidebar.radio[0].set_value("IBM AMLSim Dataset").run()
    assert not at.exception, [e.value for e in at.exception]
    md_aml = " ".join(m.value for m in at.markdown)
    assert "Benchmark scope" in md_aml and "IBM AMLSim" in md_aml
    assert "Evaluated: GhostTrace Synthetic" not in md_aml
    assert "Dataset: " in md_aml and "IBM AMLSim" in md_aml
    at.sidebar.radio[0].set_value("GhostTrace Synthetic Data").run()
    assert not at.exception
    assert "Evaluated: GhostTrace Synthetic" in " ".join(m.value for m in at.markdown)
