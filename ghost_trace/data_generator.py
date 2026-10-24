"""
Synthetic Transaction & Ledger Generator
Generates realistic financial transaction graphs, injected money mule rings,
distributed smurfing, and legitimate business loops for honest benchmarking.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
import random
from typing import List, Dict, Any, Optional

from ghost_trace.config import (
    STRUCTURING_THRESHOLD_MIN,
    STRUCTURING_THRESHOLD_MAX,
    BSA_REPORTING_LIMIT
)


@dataclass
class Account:
    account_id: str
    name: str
    account_type: str  # individual, merchant, payroll, shell_company, crypto_ramp
    kyc_status: str    # verified_full, tier_1_basic, high_risk_flagged
    is_dormant: bool = False
    dormancy_days: int = 0
    device_id: str = "DEV-DEFAULT"
    ip_address: str = "192.168.1.1"
    country: str = "US"
    initial_balance: float = 10000.0
    created_at: str = "2025-01-01T00:00:00"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Transaction:
    tx_id: str
    sender_id: str
    receiver_id: str
    amount: float
    timestamp: str  # ISO format string
    channel: str    # wire, ach, p2p, crypto_ramp
    device_id: str
    ip_address: str
    memo: str = ""
    is_ground_truth_fraud: bool = False
    pattern_type: str = "normal"  # normal, vampire_ring, smurfing, layering, legit_rebate

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LedgerData:
    scenario_name: str
    description: str
    accounts: Dict[str, Account] = field(default_factory=dict)
    transactions: List[Transaction] = field(default_factory=list)
    ground_truth_rings: List[Dict[str, Any]] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def get_account(self, account_id: str) -> Optional[Account]:
        return self.accounts.get(account_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "description": self.description,
            "account_count": len(self.accounts),
            "transaction_count": len(self.transactions),
            "ground_truth_ring_count": len(self.ground_truth_rings),
            "generated_at": self.generated_at,
            "transactions": [tx.to_dict() for tx in self.transactions],
            "accounts": {k: v.to_dict() for k, v in self.accounts.items()},
            "ground_truth_rings": self.ground_truth_rings
        }


class SyntheticLedgerGenerator:
    """Deterministic generator for financial fraud and normal banking topologies."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
        self._tx_counter = 1000
        self._acc_counter = 100

    def _next_tx_id(self) -> str:
        self._tx_counter += 1
        return f"TX-GT-{self._tx_counter}"

    def _next_acc_id(self, prefix: str = "ACC") -> str:
        self._acc_counter += 1
        return f"{prefix}-{self._acc_counter}"

    def generate_scenario(self, scenario_type: str = "mixed_ledger") -> LedgerData:
        """
        Available scenarios:
        - 'vampire_ring': Dedicated circular money mule ring hopping illicit funds.
        - 'smurfing': Distributed fan-out and fan-in smurfing structuring.
        - 'legit_rebate': Legitimate merchant loop (supplier-retailer rebate) for negative control.
        - 'dormant_reactivation': Ring utilizing dormant accounts suddenly awakened with shared device.
        - 'mixed_ledger': Production-style ledger with normal noise, 2 fraud rings, and 1 legit rebate loop.
        """
        if scenario_type == "vampire_ring":
            return self._build_vampire_ring_scenario()
        elif scenario_type == "smurfing":
            return self._build_smurfing_scenario()
        elif scenario_type == "legit_rebate":
            return self._build_legit_rebate_scenario()
        elif scenario_type == "dormant_reactivation":
            return self._build_dormant_reactivation_scenario()
        elif scenario_type == "mixed_ledger":
            return self._build_mixed_ledger_scenario()
        else:
            return self._build_mixed_ledger_scenario()

    def _build_vampire_ring_scenario(self) -> LedgerData:
        """Single-focus Vampire Ledger mule ring with background noise."""
        ledger = LedgerData(
            scenario_name="Vampire Mule Ring (Circular Layering)",
            description="Circular 4-hop mule ring with structured amounts ($9,800 -> $9,400), "
                        "tight 12-minute velocity hops, and a shared device fingerprint."
        )
        self._add_background_traffic(ledger, num_accounts=15, num_txs=25)
        self._inject_vampire_cycle(
            ledger,
            start_time=datetime(2026, 10, 20, 14, 0, 0),
            base_amount=9800.0,
            hop_time_minutes=12,
            ring_name="Vampire-Ring-Alpha"
        )
        return ledger

    def _build_smurfing_scenario(self) -> LedgerData:
        """Smurfing fan-out and fan-in structuring scenario."""
        ledger = LedgerData(
            scenario_name="Distributed Smurfing (Fan-Out / Fan-In)",
            description="Dirty funding entity fans out structured batches (<$10k) to 4 mules, "
                        "who aggregate funds into a destination shell company within 90 minutes."
        )
        self._add_background_traffic(ledger, num_accounts=15, num_txs=25)
        self._inject_smurfing_network(ledger, base_amount=38000.0, num_smurfs=4)
        return ledger

    def _build_legit_rebate_scenario(self) -> LedgerData:
        """Negative control loop: commercial supply chain with volume rebate."""
        ledger = LedgerData(
            scenario_name="Commercial Supply Chain Loop (Legitimate Negative Control)",
            description="Manufacturer -> Supplier -> Logistics -> Manufacturer annual rebate. "
                        "Legitimate loop with high decay (>70%), days-long delays, and distinct devices."
        )
        self._add_background_traffic(ledger, num_accounts=20, num_txs=35)
        self._inject_legitimate_commercial_loop(ledger)
        return ledger

    def _build_dormant_reactivation_scenario(self) -> LedgerData:
        """Dormant mule ring with sudden awakening and shared hardware device."""
        ledger = LedgerData(
            scenario_name="Dormant Mule Awakening (Synthetic Vampire Ring)",
            description="Accounts dormant for >180 days suddenly execute rapid structured transfers "
                        "from a shared hardware device DEV-MULE-SHADOW."
        )
        self._add_background_traffic(ledger, num_accounts=12, num_txs=20)
        self._inject_vampire_cycle(
            ledger,
            start_time=datetime(2026, 10, 22, 2, 15, 0),
            base_amount=9950.0,
            hop_time_minutes=8,
            ring_name="Shadow-Dormant-Ring",
            dormant_count=3,
            shared_device_id="DEV-MULE-SHADOW-X7"
        )
        return ledger

    def _build_mixed_ledger_scenario(self) -> LedgerData:
        """Comprehensive realistic benchmark ledger with multiple patterns."""
        ledger = LedgerData(
            scenario_name="Omni-Ledger: Mixed Production Portfolio",
            description="Enterprise ledger containing 45+ accounts, background commercial & retail traffic, "
                        "1 high-velocity Vampire Ring, 1 Dormant Smurfing cluster, and 1 Legit Rebate Loop."
        )
        self._add_background_traffic(ledger, num_accounts=30, num_txs=55)
        # Ring 1: High velocity vampire cycle
        self._inject_vampire_cycle(
            ledger,
            start_time=datetime(2026, 10, 23, 10, 30, 0),
            base_amount=9850.0,
            hop_time_minutes=11,
            ring_name="Vampire-Cycle-A1"
        )
        # Ring 2: Dormant ring
        self._inject_vampire_cycle(
            ledger,
            start_time=datetime(2026, 10, 23, 16, 45, 0),
            base_amount=9600.0,
            hop_time_minutes=15,
            ring_name="Vampire-Cycle-B2",
            dormant_count=2,
            shared_device_id="DEV-PROX-77"
        )
        # Legit loop: negative control to test precision and avoid false positives
        self._inject_legitimate_commercial_loop(ledger)
        return ledger

    # -------------------------------------------------------------------------
    # Internal Injectors
    # -------------------------------------------------------------------------

    def _inject_vampire_cycle(
        self,
        ledger: LedgerData,
        start_time: datetime,
        base_amount: float = 9800.0,
        hop_time_minutes: int = 12,
        ring_name: str = "Vampire-Ring",
        dormant_count: int = 2,
        shared_device_id: str = "DEV-VAMP-919"
    ):
        """
        Creates a 4-hop circular money mule cycle:
        Mule-1 -> Mule-2 -> Mule-3 -> Mule-4 -> Mule-1 (or controller)
        Amounts slightly decrease by 1-2% mule cut at each hop.
        """
        mule_names = [
            ("MULE-ALPHA", "Viktor Dracul Holdings", "shell_company", True, 210),
            ("MULE-BETA", "Carmilla M. Express", "individual", True, 185),
            ("MULE-GAMMA", "Nocturne Trade LLC", "individual", False, 12),
            ("MULE-DELTA", "Sanguine Logistics", "individual", True, 140)
        ]

        ring_accounts = []
        for i, (mid, name, atype, is_dormant, d_days) in enumerate(mule_names):
            acc_id = f"{ring_name}-{mid}"
            dorm = is_dormant if i < dormant_count else False
            days = d_days if dorm else 5
            acc = Account(
                account_id=acc_id,
                name=name,
                account_type=atype,
                kyc_status="tier_1_basic" if dorm else "high_risk_flagged",
                is_dormant=dorm,
                dormancy_days=days,
                device_id=shared_device_id,  # Shared infrastructure signal
                ip_address="198.51.100.42",   # Shared VPN/Proxy IP
                country="US",
                initial_balance=15000.0,
                created_at="2024-03-15T09:00:00"
            )
            ledger.accounts[acc_id] = acc
            ring_accounts.append(acc_id)

        # Create transactions forming a closed loop
        current_time = start_time
        current_amount = base_amount
        hop_txs = []
        cycle_len = len(ring_accounts)

        for i in range(cycle_len):
            sender = ring_accounts[i]
            receiver = ring_accounts[(i + 1) % cycle_len]
            # Mules retain 1.2% - 2.0% fee per hop
            if i > 0:
                cut_pct = self.rng.uniform(0.012, 0.022)
                current_amount = round(current_amount * (1.0 - cut_pct), 2)

            current_time = current_time + timedelta(minutes=hop_time_minutes + self.rng.randint(-2, 3))
            tx = Transaction(
                tx_id=self._next_tx_id(),
                sender_id=sender,
                receiver_id=receiver,
                amount=current_amount,
                timestamp=current_time.isoformat(),
                channel="p2p_instant" if i % 2 == 0 else "wire_transfer",
                device_id=shared_device_id,
                ip_address="198.51.100.42",
                memo=f"Settlement invoice ref #{self.rng.randint(1000, 9999)}",
                is_ground_truth_fraud=True,
                pattern_type="vampire_ring"
            )
            ledger.transactions.append(tx)
            hop_txs.append(tx.tx_id)

        ledger.ground_truth_rings.append({
            "ring_id": ring_name,
            "type": "vampire_mule_cycle",
            "cycle_nodes": ring_accounts,
            "tx_ids": hop_txs,
            "initial_amount": base_amount,
            "final_amount": current_amount,
            "shared_device": shared_device_id,
            "is_fraud": True
        })

    def _inject_smurfing_network(
        self,
        ledger: LedgerData,
        base_amount: float = 38000.0,
        num_smurfs: int = 4
    ):
        """
        Smurfing: Source account fans out structured sums under $10k to intermediate smurfs,
        which immediately forward them to a target offshore shell account.
        """
        source_id = "SMURF-SOURCE-DIRT"
        target_id = "SMURF-OFFSHORE-SINK"

        ledger.accounts[source_id] = Account(
            account_id=source_id,
            name="Shadow Syndicate Inflow",
            account_type="shell_company",
            kyc_status="high_risk_flagged",
            initial_balance=100000.0,
            device_id="DEV-SMURF-SRC",
            ip_address="203.0.113.10"
        )
        ledger.accounts[target_id] = Account(
            account_id=target_id,
            name="Bermuda Horizon Ventures",
            account_type="crypto_ramp",
            kyc_status="high_risk_flagged",
            initial_balance=50000.0,
            device_id="DEV-SMURF-SINK",
            ip_address="198.51.100.88"
        )

        smurf_accounts = []
        for i in range(num_smurfs):
            s_id = f"SMURF-MULE-{i+1}"
            acc = Account(
                account_id=s_id,
                name=f"Disposable Runner {i+1}",
                account_type="individual",
                kyc_status="tier_1_basic",
                is_dormant=True,
                dormancy_days=110 + i * 20,
                device_id="DEV-SHARED-SMURF-HUB",
                ip_address=f"203.0.113.{20 + i}"
            )
            ledger.accounts[s_id] = acc
            smurf_accounts.append(s_id)

        # Fan out
        start_time = datetime(2026, 10, 21, 9, 0, 0)
        fan_out_amount = round(base_amount / num_smurfs, 2)
        smurf_txs = []

        for i, s_id in enumerate(smurf_accounts):
            t_fan_out = start_time + timedelta(minutes=15 * i)
            # Structuring: amounts kept between $9,200 and $9,800
            amt = round(min(fan_out_amount * self.rng.uniform(0.95, 1.05), 9850.0), 2)
            tx1 = Transaction(
                tx_id=self._next_tx_id(),
                sender_id=source_id,
                receiver_id=s_id,
                amount=amt,
                timestamp=t_fan_out.isoformat(),
                channel="wire_transfer",
                device_id="DEV-SHARED-SMURF-HUB",
                ip_address=f"203.0.113.{20 + i}",
                memo="Consulting honorarium",
                is_ground_truth_fraud=True,
                pattern_type="smurfing_fan_out"
            )
            ledger.transactions.append(tx1)
            smurf_txs.append(tx1.tx_id)

            # Fan in: smurf sends to offshore sink 20 minutes later
            t_fan_in = t_fan_out + timedelta(minutes=20)
            fee = round(amt * 0.02, 2)
            tx2 = Transaction(
                tx_id=self._next_tx_id(),
                sender_id=s_id,
                receiver_id=target_id,
                amount=amt - fee,
                timestamp=t_fan_in.isoformat(),
                channel="crypto_ramp",
                device_id="DEV-SHARED-SMURF-HUB",
                ip_address=f"203.0.113.{20 + i}",
                memo="Offshore asset purchase",
                is_ground_truth_fraud=True,
                pattern_type="smurfing_fan_in"
            )
            ledger.transactions.append(tx2)
            smurf_txs.append(tx2.tx_id)

        ledger.ground_truth_rings.append({
            "ring_id": "Smurfing-Cluster-1",
            "type": "smurfing_fan_out_in",
            "cycle_nodes": [source_id] + smurf_accounts + [target_id],
            "tx_ids": smurf_txs,
            "total_structured": base_amount,
            "is_fraud": True
        })

    def _inject_legitimate_commercial_loop(self, ledger: LedgerData):
        """
        Negative Control: Commercial circular transaction with valid business rationale.
        Manufacturer -> Tier 1 Supplier -> Logistics Freight -> Manufacturer Volume Rebate.
        Key differences from mule ring:
        - Big time gaps (days / weeks)
        - High amount decay (> 80% change, not retaining funds)
        - Distinct devices and IP addresses
        - Fully verified corporate entities
        """
        corp_accounts = [
            ("LEGIT-MFG-CORP", "Apex Electronics Manufacturing", "merchant", "DEV-APEX-HQ", "198.18.0.10"),
            ("LEGIT-SUPPLIER", "Silicon Wafer Components Ltd", "merchant", "DEV-SILICON-DC", "198.18.1.25"),
            ("LEGIT-LOGISTICS", "Global Express Freight Carrier", "merchant", "DEV-LOGISTICS-HUB", "198.18.2.50")
        ]

        for aid, name, atype, dev, ip in corp_accounts:
            ledger.accounts[aid] = Account(
                account_id=aid,
                name=name,
                account_type=atype,
                kyc_status="verified_full",
                is_dormant=False,
                dormancy_days=0,
                device_id=dev,
                ip_address=ip,
                initial_balance=500000.0
            )

        # Hop 1: Apex buys wafers for $45,000 on Oct 1
        t1 = datetime(2026, 10, 1, 10, 0, 0)
        tx1 = Transaction(
            tx_id=self._next_tx_id(),
            sender_id="LEGIT-MFG-CORP",
            receiver_id="LEGIT-SUPPLIER",
            amount=45000.0,
            timestamp=t1.isoformat(),
            channel="ach_commercial",
            device_id="DEV-APEX-HQ",
            ip_address="198.18.0.10",
            memo="Invoice #INV-2026-9081 raw material purchase",
            is_ground_truth_fraud=False,
            pattern_type="legit_rebate"
        )
        ledger.transactions.append(tx1)

        # Hop 2: Silicon Wafer pays Logistics $6,200 on Oct 7 (6 days later)
        t2 = datetime(2026, 10, 7, 14, 30, 0)
        tx2 = Transaction(
            tx_id=self._next_tx_id(),
            sender_id="LEGIT-SUPPLIER",
            receiver_id="LEGIT-LOGISTICS",
            amount=6200.0,
            timestamp=t2.isoformat(),
            channel="ach_commercial",
            device_id="DEV-SILICON-DC",
            ip_address="198.18.1.25",
            memo="Freight consignment #FC-4401 shipping fee",
            is_ground_truth_fraud=False,
            pattern_type="legit_rebate"
        )
        ledger.transactions.append(tx2)

        # Hop 3: Logistics issues Apex a quarterly volume discount rebate of $1,800 on Oct 18 (11 days later)
        t3 = datetime(2026, 10, 18, 11, 15, 0)
        tx3 = Transaction(
            tx_id=self._next_tx_id(),
            sender_id="LEGIT-LOGISTICS",
            receiver_id="LEGIT-MFG-CORP",
            amount=1800.0,
            timestamp=t3.isoformat(),
            channel="ach_commercial",
            device_id="DEV-LOGISTICS-HUB",
            ip_address="198.18.2.50",
            memo="Q3 volume rebate credit memo #RBT-992",
            is_ground_truth_fraud=False,
            pattern_type="legit_rebate"
        )
        ledger.transactions.append(tx3)

        ledger.ground_truth_rings.append({
            "ring_id": "Commercial-Rebate-Loop",
            "type": "legitimate_business_cycle",
            "cycle_nodes": ["LEGIT-MFG-CORP", "LEGIT-SUPPLIER", "LEGIT-LOGISTICS"],
            "tx_ids": [tx1.tx_id, tx2.tx_id, tx3.tx_id],
            "is_fraud": False,
            "rationale": "Commercial trade loop with 96% amount decay and 17-day span."
        })

    def _add_background_traffic(self, ledger: LedgerData, num_accounts: int = 25, num_txs: int = 40):
        """Generates realistic normal retail and business noise transactions."""
        first_names = ["James", "Emma", "Liam", "Olivia", "Noah", "Ava", "Lucas", "Mia", "Ethan", "Sophia"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis", "Wilson", "Taylor", "Anderson"]
        merchants = ["WholeFoods Groceries", "Target Retail", "Shell Fuel Station", "Amazon Digital", "Netflix Subscriptions", "ConEd Utility", "Metro Transit"]

        created_accs = []
        for i in range(num_accounts):
            acc_id = self._next_acc_id("ACC-NORM")
            if i % 4 == 0:
                name = self.rng.choice(merchants)
                atype = "merchant"
                kyc = "verified_full"
            else:
                name = f"{self.rng.choice(first_names)} {self.rng.choice(last_names)}"
                atype = "individual"
                kyc = "verified_full" if self.rng.random() > 0.15 else "tier_1_basic"

            acc = Account(
                account_id=acc_id,
                name=name,
                account_type=atype,
                kyc_status=kyc,
                is_dormant=False,
                dormancy_days=0,
                device_id=f"DEV-USR-{self.rng.randint(100, 999)}",
                ip_address=f"10.0.{self.rng.randint(1, 50)}.{self.rng.randint(2, 250)}",
                initial_balance=round(self.rng.uniform(1500.0, 35000.0), 2)
            )
            ledger.accounts[acc_id] = acc
            created_accs.append(acc_id)

        # Generate random transactions between accounts
        base_date = datetime(2026, 10, 10, 8, 0, 0)
        for _ in range(num_txs):
            sender = self.rng.choice(created_accs)
            receiver = self.rng.choice([a for a in created_accs if a != sender])
            # Normal amount distribution (mostly under $500, occasional rent/payroll $1,500 - $3,500)
            if self.rng.random() < 0.75:
                amount = round(self.rng.uniform(15.0, 450.0), 2)
                memo = "Point of sale purchase"
            else:
                amount = round(self.rng.uniform(800.0, 3800.0), 2)
                memo = "Invoice / rent payment"

            tx_time = base_date + timedelta(
                days=self.rng.randint(0, 14),
                hours=self.rng.randint(0, 23),
                minutes=self.rng.randint(0, 59)
            )

            tx = Transaction(
                tx_id=self._next_tx_id(),
                sender_id=sender,
                receiver_id=receiver,
                amount=amount,
                timestamp=tx_time.isoformat(),
                channel=self.rng.choice(["ach_commercial", "p2p_instant", "debit_card"]),
                device_id=ledger.accounts[sender].device_id,
                ip_address=ledger.accounts[sender].ip_address,
                memo=memo,
                is_ground_truth_fraud=False,
                pattern_type="normal"
            )
            ledger.transactions.append(tx)

        # Sort transactions chronologically
        ledger.transactions.sort(key=lambda x: x.timestamp)
