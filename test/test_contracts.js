const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("FedTrust-Energy contracts", function () {
  let registry, oracle, auditLog, energyTrade;
  let admin, deviceA, deviceB, stranger;

  beforeEach(async function () {
    [admin, deviceA, deviceB, stranger] = await ethers.getSigners();

    const DeviceRegistry = await ethers.getContractFactory("DeviceRegistry");
    registry = await DeviceRegistry.deploy(admin.address);
    await registry.waitForDeployment();

    const AuditLog = await ethers.getContractFactory("AuditLog");
    auditLog = await AuditLog.deploy();
    await auditLog.waitForDeployment();

    const TrustOracle = await ethers.getContractFactory("TrustOracle");
    oracle = await TrustOracle.deploy(await registry.getAddress(), await auditLog.getAddress());
    await oracle.waitForDeployment();
    await (await registry.setOracle(await oracle.getAddress())).wait();

    const EnergyTrade = await ethers.getContractFactory("EnergyTrade");
    energyTrade = await EnergyTrade.deploy(await registry.getAddress(), await auditLog.getAddress());
    await energyTrade.waitForDeployment();
    await (await registry.setEnergyTrade(await energyTrade.getAddress())).wait();
  });

  it("registers a device with initial trust score 75", async function () {
    await registry.connect(deviceA).registerDevice(0); // PROSUMER
    const profile = await registry.getDevice(deviceA.address);
    expect(profile.trustScore).to.equal(75);
    expect(profile.isSuspended).to.equal(false);
  });

  it("rejects a duplicate registration", async function () {
    await registry.connect(deviceA).registerDevice(0);
    await expect(registry.connect(deviceA).registerDevice(1)).to.be.revertedWith("Already registered");
  });

  it("only the TrustOracle contract can update trust scores", async function () {
    await registry.connect(deviceA).registerDevice(0);
    await expect(registry.connect(stranger).updateTrustScore(deviceA.address, 40))
      .to.be.revertedWith("DeviceRegistry: caller is not the oracle");
  });

  it("suspends a device when the oracle pushes a score below 25", async function () {
    await registry.connect(deviceA).registerDevice(0);
    await (await oracle.connect(admin).submitTrustScore(deviceA.address, 10)).wait();
    const profile = await registry.getDevice(deviceA.address);
    expect(profile.trustScore).to.equal(10);
    expect(profile.isSuspended).to.equal(true);
  });

  it("blocks postOffer for a device below MIN_TRUST (50) without reverting, and logs TradeDenied", async function () {
    await registry.connect(deviceA).registerDevice(0);
    await (await oracle.connect(admin).submitTrustScore(deviceA.address, 40)).wait();

    const tx = await energyTrade.connect(deviceA).postOffer(10, 5);
    const receipt = await tx.wait();
    const denied = receipt.logs.some((log) => {
      try { return energyTrade.interface.parseLog(log).name === "TradeDenied"; }
      catch { return false; }
    });
    expect(denied).to.equal(true);
    expect(await energyTrade.offerCount()).to.equal(0);
  });

  it("allows postOffer + acceptOffer between two trusted devices and settles payment", async function () {
    await registry.connect(deviceA).registerDevice(0); // seller, prosumer
    await registry.connect(deviceB).registerDevice(1); // buyer, consumer

    await energyTrade.connect(deviceA).postOffer(10, ethers.parseEther("0.001"));
    const total = 10n * ethers.parseEther("0.001");

    const sellerBalBefore = await ethers.provider.getBalance(deviceA.address);
    await (await energyTrade.connect(deviceB).acceptOffer(0, { value: total })).wait();
    const sellerBalAfter = await ethers.provider.getBalance(deviceA.address);

    expect(sellerBalAfter - sellerBalBefore).to.equal(total);
    const offer = await energyTrade.offers(0);
    expect(offer.active).to.equal(false);

    const sellerProfile = await registry.getDevice(deviceA.address);
    const buyerProfile = await registry.getDevice(deviceB.address);
    expect(sellerProfile.totalTxCount).to.equal(1);
    expect(buyerProfile.totalTxCount).to.equal(1);
  });

  it("logs settled and denied trades to AuditLog", async function () {
    await registry.connect(deviceA).registerDevice(0);
    await (await oracle.connect(admin).submitTrustScore(deviceA.address, 40)).wait(); // logs 1: TRUST_UPDATE
    await (await energyTrade.connect(deviceA).postOffer(10, 5)).wait(); // denied -> logs 1 more: TRADE_DENIED
    expect(await auditLog.getLogCount()).to.equal(2);
  });
});
