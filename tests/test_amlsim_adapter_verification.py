"""
AMLSim adapter VERIFICATION tests (testing-only step).

Scope
-----
* load_amlsim_transactions() (strict loader) against the AMLSim-native schema.
* Compatibility of the adapter's LedgerData with the existing
  FinancialGraphEngine / agents / SAR generator.
* Separation of the evaluation labels (is_sar, alert_id) from every detection
  input and prediction.

Data policy
-----------
Every fixture is a tiny CSV written to a temporary directory. No real AMLSim
dataset, no 8 GB file and no network access is needed (see
test_no_network_needed_for_loader_and_engine). The only repo files read are the
two hand-made samples already shipped in data/amlsim/.

Schema reference (checked against upstream IBM/AMLSim master while writing
these tests): paramFiles/schema.json "transaction" section lists, in this
order: tran_id, tran_timestamp, base_amt, tx_type, orig_acct, bene_acct,
is_sar, alert_id. scripts/convert_logs.py writes is_sar as a Python bool
("True"/"False"), alert_id as an int (-1 = not an alert) and tran_timestamp as
str(step) (an integer simulation step, NOT a calendar date).

Documented handling policy asserted below
-----------------------------------------
* Duplicate tran_id : FIRST occurrence wins. Later rows with the same id are
  skipped and itemised in skip_reasons; their labels are discarded. An id is
  only "reserved" by a row that was actually accepted (a malformed first row
  does not block a later valid row with that id). Detection is per load call
  (it is not remembered across chunks).
* Missing values    : empty tran_id / orig_acct / bene_acct / base_amt /
  tran_timestamp -> row skipped. Blank tx_type -> loaded with channel
  "unknown". Blank or junk is_sar / alert_id -> row still loaded; label stored
  as None.
* Amount            : finite float > 0, plain decimal / exponent notation.
  Thousands separators and currency symbols are rejected.
* Blank lines       : ignored; they never count as rows or as malformed.
* Row budget        : max_rows counts non-blank data rows read, malformed rows
  included. skip_rows counts non-blank data rows too, so chunks line up.

These tests are written to be called as bare functions by run_tests.py
(no pytest fixtures / parametrize).
"""

import copy
import dataclasses
import inspect
import json
import os
import re
import socket
import sys
import tempfile
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ghost_trace.amlsim_adapter import (
    ABSOLUTE_MAX_ROWS,
    AMLSIM_LABEL_COLUMNS,
    AMLSIM_REQUIRED_COLUMNS,
    AMLSimAdapter,
    AMLSimEvalLabel,
    AMLSimLoadResult,
    AMLSimTimeConfig,
    load_amlsim_transactions,
)
from ghost_trace.agents import GhostTraceInvestigationOrchestrator
from ghost_trace.data_generator import Account, LedgerData, Transaction
from ghost_trace.graph_engine import FinancialGraphEngine, safe_parse_datetime
from ghost_trace.sar_generator import SARGenerator

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Exact upstream column ORDER (differs from the order used in older tests).
UPSTREAM_HEADER = "tran_id,tran_timestamp,base_amt,tx_type,orig_acct,bene_acct,is_sar,alert_id"


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def _csv(text="", name="transactions.csv", raw=None):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, name)
        with open(p, "wb") as f:
            f.write(raw if raw is not None else text.encode("utf-8"))
        yield p


def _txt(*rows, header=UPSTREAM_HEADER):
    return header + "\n" + "\n".join(rows) + "\n"


def _load(*rows, header=UPSTREAM_HEADER, **kw):
    with _csv(_txt(*rows, header=header)) as p:
        return load_amlsim_transactions(p, **kw)


def _strip_volatile(obj):
    """Drop wall-clock fields so two engine runs can be compared exactly."""
    if isinstance(obj, dict):
        return {k: _strip_volatile(v) for k, v in obj.items()
                if k not in ("execution_time_ms", "total_latency_seconds",
                             "investigation_id", "generated_at")}
    if isinstance(obj, list):
        return [_strip_volatile(v) for v in obj]
    if isinstance(obj, str):          # agent reports may be repr() strings
        return re.sub(r"generated_at='[^']*'", "generated_at=<t>", obj)
    return obj


def _engine_fingerprint(ledger):
    res = FinancialGraphEngine().run_investigation(ledger)
    d = _strip_volatile(res.to_dict())
    # all_tx_ids is built from a set; order is not part of the contract.
    for c in d.get("cycles", []):
        if "all_tx_ids" in c:
            c["all_tx_ids"] = sorted(c["all_tx_ids"])
    return json.dumps(d, sort_keys=True, default=str)


RING = [
    "1,0,9900.00,TRANSFER,A,B,True,5",
    "2,1,9800.00,TRANSFER,B,C,True,5",
    "3,2,9700.00,TRANSFER,C,A,True,5",
    "4,2,50.00,CASH-IN,X,Y,False,-1",
]
RING_UNLABELLED = [r.rsplit(",", 2)[0] + ",False,-1" for r in RING]


# ═════════════════════════════════════════════════════════════════════════════
# 1. Schema fidelity and mapping
# ═════════════════════════════════════════════════════════════════════════════

def test_v_upstream_column_order_and_python_bool_labels_map_correctly():
    """Real convert_logs.py layout: tran_timestamp 2nd, 'True'/'False', alert_id -1."""
    r = _load(*RING)
    assert r.success, r.error
    assert r.detected_format == "amlsim_native"
    by_id = {t.tx_id: t for t in r.ledger.transactions}
    assert set(by_id) == {"1", "2", "3", "4"}
    t2 = by_id["2"]
    assert (t2.sender_id, t2.receiver_id, t2.amount, t2.channel) == ("B", "C", 9800.0, "TRANSFER")
    assert by_id["4"].channel == "CASH-IN"           # tx_type verbatim
    assert r.raw_timestamps == {"1": "0", "2": "1", "3": "2", "4": "2"}
    assert r.labels["1"] == AMLSimEvalLabel(is_sar=True, alert_id="5")
    assert r.labels["4"] == AMLSimEvalLabel(is_sar=False, alert_id="-1")
    assert r.label_columns_present == AMLSIM_LABEL_COLUMNS


def test_v_each_required_column_missing_is_reported_by_name():
    for missing in AMLSIM_REQUIRED_COLUMNS:
        cols = [c for c in UPSTREAM_HEADER.split(",") if c != missing]
        row = ",".join("1" for _ in cols)
        with _csv(",".join(cols) + "\n" + row + "\n") as p:
            r = load_amlsim_transactions(p)
        assert not r.success and r.ledger is None, missing
        assert "Missing required" in r.error and missing in r.error, (missing, r.error)


def test_v_ids_stay_strings_and_whitespace_is_trimmed_commas_in_quotes_kept():
    r = _load('00042,0,10,TRANSFER, A1 ,"B,2",False,-1')
    assert r.success, r.error
    t = r.ledger.transactions[0]
    assert t.tx_id == "00042"                       # leading zeros preserved
    assert (t.sender_id, t.receiver_id) == ("A1", "B,2")
    assert isinstance(t.tx_id, str) and isinstance(t.sender_id, str)


def test_v_loaded_objects_match_ghosttrace_dataclasses_exactly():
    r = _load(*RING)
    led = r.ledger
    assert isinstance(led, LedgerData)
    tx_fields = {f.name for f in dataclasses.fields(Transaction)}
    acc_fields = {f.name for f in dataclasses.fields(Account)}
    for t in led.transactions:
        assert isinstance(t, Transaction)
        assert set(t.to_dict()) == tx_fields
        assert isinstance(t.amount, float) and t.amount > 0
        assert isinstance(t.timestamp, str) and safe_parse_datetime(t.timestamp) is not None
        assert isinstance(t.channel, str) and t.channel
    for aid, a in led.accounts.items():
        assert isinstance(a, Account) and a.account_id == aid
        assert set(a.to_dict()) == acc_fields
    endpoints = {x for t in led.transactions for x in (t.sender_id, t.receiver_id)}
    assert set(led.accounts) == endpoints == {"A", "B", "C", "X", "Y"}
    assert led.to_dict()["transaction_count"] == 4          # ledger serialiser works


def test_v_every_amlsim_step_maps_to_exact_distinct_ordered_timestamp():
    r = _load("1,0,10,T,A,B,False,-1", "2,1,10,T,B,C,False,-1", "3,719,10,T,C,D,False,-1")
    ts = {t.tx_id: safe_parse_datetime(t.timestamp) for t in r.ledger.transactions}
    assert (ts["2"] - ts["1"]).days == 1
    assert (ts["3"] - ts["1"]).days == 719
    cfg = AMLSimTimeConfig(base_date="2017-01-01", step_unit="day")
    r2 = _load("1,0,10,T,A,B,False,-1", "3,719,10,T,C,D,False,-1", time_config=cfg)
    assert [t.timestamp for t in r2.ledger.transactions] == [
        "2017-01-01T00:00:00", "2018-12-21T00:00:00"]       # 2017-01-01 + 719 days


def test_v_shipped_native_sample_loads_and_kaggle_sample_is_rejected_clearly():
    native = os.path.join(PROJECT_ROOT, "data", "amlsim", "transactions_sample.csv")
    kaggle = os.path.join(PROJECT_ROOT, "data", "amlsim", "HI-Small_Sample.csv")
    assert os.path.isfile(native) and os.path.isfile(kaggle)
    r = load_amlsim_transactions(native)
    assert r.success, r.error
    assert r.rows_loaded == 12 and r.rows_skipped == 0
    assert r.label_columns_present == ("is_sar",)            # sample has no alert_id
    assert all(lb.alert_id is None for lb in r.labels.values())
    k = load_amlsim_transactions(kaggle)                     # different dataset family
    assert not k.success and "Missing required" in k.error and "tran_id" in k.error


# ═════════════════════════════════════════════════════════════════════════════
# 2. Missing files, empty files, bad structure
# ═════════════════════════════════════════════════════════════════════════════

def test_v_bad_paths_never_raise():
    for bad in ("", os.path.join(tempfile.gettempdir(), "no_such_dir_xyz", "x.csv")):
        r = load_amlsim_transactions(bad)
        assert isinstance(r, AMLSimLoadResult) and not r.success and r.error, repr(bad)
    r = load_amlsim_transactions(None)                       # type: ignore[arg-type]
    assert not r.success and "path" in r.error.lower()


def test_v_pathlike_is_accepted():
    import pathlib
    with _csv(_txt("1,0,10,T,A,B,False,-1")) as p:
        r = load_amlsim_transactions(pathlib.Path(p))
    assert r.success, r.error


def test_v_whitespace_only_and_blank_header_rejected():
    with _csv("   \n\n") as p:
        r = load_amlsim_transactions(p)
    assert not r.success and r.ledger is None
    with _csv(",,,\n1,2,3,4\n") as p:
        r = load_amlsim_transactions(p)
    assert not r.success and "header" in r.error.lower()


def test_v_utf8_bom_and_crlf_line_endings_load():
    raw = b"\xef\xbb\xbf" + (UPSTREAM_HEADER + "\r\n1,0,10,T,A,B,False,-1\r\n2,1,20,T,B,A,True,3\r\n").encode()
    with _csv(raw=raw) as p:
        r = load_amlsim_transactions(p)
    assert r.success, r.error
    assert [t.amount for t in r.ledger.transactions] == [10.0, 20.0]
    assert r.labels["2"].is_sar is True


def test_v_unterminated_quote_is_reported_as_malformed_and_never_raises():
    """csv.reader folds everything after an unterminated quote into ONE record.
    Characterisation: rows before it load, the folded record is itemised as
    malformed (the rows folded into it are not individually reported)."""
    body = "0,0,10,T,A,B,False,-1\n1,0,10,T,\"A,B,False,-1\n2,0,10,T,C,D,False,-1\n"
    with _csv(UPSTREAM_HEADER + "\n" + body) as p:
        r = load_amlsim_transactions(p)
    assert r.success and r.rows_loaded == 1 and r.rows_skipped == 1
    assert [t.tx_id for t in r.ledger.transactions] == ["0"]
    assert "expected 8 fields" in r.skip_reasons[0]
    with _csv(UPSTREAM_HEADER + "\n1,0,10,T,\"A,B,False,-1\n") as p:
        r = load_amlsim_transactions(p)
    assert not r.success and r.ledger is None and r.error


# ═════════════════════════════════════════════════════════════════════════════
# 3. Invalid amounts, malformed rows, missing values
# ═════════════════════════════════════════════════════════════════════════════

def test_v_amount_policy_plain_decimals_ok_symbols_and_separators_rejected():
    ok = {"10": 10.0, "10.50": 10.5, ".5": 0.5, "1e3": 1000.0, "  7 ": 7.0}
    for raw, expected in ok.items():
        r = _load(f"1,0,{raw},T,A,B,False,-1")
        assert r.success and r.ledger.transactions[0].amount == expected, raw
    bad = ["", "abc", "0", "-1", "-0.01", "nan", "NaN", "inf", "-inf", "1e999", '"1,000"', "$100", "10%"]
    for raw in bad:
        r = _load("9,0,5,T,A,B,False,-1", f"1,0,{raw},T,A,B,False,-1")
        assert r.success and r.rows_loaded == 1 and r.rows_skipped == 1, (raw, r.error)
        assert r.skip_reasons and "base_amt" in r.skip_reasons[0], (raw, r.skip_reasons)


def test_v_each_missing_field_follows_the_documented_policy():
    base = ["1", "0", "10", "TRANSFER", "A", "B", "True", "7"]
    cols = UPSTREAM_HEADER.split(",")

    def row_with_blank(name):
        cells = list(base)
        cells[cols.index(name)] = ""
        return ",".join(cells)

    # fields whose absence rejects the row
    for name, needle in (("tran_id", "empty tran_id"), ("orig_acct", "empty orig_acct"),
                         ("bene_acct", "empty bene_acct"), ("base_amt", "empty base_amt"),
                         ("tran_timestamp", "unparseable tran_timestamp")):
        r = _load("99,0,5,T,P,Q,False,-1", row_with_blank(name))
        assert r.success and r.rows_loaded == 1 and r.rows_skipped == 1, name
        assert needle in r.skip_reasons[0], (name, r.skip_reasons)
    # tx_type: loaded as "unknown"
    r = _load(row_with_blank("tx_type"))
    assert r.success and r.ledger.transactions[0].channel == "unknown"
    # labels: loaded, label None
    r = _load(row_with_blank("is_sar"))
    assert r.success and r.labels["1"] == AMLSimEvalLabel(is_sar=None, alert_id="7")
    r = _load(row_with_blank("alert_id"))
    assert r.success and r.labels["1"] == AMLSimEvalLabel(is_sar=True, alert_id=None)


def test_v_truncated_and_overlong_rows_are_malformed_not_shifted():
    r = _load("1,0,10,T,A,B,False,-1",
              "2,0,10,T,A,B",                       # short
              "3,0,10,T,A,B,False,-1,EXTRA",        # long
              "4,0,10,T,C,D,False,-1")
    assert r.rows_loaded == 2 and r.rows_skipped == 2
    assert [t.tx_id for t in r.ledger.transactions] == ["1", "4"]
    assert all("fields" in s for s in r.skip_reasons)


def test_v_skip_reason_list_is_capped_but_skip_count_is_exact():
    rows = [f"{i},0,bad,T,A,B,False,-1" for i in range(1, 121)] + ["500,0,10,T,A,B,False,-1"]
    r = _load(*rows)
    assert r.success and r.rows_loaded == 1 and r.rows_skipped == 120
    assert len(r.skip_reasons) == 50
    assert any("70 further malformed rows" in w for w in r.warnings)


def test_v_strict_flag_rejects_whole_file_on_any_malformed_row_and_returns_no_ledger():
    r = _load("1,0,10,T,A,B,False,-1", "2,0,10,T,A,B", strict=True)
    assert not r.success and r.ledger is None and "Strict mode" in r.error
    r = _load("1,0,10,T,A,B,False,-1", "2,0,10,T,A,B,False,-1", strict=True)
    assert r.success and r.rows_loaded == 2


# ═════════════════════════════════════════════════════════════════════════════
# 4. Duplicate transaction IDs (documented policy: first wins)
# ═════════════════════════════════════════════════════════════════════════════

def test_v_duplicate_tran_id_first_wins_and_dup_label_is_discarded():
    r = _load("7,0,100,TRANSFER,A,B,False,-1",
              "7,1,999,CASH-OUT,C,D,True,42")        # same id, everything different
    assert r.success and r.rows_loaded == 1 and r.rows_skipped == 1
    t = r.ledger.transactions[0]
    assert (t.sender_id, t.receiver_id, t.amount, t.channel) == ("A", "B", 100.0, "TRANSFER")
    assert r.labels == {"7": AMLSimEvalLabel(is_sar=False, alert_id="-1")}
    assert r.raw_timestamps == {"7": "0"}
    assert "duplicate tran_id '7'" in r.skip_reasons[0]
    assert set(r.ledger.accounts) == {"A", "B"}          # losing row's accounts not created


def test_v_duplicate_ids_are_compared_after_trimming_and_case_sensitively():
    r = _load("T1,0,10,T,A,B,False,-1", " T1 ,1,10,T,B,C,False,-1", "t1,2,10,T,C,D,False,-1")
    assert [t.tx_id for t in r.ledger.transactions] == ["T1", "t1"]
    assert r.rows_skipped == 1 and "duplicate" in r.skip_reasons[0]


def test_v_malformed_first_occurrence_does_not_reserve_the_id():
    r = _load("5,0,bad,T,A,B,False,-1", "5,1,20,T,C,D,False,-1")
    assert r.rows_loaded == 1 and r.rows_skipped == 1
    assert r.ledger.transactions[0].amount == 20.0
    assert "base_amt" in r.skip_reasons[0]


def test_v_duplicate_in_strict_mode_fails_the_load():
    r = _load("1,0,10,T,A,B,False,-1", "1,1,10,T,B,C,False,-1", strict=True)
    assert not r.success and "duplicate" in r.error


def test_v_graph_edge_count_equals_rows_loaded_so_nothing_is_silently_collapsed():
    """MultiDiGraph keys edges by tx_id; the loader's duplicate rejection guarantees no overwrite."""
    rows = ["1,0,10,T,A,B,False,-1", "1,1,20,T,A,B,False,-1",   # dup id, same pair
            "2,2,30,T,A,B,False,-1", "3,3,40,T,B,A,False,-1"]
    r = _load(*rows)
    g = FinancialGraphEngine().build_graph(r.ledger)
    assert g.number_of_edges() == r.rows_loaded == 3


# ═════════════════════════════════════════════════════════════════════════════
# 5. Row limits and chunked reading
# ═════════════════════════════════════════════════════════════════════════════

def test_v_row_limit_boundaries():
    rows = [f"{i},{i},10,T,A{i},B{i},False,-1" for i in range(1, 6)]
    assert not _load(*rows, max_rows=5).truncated          # exactly at the limit
    r = _load(*rows, max_rows=4)
    assert r.truncated and r.rows_loaded == 4 and r.rows_attempted == 4
    assert _load(*rows, max_rows=ABSOLUTE_MAX_ROWS).success   # ceiling itself is legal


def test_v_malformed_rows_consume_the_row_budget():
    rows = ["1,0,bad,T,A,B,False,-1", "2,0,bad,T,A,B,False,-1",
            "3,0,10,T,A,B,False,-1", "4,0,10,T,B,C,False,-1"]
    r = _load(*rows, max_rows=3)
    assert r.rows_attempted == 3 and r.rows_loaded == 1 and r.rows_skipped == 2 and r.truncated


def test_v_chunks_concatenate_to_exactly_the_full_file_clean_input():
    rows = [f"{i},{i},10,T,A{i},B{i},False,-1" for i in range(1, 11)]
    with _csv(_txt(*rows)) as p:
        full = [t.tx_id for t in load_amlsim_transactions(p).ledger.transactions]
        for size in (1, 3, 4, 10):
            got = []
            for k in range(0, 10, size):
                c = load_amlsim_transactions(p, max_rows=size, skip_rows=k)
                assert c.success, (size, k, c.error)
                got += [t.tx_id for t in c.ledger.transactions]
            assert got == full, size


def test_v_chunks_concatenate_to_full_file_when_blank_lines_are_present():
    """Blank lines are 'ignored' by the loader, so they must not shift skip_rows."""
    body = ["1,1,10,T,A1,B1,False,-1", "", "2,2,10,T,A2,B2,False,-1",
            "3,3,10,T,A3,B3,False,-1", "", "", "4,4,10,T,A4,B4,False,-1",
            "5,5,10,T,A5,B5,False,-1", "6,6,10,T,A6,B6,False,-1"]
    text = UPSTREAM_HEADER + "\n" + "\n".join(body) + "\n"
    with _csv(text) as p:
        full = [t.tx_id for t in load_amlsim_transactions(p).ledger.transactions]
        assert full == ["1", "2", "3", "4", "5", "6"]
        got = []
        for k in range(0, 6, 2):
            c = load_amlsim_transactions(p, max_rows=2, skip_rows=k)
            assert c.success, (k, c.error)
            got += [t.tx_id for t in c.ledger.transactions]
    assert got == full, f"chunks overlap or drop rows: {got}"


def test_v_chunks_line_up_when_malformed_rows_are_inside_chunks():
    rows = ["1,1,10,T,A1,B1,False,-1", "2,2,bad,T,A2,B2,False,-1", "3,3,10,T,A3,B3,False,-1",
            "4,4,10,T,A4,B4", "5,5,10,T,A5,B5,False,-1", "6,6,10,T,A6,B6,False,-1"]
    with _csv(_txt(*rows)) as p:
        full = [t.tx_id for t in load_amlsim_transactions(p).ledger.transactions]
        got = []
        for k in range(0, 6, 3):
            got += [t.tx_id for t in load_amlsim_transactions(p, max_rows=3, skip_rows=k).ledger.transactions]
    assert full == ["1", "3", "5", "6"] and got == full


def test_v_skip_rows_at_and_beyond_end_give_clear_errors():
    rows = ["1,1,10,T,A,B,False,-1", "2,2,10,T,B,C,False,-1"]
    with _csv(_txt(*rows)) as p:
        at_end = load_amlsim_transactions(p, skip_rows=2)
        beyond = load_amlsim_transactions(p, skip_rows=3)
    assert not at_end.success and "no data rows" in at_end.error
    assert not beyond.success and "beyond the end" in beyond.error


def test_v_duplicate_detection_is_per_load_call_documented_limit():
    """Documented limitation: ids are not remembered across chunks."""
    rows = ["1,0,10,T,A,B,False,-1", "1,1,10,T,C,D,False,-1"]
    with _csv(_txt(*rows)) as p:
        a = load_amlsim_transactions(p, max_rows=1, skip_rows=0)
        b = load_amlsim_transactions(p, max_rows=1, skip_rows=1)
    assert a.success and b.success      # each chunk is internally consistent


# ═════════════════════════════════════════════════════════════════════════════
# 6. Label separation (is_sar / alert_id vs. detection inputs & predictions)
# ═════════════════════════════════════════════════════════════════════════════

def test_v_sentinel_label_values_appear_nowhere_in_the_ledger():
    rows = ["1,0,9900,TRANSFER,A,B,True,ALERT-SENTINEL-77",
            "2,1,9800,TRANSFER,B,C,True,ALERT-SENTINEL-77",
            "3,2,9700,TRANSFER,C,A,True,ALERT-SENTINEL-77"]
    r = _load(*rows)
    assert r.labels["1"].alert_id == "ALERT-SENTINEL-77"
    blob = json.dumps(r.ledger.to_dict(), default=str)
    assert "ALERT-SENTINEL-77" not in blob and "is_sar" not in blob and "alert_id" not in blob
    for t in r.ledger.transactions:
        assert t.is_ground_truth_fraud is False and t.pattern_type == "amlsim_imported"
    assert r.ledger.ground_truth_rings == []
    assert not hasattr(r.ledger, "labels")
    assert "is_sar" not in {f.name for f in dataclasses.fields(Transaction)}
    assert "alert_id" not in {f.name for f in dataclasses.fields(Transaction)}


def test_v_graph_edges_carry_no_positive_label_even_when_every_row_is_sar():
    r = _load(*[row.replace("False,-1", "True,9") for row in RING])
    g = FinancialGraphEngine().build_graph(r.ledger)
    assert g.number_of_edges() == 4
    for _, _, d in g.edges(data=True):
        assert d["is_ground_truth"] is False
        assert d["pattern_type"] == "amlsim_imported"
        assert "is_sar" not in d and "alert_id" not in d


def test_v_engine_output_unchanged_when_ledger_label_fields_are_forced_either_way():
    """Even if someone DID set the legacy label fields, the engine must not react."""
    r = _load(*RING_UNLABELLED)
    base = _engine_fingerprint(r.ledger)
    as_fraud = copy.deepcopy(r.ledger)
    for t in as_fraud.transactions:
        t.is_ground_truth_fraud, t.pattern_type = True, "vampire_ring"
    as_normal = copy.deepcopy(r.ledger)
    for t in as_normal.transactions:
        t.is_ground_truth_fraud, t.pattern_type = False, "normal"
    as_fraud.ground_truth_rings = [{"ring_id": "R", "tx_ids": ["1", "2", "3"], "is_fraud": True}]
    assert _engine_fingerprint(as_fraud) == base
    assert _engine_fingerprint(as_normal) == base


def test_v_agent_and_sar_outputs_unchanged_by_label_fields():
    r = _load(*RING_UNLABELLED)
    ledger_a = r.ledger
    ledger_b = copy.deepcopy(ledger_a)
    for t in ledger_b.transactions:
        t.is_ground_truth_fraud, t.pattern_type = True, "vampire_ring"
    outs = []
    for led in (ledger_a, ledger_b):
        res = FinancialGraphEngine().run_investigation(led)
        rep = GhostTraceInvestigationOrchestrator().run_investigation(res, led)
        outs.append((rep.overall_verdict, rep.overall_risk_score, sorted(rep.flagged_entities)
                     if isinstance(rep.flagged_entities, list) else rep.flagged_entities,
                     _strip_volatile(str(rep.detective_report)),
                     _strip_volatile(str(rep.profiler_report))))
    assert outs[0] == outs[1]


def test_v_legacy_adapter_detection_is_also_label_independent():
    """app.py still uses AMLSimAdapter, which keeps labels on the transaction."""
    hdr = b"tran_id,orig_acct,bene_acct,tx_type,base_amt,tran_timestamp,is_sar\n"
    pos = hdr + b"T1,A,B,TRANSFER,9900,1440,1\nT2,B,C,TRANSFER,9800,1445,1\nT3,C,A,TRANSFER,9700,1450,1\nT4,X,Y,TRANSFER,5,1450,1\n"
    neg = pos.replace(b",1\n", b",0\n")
    a = AMLSimAdapter().load_from_bytes(pos, "p.csv")
    b = AMLSimAdapter().load_from_bytes(neg, "n.csv")
    assert a.ledger.transactions[0].is_ground_truth_fraud is True       # label IS stored here...
    assert b.ledger.transactions[0].is_ground_truth_fraud is False
    fa, fb = _engine_fingerprint(a.ledger), _engine_fingerprint(b.ledger)
    fa = re.sub(r'"scenario_name": "[^"]*"', "", fa)
    fb = re.sub(r'"scenario_name": "[^"]*"', "", fb)
    assert fa == fb                                                      # ...but never used


def test_v_label_tokens_never_read_by_detection_source():
    """Static guard: only graph_engine.build_graph may touch the legacy label fields."""
    root = PROJECT_ROOT
    scan = [os.path.join(root, "ghost_trace", n) for n in
            ("graph_engine.py", "investigators.py", "sar_generator.py")]
    scan += [os.path.join(root, "ghost_trace", "agents", f)
             for f in sorted(os.listdir(os.path.join(root, "ghost_trace", "agents")))
             if f.endswith(".py")]
    for path in scan:
        src = open(path, encoding="utf-8").read()
        assert "is_sar" not in src and "alert_id" not in src, path
    ge = open(os.path.join(root, "ghost_trace", "graph_engine.py"), encoding="utf-8").read()
    build_src = inspect.getsource(FinancialGraphEngine.build_graph)
    rest = ge.replace(build_src, "")
    for token in ("is_ground_truth", "pattern_type", "ground_truth_rings"):
        assert token not in rest, f"{token} is referenced outside build_graph (possible label leak)"
    for f in os.listdir(os.path.join(root, "ghost_trace", "agents")):
        if f.endswith(".py"):
            s = open(os.path.join(root, "ghost_trace", "agents", f), encoding="utf-8").read()
            for token in ("is_ground_truth", "ground_truth_rings"):
                assert token not in s, (f, token)


def test_v_unlabelled_file_gives_same_detections_as_labelled_file():
    nolabel_hdr = "tran_id,tran_timestamp,base_amt,tx_type,orig_acct,bene_acct"
    rows = [r.rsplit(",", 2)[0] for r in RING_UNLABELLED]
    with _csv(_txt(*rows, header=nolabel_hdr)) as p:
        a = load_amlsim_transactions(p)
    b = _load(*RING)
    assert a.success and a.labels == {}
    fa = re.sub(r'"scenario_name": "[^"]*"', "", _engine_fingerprint(a.ledger))
    fb = re.sub(r'"scenario_name": "[^"]*"', "", _engine_fingerprint(b.ledger))
    assert fa == fb


# ═════════════════════════════════════════════════════════════════════════════
# 7. Graph-engine compatibility
# ═════════════════════════════════════════════════════════════════════════════

def test_v_graph_nodes_and_edges_represent_accounts_and_transactions_exactly():
    rows = ["1,0,9900.5,TRANSFER,A,B,False,-1", "2,1,9800.25,TRANSFER,B,C,False,-1",
            "3,2,9700,TRANSFER,C,A,False,-1", "4,3,10,CASH-IN,A,B,False,-1",   # parallel A->B
            "5,4,77,PAYMENT,D,E,False,-1"]
    r = _load(*rows)
    eng = FinancialGraphEngine()
    g = eng.build_graph(r.ledger)
    assert set(g.nodes) == set(r.ledger.accounts) == {"A", "B", "C", "D", "E"}
    assert g.number_of_edges() == 5
    assert g.number_of_edges("A", "B") == 2
    edges = {d["tx_id"]: (u, v, d["amount"], d["timestamp"], d["channel"])
             for u, v, _, d in g.edges(keys=True, data=True)}
    for t in r.ledger.transactions:
        assert edges[t.tx_id] == (t.sender_id, t.receiver_id, t.amount, t.timestamp, t.channel)
    assert {k for _, _, k in g.edges(keys=True)} == {t.tx_id for t in r.ledger.transactions}
    assert len(g.get_edge_data("A", "B")) == 2                  # parallel transfers both kept
    assert g.has_edge("A", "B") and not g.has_edge("B", "D")


def test_v_unknown_account_attributes_do_not_feed_scoring_or_fake_infrastructure():
    r = _load(*RING_UNLABELLED)
    res = FinancialGraphEngine().run_investigation(r.ledger)
    assert res.total_accounts == 5 and res.total_transactions == 4
    assert res.detected_cycles
    d = res.detected_cycles[0].to_dict()
    assert d["shared_devices"] == [] and d["shared_device_count"] == 0
    assert d["has_invalid_timestamps"] is False
    for h in d["hops"]:
        assert h["device_id"] is None
    # a node's attributes are the engine's own 'unknown' placeholders
    g = FinancialGraphEngine().build_graph(r.ledger)
    for _, attrs in g.nodes(data=True):
        assert attrs["device_id"] == "DEV-UNKNOWN" and attrs["ip_address"] == "0.0.0.0"
        assert attrs["account_type"] == "unknown"


def test_v_detected_cycle_references_exact_source_rows():
    r = _load(*RING)
    res = FinancialGraphEngine().run_investigation(r.ledger)
    assert len(res.detected_cycles) == 1
    c = res.detected_cycles[0].to_dict()
    src = {t.tx_id: t for t in r.ledger.transactions}
    assert sorted(c["all_tx_ids"]) == ["1", "2", "3"]
    for h in c["hops"]:
        t = src[h["tx_id"]]
        assert (h["from_account"], h["to_account"], h["amount"], h["timestamp"]) == (
            t.sender_id, t.receiver_id, t.amount, t.timestamp)
    assert sorted(res.flagged_tx_ids) == ["1", "2", "3"]          # noise row '4' not flagged
    assert set(res.flagged_accounts) == {"A", "B", "C"}


def test_v_input_row_order_does_not_change_detection():
    shuffled = [RING_UNLABELLED[i] for i in (2, 3, 0, 1)]
    a = _load(*RING_UNLABELLED)
    b = _load(*shuffled)
    assert [t.tx_id for t in a.ledger.transactions] == [t.tx_id for t in b.ledger.transactions]
    assert _engine_fingerprint(a.ledger) == _engine_fingerprint(b.ledger)


def test_v_chronological_sort_is_stable_for_equal_steps():
    r = _load("1,5,10,T,A,B,False,-1", "2,1,10,T,B,C,False,-1", "3,1,10,T,C,D,False,-1")
    assert [t.tx_id for t in r.ledger.transactions] == ["2", "3", "1"]


def test_v_acyclic_labelled_chain_produces_no_detections():
    r = _load("1,0,9500,T,A,B,True,3", "2,1,9400,T,B,C,True,3", "3,2,9300,T,C,D,True,3")
    res = FinancialGraphEngine().run_investigation(r.ledger)
    assert res.detected_cycles == [] and res.flagged_cycles == [] and res.flagged_tx_ids == []


def test_v_self_loop_and_parallel_edges_do_not_crash_the_engine():
    r = _load("1,0,10,T,A,A,False,-1", "2,1,10,T,A,B,False,-1", "3,2,10,T,A,B,False,-1",
              "4,3,10,T,B,A,False,-1")
    assert r.success
    res = FinancialGraphEngine().run_investigation(r.ledger)
    assert res.total_transactions == 4 and res.total_accounts == 2


def test_v_medium_synthetic_file_runs_end_to_end_quickly():
    rows = [f"{i},{i // 5},{50 + i % 40},TRANSFER,N{i % 120},N{(i * 7 + 1) % 120},False,-1"
            for i in range(1, 801)]
    r = _load(*rows)
    assert r.success and r.rows_loaded == 800
    res = FinancialGraphEngine().run_investigation(r.ledger)
    assert res.total_transactions == 800


def test_v_full_agent_and_sar_pipeline_accepts_strict_ledger():
    r = _load(*RING)
    res = FinancialGraphEngine().run_investigation(r.ledger)
    rep = GhostTraceInvestigationOrchestrator().run_investigation(res, r.ledger)
    assert rep.overall_verdict and rep.overall_risk_score > 0.15
    cv = rep.citation_verification
    assert cv.is_valid is True
    assert len(cv.verified_devices) == 0                               # none fabricated
    text = json.dumps(rep.to_dict(), default=str)
    assert "Shared Infrastructure" not in text and "DEV-" not in text and "is_sar" not in text
    sar = SARGenerator().generate_sar(rep, res, r.ledger)
    md = sar.to_markdown()
    assert "A" in md and "is_sar" not in md and "alert_id" not in md


def test_v_negative_control_all_normal_traffic_is_not_escalated():
    rows = [f"{i},{i},{20 + i},TRANSFER,U{i},M{i % 3},False,-1" for i in range(1, 31)]
    r = _load(*rows)
    res = FinancialGraphEngine().run_investigation(r.ledger)
    assert res.flagged_cycles == []
    rep = GhostTraceInvestigationOrchestrator().run_investigation(res, r.ledger)
    assert rep.overall_verdict.startswith("LOW")


# ═════════════════════════════════════════════════════════════════════════════
# 8. Offline guarantee
# ═════════════════════════════════════════════════════════════════════════════

def test_v_no_network_needed_for_loader_and_engine():
    real_connect = socket.socket.connect

    def _blocked(self, *a, **k):
        raise AssertionError("network access attempted during an offline test")

    socket.socket.connect = _blocked
    try:
        r = _load(*RING)
        FinancialGraphEngine().run_investigation(r.ledger)
    finally:
        socket.socket.connect = real_connect
    assert r.success
