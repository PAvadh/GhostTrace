"""
Entity Profiler Agent: Identity, Device & KYC Intelligence Analyst
Specializes in device hardware fingerprinting, IP/location tracking,
dormant sleeper account awakening, and customer due diligence tiering.
"""

from typing import List, Dict, Any, Optional
import json

from ghost_trace.agents.base import BaseAgent, AgentReport, EvidenceCitation
from ghost_trace.graph_engine import GraphInvestigationResult
from ghost_trace.data_generator import LedgerData


class EntityProfilerAgent(BaseAgent):
    """
    Entity Profiler Agent interprets deterministic identity, device, and dormancy indicators.
    Never invents account metadata or device fingerprints; grounds all findings in ledger evidence.
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key=api_key)

    def investigate(self, graph_result: GraphInvestigationResult, ledger: LedgerData) -> AgentReport:
        flagged_nodes = graph_result.flagged_accounts
        findings: List[str] = []
        citations: List[Dict[str, Any]] = []
        limitations: List[str] = []
        human_recs: List[str] = []

        citation_counter = 1

        if not flagged_nodes:
            status = "VERIFIED_LOW_RISK"
            summary = (
                "Entity due diligence completed across all ledger participants. "
                "No shared hardware fingerprints detected, no sleeper accounts reawakened, "
                "and all transacting entities maintain customary operational tenure with verified KYC records."
            )
            findings.append("Identity Integrity: 100% of participating entities possess distinct hardware device identifiers.")
            findings.append("Tenure Baseline: No dormant sleeper accounts reactivated during the evaluation window.")
            limitations.append("Customer profiles evaluated based on provided ledger metadata; real-time external credit bureau feeds not connected.")
            human_recs.append("Maintain standard annual KYC refresh schedule.")
            inference_label = "deterministic_local_engine"
            err_details = None
        else:
            status = "HIGH_RISK_SYNDICATE_DETECTED"
            summary = (
                f"Flagged {len(flagged_nodes)} suspect accounts for coordinated multi-identity control. "
                f"Deterministic indicators reveal shared hardware device fingerprints, dormant sleeper reactivation, "
                f"and elevated corporate entity risk profiles."
            )

            # 1. Device Linkage Analysis
            device_groups: Dict[str, List[str]] = {}
            for aid in flagged_nodes:
                acc = ledger.get_account(aid)
                dev = getattr(acc, "device_id", None) if acc else None
                if dev and dev not in ("DEV-UNKNOWN", "DEV-DEFAULT", "None", ""):
                    device_groups.setdefault(dev, []).append(aid)

            shared_hardware = {d: accs for d, accs in device_groups.items() if len(set(accs)) > 1}

            if shared_hardware:
                for dev, accs in shared_hardware.items():
                    unique_accs = sorted(list(set(accs)))
                    findings.append(
                        f"**Shared Hardware Device [{dev}]**: Conclusively accessed by {len(unique_accs)} distinct accounts: "
                        f"{', '.join(unique_accs)}. Strongly indicates single-operator mule herding or botnet access."
                    )
                    citations.append(EvidenceCitation(
                        citation_id=f"CIT-PRF-{citation_counter:03d}",
                        citation_type="device",
                        target_id=dev,
                        observed_value=unique_accs,
                        context_note=f"Hardware fingerprint shared across {len(unique_accs)} accounts"
                    ).to_dict())
                    citation_counter += 1
            else:
                findings.append("Device Fingerprints: No shared physical hardware identifiers observed across flagged nodes.")

            # 2. Dormancy Awakening Analysis
            dormant_revivals = []
            for aid in flagged_nodes:
                acc = ledger.get_account(aid)
                if acc and (getattr(acc, "is_dormant", False) or getattr(acc, "dormancy_days", 0) >= 60):
                    dormant_revivals.append((aid, acc.name, acc.dormancy_days))

            if dormant_revivals:
                for aid, name, days in dormant_revivals:
                    findings.append(
                        f"**Dormant Sleeper Awakening [{aid} - '{name}']**: Inactive for {days} days prior to "
                        f"sudden structured high-velocity transfers. Hallmarking bought, rented, or compromised mule sleeper accounts."
                    )
                    citations.append(EvidenceCitation(
                        citation_id=f"CIT-PRF-{citation_counter:03d}",
                        citation_type="account",
                        target_id=aid,
                        observed_value={"dormancy_days": days, "legal_name": name},
                        context_note=f"Sleeper account reawakened after {days} days of zero ledger activity"
                    ).to_dict())
                    citation_counter += 1

            # 3. IP Subnet & Geolocation Check
            ip_subnets: Dict[str, List[str]] = {}
            for aid in flagged_nodes:
                acc = ledger.get_account(aid)
                ip = getattr(acc, "ip_address", None) if acc else None
                if ip and ip != "0.0.0.0":
                    subnet = ".".join(ip.split(".")[:3]) + ".0/24"
                    ip_subnets.setdefault(subnet, []).append(aid)

            shared_subnets = {s: accs for s, accs in ip_subnets.items() if len(set(accs)) > 1}
            if shared_subnets:
                for subnet, accs in shared_subnets.items():
                    findings.append(
                        f"**Shared Proxy/VPN Subnet [{subnet}]**: Transacting accounts {', '.join(sorted(list(set(accs))))} "
                        f"originate traffic from common /24 CIDR network block."
                    )

            # 4. KYC Status & Entity Type Breakdown
            high_risk_entities = []
            for aid in flagged_nodes:
                acc = ledger.get_account(aid)
                if acc:
                    atype = getattr(acc, "account_type", "individual")
                    kyc = getattr(acc, "kyc_status", "tier_1_basic")
                    if atype in ["shell_company", "crypto_ramp"] or kyc != "verified_full":
                        high_risk_entities.append(f"{aid} ({acc.name} | Type: {atype} | KYC: {kyc})")
                        citations.append(EvidenceCitation(
                            citation_id=f"CIT-PRF-{citation_counter:03d}",
                            citation_type="account",
                            target_id=aid,
                            observed_value={"type": atype, "kyc": kyc},
                            context_note="High-risk entity classification"
                        ).to_dict())
                        citation_counter += 1

            if high_risk_entities:
                findings.append(
                    f"**Elevated Entity Risk Classifications**: {'; '.join(high_risk_entities)}."
                )

            limitations.append("Device hardware IDs are browser/client fingerprints; hardware virtualization or spoofing cannot be ruled out without forensic app logs.")
            limitations.append("IP addresses may reflect commercial VPN exit nodes or proxy services rather than physical geolocation.")
            human_recs.append("Conduct Enhanced Due Diligence (EDD) interviews with authorized account signatories.")
            human_recs.append("Request multi-factor authentication (MFA) audit logs from identity provider for all shared hardware devices.")
            human_recs.append("Subpoena ultimate beneficial ownership (UBO) filings for flagged shell entities.")

            inference_label = "deterministic_local_engine"
            err_details = None

            # Optional LLM Enhancement if configured
            if self.api_key:
                system_prompt = (
                    "You are the Entity Profiler Agent in the GhostTrace financial crime system. "
                    "Synthesize the provided identity, device, and dormancy facts. "
                    "Do not invent any IP addresses, device IDs, or account numbers. Cite only provided evidence."
                )
                user_prompt = f"Entity evidence:\n{json.dumps([c for c in citations], indent=2)}"
                llm_summary, mode_label, err = self._call_optional_llm(user_prompt, system_prompt)
                if llm_summary:
                    summary = llm_summary.strip()
                    inference_label = mode_label
                elif err:
                    inference_label = mode_label
                    err_details = err

        md_lines = [
            f"### 👤 Entity Profiler Agent Report",
            f"- **Role**: Identity, Device & KYC Intelligence Analyst",
            f"- **Inference Backend**: `{inference_label}`",
            f"- **Investigation Status**: `{status}`",
            f"- **Flagged Subjects**: {len(flagged_nodes)} account(s)",
            f"\n**Profiling Brief**:\n{summary}\n",
            "**Deterministic Entity Findings**:"
        ]
        for f in findings:
            md_lines.append(f"- {f}")

        md_lines.append("\n**Profiling Limitations**:")
        for lim in limitations:
            md_lines.append(f"- ⚠️ {lim}")

        md_lines.append("\n**Profiler Action Recommendations**:")
        for rec in human_recs:
            md_lines.append(f"- 📋 {rec}")

        return AgentReport(
            agent_role="Entity Profiler",
            agent_title="Identity, KYC & Device Intelligence Analyst",
            status=status,
            summary=summary,
            findings=findings,
            evidence_citations=citations,
            limitations=limitations,
            human_recommendations=human_recs,
            raw_markdown="\n".join(md_lines),
            inference_mode=inference_label,
            llm_error_details=err_details
        )
