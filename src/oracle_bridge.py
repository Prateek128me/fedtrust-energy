"""
src/oracle_bridge.py
------------------------------------------------------------------------------
Oracle bridge (Pipeline Step 7): reads data/trust_scores.json (ATSU's output)
and pushes each device's score on-chain via TrustOracle.sol, using Web3.py.

RESEARCH SIGNIFICANCE: this is the literal off-chain -> on-chain bridge the
brief's Section 1 workflow describes ("Oracle Bridge (Web3.py) --> calls
TrustOracle.sol"). It is also the single centralization point Section 8's
acknowledged limitations flag ("Oracle is centralized - single privileged
account"): whoever holds this script's private key can submit any trust
score for any device. Here that's Hardhat's well-known account #0 (Section
8: "Oracle account: Hardhat accounts[0] as privileged oracle") - fine for a
local prototype, unacceptable in production without a decentralized
replacement (Chainlink, per the brief's Future Scope).

Submits scores ONE AT A TIME (not batched) so each call is a real, separately
measurable updateTrustScore() transaction - REQ-09/Section 6 needs an average
gas cost specifically for that transaction type, which a single batched call
would not give a clean per-device figure for.

Requires a running local node with contracts already deployed:
  npx hardhat node                                    (separate terminal)
  npx hardhat run scripts/deploy.js --network localhost
  python src/oracle_bridge.py
------------------------------------------------------------------------------
"""
import json
import sys
from pathlib import Path

from web3 import Web3

sys.path.append(str(Path(__file__).resolve().parent))
from hardhat_accounts import ORACLE_PRIVATE_KEY  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TRUST_SCORES_PATH = ROOT / "data" / "trust_scores.json"
DEVICE_ADDR_PATH = ROOT / "data" / "device_addresses.json"
DEPLOYED_PATH = ROOT / "deployed_addresses.json"
GAS_LOG_PATH = ROOT / "data" / "gas_log.json"

RPC_URL = "http://127.0.0.1:8545"

TRUST_ORACLE_ABI = [
    {"inputs": [{"name": "device", "type": "address"}, {"name": "newScore", "type": "uint256"}],
     "name": "submitTrustScore", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
]


def load_gas_log():
    if GAS_LOG_PATH.exists():
        with open(GAS_LOG_PATH) as f:
            return json.load(f)
    return {"registerDevice": [], "postOffer": [], "acceptOffer": [], "updateTrustScore": []}


def save_gas_log(log):
    with open(GAS_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)


def main():
    print(f"[oracle_bridge] Connecting to {RPC_URL} ...")
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        raise ConnectionError(
            f"Could not reach {RPC_URL}. Start a node first (npx hardhat node), "
            f"then deploy (npx hardhat run scripts/deploy.js --network localhost)."
        )

    with open(DEPLOYED_PATH) as f:
        deployed = json.load(f)
    with open(DEVICE_ADDR_PATH) as f:
        device_addresses = json.load(f)
    with open(TRUST_SCORES_PATH) as f:
        trust_scores = json.load(f)

    oracle_account = w3.eth.account.from_key(ORACLE_PRIVATE_KEY)
    trust_oracle = w3.eth.contract(address=Web3.to_checksum_address(deployed["TrustOracle"]),
                                    abi=TRUST_ORACLE_ABI)
    nonce = w3.eth.get_transaction_count(oracle_account.address)

    print(f"[oracle_bridge] Submitting {len(trust_scores)} device trust scores "
          f"as oracle {oracle_account.address} -> TrustOracle @ {deployed['TrustOracle']}")

    gas_log = load_gas_log()
    for dev_id, info in sorted(trust_scores.items()):
        if dev_id not in device_addresses:
            print(f"  SKIP {dev_id}: not registered on-chain")
            continue
        addr = Web3.to_checksum_address(device_addresses[dev_id])
        score = int(round(info["trust_score"]))

        tx = trust_oracle.functions.submitTrustScore(addr, score).build_transaction({
            "from": oracle_account.address, "nonce": nonce, "gas": 200_000,
        })
        signed = w3.eth.account.sign_transaction(tx, ORACLE_PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        nonce += 1

        gas_log["updateTrustScore"].append(receipt["gasUsed"])
        status = "OK" if receipt["status"] == 1 else "FAILED"
        print(f"  {dev_id} -> {score:3d}  gas={receipt['gasUsed']:>6}  [{status}]")

    save_gas_log(gas_log)
    n = len(gas_log["updateTrustScore"])
    avg_gas = sum(gas_log["updateTrustScore"]) / n if n else 0
    print(f"\n[oracle_bridge] DONE. {n} updateTrustScore() txs this run "
          f"(avg gas so far: {avg_gas:.0f}) -> {GAS_LOG_PATH}")


if __name__ == "__main__":
    main()
