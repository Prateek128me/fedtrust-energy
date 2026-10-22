// scripts/interact.js
// Optional helper for poking at the already-deployed contracts, e.g. after
// running deploy.js + oracle_bridge.py. Reads deployed_addresses.json and
// data/device_addresses.json (both written earlier in the pipeline).
//
// NOTE: this Hardhat version's `run` task does not accept trailing CLI
// arguments (verified: both `run script.js -- args` and `run script.js
// args` are rejected by its argument parser) - so filtering to one device
// uses an environment variable instead, which bypasses Hardhat's CLI parser
// entirely:
//
//   npx hardhat run --no-compile --network localhost scripts/interact.js
//   DEVICE=DEV_005 npx hardhat run --no-compile --network localhost scripts/interact.js
const hre = require("hardhat");
const fs = require("fs");
const path = require("path");

function loadJSON(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

async function main() {
  const root = path.join(__dirname, "..");
  const deployed = loadJSON(path.join(root, "deployed_addresses.json"));
  const deviceAddresses = loadJSON(path.join(root, "data", "device_addresses.json"));

  const registry = await hre.ethers.getContractAt("DeviceRegistry", deployed.DeviceRegistry);
  const energyTrade = await hre.ethers.getContractAt("EnergyTrade", deployed.EnergyTrade);
  const auditLog = await hre.ethers.getContractAt("AuditLog", deployed.AuditLog);

  const filterDevice = process.env.DEVICE;

  if (filterDevice) {
    if (!deviceAddresses[filterDevice]) {
      console.error(`Unknown device: ${filterDevice}. Known: ${Object.keys(deviceAddresses).join(", ")}`);
      process.exit(1);
    }
    const p = await registry.getDevice(deviceAddresses[filterDevice]);
    console.log(`${filterDevice} (${deviceAddresses[filterDevice]})`);
    console.log({
      trustScore: p.trustScore.toString(), isSuspended: p.isSuspended,
      totalTxCount: p.totalTxCount.toString(), anomalyCount: p.anomalyCount.toString(),
      type: p.dtype === 0n ? "PROSUMER" : "CONSUMER",
    });
    return;
  }

  console.log("=== Contract addresses ===");
  console.log(deployed);
  console.log("\n=== All 20 devices ===");
  for (const [devId, addr] of Object.entries(deviceAddresses)) {
    const p = await registry.getDevice(addr);
    console.log(`${devId}  trust=${p.trustScore}  suspended=${p.isSuspended}  `
      + `txCount=${p.totalTxCount}  type=${p.dtype === 0n ? "PROSUMER" : "CONSUMER"}`);
  }
  const offerCount = await energyTrade.offerCount();
  const logCount = await auditLog.getLogCount();
  console.log(`\noffers posted: ${offerCount}   audit log entries: ${logCount}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
