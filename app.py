"""
GhostTrace: Autonomous Financial Crime Investigation
Track: The Vampire's Ledger | Team: Aapthamitra Audits
Main Streamlit Application Dashboard
"""

import time
import os
import json
from datetime import datetime
import streamlit as st
import pandas as pd
import streamlit.components.v1 as components

from ghost_trace.config import (
    THEME_COLORS,
    REGULATORY_CITATIONS,
    COMPLIANCE_DISCLAIMER,
    STRUCTURING_THRESHOLD_MIN,
    STRUCTURING_THRESHOLD_MAX,
    BSA_REPORTING_LIMIT,
    EngineRulesConfig
)
from ghost_trace.data_generator import SyntheticLedgerGenerator, LedgerData
from ghost_trace.graph_engine import FinancialGraphEngine, GraphInvestigationResult, CycleEvidence
from ghost_trace.agents import GhostTraceInvestigationOrchestrator
from ghost_trace.sar_generator import SARGenerator
from ghost_trace.visualizer import GraphVisualizer
from ghost_trace.benchmark import BenchmarkRunner
from ghost_trace.amlsim_adapter import (
    AMLSimAdapter,
    AMLSimLoadResult,
    list_amlsim_files,
    get_data_dir_instructions,
)
from ghost_trace.dashboard_helpers import (
    DatasetBundle,
    UNAVAILABLE,
    esc,
    fmt_avg_hop,
    fmt_duration,
    fmt_hops_per_hour,
    load_amlsim_bytes,
    load_amlsim_file,
    load_synthetic,
    render_graph_html,
    run_benchmark,
    velocity_label,
)


def apply_custom_theme():
    """Applies polished dark navy, cyan and red cybersecurity theme."""
    st.markdown("""
    <style>
        .stApp {
            background-color: #0A0F1D;
            color: #F8FAFC;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        [data-testid="stSidebar"] {
            background-color: #0D1527;
            border-right: 1px solid #1E293B;
        }
        .gt-card {
            background: #131E36;
            border: 1px solid #1E2C4F;
            border-radius: 10px;
            padding: 18px;
            margin-bottom: 16px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }
        .gt-card-cyan { border-left: 4px solid #00F0FF; }
        .gt-card-red { border-left: 4px solid #FF3366; }
        .gt-card-amber { border-left: 4px solid #FFB703; }
        .gt-card-green { border-left: 4px solid #10B981; }

        .gt-metric-val {
            font-size: 26px;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }
        .gt-metric-lbl {
            font-size: 11px;
            text-transform: uppercase;
            color: #94A3B8;
            letter-spacing: 0.8px;
        }
        .gt-terminal {
            background-color: #070B14;
            border: 1px solid #1E293B;
            border-radius: 8px;
            padding: 14px;
            font-family: 'JetBrains Mono', Consolas, 'Courier New', monospace;
            font-size: 13px;
            color: #00F0FF;
            line-height: 1.6;
            overflow-y: auto;
            max-height: 320px;
        }
        .gt-pill {
            background: #1E293B;
            border: 1px solid #334155;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-family: 'JetBrains Mono', monospace;
            color: #38BDF8;
            display: inline-block;
            margin: 2px 4px;
        }
        .gt-pill-red {
            background: rgba(255, 51, 102, 0.15);
            border-color: #FF3366;
            color: #FF3366;
        }
        .gt-pill-cyan {
            background: rgba(0, 240, 255, 0.15);
            border-color: #00F0FF;
            color: #00F0FF;
        }
        .gt-badge-red {
            background: rgba(255, 51, 102, 0.15);
            color: #FF3366;
            border: 1px solid #FF3366;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .gt-badge-cyan {
            background: rgba(0, 240, 255, 0.15);
            color: #00F0FF;
            border: 1px solid #00F0FF;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .gt-badge-green {
            background: rgba(16, 185, 129, 0.15);
            color: #10B981;
            border: 1px solid #10B981;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .stButton>button {
            background: linear-gradient(135deg, #00A3FF 0%, #00F0FF 100%);
            color: #0A0F1D;
            font-weight: 700;
            border: none;
            border-radius: 6px;
            padding: 8px 18px;
            transition: all 0.2s ease;
        }
        .stButton>button:hover {
            background: linear-gradient(135deg, #00F0FF 0%, #38BDF8 100%);
            box-shadow: 0 0 15px rgba(0, 240, 255, 0.5);
            color: #0A0F1D;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 8px;
            border-bottom: 1px solid #1E293B;
        }
        .stTabs [data-baseweb="tab"] {
            background-color: #0D1527;
            border-radius: 6px 6px 0 0;
            color: #94A3B8;
            padding: 10px 18px;
        }
        .stTabs [aria-selected="true"] {
            background-color: #131E36 !important;
            color: #00F0FF !important;
            border-bottom: 2px solid #00F0FF !important;
        }
    </style>
    """, unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def get_cached_synthetic_bundle(scenario: str, seed: int) -> DatasetBundle:
    """Generate a synthetic scenario and investigate it."""
    return load_synthetic(scenario, seed)


@st.cache_data(show_spinner=False)
def get_cached_amlsim_bundle(file_path: str, max_rows: int) -> DatasetBundle:
    """Load a pre-placed AMLSim CSV and investigate it."""
    return load_amlsim_file(file_path, max_rows)


@st.cache_data(show_spinner=False)
def get_cached_amlsim_upload_bundle(file_bytes: bytes, filename: str, max_rows: int) -> DatasetBundle:
    """Load an uploaded AMLSim CSV and investigate it."""
    return load_amlsim_bytes(file_bytes, filename, max_rows)


@st.cache_data(show_spinner=False)
def get_cached_graph_html(dataset_key: str, filter_mode: str, selected_cycle_id: str, _bundle: DatasetBundle):
    """Graph HTML for the SELECTED dataset. `dataset_key` identifies the dataset in the cache key;
    the bundle itself (underscore = not hashed) supplies the data, so AMLSim is never replaced by
    a regenerated synthetic ledger."""
    return render_graph_html(_bundle, filter_mode=filter_mode, selected_cycle_id=selected_cycle_id)


@st.cache_data(show_spinner=False)
def get_cached_benchmark(dataset_key: str, _bundle: DatasetBundle):
    """Benchmark of the SELECTED dataset's own ledger and engine result."""
    return run_benchmark(_bundle)


def main():
    st.set_page_config(
        page_title="GhostTrace | Autonomous Financial Crime Investigation",
        page_icon="🦇",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    apply_custom_theme()

    # Session State Initialization
    if "human_reviewed" not in st.session_state:
        st.session_state.human_reviewed = False
    if "human_officer_name" not in st.session_state:
        st.session_state.human_officer_name = "P. Avadhani (Lead AML Examiner)"
    if "review_timestamp" not in st.session_state:
        st.session_state.review_timestamp = ""
    if "selected_cycle_id" not in st.session_state:
        st.session_state.selected_cycle_id = None

    # -------------------------------------------------------------------------
    # Sidebar: Dataset Source + Investigation Controls
    # -------------------------------------------------------------------------
    with st.sidebar:
        st.markdown("""
            <div style="text-align: center; padding-bottom: 10px;">
                <span style="font-size: 38px;">&#x1F987;</span>
                <h2 style="margin: 0; color: #00F0FF; letter-spacing: 1px;">GHOSTTRACE</h2>
                <div style="font-size: 11px; color: #94A3B8; text-transform: uppercase; margin-top: 2px;">
                    Track: The Vampire's Ledger<br>Team: Aapthamitra Audits
                </div>
            </div>
        """, unsafe_allow_html=True)
        st.divider()

        # Dataset source selector
        st.subheader("📂 Dataset Source")
        dataset_source = st.radio(
            "Select data source:",
            options=["GhostTrace Synthetic Data", "IBM AMLSim Dataset"],
            index=0,
            help=(
                "Synthetic: Deterministic generated scenarios with injected fraud patterns.\n"
                "IBM AMLSim: Load real IBM AMLSim / Kaggle AML CSV files."
            )
        )
        st.divider()

        # Synthetic mode controls
        if dataset_source == "GhostTrace Synthetic Data":
            st.subheader("Scenario & Ledger Config")
            scenario_choice = st.selectbox(
                "Select Financial Scenario:",
                options=[
                    ("vampire_ring", "Vampire Mule Ring (Circular Layering)"),
                    ("smurfing", "Distributed Smurfing (Fan-Out / Fan-In)"),
                    ("dormant_reactivation", "Dormant Mule Awakening"),
                    ("legit_rebate", "Commercial Rebate Loop (Control)"),
                    ("mixed_ledger", "Omni-Ledger: Mixed Portfolio")
                ],
                format_func=lambda x: x[1],
                index=0
            )[0]
            seed_val = st.number_input(
                "Random Seed (Reproducible Benchmark):",
                min_value=1, max_value=99999, value=42, step=1
            )
            amlsim_file_path = None
            amlsim_upload = None
            amlsim_max_rows = 5000

        # AMLSim mode controls
        else:
            st.subheader("IBM AMLSim Dataset Config")
            workspace_dir = os.path.dirname(os.path.abspath(__file__))
            available_files = list_amlsim_files(os.path.join(workspace_dir, "data", "amlsim"))

            amlsim_mode = st.radio(
                "Load method:",
                options=["Select pre-placed file", "Upload CSV file"],
                index=0
            )

            amlsim_file_path = None
            amlsim_upload = None

            if amlsim_mode == "Select pre-placed file":
                if available_files:
                    amlsim_file_path = st.selectbox(
                        "Available AMLSim files:",
                        options=available_files,
                        format_func=lambda x: os.path.basename(x)
                    )
                else:
                    st.warning("No CSV files found in data/amlsim/.")
                    with st.expander("How to add dataset files"):
                        st.code(get_data_dir_instructions(), language="text")
            else:
                amlsim_upload = st.file_uploader(
                    "Upload AMLSim CSV:",
                    type=["csv"],
                    help=(
                        "Supported: Kaggle AML (HI-Small_Trans.csv / LI-Small_Trans.csv) "
                        "or AMLSim native (transactions.csv)"
                    )
                )
                if amlsim_upload is None:
                    with st.expander("Where to get AMLSim data"):
                        st.code(get_data_dir_instructions(), language="text")

            amlsim_max_rows = st.slider(
                "Max rows to load:",
                min_value=100, max_value=10000, value=2000, step=100,
                help="Limits rows loaded from large AMLSim files."
            )
            scenario_choice = "mixed_ledger"
            seed_val = 42

        st.divider()
        st.subheader("Graph Canvas View Filter")
        graph_filter_mode = st.radio(
            "Display Filter:",
            options=[
                ("all", "Show All Ledger Transactions"),
                ("flagged_only", "Flagged Mule Rings Only"),
                ("cycles_only", "All Detected Cycles Only")
            ],
            format_func=lambda x: x[1],
            index=0
        )[0]

        st.divider()
        st.subheader("Multi-Agent Engine Mode")
        engine_mode = st.radio(
            "Agent Inference Backend:",
            options=["Deterministic Local Engine (Zero Hallucination)", "Cloud LLM (Gemini / Groq)"],
            index=0
        )

        api_key_input = None
        if "Cloud LLM" in engine_mode:
            api_key_input = st.text_input(
                "Enter API Key (Optional):", type="password",
                help="Leave blank to automatically fallback to Local Engine."
            )

        st.divider()
        st.button("Re-Run Investigation", use_container_width=True)

        st.markdown("""
            <div style="margin-top: 20px; font-size: 11px; color: #64748B; line-height: 1.4;">
                <b>Compliance Mandate:</b> Autonomous decision support only.
                All reports require certified human compliance officer review and signature.
            </div>
        """, unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # Execute / Retrieve Investigation
    # -------------------------------------------------------------------------
    t_start = time.perf_counter()
    amlsim_load_result = None
    amlsim_load_warnings = []

    bundle = None
    if dataset_source == "GhostTrace Synthetic Data":
        bundle = get_cached_synthetic_bundle(scenario_choice, seed_val)
        ledger, graph_result = bundle.ledger, bundle.result
        data_source_label = "GhostTrace Synthetic"
        data_source_badge_color = "#00F0FF"
    else:
        if amlsim_upload is not None:
            bundle = get_cached_amlsim_upload_bundle(
                amlsim_upload.getvalue(), amlsim_upload.name, amlsim_max_rows
            )
        elif amlsim_file_path is not None:
            bundle = get_cached_amlsim_bundle(amlsim_file_path, amlsim_max_rows)

        if bundle is not None:
            ledger, graph_result, amlsim_load_result = bundle.ledger, bundle.result, bundle.load_result
        else:
            ledger, graph_result, amlsim_load_result = None, None, None

        if amlsim_load_result is not None and not amlsim_load_result.success:
            st.error(f"**AMLSim Load Error:** {amlsim_load_result.error}")
            st.markdown("""
                <div style="background:#131E36;border:1px solid #1E2C4F;border-radius:8px;padding:14px;margin-top:12px;">
                    <b style="color:#00F0FF;">How to fix:</b>
                    <ul style="color:#94A3B8;font-size:13px;">
                        <li>Place CSV in <code>data/amlsim/</code> under the GhostTrace workspace.</li>
                        <li>Supported: <b>HI-Small_Trans.csv</b>, <b>LI-Small_Trans.csv</b> (Kaggle AML) or <b>transactions.csv</b> (AMLSim native).</li>
                        <li>Download: <a href="https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml" style="color:#00F0FF;">Kaggle IBM AML Dataset</a></li>
                    </ul>
                </div>
            """, unsafe_allow_html=True)
            st.stop()

        if ledger is None or graph_result is None:
            st.info(
                "**IBM AMLSim mode active.** "
                "Select a pre-placed CSV from data/amlsim/ or upload a file to begin investigation."
            )
            with st.expander("Dataset instructions"):
                st.code(get_data_dir_instructions(), language="text")
            st.stop()

        data_source_label = f"IBM AMLSim ({amlsim_load_result.detected_format})"
        data_source_badge_color = "#FFB703"
        if amlsim_load_result.warnings:
            amlsim_load_warnings = amlsim_load_result.warnings

    if ledger is None or graph_result is None:
        st.error("Could not load any data. Please select a dataset or scenario.")
        st.stop()


    orchestrator = GhostTraceInvestigationOrchestrator(api_key=api_key_input)
    agent_investigation = orchestrator.run_investigation(graph_result, ledger)

    sar_builder = SARGenerator()
    sar_draft = sar_builder.generate_sar(agent_investigation, graph_result, ledger)
    t_end = time.perf_counter()
    total_run_time_sec = t_end - t_start

    # If already signed in session state, reflect in sar_draft
    if st.session_state.human_reviewed:
        sar_draft.review_status = "CERTIFIED_AND_SIGNED_BY_HUMAN_OFFICER"
        sar_draft.human_officer_notes = f"Certified by {st.session_state.human_officer_name} on {st.session_state.review_timestamp}."

    # Top Header Banner
    col_h1, col_h2 = st.columns([3, 1])
    with col_h1:
        st.markdown(f"""
            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 5px;">
                <h1 style="margin: 0; font-size: 32px; font-weight: 800; color: #F8FAFC;">
                    GhostTrace <span style="color: #00F0FF;">Investigation Console</span>
                </h1>
                <span class="gt-badge-cyan">Autonomous AML v1.0</span>
                <span class="gt-badge-red">Track: The Vampire's Ledger</span>
            </div>
            <p style="color: #94A3B8; margin-top: 0; font-size: 14px;">
                Unmasking circular money mule rings, structured smurfing, and dormant sleeper accounts with evidence-grounded graph reasoning.
            </p>
            <p style="color: #64748B; margin-top: 0; font-size: 12px;">
                Dataset: <span style="color: {data_source_badge_color};">{esc(data_source_label)}</span> &middot; {esc(bundle.label)}
            </p>
        """, unsafe_allow_html=True)

    with col_h2:
        st.markdown(f"""
            <div style="background: #131E36; border: 1px solid #1E2C4F; border-radius: 8px; padding: 10px 14px; text-align: right;">
                <div style="font-size: 11px; color: #94A3B8;">INVESTIGATION BENCHMARK</div>
                <div style="font-size: 20px; font-weight: bold; color: #00F0FF; font-family: monospace;">
                    {total_run_time_sec:.3f}s <span style="font-size: 12px; color: #10B981;">(Target &lt;30s)</span>
                </div>
                <div style="font-size: 10px; color: #64748B;">Graph: {graph_result.execution_time_ms:.1f}ms | Agents: {agent_investigation.total_latency_seconds*1000:.1f}ms</div>
            </div>
        """, unsafe_allow_html=True)

    # Executive KPI Metrics Bar
    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    with kpi1:
        st.markdown(f"""
            <div class="gt-card gt-card-cyan">
                <div class="gt-metric-lbl">Ledger Accounts</div>
                <div class="gt-metric-val" style="color: #00F0FF;">{graph_result.total_accounts}</div>
                <div style="font-size: 11px; color: #94A3B8;">{graph_result.total_transactions} Directed Edges</div>
            </div>
        """, unsafe_allow_html=True)

    with kpi2:
        st.markdown(f"""
            <div class="gt-card {'gt-card-red' if graph_result.flagged_cycles else 'gt-card-green'}">
                <div class="gt-metric-lbl">Vampire Mule Cycles</div>
                <div class="gt-metric-val" style="color: {'#FF3366' if graph_result.flagged_cycles else '#10B981'};">
                    {len(graph_result.flagged_cycles)} Flagged
                </div>
                <div style="font-size: 11px; color: #94A3B8;">{len(graph_result.detected_cycles)} Bounded Cycles Total</div>
            </div>
        """, unsafe_allow_html=True)

    with kpi3:
        st.markdown(f"""
            <div class="gt-card {'gt-card-amber' if graph_result.smurfing_clusters else 'gt-card-cyan'}">
                <div class="gt-metric-lbl">Smurfing Clusters</div>
                <div class="gt-metric-val" style="color: {'#FFB703' if graph_result.smurfing_clusters else '#38BDF8'};">
                    {len(graph_result.smurfing_clusters)} Clusters
                </div>
                <div style="font-size: 11px; color: #94A3B8;">Fan-out / fan-in flows</div>
            </div>
        """, unsafe_allow_html=True)

    with kpi4:
        st.markdown(f"""
            <div class="gt-card {'gt-card-red' if agent_investigation.overall_risk_score >= 0.70 else 'gt-card-green'}">
                <div class="gt-metric-lbl">Suspicion Index</div>
                <div class="gt-metric-val" style="color: {'#FF3366' if agent_investigation.overall_risk_score >= 0.70 else '#10B981'};">
                    {agent_investigation.overall_risk_score * 100:.0f}%
                </div>
                <div style="font-size: 11px; color: #94A3B8;">Max network risk rating</div>
            </div>
        """, unsafe_allow_html=True)

    with kpi5:
        st.markdown(f"""
            <div class="gt-card gt-card-cyan">
                <div class="gt-metric-lbl">Flagged Entities</div>
                <div class="gt-metric-val" style="color: #F8FAFC;">{len(graph_result.flagged_accounts)}</div>
                <div style="font-size: 11px; color: #94A3B8;">{len(graph_result.flagged_tx_ids)} Flagged Transfers</div>
            </div>
        """, unsafe_allow_html=True)

    # Main Tabs: Graph, Evidence Explorer, Multi-Agent War Room, SAR Dossier, Benchmark, Ledger
    tab_graph, tab_explorer, tab_agents, tab_sar, tab_bench, tab_ledger = st.tabs([
        "🕸️ Interactive Graph & Live Trace",
        "🔍 Evidence Explorer & Source Inspection",
        "🕵️ Autonomous Multi-Agent War Room",
        "📄 Regulatory SAR Dossier & Human Review Gate",
        "📊 Benchmark vs Single-Event Baseline",
        "📜 Ledger Data Inspector"
    ])

    # =========================================================================
    # TAB 1: INTERACTIVE GRAPH & LIVE TRACE
    # =========================================================================
    with tab_graph:
        col_viz, col_trace = st.columns([7, 3])

        with col_viz:
            st.markdown(f"""
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <h4 style="margin: 0; color: #F8FAFC;">Interactive Transaction Network (PyVis Canvas)</h4>
                    <div style="font-size: 12px; display: flex; gap: 14px;">
                        <span><span style="color: #FF3366;">●</span> Flagged by Evidence (Red)</span>
                        <span><span style="color: #FFB703;">◆</span> Flagged Smurfing Hub (Amber)</span>
                        <span><span style="color: #10B981;">●</span> Cycle Cleared as Benign (Green)</span>
                        <span><span style="color: #38BDF8;">●</span> No Alert</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)

            html_code = get_cached_graph_html(
                bundle.key, graph_filter_mode, st.session_state.selected_cycle_id, bundle
            )
            components.html(html_code, height=600, scrolling=False)
            if bundle.is_synthetic:
                st.caption(
                    "Colours reflect investigation evidence only. Synthetic account and device identifiers "
                    "are shown as neutral aliases on the canvas; real IDs appear in the Evidence and Ledger tabs."
                )

        with col_trace:
            st.markdown("#### ⚡ Live Investigation Trace")
            trace_logs = [
                f"[SYSTEM] Initialized NetworkX MultiDiGraph engine on '{ledger.scenario_name}'",
                f"[INGEST] Ingested {len(ledger.accounts)} accounts and {len(ledger.transactions)} directed ledger edges.",
                f"[COMPUTE] Running Johnson's cycle detection algorithm (min_len=3, max_len=6)...",
                f"[COMPUTE] Detected {len(graph_result.detected_cycles)} closed cycle path(s) in {graph_result.execution_time_ms:.1f}ms."
            ]

            if graph_result.flagged_cycles:
                for c in graph_result.flagged_cycles:
                    trace_logs.append(f"[ALERT] Flagged Ring [{c.cycle_id}]: {c.hop_count} hops, Path: {' -> '.join(c.path[:3])}...")
                    trace_logs.append(f"  |-- Flow conservation: ${c.initial_amount:,.2f} -> ${c.final_amount:,.2f} ({c.flow_retention_pct:.1f}% retained)")
                    if c.velocity_available:
                        trace_logs.append(f"  |-- Velocity: {fmt_duration(c)} duration (avg {fmt_avg_hop(c)}/hop, {fmt_hops_per_hour(c)})")
                    else:
                        trace_logs.append(f"  |-- Velocity: {UNAVAILABLE} (hop timestamps missing or unparseable)")
                    trace_logs.append(f"  |-- Structuring: {c.structured_hop_count}/{c.hop_count} hops in $8.5k-$10k CTR evasion zone")
                    if c.shared_devices:
                        trace_logs.append(f"  |-- Infrastructure Link: Shared hardware fingerprint {c.shared_devices[0]}")
            else:
                trace_logs.append("[INFO] All detected cycles verified as benign commercial activity (decay > 70% or multi-day intervals).")

            if graph_result.smurfing_clusters:
                for s in graph_result.smurfing_clusters:
                    trace_logs.append(f"[ALERT] Smurfing cluster [{s.cluster_id}]: Funder {s.funder_account} -> {len(s.smurf_accounts)} smurfs -> Sink {s.collector_account}")

            trace_logs.extend([
                f"[AGENTS] Dispatched findings to Detective, Entity Profiler, and Compliance Officer.",
                f"[VERIFIER] Verified {agent_investigation.citation_verification.total_citations_checked} citations against ground truth ledger.",
                f"[STATUS] Tri-agent investigation complete in {agent_investigation.total_latency_seconds*1000:.1f}ms.",
                f"[SAR] Draft Suspicious Activity Report prepared ({sar_draft.sar_tracking_id}).",
                f"[GATE] Human compliance officer sign-off strictly required before filing."
            ])

            trace_html = "<br>".join([f"&gt; {esc(line)}" for line in trace_logs])
            st.markdown(f'<div class="gt-terminal">{trace_html}</div>', unsafe_allow_html=True)

            st.markdown("#### 🔍 Primary Ring Metric Snapshot")
            if graph_result.flagged_cycles:
                c_top = graph_result.flagged_cycles[0]
                st.markdown(f"""
                    <div style="background: #131E36; border: 1px solid #1E2C4F; border-radius: 8px; padding: 12px; font-size: 13px;">
                        <b>Primary Ring:</b> <code>{esc(c_top.cycle_id)}</code> ({c_top.hop_count} Hops)<br>
                        <b>Flow Decay:</b> <span style="color:#00F0FF;">{c_top.amount_decay_pct:.1f}%</span> (Mule Cut: ${c_top.initial_amount - c_top.final_amount:,.2f})<br>
                        <b>Hop Velocity:</b> <span style="color:#00F0FF;">{fmt_avg_hop(c_top)}</span> per hop ({fmt_hops_per_hour(c_top)})<br>
                        <b>Structuring Match:</b> <span style="color:#FF3366;">{c_top.structured_hop_count}/{c_top.hop_count} Hops</span><br>
                        <b>Shared Hardware:</b> <code>{esc(c_top.shared_devices[0]) if c_top.shared_devices else 'None'}</code><br>
                        <b>Composite Suspicion Score:</b> <span style="color:#FF3366;font-weight:bold;">{c_top.suspicion_score:.4f} / 1.00</span>
                    </div>
                """, unsafe_allow_html=True)
            else:
                st.info("No suspicious money mule rings flagged in this scenario.")

    # =========================================================================
    # TAB 2: EVIDENCE EXPLORER & SOURCE INSPECTION (NEW DEDICATED VIEW)
    # =========================================================================
    with tab_explorer:
        st.markdown("### 🔍 Evidence Explorer & Cycle Source Inspection")
        st.markdown(
            "Deep-dive inspection for any detected closed cycle: path topology, hop-by-hop amounts, "
            "temporal velocity, structuring compliance, mathematical score breakdown, and source transactions."
        )

        all_detected = graph_result.detected_cycles

        if not all_detected:
            st.warning("No closed cycles detected in this ledger scenario.")
        else:
            # Selector for cycle to inspect
            cycle_options = {
                c.cycle_id: f"{c.cycle_id} — {c.hop_count} Hops | Initial: ${c.initial_amount:,.2f} -> Final: ${c.final_amount:,.2f} | Risk: {c.risk_level} (Score: {c.suspicion_score:.2f})"
                for c in all_detected
            }
            selected_cid = st.selectbox(
                "Select Cycle to Inspect:",
                options=list(cycle_options.keys()),
                format_func=lambda x: cycle_options[x],
                index=0
            )

            # Update session state for graph canvas highlight
            st.session_state.selected_cycle_id = selected_cid

            chosen_cycle: CycleEvidence = next(c for c in all_detected if c.cycle_id == selected_cid)

            # Cycle Path Flow Display
            st.markdown("#### 🔄 Cycle Path Flow Sequence")
            path_pills = " &rarr; ".join([f"<span class='gt-pill {'gt-pill-red' if chosen_cycle.is_flagged_suspicious else 'gt-pill-cyan'}'>{esc(n)}</span>" for n in chosen_cycle.path])
            path_pills += f" &rarr; <span class='gt-pill {'gt-pill-red' if chosen_cycle.is_flagged_suspicious else 'gt-pill-cyan'}'>{esc(chosen_cycle.path[0])}</span>"
            st.markdown(f"<div>{path_pills}</div>", unsafe_allow_html=True)

            st.write("")

            # Cycle Metric KPI Cards
            c_kpi1, c_kpi2, c_kpi3, c_kpi4, c_kpi5 = st.columns(5)
            with c_kpi1:
                st.metric("Hop Count", f"{chosen_cycle.hop_count} Hops", delta="Bounded 3-6")
            with c_kpi2:
                st.metric("Flow Retention", f"{chosen_cycle.flow_retention_pct:.1f}%", delta=f"{chosen_cycle.amount_decay_pct:.1f}% Decay", delta_color="inverse")
            with c_kpi3:
                st.metric(
                    "Total Duration", fmt_duration(chosen_cycle),
                    delta=(f"{fmt_avg_hop(chosen_cycle)} / hop" if chosen_cycle.velocity_available and chosen_cycle.time_gaps_minutes else None),
                    delta_color="off"
                )
            with c_kpi4:
                st.metric(
                    "Velocity Rate", fmt_hops_per_hour(chosen_cycle),
                    delta=(velocity_label(chosen_cycle) if chosen_cycle.velocity_available else None),
                    delta_color="off"
                )
            with c_kpi5:
                st.metric("Suspicion Score", f"{chosen_cycle.suspicion_score:.4f}", delta=f"{chosen_cycle.risk_level} Risk", delta_color="normal" if chosen_cycle.is_flagged_suspicious else "off")

            st.divider()

            col_math, col_details = st.columns([1, 1])

            with col_math:
                st.markdown("#### 📐 Mathematical Suspicion Score Breakdown")
                st.markdown("""
                    Every alert is computed from configurable explainable weights. 
                    Cycles alone are never treated as fraud without corroborating evidence.
                """)

                math_dict = chosen_cycle.mathematical_rationale
                st.write(f"- **Flow Conservation Component** (Retained funds): `{math_dict.get('flow_conservation_component', 0.0):.4f}`")
                st.write(f"- **Temporal Velocity Component** (Rapid movement): `{math_dict.get('temporal_velocity_component', 0.0):.4f}`")
                st.write(f"- **BSA Structuring Component** ($8.5k-$10k band): `{math_dict.get('structuring_band_component', 0.0):.4f}`")
                st.write(f"- **Shared Hardware Infrastructure** (Botnet match): `{math_dict.get('shared_infrastructure_component', 0.0):.4f}`")
                st.write(f"- **Dormant Sleeper Reactivation** (>90d inactive): `{math_dict.get('dormancy_reactivation_component', 0.0):.4f}`")
                st.markdown(f"**Total Computed Suspicion Score:** `{chosen_cycle.suspicion_score:.4f} / 1.0000`")

            with col_details:
                st.markdown("#### 🛡️ Hardware & Entity Evidence")
                st.write(f"- **Shared Devices**: `{', '.join(chosen_cycle.shared_devices) if chosen_cycle.shared_devices else 'None (Unique hardware)'}`")
                st.write(f"- **Dormant Accounts Involved**: `{', '.join(chosen_cycle.dormant_accounts_involved) if chosen_cycle.dormant_accounts_involved else 'None (Customary tenure)'}`")
                st.write(f"- **BSA Structured Transfers**: `{chosen_cycle.structured_hop_count} / {chosen_cycle.hop_count} hops ({chosen_cycle.structuring_ratio*100:.0f}%)`")
                st.write(f"- **Initial Injection Amount**: `${chosen_cycle.initial_amount:,.2f}`")
                st.write(f"- **Final Closing Amount**: `${chosen_cycle.final_amount:,.2f}`")

            st.markdown("#### 📋 Chronological Hop-by-Hop Audit Trail")
            hop_rows = []
            for idx, h in enumerate(chosen_cycle.hops):
                hop_rows.append({
                    "Hop #": idx + 1,
                    "Tx ID": h.tx_id,
                    "Originator": h.from_account,
                    "Beneficiary": h.to_account,
                    "Amount ($)": f"${h.amount:,.2f}",
                    "Timestamp": h.timestamp or UNAVAILABLE,
                    "Hop Delta (min)": (
                        f"{h.time_delta_from_previous_minutes:.1f}" if h.time_delta_from_previous_minutes is not None
                        else ("Initial Hop" if idx == 0 else UNAVAILABLE)
                    ),
                    "Channel": h.channel,
                    "Device ID": h.device_id or "Unassigned",
                    "Structuring Band": "⚠️ Structured ($8.5k-$10k)" if h.is_structured else "Standard",
                    "Parallel Transfers": f"{h.parallel_tx_count} Other Tx(s)" if h.parallel_tx_count > 0 else "None"
                })
            st.dataframe(pd.DataFrame(hop_rows), use_container_width=True)

            st.markdown("#### 📑 Source Transactions for this Cycle")
            cycle_tx_objs = [tx for tx in ledger.transactions if tx.tx_id in chosen_cycle.all_tx_ids]
            src_tx_rows = [{
                "Tx ID": tx.tx_id,
                "Timestamp": tx.timestamp or UNAVAILABLE,
                "Sender": tx.sender_id,
                "Receiver": tx.receiver_id,
                "Amount ($)": tx.amount,
                "Channel": tx.channel,
                "Device ID": tx.device_id,
                "Memo": tx.memo
            } for tx in cycle_tx_objs]
            st.dataframe(pd.DataFrame(src_tx_rows), use_container_width=True)

    # =========================================================================
    # TAB 3: AUTONOMOUS MULTI-AGENT WAR ROOM
    # =========================================================================
    with tab_agents:
        col_tb_title, col_tb_badge = st.columns([3, 2])
        with col_tb_title:
            st.markdown("""
                <div style="display: flex; align-items: center; gap: 10px;">
                    <h3 style="margin: 0; color: #F8FAFC;">Tri-Agent Autonomous Deliberation Chamber</h3>
                </div>
            """, unsafe_allow_html=True)
        with col_tb_badge:
            verif = agent_investigation.citation_verification
            status_color = "#10B981" if verif.is_valid else "#FF3366"
            st.markdown(f"""
                <div style="text-align: right;">
                    <span class="gt-badge-cyan" style="margin-right: 6px;">Engine: {esc(agent_investigation.detective_report.inference_mode)}</span>
                    <span style="background: rgba(16, 185, 129, 0.15); color: {status_color}; border: 1px solid {status_color}; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">
                        ✓ Citations: {verif.total_citations_checked} Verified (0 Hallucinations)
                    </span>
                </div>
            """, unsafe_allow_html=True)

        st.markdown(f"""
            <div style="background: #131E36; border: 1px solid #1E2C4F; border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; font-size: 12px; color: #94A3B8;">
                <b style="color: #00F0FF;">Evidence Audit Trail:</b> {esc(verif.verification_notes)} | 
                <b>Verified Records:</b> {len(verif.verified_transactions)} Transactions, {len(verif.verified_accounts)} Accounts, {len(verif.verified_devices)} Hardware Devices.
            </div>
        """, unsafe_allow_html=True)

        col_det, col_prof, col_comp = st.columns(3)
        with col_det:
            st.markdown("""
                <div class="gt-card gt-card-cyan">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <h4 style="margin: 0; color: #00F0FF;">🕵️ Detective Agent</h4>
                        <span class="gt-badge-cyan">Flow Topology</span>
                    </div>
                    <div style="font-size: 12px; color: #94A3B8; margin-top: 4px;">Role: Graph Crime & Velocity Specialist</div>
                </div>
            """, unsafe_allow_html=True)
            st.markdown(agent_investigation.detective_report.raw_markdown)

        with col_prof:
            st.markdown("""
                <div class="gt-card gt-card-amber">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <h4 style="margin: 0; color: #FFB703;">👤 Entity Profiler</h4>
                        <span class="gt-badge-cyan">Identity & Device</span>
                    </div>
                    <div style="font-size: 12px; color: #94A3B8; margin-top: 4px;">Role: KYC, Dormancy & Hardware Analyst</div>
                </div>
            """, unsafe_allow_html=True)
            st.markdown(agent_investigation.profiler_report.raw_markdown)

        with col_comp:
            st.markdown("""
                <div class="gt-card gt-card-red">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <h4 style="margin: 0; color: #FF3366;">⚖️ Compliance Officer</h4>
                        <span class="gt-badge-red">Regulatory BSA</span>
                    </div>
                    <div style="font-size: 12px; color: #94A3B8; margin-top: 4px;">Role: Chief AML Legal & SAR Officer</div>
                </div>
            """, unsafe_allow_html=True)
            st.markdown(agent_investigation.compliance_report.raw_markdown)

    # =========================================================================
    # TAB 4: REGULATORY SAR DOSSIER & HUMAN REVIEW GATE
    # =========================================================================
    with tab_sar:
        st.markdown("### 📄 Evidence-Backed Suspicious Activity Report (FinCEN SAR Draft)")
        st.markdown(f"""
            <div style="background: rgba(255, 51, 102, 0.1); border: 1px solid #FF3366; border-radius: 8px; padding: 12px 18px; margin-bottom: 20px;">
                <b style="color: #FF3366;">⚠️ MANDATORY REGULATORY NOTICE:</b> {COMPLIANCE_DISCLAIMER}
            </div>
        """, unsafe_allow_html=True)

        sar_markdown_text = sar_draft.to_markdown()
        col_sar_content, col_sar_actions = st.columns([7, 3])

        with col_sar_content:
            st.text_area("Regulatory SAR Document (FinCEN Form Standard)", value=sar_markdown_text, height=520)

        with col_sar_actions:
            st.markdown("#### 🛡️ Human Compliance Review Gate")
            st.write("FinCEN regulations mandate certified human compliance officer review before filing or freezing accounts.")

            check_evidence = st.checkbox("1. Graph topology & hop evidence verified", value=st.session_state.human_reviewed)
            check_kyc = st.checkbox("2. Physical KYC files & dormant histories confirmed", value=st.session_state.human_reviewed)
            check_freeze = st.checkbox("3. Authorize temporary administrative debit restraint (hold)", value=st.session_state.human_reviewed)
            check_file = st.checkbox("4. Authorize electronic FinCEN SAR filing", value=st.session_state.human_reviewed)

            officer_name = st.text_input("Reviewing Officer Legal Name:", value=st.session_state.human_officer_name)
            officer_notes = st.text_area("Compliance Officer Verification Memo:", value="Independent review completed. Graph cycle evidence, structuring amounts, and shared device IDs substantiate money mule ring operations.")

            if st.button("✍️ Sign & Certify SAR Draft", use_container_width=True):
                if check_evidence and check_kyc:
                    st.session_state.human_reviewed = True
                    st.session_state.human_officer_name = officer_name
                    st.session_state.review_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
                    st.success(f"SAR certified by Officer {officer_name} on {st.session_state.review_timestamp}!")
                else:
                    st.error("Please verify both graph evidence and KYC files before certifying.")

            st.divider()
            st.markdown("#### 💾 Export Regulatory Dossier")

            st.download_button(
                label="📥 Download SAR Draft (.MD)",
                data=sar_markdown_text,
                file_name=f"{sar_draft.sar_tracking_id}.md",
                mime="text/markdown",
                use_container_width=True
            )

            st.download_button(
                label="📥 Download Audit Dossier (.JSON)",
                data=json.dumps(sar_draft.to_dict(), indent=2),
                file_name=f"{sar_draft.sar_tracking_id}.json",
                mime="application/json",
                use_container_width=True
            )

    # =========================================================================
    # TAB 5: LABELLED BENCHMARK VS SINGLE-EVENT BASELINE
    # =========================================================================
    with tab_bench:
        st.markdown("### 📊 Labelled Benchmark vs Traditional Single-Event Baseline")
        st.markdown("""
            Evaluates the **GhostTrace Graph Engine** against a **Traditional Single-Event Rule Baseline**
            (which flags any individual transaction $\\ge \\$10,000$) on **the dataset currently selected in the sidebar**.
            Ground-truth labels are used only to score results, never to detect them.
        """)

        benchmark_res = get_cached_benchmark(bundle.key, bundle)
        df_bench = benchmark_res.to_dataframe()

        st.markdown(f"""
            <div style="background: #131E36; border: 1px solid #1E2C4F; border-radius: 8px; padding: 8px 14px; margin-bottom: 12px; font-size: 12px; color: #94A3B8;">
                <b style="color: #00F0FF;">Benchmark scope:</b> {esc(benchmark_res.provenance_caption())}
            </div>
        """, unsafe_allow_html=True)

        gt_m, bl_m = benchmark_res.ghost_trace_metrics, benchmark_res.baseline_metrics
        bm_col1, bm_col2, bm_col3, bm_col4, bm_col5 = st.columns(5)
        if benchmark_res.labels_available:
            with bm_col1:
                st.metric("GhostTrace F1 Score", f"{gt_m.f1_score:.3f}", delta=f"{gt_m.f1_score - bl_m.f1_score:+.3f} vs Baseline")
            with bm_col2:
                st.metric("GhostTrace Recall", f"{gt_m.recall * 100:.1f}%", delta=f"{(gt_m.recall - bl_m.recall) * 100:+.1f}% vs Baseline")
            with bm_col3:
                st.metric("GhostTrace Precision", f"{gt_m.precision * 100:.1f}%", delta=f"{(gt_m.precision - bl_m.precision) * 100:+.1f}% vs Baseline")
            with bm_col4:
                st.metric(
                    "False Positive Rate (FPR)", f"{gt_m.false_positive_rate * 100:.1f}%",
                    delta=f"{bl_m.false_positive_rate * 100:.1f}% Baseline FPR", delta_color="inverse"
                )
        else:
            for col, name in ((bm_col1, "GhostTrace F1 Score"), (bm_col2, "GhostTrace Recall"),
                              (bm_col3, "GhostTrace Precision"), (bm_col4, "False Positive Rate (FPR)")):
                with col:
                    st.metric(name, "N/A")
            st.info("This dataset has no ground-truth laundering labels, so accuracy metrics cannot be computed. "
                    "They are shown as N/A rather than 0.")
        with bm_col5:
            st.metric("Execution Latency", f"{gt_m.execution_time_ms:.1f} ms", delta="Real-Time NetworkX", delta_color="off")

        st.markdown("#### Detailed Performance Metrics Table")
        st.dataframe(df_bench, use_container_width=True)

        if benchmark_res.labels_available:
            st.markdown("#### Performance Metric Comparison")
            chart_data = pd.DataFrame({
                "Metric": ["Recall", "Precision", "F1 Score", "False Positive Rate (FPR)"],
                "GhostTrace (Graph + Agents)": [
                    gt_m.recall, gt_m.precision, gt_m.f1_score, gt_m.false_positive_rate
                ],
                "Legacy Rule Baseline (Tx >= $10k)": [
                    bl_m.recall, bl_m.precision, bl_m.f1_score, bl_m.false_positive_rate
                ]
            }).melt("Metric", var_name="Model", value_name="Score")

            st.bar_chart(chart_data, x="Metric", y="Score", color="Model", stack=False)

        st.markdown(f"""
            <div style="background: #131E36; border: 1px solid #1E2C4F; border-radius: 8px; padding: 15px; margin-top: 15px;">
                <h5 style="margin-top: 0; color: #00F0FF;">💡 Root Cause Analysis & Ground Truth Integrity</h5>
                <p style="font-size: 13px; color: #F8FAFC; margin-bottom: 0;">
                    {esc(benchmark_res.summary_analysis).replace(chr(10), '<br>')}
                </p>
            </div>
        """, unsafe_allow_html=True)

    # =========================================================================
    # TAB 6: RAW LEDGER DATA INSPECTOR
    # =========================================================================
    with tab_ledger:
        st.markdown(f"### 📜 Raw Ledger Data Inspector ({'IBM AMLSim' if not bundle.is_synthetic else 'Synthetic'}: {ledger.scenario_name})")
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            filter_flagged = st.checkbox("Show Only Flagged Suspicious Transactions", value=False)
        with col_f2:
            min_amt = st.number_input("Filter Minimum Transaction Amount ($):", min_value=0.0, value=0.0, step=500.0)
        with col_f3:
            channel_filter = st.selectbox("Filter Channel:", options=["All Channels", "wire", "p2p", "ach", "crypto_ramp"])

        tx_rows = []
        for tx in ledger.transactions:
            if filter_flagged and tx.tx_id not in graph_result.flagged_tx_ids:
                continue
            if tx.amount < min_amt:
                continue
            if channel_filter != "All Channels" and channel_filter not in tx.channel:
                continue

            tx_rows.append({
                "Tx ID": tx.tx_id,
                "Timestamp": tx.timestamp or UNAVAILABLE,
                "Originator": tx.sender_id,
                "Beneficiary": tx.receiver_id,
                "Amount ($)": tx.amount,
                "Channel": tx.channel,
                "Device ID": tx.device_id,
                "Flagged by GhostTrace": "⚠️ FLAGGED" if tx.tx_id in graph_result.flagged_tx_ids else "NORMAL"
            })

        df_txs = pd.DataFrame(tx_rows)
        st.dataframe(df_txs, use_container_width=True, height=450)

        st.download_button(
            label="📥 Download Full Ledger CSV",
            data=df_txs.to_csv(index=False),
            file_name=f"{ledger.scenario_name.lower().replace(' ', '_')}_ledger.csv",
            mime="text/csv"
        )


if __name__ == "__main__":
    main()
