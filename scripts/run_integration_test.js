// Runs against Hardhat's built-in in-process EVM (no live node needed).
// Deploys using bytecode/ABI from the standalone solc compile (compiled_artifacts.json)
// instead of Hardhat's own artifact system, because Hardhat's `compile` task needs to
// download solc from binaries.soliditylang.org, which is not reachable in this sandbox.
// This still exercises real EVM execution end-to-end: real deployments, real gas, real
// require()/revert semantics, real event logs - just via a different route to bytecode.
const hre = require("hardhat");
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const artifacts = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "compiled_artifacts.json"), "utf8"));

function getContract(fileName, contractName) {
  const c = artifacts[fileName][contractName];
  return { abi: c.abi, bytecode: "0x" + c.evm.bytecode.object, gasEstimates: c.evm.gasEstimates };
}

async function deploy(hre, fileName, contractName, signer, args = []) {
  const { abi, bytecode } = getContract(fileName, contractName);
  const factory = new hre.ethers.ContractFactory(abi, bytecode, signer);
  const contract = await factory.deploy(...args);
  await contract.waitForDeployment();
  return contract;
}

async function main() {
  const [admin, deviceA, deviceB, stranger] = await hre.ethers.getSigners();
  let passed = 0, failed = 0;
  const check = (desc, cond) => {
    if (cond) { console.log(`  PASS: ${desc}`); passed++; }
    else { console.log(`  FAIL: ${desc}`); failed++; }
  };

  console.log("Deploying all 4 contracts to Hardhat's in-process EVM ...");
  const registry = await deploy(hre, "DeviceRegistry.sol", "DeviceRegistry", admin, [admin.address]);
  const auditLog = await deploy(hre, "AuditLog.sol", "AuditLog", admin, []);
  const oracle = await deploy(hre, "TrustOracle.sol", "TrustOracle", admin,
    [await registry.getAddress(), await auditLog.getAddress()]);
  await (await registry.setOracle(await oracle.getAddress())).wait();
  const energyTrade = await deploy(hre, "EnergyTrade.sol", "EnergyTrade", admin,
    [await registry.getAddress(), await auditLog.getAddress()]);
  await (await registry.setEnergyTrade(await energyTrade.getAddress())).wait();
  console.log("  DeviceRegistry:", await registry.getAddress());
  console.log("  AuditLog:      ", await auditLog.getAddress());
  console.log("  TrustOracle:   ", await oracle.getAddress());
  console.log("  EnergyTrade:   ", await energyTrade.getAddress());

  console.log("\nTest 1: register a device with initial trust score 75");
  await (await registry.connect(deviceA).registerDevice(0)).wait(); // PROSUMER
  let profile = await registry.getDevice(deviceA.address);
  check("trustScore == 75", profile.trustScore.toString() === "75");
  check("isSuspended == false", profile.isSuspended === false);

  console.log("\nTest 2: only the TrustOracle contract can update trust scores");
  let reverted = false;
  try { await registry.connect(stranger).updateTrustScore(deviceA.address, 40); }
  catch (e) { reverted = /caller is not the oracle/.test(e.message); }
  check("direct updateTrustScore() from a stranger reverts", reverted);

  console.log("\nTest 3: oracle pushes a score below 25 -> device auto-suspended");
  await (await oracle.connect(admin).submitTrustScore(deviceA.address, 10)).wait();
  profile = await registry.getDevice(deviceA.address);
  check("trustScore == 10", profile.trustScore.toString() === "10");
  check("isSuspended == true", profile.isSuspended === true);

  console.log("\nTest 4: postOffer denied (no revert) for a device below MIN_TRUST, TradeDenied emitted");
  await (await oracle.connect(admin).submitTrustScore(deviceA.address, 40)).wait(); // below 50, not suspended
  const txDenied = await energyTrade.connect(deviceA).postOffer(10, 5);
  const receiptDenied = await txDenied.wait();
  const deniedEvent = receiptDenied.logs.some((log) => {
    try { return energyTrade.interface.parseLog(log).name === "TradeDenied"; } catch { return false; }
  });
  check("TradeDenied event emitted (transaction did not revert)", deniedEvent);
  check("offerCount stayed 0 (offer was not created)", (await energyTrade.offerCount()).toString() === "0");

  console.log("\nTest 5: two trusted devices trade successfully and payment settles");
  await (await registry.connect(deviceB).registerDevice(1)).wait(); // CONSUMER
  await (await oracle.connect(admin).submitTrustScore(deviceA.address, 80)).wait(); // restore seller trust
  const price = hre.ethers.parseEther("0.001");
  await (await energyTrade.connect(deviceA).postOffer(10, price)).wait();
  const total = 10n * price;
  const sellerBalBefore = await hre.ethers.provider.getBalance(deviceA.address);
  await (await energyTrade.connect(deviceB).acceptOffer(0, { value: total })).wait();
  const sellerBalAfter = await hre.ethers.provider.getBalance(deviceA.address);
  check("seller received exactly the trade total", (sellerBalAfter - sellerBalBefore).toString() === total.toString());
  const offer = await energyTrade.offers(0);
  check("offer marked inactive after settlement", offer.active === false);

  console.log("\nTest 6: settled trade incremented both parties' totalTxCount via DeviceRegistry");
  const profA = await registry.getDevice(deviceA.address);
  const profB = await registry.getDevice(deviceB.address);
  check("seller totalTxCount == 1", profA.totalTxCount.toString() === "1");
  check("buyer totalTxCount == 1", profB.totalTxCount.toString() === "1");

  console.log("\nTest 7: AuditLog recorded both the denial and the settlement");
  const logCount = await auditLog.getLogCount();
  check("AuditLog has >= 2 entries (1 denial + 1 settlement)", Number(logCount) >= 2);

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
}

main().catch((e) => { console.error(e); process.exit(1); });
