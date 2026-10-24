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

    if dataset_source == "GhostTrace Synthetic Data":
        ledger, graph_result = get_cached_investigation(scenario_choice, seed_val)
        data_source_label = "GhostTrace Synthetic"
        data_source_badge_color = "#00F0FF"
    else:
        if amlsim_upload is not None:
            file_bytes = amlsim_upload.getvalue()
            ledger, graph_result, amlsim_load_result = get_cached_amlsim_investigation_upload(
                file_bytes, amlsim_upload.name, amlsim_max_rows
            )
        elif amlsim_file_path is not None:
            ledger, graph_result, amlsim_load_result = get_cached_amlsim_investigation(
                amlsim_file_path, amlsim_max_rows
            )
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

