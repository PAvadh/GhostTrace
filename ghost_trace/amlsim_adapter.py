"""
IBM AMLSim Dataset Adapter for GhostTrace
==========================================
Maps IBM AMLSim / Kaggle AML Transaction CSV files into GhostTrace's
existing LedgerData / Transaction / Account schema without fabricating
missing fields or allowing ground-truth labels to influence detection.

Supported CSV formats
---------------------
Format A – IBM Kaggle AML (HI-Small_Trans.csv / LI-Small_Trans.csv)
    Columns: Timestamp, From Bank, Account, To Bank, Account.1,
             Amount Received, Receiving Currency, Amount Paid,
             Payment Currency, Payment Format, Is Laundering

Format B – AMLSim native log (transactions.csv)
    Columns: tran_id, orig_acct, bene_acct, tx_type,
             base_amt, tran_timestamp, is_sar

Format C – Generic with flexible column detection

Two loaders live in this module
-------------------------------
* AMLSimAdapter (legacy, used by app.py today): in-memory, tolerant, keeps
  labels on Transaction.is_ground_truth_fraud and converts integer steps to
  minutes from 2022-01-01. Retained unchanged for backward compatibility.
* load_amlsim_transactions() (strict, streaming, path-based): AMLSim-native
  schema only (verified against IBM/AMLSim paramFiles/schema.json). Keeps
  is_sar / alert_id OUT of Transaction objects (result.labels only), never
  guesses calendar dates for simulation steps, never fabricates device /
  IP / KYC data. See that function's docstring.

Design principles
-----------------
- Original identifiers are preserved verbatim (no renaming).
- is_ground_truth_fraud is populated from Is Laundering / is_sar
  but is NEVER passed to the graph engine for scoring.
- Missing device_id / ip_address / memo are set to GhostTrace's own
  "no data" markers (DEV-UNKNOWN / 0.0.0.0 / "") which the engine excludes
  from shared-infrastructure analysis.
- Timestamps that cannot be parsed are stored as empty strings and
  flagged so the graph engine's safe_parse_datetime handles them.
- Rows with null account IDs or unparseable amounts are skipped with
  a logged warning (no silent data corruption).
- Max rows limit protects against accidentally loading 500k-row files
  into the dashboard; default cap is 5,000 rows.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from ghost_trace.data_generator import Account, LedgerData, Transaction


# ──────────────────────────────────────────────────────────────────────────────
# Public constants – document exactly which column names each format uses
# ──────────────────────────────────────────────────────────────────────────────

# Format A: IBM Kaggle HI/LI small dataset (column order matters for Account.1)
KAGGLE_AML_COLUMNS = [
    "Timestamp",
    "From Bank",
    "Account",          # sender account
    "To Bank",
    "Account.1",        # receiver account (pandas auto-renames duplicate)
    "Amount Received",
    "Receiving Currency",
    "Amount Paid",
    "Payment Currency",
    "Payment Format",
    "Is Laundering",
]

# Format B: AMLSim native log schema
AMLSIM_NATIVE_COLUMNS = [
    "tran_id",
    "orig_acct",
    "bene_acct",
    "tx_type",
    "base_amt",
    "tran_timestamp",
    "is_sar",
]

# These two values are GhostTrace's OWN "no data" markers, not invented IDs.
# graph_engine.py and agents/profiler.py explicitly exclude "DEV-UNKNOWN" and
# "0.0.0.0" from shared-device / shared-subnet analysis. A bespoke sentinel
# (the previous value "UNSET-NO-DEVICE-DATA") was NOT on that exclusion list,
# so every account appeared to share one device and the engine reported
# fabricated "Shared Infrastructure" evidence on every cycle.
MISSING_DEVICE_SENTINEL = "DEV-UNKNOWN"
MISSING_IP_SENTINEL = "0.0.0.0"
MISSING_MEMO_SENTINEL = ""

# AMLSim payment format → GhostTrace channel normalisation
_PAYMENT_FORMAT_MAP: Dict[str, str] = {
    "wire": "wire_transfer",
    "wire transfer": "wire_transfer",
    "ach": "ach_commercial",
    "cheque": "cheque",
    "check": "cheque",
    "cash": "cash",
    "credit card": "credit_card",
    "debit card": "debit_card",
    "reinvestment": "reinvestment",
    "crypto": "crypto_ramp",
    "bitcoin": "crypto_ramp",
    "swift": "swift",
    "transfer": "wire_transfer",
    "payment": "ach_commercial",
}


# ──────────────────────────────────────────────────────────────────────────────
# Load result
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class AMLSimLoadResult:
    """Detailed outcome of a CSV load attempt."""
    success: bool
    ledger: Optional[LedgerData]
    detected_format: str                    # "kaggle_aml", "amlsim_native", "unknown"
    rows_attempted: int = 0
    rows_loaded: int = 0
    rows_skipped: int = 0
    skip_reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    # ── Populated only by load_amlsim_transactions() (strict loader) ─────────
    # Evaluation-only labels, keyed by tx_id. NEVER attached to Transaction
    # objects, so they cannot reach the detection engine.
    labels: Dict[str, "AMLSimEvalLabel"] = field(default_factory=dict)
    # tx_id -> the tran_timestamp cell exactly as it appeared in the file.
    raw_timestamps: Dict[str, str] = field(default_factory=dict)
    # "calendar_in_file" | "configured_calendar" | "ordinal_surrogate" | None
    time_basis: Optional[str] = None
    # True when more data rows existed beyond max_rows (prefix sample only).
    truncated: bool = False
    label_columns_present: Tuple[str, ...] = ()

    @property
    def load_summary(self) -> str:
        lines = [
            f"Format: {self.detected_format}",
            f"Rows attempted: {self.rows_attempted}",
            f"Rows loaded:    {self.rows_loaded}",
            f"Rows skipped:   {self.rows_skipped}",
        ]
        if self.time_basis:
            lines.append(f"Time basis:     {self.time_basis}")
        if self.truncated:
            lines.append("Truncated:      yes (row limit reached; prefix sample only)")
        if self.warnings:
            lines.append("Warnings:")
            for w in self.warnings[:10]:
                lines.append(f"  • {w}")
            if len(self.warnings) > 10:
                lines.append(f"  … and {len(self.warnings) - 10} more.")
        if self.error:
            lines.append(f"Error: {self.error}")
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Schema detection
# ──────────────────────────────────────────────────────────────────────────────

def _normalise_header(h: str) -> str:
    """Lowercase, strip, collapse internal whitespace."""
    return re.sub(r"\s+", " ", h.strip().lower())


def detect_csv_format(headers: List[str]) -> str:
    """
    Returns 'kaggle_aml', 'amlsim_native', or 'unknown'.
    Detection is case-insensitive and whitespace-tolerant.
    """
    nh = [_normalise_header(h) for h in headers]
    nh_set = set(nh)

    # Kaggle AML: must have 'is laundering' and 'from bank'
    if "is laundering" in nh_set and "from bank" in nh_set:
        return "kaggle_aml"

    # AMLSim native: must have 'tran_id' and 'orig_acct'
    if "tran_id" in nh_set and "orig_acct" in nh_set:
        return "amlsim_native"

    # Generic fallback: has some key AML fields
    required_generic = {"orig_acct", "bene_acct", "base_amt"}
    if required_generic.issubset(nh_set):
        return "amlsim_native"

    return "unknown"


def validate_schema(headers: List[str]) -> Tuple[bool, str]:
    """
    Returns (is_valid, error_message).
    Validates that the CSV has the minimum columns GhostTrace needs.
    """
    fmt = detect_csv_format(headers)
    if fmt == "unknown":
        found = ", ".join(repr(h) for h in headers[:12])
        return False, (
            f"Unrecognised CSV schema. Found columns: {found}. "
            "Expected either IBM Kaggle AML format (with 'Timestamp', 'From Bank', "
            "'Account', 'Account.1', 'Amount Paid', 'Payment Format', 'Is Laundering') "
            "or AMLSim native format (with 'tran_id', 'orig_acct', 'bene_acct', "
            "'base_amt', 'tran_timestamp', 'is_sar')."
        )
    return True, ""


# ──────────────────────────────────────────────────────────────────────────────
# Timestamp parsing (extends graph_engine's safe_parse_datetime patterns)
# ──────────────────────────────────────────────────────────────────────────────

_TIMESTAMP_FORMATS = [
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%Y-%m-%d",
]


def _parse_timestamp(val: Any) -> str:
    """
    Attempts to parse a timestamp value and returns an ISO-format string.
    Returns empty string if unparseable (graph engine handles that gracefully).
    Numeric 'step' values (AMLSim simulation ticks) are converted to a base
    datetime offset (2022-01-01 + step minutes) so they are comparable.
    """
    if val is None:
        return ""
    s = str(val).strip()
    if not s:
        return ""

    # Pure integer → treat as simulation step/tick in minutes from epoch
    if re.fullmatch(r"\d+", s):
        step = int(s)
        base = datetime(2022, 1, 1, 0, 0, 0)
        from datetime import timedelta
        ts = base + timedelta(minutes=step)
        return ts.isoformat()

    # Try each explicit format
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(s, fmt).isoformat()
        except ValueError:
            continue

    # Last-ditch: fromisoformat
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
    except Exception:
        return ""  # graph engine's safe_parse_datetime will handle as missing


def _safe_amount(val: Any) -> Optional[float]:
    """Returns float if parseable and finite, else None."""
    if val is None:
        return None
    try:
        f = float(str(val).replace(",", "").strip())
        return f if math.isfinite(f) and f >= 0 else None
    except (ValueError, TypeError):
        return None


def _normalise_channel(payment_format: str) -> str:
    key = payment_format.strip().lower() if payment_format else ""
    return _PAYMENT_FORMAT_MAP.get(key, payment_format.strip() or "unknown")


def _safe_bool_label(val: Any) -> bool:
    """Converts '1', 1, 'True', 'true' → True, everything else → False."""
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "t")


# ──────────────────────────────────────────────────────────────────────────────
# Row mappers
# ──────────────────────────────────────────────────────────────────────────────

def _header_index_map(headers: List[str]) -> Dict[str, int]:
    """Case-insensitive, whitespace-tolerant column index lookup."""
    return {_normalise_header(h): i for i, h in enumerate(headers)}


def _get(row: List[str], idx_map: Dict[str, int], key: str, default: str = "") -> str:
    idx = idx_map.get(_normalise_header(key))
    if idx is None or idx >= len(row):
        return default
    return row[idx].strip()


def _map_kaggle_row(
    row: List[str],
    idx_map: Dict[str, int],
    tx_counter: list,  # mutable counter [int]
    ground_truth_labels: Dict[str, bool],  # tx_id → is_fraud (OUT-only)
) -> Optional[Transaction]:
    """
    Maps one Kaggle AML CSV row to a GhostTrace Transaction.
    Ground-truth label is recorded in ground_truth_labels separately
    and is NOT embedded in the Transaction until explicitly requested.
    """
    # Identify sender/receiver account IDs
    # The CSV has two columns named "Account" – pandas renames the second to
    # "Account.1". In raw CSV parsing we detect by position after "From Bank".
    sender_id_raw = _get(row, idx_map, "account")
    receiver_id_raw = _get(row, idx_map, "account.1")

    from_bank = _get(row, idx_map, "from bank")
    to_bank = _get(row, idx_map, "to bank")

    # Qualify with bank prefix to ensure global uniqueness
    sender_id = f"B{from_bank}-{sender_id_raw}" if from_bank and sender_id_raw else sender_id_raw
    receiver_id = f"B{to_bank}-{receiver_id_raw}" if to_bank and receiver_id_raw else receiver_id_raw

    if not sender_id or not receiver_id:
        return None

    # Amount: prefer Amount Paid (sender's perspective), fallback to Amount Received
    amt_paid = _safe_amount(_get(row, idx_map, "amount paid"))
    amt_recv = _safe_amount(_get(row, idx_map, "amount received"))
    amount = amt_paid if amt_paid is not None else amt_recv
    if amount is None:
        return None

    timestamp = _parse_timestamp(_get(row, idx_map, "timestamp"))
    channel = _normalise_channel(_get(row, idx_map, "payment format"))
    is_fraud = _safe_bool_label(_get(row, idx_map, "is laundering"))

    tx_counter[0] += 1
    tx_id = f"AML-{tx_counter[0]:08d}"

    ground_truth_labels[tx_id] = is_fraud

    return Transaction(
        tx_id=tx_id,
        sender_id=sender_id,
        receiver_id=receiver_id,
        amount=amount,
        timestamp=timestamp,
        channel=channel,
        device_id=MISSING_DEVICE_SENTINEL,
        ip_address=MISSING_IP_SENTINEL,
        memo=MISSING_MEMO_SENTINEL,
        is_ground_truth_fraud=is_fraud,   # stored for evaluation, NOT used by engine
        pattern_type="amlsim_imported",
    )


def _map_amlsim_native_row(
    row: List[str],
    idx_map: Dict[str, int],
    ground_truth_labels: Dict[str, bool],
) -> Optional[Transaction]:
    """Maps one AMLSim native CSV row to a GhostTrace Transaction."""
    tran_id = _get(row, idx_map, "tran_id")
    orig_acct = _get(row, idx_map, "orig_acct")
    bene_acct = _get(row, idx_map, "bene_acct")

    if not orig_acct or not bene_acct:
        return None

    amount = _safe_amount(_get(row, idx_map, "base_amt"))
    if amount is None:
        return None

    timestamp = _parse_timestamp(_get(row, idx_map, "tran_timestamp"))
    tx_type = _get(row, idx_map, "tx_type")
    channel = _normalise_channel(tx_type)

    is_sar = _safe_bool_label(_get(row, idx_map, "is_sar"))
    tx_id = tran_id if tran_id else f"AML-{id(row):016x}"

    ground_truth_labels[tx_id] = is_sar

    return Transaction(
        tx_id=tx_id,
        sender_id=orig_acct,
        receiver_id=bene_acct,
        amount=amount,
        timestamp=timestamp,
        channel=channel,
        device_id=MISSING_DEVICE_SENTINEL,
        ip_address=MISSING_IP_SENTINEL,
        memo=MISSING_MEMO_SENTINEL,
        is_ground_truth_fraud=is_sar,
        pattern_type="amlsim_imported",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Account synthesiser (from transaction graph)
# ──────────────────────────────────────────────────────────────────────────────

def _build_accounts_from_transactions(transactions: List[Transaction]) -> Dict[str, Account]:
    """
    AMLSim transaction files don't always include separate account metadata.
    We synthesise minimal Account objects from the transaction graph.
    Explicitly marks all inferred fields so downstream agents know they
    are derived, not sourced from a KYC record.
    """
    accounts: Dict[str, Account] = {}
    for tx in transactions:
        for acc_id in (tx.sender_id, tx.receiver_id):
            if acc_id not in accounts:
                accounts[acc_id] = Account(
                    account_id=acc_id,
                    name=f"[AMLSim] {acc_id}",   # no name data in CSV
                    account_type="unknown",        # not available
                    kyc_status="unverified",       # no KYC data in CSV
                    is_dormant=False,
                    dormancy_days=0,
                    device_id=MISSING_DEVICE_SENTINEL,
                    ip_address=MISSING_IP_SENTINEL,
                    country="UNKNOWN",
                    initial_balance=0.0,           # not in CSV
                    created_at="",
                )
    return accounts


# ──────────────────────────────────────────────────────────────────────────────
# Main public loader
# ──────────────────────────────────────────────────────────────────────────────

class AMLSimAdapter:
    """
    Loads an IBM AMLSim / Kaggle AML CSV file and returns a GhostTrace
    LedgerData object ready to be fed to FinancialGraphEngine.

    Usage
    -----
        adapter = AMLSimAdapter(max_rows=2000)
        result  = adapter.load_csv("path/to/HI-Small_Trans.csv")
        if result.success:
            ledger = result.ledger
    """

    def __init__(self, max_rows: int = 5000):
        """
        Parameters
        ----------
        max_rows : int
            Maximum transaction rows to load. AMLSim files can be large;
            this cap prevents OOM in Streamlit. Default 5 000.
        """
        self.max_rows = max_rows

    # ── File path API ──────────────────────────────────────────────────────────

    def load_csv(self, path: str) -> AMLSimLoadResult:
        """Load from a filesystem path."""
        if not os.path.exists(path):
            return AMLSimLoadResult(
                success=False,
                ledger=None,
                detected_format="unknown",
                error=f"File not found: {path!r}. "
                      f"Please place the CSV in the 'data/amlsim/' directory under "
                      f"your GhostTrace workspace.",
            )

        if not path.lower().endswith(".csv"):
            return AMLSimLoadResult(
                success=False,
                ledger=None,
                detected_format="unknown",
                error=f"Unsupported file format. Only .csv files are accepted. Got: {path!r}",
            )

        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                with open(path, newline="", encoding="latin-1") as f:
                    content = f.read()
            except Exception as e:
                return AMLSimLoadResult(
                    success=False,
                    ledger=None,
                    detected_format="unknown",
                    error=f"Cannot read file (encoding error): {e}",
                )
        except Exception as e:
            return AMLSimLoadResult(
                success=False,
                ledger=None,
                detected_format="unknown",
                error=f"Cannot open file: {e}",
            )

        filename = os.path.splitext(os.path.basename(path))[0]
        return self._parse_csv_content(content, source_name=filename)

    # ── In-memory / uploaded file API ─────────────────────────────────────────

    def load_from_bytes(self, content: bytes, filename: str = "uploaded") -> AMLSimLoadResult:
        """Load from raw bytes (e.g., Streamlit file_uploader)."""
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            return AMLSimLoadResult(
                success=False,
                ledger=None,
                detected_format="unknown",
                error="Cannot decode file content. Only UTF-8 or Latin-1 encoded CSVs are supported.",
            )
        source_name = os.path.splitext(filename)[0]
        return self._parse_csv_content(text, source_name=source_name)

    # ── Core parser ──────────────────────────────────────────────────────────

    def _parse_csv_content(self, content: str, source_name: str) -> AMLSimLoadResult:
        reader = csv.reader(io.StringIO(content))

        try:
            headers = next(reader)
        except StopIteration:
            return AMLSimLoadResult(
                success=False,
                ledger=None,
                detected_format="unknown",
                error="The CSV file is empty (no header row found).",
            )

        if not headers:
            return AMLSimLoadResult(
                success=False,
                ledger=None,
                detected_format="unknown",
                error="The CSV header row is empty.",
            )

        # ── Schema validation ─────────────────────────────────────────────────
        fmt = detect_csv_format(headers)
        is_valid, schema_error = validate_schema(headers)
        if not is_valid:
            return AMLSimLoadResult(
                success=False,
                ledger=None,
                detected_format=fmt,
                error=schema_error,
            )

        # Build a normalised header → column-index map.
        # The Kaggle CSV has TWO columns named "Account"; we need positional
        # handling. We detect them by finding the first and second occurrence.
        idx_map: Dict[str, int] = {}
        account_occurrences = []
        for i, h in enumerate(headers):
            nh = _normalise_header(h)
            if nh == "account":
                account_occurrences.append(i)
                if len(account_occurrences) == 1:
                    idx_map["account"] = i
                else:
                    idx_map["account.1"] = i  # second occurrence = receiver
            else:
                idx_map[nh] = i

        # ── Parse rows ────────────────────────────────────────────────────────
        transactions: List[Transaction] = []
        ground_truth_labels: Dict[str, bool] = {}
        skip_reasons: List[str] = []
        warnings: List[str] = []
        rows_attempted = 0
        tx_counter = [0]

        for raw_row in reader:
            if rows_attempted >= self.max_rows:
                warnings.append(
                    f"Row limit reached ({self.max_rows}). "
                    "Remaining rows were not loaded. "
                    "Increase max_rows or use a smaller slice of the dataset."
                )
                break

            rows_attempted += 1

            if not any(cell.strip() for cell in raw_row):
                continue  # skip blank rows silently

            try:
                if fmt == "kaggle_aml":
                    tx = _map_kaggle_row(raw_row, idx_map, tx_counter, ground_truth_labels)
                else:  # amlsim_native
                    tx = _map_amlsim_native_row(raw_row, idx_map, ground_truth_labels)

                if tx is None:
                    skip_reasons.append(
                        f"Row {rows_attempted}: Skipped – null account ID or unparseable amount."
                    )
                    continue

                transactions.append(tx)

            except Exception as exc:
                skip_reasons.append(f"Row {rows_attempted}: Unexpected error – {exc}")
                continue

        if not transactions:
            return AMLSimLoadResult(
                success=False,
                ledger=None,
                detected_format=fmt,
                rows_attempted=rows_attempted,
                rows_loaded=0,
                rows_skipped=len(skip_reasons),
                skip_reasons=skip_reasons,
                warnings=warnings,
                error=(
                    "No valid transactions could be loaded from the file. "
                    "All rows were skipped due to missing account IDs or "
                    "unparseable amount values."
                ),
            )

        # Sort chronologically (graph engine expects this for velocity checks)
        transactions.sort(key=lambda t: t.timestamp)

        # Build minimal accounts from the transaction graph
        accounts = _build_accounts_from_transactions(transactions)

        # Build ground-truth ring annotations (one entry per SAR-labelled cluster)
        fraud_tx_ids = [tx_id for tx_id, label in ground_truth_labels.items() if label]
        ground_truth_rings = []
        if fraud_tx_ids:
            ground_truth_rings.append({
                "ring_id": "AMLSim-SAR-Labelled-Set",
                "type": "amlsim_labelled_fraud",
                "tx_ids": fraud_tx_ids,
                "is_fraud": True,
                "note": (
                    "Ground-truth labels sourced from Is Laundering / is_sar column. "
                    "These labels identify transactions the simulation designated as SAR-relevant. "
                    "Labels are stored separately and are NOT used as detection inputs."
                ),
            })

        ledger = LedgerData(
            scenario_name=f"IBM AMLSim: {source_name}",
            description=(
                f"IBM AMLSim dataset loaded from '{source_name}.csv'. "
                f"Format: {fmt}. "
                f"{len(transactions)} transactions across {len(accounts)} unique accounts. "
                f"Ground-truth fraud labels: {len(fraud_tx_ids)} of {len(transactions)} transactions. "
                f"Device IDs and IP addresses are not available in this dataset format; "
                f"shared-device detection is disabled for this run."
            ),
            accounts=accounts,
            transactions=transactions,
            ground_truth_rings=ground_truth_rings,
        )

        return AMLSimLoadResult(
            success=True,
            ledger=ledger,
            detected_format=fmt,
            rows_attempted=rows_attempted,
            rows_loaded=len(transactions),
            rows_skipped=rows_attempted - len(transactions),
            skip_reasons=skip_reasons,
            warnings=warnings,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Convenience helper: list available data files
# ──────────────────────────────────────────────────────────────────────────────

def list_amlsim_files(data_dir: str = "data/amlsim") -> List[str]:
    """
    Returns paths of .csv files found in data_dir (relative to cwd).
    Returns empty list if the directory doesn't exist.
    """
    if not os.path.isdir(data_dir):
        return []
    return [
        os.path.join(data_dir, f)
        for f in sorted(os.listdir(data_dir))
        if f.lower().endswith(".csv")
    ]


def get_data_dir_instructions() -> str:
    """Returns user-facing instructions for placing AMLSim dataset files."""
    return (
        "OFFICIAL AMLSim DATA (IBM/AMLSim)\n"
        "  Documented example: '100vertices-10Kedges' (100 accounts, 10,000 transactions),\n"
        "  listed on https://github.com/IBM/AMLSim/wiki/Download-Example-Data-Set\n"
        "  (7-Zip archive in the Dropbox folder linked there). Its transactions.csv uses the\n"
        "  AMLSim-native columns below. The files bundled in data/amlsim/ are hand-written\n"
        "  test fixtures, NOT AMLSim output; see data/amlsim/README.md.\n"
        "  NOTE: the Kaggle 'IBM Transactions for AML' (HI/LI-Small) files are a DIFFERENT\n"
        "  IBM dataset (IT-AML generator), not AMLSim.\n\n"
        "Place your IBM AMLSim / Kaggle AML CSV files in:\n"
        "  <your GhostTrace workspace>/data/amlsim/\n\n"
        "Supported files:\n"
        "  • HI-Small_Trans.csv  (IBM Kaggle AML – High Illicit ratio)\n"
        "  • LI-Small_Trans.csv  (IBM Kaggle AML – Low Illicit ratio)\n"
        "  • transactions.csv    (AMLSim native log format)\n\n"
        "Download from:\n"
        "  https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml\n"
        "  (Free account required. Click Download → select the CSV files.)\n\n"
        "Column requirements:\n"
        "  Kaggle format: Timestamp, From Bank, Account, To Bank, Account.1,\n"
        "                 Amount Received, Receiving Currency, Amount Paid,\n"
        "                 Payment Currency, Payment Format, Is Laundering\n"
        "  Native format: tran_id, orig_acct, bene_acct, tx_type,\n"
        "                 base_amt, tran_timestamp, is_sar\n"
    )


# ══════════════════════════════════════════════════════════════════════════════
# STRICT AMLSim-NATIVE LOADER  (streaming, path-based)
# ══════════════════════════════════════════════════════════════════════════════
#
# Schema source (verified): IBM/AMLSim master @ 7338a4b (2022-02-14),
# paramFiles/schema.json -> "transaction" section, and scripts/convert_logs.py:
#
#   tran_id         transaction id (sequential integer in convert_logs output)
#   orig_acct       originator account id
#   bene_acct       beneficiary account id
#   tx_type         transaction type string (e.g. TRANSFER, CASH-IN ...)
#   base_amt        amount
#   tran_timestamp  convert_logs.py writes str(step): the integer SIMULATION
#                   STEP, not a calendar date (its days_to_date() call is
#                   commented out).
#   is_sar          boolean flag  -> evaluation label
#   alert_id        alert id      -> evaluation label (convert_logs treats
#                                    alert_id >= 0 as "is an alert")
#
# The two label columns are optional here (older/other exports omit them).

AMLSIM_REQUIRED_COLUMNS: Tuple[str, ...] = (
    "tran_id", "orig_acct", "bene_acct", "tx_type", "base_amt", "tran_timestamp",
)
AMLSIM_LABEL_COLUMNS: Tuple[str, ...] = ("is_sar", "alert_id")

DEFAULT_MAX_ROWS = 5_000
ABSOLUTE_MAX_ROWS = 500_000            # hard ceiling; never auto-load a huge file
LARGE_FILE_WARNING_BYTES = 200 * 1024 * 1024
MAX_ITEMISED_SKIPS = 50

UNKNOWN_CHANNEL = "unknown"
UNKNOWN_ACCOUNT_TYPE = "unknown"
UNKNOWN_KYC_STATUS = "unknown"

# Surrogate clock used ONLY when the file holds integer steps and the caller has
# not supplied a base_date + step_unit. It exists because graph_engine.py needs
# a parseable ISO string (an empty timestamp is silently replaced by "now").
# 2000-01-01 is deliberately not a plausible AMLSim date and is safely after the
# 1970 epoch (naive pre-epoch datetimes raise OSError in .timestamp() on Windows).
ORDINAL_SURROGATE_EPOCH = datetime(2000, 1, 1)
ORDINAL_SURROGATE_UNIT = "day"

_STEP_UNITS: Dict[str, timedelta] = {
    "day": timedelta(days=1),
    "hour": timedelta(hours=1),
    "minute": timedelta(minutes=1),
    "second": timedelta(seconds=1),
}
_STEP_RE = re.compile(r"\d+")


@dataclass(frozen=True)
class AMLSimEvalLabel:
    """Evaluation-only labels for one transaction (never a detection input)."""
    is_sar: Optional[bool]      # None = column absent, blank, or unparseable
    alert_id: Optional[str]     # verbatim cell, None if absent/blank


@dataclass(frozen=True)
class AMLSimTimeConfig:
    """
    Dataset-confirmed interpretation of integer ``tran_timestamp`` steps.

    Supply BOTH values only when you know them for the dataset being loaded:
      base_date : calendar date of step 0 (AMLSim conf.json -> general.base_date;
                  see read_base_date_from_conf()).
      step_unit : "day" | "hour" | "minute" | "second". conf.json does NOT record
                  this; scripts/convert_logs.py documents steps as days.
    Leave the config out and the loader uses an ordinal surrogate clock and says
    so in result.time_basis / result.warnings.
    """
    base_date: Optional[str] = None
    step_unit: Optional[str] = None

    def resolve(self) -> Optional[Tuple[datetime, timedelta]]:
        if self.base_date is None and self.step_unit is None:
            return None
        if self.base_date is None or self.step_unit is None:
            raise ValueError(
                "AMLSimTimeConfig needs BOTH base_date and step_unit (or neither). "
                f"Got base_date={self.base_date!r}, step_unit={self.step_unit!r}."
            )
        if self.step_unit not in _STEP_UNITS:
            raise ValueError(
                f"Unsupported step_unit {self.step_unit!r}. "
                f"Use one of: {', '.join(sorted(_STEP_UNITS))}."
            )
        base = _parse_calendar_timestamp(str(self.base_date))
        if base is None:
            raise ValueError(
                f"base_date {self.base_date!r} is not a valid ISO date "
                "(expected e.g. '2017-01-01')."
            )
        return base, _STEP_UNITS[self.step_unit]


def read_base_date_from_conf(conf_path: str) -> str:
    """
    Read ``general.base_date`` from an AMLSim conf.json ("the date corresponds
    to step 0"). Raises ValueError with a clear message on any problem.
    """
    if not os.path.isfile(conf_path):
        raise ValueError(f"AMLSim conf file not found: {conf_path!r}")
    try:
        with open(conf_path, encoding="utf-8-sig") as f:
            conf = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read AMLSim conf file {conf_path!r}: {exc}") from exc
    try:
        base = conf["general"]["base_date"]
    except (KeyError, TypeError):
        raise ValueError(
            f"{conf_path!r} has no general.base_date entry; cannot confirm what "
            "step 0 means."
        ) from None
    if _parse_calendar_timestamp(str(base)) is None:
        raise ValueError(f"general.base_date {base!r} in {conf_path!r} is not a valid date.")
    return str(base)


def _parse_calendar_timestamp(text: str) -> Optional[datetime]:
    """Parse an ISO-8601 (or legacy-listed) calendar value to a UTC-naive datetime."""
    t = text.strip()
    if not t:
        return None
    if t[-1] in ("Z", "z"):
        t = t[:-1] + "+00:00"
    dt: Optional[datetime] = None
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        for fmt in _TIMESTAMP_FORMATS:
            try:
                dt = datetime.strptime(t, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _strict_amount(raw: str) -> Tuple[Optional[float], str]:
    """(value, "") on success, (None, reason) otherwise. Must be finite and > 0."""
    if raw == "":
        return None, "empty base_amt"
    try:
        v = float(raw)
    except ValueError:
        return None, f"non-numeric base_amt {raw!r}"
    if not math.isfinite(v):
        return None, f"non-finite base_amt {raw!r}"
    if v <= 0:
        return None, f"base_amt must be > 0, got {raw!r}"
    return v, ""


def _parse_label_bool(raw: str) -> Tuple[Optional[bool], bool]:
    """(value, ok). Blank -> (None, True); junk -> (None, False)."""
    t = raw.strip().lower()
    if t == "":
        return None, True
    if t in ("true", "1"):
        return True, True
    if t in ("false", "0"):
        return False, True
    return None, False


def _build_unprofiled_accounts(transactions: List[Transaction]) -> Dict[str, Account]:
    """
    One Account per account id seen. The transaction file carries NO account
    attributes, so every attribute except the id is an explicit "unknown"
    placeholder (the same placeholders graph_engine.py uses for implicit nodes).
    Account dataclass defaults (US, 10000.0, 192.168.1.1, 2025-01-01) are NOT
    used because they would fabricate data.
    """
    accounts: Dict[str, Account] = {}
    for tx in transactions:
        for acc_id in (tx.sender_id, tx.receiver_id):
            if acc_id not in accounts:
                accounts[acc_id] = Account(
                    account_id=acc_id,
                    name=acc_id,
                    account_type=UNKNOWN_ACCOUNT_TYPE,
                    kyc_status=UNKNOWN_KYC_STATUS,
                    is_dormant=False,
                    dormancy_days=0,
                    device_id=MISSING_DEVICE_SENTINEL,
                    ip_address=MISSING_IP_SENTINEL,
                    country="UNKNOWN",
                    initial_balance=0.0,
                    created_at="",
                )
    return accounts


def _fail(error: str, **kw: Any) -> AMLSimLoadResult:
    return AMLSimLoadResult(
        success=False, ledger=None, detected_format=kw.pop("detected_format", "unknown"),
        error=error, **kw,
    )


def load_amlsim_transactions(
    path: str,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    skip_rows: int = 0,
    time_config: Optional[AMLSimTimeConfig] = None,
    strict: bool = False,
) -> AMLSimLoadResult:
    """
    Stream an AMLSim-native transactions CSV from disk into a GhostTrace
    LedgerData (result.ledger). Never raises for data problems; check
    ``result.success`` / ``result.error``.

    Parameters
    ----------
    path        Local ``.csv`` file with at least AMLSIM_REQUIRED_COLUMNS
                (header names matched case-insensitively; extra columns ignored).
    max_rows    Maximum non-blank data rows to read (1..ABSOLUTE_MAX_ROWS,
                default 5000). The file is streamed, never read whole, so a
                multi-GB file is safe: only the first max_rows are parsed and
                result.truncated is set. NOTE this is a file-order PREFIX, not a
                time- or graph-connected sample; cycles may be cut at the edge.
    skip_rows   Data records to skip before reading (chunked access:
                call repeatedly with skip_rows=k*max_rows).
    time_config Optional AMLSimTimeConfig confirming how integer steps map to
                dates (see class docstring). Without it, steps become an ordinal
                surrogate clock (1 step = 1 day from 2000-01-01) so ordering is
                exact but absolute dates AND temporal-velocity scores are NOT
                meaningful. Calendar values already in the file are used as-is
                (converted to UTC-naive ISO).
    strict      If True, the first malformed row fails the whole load instead of
                being skipped and reported.

    Field mapping (Transaction <- CSV)
    ----------------------------------
    tx_id <- tran_id, sender_id <- orig_acct, receiver_id <- bene_acct,
    amount <- base_amt (float, finite, > 0), channel <- tx_type verbatim
    ("unknown" if blank), timestamp <- tran_timestamp (ISO string; original
    cell kept in result.raw_timestamps). device_id / ip_address are None and
    memo is "" (not in the schema). Account attributes are "unknown".

    Handling policy (asserted by tests/test_amlsim_adapter_verification.py)
    -----------------------------------------------------------------------
    Duplicate tran_id : FIRST occurrence wins; later rows with the same id are
                        skipped, itemised in skip_reasons, and their labels are
                        discarded. Only an ACCEPTED row reserves its id (a
                        malformed first row does not). Detection is per call:
                        ids are not remembered across skip_rows chunks.
    Missing values    : empty tran_id / orig_acct / bene_acct / base_amt /
                        tran_timestamp -> row skipped. Blank tx_type -> loaded,
                        channel "unknown". Blank/junk is_sar or alert_id ->
                        loaded, label field stored as None.
    Amount            : finite float > 0; thousands separators and currency
                        symbols are rejected.
    Blank lines       : ignored; never counted as rows, malformed rows or
                        skip_rows records.
    Row budget        : max_rows and skip_rows both count non-blank data
                        records, malformed ones included, so
                        skip_rows=k*max_rows yields contiguous, non-overlapping
                        chunks.

    Label separation
    ----------------
    is_sar / alert_id go ONLY to result.labels[tx_id]. Every Transaction has
    is_ground_truth_fraud=False and ledger.ground_truth_rings is empty, so the
    engine, visualizer and agents never see a label. A malformed label cell
    never changes which rows are loaded.
    """
    # ── argument validation ────────────────────────────────────────────────
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        return _fail(f"max_rows must be a positive integer, got {max_rows!r}.")
    if max_rows > ABSOLUTE_MAX_ROWS:
        return _fail(
            f"max_rows={max_rows} exceeds the hard limit of {ABSOLUTE_MAX_ROWS}. "
            "Load large AMLSim files in chunks using skip_rows."
        )
    if isinstance(skip_rows, bool) or not isinstance(skip_rows, int) or skip_rows < 0:
        return _fail(f"skip_rows must be a non-negative integer, got {skip_rows!r}.")
    try:
        clock = (time_config or AMLSimTimeConfig()).resolve()
    except ValueError as exc:
        return _fail(str(exc))

    # ── file checks ────────────────────────────────────────────────────────
    try:
        path = os.fspath(path)
    except TypeError:
        return _fail(f"path must be a string or path-like object, got {type(path).__name__}.")
    if not os.path.exists(path):
        return _fail(f"File not found: {path!r}.")
    if os.path.isdir(path):
        return _fail(f"Expected a CSV file but {path!r} is a directory.")
    if not path.lower().endswith(".csv"):
        return _fail(f"Unsupported file type. Only .csv files are accepted. Got: {path!r}")

    warnings: List[str] = []
    try:
        if os.path.getsize(path) > LARGE_FILE_WARNING_BYTES:
            warnings.append(
                f"Large file ({os.path.getsize(path) / 1e6:,.0f} MB). The file is "
                f"streamed and only the first {max_rows} rows after skip_rows="
                f"{skip_rows} are loaded."
            )
    except OSError:
        pass

    transactions: List[Transaction] = []
    sort_keys: List[Tuple[datetime, int]] = []
    labels: Dict[str, AMLSimEvalLabel] = {}
    raw_ts: Dict[str, str] = {}
    seen_ids: set = set()
    skip_reasons: List[str] = []
    skipped = 0
    blank_rows = 0
    rows_attempted = 0
    truncated = False
    basis_kind: Optional[str] = None          # "step" | "calendar"
    label_parse_failures = 0
    blank_type_rows = 0
    label_cols_present: Tuple[str, ...] = ()

    def _skip(reason: str) -> None:
        nonlocal skipped
        skipped += 1
        if len(skip_reasons) < MAX_ITEMISED_SKIPS:
            skip_reasons.append(reason)

    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                return _fail("The CSV file is empty (no header row found).")

            names = [h.strip().lower() for h in header]
            if not any(names):
                return _fail("The CSV header row is empty.")
            dupes = sorted({n for n in names if n and names.count(n) > 1})
            if dupes:
                return _fail(f"Ambiguous header: duplicate column name(s) {dupes}.")
            idx = {n: i for i, n in enumerate(names) if n}
            missing = [c for c in AMLSIM_REQUIRED_COLUMNS if c not in idx]
            if missing:
                found = ", ".join(repr(h.strip()) for h in header[:15])
                return _fail(
                    f"Missing required AMLSim column(s): {missing}. Found: {found}. "
                    f"Required: {list(AMLSIM_REQUIRED_COLUMNS)}."
                )
            label_cols_present = tuple(c for c in AMLSIM_LABEL_COLUMNS if c in idx)
            ncols = len(header)

            # chunked access: stream past skip_rows records without storing them
            if skip_rows > 0:
                skipped_records = 0
                for skipped_row in reader:
                    if not any(cell.strip() for cell in skipped_row):
                        continue            # blank lines are not data records
                    skipped_records += 1
                    if skipped_records >= skip_rows:
                        break
                if skipped_records < skip_rows:
                    return _fail(
                        f"skip_rows={skip_rows} is beyond the end of the file "
                        f"({skipped_records} data records)."
                    )

            for rec_no, row in enumerate(reader, start=skip_rows + 1):
                if not any(cell.strip() for cell in row):
                    blank_rows += 1
                    continue
                if rows_attempted >= max_rows:
                    truncated = True
                    break
                rows_attempted += 1

                if len(row) != ncols:
                    _skip(f"Data row {rec_no}: expected {ncols} fields, got {len(row)}.")
                    if strict:
                        break
                    continue

                def cell(name: str) -> str:
                    return row[idx[name]].strip()

                tran_id, orig, bene = cell("tran_id"), cell("orig_acct"), cell("bene_acct")
                problem = ""
                if not tran_id:
                    problem = "empty tran_id"
                elif not orig:
                    problem = "empty orig_acct"
                elif not bene:
                    problem = "empty bene_acct"
                elif tran_id in seen_ids:
                    problem = f"duplicate tran_id {tran_id!r}"

                amount = None
                if not problem:
                    amount, problem = _strict_amount(cell("base_amt"))

                ts_iso = ""
                dt: Optional[datetime] = None
                raw_cell = cell("tran_timestamp")
                if not problem:
                    # 1) parse on its own merits ...
                    if _STEP_RE.fullmatch(raw_cell):
                        kind = "step"
                        base, unit = clock if clock else (
                            ORDINAL_SURROGATE_EPOCH, _STEP_UNITS[ORDINAL_SURROGATE_UNIT])
                        try:
                            dt = base + int(raw_cell) * unit
                        except OverflowError:
                            problem = f"tran_timestamp step {raw_cell!r} is out of range"
                    else:
                        kind = "calendar"
                        dt = _parse_calendar_timestamp(raw_cell)
                        if dt is None:
                            problem = (
                                f"unparseable tran_timestamp {raw_cell!r} (expected an "
                                "integer step or an ISO date/datetime)"
                            )
                    # 2) ... then require one consistent kind across the file
                    if not problem and basis_kind is not None and kind != basis_kind:
                        problem = (
                            f"tran_timestamp {raw_cell!r} is a {kind} value but earlier "
                            f"rows were {basis_kind} values (mixed kinds)"
                        )
                    if not problem and basis_kind is None:
                        basis_kind = kind
                if problem:
                    _skip(f"Data row {rec_no}: {problem}.")
                    if strict:
                        break
                    continue

                ts_iso = dt.isoformat()  # type: ignore[union-attr]
                tx_type = cell("tx_type")
                if not tx_type:
                    blank_type_rows += 1

                seen_ids.add(tran_id)
                transactions.append(Transaction(
                    tx_id=tran_id,
                    sender_id=orig,
                    receiver_id=bene,
                    amount=amount,                       # type: ignore[arg-type]
                    timestamp=ts_iso,
                    channel=tx_type or UNKNOWN_CHANNEL,
                    device_id=None,                      # type: ignore[arg-type]
                    ip_address=None,                     # type: ignore[arg-type]
                    memo="",
                    is_ground_truth_fraud=False,         # labels live in result.labels only
                    pattern_type="amlsim_imported",
                ))
                sort_keys.append((dt, len(sort_keys)))   # type: ignore[arg-type]
                raw_ts[tran_id] = raw_cell

                if label_cols_present:
                    sar_val: Optional[bool] = None
                    if "is_sar" in idx:
                        sar_val, ok = _parse_label_bool(cell("is_sar"))
                        if not ok:
                            label_parse_failures += 1
                    alert_val = cell("alert_id") if "alert_id" in idx else ""
                    labels[tran_id] = AMLSimEvalLabel(
                        is_sar=sar_val, alert_id=alert_val or None)
    except UnicodeDecodeError as exc:
        return _fail(f"Cannot decode file as UTF-8 (near byte {exc.start}): {exc.reason}.")
    except csv.Error as exc:
        return _fail(f"Malformed CSV structure: {exc}")
    except OSError as exc:
        return _fail(f"Cannot read file {path!r}: {exc}")

    if strict and skipped:
        return _fail(
            f"Strict mode: {skip_reasons[0]}",
            rows_attempted=rows_attempted, skip_reasons=skip_reasons,
            rows_skipped=skipped, warnings=warnings,
        )

    if not transactions:
        if rows_attempted == 0:
            msg = ("The CSV has a header but no data rows"
                   + (f" after skip_rows={skip_rows}." if skip_rows else "."))
        else:
            msg = (f"No valid transactions could be loaded: all {rows_attempted} "
                   f"data rows were rejected. First problem: {skip_reasons[0]}")
        return _fail(msg, detected_format="amlsim_native", rows_attempted=rows_attempted,
                     rows_skipped=skipped, skip_reasons=skip_reasons, warnings=warnings)

    # ── warnings / provenance ──────────────────────────────────────────────
    if basis_kind == "calendar":
        time_basis = "calendar_in_file"
        if clock is not None:
            warnings.append(
                "time_config was ignored: tran_timestamp already holds calendar values.")
    elif clock is not None:
        time_basis = "configured_calendar"
    else:
        time_basis = "ordinal_surrogate"
        warnings.append(
            "tran_timestamp holds simulation steps and no time_config was given. "
            f"Steps were mapped to a surrogate clock (1 step = 1 {ORDINAL_SURROGATE_UNIT} "
            f"from {ORDINAL_SURROGATE_EPOCH.date()}) ONLY so the engine can order events. "
            "Absolute dates are not real and temporal-velocity scores are not "
            "meaningful until base_date and step_unit are confirmed. Original values "
            "are in result.raw_timestamps."
        )
    if truncated:
        warnings.append(
            f"Row limit reached ({max_rows}); the rest of the file was not read. "
            "This is a file-order prefix, so cycles near the cut may be incomplete."
        )
    if skipped > len(skip_reasons):
        warnings.append(
            f"{skipped - len(skip_reasons)} further malformed rows were skipped "
            f"(only the first {MAX_ITEMISED_SKIPS} are itemised).")
    if blank_type_rows:
        warnings.append(
            f"{blank_type_rows} rows had a blank tx_type; channel set to "
            f"{UNKNOWN_CHANNEL!r}.")
    if label_parse_failures:
        warnings.append(
            f"{label_parse_failures} is_sar values were not recognisable booleans "
            "and were stored as None (transactions still loaded).")
    if not label_cols_present:
        warnings.append("No is_sar / alert_id columns found; no evaluation labels available.")
    warnings.append(
        "Device IDs, IP addresses, KYC, account type, balances and country are not "
        "present in AMLSim transaction files; they are left as 'unknown' placeholders.")

    # Stable chronological order (ties keep file order).
    order = sorted(range(len(transactions)), key=lambda i: sort_keys[i])
    transactions = [transactions[i] for i in order]
    accounts = _build_unprofiled_accounts(transactions)

    source = os.path.splitext(os.path.basename(path))[0]
    ledger = LedgerData(
        scenario_name=f"IBM AMLSim: {source}",
        description=(
            f"AMLSim-native transactions from '{source}.csv': {len(transactions)} "
            f"transactions, {len(accounts)} accounts (time basis: {time_basis}). "
            "Evaluation labels (if any) are held outside the ledger, in "
            "AMLSimLoadResult.labels. No device, IP or KYC data exists in this source."
        ),
        accounts=accounts,
        transactions=transactions,
        ground_truth_rings=[],
    )
    return AMLSimLoadResult(
        success=True,
        ledger=ledger,
        detected_format="amlsim_native",
        rows_attempted=rows_attempted,
        rows_loaded=len(transactions),
        rows_skipped=skipped,
        skip_reasons=skip_reasons,
        warnings=warnings,
        labels=labels,
        raw_timestamps=raw_ts,
        time_basis=time_basis,
        truncated=truncated,
        label_columns_present=label_cols_present,
    )
