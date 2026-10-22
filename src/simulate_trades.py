"""
src/simulate_trades.py
------------------------------------------------------------------------------
Trade simulator (Pipeline Step 8): executes 1,000 blockchain transactions
(500 postOffer + 500 acceptOffer attempts) across the 20 registered devices,
logging outcome + gas for every single one to data/transaction_log.csv.

REQ-14 asks for "a mix of trusted (score>50) and low-trust (score<50)
devices to demonstrate gating". The real ATSU output (data/trust_scores.json)
correctly gave every one of the 20 devices a healthy trust score in the 80s
(see trust_engine.py's findings on why) - which is the CORRECT outcome given
they only exhibit the dataset's baseline 5% anomaly rate, but it means there
is no naturally low-trust device to demonstrate the gate with. So this
script first pushes 3 specific, named devices' ON-CHAIN trust below the
relevant thresholds via the oracle account (clearly logged as a demo
override - NOT a change to trust_scores.json or a re-run of ATSU), then runs
the 1,000-tx mix. This exercises real code paths (a real revert-free denial,
a real suspension check) with real, honestly-measured gas numbers; it does
not fabricate the denial outcomes themselves, which are genuine results of
the contract's real trust check against these seeded on-chain scores.

Requires a running local node with contracts deployed and devices
registered (npx hardhat node && npx hardhat run scripts/deploy.js
--network localhost), same as oracle_bridge.py.
------------------------------------------------------------------------------
"""
import csv
import json
import random
import sys
import time
import warnings
from pathlib import Path

from web3 import Web3

warnings.filterwarnings("ignore", message="The log with transaction hash.*MismatchedABI")

sys.path.append(str(Path(__file__).resolve().parent))
from hardhat_accounts import ORACLE_PRIVATE_KEY, private_key_for  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEVICE_ADDR_PATH = ROOT / "data" / "device_addresses.json"
DEPLOYED_PATH = ROOT / "deployed_addresses.json"
GAS_LOG_PATH = ROOT / "data" / "gas_log.json"
TX_LOG_PATH = ROOT / "data" / "transaction_log.csv"

RPC_URL = "http://127.0.0.1:8545"
RANDOM_SEED = 42
N_ROUNDS = 500          # -> 500 postOffer + 500 acceptOffer = 1000 total (REQ-14)

# Demo overrides: named devices pushed below threshold ON-CHAIN ONLY, purely
# to exercise the trust gate in this simulation (see module docstring).
DEMO_LOW_TRUST = {"DEV_005": 35, "DEV_012": 15, "DEV_018": 45}

ENERGY_TRADE_ABI = [
    {"inputs": [{"name": "_qty", "type": "uint256"}, {"name": "_price", "type": "uint256"}],
     "name": "postOffer", "outputs": [{"type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "offerId", "type": "uint256"}],
     "name": "acceptOffer", "outputs": [{"type": "bool"}], "stateMutability": "payable", "type": "function"},
    {"inputs": [], "name": "offerCount", "outputs": [{"type": "uint256"}],
     "stateMutability": "view", "type": "function"},
    {"anonymous": False, "inputs": [
        {"indexed": True, "name": "buyer", "type": "address"}, {"indexed": True, "name": "seller", "type": "address"},
        {"indexed": False, "name": "qty", "type": "uint256"}, {"indexed": False, "name": "total", "type": "uint256"},
        {"indexed": False, "name": "ts", "type": "uint256"}], "name": "TradeSettled", "type": "event"},
    {"anonymous": False, "inputs": [
        {"indexed": True, "name": "initiator", "type": "address"},
        {"indexed": False, "name": "trustScore", "type": "uint256"},
        {"indexed": False, "name": "reason", "type": "string"}], "name": "TradeDenied", "type": "event"},
]
DEVICE_REGISTRY_ABI = [
    {"inputs": [{"name": "device", "type": "address"}], "name": "getDevice",
     "outputs": [{"components": [
         {"name": "owner", "type": "address"}, {"name": "dtype", "type": "uint8"},
         {"name": "trustScore", "type": "uint256"}, {"name": "totalTxCount", "type": "uint256"},
         {"name": "anomalyCount", "type": "uint256"}, {"name": "isSuspended", "type": "bool"},
         {"name": "registeredAt", "type": "uint256"}], "type": "tuple"}],
     "stateMutability": "view", "type": "function"},
]
TRUST_ORACLE_ABI = [
    {"inputs": [{"name": "device", "type": "address"}, {"name": "newScore", "type": "uint256"}],
     "name": "submitTrustScore", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
]


def load_gas_log():
    if GAS_LOG_PATH.exists():
        with open(GAS_LOG_PATH) as f:
            return json.load(f)
    return {"registerDevice": [], "postOffer": [], "acceptOffer": [], "updateTrustScore": []}


def send(w3, fn, from_addr, private_key, nonce, value=0, gas=300_000):
    """Signs and sends a transaction."""
    tx = fn.build_transaction({"from": from_addr, "nonce": nonce, "gas": gas, "value": value})
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(tx_hash)


def main():
    rng = random.Random(RANDOM_SEED)
    print(f"[simulate_trades] Connecting to {RPC_URL} ...")
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        raise ConnectionError(f"Could not reach {RPC_URL}. Start/deploy the chain first.")

    with open(DEPLOYED_PATH) as f:
        deployed = json.load(f)
    with open(DEVICE_ADDR_PATH) as f:
        device_addresses = {k: Web3.to_checksum_address(v) for k, v in json.load(f).items()}

    oracle_addr = w3.eth.account.from_key(ORACLE_PRIVATE_KEY).address
    energy_trade = w3.eth.contract(address=Web3.to_checksum_address(deployed["EnergyTrade"]),
                                    abi=ENERGY_TRADE_ABI)
    registry = w3.eth.contract(address=Web3.to_checksum_address(deployed["DeviceRegistry"]),
                                abi=DEVICE_REGISTRY_ABI)
    trust_oracle = w3.eth.contract(address=Web3.to_checksum_address(deployed["TrustOracle"]),
                                    abi=TRUST_ORACLE_ABI)
    oracle_nonce = w3.eth.get_transaction_count(oracle_addr)

    print(f"[simulate_trades] Applying {len(DEMO_LOW_TRUST)} demo low-trust overrides "
          f"(on-chain only, exercises the gate - see module docstring):")
    for dev_id, score in DEMO_LOW_TRUST.items():
        receipt = send(w3, trust_oracle.functions.submitTrustScore(device_addresses[dev_id], score),
                        oracle_addr, ORACLE_PRIVATE_KEY, oracle_nonce)
        oracle_nonce += 1
        tag = "SUSPENDED" if score < 25 else "below MIN_TRUST" if score < 50 else "ok"
        print(f"  {dev_id} -> trust={score}  ({tag})")

    device_ids = sorted(device_addresses.keys())
    device_nonces = {dev: w3.eth.get_transaction_count(addr) for dev, addr in device_addresses.items()}

    def current_trust(dev_id):
        p = registry.functions.getDevice(device_addresses[dev_id]).call()
        return int(p[2]), bool(p[5])  # trustScore, isSuspended

    gas_log = load_gas_log()
    rows = []
    active_offers = []  # (offer_id, seller_dev_id, qty, price_wei)

    print(f"[simulate_trades] Running {N_ROUNDS} postOffer attempts ...")
    throughput_start = time.monotonic()
    for i in range(N_ROUNDS):
        # 50/50 weighting toward the small low-trust pool so denials are
        # well represented in the sample, not just their true 3/20 share.
        seller = rng.choice(list(DEMO_LOW_TRUST.keys())) if rng.random() < 0.5 else rng.choice(device_ids)
        qty = rng.randint(1, 50)
        price_wei = rng.randint(1, 20) * 10**14  # ~0.0001-0.002 ETH/kWh
        trust_before, suspended_before = current_trust(seller)

        receipt = send(w3, energy_trade.functions.postOffer(qty, price_wei),
                        device_addresses[seller], private_key_for(device_addresses[seller]),
                        device_nonces[seller])
        device_nonces[seller] += 1
        gas_log["postOffer"].append(receipt["gasUsed"])

        denied_events = energy_trade.events.TradeDenied().process_receipt(receipt)
        settled = len(denied_events) == 0
        offer_id = None
        if settled:
            offer_id = energy_trade.functions.offerCount().call() - 1
            active_offers.append((offer_id, seller, qty, price_wei))

        rows.append({"tx_index": i, "tx_type": "postOffer", "device_id": seller,
                      "trust_score": trust_before, "suspended": suspended_before,
                      "outcome": "settled" if settled else "denied",
                      "gas_used": receipt["gasUsed"], "offer_id": offer_id if offer_id is not None else ""})

    print(f"[simulate_trades] {len(active_offers)}/{N_ROUNDS} offers created. "
          f"Running {N_ROUNDS} acceptOffer attempts ...")
    for i in range(N_ROUNDS):
        buyer = rng.choice(list(DEMO_LOW_TRUST.keys())) if rng.random() < 0.5 else rng.choice(device_ids)
        if active_offers:
            offer_id, seller, qty, price_wei = active_offers[i % len(active_offers)]
        else:
            offer_id, seller, qty, price_wei = (0, device_ids[0], 1, 10**14)
        total_value = qty * price_wei
        trust_before, suspended_before = current_trust(buyer)

        try:
            receipt = send(w3, energy_trade.functions.acceptOffer(offer_id),
                            device_addresses[buyer], private_key_for(device_addresses[buyer]),
                            device_nonces[buyer], value=total_value)
            device_nonces[buyer] += 1
            gas_used = receipt["gasUsed"]
            if receipt["status"] == 0:
                outcome = "reverted"  # e.g. offer already settled by an earlier round in this same loop
            else:
                settled_events = energy_trade.events.TradeSettled().process_receipt(receipt)
                outcome = "settled" if len(settled_events) > 0 else "denied"
        except Exception as exc:  # noqa: BLE001 - a hard revert can also raise client-side
            device_nonces[buyer] += 1
            gas_used = 0
            outcome = "reverted"
            if i < 3:
                print(f"  (reverted attempt on offer {offer_id}: {str(exc)[:80]})")

        gas_log["acceptOffer"].append(gas_used)
        rows.append({"tx_index": N_ROUNDS + i, "tx_type": "acceptOffer", "device_id": buyer,
                      "trust_score": trust_before, "suspended": suspended_before,
                      "outcome": outcome, "gas_used": gas_used, "offer_id": offer_id})
    throughput_elapsed_s = time.monotonic() - throughput_start

    with open(TX_LOG_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    with open(GAS_LOG_PATH, "w") as f:
        json.dump(gas_log, f, indent=2)
    with open(ROOT / "data" / "throughput.json", "w") as f:
        json.dump({"total_transactions": len(rows), "elapsed_seconds": throughput_elapsed_s,
                    "tx_per_minute": len(rows) / (throughput_elapsed_s / 60)}, f, indent=2)

    n_settled = sum(1 for r in rows if r["outcome"] == "settled")
    n_denied = sum(1 for r in rows if r["outcome"] == "denied")
    n_reverted = sum(1 for r in rows if r["outcome"] == "reverted")
    print(f"\n[simulate_trades] DONE. {len(rows)} transactions -> {TX_LOG_PATH}")
    print(f"  settled: {n_settled} ({n_settled/len(rows):.1%})   "
          f"denied (trust gate): {n_denied} ({n_denied/len(rows):.1%})   "
          f"reverted (other): {n_reverted} ({n_reverted/len(rows):.1%})")
    if gas_log["postOffer"]:
        print(f"  avg gas postOffer:   {sum(gas_log['postOffer'])/len(gas_log['postOffer']):.0f}")
    if gas_log["acceptOffer"]:
        print(f"  avg gas acceptOffer: {sum(gas_log['acceptOffer'])/len(gas_log['acceptOffer']):.0f}")
    print(f"  throughput: {len(rows)} tx in {throughput_elapsed_s:.1f}s "
          f"= {len(rows)/(throughput_elapsed_s/60):.0f} tx/min")


if __name__ == "__main__":
    main()
