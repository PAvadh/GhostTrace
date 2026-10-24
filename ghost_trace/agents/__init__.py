"""
GhostTrace Autonomous Multi-Agent Investigation System
Modular investigative roles:
- DetectiveAgent: Flow topology, structuring, velocity, and cycle metrics
- EntityProfilerAgent: Devices, proxy subnets, dormancy awakening, and KYC
- ComplianceOfficerAgent: Structured draft SAR, regulatory statutes, limitations, and recommendations
- CitationVerifier: Audit claims against source evidence
- GhostTraceInvestigationOrchestrator: Multi-agent coordination
"""

from ghost_trace.agents.base import (
    BaseAgent,
    AgentReport,
    EvidenceCitation,
    CitationVerificationResult,
    TriAgentInvestigationReport
)
from ghost_trace.agents.detective import DetectiveAgent
from ghost_trace.agents.profiler import EntityProfilerAgent
from ghost_trace.agents.compliance import ComplianceOfficerAgent
from ghost_trace.agents.verifier import CitationVerifier
from ghost_trace.agents.orchestrator import GhostTraceInvestigationOrchestrator

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
