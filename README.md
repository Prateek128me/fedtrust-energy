# FedTrust-Energy

Blockchain-based P2P energy trading with federated fraud detection (TW-FIF) and
adaptive IoT trust scoring (ATSU).

**This README documents what actually happened building and running this
system** - real commands, real numbers from real runs, and every place the
implementation had to make a disclosed judgment call the original project
brief left ambiguous or got mathematically wrong. It does not report the
brief's target/expected figures as if they were measured; where the two
differ, both are shown.

---

## 1. Quick start - exact pipeline commands, in order

```bash
# Python environment
pip install -r requirements.txt --break-system-packages   # or your own venv

# Node environment
npm install
```

```bash
# Step 1 - Generate the synthetic 200,000-record dataset
python src/simulate_iot.py

# Step 2 - Extract 6-feature daily windows
python src/feature_extraction.py

# Step 3 - Federated training (TW-FIF), 10 rounds
python src/federated_train.py

# Step 4 - Compute trust scores (ATSU) for all 20 devices + attack-profile experiment
python src/trust_engine.py

# Step 5/6 - Start a local chain and deploy all 4 contracts (registers 20 devices too)
npx hardhat node                                            # separate terminal, leave running
npx hardhat run scripts/deploy.js --network localhost

# Step 7 - Oracle bridge: push real trust scores on-chain
python src/oracle_bridge.py

# Step 8 - Simulate 1,000 blockchain transactions
python src/simulate_trades.py

# Step 9 - Evaluate: 3-model comparison, all metrics, all 8 plots
python src/evaluate.py

# Step 10 (optional) - Live dashboard
streamlit run src/dashboard.py

# Optional - inspect deployed contract / device state from the CLI
npx hardhat run --no-compile --network localhost scripts/interact.js
DEVICE=DEV_005 npx hardhat run --no-compile --network localhost scripts/interact.js

# Tests
npx hardhat test                    # 7 contract tests
python -m pytest test/ -v           # 11 FL/ATSU unit tests
```

Note: this Hardhat version's `run` task doesn't accept trailing CLI
arguments at all (verified directly - both `script.js -- args` and
`script.js args` are rejected), which is why `interact.js` takes its
optional device filter via the `DEVICE=` environment variable instead of a
CLI flag.

If a step is cut off mid-run, just re-run it - everything is seeded (42) and
deterministic, so re-running any script reproduces the same output.

### A note on this project's own build environment

This project was built and verified inside a sandboxed container whose
network egress does **not** include `binaries.soliditylang.org`, which
Hardhat's own `compile` task needs to download the Solidity compiler. In a
normal environment `npx hardhat compile` will just work and none of the
following applies. In that sandbox, contracts were instead compiled via the
`solc` **npm package** (`scripts/solc_compile_check.js`) and the result
converted into Hardhat's native artifact format
(`scripts/write_hardhat_artifacts.js`), which is why some commands in this
build's own log use `--no-compile`. Both scripts are included in case you
hit the same restriction; if `npx hardhat compile` works for you, ignore
them entirely.

Also worth knowing if you're scripting this yourself rather than typing
commands by hand: this container did not keep background processes (like
`npx hardhat node &`) alive **across** separate tool/terminal invocations -
only within one continuous shell session. If you're automating this, start
the node and everything that talks to it in the same script/session.

---

## 2. What's real vs. what's the brief's target

The original brief (Section 6) gives specific "Expected Results" - 94.7%
accuracy, exact epoch-to-suspension counts, precise gas figures - presented
as targets the prototype "must achieve results close to." **This build does
not attempt to hit those numbers.** It implements the specified algorithms
exactly (formulas, weights, thresholds) and reports what the real code
actually produces. In several places, that turned out to be genuinely
different from the brief's table - not because of a bug, but because of real
mathematical properties of the specified algorithms, discovered by actually
building and running them rather than assuming they'd behave as described.

### Table 1: Fraud Detection (real, this run)

| Model | Accuracy | Precision | Recall | F1 | AUC |
|---|---|---|---|---|---|
| Centralized IF (baseline) | 90.9% | 15.4% | 13.6% | 0.144 | 0.581 |
| Standard FedIF (Uniform) | 90.8% | 15.2% | 13.6% | 0.143 | 0.565 |
| TW-FIF (Proposed) | 90.8% | 15.2% | 13.6% | 0.143 | 0.565 |

*Brief's target for TW-FIF: 94.7% / 92.3% / 91.8% / 0.921 / 0.97.* Real
precision/recall are far lower. This is a genuine result, not a bug - see
Finding 1 below for why, and the ground-truth methodology note in
`evaluate.py` for how "anomalous window" is defined given that anomalies
are injected at the row level but detected at the window level.

**TW-FIF and Standard FedIF produce identical results in this run.** All 20
real devices converged to closely clustered, healthy trust scores (81.45-
82.45 - see Finding 2), so trust-weighted and uniform-weighted client
averaging end up numerically indistinguishable. Trust-weighting would show
a real, different effect against a client population with genuinely
divergent trust scores; this run's real ATSU output didn't happen to produce
one (correctly - see Finding 2).

### Table 2: Trust Score Convergence (real, this run)

| Attack Profile | Rate | Epochs to Warning (<50) | Epochs to Suspension (<25) |
|---|---|---|---|
| Aggressive attacker | 40% | None (never, in 50 epochs) | None |
| Stealthy attacker | 15% | None | None |
| Insider threat (from ep.20) | 15% | None | None |

*Brief's targets: 5/8, 10/28, 32/45+ epochs.* Real result: **none of the
three profiles ever cross either threshold**, and a supplementary sweep
(`trust_engine.py`'s diagnostic block) shows suspension is essentially
unreachable even at 100% sustained fraud. See Finding 3.

### Table 3: Blockchain Gas Costs (real measurements, live Hardhat node)

| Transaction | Avg Gas | Count | Notes |
|---|---|---|---|
| `registerDevice()` | 125,084 | 20 | One-time per device |
| `postOffer()` | 155,550 | 500 | Blocked if trust<50 |
| `acceptOffer()` | 164,740 | 451* | Trust-gated settlement |
| `updateTrustScore()` | 126,985 | 20 | Oracle-only privileged call |

*451 = 500 attempts minus 49 that reverted for an unrelated reason (offer
already settled by an earlier cycle through a small offer pool - see
`simulate_trades.py`); those aren't real gas measurements of a normal call,
so they're excluded rather than averaged in as zeros.*

Real throughput: **1,000 transactions in 22.1s = 2,720 tx/min**, sequential,
on a local auto-mining Hardhat node. *Brief's target: ~420 tx/min* - this
build's number is real but not directly comparable, since it depends
entirely on this specific local node's mining/latency behavior, which the
brief doesn't fully specify either.

Real transaction outcomes (1,000 total, mixed-trust by design - see REQ-14
note in `simulate_trades.py`): **36.5% settled, 58.6% denied by the trust
gate, 4.9% reverted** for the unrelated reason above.

### Privacy metric (real, this run)

Raw-data-sharing baseline (self-information proxy): **31.82**
TW-FIF shared artifact (per-window client `theta_k`): **0.0175**
Estimated reduction in information leakage: **99.9%**

*Brief's target: 99.7% reduction.* These landed close by coincidence, not
by tuning - see the disclosed methodology in `evaluate.py`'s
`mutual_information_privacy()`, which is a real, defensible comparative
estimate rather than a formal information-theoretic proof (with only 5
federated clients, a rigorous bits-of-leakage bound isn't estimable from
this little data; the number here should be read as "much less than raw
data," not as a precise bit count).

---

## 3. Findings from actually building this (not in the original brief)

These emerged from implementing the specified formulas exactly and running
them for real - each is documented in more detail as inline comments at the
point in the code where it was discovered.

**Finding 1 - Window-level ground truth is underspecified.** Anomalies are
injected at the raw-reading level (~5% of 200,000 rows, scattered
~uniformly), but detection happens at the 96-step/1-day window level. Given
uniform scattering, a window has ~4.8 anomalous rows on average and only
0.8% of windows are completely clean - so "window is anomalous" defined as
"contains any anomalous row" would label ~99% of windows positive, making
precision/recall meaningless. This build defines ground truth as "top 5% of
windows by anomalous-row-count" (verified to give a 5.67% positive rate).
Real precision/recall against this stricter, correctly-posed definition are
genuinely much lower than the brief's claimed numbers - a legitimate result
of a harder, better-defined task, not a failure of the implementation.

**Finding 2 - `theta_k` is close to tautological.** scikit-learn's
`IsolationForest`, given a float `contamination`, calibrates its own
`decision_function` offset so that exactly that fraction of the *training
data* scores below 0. `theta_k = percentile(decision_function(D_k),
contamination*100)`, evaluated on the SAME `D_k` the model was just fit on,
is therefore ~0 regardless of what's actually in `D_k` - verified across
independent random datasets. This means TW-FIF's trust-weighting doesn't
show up as a moving `theta_global` (see `outputs/fl_convergence.png`, which
is real and correctly near-flat); it shows up in which local models are
more/less influential, measured downstream via classification quality.

**Finding 3 - ATSU's `BCS` term rewards consistency, not trustworthiness.**
`BCS = max(0, 1 - std(recent_10)/mean(recent_10)) * 100` measures the
*variance* of recent trust scores, not their *level*. Once a device's trust
settles into any smooth trajectory - rising, falling, or flat - `BCS`
saturates near 95-99%, essentially regardless of whether that trajectory is
healthy or unhealthy. Combined with `PCS` fixed at 75 (no counterparty
history early on), those two terms alone floor the achievable score around
~31 even at 100% sustained fraud (verified via direct trace in
`trust_engine.py`). Under the exact specified weights, the 25-point
suspension threshold is not reachable through the APS/TSR channel within any
reasonable timeframe. This is a legitimate methodological finding worth
discussing in a report, not a bug - and it directly explains why Table 2
shows "None" across the board.

**Finding 4 - the brief's example code has real, disclosed bugs**, fixed
here and noted at each fix site: the replay-anomaly injector could read
across device boundaries; `x or 0` doesn't default `NaN` to `0` in Python
(NaN is truthy), which would crash `IsolationForest.fit()`; all 20 devices
generated solar power identically despite 5 of them being specified as
consumers; `registry.devices(addr)` called from another Solidity contract
returns a raw tuple, not the named struct, so the brief's `EnergyTrade`
example wouldn't compile as written; and a `require()`-based revert inside
`requiresTrust` would make `TradeDenied` unobservable on-chain (a reverted
transaction's events are discarded by the EVM), so `EnergyTrade.sol` here
uses a soft-fail pattern instead.

---

## 4. Architecture

```
LAYER 1 - IoT PHYSICAL LAYER
  simulate_iot.py -> data/energy_dataset.csv (200,000 labeled records)

LAYER 2 - FEDERATED LEARNING LAYER
  feature_extraction.py -> 6-feature/window per device
  federated_train.py -> 5 clients x 4 devices, TW-FIF, 10 rounds -> global_threshold.pkl

LAYER 3 - ADAPTIVE TRUST SCORING ENGINE
  trust_engine.py -> ATSU (4-component formula + EMA) -> data/trust_scores.json
  oracle_bridge.py (Web3.py) -> TrustOracle.sol

LAYER 4 - BLOCKCHAIN LAYER (Hardhat local node)
  DeviceRegistry.sol | EnergyTrade.sol | TrustOracle.sol | AuditLog.sol
  EnergyTrade's trust check gates postOffer/acceptOffer at MIN_TRUST=50
```

Contract wiring (needed because `DeviceRegistry` and `TrustOracle` each
require the other's address at construction, which plain constructors can't
resolve): deploy `DeviceRegistry` with a placeholder oracle -> deploy
`AuditLog` -> deploy `TrustOracle` (needs `DeviceRegistry` + `AuditLog`) ->
`registry.setOracle(trustOracleAddress)` -> deploy `EnergyTrade` (needs
`DeviceRegistry` + `AuditLog`) -> `registry.setEnergyTrade(energyTradeAddress)`
-> register all 20 devices. All of this is in `scripts/deploy.js`.

---

## 5. Fixed implementation parameters (unchanged from the brief)

Solidity 0.8.x · `MIN_TRUST`=50 · Suspension threshold=25 · EMA alpha=0.9 ·
ATSU weights (0.35, 0.30, 0.20, 0.15) · FL contamination=0.05 · 5 clients x 4
devices x 10 rounds · Initial trust=75 · Window=96 steps · seed=42
everywhere · Hardhat local network only · Oracle = Hardhat `accounts[0]`.

## 6. Disclosed deviations from a fully literal reading (summary)

- Prosumer/consumer generation split (Finding 4)
- Device-safe replay injection (Finding 4)
- `autocorr` NaN fix (Finding 4)
- Round-varying IsolationForest seed (`42+round`) so TW-FIF's 10 rounds are
  not all mathematically identical (see `federated_train.py`)
- `getDevice()` getter + `setOracle`/`setEnergyTrade` wiring, needed for the
  contracts to compile and deploy at all (Finding 4)
- `EnergyTrade`'s soft-fail (non-reverting) trust check (Finding 4)
- Window-level ground truth definition for evaluation (Finding 1)
- 3 named devices' on-chain trust temporarily overridden in
  `simulate_trades.py` to actually exercise the trust gate, since the real
  ATSU output correctly produced no low-trust devices from baseline data
  (REQ-14 needs a trust *mix* to demonstrate gating) - clearly logged as a
  demo override, separate from `trust_scores.json`

None of these touch the TW-FIF or ATSU formulas themselves (REQ-01).

## 7. Acknowledged limitations

- Oracle is centralized (single privileged account - production would use
  Chainlink or similar).
- Isolation Forest is retrained periodically here, not continuously.
- Hardhat's local node doesn't reflect mainnet gas volatility or congestion.
- FedAvg over a scalar threshold is a simplification of real FL, which would
  typically share fuller model parameters.
- Dataset is synthetic; real deployment needs validation against actual
  smart-meter data.
- ATSU's `BCS` term (Finding 3) and the window-level ground-truth mismatch
  (Finding 1) are both worth revisiting in any follow-on version of this
  design, not just implementation details to work around.

## 8. Future scope

Real hardware (Raspberry Pi meters + Sepolia testnet) · differential privacy
(Opacus) for provable privacy bounds · Layer-2 scaling (Polygon/Arbitrum) for
city-scale gas costs · decentralized oracle (Chainlink) · Byzantine-robust
aggregation (FedProx, Scaffold, Krum) in place of trust-weighted averaging ·
revisiting the `BCS` term so consistency and trustworthiness aren't
conflated · defining ground truth at the same granularity anomalies are
injected at, or injecting at the window granularity instead.

## 9. Folder structure

```
fedtrust_energy/
├── contracts/         DeviceRegistry.sol, EnergyTrade.sol, TrustOracle.sol, AuditLog.sol
├── scripts/            deploy.js, interact.js, solc_compile_check.js*, write_hardhat_artifacts.js*
├── data/               energy_dataset.csv, device_features.csv, trust_scores.json,
│                       transaction_log.csv, gas_log.json, device_addresses.json, ...
├── models/             global_threshold.pkl, local_models/, client_map.json
├── src/                all 8 pipeline scripts + hardhat_accounts.py
├── outputs/             8 required PNGs
├── test/                test_contracts.js, test_fl_model.py
├── hardhat.config.js · requirements.txt · package.json · README.md

  * solc_compile_check.js / write_hardhat_artifacts.js are this sandbox's
    workaround for a blocked compiler download (see Section 1) - not part
    of the brief's required file list, safe to ignore/delete in a normal
    environment.
```
