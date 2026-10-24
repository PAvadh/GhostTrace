"""
PyVis Interactive Dark Navy Network Graph Visualizer
Renders an interactive financial crime network with deep navy background,
electric cyan account highlights, bold red flagged vampire cycles, and detailed hover tooltips.
Supports dynamic filtering and selected-cycle emphasis.
"""

import hashlib
import html
import re
from typing import Dict, Any, List, Optional, Set
import networkx as nx
from pyvis.network import Network

from ghost_trace.config import THEME_COLORS
from ghost_trace.graph_engine import GraphInvestigationResult, safe_float
from ghost_trace.data_generator import LedgerData


def _esc(value: Any) -> str:
    """HTML-escapes any untrusted value (None -> empty string)."""
    return html.escape("" if value is None else str(value), quote=True)


_UNSAFE_LABEL_CHARS = re.compile(r"[<>\x00-\x08\x0b\x0c\x0e-\x1f]")


def _plain(value: Any) -> str:
    """Sanitises text placed in canvas labels / JSON (no angle brackets or control chars)."""
    return _UNSAFE_LABEL_CHARS.sub("", "" if value is None else str(value))


def _alias(prefix: str, value: Any) -> str:
    """Stable, content-neutral display alias (same input -> same alias) used when masking identifiers."""
    digest = hashlib.sha1(str(value).encode("utf-8", "replace")).hexdigest()[:6].upper()
    return f"{prefix}-{digest}"


class GraphVisualizer:
    """
    Produces interactive PyVis graph visualizations with dark navy cybersecurity aesthetic.

    Styling is driven ONLY by investigation evidence (flagged cycles, flagged smurfing clusters,
    cycles the engine cleared as benign). Ground-truth labels, pattern_type, and substrings of
    account IDs/names are never used for colour, shape or edge style.

    mask_identifiers=True (default) replaces account IDs, names and device IDs shown on the canvas
    with neutral stable aliases, because synthetic data can carry revealing names
    (e.g. 'SMURF-MULE-1', 'LEGIT-SUPPLIER', 'Disposable Runner 1'). Pass False for real datasets
    whose identifiers are not label-bearing.
    """

    def __init__(self, height: str = "600px", width: str = "100%", mask_identifiers: bool = True):
        self.height = height
        self.width = width
        self.mask_identifiers = mask_identifiers

    def _acc_disp(self, acc_id: str) -> str:
        return _alias("ACC", acc_id) if self.mask_identifiers else str(acc_id)

    def _dev_disp(self, dev: Any) -> str:
        if dev in (None, "", "None"):
            return "Unassigned"
        return _alias("DEV", dev) if self.mask_identifiers else str(dev)

    def generate_html(
        self,
        ledger: LedgerData,
        investigation_result: GraphInvestigationResult,
        filter_mode: str = "all",
        selected_cycle_id: Optional[str] = None,
        output_path: Optional[str] = None
    ) -> str:
        """
        Constructs an interactive PyVis HTML network graph with custom dark theme.
        Filter modes: 'all', 'flagged_only', 'cycles_only'.
        Selected cycle ID: highlights the chosen ring in prominent glowing red/cyan.
        """
        net = Network(
            height=self.height,
            width=self.width,
            bgcolor=THEME_COLORS["bg_dark"],
            font_color=THEME_COLORS["text_light"],
            directed=True
        )

        # ---- Evidence-derived sets (never ground truth) ----
        flagged_nodes = set(investigation_result.flagged_accounts)
        flagged_tx_ids = set(investigation_result.flagged_tx_ids)

        smurf_nodes: Set[str] = set()
        for sc in investigation_result.smurfing_clusters:
            if sc.is_flagged_suspicious:
                smurf_nodes.add(sc.funder_account)
                smurf_nodes.add(sc.collector_account)
                smurf_nodes.update(sc.smurf_accounts)

        benign_cycle_nodes: Set[str] = set()
        benign_cycle_txs: Set[str] = set()
        for c in investigation_result.detected_cycles:
            if not c.is_flagged_suspicious:
                benign_cycle_nodes.update(c.path)
                benign_cycle_txs.update(c.all_tx_ids)

        # Collect nodes and txs of the selected cycle if specified
        selected_cycle_nodes: Set[str] = set()
        selected_cycle_txs: Set[str] = set()
        if selected_cycle_id:
            for c in investigation_result.detected_cycles:
                if c.cycle_id == selected_cycle_id:
                    selected_cycle_nodes.update(c.path)
                    selected_cycle_txs.update(c.all_tx_ids)
                    break

        # Build map of tx_id to cycle info for edge annotations
        tx_cycle_map: Dict[str, Dict[str, Any]] = {}
        for c in investigation_result.detected_cycles:
            for h in c.hops:
                tx_cycle_map[h.tx_id] = {
                    "cycle_id": c.cycle_id,
                    "delta_minutes": h.time_delta_from_previous_minutes,
                    "is_flagged": c.is_flagged_suspicious,
                    "score": c.suspicion_score
                }

        # Filter nodes to include based on filter_mode
        active_nodes: Set[str] = set()
        if filter_mode == "flagged_only":
            active_nodes = flagged_nodes.copy()
        elif filter_mode == "cycles_only":
            for c in investigation_result.detected_cycles:
                active_nodes.update(c.path)
        else:  # 'all'
            active_nodes = set(ledger.accounts.keys())

        # If a specific cycle is selected, always include its nodes
        if selected_cycle_nodes:
            active_nodes.update(selected_cycle_nodes)

        # Opaque internal node ids (safe for JSON/script embedding, carry no label information)
        node_ids: Dict[str, str] = {acc_id: f"n{i}" for i, acc_id in enumerate(ledger.accounts.keys())}

        # Add Nodes
        for acc_id, acc in ledger.accounts.items():
            if acc_id not in active_nodes:
                continue

            is_flagged = acc_id in flagged_nodes
            is_dormant = bool(acc.is_dormant) or (acc.dormancy_days or 0) > 60
            is_in_selected = acc_id in selected_cycle_nodes

            # Determine visual attributes from investigation evidence only
            if is_in_selected:
                node_color = {
                    "background": "#FF0055",
                    "border": THEME_COLORS["accent_cyan"],
                    "highlight": {"background": "#FF0033", "border": "#FFFFFF"}
                }
                size = 30
                shape = "dot"
            elif is_flagged and acc_id in smurf_nodes:
                node_color = {
                    "background": THEME_COLORS["warning_amber"],
                    "border": "#FFFFFF",
                    "highlight": {"background": "#F59E0B", "border": "#FFFFFF"}
                }
                size = 24
                shape = "diamond"
            elif is_flagged:
                node_color = {
                    "background": THEME_COLORS["flagged_red"],
                    "border": "#FFFFFF",
                    "highlight": {"background": "#FF0033", "border": "#00F0FF"}
                }
                size = 26
                shape = "dot"
            elif acc_id in benign_cycle_nodes:
                node_color = {
                    "background": THEME_COLORS["legit_green"],
                    "border": "#34D399",
                    "highlight": {"background": "#059669", "border": "#FFFFFF"}
                }
                size = 20
                shape = "dot"
            else:
                node_color = {
                    "background": "#1E293B",
                    "border": THEME_COLORS["accent_blue"],
                    "highlight": {"background": THEME_COLORS["accent_cyan"], "border": "#FFFFFF"}
                }
                size = 14
                shape = "dot"

            # Rich HTML tooltip (every untrusted field escaped)
            if is_flagged:
                status_badge = "<span style='color:#FF3366;font-weight:bold;'>⚠️ FLAGGED BY INVESTIGATION</span>"
            elif acc_id in benign_cycle_nodes:
                status_badge = "<span style='color:#10B981;'>IN CYCLE CLEARED AS BENIGN</span>"
            else:
                status_badge = "<span style='color:#94A3B8;'>NO ALERT</span>"
            dormant_badge = f"<span style='color:#F59E0B;'> (Dormant {_esc(acc.dormancy_days)}d)</span>" if is_dormant else ""

            disp_id = self._acc_disp(acc_id)
            if self.mask_identifiers:
                id_rows = f"<b>Account:</b> {_esc(disp_id)} {dormant_badge}<br>"
            else:
                id_rows = (
                    f"<b>Account:</b> {_esc(acc.account_id)} {dormant_badge}<br>"
                    f"<b>Legal Name:</b> {_esc(acc.name)}<br>"
                )
            balance = safe_float(acc.initial_balance, 0.0)
            tooltip_html = (
                f"<div style='font-family:sans-serif;font-size:13px;padding:8px;line-height:1.4;'>"
                f"{id_rows}"
                f"<b>Type:</b> {_esc(str(acc.account_type or '').replace('_', ' ').title())}<br>"
                f"<b>KYC Tier:</b> {_esc(acc.kyc_status)}<br>"
                f"<b>Device ID:</b> <code>{_esc(self._dev_disp(acc.device_id))}</code><br>"
                f"<b>IP Address:</b> {_esc(_alias('IP', acc.ip_address) if self.mask_identifiers else acc.ip_address)}<br>"
                f"<b>Balance:</b> ${balance:,.2f}<br>"
                f"<b>Status:</b> {status_badge}"
                f"</div>"
            )

            display_label = _plain(f"{disp_id}\n(${balance/1000:.1f}k)")

            net.add_node(
                node_ids[acc_id],
                label=display_label,
                title=tooltip_html,
                color=node_color,
                size=size,
                shape=shape,
                font={"color": THEME_COLORS["text_light"], "size": 11, "face": "monospace"}
            )

        # Add Edges
        for tx in ledger.transactions:
            if tx.sender_id not in active_nodes or tx.receiver_id not in active_nodes:
                continue
            if tx.sender_id not in node_ids or tx.receiver_id not in node_ids:
                continue

            is_flagged = tx.tx_id in flagged_tx_ids          # evidence only; NOT tx.is_ground_truth_fraud
            is_benign_cycle_tx = tx.tx_id in benign_cycle_txs and not is_flagged
            is_in_selected = tx.tx_id in selected_cycle_txs
            amount = safe_float(tx.amount, 0.0)

            if filter_mode == "flagged_only" and not is_flagged and not is_in_selected:
                continue
            if filter_mode == "cycles_only" and tx.tx_id not in tx_cycle_map:
                continue

            cycle_meta = tx_cycle_map.get(tx.tx_id, {})
            delta = cycle_meta.get('delta_minutes')
            delta_str = f" | {delta:.0f}m" if delta else ""

            if is_in_selected:
                edge_color = "#00F0FF"
                width = 4.5
                dashes = False
                edge_label = f"${amount/1000:.1f}k{delta_str} [SELECTED]"
            elif is_flagged:
                edge_color = THEME_COLORS["flagged_red"]
                width = 3.5
                dashes = False
                edge_label = f"${amount/1000:.1f}k{delta_str}"
            elif is_benign_cycle_tx:
                edge_color = THEME_COLORS["legit_green"]
                width = 2.0
                dashes = [5, 5]
                edge_label = f"${amount/1000:.1f}k"
            else:
                edge_color = "#334155"
                width = 1.0
                dashes = False
                edge_label = ""

            if self.mask_identifiers:
                flow_txt = f"{self._acc_disp(tx.sender_id)} &rarr; {self._acc_disp(tx.receiver_id)}"
                tx_id_txt = _esc(_alias("TX", tx.tx_id))
                memo_row = ""
            else:
                flow_txt = f"{_esc(tx.sender_id)} &rarr; {_esc(tx.receiver_id)}"
                tx_id_txt = _esc(tx.tx_id)
                memo_row = f"<b>Memo:</b> {_esc(tx.memo)}"
            ts_txt = _esc(tx.timestamp) if tx.timestamp else "Unavailable"
            tooltip_html = (
                f"<div style='font-family:sans-serif;font-size:12px;padding:6px;'>"
                f"<b>Tx ID:</b> {tx_id_txt}<br>"
                f"<b>Flow:</b> {flow_txt}<br>"
                f"<b>Amount:</b> <span style='color:{edge_color};font-weight:bold;'>${amount:,.2f}</span><br>"
                f"<b>Timestamp:</b> {ts_txt}<br>"
                f"<b>Channel:</b> {_esc(tx.channel)}<br>"
                f"<b>Device:</b> <code>{_esc(self._dev_disp(tx.device_id))}</code><br>"
                f"{memo_row}"
                f"</div>"
            )

            net.add_edge(
                node_ids[tx.sender_id],
                node_ids[tx.receiver_id],
                label=_plain(edge_label),
                title=tooltip_html,
                color=edge_color,
                width=width,
                dashes=dashes,
                arrows={"to": {"enabled": True, "scaleFactor": 0.8}},
                font={"color": edge_color, "size": 10, "align": "top"}
            )

        # Force-directed layout physics
        net.set_options("""
        {
          "physics": {
            "barnesHut": {
              "gravitationalConstant": -4500,
              "centralGravity": 0.35,
              "springLength": 120,
              "springConstant": 0.04,
              "damping": 0.15,
              "avoidOverlap": 0.3
            },
            "minVelocity": 0.75,
            "solver": "barnesHut"
          },
          "interaction": {
            "hover": true,
            "navigationButtons": true,
            "zoomView": true,
            "tooltipDelay": 150
          }
        }
        """)

        html_content = net.generate_html()

        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html_content)

        return html_content
