"""
Tests for the IBM AMLSim Adapter
Tests cover: schema detection, column mapping, missing values, timestamp
parsing, ground-truth label isolation, integration through graph engine,
error handling (missing file, invalid schema, empty file), and that all
existing synthetic-data tests are unaffected.
"""

import os
import sys
import math
import textwrap

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ghost_trace.amlsim_adapter import (
    AMLSimAdapter,
    detect_csv_format,
    validate_schema,
    list_amlsim_files,
    get_data_dir_instructions,
    MISSING_DEVICE_SENTINEL,
    MISSING_IP_SENTINEL,
)
from ghost_trace.graph_engine import FinancialGraphEngine
from ghost_trace.data_generator import SyntheticLedgerGenerator


# ─────────────────────────────────────────────────────────────────────────────
# Helper: build in-memory CSV content
# ─────────────────────────────────────────────────────────────────────────────

KAGGLE_HEADER = (
    "Timestamp,From Bank,Account,To Bank,Account.1,"
    "Amount Received,Receiving Currency,Amount Paid,Payment Currency,"
    "Payment Format,Is Laundering"
)

def _kaggle_csv(*rows: str) -> bytes:
    return (KAGGLE_HEADER + "\n" + "\n".join(rows) + "\n").encode("utf-8")


NATIVE_HEADER = "tran_id,orig_acct,bene_acct,tx_type,base_amt,tran_timestamp,is_sar"

def _native_csv(*rows: str) -> bytes:
    return (NATIVE_HEADER + "\n" + "\n".join(rows) + "\n").encode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Schema detection
# ─────────────────────────────────────────────────────────────────────────────

def test_detect_kaggle_format():
    headers = [
        "Timestamp", "From Bank", "Account", "To Bank", "Account.1",
        "Amount Received", "Receiving Currency", "Amount Paid",
        "Payment Currency", "Payment Format", "Is Laundering",
    ]
    assert detect_csv_format(headers) == "kaggle_aml", \
        "Kaggle AML format should be detected from Is Laundering + From Bank headers"


def test_detect_native_format():
    headers = ["tran_id", "orig_acct", "bene_acct", "tx_type", "base_amt", "tran_timestamp", "is_sar"]
    assert detect_csv_format(headers) == "amlsim_native", \
        "AMLSim native format should be detected from tran_id + orig_acct headers"


def test_detect_unknown_format():
    headers = ["col1", "col2", "col3"]
    assert detect_csv_format(headers) == "unknown"


def test_validate_schema_kaggle():
    headers = [
        "Timestamp", "From Bank", "Account", "To Bank", "Account.1",
        "Amount Received", "Receiving Currency", "Amount Paid",
        "Payment Currency", "Payment Format", "Is Laundering",
    ]
    ok, err = validate_schema(headers)
    assert ok, f"Kaggle schema should validate. Error: {err}"


def test_validate_schema_rejects_unknown():
    headers = ["step", "type", "amount", "nameOrig", "nameDest"]  # PaySim, not AMLSim
    ok, err = validate_schema(headers)
    assert not ok, "Unknown/PaySim schema should be rejected"
    assert "Unrecognised" in err


# ─────────────────────────────────────────────────────────────────────────────
# 2. Kaggle AML format loading
# ─────────────────────────────────────────────────────────────────────────────

def test_kaggle_basic_load():
    csv_bytes = _kaggle_csv(
        "2022/01/01 00:00,11,A001,22,B001,9500.0,US Dollar,9500.0,US Dollar,Wire,0",
        "2022/01/01 00:30,22,B001,33,C001,9400.0,US Dollar,9400.0,US Dollar,Wire,1",
    )
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(csv_bytes, filename="test.csv")

    assert result.success, f"Load should succeed. Error: {result.error}"
    assert result.detected_format == "kaggle_aml"
    assert result.rows_loaded == 2
    assert result.rows_skipped == 0
    assert result.ledger is not None

    txs = result.ledger.transactions
    assert len(txs) == 2

    # Sender account IDs should be prefixed with bank ID
    assert txs[0].sender_id == "B11-A001"
    assert txs[0].receiver_id == "B22-B001"
    assert txs[0].amount == 9500.0
    assert txs[0].channel == "wire_transfer"
    assert "2022-01-01" in txs[0].timestamp

    # Ground-truth labels should be stored on the transaction
    assert txs[0].is_ground_truth_fraud == False
    assert txs[1].is_ground_truth_fraud == True


def test_kaggle_accounts_built():
    csv_bytes = _kaggle_csv(
        "2022/01/01 00:00,11,A001,22,B001,9500.0,US Dollar,9500.0,US Dollar,Wire,0",
    )
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(csv_bytes, "test.csv")
    assert result.success

    accounts = result.ledger.accounts
    assert "B11-A001" in accounts
    assert "B22-B001" in accounts

    acc = accounts["B11-A001"]
    assert acc.device_id == MISSING_DEVICE_SENTINEL, \
        "Device ID must be UNSET sentinel, not fabricated"
    assert acc.ip_address == MISSING_IP_SENTINEL, \
        "IP must be UNSET sentinel, not fabricated"
    assert acc.kyc_status == "unverified"


def test_kaggle_ground_truth_label_present_on_transaction():
    """Ground truth label must be stored on tx.is_ground_truth_fraud (for eval).
    It must NOT be used as a detection input by the graph engine."""
    csv_bytes = _kaggle_csv(
        "2022/01/01 00:00,11,A001,22,B001,9500.0,US Dollar,9500.0,US Dollar,Wire,1",
    )
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(csv_bytes, "test.csv")
    assert result.success

    tx = result.ledger.transactions[0]
    assert tx.is_ground_truth_fraud is True, \
        "is_ground_truth_fraud should reflect source label for evaluation"
    # Pattern type must be amlsim_imported, NOT the internal fraud type names
    assert tx.pattern_type == "amlsim_imported"


# ─────────────────────────────────────────────────────────────────────────────
# 3. AMLSim native format loading
# ─────────────────────────────────────────────────────────────────────────────

def test_native_basic_load():
    csv_bytes = _native_csv(
        "TX001,ACC-100,ACC-200,TRANSFER,5000.00,1440,0",
        "TX002,ACC-200,ACC-300,TRANSFER,4900.00,1445,1",
    )
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(csv_bytes, "transactions.csv")

    assert result.success, f"Native load failed: {result.error}"
    assert result.detected_format == "amlsim_native"
    assert result.rows_loaded == 2

    txs = result.ledger.transactions
    assert txs[0].tx_id == "TX001"
    assert txs[0].sender_id == "ACC-100"
    assert txs[0].receiver_id == "ACC-200"
    assert txs[0].amount == 5000.00
    # Timestamp: step 1440 = 2022-01-01T00:00:00 + 1440 minutes = day 1
    assert "2022-01-02" in txs[0].timestamp

    assert txs[1].is_ground_truth_fraud == True


# ─────────────────────────────────────────────────────────────────────────────
# 4. Missing values handling
# ─────────────────────────────────────────────────────────────────────────────

def test_missing_amount_row_skipped():
    """Rows with missing/invalid amounts must be skipped, not crash."""
    csv_bytes = _kaggle_csv(
        "2022/01/01 00:00,11,A001,22,B001,,US Dollar,,US Dollar,Wire,0",   # empty amounts
        "2022/01/01 01:00,11,A002,22,B002,1000.0,US Dollar,1000.0,US Dollar,ACH,0",
    )
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(csv_bytes, "test.csv")

    assert result.success
    assert result.rows_loaded == 1
    assert result.rows_skipped == 1
    assert any("null account" in r.lower() or "unparseable" in r.lower()
               for r in result.skip_reasons), \
        "Skip reason should mention null account or unparseable amount"


def test_missing_account_id_row_skipped():
    """Rows with empty account IDs must be skipped."""
    csv_bytes = _kaggle_csv(
        "2022/01/01 00:00,11,,22,,9000.0,US Dollar,9000.0,US Dollar,Wire,0",  # empty acct IDs
        "2022/01/01 01:00,33,ACC-X,44,ACC-Y,500.0,US Dollar,500.0,US Dollar,ACH,0",
    )
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(csv_bytes, "test.csv")

    assert result.success
    assert result.rows_loaded == 1
    assert result.rows_skipped == 1


def test_missing_timestamp_does_not_crash():
    """Missing/empty timestamp should produce empty string, not crash."""
    csv_bytes = _kaggle_csv(
        ",11,A001,22,B001,9000.0,US Dollar,9000.0,US Dollar,Wire,0",  # empty Timestamp
    )
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(csv_bytes, "test.csv")

    assert result.success
    tx = result.ledger.transactions[0]
    assert tx.timestamp == "", "Missing timestamp should be empty string (not crash)"


def test_numeric_step_timestamp_converted():
    """Numeric step timestamps (AMLSim ticks) should be converted to ISO datetime."""
    csv_bytes = _native_csv(
        "TX001,A,B,TRANSFER,100.0,0,0",    # step 0 → 2022-01-01T00:00:00
        "TX002,B,C,TRANSFER,100.0,60,0",   # step 60 → 2022-01-01T01:00:00
    )
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(csv_bytes, "test.csv")

    assert result.success
    ts0 = result.ledger.transactions[0].timestamp
    ts1 = result.ledger.transactions[1].timestamp
    assert "2022-01-01" in ts0
    assert "T01:00:00" in ts1


# ─────────────────────────────────────────────────────────────────────────────
# 5. Error handling
# ─────────────────────────────────────────────────────────────────────────────

def test_missing_file_error():
    adapter = AMLSimAdapter()
    result = adapter.load_csv("nonexistent_path/does_not_exist.csv")

    assert not result.success
    assert result.error is not None
    assert "not found" in result.error.lower() or "File not found" in result.error


def test_invalid_schema_error():
    bad_csv = b"step,type,amount,nameOrig,nameDest,oldbalanceOrg\n1,PAYMENT,100,Alice,Bob,500\n"
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(bad_csv, "paysim.csv")

    assert not result.success
    assert result.error is not None
    assert "Unrecognised" in result.error


def test_empty_file_error():
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(b"", "empty.csv")

    assert not result.success
    assert result.error is not None
    assert "empty" in result.error.lower()


def test_header_only_file_error():
    """A CSV with header but no data rows should fail gracefully."""
    csv_bytes = KAGGLE_HEADER.encode("utf-8") + b"\n"
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(csv_bytes, "header_only.csv")

    assert not result.success
    assert result.error is not None
    assert "valid transactions" in result.error.lower() or "no valid" in result.error.lower()


def test_non_csv_file_extension_rejected():
    """A .xlsx extension on a non-existent path should fail (not found or unsupported format)."""
    adapter = AMLSimAdapter()
    result = adapter.load_csv("data/amlsim/file.xlsx")

    assert not result.success
    # Either "not found" or "unsupported file format" — both are valid honest errors
    assert result.error is not None
    assert ("not found" in result.error.lower() or
            "unsupported" in result.error.lower() or
            ".csv" in result.error)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Row cap / max_rows
# ─────────────────────────────────────────────────────────────────────────────

def test_max_rows_limit():
    """Adapter should load at most max_rows rows and warn about the rest."""
    rows = [
        f"2022/01/01 {h:02d}:00,11,ACC{i},22,ACC{i+1},1000.0,US Dollar,1000.0,US Dollar,ACH,0"
        for i, h in enumerate(range(20))
    ]
    csv_bytes = _kaggle_csv(*rows)
    adapter = AMLSimAdapter(max_rows=5)
    result = adapter.load_from_bytes(csv_bytes, "big.csv")

    assert result.success
    assert result.rows_loaded <= 5
    assert any("limit" in w.lower() for w in result.warnings), \
        "Should warn that row limit was reached"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Integration: AMLSim data → Graph Engine
# ─────────────────────────────────────────────────────────────────────────────

def test_amlsim_ledger_runs_through_graph_engine():
    """
    AMLSim loaded data must flow through FinancialGraphEngine without errors.
    A manually constructed circular ring (3-hop cycle meeting velocity & device
    criteria) should be detected.
    Note: AMLSim CSVs have no device_id, so shared-device scoring = 0.
    We inject amounts in the structuring band and rapid timing to trigger detection.
    """
    # Build a 3-hop circular ring in structuring band with < 2hr total duration
    csv_bytes = _kaggle_csv(
        "2022/01/01 00:00,11,RING1,22,RING2,9800.0,US Dollar,9800.0,US Dollar,Wire,1",
        "2022/01/01 00:30,22,RING2,33,RING3,9700.0,US Dollar,9700.0,US Dollar,Wire,1",
        "2022/01/01 01:00,33,RING3,11,RING1,9600.0,US Dollar,9600.0,US Dollar,Wire,1",
        # Some background normal noise
        "2022/01/01 02:00,44,NORM1,55,NORM2,250.0,US Dollar,250.0,US Dollar,ACH,0",
    )
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(csv_bytes, "ring_test.csv")
    assert result.success, f"Load failed: {result.error}"

    ledger = result.ledger
    engine = FinancialGraphEngine()
    graph_result = engine.run_investigation(ledger)

    # Engine must not crash on AMLSim data
    assert graph_result is not None
    assert graph_result.total_transactions == 4
    # Accounts: B11-RING1, B22-RING2, B33-RING3 (ring) + B44-NORM1, B55-NORM2 (noise) = 5
    assert graph_result.total_accounts == 5

    # The 3-hop ring should be detected as a cycle
    assert len(graph_result.detected_cycles) >= 1, \
        "3-hop structuring ring should be detected as a closed cycle"

    # Ground-truth labels must NOT contaminate detection scores
    # (The engine sees tx.is_ground_truth_fraud but the scoring rules in
    #  graph_engine.py never reference that field.)
    for cycle in graph_result.detected_cycles:
        for hop in cycle.hops:
            # Verify the engine computed device_id from the transaction, not from the label
            assert hop.device_id == MISSING_DEVICE_SENTINEL or hop.device_id is None or hop.device_id == ""


def test_amlsim_acyclic_no_false_positives():
    """
    AMLSim data with no cycles should not produce flagged suspicious cycles.
    """
    csv_bytes = _kaggle_csv(
        "2022/01/01 00:00,11,A,22,B,9500.0,US Dollar,9500.0,US Dollar,Wire,1",
        "2022/01/01 01:00,22,B,33,C,9400.0,US Dollar,9400.0,US Dollar,Wire,1",
        "2022/01/01 02:00,33,C,44,D,9300.0,US Dollar,9300.0,US Dollar,Wire,1",
    )
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(csv_bytes, "acyclic_test.csv")
    assert result.success

    engine = FinancialGraphEngine()
    graph_result = engine.run_investigation(result.ledger)

    # A → B → C → D is acyclic, no false positive cycles
    assert graph_result.detected_cycles == [], \
        "Acyclic chain must not produce false-positive cycle detections"


def test_ground_truth_labels_separated_from_detection():
    """
    The ground_truth_rings entry in the LedgerData must accurately list
    labelled fraud transactions, but these IDs must not appear in
    graph_result.flagged_tx_ids unless the engine independently detects them.
    """
    # Non-cyclic transactions labeled as fraud (SAR) in source data
    csv_bytes = _kaggle_csv(
        "2022/01/01 00:00,11,X1,22,X2,100.0,US Dollar,100.0,US Dollar,ACH,1",
        "2022/01/01 01:00,33,X3,44,X4,200.0,US Dollar,200.0,US Dollar,ACH,1",
    )
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(csv_bytes, "label_test.csv")
    assert result.success

    ledger = result.ledger
    # Ground truth rings should be populated
    assert len(ledger.ground_truth_rings) == 1
    ring = ledger.ground_truth_rings[0]
    assert ring["is_fraud"] is True
    assert len(ring["tx_ids"]) == 2

    # Run engine
    engine = FinancialGraphEngine()
    graph_result = engine.run_investigation(ledger)

    # No cycles exist → engine should not flag anything
    assert len(graph_result.flagged_cycles) == 0, \
        "Non-cyclic fraud-labelled transactions should NOT be flagged by cycle engine"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Payment format normalisation
# ─────────────────────────────────────────────────────────────────────────────

def test_payment_format_normalisation():
    csv_bytes = _kaggle_csv(
        "2022/01/01 00:00,11,A,22,B,1000.0,US Dollar,1000.0,US Dollar,Cheque,0",
        "2022/01/01 01:00,33,C,44,D,2000.0,US Dollar,2000.0,US Dollar,Bitcoin,0",
        "2022/01/01 02:00,55,E,66,F,3000.0,US Dollar,3000.0,US Dollar,SWIFT,0",
    )
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(csv_bytes, "channel_test.csv")
    assert result.success

    channels = {tx.tx_id: tx.channel for tx in result.ledger.transactions}
    channel_values = list(channels.values())
    assert "cheque" in channel_values
    assert "crypto_ramp" in channel_values
    assert "swift" in channel_values


# ─────────────────────────────────────────────────────────────────────────────
# 9. Utility functions
# ─────────────────────────────────────────────────────────────────────────────

def test_list_amlsim_files_nonexistent_dir():
    """Should return empty list for non-existent directory, not crash."""
    files = list_amlsim_files("nonexistent_dir_xyz_123")
    assert files == []


def test_get_data_dir_instructions_contains_key_info():
    instructions = get_data_dir_instructions()
    assert "data/amlsim" in instructions
    assert "kaggle" in instructions.lower()
    assert "HI-Small_Trans.csv" in instructions
    assert "Is Laundering" in instructions


# ─────────────────────────────────────────────────────────────────────────────
# 10. Existing synthetic data pipeline unaffected
# ─────────────────────────────────────────────────────────────────────────────

def test_synthetic_pipeline_unaffected_by_amlsim_import():
    """
    Importing the AMLSim adapter must not break the synthetic data pipeline.
    The existing SyntheticLedgerGenerator + FinancialGraphEngine must still work.
    """
    gen = SyntheticLedgerGenerator(seed=42)
    ledger = gen.generate_scenario("vampire_ring")

    engine = FinancialGraphEngine()
    result = engine.run_investigation(ledger)

    assert result.total_transactions > 0
    assert len(result.flagged_cycles) >= 1, \
        "Synthetic vampire ring must still be detected after AMLSim adapter is imported"


def test_load_summary_is_human_readable():
    csv_bytes = _kaggle_csv(
        "2022/01/01 00:00,11,A001,22,B001,9500.0,US Dollar,9500.0,US Dollar,Wire,0",
    )
    adapter = AMLSimAdapter()
    result = adapter.load_from_bytes(csv_bytes, "test.csv")
    summary = result.load_summary

    assert "Format:" in summary
    assert "Rows loaded:" in summary
    assert isinstance(summary, str)


# ═════════════════════════════════════════════════════════════════════════════
# STRICT LOADER: load_amlsim_transactions()  (tiny, locally generated fixtures)
# Schema verified against IBM/AMLSim paramFiles/schema.json "transaction":
#   tran_id, orig_acct, bene_acct, tx_type, base_amt, tran_timestamp, is_sar, alert_id
# NOTE: no real IBM AMLSim dataset is used or required by any test here.
# ═════════════════════════════════════════════════════════════════════════════

import json
import tempfile
from contextlib import contextmanager
from datetime import datetime

from ghost_trace.amlsim_adapter import (
    load_amlsim_transactions,
    read_base_date_from_conf,
    AMLSimTimeConfig,
    AMLSimEvalLabel,
    AMLSIM_REQUIRED_COLUMNS,
    ABSOLUTE_MAX_ROWS,
    ORDINAL_SURROGATE_EPOCH,
)
from ghost_trace.graph_engine import safe_parse_datetime
from ghost_trace.data_generator import Account

STRICT_HEADER = "tran_id,orig_acct,bene_acct,tx_type,base_amt,tran_timestamp,is_sar,alert_id"


@contextmanager
def _csv_file(text, name="transactions.csv", raw_bytes=None):
    """Write a tiny CSV into a temp dir; yield its path; always clean up."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, name)
        if raw_bytes is not None:
            with open(p, "wb") as f:
                f.write(raw_bytes)
        else:
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        yield p


def _strict_text(*rows, header=STRICT_HEADER):
    return header + "\n" + "\n".join(rows) + "\n"


RING_ROWS_LABELLED = [
    "1,A,B,TRANSFER,9900.00,0,True,5",
    "2,B,C,TRANSFER,9800.00,1,True,5",
    "3,C,A,TRANSFER,9700.00,2,True,5",
    "4,X,Y,TRANSFER,50.00,2,False,-1",
]
RING_ROWS_UNLABELLED = [
    "1,A,B,TRANSFER,9900.00,0,False,-1",
    "2,B,C,TRANSFER,9800.00,1,False,-1",
    "3,C,A,TRANSFER,9700.00,2,False,-1",
    "4,X,Y,TRANSFER,50.00,2,False,-1",
]


# ── Field mapping ────────────────────────────────────────────────────────────

def test_strict_maps_verified_fields_verbatim():
    text = _strict_text(
        "00042,ACC_7,ACC_9,TRANSFER,123.45,5,False,-1",
        "00043,ACC_9,ACC_7,CASH-IN,10.5,6,False,-1",
    )
    with _csv_file(text) as p:
        r = load_amlsim_transactions(p)
    assert r.success, r.error
    txs = {t.tx_id: t for t in r.ledger.transactions}
    t = txs["00042"]                      # leading zeros preserved: ids stay strings
    assert (t.sender_id, t.receiver_id) == ("ACC_7", "ACC_9")   # no bank prefixing
    assert t.amount == 123.45
    assert t.channel == "TRANSFER"        # tx_type preserved, not re-mapped
    assert txs["00043"].channel == "CASH-IN"
    assert r.raw_timestamps["00042"] == "5"   # original cell preserved
    assert r.detected_format == "amlsim_native"
    assert r.rows_loaded == 2 and r.rows_skipped == 0


def test_strict_missing_attributes_are_not_fabricated():
    with _csv_file(_strict_text("1,A,B,TRANSFER,100,0,False,-1")) as p:
        r = load_amlsim_transactions(p)
    t = r.ledger.transactions[0]
    assert t.device_id is None and t.ip_address is None and t.memo == ""
    acc = r.ledger.accounts["A"]
    assert acc.name == "A"
    assert acc.account_type == "unknown" and acc.kyc_status == "unknown"
    assert acc.country == "UNKNOWN" and acc.created_at == ""
    # None of the Account dataclass defaults (which would be invented data):
    defaults = Account("x", "x", "x", "x")
    assert acc.device_id != defaults.device_id
    assert acc.ip_address != defaults.ip_address
    assert acc.initial_balance != defaults.initial_balance
    assert acc.country != defaults.country
    assert acc.created_at != defaults.created_at


def test_strict_header_case_order_and_extra_columns_tolerated():
    header = "Extra,BASE_AMT,Tran_Timestamp,Bene_Acct,Orig_Acct,TX_TYPE,Tran_ID"
    text = _strict_text("zzz,250.0,7,B,A,TRANSFER,T1", header=header)
    with _csv_file(text) as p:
        r = load_amlsim_transactions(p)
    assert r.success, r.error
    t = r.ledger.transactions[0]
    assert (t.tx_id, t.sender_id, t.receiver_id, t.amount) == ("T1", "A", "B", 250.0)
    assert r.label_columns_present == ()      # optional label columns may be absent


def test_strict_blank_tx_type_becomes_unknown_not_wire():
    with _csv_file(_strict_text("1,A,B,,100,0,False,-1")) as p:
        r = load_amlsim_transactions(p)
    assert r.ledger.transactions[0].channel == "unknown"
    assert any("blank tx_type" in w for w in r.warnings)


# ── Files, schema and argument errors ────────────────────────────────────────

def test_strict_missing_file_directory_and_extension_errors():
    r = load_amlsim_transactions(os.path.join(tempfile.gettempdir(), "nope_does_not_exist.csv"))
    assert not r.success and r.ledger is None and "File not found" in r.error
    with tempfile.TemporaryDirectory() as d:
        r = load_amlsim_transactions(d)
        assert not r.success and "directory" in r.error
    with _csv_file("a,b\n1,2\n", name="data.txt") as p:
        r = load_amlsim_transactions(p)
        assert not r.success and ".csv" in r.error


def test_strict_empty_and_header_only_files():
    with _csv_file("", name="empty.csv") as p:
        r = load_amlsim_transactions(p)
        assert not r.success and "empty" in r.error.lower()
    with _csv_file(STRICT_HEADER + "\n") as p:
        r = load_amlsim_transactions(p)
        assert not r.success and "no data rows" in r.error


def test_strict_missing_required_columns_named_in_error():
    header = "tran_id,orig_acct,bene_acct,tx_type"          # no base_amt / tran_timestamp
    with _csv_file(_strict_text("1,A,B,TRANSFER", header=header)) as p:
        r = load_amlsim_transactions(p)
    assert not r.success
    assert "base_amt" in r.error and "tran_timestamp" in r.error
    assert "Missing required" in r.error


def test_strict_rejects_official_20k_sample_schema_clearly():
    """IBM/AMLSim sample/*.tgz ship sourceNodeId,targetNodeId,value,time (no ids/labels)."""
    with _csv_file("sourceNodeId,targetNodeId,value,time\n1,2,10.0,1\n") as p:
        r = load_amlsim_transactions(p)
    assert not r.success
    assert "Missing required" in r.error and "sourceNodeId" in r.error


def test_strict_duplicate_header_names_rejected():
    header = "tran_id,orig_acct,bene_acct,tx_type,base_amt,tran_timestamp,base_amt"
    with _csv_file(_strict_text("1,A,B,T,1,0,2", header=header)) as p:
        r = load_amlsim_transactions(p)
    assert not r.success and "duplicate column" in r.error


def test_strict_invalid_utf8_gives_clear_error():
    raw = (STRICT_HEADER + "\n1,A,B,T,1,0,False,-1\n").encode("utf-8") + b"\xff\xfe\n"
    with _csv_file("", raw_bytes=raw) as p:
        r = load_amlsim_transactions(p)
    assert not r.success and "decode" in r.error.lower()


def test_strict_argument_validation():
    with _csv_file(_strict_text("1,A,B,T,1,0,False,-1")) as p:
        for bad in (0, -5, True, 2.5, "10"):
            r = load_amlsim_transactions(p, max_rows=bad)
            assert not r.success and "max_rows" in r.error, bad
        r = load_amlsim_transactions(p, max_rows=ABSOLUTE_MAX_ROWS + 1)
        assert not r.success and "hard limit" in r.error
        r = load_amlsim_transactions(p, skip_rows=-1)
        assert not r.success and "skip_rows" in r.error


# ── Malformed rows / invalid numbers ─────────────────────────────────────────

def test_strict_malformed_rows_skipped_with_itemised_reasons():
    text = _strict_text(
        "1,A,B,TRANSFER,100,0,False,-1",            # good
        "2,A,B,TRANSFER,100,0,False",               # wrong field count
        ",A,B,TRANSFER,100,0,False,-1",             # empty tran_id
        "4,,B,TRANSFER,100,0,False,-1",             # empty orig_acct
        "5,A,,TRANSFER,100,0,False,-1",             # empty bene_acct
        "6,A,B,TRANSFER,abc,0,False,-1",            # non-numeric amount
        "7,A,B,TRANSFER,-5,0,False,-1",             # negative amount
        "8,A,B,TRANSFER,0,0,False,-1",              # zero amount
        "9,A,B,TRANSFER,nan,0,False,-1",            # NaN amount
        "10,A,B,TRANSFER,inf,0,False,-1",           # infinite amount
        "11,A,B,TRANSFER,100,not-a-time,False,-1",  # unparseable timestamp
        "1,C,D,TRANSFER,100,0,False,-1",            # duplicate tran_id
    )
    with _csv_file(text) as p:
        r = load_amlsim_transactions(p)
    assert r.success
    assert r.rows_loaded == 1 and r.rows_skipped == 11 and r.rows_attempted == 12
    joined = " | ".join(r.skip_reasons)
    for needle in ("expected 8 fields", "empty tran_id", "empty orig_acct", "empty bene_acct",
                   "non-numeric", "must be > 0", "non-finite", "unparseable tran_timestamp",
                   "duplicate tran_id"):
        assert needle in joined, f"missing reason: {needle}\n{joined}"
    assert all(reason.startswith("Data row ") for reason in r.skip_reasons)


def test_strict_mode_fails_on_first_malformed_row():
    text = _strict_text("1,A,B,T,100,0,False,-1", "2,A,B,T,oops,0,False,-1", "3,A,B,T,100,0,False,-1")
    with _csv_file(text) as p:
        r = load_amlsim_transactions(p, strict=True)
    assert not r.success and r.ledger is None
    assert "Strict mode" in r.error and "non-numeric" in r.error


def test_strict_all_rows_invalid_is_an_error():
    with _csv_file(_strict_text("1,A,B,T,oops,0,False,-1", "2,A,B,T,-1,0,False,-1")) as p:
        r = load_amlsim_transactions(p)
    assert not r.success and "No valid transactions" in r.error
    assert r.rows_skipped == 2


def test_strict_blank_lines_ignored_not_counted_as_malformed():
    text = STRICT_HEADER + "\n\n1,A,B,T,100,0,False,-1\n\n   ,,,,,,,\n2,B,A,T,100,1,False,-1\n"
    with _csv_file(text) as p:
        r = load_amlsim_transactions(p)
    assert r.success and r.rows_loaded == 2 and r.rows_skipped == 0


# ── Timestamp handling ───────────────────────────────────────────────────────

def test_step_timestamps_without_config_use_flagged_surrogate_clock():
    text = _strict_text("1,A,B,T,100,0,False,-1", "2,B,C,T,100,3,False,-1")
    with _csv_file(text) as p:
        r = load_amlsim_transactions(p)
    assert r.success and r.time_basis == "ordinal_surrogate"
    assert any("surrogate" in w and "not" in w for w in r.warnings)
    ts = {t.tx_id: t.timestamp for t in r.ledger.transactions}
    assert ts["1"] == ORDINAL_SURROGATE_EPOCH.isoformat()
    d = safe_parse_datetime(ts["2"]) - safe_parse_datetime(ts["1"])
    assert d.days == 3                        # ordering and spacing follow the step values
    assert r.raw_timestamps == {"1": "0", "2": "3"}   # originals untouched
    assert safe_parse_datetime(ts["1"]).year == 2000   # NOT the old invented 2022-01-01 base
    assert datetime.fromisoformat(ts["1"]).timestamp() > 0   # safe on Windows


def test_step_timestamps_with_confirmed_config_become_calendar():
    text = _strict_text("1,A,B,T,100,0,False,-1", "2,B,C,T,100,3,False,-1", "3,C,D,T,100,36,False,-1")
    cfg = AMLSimTimeConfig(base_date="2017-01-01", step_unit="day")
    with _csv_file(text) as p:
        r = load_amlsim_transactions(p, time_config=cfg)
    assert r.time_basis == "configured_calendar"
    ts = {t.tx_id: t.timestamp for t in r.ledger.transactions}
    assert ts["1"] == "2017-01-01T00:00:00" and ts["2"] == "2017-01-04T00:00:00"
    assert ts["3"] == "2017-02-06T00:00:00"
    assert not any("surrogate" in w for w in r.warnings)
    cfg_h = AMLSimTimeConfig(base_date="2017-01-01", step_unit="hour")
    with _csv_file(text) as p:
        r2 = load_amlsim_transactions(p, time_config=cfg_h)
    assert {t.tx_id: t.timestamp for t in r2.ledger.transactions}["3"] == "2017-01-02T12:00:00"


def test_time_config_validation():
    with _csv_file(_strict_text("1,A,B,T,100,0,False,-1")) as p:
        for cfg, needle in (
            (AMLSimTimeConfig(base_date="2017-01-01"), "BOTH"),
            (AMLSimTimeConfig(step_unit="day"), "BOTH"),
            (AMLSimTimeConfig(base_date="2017-01-01", step_unit="week"), "step_unit"),
            (AMLSimTimeConfig(base_date="garbage", step_unit="day"), "base_date"),
        ):
            r = load_amlsim_transactions(p, time_config=cfg)
            assert not r.success and needle in r.error, (cfg, r.error)


def test_calendar_values_in_file_are_used_as_is_and_normalised_to_utc_naive():
    text = _strict_text(
        "1,A,B,T,100,2017-01-01T00:00:00Z,False,-1",
        "2,B,C,T,100,2017-01-01T05:30:00+05:30,False,-1",
        "3,C,D,T,100,2017-01-02,False,-1",
    )
    cfg = AMLSimTimeConfig(base_date="1999-01-01", step_unit="day")
    with _csv_file(text) as p:
        r = load_amlsim_transactions(p, time_config=cfg)
    assert r.success and r.time_basis == "calendar_in_file"
    ts = {t.tx_id: t.timestamp for t in r.ledger.transactions}
    assert ts["1"] == "2017-01-01T00:00:00" and ts["2"] == "2017-01-01T00:00:00"
    assert ts["3"] == "2017-01-02T00:00:00"
    assert all("+" not in v and not v.endswith("Z") for v in ts.values())
    assert any("time_config was ignored" in w for w in r.warnings)


def test_mixed_step_and_calendar_timestamps_rejected_per_row():
    text = _strict_text("1,A,B,T,100,5,False,-1", "2,B,C,T,100,2017-01-01,False,-1")
    with _csv_file(text) as p:
        r = load_amlsim_transactions(p)
    assert r.success and r.rows_loaded == 1 and r.rows_skipped == 1
    assert "mixed kinds" in r.skip_reasons[0]


def test_absurd_step_value_is_a_malformed_row_not_a_crash():
    text = _strict_text("1,A,B,T,100,1,False,-1", "2,B,C,T,100," + "9" * 30 + ",False,-1")
    with _csv_file(text) as p:
        r = load_amlsim_transactions(p)
    assert r.success and r.rows_loaded == 1 and "out of range" in r.skip_reasons[0]


def test_loaded_timestamps_never_empty_so_engine_cannot_substitute_now():
    with _csv_file(_strict_text(*RING_ROWS_UNLABELLED)) as p:
        r = load_amlsim_transactions(p)
    assert all(t.timestamp and safe_parse_datetime(t.timestamp) for t in r.ledger.transactions)
    res = FinancialGraphEngine().run_investigation(r.ledger)
    assert res.detected_cycles, "ring should be found"
    assert all(not c.to_dict()["has_invalid_timestamps"] for c in res.detected_cycles)


def test_read_base_date_from_conf():
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "conf.json")
        with open(good, "w") as f:
            json.dump({"general": {"base_date": "2017-01-01", "total_steps": 720}}, f)
        assert read_base_date_from_conf(good) == "2017-01-01"
        nokey = os.path.join(d, "nokey.json")
        with open(nokey, "w") as f:
            json.dump({"general": {}}, f)
        badjson = os.path.join(d, "bad.json")
        with open(badjson, "w") as f:
            f.write("{not json")
        baddate = os.path.join(d, "baddate.json")
        with open(baddate, "w") as f:
            json.dump({"general": {"base_date": "someday"}}, f)
        for path, needle in ((os.path.join(d, "absent.json"), "not found"),
                             (nokey, "base_date"), (badjson, "Cannot read"),
                             (baddate, "not a valid date")):
            try:
                read_base_date_from_conf(path)
                assert False, f"expected ValueError for {path}"
            except ValueError as exc:
                assert needle in str(exc), str(exc)


# ── Row limits / chunking / memory behaviour ─────────────────────────────────

def test_row_limit_truncation_and_skip_rows_chunking():
    rows = [f"{i},A{i},B{i},T,100,{i},False,-1" for i in range(1, 11)]   # 10 rows
    with _csv_file(_strict_text(*rows)) as p:
        c1 = load_amlsim_transactions(p, max_rows=4)
        c2 = load_amlsim_transactions(p, max_rows=4, skip_rows=4)
        c3 = load_amlsim_transactions(p, max_rows=4, skip_rows=8)
        beyond = load_amlsim_transactions(p, max_rows=4, skip_rows=50)
    ids = lambda r: [t.tx_id for t in r.ledger.transactions]
    assert ids(c1) == ["1", "2", "3", "4"]        # first data row NOT swallowed
    assert c1.truncated and any("Row limit reached" in w for w in c1.warnings)
    assert ids(c2) == ["5", "6", "7", "8"] and c2.truncated
    assert ids(c3) == ["9", "10"] and not c3.truncated
    assert not beyond.success and "beyond the end" in beyond.error


def test_loader_streams_and_stops_at_row_limit():
    """Invalid bytes far past the limit are never reached => file is not read whole."""
    head = STRICT_HEADER + "\n" + "".join(
        f"{i},A{i},B{i},T,100,{i},False,-1\n" for i in range(1, 6001))
    raw = head.encode("utf-8") + b"\xff\xfe\xfd bad tail\n"
    with _csv_file("", raw_bytes=raw) as p:
        r = load_amlsim_transactions(p, max_rows=50)
    assert r.success and r.rows_loaded == 50 and r.truncated


# ── Ground-truth label separation ────────────────────────────────────────────

def test_labels_are_kept_out_of_transactions_and_ledger():
    with _csv_file(_strict_text(*RING_ROWS_LABELLED)) as p:
        r = load_amlsim_transactions(p)
    assert r.label_columns_present == ("is_sar", "alert_id")
    assert r.labels["1"] == AMLSimEvalLabel(is_sar=True, alert_id="5")
    assert r.labels["4"] == AMLSimEvalLabel(is_sar=False, alert_id="-1")   # alert_id verbatim
    assert all(t.is_ground_truth_fraud is False for t in r.ledger.transactions)
    assert r.ledger.ground_truth_rings == []
    blob = json.dumps([t.to_dict() for t in r.ledger.transactions], default=str)
    assert "is_sar" not in blob and "alert_id" not in blob
    assert "is_sar" not in r.ledger.description.split("(")[0]  # description cites a count only


def test_missing_label_columns_still_loads_with_empty_labels():
    header = "tran_id,orig_acct,bene_acct,tx_type,base_amt,tran_timestamp"
    with _csv_file(_strict_text("1,A,B,T,100,0", header=header)) as p:
        r = load_amlsim_transactions(p)
    assert r.success and r.labels == {} and r.label_columns_present == ()
    assert any("No is_sar / alert_id" in w for w in r.warnings)


def test_malformed_label_never_changes_which_rows_load():
    text = _strict_text("1,A,B,T,100,0,maybe,7", "2,B,A,T,100,1,True,", "3,C,D,T,100,2,,-1")
    with _csv_file(text) as p:
        r = load_amlsim_transactions(p)
    assert r.rows_loaded == 3 and r.rows_skipped == 0
    assert r.labels["1"] == AMLSimEvalLabel(is_sar=None, alert_id="7")
    assert r.labels["2"] == AMLSimEvalLabel(is_sar=True, alert_id=None)
    assert r.labels["3"].is_sar is None
    assert any("not recognisable booleans" in w for w in r.warnings)


def test_detection_output_identical_whether_or_not_rows_are_labelled_sar():
    """Flip every is_sar/alert_id value: engine inputs and outputs must not change."""
    with _csv_file(_strict_text(*RING_ROWS_LABELLED)) as p1:
        a = load_amlsim_transactions(p1)
    with _csv_file(_strict_text(*RING_ROWS_UNLABELLED)) as p2:
        b = load_amlsim_transactions(p2)
    assert [t.to_dict() for t in a.ledger.transactions] == [t.to_dict() for t in b.ledger.transactions]
    assert a.labels != b.labels                       # labels DO differ ...
    ra = FinancialGraphEngine().run_investigation(a.ledger)
    rb = FinancialGraphEngine().run_investigation(b.ledger)
    assert sorted(ra.flagged_tx_ids) == sorted(rb.flagged_tx_ids)    # ... detection does not
    assert [c.to_dict() for c in ra.detected_cycles] == [c.to_dict() for c in rb.detected_cycles]
    assert ra.flagged_tx_ids, "sanity: the ring is flagged from structure, not labels"


def test_unlabelled_ring_is_still_found_and_labelled_noise_is_not_flagged():
    """Labels cannot create detections: label an acyclic chain as SAR -> nothing flagged."""
    rows = [
        "1,A,B,TRANSFER,9500,0,True,3",
        "2,B,C,TRANSFER,9400,1,True,3",
        "3,C,D,TRANSFER,9300,2,True,3",
    ]
    with _csv_file(_strict_text(*rows)) as p:
        r = load_amlsim_transactions(p)
    res = FinancialGraphEngine().run_investigation(r.ledger)
    assert res.flagged_tx_ids == [] or len(res.flagged_tx_ids) == 0
    assert res.flagged_cycles == []
    assert sum(1 for lb in r.labels.values() if lb.is_sar) == 3


def test_strict_ledger_creates_no_fabricated_shared_infrastructure():
    with _csv_file(_strict_text(*RING_ROWS_UNLABELLED)) as p:
        r = load_amlsim_transactions(p)
    res = FinancialGraphEngine().run_investigation(r.ledger)
    assert res.detected_cycles
    for c in res.detected_cycles:
        d = c.to_dict()
        assert d["shared_devices"] == [] and d["shared_device_count"] == 0
        assert not any("Shared Infrastructure" in e for e in d["explanation_points"])


def test_legacy_adapter_no_longer_fabricates_shared_device_evidence():
    """Regression: the old 'UNSET-NO-DEVICE-DATA' sentinel made every account 'share' a device."""
    assert MISSING_DEVICE_SENTINEL in ("DEV-UNKNOWN", "DEV-DEFAULT", "None", "")
    csv_bytes = _native_csv(
        "T1,A,B,TRANSFER,9900,1440,1", "T2,B,C,TRANSFER,9800,1445,1", "T3,C,A,TRANSFER,9700,1450,1")
    res = AMLSimAdapter().load_from_bytes(csv_bytes, "ring.csv")
    out = FinancialGraphEngine().run_investigation(res.ledger)
    assert out.detected_cycles
    for c in out.detected_cycles:
        d = c.to_dict()
        assert d["shared_devices"] == []
        assert not any("Shared Infrastructure" in e for e in d["explanation_points"])


def test_strict_required_columns_constant_matches_verified_schema():
    assert AMLSIM_REQUIRED_COLUMNS == (
        "tran_id", "orig_acct", "bene_acct", "tx_type", "base_amt", "tran_timestamp")
