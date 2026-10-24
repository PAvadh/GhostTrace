"""
Base Agent Definitions, LLM Client Interface & Citation Models
"""

from dataclasses import dataclass, field
from datetime import datetime
import os
import json
from typing import List, Dict, Any, Optional, Tuple

from ghost_trace.config import COMPLIANCE_DISCLAIMER


@dataclass
class EvidenceCitation:
    """Rigorous structured evidence citation linking a claim to source records."""
    citation_id: str
    citation_type: str  # 'transaction', 'account', 'cycle', 'smurfing_cluster', 'device'
    target_id: str      # tx_id, account_id, cycle_id, etc.
    observed_value: Any
    context_note: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "citation_type": self.citation_type,
            "target_id": self.target_id,
            "observed_value": self.observed_value,
            "context_note": self.context_note
        }


@dataclass
class AgentReport:
    """Structured report produced by an individual investigation agent."""
    agent_role: str
    agent_title: str
    status: str
    summary: str
    findings: List[str]
    evidence_citations: List[Dict[str, Any]]
    raw_markdown: str
    limitations: List[str] = field(default_factory=list)
    human_recommendations: List[str] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    inference_mode: str = "deterministic_local_engine"  # 'deterministic_local_engine', 'llm_gemini', 'llm_groq', 'llm_fallback_to_local'
    llm_error_details: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_role": self.agent_role,
            "agent_title": self.agent_title,
            "status": self.status,
            "summary": self.summary,
            "findings": self.findings,
            "evidence_citations": self.evidence_citations,
            "limitations": self.limitations,
            "human_recommendations": self.human_recommendations,
            "generated_at": self.generated_at,
            "inference_mode": self.inference_mode,
            "llm_error_details": self.llm_error_details,
            "raw_markdown": self.raw_markdown
        }


@dataclass
class CitationVerificationResult:
    """Result of cross-referencing agent claims against source ledger & graph."""
    is_valid: bool
    total_citations_checked: int
    verified_transactions: List[str]
    verified_accounts: List[str]
    verified_devices: List[str]
    unverified_claims: List[Dict[str, Any]]
    verification_notes: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "total_citations_checked": self.total_citations_checked,
            "verified_transactions_count": len(self.verified_transactions),
            "verified_accounts_count": len(self.verified_accounts),
            "verified_devices_count": len(self.verified_devices),
            "unverified_claims_count": len(self.unverified_claims),
            "unverified_claims": self.unverified_claims,
            "verification_notes": self.verification_notes
        }


@dataclass
class TriAgentInvestigationReport:
    """Comprehensive investigation dossier synthesized across all three agents."""
    scenario_name: str
    investigation_id: str
    overall_verdict: str
    overall_risk_score: float
    detective_report: AgentReport
    profiler_report: AgentReport
    compliance_report: AgentReport
    flagged_entities: List[str]
    flagged_transactions: List[str]
    citation_verification: CitationVerificationResult
    human_action_checklist: List[str]
    disclaimer: str = COMPLIANCE_DISCLAIMER
    total_latency_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "investigation_id": self.investigation_id,
            "overall_verdict": self.overall_verdict,
            "overall_risk_score": self.overall_risk_score,
            "detective_report": self.detective_report.to_dict(),
            "profiler_report": self.profiler_report.to_dict(),
            "compliance_report": self.compliance_report.to_dict(),
            "flagged_entities": self.flagged_entities,
            "flagged_transactions": self.flagged_transactions,
            "citation_verification": self.citation_verification.to_dict(),
            "human_action_checklist": self.human_action_checklist,
            "disclaimer": self.disclaimer,
            "total_latency_seconds": round(self.total_latency_seconds, 3)
        }


class BaseAgent:
    """Abstract base class for all GhostTrace investigative agents."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = (
            api_key or
            os.environ.get("GEMINI_API_KEY") or
            os.environ.get("GROQ_API_KEY") or
            os.environ.get("OPENAI_API_KEY")
        )

    def _call_optional_llm(self, prompt: str, system_prompt: str) -> Tuple[Optional[str], str, Optional[str]]:
        """
        Executes optional LLM summarization if API key is present.
        Safely catches network/auth/quota exceptions and falls back without crashing.
        Returns: (response_text, inference_mode_label, error_details)
        """
        if not self.api_key:
            return None, "deterministic_local_engine", None

        # Check for Gemini credentials
        if os.environ.get("GEMINI_API_KEY") or (self.api_key and "AIza" in self.api_key):
            try:
                import urllib.request
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
                payload = {
                    "contents": [{
                        "parts": [{"text": f"System: {system_prompt}\n\nTask: {prompt}"}]
                    }],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 800}
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as response:
                    res_body = json.loads(response.read().decode("utf-8"))
                    text = res_body["candidates"][0]["content"]["parts"][0]["text"]
                    return text, "llm_gemini", None
            except Exception as e:
                return None, "llm_fallback_to_local", f"Gemini API invocation failed: {str(e)}"

        # Default fallback
        return None, "deterministic_local_engine", None
