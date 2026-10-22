"""
src/trust_engine.py
------------------------------------------------------------------------------
ALGORITHM 2: ATSU - Adaptive Trust Score Update (Pipeline Step 4).

RESEARCH SIGNIFICANCE: TW-FIF only produces a binary anomaly flag per device
per window. On its own that's a blunt instrument - one false positive would
look identical to a genuinely compromised meter. ATSU turns that noisy
per-window signal into a slowly-moving reputation score (EMA decay alpha=0.9)
so a single bad reading nudges trust down instead of instantly blocking a
device, while a sustained pattern of anomalies drives the score down fast
enough to actually reach the blockchain's suspension/trading thresholds. This
is the score DeviceRegistry.sol and EnergyTrade.sol gate every transaction on.

Two things run in this script:
  1. compute_trust_score() applied to the 20 REAL devices, using each
     device's own client model to score its own windows against the shared
     global threshold (the INFERENCE rule from Algorithm 1: "flag as ANOMALY
     if score < theta_global"), producing data/trust_scores.json - the file
     oracle_bridge.py pushes on-chain in Step 5. At this point in the
     pipeline no blockchain trades have happened yet (Step 8 runs later), so
     tx_history is empty for every device and the score is driven purely by
     APS (anomaly presence), exactly as the formula's defaults intend.
  2. simulate_attack_profiles() - a SEPARATE, clearly-synthetic experiment
     (REQ-13): 3 controlled devices at fixed anomaly rates (not the 20 real
     devices, which don't have attacker-labeled ground truth at those exact
     rates) to show how fast ATSU's EMA reacts to different attack
     intensities. Produces the epochs-to-warning / epochs-to-suspension
     table and the data plotted in outputs/trust_evolution.png.
     NOTE: the brief's Section 6 "Expected Results" table gives specific
     target epoch numbers (5/8, 10/28, 32/45+). Those numbers are not
     reproducible from the formula alone - the brief doesn't specify the
     exact per-epoch random draw sequence an attacker follows, only a summary
     rate - so this script runs the real formula with a disclosed, seeded
     random process and reports whatever epoch counts that produces, rather
     than being tuned to match the brief's table.
------------------------------------------------------------------------------
"""
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))

RANDOM_SEED = 42
ROOT = Path(__file__).resolve().parent.parent
FEATURES_PATH = ROOT / "data" / "device_features.csv"
MODEL_DIR = ROOT / "models"
OUT_PATH = ROOT / "data" / "trust_scores.json"
ATTACK_TRAJ_PATH = ROOT / "data" / "attack_profile_trajectories.json"

WEIGHTS = (0.35, 0.30, 0.20, 0.15)   # w1..w4, fixed, sums to 1.0 (REQ)
INITIAL_TRUST = 75                    # REQ: initial trust for new device
SUSPENSION_THRESHOLD = 25             # REQ: DeviceRegistry suspends below this
WARNING_THRESHOLD = 50                # REQ: EnergyTrade MIN_TRUST


def compute_trust_score(tx_history, anomaly_flags, previous_score=INITIAL_TRUST, weights=WEIGHTS):
    """Exact ATSU formula from the brief (Algorithm 2), unmodified:
    Trust = w1*TSR + w2*(1-APS)*100 + w3*BCS + w4*PCS, then EMA(alpha=0.9)."""
    w1, w2, w3, w4 = weights
    tsr = (sum(1 for t in tx_history if t["success"]) / len(tx_history) * 100
           if tx_history else 75)
    aps = sum(anomaly_flags) / len(anomaly_flags) if anomaly_flags else 0
    recent = [t.get("trust_at_time", 75) for t in tx_history[-10:]]
    bcs = max(0, 1 - np.std(recent) / np.mean(recent)) * 100 if len(recent) > 1 else 75
    pcs = np.mean([t.get("counterparty_trust", 75) for t in tx_history]) if tx_history else 75

    raw = w1 * tsr + w2 * (1 - aps) * 100 + w3 * bcs + w4 * pcs
    score = 0.9 * previous_score + 0.1 * raw   # EMA decay, alpha=0.9 (fixed, REQ)
    return round(min(100, max(0, score)), 2)


def score_device_windows(device_id, client_map, local_models, feats, global_threshold, feature_columns):
    """Each device's own client-local model scores its own windows; a window
    is flagged anomalous if score < theta_global (Algorithm 1's INFERENCE rule).
    One epoch = one day/window here, so anomaly_flags per epoch is [0] or [1]."""
    client_id = next(c for c, devs in client_map.items() if device_id in devs)
    model = local_models[client_id]
    dev_feats = feats[feats["device_id"] == device_id].sort_values("window_start")
    X = dev_feats[feature_columns]  # keep as DataFrame so column names match training
    scores = model.decision_function(X)
    flags = (scores < global_threshold).astype(int)
    return flags.tolist()


def run_real_device_trust(feats, client_map, local_models, global_threshold, feature_columns):
    results = {}
    for device_id in sorted(feats["device_id"].unique()):
        flags = score_device_windows(device_id, client_map, local_models, feats,
                                      global_threshold, feature_columns)
        trust = INITIAL_TRUST
        trajectory = [trust]
        for flag in flags:  # one epoch = one window, EMA-updated epoch by epoch
            trust = compute_trust_score(tx_history=[], anomaly_flags=[flag], previous_score=trust)
            trajectory.append(trust)
        dev_num = int(device_id.split("_")[1])
        results[device_id] = {
            "trust_score": trust,
            "device_type": "prosumer" if dev_num < 15 else "consumer",
            "epochs_evaluated": len(flags),
            "anomalous_windows": int(sum(flags)),
            "suspended": trust < SUSPENSION_THRESHOLD,
            "below_trade_threshold": trust < WARNING_THRESHOLD,
        }
    return results


def simulate_attack_profiles(n_epochs=50, seed=RANDOM_SEED):
    """Controlled experiment (REQ-13): 3 synthetic attackers, fixed anomaly
    rates, run through the real EMA formula.

    IMPORTANT, DISCLOSED MODELING CHOICE: with tx_history permanently empty,
    3 of ATSU's 4 weighted terms (TSR, BCS, PCS) are pinned at their default
    of 75 forever - only APS (weight 0.30) can move. Verified directly: even
    a permanently-100%-anomalous device's raw score floors at 52.5, which the
    EMA then approaches but can never cross below - so trust could NEVER
    reach the 50 or 25 thresholds with an empty tx_history, no matter how bad
    the anomaly rate (a device would never "converge" in the sense REQ-13
    and Section 6 describe). That only becomes possible once the tx_history
    terms move too - which is exactly what happens once the on-chain gate
    (EnergyTrade.sol, MIN_TRUST=50) starts rejecting a device's own trades:
    its own past failures then drag TSR and BCS down, on top of APS. So each
    simulated epoch here also attempts one transaction, with
    success = (this epoch's reading is not anomalous) AND (current trust is
    still >= MIN_TRUST) - i.e. an already-blocked device's trades keep
    failing even on a clean reading, exactly mirroring EnergyTrade's
    requiresTrust gate. This uses the EXACT given ATSU formula, unmodified;
    only the *input* (a populated, realistic tx_history) is supplied,
    matching how the full closed-loop system (Section 1) is described to
    behave. Not tuned to the brief's target epoch numbers - see module
    docstring.
    """
    rng = np.random.default_rng(seed)
    profiles = {
        "aggressive_40pct": {"rate": 0.40, "start_epoch": 0},
        "stealthy_15pct": {"rate": 0.15, "start_epoch": 0},
        "insider_15pct_from_ep20": {"rate": 0.15, "start_epoch": 20},
    }

    trajectories, summary = {}, {}
    for name, cfg in profiles.items():
        trust = INITIAL_TRUST
        tx_history = []
        traj = [trust]
        warning_epoch, suspend_epoch = None, None
        for epoch in range(1, n_epochs + 1):
            active = epoch >= cfg["start_epoch"]
            is_anomalous = (rng.random() < cfg["rate"]) if active else False
            tx_success = (not is_anomalous) and (trust >= WARNING_THRESHOLD)

            trust = compute_trust_score(tx_history=tx_history, anomaly_flags=[int(is_anomalous)],
                                         previous_score=trust)
            tx_history.append({"success": tx_success, "trust_at_time": trust, "counterparty_trust": 75})
            traj.append(trust)

            if warning_epoch is None and trust < WARNING_THRESHOLD:
                warning_epoch = epoch
            if suspend_epoch is None and trust < SUSPENSION_THRESHOLD:
                suspend_epoch = epoch
        trajectories[name] = traj
        summary[name] = {
            "anomaly_rate": cfg["rate"], "start_epoch": cfg["start_epoch"],
            "epochs_to_warning": warning_epoch, "epochs_to_suspension": suspend_epoch,
            "final_trust": trust,
        }
    return trajectories, summary


def main():
    from feature_extraction import FEATURE_COLUMNS

    print("[trust_engine] Loading FL outputs (global threshold + local models) ...")
    with open(MODEL_DIR / "global_threshold.pkl", "rb") as f:
        global_threshold = pickle.load(f)
    with open(MODEL_DIR / "client_map.json") as f:
        client_map = json.load(f)  # string-keyed after JSON round-trip

    local_models = {}
    for cid in client_map.keys():
        with open(MODEL_DIR / "local_models" / f"client_{cid}.pkl", "rb") as f:
            local_models[cid] = pickle.load(f)

    feats = pd.read_csv(FEATURES_PATH)

    print(f"[trust_engine] Scoring 20 devices against global threshold = {global_threshold:.6f} ...")
    device_trust = run_real_device_trust(feats, client_map, local_models, global_threshold, FEATURE_COLUMNS)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(device_trust, f, indent=2)
    print(f"[trust_engine] Saved 20 device trust scores -> {OUT_PATH}")

    for dev, info in device_trust.items():
        flag = (" SUSPENDED" if info["suspended"]
                else " below trade threshold" if info["below_trade_threshold"] else "")
        print(f"  {dev} ({info['device_type']:9s}): trust={info['trust_score']:6.2f}  "
              f"anomalous_windows={info['anomalous_windows']:>3}/{info['epochs_evaluated']}{flag}")

    print("\n[trust_engine] Running 3-attack-profile convergence experiment (REQ-13) ...")
    trajectories, summary = simulate_attack_profiles()
    with open(ATTACK_TRAJ_PATH, "w") as f:
        json.dump({"trajectories": trajectories, "summary": summary}, f, indent=2)

    print(f"{'Attack Profile':<26}{'Rate':>7}{'Epochs to Warning(<50)':>26}{'Epochs to Suspension(<25)':>28}")
    for name, s in summary.items():
        print(f"{name:<26}{s['anomaly_rate']:>6.0%} {str(s['epochs_to_warning']):>25} {str(s['epochs_to_suspension']):>27}")
    print(f"[trust_engine] Saved attack-profile trajectories -> {ATTACK_TRAJ_PATH}")

    print("\n[trust_engine] NOTE ON THE ABOVE (real finding, not a bug - see module docstring):")
    print("  At 15-40% sustained anomaly rates, none of the 3 profiles cross even the 50")
    print("  (warning) threshold within 50 epochs. Traced directly: BCS (w3=0.20) saturates")
    print("  near its ceiling (~95-99) almost immediately once a device's recent trust")
    print("  history is smooth - regardless of whether it is smoothly RISING or FALLING -")
    print("  because BCS measures variance, not level. Combined with PCS fixed at 75 (no")
    print("  counterparty data yet), those two terms alone floor 'raw' around ~31, even at")
    print("  100% sustained fraud (APS=1, TSR->0). Diagnostic sweep at higher rates:")

    for rate in (0.70, 0.90, 1.00):
        rng = np.random.default_rng(RANDOM_SEED)
        trust, hist = INITIAL_TRUST, []
        w_epoch = s_epoch = None
        for epoch in range(1, 51):
            is_anom = rng.random() < rate
            success = (not is_anom) and (trust >= WARNING_THRESHOLD)
            trust = compute_trust_score(hist, [int(is_anom)], trust)
            hist.append({"success": success, "trust_at_time": trust, "counterparty_trust": 75})
            if w_epoch is None and trust < WARNING_THRESHOLD:
                w_epoch = epoch
            if s_epoch is None and trust < SUSPENSION_THRESHOLD:
                s_epoch = epoch
        print(f"    rate={rate:>4.0%}: warning@{str(w_epoch):>4}  suspension@{str(s_epoch):>4}  "
              f"final_trust={trust:.2f}")
    print("  Conclusion: under the exact given formula/weights, suspension (<25) is not")
    print("  reachable even at 100% sustained fraud within 50 epochs (asymptote ~31) - a")
    print("  real limitation of the specified weighting, worth discussing in the report")
    print("  rather than a target this build should force numbers to hit.")


if __name__ == "__main__":
    main()
