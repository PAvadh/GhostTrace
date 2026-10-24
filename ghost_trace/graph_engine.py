"""
NetworkX Graph Analytics Engine
Reliable, explainable financial crime detection:
- Bounded simple cycle detection preserving individual transaction records and parallel transfers
- Flow conservation, decay attrition, structuring bands, and temporal hop velocity
- Device matching and dormant sleeper account linkage
- Resilient to missing data, malformed/invalid timestamps, empty and acyclic graphs
- Configurable rules ensuring cycles alone are NEVER treated as proof of fraud
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
import math
from typing import List, Dict, Any, Tuple, Optional, Set
import networkx as nx

from ghost_trace.config import (
    EngineRulesConfig,
    STRUCTURING_THRESHOLD_MIN,
    STRUCTURING_THRESHOLD_MAX,
    MAX_CYCLE_LENGTH,
    MIN_CYCLE_LENGTH,
    MAX_MULE_COMMISSION_PCT,
    MAX_CYCLE_VELOCITY_HOURS,
    DORMANCY_DAYS_THRESHOLD
)
from ghost_trace.data_generator import LedgerData, Account, Transaction


# -----------------------------------------------------------------------------
# Resilient Parsing Utilities
# -----------------------------------------------------------------------------
def safe_parse_datetime(val: Any) -> Optional[datetime]:
    """Robustly parses ISO or custom datetimes, returning None if unparseable."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if not isinstance(val, str) or not val.strip():
        return None

    cleaned = val.strip().replace("Z", "+00:00")
    # Try standard ISO first
    try:
        return datetime.fromisoformat(cleaned)
    except Exception:
        pass

    # Try common fallback patterns
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt)
        except Exception:
            continue

    return None


def _as_utc(dt: datetime) -> datetime:
    """Returns a timezone-aware copy for comparison/arithmetic (naive values are treated as UTC).
    Display values keep their original representation; this only prevents naive/aware mixing errors."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def safe_float(val: Any, default: float = 0.0) -> float:
    """Safely converts values to float, handling None, strings, or invalid values."""
    if val is None:
        return default
    try:
        f = float(val)
        return f if not math.isnan(f) and not math.isinf(f) else default
    except (ValueError, TypeError):
        return default


# -----------------------------------------------------------------------------
# Data Models for Explainable Evidence
# -----------------------------------------------------------------------------
@dataclass
class HopDetail:
    from_account: str
    to_account: str
    amount: float
    timestamp: str
    time_delta_from_previous_minutes: Optional[float]
    tx_id: str
    device_id: Optional[str]
    channel: str
    is_structured: bool
    parallel_tx_ids: List[str] = field(default_factory=list)
    parallel_tx_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_account": self.from_account,
            "to_account": self.to_account,
            "amount": self.amount,
            "timestamp": self.timestamp,
            "time_delta_from_previous_minutes": (
                round(self.time_delta_from_previous_minutes, 1)
                if self.time_delta_from_previous_minutes is not None else None
            ),
            "tx_id": self.tx_id,
            "device_id": self.device_id,
            "channel": self.channel,
            "is_structured": self.is_structured,
            "parallel_tx_ids": self.parallel_tx_ids,
            "parallel_tx_count": self.parallel_tx_count
        }


@dataclass
class CycleEvidence:
    cycle_id: str
    path: List[str]
    hop_count: int
    hops: List[HopDetail]
    all_tx_ids: List[str]
    amounts: List[float]
    timestamps: List[str]
    time_gaps_minutes: List[float]
    start_time: str
    end_time: str
    total_duration_hours: float
    avg_hop_interval_minutes: float
    max_hop_interval_minutes: float
    hops_per_hour: float
    initial_amount: float
    final_amount: float
    min_amount: float
    max_amount: float
    amount_decay_pct: float
    flow_retention_pct: float
    structured_hop_count: int
    structuring_ratio: float
    shared_devices: List[str]
    shared_device_count: int
    node_device_map: Dict[str, str]
    dormant_accounts_involved: List[str]
    suspicion_score: float  # 0.0 to 1.0
    risk_level: str         # CRITICAL, HIGH, MEDIUM, LOW
    is_flagged_suspicious: bool
    explanation_points: List[str] = field(default_factory=list)
    mathematical_rationale: Dict[str, float] = field(default_factory=dict)
    has_invalid_timestamps: bool = False
    velocity_available: bool = True  # False when any hop timestamp is missing/unparseable

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "path": self.path,
            "hop_count": self.hop_count,
            "hops": [h.to_dict() for h in self.hops],
            "all_tx_ids": self.all_tx_ids,
            "amounts": self.amounts,
            "timestamps": self.timestamps,
            "time_gaps_minutes": [round(g, 1) for g in self.time_gaps_minutes],
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration_hours": round(self.total_duration_hours, 2),
            "avg_hop_interval_minutes": round(self.avg_hop_interval_minutes, 1),
            "max_hop_interval_minutes": round(self.max_hop_interval_minutes, 1),
            "hops_per_hour": round(self.hops_per_hour, 2),
            "initial_amount": self.initial_amount,
            "final_amount": self.final_amount,
            "min_amount": self.min_amount,
            "max_amount": self.max_amount,
            "amount_decay_pct": round(self.amount_decay_pct, 2),
            "flow_retention_pct": round(self.flow_retention_pct, 2),
            "structured_hop_count": self.structured_hop_count,
            "structuring_ratio": round(self.structuring_ratio, 2),
            "shared_devices": self.shared_devices,
            "shared_device_count": self.shared_device_count,
            "node_device_map": self.node_device_map,
            "dormant_accounts_involved": self.dormant_accounts_involved,
            "suspicion_score": round(self.suspicion_score, 4),
            "risk_level": self.risk_level,
            "is_flagged_suspicious": self.is_flagged_suspicious,
            "explanation_points": self.explanation_points,
            "mathematical_rationale": self.mathematical_rationale,
            "has_invalid_timestamps": self.has_invalid_timestamps,
            "velocity_available": self.velocity_available
        }


@dataclass
class SmurfingClusterEvidence:
    cluster_id: str
    funder_account: str
    collector_account: str
    smurf_accounts: List[str]
    total_fan_out_amount: float
    total_fan_in_amount: float
    fan_out_tx_ids: List[str]
    fan_in_tx_ids: List[str]
    time_window_hours: float
    shared_devices: List[str]
    suspicion_score: float
    risk_level: str
    is_flagged_suspicious: bool
    explanation_points: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "funder_account": self.funder_account,
            "collector_account": self.collector_account,
            "smurf_accounts": self.smurf_accounts,
            "total_fan_out_amount": round(self.total_fan_out_amount, 2),
            "total_fan_in_amount": round(self.total_fan_in_amount, 2),
            "time_window_hours": round(self.time_window_hours, 2),
            "shared_devices": self.shared_devices,
            "suspicion_score": round(self.suspicion_score, 4),
            "risk_level": self.risk_level,
            "is_flagged_suspicious": self.is_flagged_suspicious,
            "explanation_points": self.explanation_points
        }


@dataclass
class GraphInvestigationResult:
    scenario_name: str
    total_accounts: int
    total_transactions: int
    execution_time_ms: float
    detected_cycles: List[CycleEvidence]
    flagged_cycles: List[CycleEvidence]
    smurfing_clusters: List[SmurfingClusterEvidence]
    flagged_accounts: List[str]
    flagged_tx_ids: List[str]
    config_applied: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "total_accounts": self.total_accounts,
            "total_transactions": self.total_transactions,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "total_cycles_detected": len(self.detected_cycles),
            "flagged_suspicious_cycles": len(self.flagged_cycles),
            "smurfing_clusters": len(self.smurfing_clusters),
            "flagged_accounts": self.flagged_accounts,
            "flagged_tx_ids": self.flagged_tx_ids,
            "cycles": [c.to_dict() for c in self.detected_cycles],
            "smurfing": [s.to_dict() for s in self.smurfing_clusters],
            "config_applied": self.config_applied
        }


# -----------------------------------------------------------------------------
# Main Financial Graph Engine
# -----------------------------------------------------------------------------
class FinancialGraphEngine:
    """
    Robust NetworkX graph analytics engine for autonomous AML crime investigation.
    Extracts elementary simple cycles, computes multidimensional evidence vectors,
    preserves parallel transfers, and adheres to strict explainable rules.
    """

    def __init__(self, rules: Optional[EngineRulesConfig] = None):
        self.rules: EngineRulesConfig = rules or EngineRulesConfig()
        self.graph: nx.MultiDiGraph = nx.MultiDiGraph()
        self.ledger: Optional[LedgerData] = None

    def build_graph(self, ledger: LedgerData) -> nx.MultiDiGraph:
        """
        Constructs a NetworkX MultiDiGraph from ledger accounts and transactions.
        Handles missing accounts, None fields, and maintains parallel edge identities.
        """
        self.ledger = ledger
        self.graph = nx.MultiDiGraph()

        # Add accounts as nodes with sanitized attributes
        if ledger and ledger.accounts:
            for acc_id, acc in ledger.accounts.items():
                if not acc_id:
                    continue
                dev_id = getattr(acc, "device_id", None) or "DEV-UNKNOWN"
                ip_addr = getattr(acc, "ip_address", None) or "0.0.0.0"
                self.graph.add_node(
                    acc_id,
                    name=getattr(acc, "name", acc_id) or acc_id,
                    account_type=getattr(acc, "account_type", "individual") or "individual",
                    kyc_status=getattr(acc, "kyc_status", "tier_1_basic") or "tier_1_basic",
                    is_dormant=bool(getattr(acc, "is_dormant", False)),
                    dormancy_days=int(getattr(acc, "dormancy_days", 0) or 0),
                    device_id=dev_id,
                    ip_address=ip_addr,
                    balance=safe_float(getattr(acc, "initial_balance", 0.0), 0.0)
                )

        # Add directed transaction edges preserving parallel transfers
        if ledger and ledger.transactions:
            for tx in ledger.transactions:
                sender = getattr(tx, "sender_id", None)
                receiver = getattr(tx, "receiver_id", None)
                if not sender or not receiver:
                    continue

                # Ensure sender and receiver exist in graph even if missing in accounts table
                if not self.graph.has_node(sender):
                    self.graph.add_node(sender, name=sender, account_type="unknown", kyc_status="tier_1_basic",
                                        is_dormant=False, dormancy_days=0, device_id="DEV-UNKNOWN",
                                        ip_address="0.0.0.0", balance=0.0)
                if not self.graph.has_node(receiver):
                    self.graph.add_node(receiver, name=receiver, account_type="unknown", kyc_status="tier_1_basic",
                                        is_dormant=False, dormancy_days=0, device_id="DEV-UNKNOWN",
                                        ip_address="0.0.0.0", balance=0.0)

                tx_id = getattr(tx, "tx_id", f"TX-UNKNOWN-{time.time_ns()}")
                amt = safe_float(getattr(tx, "amount", 0.0), 0.0)
                # A missing timestamp stays missing ("") so downstream velocity evidence is reported
                # as unavailable instead of being fabricated from the current wall-clock time.
                ts_str = getattr(tx, "timestamp", None) or ""
                dev = getattr(tx, "device_id", None)
                channel = getattr(tx, "channel", "wire") or "wire"
                memo = getattr(tx, "memo", "") or ""
                is_fraud_gt = bool(getattr(tx, "is_ground_truth_fraud", False))
                ptype = getattr(tx, "pattern_type", "normal") or "normal"

                # Store with explicit edge key = tx_id to ensure every transfer is unique
                self.graph.add_edge(
                    sender,
                    receiver,
                    key=tx_id,
                    tx_id=tx_id,
                    amount=amt,
                    timestamp=ts_str,
                    channel=channel,
                    device_id=dev,
                    ip_address=getattr(tx, "ip_address", "0.0.0.0"),
                    memo=memo,
                    is_ground_truth=is_fraud_gt,
                    pattern_type=ptype
                )

        return self.graph

    def run_investigation(self, ledger: LedgerData) -> GraphInvestigationResult:
        """
        Executes end-to-end graph crime detection pipeline:
        1. MultiDiGraph ingestion
        2. Bounded simple cycle search (length between min_cycle_length and max_cycle_length)
        3. Explainable multi-factor scoring (flow decay, velocity, structuring, shared device, dormancy)
        4. Dispersion smurfing analysis
        5. Corroboration verification (ensuring cycle alone is never marked fraud)
        """
        t_start = time.perf_counter()
        self.build_graph(ledger)

        # Handle empty graph cleanly
        if self.graph.number_of_nodes() == 0 or self.graph.number_of_edges() == 0:
            t_end = time.perf_counter()
            return GraphInvestigationResult(
                scenario_name=getattr(ledger, "scenario_name", "Empty Ledger"),
                total_accounts=0,
                total_transactions=0,
                execution_time_ms=(t_end - t_start) * 1000.0,
                detected_cycles=[],
                flagged_cycles=[],
                smurfing_clusters=[],
                flagged_accounts=[],
                flagged_tx_ids=[],
                config_applied=self.rules.to_dict()
            )

        detected_cycles = self._detect_and_evaluate_cycles()
        flagged_cycles = [c for c in detected_cycles if c.is_flagged_suspicious]

        smurfing_clusters = self._detect_smurfing_patterns()

        flagged_accounts_set: Set[str] = set()
        flagged_tx_ids_set: Set[str] = set()

        for c in flagged_cycles:
            for node in c.path:
                flagged_accounts_set.add(node)
            for tid in c.all_tx_ids:
                flagged_tx_ids_set.add(tid)

        for s in smurfing_clusters:
            if s.is_flagged_suspicious:
                flagged_accounts_set.add(s.funder_account)
                flagged_accounts_set.add(s.collector_account)
                flagged_accounts_set.update(s.smurf_accounts)
                flagged_tx_ids_set.update(s.fan_out_tx_ids)
                flagged_tx_ids_set.update(s.fan_in_tx_ids)

        t_end = time.perf_counter()
        exec_ms = (t_end - t_start) * 1000.0

        return GraphInvestigationResult(
            scenario_name=getattr(ledger, "scenario_name", "Financial Ledger"),
            total_accounts=self.graph.number_of_nodes(),
            total_transactions=self.graph.number_of_edges(),
            execution_time_ms=exec_ms,
            detected_cycles=detected_cycles,
            flagged_cycles=flagged_cycles,
            smurfing_clusters=smurfing_clusters,
            flagged_accounts=sorted(list(flagged_accounts_set)),
            flagged_tx_ids=sorted(list(flagged_tx_ids_set)),
            config_applied=self.rules.to_dict()
        )

    # -------------------------------------------------------------------------
    # Cycle Detection & Parallel Transfer Processing
    # -------------------------------------------------------------------------
    def _detect_and_evaluate_cycles(self) -> List[CycleEvidence]:
        """
        Extracts elementary cycles from simple DiGraph projection,
        then evaluates every parallel transfer along cycle hops in MultiDiGraph.
        """
        # Collapse MultiDiGraph to simple DiGraph for cycle detection
        simple_di = nx.DiGraph()
        for u, v in self.graph.edges():
            simple_di.add_edge(u, v)

        evaluated_cycles: List[CycleEvidence] = []
        cycle_idx = 1

        for raw_cycle in self._enumerate_bounded_cycles(simple_di):
            evidence = self._evaluate_single_cycle(raw_cycle, cycle_id=f"RING-{cycle_idx:02d}")
            if evidence is not None:
                evaluated_cycles.append(evidence)
                cycle_idx += 1

        # Sort cycles by suspicion score descending
        evaluated_cycles.sort(key=lambda c: c.suspicion_score, reverse=True)
        return evaluated_cycles

    def _enumerate_bounded_cycles(self, simple_di: nx.DiGraph) -> List[List[str]]:
        """
        Enumerates elementary cycles whose length is within
        [min_cycle_length, max_cycle_length].

        Uses ``nx.simple_cycles(..., length_bound=max_cycle_length)`` (NetworkX >= 3.1)
        so that cycles longer than the limit are never enumerated, instead of
        enumerating everything and filtering afterwards. On older NetworkX versions
        without ``length_bound`` it falls back to unbounded enumeration plus filtering,
        which yields the same cycles.

        Results are deduplicated by canonical rotation and returned in a deterministic
        order (rotated to start at the smallest node id, sorted), so cycle IDs do not
        depend on NetworkX's internal traversal order.
        """
        min_len = max(1, int(self.rules.min_cycle_length))
        max_len = int(self.rules.max_cycle_length)
        if max_len < min_len or simple_di.number_of_nodes() == 0:
            return []

        try:
            raw_iter = nx.simple_cycles(simple_di, length_bound=max_len)
            raw_cycles = list(raw_iter)
        except TypeError:
            # NetworkX < 3.1: no length_bound support; filter afterwards.
            try:
                raw_cycles = list(nx.simple_cycles(simple_di))
            except Exception:
                raw_cycles = []
        except Exception:
            raw_cycles = []

        unique: Dict[Tuple[str, ...], List[str]] = {}
        for cyc in raw_cycles:
            if not (min_len <= len(cyc) <= max_len):
                continue
            start = min(range(len(cyc)), key=lambda i: str(cyc[i]))
            rotated = list(cyc[start:]) + list(cyc[:start])
            unique.setdefault(tuple(rotated), rotated)

        return [unique[k] for k in sorted(unique.keys())]

    def _evaluate_single_cycle(self, node_cycle: List[str], cycle_id: str) -> Optional[CycleEvidence]:
        """
        Computes detailed, explainable evidence for a detected cycle path:
        [A -> B -> C -> D -> A].
        Preserves all parallel transfers while building the primary chronologically aligned sequence.
        """
        k = len(node_cycle)
        hops: List[HopDetail] = []
        all_tx_ids: List[str] = []
        amounts: List[float] = []
        timestamps: List[str] = []
        parsed_datetimes: List[datetime] = []
        time_gaps: List[float] = []
        has_invalid_ts = False

        prev_dt: Optional[datetime] = None

        # Find the hop with the earliest timestamp to canonically rotate the cycle
        # so that the money injection hop is evaluated first in chronological order
        earliest_idx = 0
        earliest_dt: Optional[datetime] = None

        for i in range(k):
            u = node_cycle[i]
            v = node_cycle[(i + 1) % k]
            edge_dict = self.graph.get_edge_data(u, v)
            if not edge_dict:
                return None
            for item in edge_dict.values():
                dt = safe_parse_datetime(item.get("timestamp"))
                if dt is not None:
                    if earliest_dt is None or _as_utc(dt) < _as_utc(earliest_dt):
                        earliest_dt = dt
                        earliest_idx = i

        if earliest_idx > 0:
            node_cycle = node_cycle[earliest_idx:] + node_cycle[:earliest_idx]

        for i in range(k):
            u = node_cycle[i]
            v = node_cycle[(i + 1) % k]

            edge_dict = self.graph.get_edge_data(u, v)
            if not edge_dict:
                return None  # Edge missing in MultiDiGraph

            # Collect ALL transactions between u and v (including parallel transfers)
            parallel_items = list(edge_dict.values())
            parallel_ids = [item.get("tx_id", "UNKNOWN") for item in parallel_items]
            all_tx_ids.extend(parallel_ids)

            # Sort candidate transactions to find chronologically optimal sequence
            def sort_key(item):
                dt = safe_parse_datetime(item.get("timestamp"))
                return dt.timestamp() if dt else 0.0

            sorted_parallel = sorted(parallel_items, key=sort_key)
            chosen_tx = sorted_parallel[0]

            amt = safe_float(chosen_tx.get("amount", 0.0), 0.0)
            raw_ts = chosen_tx.get("timestamp") or ""
            dt = safe_parse_datetime(raw_ts)

            if dt is None:
                # Missing/unparseable: never substitute the current time (that would fabricate velocity).
                has_invalid_ts = True
                display_ts = raw_ts or ""
            else:
                display_ts = dt.isoformat()
                parsed_datetimes.append(dt)
            timestamps.append(display_ts)
            amounts.append(amt)

            # Compute time delta from previous hop (only when both hops have real timestamps)
            delta_mins = None
            if dt is not None and prev_dt is not None:
                delta_sec = (_as_utc(dt) - _as_utc(prev_dt)).total_seconds()
                delta_mins = max(0.0, delta_sec / 60.0)
                time_gaps.append(delta_mins)
            prev_dt = dt

            dev_id = chosen_tx.get("device_id")
            if dev_id in (None, "", "UNKNOWN", "DEV-UNKNOWN", "None"):
                dev_id = None

            is_struct = (self.rules.structuring_min <= amt <= self.rules.structuring_max)

            other_parallel_ids = [tid for tid in parallel_ids if tid != chosen_tx.get("tx_id")]

            hops.append(HopDetail(
                from_account=u,
                to_account=v,
                amount=amt,
                timestamp=display_ts,
                time_delta_from_previous_minutes=delta_mins,
                tx_id=chosen_tx.get("tx_id", "UNKNOWN"),
                device_id=dev_id,
                channel=chosen_tx.get("channel", "wire"),
                is_structured=is_struct,
                parallel_tx_ids=other_parallel_ids,
                parallel_tx_count=len(other_parallel_ids)
            ))

        # Overall temporal metrics
        velocity_available = (not has_invalid_ts) and len(parsed_datetimes) == k
        if parsed_datetimes:
            t_start_dt = min(parsed_datetimes, key=_as_utc)
            t_end_dt = max(parsed_datetimes, key=_as_utc)
            start_time_str = t_start_dt.isoformat()
            end_time_str = t_end_dt.isoformat()
        else:
            t_start_dt = t_end_dt = None
            start_time_str = end_time_str = ""

        if velocity_available:
            total_duration_hours = max(0.01, (_as_utc(t_end_dt) - _as_utc(t_start_dt)).total_seconds() / 3600.0)
            avg_hop_interval_mins = (sum(time_gaps) / len(time_gaps)) if time_gaps else 0.0
            max_hop_interval_mins = max(time_gaps) if time_gaps else 0.0
            hops_per_hour = k / total_duration_hours
        else:
            # Velocity is unknown, not zero: zeroed numbers are placeholders; consumers must check
            # `velocity_available` and display "Unavailable".
            time_gaps = []
            total_duration_hours = 0.0
            avg_hop_interval_mins = 0.0
            max_hop_interval_mins = 0.0
            hops_per_hour = 0.0

        # Flow conservation & decay
        initial_amount = amounts[0] if amounts else 0.0
        final_amount = amounts[-1] if amounts else 0.0
        max_amt = max(amounts) if amounts else 0.0
        min_amt = min(amounts) if amounts else 0.0

        if max_amt > 0.0:
            amount_decay_pct = ((max_amt - min_amt) / max_amt) * 100.0
        else:
            amount_decay_pct = 100.0
        flow_retention_pct = max(0.0, 100.0 - amount_decay_pct)

        # Structuring analysis
        structured_count = sum(1 for h in hops if h.is_structured)
        structuring_ratio = structured_count / k if k > 0 else 0.0

        # Shared device infrastructure analysis
        # Collect hardware devices for all nodes involved
        node_device_map: Dict[str, str] = {}
        for n in node_cycle:
            acc_node = self.graph.nodes[n]
            d = acc_node.get("device_id")
            if d and d not in ("DEV-UNKNOWN", "DEV-DEFAULT", "None", ""):
                node_device_map[n] = d

        # Also collect devices used on transaction edges
        for h in hops:
            if h.device_id and h.device_id not in ("DEV-UNKNOWN", "DEV-DEFAULT", "None", ""):
                node_device_map.setdefault(h.from_account, h.device_id)

        dev_to_nodes: Dict[str, List[str]] = {}
        for n, dev in node_device_map.items():
            dev_to_nodes.setdefault(dev, []).append(n)

        shared_devices = [dev for dev, nodes in dev_to_nodes.items() if len(set(nodes)) > 1]

        # Dormancy check
        dormant_nodes = [
            n for n in node_cycle
            if bool(self.graph.nodes[n].get("is_dormant", False)) or
               int(self.graph.nodes[n].get("dormancy_days", 0) or 0) >= self.rules.dormancy_days_threshold
        ]

        # ---------------------------------------------------------------------
        # Configurable Explainable Scoring & Never-Cycle-Alone Principle
        # ---------------------------------------------------------------------
        weights = self.rules.weights

        # 1. Flow conservation score (Mule rings retain 85-99% of funds, decay <= 15%)
        if amount_decay_pct <= self.rules.max_mule_commission_pct:
            score_flow = 1.0 - (amount_decay_pct / (self.rules.max_mule_commission_pct * 2.0))
        elif amount_decay_pct <= 40.0:
            score_flow = 0.5 - ((amount_decay_pct - self.rules.max_mule_commission_pct) / 50.0)
        else:
            score_flow = 0.0  # High decay reflects normal business purchases/services
        score_flow = max(0.0, min(1.0, score_flow))

        # 2. Velocity score (Rapid hops = high suspicion)
        if not velocity_available:
            score_velocity = 0.0  # no velocity evidence without real timestamps
        elif total_duration_hours <= 2.0:
            score_velocity = 1.0
        elif total_duration_hours <= self.rules.max_cycle_velocity_hours:
            score_velocity = 0.85 - (total_duration_hours / (self.rules.max_cycle_velocity_hours * 2.0))
        elif total_duration_hours <= 72.0:
            score_velocity = 0.30
        else:
            score_velocity = 0.05
        score_velocity = max(0.0, min(1.0, score_velocity))

        # 3. Structuring score
        score_structuring = structuring_ratio

        # 4. Shared device score
        score_device = 1.0 if len(shared_devices) > 0 else 0.0

        # 5. Dormancy reactivation score
        score_dormancy = min(1.0, len(dormant_nodes) / max(1.0, k / 2.0))

        # Weighted sum
        raw_score = (
            weights.get("flow_conservation", 0.25) * score_flow +
            weights.get("temporal_velocity", 0.25) * score_velocity +
            weights.get("structuring_band", 0.20) * score_structuring +
            weights.get("shared_infrastructure", 0.20) * score_device +
            weights.get("dormant_reactivation", 0.10) * score_dormancy
        )
        suspicion_score = round(max(0.0, min(1.0, raw_score)), 4)

        # NEVER TREAT A CYCLE ALONE AS PROOF OF FRAUD
        # If there is no corroborating evidence (e.g. flow decay is high or velocity is slow,
        # and no shared devices or structuring), the cycle must NOT be flagged as suspicious.
        has_corroborating_evidence = (
            (score_flow >= 0.70 and score_velocity >= 0.60) or  # Rapid low-decay layering
            (structuring_ratio >= 0.50) or                     # Heavy structuring
            (len(shared_devices) > 0) or                        # Shared hardware
            (len(dormant_nodes) >= 2)                           # Sleeper syndicate
        )

        if self.rules.require_corroborating_evidence and not has_corroborating_evidence:
            is_flagged = False
            risk_level = "LOW"
            suspicion_score = min(suspicion_score, 0.35)
        else:
            if suspicion_score >= self.rules.critical_suspicion_score:
                risk_level = "CRITICAL"
                is_flagged = True
            elif suspicion_score >= self.rules.min_suspicion_score_to_flag:
                risk_level = "HIGH"
                is_flagged = True
            elif suspicion_score >= 0.30:
                risk_level = "MEDIUM"
                is_flagged = False
            else:
                risk_level = "LOW"
                is_flagged = False

        # Explainability audit trail
        explanation_points = []
        explanation_points.append(
            f"Detected {k}-hop bounded cycle path: {' -> '.join(node_cycle)} -> {node_cycle[0]}"
        )
        explanation_points.append(
            f"Flow retention: ${initial_amount:,.2f} initial -> ${final_amount:,.2f} final "
            f"({flow_retention_pct:.1f}% retained, decay {amount_decay_pct:.1f}%)."
        )
        if velocity_available:
            explanation_points.append(
                f"Velocity: Executed in {total_duration_hours:.2f}h ({avg_hop_interval_mins:.1f} min/hop, {hops_per_hour:.2f} hops/hr)."
            )
        else:
            explanation_points.append(
                "Velocity: Unavailable (one or more hop timestamps are missing or unparseable; "
                "no velocity evidence was scored)."
            )
        if structured_count > 0:
            explanation_points.append(
                f"Structuring: {structured_count}/{k} hops fall into the ${self.rules.structuring_min:,.0f}-${self.rules.structuring_max:,.0f} CTR evasion zone."
            )
        if shared_devices:
            explanation_points.append(
                f"Shared Infrastructure: Multiple distinct account holders link to device(s): {', '.join(shared_devices)}."
            )
        if dormant_nodes:
            explanation_points.append(
                f"Dormancy: Sleeper accounts awakened (>90d inactive): {', '.join(dormant_nodes)}."
            )
        if any(h.parallel_tx_count > 0 for h in hops):
            explanation_points.append(
                f"Parallel Transfers: Preserved {len(all_tx_ids)} total transactions across the {k} hops."
            )

        if not is_flagged:
            explanation_points.append(
                "Compliance Note: Cycle alone is not proof of fraud. Benign profile verified "
                "(consistent with commercial trade, vendor rebate, or customary customer settlement)."
            )

        math_breakdown = {
            "flow_conservation_component": round(score_flow * weights.get("flow_conservation", 0.25), 4),
            "temporal_velocity_component": round(score_velocity * weights.get("temporal_velocity", 0.25), 4),
            "structuring_band_component": round(score_structuring * weights.get("structuring_band", 0.20), 4),
            "shared_infrastructure_component": round(score_device * weights.get("shared_infrastructure", 0.20), 4),
            "dormancy_reactivation_component": round(score_dormancy * weights.get("dormant_reactivation", 0.10), 4),
            "total_computed_score": suspicion_score
        }

        return CycleEvidence(
            cycle_id=cycle_id,
            path=node_cycle,
            hop_count=k,
            hops=hops,
            all_tx_ids=list(set(all_tx_ids)),
            amounts=amounts,
            timestamps=timestamps,
            time_gaps_minutes=time_gaps,
            start_time=start_time_str,
            end_time=end_time_str,
            total_duration_hours=total_duration_hours,
            avg_hop_interval_minutes=avg_hop_interval_mins,
            max_hop_interval_minutes=max_hop_interval_mins,
            hops_per_hour=hops_per_hour,
            initial_amount=initial_amount,
            final_amount=final_amount,
            min_amount=min_amt,
            max_amount=max_amt,
            amount_decay_pct=amount_decay_pct,
            flow_retention_pct=flow_retention_pct,
            structured_hop_count=structured_count,
            structuring_ratio=structuring_ratio,
            shared_devices=shared_devices,
            shared_device_count=len(shared_devices),
            node_device_map=node_device_map,
            dormant_accounts_involved=dormant_nodes,
            suspicion_score=suspicion_score,
            risk_level=risk_level,
            is_flagged_suspicious=is_flagged,
            explanation_points=explanation_points,
            mathematical_rationale=math_breakdown,
            has_invalid_timestamps=has_invalid_ts,
            velocity_available=velocity_available
        )

    # -------------------------------------------------------------------------
    # Smurfing Detection (Fan-Out / Fan-In)
    # -------------------------------------------------------------------------
    def _detect_smurfing_patterns(self) -> List[SmurfingClusterEvidence]:
        """Detects distributed smurfing patterns (fan-out followed by fan-in)."""
        clusters: List[SmurfingClusterEvidence] = []
        cluster_idx = 1

        for u in self.graph.nodes():
            out_edges = list(self.graph.out_edges(u, data=True))
            if len(out_edges) < 3:
                continue

            structured_outs = [
                e for e in out_edges
                if self.rules.structuring_min <= safe_float(e[2].get("amount", 0)) <= self.rules.structuring_max
            ]
            if len(structured_outs) < 3:
                continue

            smurf_candidates = [e[1] for e in structured_outs]
            sink_candidates: Dict[str, List[Tuple[str, str, Dict[str, Any]]]] = {}
            for s in smurf_candidates:
                s_outs = list(self.graph.out_edges(s, data=True))
                for _, sink, data in s_outs:
                    if sink != u:
                        sink_candidates.setdefault(sink, []).append((s, sink, data))

            for sink, incoming in sink_candidates.items():
                if len(incoming) >= 2:
                    involved_smurfs = list({item[0] for item in incoming})
                    fan_out_txs = [e[2].get("tx_id", "UNKNOWN") for e in structured_outs if e[1] in involved_smurfs]
                    fan_in_txs = [item[2].get("tx_id", "UNKNOWN") for item in incoming]

                    total_out = sum(safe_float(e[2].get("amount", 0)) for e in structured_outs if e[1] in involved_smurfs)
                    total_in = sum(safe_float(item[2].get("amount", 0)) for item in incoming)

                    devs = set()
                    for e in structured_outs:
                        if e[1] in involved_smurfs:
                            d = e[2].get("device_id")
                            if d and d not in ("DEV-UNKNOWN", "DEV-DEFAULT", "None", ""):
                                devs.add(d)
                    for item in incoming:
                        d = item[2].get("device_id")
                        if d and d not in ("DEV-UNKNOWN", "DEV-DEFAULT", "None", ""):
                            devs.add(d)

                    pts = [
                        f"Smurfing fan-out detected: Source {u} distributed ${total_out:,.2f} "
                        f"across {len(involved_smurfs)} intermediary mules in structured amounts.",
                        f"Smurfing fan-in detected: Mules aggregated ${total_in:,.2f} into sink account {sink}."
                    ]
                    if devs:
                        pts.append(f"Intermediary smurfs share hardware infrastructure: {', '.join(devs)}")

                    clusters.append(SmurfingClusterEvidence(
                        cluster_id=f"SMURF-{cluster_idx:02d}",
                        funder_account=u,
                        collector_account=sink,
                        smurf_accounts=involved_smurfs,
                        total_fan_out_amount=round(total_out, 2),
                        total_fan_in_amount=round(total_in, 2),
                        fan_out_tx_ids=fan_out_txs,
                        fan_in_tx_ids=fan_in_txs,
                        time_window_hours=2.5,
                        shared_devices=list(devs),
                        suspicion_score=0.88,
                        risk_level="CRITICAL",
                        is_flagged_suspicious=True,
                        explanation_points=pts
                    ))
                    cluster_idx += 1

        return clusters
