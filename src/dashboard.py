"""
src/dashboard.py
------------------------------------------------------------------------------
Streamlit live dashboard (Pipeline Step 10, optional per the brief).

REQ-18: shows a real-time trust score table, transaction log, anomaly flag
counts, and FL convergence chart. Reads the same JSON/CSV files every other
script in this pipeline produces - run the earlier steps first, or this
dashboard will show "not found yet" placeholders instead of crashing.

Run with: streamlit run src/dashboard.py
------------------------------------------------------------------------------
"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR, MODEL_DIR, OUT_DIR = ROOT / "data", ROOT / "models", ROOT / "outputs"

st.set_page_config(page_title="FedTrust-Energy Dashboard", layout="wide")
st.title("FedTrust-Energy - Live System Dashboard")
st.caption("Blockchain P2P Energy Trading with Federated Fraud Detection & Adaptive Trust Scoring")


def load_json(path):
    return json.loads(path.read_text()) if path.exists() else None


def missing(name, script):
    st.info(f"**{name}** not generated yet. Run `python src/{script}` first.")


# --- Row 1: trust scores + anomaly counts ---
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Real-Time Trust Score Table (20 Devices)")
    trust = load_json(DATA_DIR / "trust_scores.json")
    if trust:
        df = pd.DataFrame([
            {"device_id": dev, "type": v["device_type"], "trust_score": v["trust_score"],
             "anomalous_windows": f"{v['anomalous_windows']}/{v['epochs_evaluated']}",
             "status": "SUSPENDED" if v["suspended"] else
                       "BELOW TRADE THRESHOLD" if v["below_trade_threshold"] else "OK"}
            for dev, v in trust.items()
        ]).sort_values("device_id")

        def highlight_status(row):
            # Set BOTH background and text color. With only a background, Streamlit's
            # dark theme keeps its default white text, which is invisible on these
            # pale row colors; an explicit dark text color works in light and dark themes.
            color = "#fee2e2" if row["status"] == "SUSPENDED" else \
                    "#fef3c7" if row["status"] == "BELOW TRADE THRESHOLD" else "#dcfce7"
            return [f"background-color: {color}; color: #111827"] * len(row)

        styled = df.style.apply(highlight_status, axis=1).format({"trust_score": "{:.2f}"})
        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        missing("trust_scores.json", "trust_engine.py")

with col2:
    st.subheader("Anomaly Flag Counts")
    if trust:
        total_flagged = sum(v["anomalous_windows"] for v in trust.values())
        total_windows = sum(v["epochs_evaluated"] for v in trust.values())
        st.metric("Total anomalous windows flagged", f"{total_flagged} / {total_windows}",
                   f"{total_flagged/total_windows:.1%} of all windows")
        n_suspended = sum(1 for v in trust.values() if v["suspended"])
        n_warned = sum(1 for v in trust.values() if v["below_trade_threshold"] and not v["suspended"])
        st.metric("Devices suspended (trust<25)", n_suspended)
        st.metric("Devices below trade threshold (trust<50)", n_warned)
    else:
        missing("trust_scores.json", "trust_engine.py")

st.divider()

# --- Row 2: FL convergence + gas costs ---
col3, col4 = st.columns(2)

with col3:
    st.subheader("FL Convergence (TW-FIF)")
    history = load_json(DATA_DIR / "fl_round_history.json")
    if history:
        hist_df = pd.DataFrame(history)[["round", "global_threshold"]].set_index("round")
        st.line_chart(hist_df)
        st.caption("theta_global stays ~0 every round - see federated_train.py's disclosed "
                   "finding on IsolationForest's contamination-based score calibration.")
    else:
        missing("fl_round_history.json", "federated_train.py")

with col4:
    st.subheader("Average Gas Cost by Transaction Type")
    gas = load_json(DATA_DIR / "gas_log.json")
    if gas:
        avgs = {k: sum(v2 for v2 in v if v2 > 0) / max(len([v2 for v2 in v if v2 > 0]), 1)
                for k, v in gas.items() if v}
        st.bar_chart(pd.Series(avgs, name="avg_gas"))
    else:
        missing("gas_log.json", "oracle_bridge.py / simulate_trades.py")

st.divider()

# --- Row 3: transaction log ---
st.subheader("Transaction Log")
tx_path = DATA_DIR / "transaction_log.csv"
if tx_path.exists():
    tx_df = pd.read_csv(tx_path)
    c1, c2, c3 = st.columns(3)
    c1.metric("Total transactions", len(tx_df))
    c2.metric("Settled", int((tx_df["outcome"] == "settled").sum()))
    c3.metric("Denied by trust gate", int((tx_df["outcome"] == "denied").sum()))

    outcome_filter = st.multiselect("Filter by outcome", options=sorted(tx_df["outcome"].unique()),
                                     default=sorted(tx_df["outcome"].unique()))
    st.dataframe(tx_df[tx_df["outcome"].isin(outcome_filter)].tail(200),
                 use_container_width=True, hide_index=True)
else:
    missing("transaction_log.csv", "simulate_trades.py")

st.divider()
st.caption("This dashboard reflects the most recent pipeline run's saved files - it does not "
           "connect to a live chain itself. Re-run the pipeline (README.md) and refresh to update.")
