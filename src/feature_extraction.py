"""
src/feature_extraction.py
------------------------------------------------------------------------------
Turns raw 15-min smart-meter readings into 6-dimensional daily feature
vectors, one per device per 96-step (1-day) window (Pipeline Step 2).

RESEARCH SIGNIFICANCE: IsolationForest (and every detector downstream) needs a
representation where fraud actually looks different from normal behaviour. A
single raw reading barely carries signal - a replay attack, for instance, is
invisible at the row level (the copied value is a perfectly plausible reading
on its own) but jumps out at the window level as near-1.0 autocorrelation.
Aggregating to day-level windows is what makes the 4 injected anomaly types
separable at all, and is also the natural unit for federation: one vector per
device per day is small enough that "share the statistic, not the raw
readings" is a credible privacy claim (measured later in evaluate.py).

Bug fix vs. the brief's example code: `df['net_injection'].autocorr(lag=1) or 0`
does NOT default NaN to 0 in Python (NaN is truthy, so `NaN or 0` evaluates to
NaN, not 0) - a constant-valued window makes autocorr undefined. Left as-is,
this NaN silently propagates into IsolationForest.fit() and raises a
ValueError. Fixed with an explicit pd.isna() check.
------------------------------------------------------------------------------
"""
import pandas as pd
from pathlib import Path

WINDOW = 96  # 96 x 15-min = 1 day, per the brief

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "energy_dataset.csv"
OUTPUT_PATH = ROOT / "data" / "device_features.csv"

# The 6 features fed into IsolationForest. `n_anomalous_rows` is tracked
# alongside them for evaluation ground truth ONLY - it is never given to the
# model (see FEATURE_COLUMNS vs. the full output columns).
FEATURE_COLUMNS = ["mean_injection", "std_injection", "gen_cons_ratio",
                    "max_deviation", "zero_cons_count", "autocorr"]


def extract_features(device_df, window=WINDOW):
    """Exactly the 6 features specified in the brief, computed per window."""
    device_df = device_df.reset_index(drop=True)
    rows = []
    for i in range(0, len(device_df) - window + 1, window):
        w = device_df.iloc[i:i + window]

        autocorr = w["net_injection"].autocorr(lag=1)
        if pd.isna(autocorr):
            autocorr = 0.0  # fixed: NaN (constant window) must default to 0, not stay NaN

        n_anomalous_rows = int(w["anomaly"].sum()) if "anomaly" in w.columns else 0

        rows.append({
            "window_start": i,
            "mean_injection": w["net_injection"].mean(),
            "std_injection": w["net_injection"].std(ddof=0) if len(w) > 1 else 0.0,
            "gen_cons_ratio": w["energy_gen"].mean() / max(w["energy_cons"].mean(), 0.001),
            "max_deviation": (w["net_injection"] - w["net_injection"].mean()).abs().max(),
            "zero_cons_count": int((w["energy_cons"] == 0).sum()),
            "autocorr": autocorr,
            "n_anomalous_rows": n_anomalous_rows,
        })
    return pd.DataFrame(rows)


def build_all_device_features(df=None):
    if df is None:
        df = pd.read_csv(DATA_PATH)
    all_feats = []
    for dev_id, dev_df in df.groupby("device_id", sort=True):
        feats = extract_features(dev_df)
        feats.insert(0, "device_id", dev_id)
        all_feats.append(feats)
    return pd.concat(all_feats, ignore_index=True)


def main():
    print(f"[feature_extraction] Reading {DATA_PATH} ...")
    feats = build_all_device_features()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    feats.to_csv(OUTPUT_PATH, index=False)
    print(f"[feature_extraction] {len(feats)} windows x {len(FEATURE_COLUMNS)} features "
          f"({feats['device_id'].nunique()} devices, ~{WINDOW}-step/1-day windows) -> {OUTPUT_PATH}")
    print(feats[["device_id"] + FEATURE_COLUMNS].head().to_string(index=False))


if __name__ == "__main__":
    main()
