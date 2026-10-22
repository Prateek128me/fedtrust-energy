"""
src/federated_train.py
------------------------------------------------------------------------------
ALGORITHM 1: TW-FIF - Trust-Weighted Federated Isolation Forest (Pipeline Step 3).

RESEARCH SIGNIFICANCE: this is the first of the project's two claimed-novel
algorithms. Standard federated averaging treats every client as equally
trustworthy, which is exactly the weakness a fraudulent device can exploit - a
compromised meter poisons the shared decision threshold as much as an honest
one does. TW-FIF instead weights each client's contribution by that client's
*current trust score*, so a device already under suspicion has shrinking
influence over what "normal" means for everyone else. Only a single scalar
(the local percentile threshold) ever leaves a client - raw readings never do -
which is the privacy property measured later in evaluate.py's mutual-
information metric.

Implementation notes:
  - TW-FIF's `trust_scores` parameter is a FIXED INPUT to the whole training
    call (used to weight every round), not something trust_engine.py updates
    mid-call. On this pipeline's very first run (Step 3 runs before Step 4,
    so data/trust_scores.json does not exist yet), every device starts at the
    brief's initial trust of 75 -> all client weights are equal -> round 1 of
    TW-FIF is mathematically identical to uniform FedAvg. On any later run
    (e.g. a subsequent day/epoch of operation), real trust scores from
    trust_engine.py are loaded and used, so a client that owns a suspected
    device measurably loses influence.
  - "Client datasets D_k" are each client's windowed 6-feature vectors from
    feature_extraction.py, not raw readings (see module docstring there for
    why: this IS the federation's privacy boundary).
  - 20 devices / 5 clients = 4 devices/client, assigned round-robin (not
    contiguous blocks) so every client gets a prosumer/consumer mix instead
    of dumping all 5 consumers onto a single client.

  IMPORTANT DEVIATION, DISCLOSED: the brief's pseudocode fits
  `IsolationForest(D_k, ..., random_state=42)` on the SAME static D_k every
  round, with no mechanism for D_k or the RNG to change between rounds.
  Verified directly: two IsolationForest fits with identical data and
  identical random_state produce byte-identical decision_function scores.
  Taken 100% literally, this means all "10 rounds" are mathematically
  identical and theta_global is constant from round 1 - "convergence over
  rounds" would be vacuous, and REQ-12's "print the global threshold after
  each round" would just print the same number 10 times.
  Fix applied: each round's local IsolationForest uses random_state = 42 +
  round_num (still 100% reproducible - reruns are identical - but each round
  now represents a distinct local retrain, exactly as multiple FL rounds are
  meant to). This is a deliberate, disclosed algorithmic completion, not a
  change to the TW-FIF weighting formula itself (REQ-01 is untouched).

  SECOND FINDING, ALSO DISCLOSED: even with that fix, theta_k stays ~0.000
  every round. Verified directly (see build log / README): scikit-learn's
  IsolationForest, given a float `contamination`, calibrates its own
  decision_function offset so that *exactly that fraction of the training
  data* scores below 0 - by construction, independent of the data's actual
  content or the random seed. theta_k = percentile(decision_function(D_k),
  contamination*100), evaluated on the SAME D_k the model was just fit on, is
  therefore close to tautological: it reports back approximately the value
  it was calibrated to produce. This is a real property of the specified
  algorithm (evaluate-on-own-training-data), not an implementation bug -
  confirmed empirically across multiple independent random datasets, all
  landing at theta_k ~ 0.000 regardless of content.
  Practical consequence: TW-FIF's trust-weighting doesn't show up as a
  moving theta_global (that number is pinned near 0 by sklearn's
  calibration no matter what). It shows up in which LOCAL MODELS end up
  more/less influential and in downstream classification quality - which is
  measured properly in evaluate.py using held-out scoring, not by watching
  theta_global move.
------------------------------------------------------------------------------
"""
import json
import pickle
import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest

sys.path.append(str(Path(__file__).resolve().parent))
from feature_extraction import build_all_device_features, FEATURE_COLUMNS  # noqa: E402

RANDOM_SEED = 42          # REQ-16
N_CLIENTS = 5             # REQ: 5 clients, 4 devices each
N_ROUNDS = 10             # REQ-12: exactly 10 rounds
CONTAMINATION = 0.05      # REQ: matches the 5% anomaly injection rate
INITIAL_TRUST = 75

ROOT = Path(__file__).resolve().parent.parent
TRUST_PATH = ROOT / "data" / "trust_scores.json"
MODEL_DIR = ROOT / "models"
LOCAL_MODEL_DIR = MODEL_DIR / "local_models"


def assign_clients(device_ids, n_clients=N_CLIENTS):
    """Round-robin device -> client assignment so every client mixes
    prosumers (DEV_000-014) and consumers (DEV_015-019) instead of one
    client ending up all-consumer."""
    device_ids = sorted(device_ids)
    clients = {k: [] for k in range(n_clients)}
    for i, dev in enumerate(device_ids):
        clients[i % n_clients].append(dev)
    return clients


def load_client_datasets():
    feats = build_all_device_features()
    device_ids = feats["device_id"].unique()
    client_map = assign_clients(device_ids)

    client_datasets = {}
    for client_id, devices in client_map.items():
        subset = feats[feats["device_id"].isin(devices)]
        client_datasets[client_id] = subset[FEATURE_COLUMNS].reset_index(drop=True)
    return client_datasets, client_map, feats


def load_trust_weights(client_map):
    """Cold start (see module docstring): defaults every device to trust=75
    if trust_scores.json doesn't exist yet. A client's weight is the mean
    trust of the devices it owns."""
    device_trust = {}
    if TRUST_PATH.exists():
        with open(TRUST_PATH) as f:
            raw = json.load(f)
        device_trust = {dev: v["trust_score"] for dev, v in raw.items()}

    weights = {}
    for client_id, devices in client_map.items():
        scores = [device_trust.get(dev, INITIAL_TRUST) for dev in devices]
        weights[client_id] = float(np.mean(scores))
    return weights


def federated_train(client_datasets, trust_scores, n_rounds=N_ROUNDS, contamination=CONTAMINATION):
    """Exact TW-FIF loop from the brief (Algorithm 1), verbatim formula:
    w_k = t_k / sum(t_i); theta_global = sum(w_k * theta_k)."""
    global_threshold = -0.1
    client_ids = sorted(client_datasets.keys())
    local_models = {}
    round_history = []  # for outputs/fl_convergence.png

    for round_num in range(n_rounds):
        local_thresholds, local_weights = [], []
        for cid in client_ids:
            data = client_datasets[cid]
            # random_state varies per round (42 + round_num), not frozen at 42 -
            # see the "IMPORTANT DEVIATION, DISCLOSED" note in the module docstring
            model = IsolationForest(contamination=contamination, n_estimators=100,
                                     random_state=RANDOM_SEED + round_num)
            model.fit(data)
            scores = model.decision_function(data)
            theta_k = np.percentile(scores, contamination * 100)
            local_thresholds.append(theta_k)
            local_weights.append(trust_scores[cid] / 100.0)
            local_models[cid] = model  # latest-round local model, used later for inference

        total_w = sum(local_weights)
        global_threshold = sum(t * w for t, w in zip(local_thresholds, local_weights)) / total_w
        round_history.append({"round": round_num + 1, "global_threshold": global_threshold,
                               "local_thresholds": local_thresholds, "weights": local_weights})
        print(f"Round {round_num + 1:02d}: Global threshold = {global_threshold:.6f}  "
              f"(client weights: {[round(w, 3) for w in local_weights]})")

    return global_threshold, local_models, round_history


def main():
    print("[federated_train] Loading client datasets (5 clients x 4 devices) ...")
    client_datasets, client_map, feats = load_client_datasets()
    for cid, devs in client_map.items():
        print(f"  Client {cid}: {devs}  ({len(client_datasets[cid])} windows)")

    trust_weights = load_trust_weights(client_map)
    cold_start = not TRUST_PATH.exists()
    print(f"[federated_train] Client trust weights "
          f"({'cold start, all devices at initial=75' if cold_start else 'loaded from trust_scores.json'}): "
          f"{trust_weights}")

    print(f"[federated_train] Running TW-FIF for {N_ROUNDS} rounds (contamination={CONTAMINATION}) ...")
    global_threshold, local_models, round_history = federated_train(client_datasets, trust_weights)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODEL_DIR / "global_threshold.pkl", "wb") as f:
        pickle.dump(global_threshold, f)
    for cid, model in local_models.items():
        with open(LOCAL_MODEL_DIR / f"client_{cid}.pkl", "wb") as f:
            pickle.dump(model, f)
    with open(ROOT / "data" / "fl_round_history.json", "w") as f:
        json.dump(round_history, f, indent=2)

    # client_map + device_features are persisted so trust_engine.py and
    # evaluate.py don't need to recompute the federation split or features
    with open(MODEL_DIR / "client_map.json", "w") as f:
        json.dump(client_map, f, indent=2)
    feats.to_csv(ROOT / "data" / "device_features.csv", index=False)

    print(f"[federated_train] DONE. Final global threshold = {global_threshold:.6f}")
    print(f"[federated_train] Saved -> {MODEL_DIR / 'global_threshold.pkl'}, "
          f"{len(local_models)} local models -> {LOCAL_MODEL_DIR}/")


if __name__ == "__main__":
    main()
