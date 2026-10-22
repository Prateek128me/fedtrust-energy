// This script exists ONLY because this sandbox's network egress doesn't
// allow binaries.soliditylang.org, which Hardhat's own `compile` task needs.
// It takes the solc-compiled output (already proven correct by
// scripts/solc_compile_check.js) and writes it into Hardhat's own artifact
// format, so `npx hardhat test --no-compile` and any script using the
// standard `ethers.getContractFactory("ContractName")` API work normally.
// In a normal (unrestricted) environment, this script is unnecessary -
// `npx hardhat compile` does this automatically.
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const compiled = JSON.parse(fs.readFileSync(path.join(root, "compiled_artifacts.json"), "utf8"));
const artifactsDir = path.join(root, "artifacts", "contracts");

for (const fileName of Object.keys(compiled)) {
  for (const contractName of Object.keys(compiled[fileName])) {
    const c = compiled[fileName][contractName];
    const artifact = {
      _format: "hh-sol-artifact-1",
      contractName,
      sourceName: `contracts/${fileName}`,
      abi: c.abi,
      bytecode: "0x" + c.evm.bytecode.object,
      deployedBytecode: "0x" + c.evm.deployedBytecode.object,
      linkReferences: {},
      deployedLinkReferences: {},
    };
    const dir = path.join(artifactsDir, fileName);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, `${contractName}.json`), JSON.stringify(artifact, null, 2));
    console.log(`Wrote artifacts/contracts/${fileName}/${contractName}.json`);
  }
}
