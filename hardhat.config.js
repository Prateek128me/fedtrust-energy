require("@nomicfoundation/hardhat-toolbox");

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: { enabled: true, runs: 200 },
    },
  },
  networks: {
    hardhat: {
      chainId: 31337,
      accounts: {
        count: 30, // account #0 = oracle/deployer/admin, #1-20 = the 20 devices, rest spare
      },
    },
    localhost: {
      url: "http://127.0.0.1:8545",
      // REQ-15: local network only, no external testnet configuration
    },
  },
};
