"""
Backward-compatibility adapter for GhostTrace investigative agents.
Re-exports modular agent classes from ghost_trace.agents.
"""

from ghost_trace.agents import (
    BaseAgent,
    AgentReport,
    EvidenceCitation,
    CitationVerificationResult,
    TriAgentInvestigationReport,
    DetectiveAgent,
    EntityProfilerAgent,
    ComplianceOfficerAgent,
    CitationVerifier,
    GhostTraceInvestigationOrchestrator
)

__all__ = [
    "BaseAgent",
    "AgentReport",
    "EvidenceCitation",
    "CitationVerificationResult",
    "TriAgentInvestigationReport",
    "DetectiveAgent",
    "EntityProfilerAgent",
    "ComplianceOfficerAgent",
    "CitationVerifier",
    "GhostTraceInvestigationOrchestrator"
]
