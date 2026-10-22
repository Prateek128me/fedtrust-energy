"""
src/simulate_iot.py
------------------------------------------------------------------------------
Synthetic IoT smart-meter data generator for FedTrust-Energy (Pipeline Step 1).

RESEARCH SIGNIFICANCE: federated fraud detection can only be *evaluated* if
ground truth is known, and real smart-meter deployments almost never have
labeled fraud data (utilities rarely know which historical readings were
fabricated). Generating a synthetic-but-physically-plausible dataset with
known injected anomalies is what makes it possible to compute precision,
recall, F1 and AUC for TW-FIF later in evaluate.py - without labels there is
nothing to score the model against.

Implementation notes (deviations from the literal generator code in the
brief, made for correctness - the ATSU/TW-FIF algorithms themselves are NOT
touched):
  1. The brief's device split is "15 prosumers (solar model) + 5 consumers",
     but its example generator code makes *every* device generate power via
     the same solar curve. That's inconsistent with having consumers at all,
     so consumers here get near-zero own-generation instead.
  2. The brief's replay-attack code does `df.loc[max(0, idx-1)]`, which reads
     the previous ROW OF THE WHOLE DATAFRAME - at a device boundary that's a
     different device's reading. Fixed to look up the previous reading of the
     SAME device (falls back to over_report on a device's very first row,
     where there is no previous reading to replay).
  3. Uses numpy arrays + a local np.random.default_rng(42) instead of
     row-by-row DataFrame.loc writes, purely for speed (10,000 scalar .loc
     writes over a 200,000-row frame is minutes-slow; this is seconds).
------------------------------------------------------------------------------
"""
import numpy as np
import pandas as pd
from pathlib import Path

RANDOM_SEED = 42                 # REQ-16: one seed, used everywhere
N_DEVICES = 20                   # 15 prosumers + 5 consumers
N_PROSUMERS = 15
N_STEPS = 10000                  # 15-min steps ~= 104 days per device
ANOMALY_RATE = 0.05              # 5% -> 10,000 anomalous rows of 200,000
ANOMALY_TYPES = ["over_report", "sudden_drop", "replay", "drift"]

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "data" / "energy_dataset.csv"


def generate_normal_readings(n_devices=N_DEVICES, n_steps=N_STEPS, n_prosumers=N_PROSUMERS,
                              seed=RANDOM_SEED):
    """Physically-plausible generation/consumption curves.

    Generation follows a rectified sine wave (solar output: ~zero at night,
    peaks at midday). Consumption is a two-bump curve (morning + evening
    demand) with noise. Devices 0..n_prosumers-1 are prosumers (own solar);
    the rest are pure consumers with negligible own-generation.
    """
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 4 * np.pi, n_steps)  # ~4 synthetic day-cycles, as in the brief

    frames = []
    for dev_id in range(n_devices):
        is_prosumer = dev_id < n_prosumers
        if is_prosumer:
            gen = np.maximum(0, 3.0 * np.sin(t) + rng.normal(0, 0.3, n_steps))
        else:
            gen = np.maximum(0, rng.normal(0.05, 0.05, n_steps))  # no solar panels

        cons = (1.5 * np.exp(-((t % (2 * np.pi) - 1.5) ** 2) / 0.2) +
                2.0 * np.exp(-((t % (2 * np.pi) - 4.5) ** 2) / 0.3) +
                rng.normal(0.5, 0.2, n_steps))
        cons = np.maximum(0, cons)

        df_dev = pd.DataFrame({
            "device_id": [f"DEV_{dev_id:03d}"] * n_steps,
            "timestamp": np.arange(n_steps),
            "energy_gen": np.round(gen, 3),
            "energy_cons": np.round(cons, 3),
        })
        frames.append(df_dev)

    df = pd.concat(frames, ignore_index=True)
    df["net_injection"] = np.round(df["energy_gen"] - df["energy_cons"], 3)
    df["anomaly"] = 0
    df["anomaly_type"] = "none"
    return df


def inject_anomalies(df, anomaly_rate=ANOMALY_RATE, n_steps=N_STEPS, seed=RANDOM_SEED):
    """Injects the 4 fraud/fault patterns from the brief at random rows.

    over_report : energy_gen *= U(2.5, 5.0)   -- inflated solar export claim
    sudden_drop : energy_cons = 0.0            -- masked real consumption
    replay      : row copies the SAME DEVICE's previous reading -- stale/duplicated telemetry
    drift       : energy_gen += energy_gen * 0.3 * (idx / N)    -- slow sensor tampering
    """
    rng = np.random.default_rng(seed)
    n_rows = len(df)
    n_anomalies = int(round(n_rows * anomaly_rate))
    anomaly_idx = rng.choice(n_rows, size=n_anomalies, replace=False)
    chosen_types = rng.choice(ANOMALY_TYPES, size=n_anomalies)

    gen = df["energy_gen"].to_numpy(copy=True)
    cons = df["energy_cons"].to_numpy(copy=True)
    anomaly = df["anomaly"].to_numpy(copy=True)
    anomaly_type = df["anomaly_type"].astype(object).to_numpy(copy=True)

    for idx, atype in zip(anomaly_idx, chosen_types):
        is_first_row_of_device = (idx % n_steps == 0)  # devices are contiguous n_steps-row blocks

        if atype == "over_report":
            gen[idx] = gen[idx] * rng.uniform(2.5, 5.0)
        elif atype == "sudden_drop":
            cons[idx] = 0.0
        elif atype == "replay":
            if is_first_row_of_device:
                atype = "over_report"           # nothing to replay -> fall back
                gen[idx] = gen[idx] * rng.uniform(2.5, 5.0)
            else:
                gen[idx] = gen[idx - 1]
                cons[idx] = cons[idx - 1]
        elif atype == "drift":
            gen[idx] = gen[idx] + gen[idx] * 0.3 * (idx / n_rows)

        anomaly[idx] = 1
        anomaly_type[idx] = atype

    df = df.copy()
    df["energy_gen"] = np.round(gen, 3)
    df["energy_cons"] = np.round(cons, 3)
    df["anomaly"] = anomaly
    df["anomaly_type"] = anomaly_type
    df["net_injection"] = np.round(df["energy_gen"] - df["energy_cons"], 3)
    return df


def main():
    print(f"[simulate_iot] Generating {N_DEVICES} devices x {N_STEPS} steps "
          f"({N_PROSUMERS} prosumers + {N_DEVICES - N_PROSUMERS} consumers) ...")
    df = generate_normal_readings()
    print(f"[simulate_iot] {len(df):,} clean records generated. "
          f"Injecting {ANOMALY_RATE:.0%} anomalies (seed={RANDOM_SEED}) ...")
    df = inject_anomalies(df)

    df = df[["device_id", "timestamp", "energy_gen", "energy_cons",
             "net_injection", "anomaly", "anomaly_type"]]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)

    n_anom = int(df["anomaly"].sum())
    print(f"[simulate_iot] Saved {len(df):,} records -> {OUTPUT_PATH}")
    print(f"[simulate_iot] Anomalous records: {n_anom:,} ({n_anom / len(df):.2%})")
    print("[simulate_iot] Breakdown by type:")
    print(df.loc[df['anomaly'] == 1, 'anomaly_type'].value_counts().to_string())


if __name__ == "__main__":
    main()
