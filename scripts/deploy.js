// scripts/deploy.js
// Deploys all 4 contracts in the order their constructor dependencies require:
//   1. DeviceRegistry (oracle = deployer as a placeholder - see setOracle below)
//   2. TrustOracle    (needs DeviceRegistry's address)
//   3. registry.setOracle(TrustOracle)   -- re-points the real oracle
//   4. AuditLog       (no dependencies)
//   5. EnergyTrade    (needs DeviceRegistry + AuditLog addresses)
//   6. registry.setEnergyTrade(EnergyTrade)
// This ordering exists because DeviceRegistry and TrustOracle each need the
// other's address, which Solidity constructors can't resolve directly - see
// the deployment note in contracts/DeviceRegistry.sol.
const hre = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log("Deploying with account:", deployer.address);
  console.log("Account balance:", (await hre.ethers.provider.getBalance(deployer.address)).toString());

  const DeviceRegistry = await hre.ethers.getContractFactory("DeviceRegistry");
  const registry = await DeviceRegistry.deploy(deployer.address); // placeholder oracle
  await registry.waitForDeployment();
  console.log("DeviceRegistry deployed:", await registry.getAddress());

  const AuditLog = await hre.ethers.getContractFactory("AuditLog");
  const auditLog = await AuditLog.deploy();
  await auditLog.waitForDeployment();
  console.log("AuditLog deployed:      ", await auditLog.getAddress());

  const TrustOracle = await hre.ethers.getContractFactory("TrustOracle");
  const oracle = await TrustOracle.deploy(await registry.getAddress(), await auditLog.getAddress());
  await oracle.waitForDeployment();
  console.log("TrustOracle deployed:   ", await oracle.getAddress());

  let tx = await registry.setOracle(await oracle.getAddress());
  await tx.wait();
  console.log("DeviceRegistry.oracle -> TrustOracle");

  const EnergyTrade = await hre.ethers.getContractFactory("EnergyTrade");
  const energyTrade = await EnergyTrade.deploy(await registry.getAddress(), await auditLog.getAddress());
  await energyTrade.waitForDeployment();
  console.log("EnergyTrade deployed:   ", await energyTrade.getAddress());

  tx = await registry.setEnergyTrade(await energyTrade.getAddress());
  await tx.wait();
  console.log("DeviceRegistry.energyTrade -> EnergyTrade");

  // Register all 20 devices on-chain (needed before Step 7's oracle bridge can
  // call updateTrustScore, and before Step 8's trades can happen - neither
  // the brief's pipeline list nor deploy.js's one-line description mentions
  // this explicitly, but it's a precondition both later steps require).
  // account #0 is the oracle/admin signer; devices use accounts #1-20.
  const signers = await hre.ethers.getSigners();
  const deviceAddresses = {};
  const registerGas = [];
  console.log("\nRegistering 20 devices (DEV_000-014 = PROSUMER, DEV_015-019 = CONSUMER) ...");
  for (let i = 0; i < 20; i++) {
    const devId = `DEV_${String(i).padStart(3, "0")}`;
    const signer = signers[i + 1];
    const dtype = i < 15 ? 0 : 1; // 0 = PROSUMER, 1 = CONSUMER
    tx = await registry.connect(signer).registerDevice(dtype);
    const receipt = await tx.wait();
    registerGas.push(Number(receipt.gasUsed));
    deviceAddresses[devId] = signer.address;
  }
  fs.writeFileSync(path.join(__dirname, "..", "data", "device_addresses.json"),
    JSON.stringify(deviceAddresses, null, 2));
  console.log(`Registered 20 devices -> data/device_addresses.json`);

  const gasLogPath = path.join(__dirname, "..", "data", "gas_log.json");
  const gasLog = fs.existsSync(gasLogPath)
    ? JSON.parse(fs.readFileSync(gasLogPath, "utf8"))
    : { registerDevice: [], postOffer: [], acceptOffer: [], updateTrustScore: [] };
  gasLog.registerDevice = registerGas;
  fs.writeFileSync(gasLogPath, JSON.stringify(gasLog, null, 2));
  console.log(`Logged ${registerGas.length} registerDevice gas measurements -> data/gas_log.json`);

  const addresses = {
    DeviceRegistry: await registry.getAddress(),
    AuditLog: await auditLog.getAddress(),
    TrustOracle: await oracle.getAddress(),
    EnergyTrade: await energyTrade.getAddress(),
    oracleSigner: deployer.address,
    network: hre.network.name,
    deployedAt: new Date().toISOString(),
  };
  const outPath = path.join(__dirname, "..", "deployed_addresses.json");
  fs.writeFileSync(outPath, JSON.stringify(addresses, null, 2));
  console.log(`\nAll 4 contracts deployed. Addresses saved -> ${outPath}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
