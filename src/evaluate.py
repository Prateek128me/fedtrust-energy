"""
src/evaluate.py
------------------------------------------------------------------------------
Evaluation suite (Pipeline Step 9). Computes all 10 evaluation metrics from
Section 6, generates all 8 required visualizations to outputs/, and prints
the 3 result tables (REQ-09) - using REAL numbers from the actual pipeline
runs (federated_train.py, trust_engine.py, oracle_bridge.py,
simulate_trades.py), not the brief's target figures.

GROUND TRUTH NOTE (disclosed design decision, verified empirically - see
build log): anomalies are injected at the RAW READING level (~5% of all
200,000 rows, scattered ~uniformly - simulate_iot.py), but detection happens
at the WINDOW level (96-step/1-day aggregates - feature_extraction.py).
Because anomalies are scattered roughly uniformly, windows have on average
4.8 anomalous rows (Binomial(96, 0.05)) and only 0.8% of windows are fully
clean - so "window is anomalous" defined as "contains >=1 anomalous row"
would label ~99% of windows positive, which breaks precision/recall/F1 (no
real minority class) and doesn't match the ~5% contamination rate the whole
system assumes. Ground truth here is instead "this window's anomalous-row-
count is in the top 5% across all windows" (>=9 of 96 rows, empirically
verified to give a 5.67% positive rate). This is computed directly from the
real injected labels, not invented; it is a disclosed threshold CHOICE, not
a result.

THREE-MODEL COMPARISON:
  - Centralized IF (Baseline): one IsolationForest on all pooled windows -
    the pre-federated-learning status quo.
  - Standard FedIF (Uniform): identical federation mechanics to TW-FIF, but
    with equal (1/5) client weights instead of trust-weighted - isolates
    the effect of trust-weighting specifically.
  - TW-FIF (Proposed): the real trust-weighted federation, using the actual
    trust_scores.json values from trust_engine.py.
All three use the same round-varying-seed fix documented in
federated_train.py (applies to FedIF/TW-FIF only; centralized has no rounds).
------------------------------------------------------------------------------
"""
import json
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.ensemble import IsolationForest
from sklearn.feature_selection import mutual_info_regression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                              precision_score, recall_score, roc_auc_score, roc_curve)

sys.path.append(str(Path(__file__).resolve().parent))
from feature_extraction import build_all_device_features, FEATURE_COLUMNS  # noqa: E402
from federated_train import N_CLIENTS, N_ROUNDS, CONTAMINATION, RANDOM_SEED  # noqa: E402

warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR, MODEL_DIR, OUT_DIR = ROOT / "data", ROOT / "models", ROOT / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sns.set_style("whitegrid")
PALETTE = {"Centralized IF": "#6b7280", "Standard FedIF (Uniform)": "#f59e0b", "TW-FIF (Proposed)": "#2563eb"}


# --------------------------------------------------------------------------
# Ground truth
# --------------------------------------------------------------------------
def build_ground_truth(feats):
    counts = feats["n_anomalous_rows"].values
    threshold = np.percentile(counts, 95)
    gt = (counts >= threshold).astype(int)
    print(f"[evaluate] Ground truth: windows with >={threshold:.0f}/96 anomalous rows "
          f"labeled positive -> {gt.sum()}/{len(gt)} ({gt.mean():.2%})")
    return gt


# --------------------------------------------------------------------------
# Three models
# --------------------------------------------------------------------------
def train_centralized(feats):
    model = IsolationForest(contamination=CONTAMINATION, n_estimators=100, random_state=RANDOM_SEED)
    model.fit(feats[FEATURE_COLUMNS])
    scores = model.decision_function(feats[FEATURE_COLUMNS])
    threshold = np.percentile(scores, CONTAMINATION * 100)
    return scores, threshold


def train_federated(feats, client_map, weights_by_client, n_rounds=N_ROUNDS):
    """Same mechanics as federated_train.federated_train(), reimplemented
    here to also return per-window scores (federated_train.py itself only
    returns the global threshold + models, which is all the live pipeline
    needs)."""
    client_datasets = {cid: feats[feats["device_id"].isin(devs)][FEATURE_COLUMNS].reset_index(drop=True)
                        for cid, devs in client_map.items()}
    global_threshold = -0.1
    local_models = {}
    for round_num in range(n_rounds):
        local_thresholds, local_weights = [], []
        for cid in sorted(client_map.keys()):
            model = IsolationForest(contamination=CONTAMINATION, n_estimators=100,
                                     random_state=RANDOM_SEED + round_num)
            model.fit(client_datasets[cid])
            scores = model.decision_function(client_datasets[cid])
            local_thresholds.append(np.percentile(scores, CONTAMINATION * 100))
            local_weights.append(weights_by_client[cid])
            local_models[cid] = model
        total_w = sum(local_weights)
        global_threshold = sum(t * w for t, w in zip(local_thresholds, local_weights)) / total_w

    # score every window using its owning client's final-round model
    all_scores = np.zeros(len(feats))
    for cid, devs in client_map.items():
        idx = feats.index[feats["device_id"].isin(devs)]
        all_scores[idx] = local_models[cid].decision_function(feats.loc[idx, FEATURE_COLUMNS])
    return all_scores, global_threshold


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------
def compute_metrics(scores, threshold, ground_truth):
    preds = (scores < threshold).astype(int)  # IsolationForest convention: lower score = more anomalous
    tn, fp, fn, tp = confusion_matrix(ground_truth, preds, labels=[0, 1]).ravel()
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    auc = roc_auc_score(ground_truth, -scores) if len(set(ground_truth)) > 1 else float("nan")
    return {
        "accuracy": accuracy_score(ground_truth, preds),
        "precision": precision_score(ground_truth, preds, zero_division=0),
        "recall": recall_score(ground_truth, preds, zero_division=0),
        "f1": f1_score(ground_truth, preds, zero_division=0),
        "fpr": fpr, "auc": auc, "preds": preds,
        "confusion": {"tp": int(tp), "tn": int(tn), "fp": int(fp), "fn": int(fn)},
    }


def mutual_information_privacy(feats, client_map, local_model_thetas):
    """See module docstring for methodology. 'Raw data' baseline = summed
    per-feature self-information proxy (mutual_info_regression of each raw
    feature against itself) representing full disclosure. 'Model update' =
    summed per-feature MI between the raw features and the single shared
    scalar (that window's owning client's theta_k, replicated per-window) -
    representing what leaks through if only the threshold is shared, as
    TW-FIF actually does. Real numbers from real data; a disclosed
    comparative estimate, not a formal privacy proof."""
    X = feats[FEATURE_COLUMNS].values
    client_of_window = feats["device_id"].map(
        {dev: cid for cid, devs in client_map.items() for dev in devs}).values
    shared_scalar = np.array([local_model_thetas[c] for c in client_of_window], dtype=float)

    raw_baseline = sum(mutual_info_regression(X[:, [i]], X[:, i], random_state=RANDOM_SEED)[0]
                        for i in range(X.shape[1]))
    model_update_mi = sum(mutual_info_regression(X[:, [i]], shared_scalar, random_state=RANDOM_SEED)[0]
                           for i in range(X.shape[1]))
    reduction = 1 - (model_update_mi / raw_baseline) if raw_baseline > 0 else float("nan")
    return raw_baseline, model_update_mi, reduction


# --------------------------------------------------------------------------
# Visualizations (all 8, REQ-08)
# --------------------------------------------------------------------------
def plot_roc_curve(results, ground_truth):
    plt.figure(figsize=(7, 6))
    for name, r in results.items():
        if len(set(ground_truth)) > 1:
            fpr, tpr, _ = roc_curve(ground_truth, -r["scores"])
            plt.plot(fpr, tpr, label=f"{name} (AUC={r['metrics']['auc']:.3f})",
                      color=PALETTE[name], linewidth=2)
    plt.plot([0, 1], [0, 1], "k--", linewidth=1, label="Random")
    plt.xlabel("False Positive Rate"); plt.ylabel("True Positive Rate")
    plt.title("ROC Curve - Centralized IF vs Standard FedIF vs TW-FIF")
    plt.legend(loc="lower right"); plt.tight_layout()
    plt.savefig(OUT_DIR / "roc_curve.png", dpi=150); plt.close()


def plot_trust_evolution():
    with open(DATA_DIR / "attack_profile_trajectories.json") as f:
        d = json.load(f)
    plt.figure(figsize=(9, 6))
    for name, traj in d["trajectories"].items():
        plt.plot(traj, label=name, linewidth=2)
    plt.axhline(50, color="orange", linestyle="--", linewidth=1, label="MIN_TRUST (50)")
    plt.axhline(25, color="red", linestyle="--", linewidth=1, label="Suspension (25)")
    plt.xlabel("Epoch"); plt.ylabel("Trust Score")
    plt.title("Trust Score Evolution by Attack Profile (ATSU, real formula, seed=42)")
    plt.legend(); plt.ylim(0, 100); plt.tight_layout()
    plt.savefig(OUT_DIR / "trust_evolution.png", dpi=150); plt.close()


def plot_confusion_matrix(tw_fif_metrics):
    c = tw_fif_metrics["confusion"]
    mat = np.array([[c["tn"], c["fp"]], [c["fn"], c["tp"]]])
    plt.figure(figsize=(5.5, 5))
    sns.heatmap(mat, annot=True, fmt="d", cmap="Blues", cbar=False,
                xticklabels=["Pred Normal", "Pred Anomaly"], yticklabels=["True Normal", "True Anomaly"])
    plt.title("Confusion Matrix - TW-FIF")
    plt.tight_layout(); plt.savefig(OUT_DIR / "confusion_matrix.png", dpi=150); plt.close()


def plot_trust_distribution():
    with open(DATA_DIR / "trust_scores.json") as f:
        trust = json.load(f)
    scores = sorted(v["trust_score"] for v in trust.values())

    fig, ax = plt.subplots(figsize=(9, 4.5))
    rng = np.random.default_rng(RANDOM_SEED)
    jitter = rng.uniform(-0.15, 0.15, size=len(scores))
    ax.scatter(scores, jitter, s=60, color="#2563eb", alpha=0.8, zorder=3)
    ax.axvline(50, color="orange", linestyle="--", linewidth=1.5, label="MIN_TRUST (50)")
    ax.axvline(25, color="red", linestyle="--", linewidth=1.5, label="Suspension (25)")
    ax.set_xlim(0, 100)
    ax.set_ylim(-1, 1)
    ax.set_yticks([])
    ax.set_xlabel("Trust Score")
    ax.set_title(f"Trust Score Distribution - 20 Real Devices, Final Epoch "
                 f"(range: {min(scores):.2f}-{max(scores):.2f})")
    ax.legend(loc="upper left")
    plt.tight_layout()
    plt.savefig(OUT_DIR / "trust_distribution.png", dpi=150)
    plt.close()


def plot_fl_convergence():
    with open(DATA_DIR / "fl_round_history.json") as f:
        history = json.load(f)
    rounds = [h["round"] for h in history]
    thetas = [h["global_threshold"] for h in history]
    plt.figure(figsize=(8, 5))
    plt.plot(rounds, thetas, marker="o", color="#2563eb")
    plt.xlabel("FL Round"); plt.ylabel("Global Threshold (theta_global)")
    plt.title("FL Convergence - Global Threshold vs Training Round")
    span = max(max(thetas) - min(thetas), 1e-6)
    plt.ylim(min(thetas) - span, max(thetas) + span)
    plt.tight_layout(); plt.savefig(OUT_DIR / "fl_convergence.png", dpi=150); plt.close()


def plot_gas_costs():
    with open(DATA_DIR / "gas_log.json") as f:
        gas = json.load(f)
    # exclude placeholder zeros from reverted/excepted acceptOffer attempts -
    # those are not real gas measurements (see simulate_trades.py)
    labels, avgs = [], []
    for tx_type in ["registerDevice", "postOffer", "acceptOffer", "updateTrustScore"]:
        vals = [v for v in gas.get(tx_type, []) if v > 0]
        if vals:
            labels.append(tx_type); avgs.append(sum(vals) / len(vals))
    plt.figure(figsize=(8, 5))
    bars = plt.bar(labels, avgs, color=["#6b7280", "#2563eb", "#16a34a", "#f59e0b"])
    for b, v in zip(bars, avgs):
        plt.text(b.get_x() + b.get_width() / 2, v, f"{v:,.0f}", ha="center", va="bottom")
    plt.ylabel("Average Gas Used"); plt.title("Average Gas Cost by Transaction Type (real measurements)")
    plt.tight_layout(); plt.savefig(OUT_DIR / "gas_costs.png", dpi=150); plt.close()


def plot_tx_approval_rate():
    tx = pd.read_csv(DATA_DIR / "transaction_log.csv")
    counts = tx["outcome"].value_counts()
    plt.figure(figsize=(6, 6))
    colors = {"settled": "#16a34a", "denied": "#dc2626", "reverted": "#9ca3af"}
    plt.pie(counts.values, labels=counts.index, autopct="%1.1f%%",
            colors=[colors.get(k, "#999") for k in counts.index], startangle=90)
    plt.title(f"Transaction Outcomes - {len(tx)} Real Transactions")
    plt.tight_layout(); plt.savefig(OUT_DIR / "tx_approval_rate.png", dpi=150); plt.close()


def plot_anomaly_scores(tw_fif_scores, ground_truth):
    df = pd.DataFrame({"score": tw_fif_scores, "label": np.where(ground_truth == 1, "Anomalous", "Normal")})
    plt.figure(figsize=(7, 6))
    sns.violinplot(data=df, x="label", y="score", hue="label",
                    palette={"Normal": "#2563eb", "Anomalous": "#dc2626"}, legend=False)
    plt.xlabel(""); plt.ylabel("IsolationForest decision_function score")
    plt.title("TW-FIF Anomaly Scores: Normal vs Anomalous Windows")
    plt.tight_layout(); plt.savefig(OUT_DIR / "anomaly_scores.png", dpi=150); plt.close()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    print("[evaluate] Loading features + ground truth ...")
    feats = build_all_device_features()
    ground_truth = build_ground_truth(feats)

    with open(MODEL_DIR / "client_map.json") as f:
        client_map_raw = json.load(f)
    client_map = {int(k): v for k, v in client_map_raw.items()}
    with open(DATA_DIR / "trust_scores.json") as f:
        trust_scores = json.load(f)

    print("[evaluate] Training Centralized IF (baseline) ...")
    cent_scores, cent_threshold = train_centralized(feats)

    print("[evaluate] Training Standard FedIF (uniform weights) ...")
    uniform_weights = {cid: 1.0 / N_CLIENTS for cid in client_map}
    fedavg_scores, fedavg_threshold = train_federated(feats, client_map, uniform_weights)

    print("[evaluate] Training TW-FIF (real trust-weighted, from trust_scores.json) ...")
    trust_weights_by_client = {}
    for cid, devs in client_map.items():
        vals = [trust_scores[d]["trust_score"] for d in devs if d in trust_scores]
        trust_weights_by_client[cid] = (np.mean(vals) / 100.0) if vals else 0.75
    tw_scores, tw_threshold = train_federated(feats, client_map, trust_weights_by_client)

    results = {
        "Centralized IF": {"scores": cent_scores, "threshold": cent_threshold},
        "Standard FedIF (Uniform)": {"scores": fedavg_scores, "threshold": fedavg_threshold},
        "TW-FIF (Proposed)": {"scores": tw_scores, "threshold": tw_threshold},
    }
    for name, r in results.items():
        r["metrics"] = compute_metrics(r["scores"], r["threshold"], ground_truth)

    print("\n" + "=" * 78)
    print("TABLE 1: FRAUD DETECTION (real metrics, this run)")
    print("=" * 78)
    print(f"{'Model':<28}{'Accuracy':>10}{'Precision':>11}{'Recall':>9}{'F1':>8}{'AUC':>8}")
    for name, r in results.items():
        m = r["metrics"]
        auc_str = f"{m['auc']:.3f}" if not np.isnan(m["auc"]) else "n/a"
        print(f"{name:<28}{m['accuracy']:>9.1%} {m['precision']:>10.1%} {m['recall']:>8.1%} "
              f"{m['f1']:>7.3f} {auc_str:>8}")

    with open(DATA_DIR / "attack_profile_trajectories.json") as f:
        attack_data = json.load(f)
    print("\n" + "=" * 78)
    print("TABLE 2: TRUST SCORE CONVERGENCE (real ATSU formula, this run)")
    print("=" * 78)
    print(f"{'Attack Profile':<28}{'Rate':>7}{'Epochs to Warning':>20}{'Epochs to Suspension':>22}")
    for name, s in attack_data["summary"].items():
        print(f"{name:<28}{s['anomaly_rate']:>6.0%} {str(s['epochs_to_warning']):>19} "
              f"{str(s['epochs_to_suspension']):>22}")
    print("NOTE: suspension is structurally near-unreachable under the exact given ATSU")
    print("weights (BCS saturates regardless of trust level - see trust_engine.py). Not")
    print("tuned to the brief's target epoch numbers; this is the real formula's output.")

    with open(DATA_DIR / "gas_log.json") as f:
        gas = json.load(f)
    with open(DATA_DIR / "throughput.json") as f:
        throughput = json.load(f)
    print("\n" + "=" * 78)
    print("TABLE 3: BLOCKCHAIN GAS COSTS (real measurements, live Hardhat node)")
    print("=" * 78)
    print(f"{'Transaction':<20}{'Avg Gas':>12}{'Count':>8}{'Notes':>30}")
    notes = {"registerDevice": "One-time per device", "postOffer": "Blocked if trust<50",
              "acceptOffer": "Trust-gated settlement", "updateTrustScore": "Oracle-only privileged call"}
    for tx_type in ["registerDevice", "postOffer", "acceptOffer", "updateTrustScore"]:
        vals = [v for v in gas.get(tx_type, []) if v > 0]
        if vals:
            print(f"{tx_type:<20}{sum(vals)/len(vals):>12,.0f}{len(vals):>8}{notes[tx_type]:>30}")
    print(f"\nThroughput: {throughput['total_transactions']} tx in {throughput['elapsed_seconds']:.1f}s "
          f"= {throughput['tx_per_minute']:,.0f} tx/min (local Hardhat node, sequential, auto-mined)")

    last_round = json.load(open(DATA_DIR / "fl_round_history.json"))[-1]
    local_model_thetas = dict(zip(sorted(client_map.keys()), last_round["local_thresholds"]))
    raw_mi, model_mi, reduction = mutual_information_privacy(feats, client_map, local_model_thetas)
    print("\n" + "=" * 78)
    print("PRIVACY METRIC: Mutual Information (raw data vs shared artifact)")
    print("=" * 78)
    print(f"Raw-data-sharing baseline (self-MI proxy): {raw_mi:.4f}")
    print(f"TW-FIF shared artifact (per-window client theta_k): {model_mi:.4f}")
    print(f"Estimated reduction in information leakage: {reduction:.1%}")
    print("(Disclosed methodology - see mutual_information_privacy() docstring. A real,")
    print(" comparative estimate from this run's data, not a formal privacy proof.)")

    print("\n[evaluate] Generating 8 visualizations -> outputs/ ...")
    plot_roc_curve(results, ground_truth)
    plot_trust_evolution()
    plot_confusion_matrix(results["TW-FIF (Proposed)"]["metrics"])
    plot_trust_distribution()
    plot_fl_convergence()
    plot_gas_costs()
    plot_tx_approval_rate()
    plot_anomaly_scores(results["TW-FIF (Proposed)"]["scores"], ground_truth)
    for png in sorted(OUT_DIR.glob("*.png")):
        print(f"  {png}")

    print("\n[evaluate] DONE.")


if __name__ == "__main__":
    main()
