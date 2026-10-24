# GhostTrace – Handoff (Part 5: AMLSim integration — PARTIAL, BLOCKED on the official sample)

**Status in one line:** the official IBM AMLSim schema was verified and the existing strict adapter already matches it, but the official pre-generated sample could **not be retrieved**, so no AMLSim data was loaded, no AMLSim benchmark was run, and no AMLSim metric exists. Nothing here should be described as an AMLSim result.

## 1. Source verification (what was actually checked)
Checked on 2026-10-24 via the public web (the build sandbox itself had no network):
- **Repository** https://github.com/IBM/AMLSim (Apache-2.0): a multi-agent *simulator*. The README documents generating data with `transaction_graph_generator.py` + the Java simulator + `convert_logs.py`; it does not ship generated transaction files in the README. GitHub tree pages (`/sample`, `/outputs`) are blocked to automated access, so their contents were **not** inspected.
- **Schema (verified):** wiki page "Data Schema for Input Parameters and Generated Data Set" documents `transactions.csv` as `tran_id, orig_acct, bene_acct, tx_type, base_amt, tran_timestamp, is_sar, alert_id` (`tran_timestamp` = integer simulation step; `alert_id` = -1 when the transaction is in no alert). Related files: `accounts.csv`, `alert_accounts.csv`, `alert_transactions.csv`.
- **Documented pre-generated sample:** wiki page "Download Example Data Set" lists `100vertices-10Kedges` = 100 accounts, 10,000 transactions, 1 fraud pattern (1 fan_in), 7-Zip ~149 KB, in a Dropbox folder linked from that page. This is the smallest documented sample and the intended target.
- **Not selected:** (a) the Kaggle "IBM AMLSim Example Dataset" (third-party upload by `anshankul`, ~61 MB, 10,000 accounts — not the documented small sample, not official); (b) a Hugging Face mirror of the repo (unofficial, parameter files only); (c) the Kaggle "IBM Transactions for AML" HI/LI-Small files, which come from the **IT-AML generator, a different IBM dataset, not AMLSim**.

## 2. Blocker
The Dropbox archive could not be fetched (the fetch tool refused the link and the sandbox has no network), and a binary 7-Zip archive cannot be reconstructed through the assistant's text channel. **No file from that sample was downloaded or inspected.** Per the task rules, no sample data was fabricated.

**To finish:** download `100vertices-10Kedges` from the wiki's Dropbox link, extract to `data/amlsim/official/100vertices-10Kedges/`, run the integration tests (below), and read the real headers and `is_sar` / `alert_id` values before deciding anything about evaluation. See `data/amlsim/README.md`.

## 3. What changed in Part 5 (small, deliberate)
1. **Provenance correction (important).** The two CSVs in `data/amlsim/` (`transactions_sample.csv`, 12 rows; `HI-Small_Sample.csv`, 25 rows) are **hand-written test fixtures**, not AMLSim output (the second is even in the IT-AML/Kaggle column layout). Earlier handoffs/UI wording could be read as calling them AMLSim samples. New `data/amlsim/README.md` states this. Files were not renamed or removed because existing tests reference their paths.
2. `get_data_dir_instructions()` now leads with the official source/sample and says the Kaggle HI/LI files are a different dataset. The old text (Kaggle, `HI-Small_Trans.csv`, column lists) is kept because existing tests assert it.
3. New `tests/test_amlsim_official_sample.py` (5 tests): 3 integration tests against `data/amlsim/official/100vertices-10Kedges/transactions.csv` that **skip** (not pass) while the file is absent; 2 always-on guards (loader required columns are a subset of the wiki schema; data README declares the bundled CSVs as fixtures). The 3 integration tests were exercised once against a throwaway synthetic stand-in in a temp copy (all passed) purely to prove the test logic works; that stand-in was discarded and is not in the project.
4. `run_tests.py`: registers the new file and reports `unittest.SkipTest` as `[SKIP]` with a separate count. Nothing else in the runner changed.

Not changed: detectors, scoring, agents, visualizer, `dashboard_helpers.py`, `benchmark.py`, `app.py`, synthetic scenarios, presentation.

## 4. Requirements status (honest)
| Req | Status |
|---|---|
| 1 Verify source / pick sample | Schema + sample **identified and documented**; sample **not retrieved** |
| 2 Adapter | Pre-existing strict loader `load_amlsim_transactions()` matches the verified column names; **not exercised on real AMLSim data** |
| 3 Dataset selection | Pre-existing (Part 4); unchanged; not re-verified here (see §6) |
| 4 Ground-truth separation | Pre-existing in the strict loader (`result.labels`, ledger flags False); legacy `AMLSimAdapter` still stores labels on `Transaction.is_ground_truth_fraud` (see §7) |
| 5 Benchmark on AMLSim | **Not done.** No verified labels exist; the existing benchmark correctly shows N/A for label-less loads. No precision/recall/F1 may be claimed |
| 6 Tests | Partly: official-sample integration tests exist but skip; items 3-5, 7 (new dashboard-consistency / benchmark-attribution tests) **not added** |
| 7 Docs | This section + `data/amlsim/README.md` |
| 8 Verified ZIP | See §5: verification was **partial** |

## 5. Verification actually performed (and what could not be)
Sandbox lacked `pytest`, `streamlit`, `pyvis`, `altair` and had no network, so:
- **Real `python -m pytest -q`: NOT run.**
- **`python run_tests.py`: NOT run to completion.** It imports `tests/test_dashboard_correctness.py`, which imports `pyvis` and would abort here.
- What *was* run: a throwaway driver (outside the project, with an empty placeholder `pytest` module — the tests only `import pytest`) that executes every test function in the pyvis-independent files, using the same call-and-catch logic as `run_tests.py`.
  Result: **154 tests: 151 passed, 0 failed, 3 skipped** (149 pre-existing + 5 new; the 3 skips are the official-sample integration tests). The 36 tests in `test_dashboard_correctness.py` (incl. the Streamlit `AppTest`) were **not executed**, so the Part 4 figure of 185 could not be re-confirmed.
- No headless Streamlit run, no clean-extraction run of the *full* suite.
Re-run on a machine with dependencies: `pip install -r requirements.txt && python -m pytest -q && python run_tests.py`. Expect 190 collected (185 + 5 new), with 3 skipped until the official sample is added.

## 6. Commands
- App: `pip install -r requirements.txt && streamlit run app.py`
- Tests: `python -m pytest -q` ; `python run_tests.py`
- Official-sample tests only: `python -m pytest tests/test_amlsim_official_sample.py -q -rs`

## 7. Known limitations / recommended next step
1. **Dashboard wording:** `app.py` still labels the dataset option "IBM AMLSim" and lists the bundled fixtures under "Available AMLSim files", and its help text mentions Kaggle AML as AMLSim. Fixture/IT-AML files can therefore be mistaken for AMLSim. Recommended: label bundled fixtures "Test fixture (not AMLSim)" and Kaggle-format loads "IBM IT-AML (not AMLSim)". Not done because `app.py` cannot be run or tested in the sandbox.
2. The app's AMLSim path currently uses the legacy `AMLSimAdapter` (labels on `Transaction.is_ground_truth_fraud`; Part 4 stops the visualizer/engine from using them). Moving the dashboard to `load_amlsim_transactions()` (labels outside the ledger) would remove that risk by construction.
3. Evaluation design to settle *after* inspecting the real files: unit (transaction vs account vs alert pattern), whether `is_sar` or `alert_id >= 0` is the positive class (wiki: alerts can be false alerts), and how detector output (cycle/cluster members) maps to that unit. With one fan_in pattern, GhostTrace's cycle detector would be evaluated against a pattern type it is not built to find, so scores would be a small, non-generalisable sanity check at best.
4. `tran_timestamp` is a simulation step; without confirmed `base_date` + `step_unit` the loader uses an ordinal surrogate clock and velocity scores are not meaningful (existing, documented behaviour).
5. **Recommended next step:** add the official sample, run the three integration tests, read the headers/labels, record the verified facts here, then do the dashboard relabelling (item 1) and the evaluation design (item 3) in an environment where the full test suite can run.

---

## (previous handoff) Part 4: dashboard & visualization correctness)

Starting point: `ghosttrace_part3.zip` (149 tests passing; note: that ZIP was the one produced in Part 3 – it was not re-uploaded, so the Part 3 output was used as the source). Bounded cycle detection (`length_bound`), scoring and output format from Part 3 are preserved: the 15-scenario before/after engine snapshot is identical (cycle IDs included) except for the one new field `velocity_available`.

## What changed in Part 4
**1. Dataset consistency (root cause: `app.py`)** – the graph HTML and the benchmark were produced by `get_cached_graph_html(scenario_choice, seed_val, …)` / `get_cached_benchmark(scenario_choice, seed_val)`, which always regenerated the *synthetic* `mixed_ledger` (seed 42) when AMLSim was selected, while KPIs/tables used the AMLSim data.
- New `ghost_trace/dashboard_helpers.py` (Streamlit-free, unit-testable): `DatasetBundle` (source, label, cache key, ledger, engine result) with `load_synthetic`, `load_amlsim_file`, `load_amlsim_bytes`, `render_graph_html`, `run_benchmark`, `kpi_summary`.
- `app.py` now builds ONE bundle per run and derives graph, KPIs, findings, ledger/evidence tables and benchmark from it. Cache keys include the dataset key (source, file/scenario, seed or content hash, max rows); the bundle is passed as an un-hashed `_bundle` arg.
- A header line shows the active dataset; the ledger tab title names the source and scenario.

**2. Benchmark consistency** – `BenchmarkRunner.run_benchmark_on_ledger(ledger, graph_result=None, dataset_source, dataset_label, seed)` evaluates the *given* ledger (reusing the dashboard's engine result). `run_benchmark(scenario)` now delegates to it. `BenchmarkSuiteResult` gained `dataset_source`, `dataset_label`, `seed`, `labelled_positive_count`, `labels_available`, `provenance_caption()`; the Benchmark tab shows a "Benchmark scope" line (dataset, file/scenario, seed, accounts/tx, labelled positives). Datasets without ground-truth labels show **N/A** (not 0) for precision/recall/F1/FPR. Hard-coded "100% Pure Signals" and the "synthetic ledgers" blurb were replaced by computed values / dataset-aware text.

**3. Unavailable evidence (root cause: engine)** – missing timestamps were replaced with `datetime.now()` (in `build_graph` and per hop), which fabricated an "instant" cycle (inflated velocity score, `0.01h`/hundreds of hops/hr) and caused the naive/aware `TypeError` crash.
- `graph_engine.py`: missing timestamp stays `""`; no wall-clock substitution; datetimes compared via UTC-normalised copies (display values unchanged); new `CycleEvidence.velocity_available` (also in `to_dict()`); when False, duration/avg/hops-per-hour are placeholders (0), no gaps are reported, and the velocity score component is 0. Explanation text says "Velocity: Unavailable…". **Scoring change:** only cycles with missing/unparseable timestamps are affected (their velocity score used to be fabricated high). Valid-timestamp results are unchanged.
- Display helpers (`fmt_duration`, `fmt_hops_per_hour`, `fmt_avg_hop`) return **"Unavailable"**; simultaneous valid timestamps show "<0.01 h" / "Near-simultaneous". Used in the trace log, ring snapshot, Evidence Explorer KPIs, hop audit table (timestamps/deltas) and the Detective agent text.

**4. Visualization leakage (`ghost_trace/visualizer.py`)** – removed use of `tx.is_ground_truth_fraud`, `tx.pattern_type == "legit_rebate"`, and `"SMURF" in id` / `startswith("LEGIT")`. Styling is evidence-only: red = in a flagged cycle/cluster; amber diamond = member of a *flagged smurfing cluster*; green dashed = in a cycle the engine cleared as benign; blue = no alert; cyan/magenta = selected cycle. Legend and tooltips reworded accordingly ("FLAGGED BY INVESTIGATION", "NO ALERT"). `mask_identifiers=True` (default; used by the dashboard for synthetic data) shows neutral hashed aliases for account, transaction, device and IP values and hides legal names/memos on the canvas, because the synthetic generator's names/IDs (e.g. `SMURF-MULE-1`, `LEGIT-SUPPLIER`, "Disposable Runner 1", `DEV-SHARED-…`, a distinct merchant IP block) reveal the answer. AMLSim identifiers are shown as loaded. Real IDs remain in the Evidence/Ledger tabs. The "Ground Truth Fraud" (Evidence Explorer) and "Pattern Type" (Ledger inspector) columns were removed from the UI.

**5. Safe rendering** – all untrusted text interpolated into `unsafe_allow_html` blocks in `app.py` (trace log lines, cycle IDs, path pills, devices, verifier notes, benchmark summary, inference mode, dataset label) goes through `esc()`. In the visualizer every tooltip field is `html.escape`d; canvas labels strip `<`/`>`/control chars; node IDs are opaque (`n0…`) so account IDs never reach the embedded JSON. (PyVis already escapes `<` as `\u003c` in its JSON, which protects the script block; the tooltip escaping protects the decoded HTML.)

## Tests / results (actual)
- New `tests/test_dashboard_correctness.py`: 36 tests (dataset switching, KPI/benchmark consistency, no-label benchmark, unavailable evidence incl. mixed/aware timestamps, leakage via labels / pattern_type / ID substrings / synthetic names, escaping of names, memos, IDs, devices, IP, and an end-to-end Streamlit `AppTest` dataset switch). Registered in `run_tests.py`.
- Mutation sanity checks (temporarily re-introducing each old bug made tests fail): ground-truth edge styling, ID-substring styling, benchmark regenerating synthetic data, `datetime.now()` timestamp fallback, unescaped memo / account name / KYC.
- `python -m pytest -q`: **185 passed** (149 prior + 36 new).
- `python run_tests.py`: **185/185 passed, 0 failed**.
- Headless `streamlit.testing AppTest` run of `app.py` in Synthetic and AMLSim modes: no exceptions.
- Clean-extraction re-run of `ghosttrace_part4.zip`: pytest **185 passed**; `run_tests.py` **185/185 passed** (final numbers also reported in the Part 4 reply).

## Remaining issues / notes
1. Streamlit emits `use_container_width` deprecation warnings (pre-existing; not changed).
2. The `unsafe_allow_html` escaping in `app.py` is covered by code review and the AppTest smoke test, not by a test that injects hostile names through the real UI (AppTest cannot drive the file uploader). Visualizer escaping is tested directly.
3. Masked aliases mean synthetic node labels on the canvas are not human-readable IDs; use the Evidence/Ledger tabs for real IDs. `GraphVisualizer(mask_identifiers=False)` restores real labels.
4. Native-format AMLSim loads carry labels outside the ledger, so their benchmark shows "N/A (no labels)".
5. The mixed-timezone fix treats naive timestamps as UTC for arithmetic only.
6. `all_tx_ids`/smurfing list ordering still comes from sets; `run_tests.py` still uses a hard-coded file list; `patch_app.py` / `_app_new_block.py` remain untouched leftovers (the latter predates the dataset-source work and is not imported).
7. Not done (out of scope): smurfing-detector review, API/LLM modes, presentation updates.

## Part 3 – bounded cycle detection (previous handoff, preserved)

Source of truth: `ghost_trace_updated_tested.zip` (128 tests passing at start).
Verified at start: **no `HANDOFF.md` and no `timeutil.py`** existed in that ZIP; nothing was assumed. Timestamp handling lives in `ghost_trace/graph_engine.py` (`safe_parse_datetime`) and `ghost_trace/amlsim_adapter.py` (`_parse_timestamp`); both were left untouched.

## What changed
1. `ghost_trace/graph_engine.py`
   - `_detect_and_evaluate_cycles` no longer calls `list(nx.simple_cycles(g))` and filters afterwards.
   - New `FinancialGraphEngine._enumerate_bounded_cycles()` calls `nx.simple_cycles(g, length_bound=max_cycle_length)` (NetworkX >= 3.1; requirements pin >= 3.2; tested on 3.6.1), then applies `min_cycle_length`.
   - Falls back to unbounded enumeration + filter if `length_bound` is unsupported (`TypeError`), so results are identical on old NetworkX.
   - Defensive dedupe by canonical rotation; cycles are returned in a deterministic order (rotated to the smallest node id, sorted).
   - Limits unchanged: min 3, max 6 (`config.py` untouched). Scoring, evidence, `to_dict()` format unchanged.
2. `tests/test_cycle_bounds.py` – 21 new tests (within/at/beyond limit, below minimum, custom limit, mixed lengths, empty graphs, overlapping cycles, duplicates, parallel transfers, determinism, bound passed to NetworkX, legacy fallback, equivalence with old method on random graphs, dense graph, output format, missing-device and timestamp regression checks). Written without fixtures so they run under both pytest and `run_tests.py`.
3. `run_tests.py` – registered `test_cycle_bounds.py`.
4. Added this file. No dashboard (`app.py`, `visualizer.py`), agent, or adapter changes.

## Behaviour verification
- Before/after snapshot of full `run_investigation().to_dict()` on 15 generated scenarios (5 scenario types x seeds 1, 42, 7): **identical** after normalising `cycle_id` and unordered lists (`all_tx_ids`, smurf account/device lists, which were already built from sets).
- One visible difference: **`cycle_id` numbering (RING-nn) can differ** from before, because IDs are assigned in enumeration order, which is now deterministic (sorted) instead of NetworkX's internal order. The set of cycles and all their scores are the same. Score ties sort by that ID order.
- Micro-benchmark (random digraphs, bound 6): 2.9x (14 nodes), 13x (16), 89x (18) faster than unbounded enumeration, same cycle counts.

## Test results (actual)
- `python -m pytest -q` : **149 passed** (128 original + 21 new)
- `python run_tests.py` : **149/149 passed, 0 failed**
- Re-run on a clean extraction of `ghosttrace_part3.zip` into an empty directory: pytest **149 passed**; `run_tests.py` **149/149 passed**.

## Remaining issues (not fixed – out of scope)
1. **[FIXED in Part 4]** Pre-existing crash (reproduced on the original ZIP): a cycle mixing parseable naive timestamps with an unparseable one raises `TypeError: can't subtract offset-naive and offset-aware datetimes` in `_evaluate_single_cycle`, because the invalid-timestamp fallback is `datetime.now(timezone.utc)` (aware) while valid ISO strings without a zone are naive. All-invalid and all-valid cases work. Suggested fix: normalise all datetimes to one tz convention in `safe_parse_datetime`, and avoid `now()` as a stand-in.
2. `all_tx_ids` and smurfing list fields come from `set()` so their order varies with hash seed.
3. `run_tests.py` only discovers files in its hard-coded list and cannot run fixture/parametrized tests.
4. Smurfing detection and `_evaluate_single_cycle` were not optimised.
5. `patch_app.py` / `_app_new_block.py` are leftover helper scripts from earlier work; not touched.
