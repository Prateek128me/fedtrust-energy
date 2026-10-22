const fs = require("fs");
const path = require("path");
const solc = require("solc");

const contractsDir = path.join(__dirname, "..", "contracts");
const files = fs.readdirSync(contractsDir).filter((f) => f.endsWith(".sol"));

const sources = {};
for (const file of files) {
  sources[file] = { content: fs.readFileSync(path.join(contractsDir, file), "utf8") };
}

const input = {
  language: "Solidity",
  sources,
  settings: {
    outputSelection: { "*": { "*": ["abi", "evm.bytecode.object", "evm.deployedBytecode.object", "evm.gasEstimates"] } },
    optimizer: { enabled: true, runs: 200 },
  },
};

function findImports(importPath) {
  const p = path.join(contractsDir, importPath);
  if (fs.existsSync(p)) return { contents: fs.readFileSync(p, "utf8") };
  return { error: "File not found: " + importPath };
}

const output = JSON.parse(solc.compile(JSON.stringify(input), { import: findImports }));

let hasError = false;
if (output.errors) {
  for (const err of output.errors) {
    const stream = err.severity === "error" ? console.error : console.warn;
    stream(`[${err.severity}] ${err.formattedMessage}`);
    if (err.severity === "error") hasError = true;
  }
}

if (!hasError) {
  console.log("\n=== COMPILATION SUCCESSFUL ===");
  for (const file of Object.keys(output.contracts || {})) {
    for (const name of Object.keys(output.contracts[file])) {
      const c = output.contracts[file][name];
      const bytecodeSize = (c.evm.bytecode.object.length / 2);
      console.log(`  ${name.padEnd(16)} bytecode: ${bytecodeSize.toString().padStart(6)} bytes   `
        + `functions: ${c.abi.filter(x => x.type === 'function').length}   `
        + `events: ${c.abi.filter(x => x.type === 'event').length}`);
    }
  }
  fs.writeFileSync(path.join(__dirname, "..", "compiled_artifacts.json"), JSON.stringify(output.contracts, null, 2));
} else {
  console.error("\n=== COMPILATION FAILED ===");
  process.exit(1);
}
