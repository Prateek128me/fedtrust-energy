"""
test/test_fl_model.py
------------------------------------------------------------------------------
Tests for the ML/FL layer: feature extraction, TW-FIF's client assignment,
and ATSU's formula. Run with: pytest test/test_fl_model.py -v

A few of these are regression tests for the real, disclosed findings in this
build (see federated_train.py and trust_engine.py docstrings) rather than
tests of "does the code match some target number" - they exist so a future
change that accidentally alters that behavior gets caught.
------------------------------------------------------------------------------
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import IsolationForest

sys.path.append(str(Path(__file__).resolve().parent.parent / "src"))

from feature_extraction import extract_features, FEATURE_COLUMNS  # noqa: E402
from federated_train import assign_clients, N_CLIENTS  # noqa: E402
from trust_engine import compute_trust_score, WEIGHTS, INITIAL_TRUST  # noqa: E402


# --------------------------------------------------------------------------
# feature_extraction.py
# --------------------------------------------------------------------------
def make_device_df(n_steps=96 * 3, seed=0):
    rng = np.random.default_rng(seed)
    gen = np.maximum(0, rng.normal(2, 0.5, n_steps))
    cons = np.maximum(0, rng.normal(1, 0.3, n_steps))
    return pd.DataFrame({
        "energy_gen": gen, "energy_cons": cons, "net_injection": gen - cons,
        "anomaly": np.zeros(n_steps, dtype=int),
    })


def test_extract_features_returns_all_six_columns():
    feats = extract_features(make_device_df())
    for col in FEATURE_COLUMNS:
        assert col in feats.columns


def test_extract_features_no_nans_even_on_constant_window():
    """Regression test for the autocorr NaN bug documented in
    feature_extraction.py: a perfectly constant window makes autocorr
    undefined, and `x or 0` silently fails to default it (NaN is truthy)."""
    constant_df = pd.DataFrame({
        "energy_gen": [1.0] * 96, "energy_cons": [0.5] * 96,
        "net_injection": [0.5] * 96, "anomaly": [0] * 96,
    })
    feats = extract_features(constant_df)
    assert not feats[FEATURE_COLUMNS].isnull().any().any()
    assert feats.loc[0, "autocorr"] == 0.0


def test_extract_features_window_count():
    n_steps = 96 * 5
    feats = extract_features(make_device_df(n_steps=n_steps))
    assert len(feats) == 5


# --------------------------------------------------------------------------
# federated_train.py
# --------------------------------------------------------------------------
def test_assign_clients_gives_five_clients_of_four():
    device_ids = [f"DEV_{i:03d}" for i in range(20)]
    client_map = assign_clients(device_ids)
    assert len(client_map) == N_CLIENTS
    for devices in client_map.values():
        assert len(devices) == 4
    all_assigned = sorted(d for devs in client_map.values() for d in devs)
    assert all_assigned == sorted(device_ids)


def test_assign_clients_mixes_prosumers_and_consumers():
    """Round-robin assignment should not dump all 5 consumers (DEV_015-019)
    onto a single client - each client should see at least one consumer."""
    device_ids = [f"DEV_{i:03d}" for i in range(20)]
    client_map = assign_clients(device_ids)
    consumers = {f"DEV_{i:03d}" for i in range(15, 20)}
    for devices in client_map.values():
        assert len(set(devices) & consumers) >= 1


def test_isolation_forest_theta_k_is_near_zero_regardless_of_data():
    """Regression test for the documented finding in federated_train.py:
    scikit-learn calibrates decision_function's offset so that exactly
    `contamination` fraction of the TRAINING data scores below 0, making
    percentile(decision_function(D), contamination*100) on that SAME data
    close to tautological - true for any random data, any seed."""
    for seed in (1, 7, 99):
        X = np.random.default_rng(seed).normal(size=(300, 6))
        model = IsolationForest(contamination=0.05, n_estimators=100, random_state=seed)
        model.fit(X)
        theta = np.percentile(model.decision_function(X), 5)
        assert abs(theta) < 1e-3, f"expected theta~0 for seed={seed}, got {theta}"


# --------------------------------------------------------------------------
# trust_engine.py (ATSU)
# --------------------------------------------------------------------------
def test_atsu_weights_sum_to_one():
    assert abs(sum(WEIGHTS) - 1.0) < 1e-9


def test_compute_trust_score_clamped_to_0_100():
    score = compute_trust_score(tx_history=[], anomaly_flags=[1], previous_score=0)
    assert 0 <= score <= 100
    score = compute_trust_score(tx_history=[], anomaly_flags=[0], previous_score=100)
    assert 0 <= score <= 100


def test_compute_trust_score_no_anomaly_moves_toward_82_5():
    """With empty tx_history (TSR/BCS/PCS default to 75) and no anomaly this
    epoch (APS=0), raw = 0.35*75 + 0.30*100 + 0.20*75 + 0.15*75 = 82.5 - the
    EMA should move previous_score toward 82.5, not away from it."""
    score = compute_trust_score(tx_history=[], anomaly_flags=[0], previous_score=INITIAL_TRUST)
    assert score > INITIAL_TRUST
    assert abs(score - (0.9 * INITIAL_TRUST + 0.1 * 82.5)) < 1e-6


def test_compute_trust_score_worst_case_floors_at_52_5_with_empty_history():
    """Regression test for the documented finding in trust_engine.py: with
    tx_history permanently empty, even a 100%-anomalous device's raw score
    can't go below 52.5 (TSR/BCS/PCS pinned at 75 default), so trust
    converges toward but never below that floor - explaining why suspension
    (<25) is unreachable with an empty tx_history no matter the anomaly rate."""
    trust = INITIAL_TRUST
    for _ in range(200):
        trust = compute_trust_score(tx_history=[], anomaly_flags=[1], previous_score=trust)
    assert trust > 52.0, f"expected convergence near 52.5 floor, got {trust}"


def test_compute_trust_score_deterministic():
    a = compute_trust_score(tx_history=[{"success": True, "trust_at_time": 80}],
                             anomaly_flags=[0], previous_score=75)
    b = compute_trust_score(tx_history=[{"success": True, "trust_at_time": 80}],
                             anomaly_flags=[0], previous_score=75)
    assert a == b


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
