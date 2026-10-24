"""
GhostTrace Configuration & AML Compliance Constants
Track: The Vampire's Ledger | Aapthamitra Audits
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List

# UI & Visualization Palette (Polished Dark Navy with Cyan Accents & Red Alerts)
THEME_COLORS = {
    "bg_dark": "#0A0F1D",         # Deep dark navy canvas
    "card_dark": "#131E36",       # Surface card navy
    "card_border": "#1E2C4F",     # Subtle navy border
    "accent_cyan": "#00F0FF",     # Electric cyan highlight
    "accent_blue": "#38BDF8",     # Muted sky blue
    "flagged_red": "#FF3366",     # Crimson red for flagged mule rings
    "warning_amber": "#FFB703",   # Amber for moderate risk/structuring
    "legit_green": "#10B981",     # Emerald green for legit business loops
    "text_light": "#F8FAFC",      # High contrast light text
    "text_muted": "#94A3B8",      # Muted slate text
}

# Regulatory & Detection Defaults
STRUCTURING_THRESHOLD_MIN = 8500.0   # Just below $10,000 CTR reporting limit
STRUCTURING_THRESHOLD_MAX = 9999.0   # Structuring band
BSA_REPORTING_LIMIT = 10000.0        # Traditional single-event threshold

MAX_CYCLE_LENGTH = 6                 # Maximum hops to evaluate in graph cycle search
MIN_CYCLE_LENGTH = 3                 # Minimum hops for circular mule ring
MAX_MULE_COMMISSION_PCT = 15.0       # Illicit mule rings retain 85-99% across hops (1-15% fee)
MAX_CYCLE_VELOCITY_HOURS = 24.0      # Typical money mule circular hops happen rapidly (<24 hrs)
DORMANCY_DAYS_THRESHOLD = 90         # Days of inactivity before sudden reactivation

# Default Scoring Weights for Suspicious-Cycle Composite Score
DEFAULT_SCORE_WEIGHTS = {
    "flow_conservation": 0.25,       # How closely amounts match across hops (1 - decay)
    "temporal_velocity": 0.25,       # How rapid the hops are
    "structuring_band": 0.20,        # Are amounts clustered just below $10,000?
    "shared_infrastructure": 0.20,   # Shared device_id or IP subnet across cycle hops
    "dormant_reactivation": 0.10,    # Involves accounts reactivated after dormancy
}

SCORE_WEIGHTS = DEFAULT_SCORE_WEIGHTS


@dataclass
class EngineRulesConfig:
    """Configurable explainable rules for cycle detection and risk scoring."""
    min_cycle_length: int = MIN_CYCLE_LENGTH
    max_cycle_length: int = MAX_CYCLE_LENGTH
    structuring_min: float = STRUCTURING_THRESHOLD_MIN
    structuring_max: float = STRUCTURING_THRESHOLD_MAX
    max_mule_commission_pct: float = MAX_MULE_COMMISSION_PCT
    max_cycle_velocity_hours: float = MAX_CYCLE_VELOCITY_HOURS
    dormancy_days_threshold: int = DORMANCY_DAYS_THRESHOLD
    min_suspicion_score_to_flag: float = 0.45
    critical_suspicion_score: float = 0.70
    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SCORE_WEIGHTS))
    require_corroborating_evidence: bool = True  # NEVER treat cycle alone as fraud

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_cycle_length": self.min_cycle_length,
            "max_cycle_length": self.max_cycle_length,
            "structuring_min": self.structuring_min,
            "structuring_max": self.structuring_max,
            "max_mule_commission_pct": self.max_mule_commission_pct,
            "max_cycle_velocity_hours": self.max_cycle_velocity_hours,
            "dormancy_days_threshold": self.dormancy_days_threshold,
            "min_suspicion_score_to_flag": self.min_suspicion_score_to_flag,
            "critical_suspicion_score": self.critical_suspicion_score,
            "weights": self.weights,
            "require_corroborating_evidence": self.require_corroborating_evidence
        }


# Regulatory Citations for Evidence-Backed SAR Dossier
REGULATORY_CITATIONS = [
    {
        "title": "31 U.S.C. 5318(g)",
        "law": "Bank Secrecy Act - Reporting of Suspicious Transactions",
        "description": "Requires financial institutions to report suspicious transactions relevant to a possible violation of law or regulation."
    },
    {
        "title": "31 U.S.C. 5324",
        "law": "Structuring Transactions to Evade Reporting Requirement Prohibited",
        "description": "Prohibits structuring transactions with financial institutions for the purpose of evading Currency Transaction Reporting (CTR) requirements."
    },
    {
        "title": "18 U.S.C. 1956 & 1957",
        "law": "Money Laundering Control Act",
        "description": "Criminalizes knowingly conducting financial transactions involving illicit proceeds, layering funds to conceal ownership, and engaging in monetary transactions over $10,000 derived from specified unlawful activity."
    },
    {
        "title": "31 CFR 1020.320",
        "law": "FinCEN Suspicious Activity Report (SAR) Filing Rules for Banks",
        "description": "Mandates SAR filing within 30 calendar days after the date of initial detection of facts that may constitute a basis for filing."
    }
]

# Strict Human-in-the-Loop Policy
COMPLIANCE_DISCLAIMER = (
    "NOTICE: GhostTrace operates as an autonomous decision-support system. "
    "All risk classifications, entity profiles, and draft SAR narratives are "
    "RECOMMENDATIONS ONLY. GhostTrace NEVER automatically submits regulatory reports "
    "nor freezes accounts without explicit verification, review, and authorization "
    "by a qualified human AML Compliance Officer."
)
