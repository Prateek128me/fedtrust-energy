// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title DeviceRegistry
/// @notice CONTRACT 1 of 4. Tracks every IoT smart meter's identity, type,
/// and on-chain trust score. This is the single source of truth that
/// EnergyTrade gates every transaction against - the point where an
/// ML-derived reputation score (computed entirely off-chain by ATSU)
/// becomes an enforceable, tamper-resistant on-chain fact.
///
/// Deployment note (fixes a real issue in the brief's example code): calling
/// a public struct-mapping getter like `registry.devices(addr)` from ANOTHER
/// contract returns a raw tuple in Solidity, not a DeviceProfile struct - you
/// cannot assign that directly to a `DeviceProfile memory` variable the way
/// EnergyTrade's example code does. getDevice() below returns the struct
/// properly. Similarly, `oracle` and `energyTrade` are settable once after
/// deployment (by `admin`, the deployer) because DeviceRegistry and
/// TrustOracle each need the other's address at construction time - a
/// circular dependency resolved by deploying DeviceRegistry first with a
/// placeholder, then re-pointing it (see scripts/deploy.js).
contract DeviceRegistry {
    address public oracle;      // only this address may push trust score updates
    address public energyTrade; // only this address may increment tx counts
    address public admin;       // deployer; may re-point oracle/energyTrade once during setup

    enum DeviceType { PROSUMER, CONSUMER }

    struct DeviceProfile {
        address owner;
        DeviceType dtype;
        uint256 trustScore;     // 0-100, initial = 75
        uint256 totalTxCount;
        uint256 anomalyCount;
        bool isSuspended;
        uint256 registeredAt;
    }

    mapping(address => DeviceProfile) public devices;
    address[] public deviceList;

    event DeviceRegistered(address indexed device, DeviceType dtype, uint256 timestamp);
    event TrustScoreUpdated(address indexed device, uint256 oldScore, uint256 newScore);
    event DeviceSuspended(address indexed device, uint256 trustScore);
    event OracleUpdated(address indexed oldOracle, address indexed newOracle);
    event EnergyTradeUpdated(address indexed oldEnergyTrade, address indexed newEnergyTrade);

    modifier onlyOracle() {
        require(msg.sender == oracle, "DeviceRegistry: caller is not the oracle");
        _;
    }

    modifier onlyAdmin() {
        require(msg.sender == admin, "DeviceRegistry: caller is not the admin");
        _;
    }

    modifier onlyEnergyTrade() {
        require(msg.sender == energyTrade, "DeviceRegistry: caller is not EnergyTrade");
        _;
    }

    constructor(address _oracle) {
        oracle = _oracle;   // placeholder at deploy time; re-pointed via setOracle()
        admin = msg.sender;
    }

    /// @notice One-time re-pointing of the oracle to the TrustOracle contract.
    function setOracle(address _oracle) external onlyAdmin {
        emit OracleUpdated(oracle, _oracle);
        oracle = _oracle;
    }

    /// @notice One-time wiring of the EnergyTrade contract address.
    function setEnergyTrade(address _energyTrade) external onlyAdmin {
        emit EnergyTradeUpdated(energyTrade, _energyTrade);
        energyTrade = _energyTrade;
    }

    function registerDevice(DeviceType _type) external {
        require(devices[msg.sender].registeredAt == 0, "Already registered");
        devices[msg.sender] = DeviceProfile(
            msg.sender, _type, 75, 0, 0, false, block.timestamp
        );
        deviceList.push(msg.sender);
        emit DeviceRegistered(msg.sender, _type, block.timestamp);
    }

    /// @notice Called by TrustOracle with the latest ATSU score for a device.
    /// Suspension threshold (25) is enforced here, matching Section 8's
    /// fixed parameter - a device newly below 25 is auto-suspended.
    function updateTrustScore(address device, uint256 newScore) external onlyOracle {
        require(newScore <= 100, "DeviceRegistry: score out of range");
        require(devices[device].registeredAt != 0, "DeviceRegistry: device not registered");
        uint256 old = devices[device].trustScore;
        devices[device].trustScore = newScore;
        devices[device].isSuspended = (newScore < 25);
        emit TrustScoreUpdated(device, old, newScore);
        if (devices[device].isSuspended) {
            emit DeviceSuspended(device, newScore);
        }
    }

    function recordAnomaly(address device) external onlyOracle {
        devices[device].anomalyCount += 1;
    }

    /// @notice Called by EnergyTrade after a settled trade, so ATSU's TSR
    /// term (successful_tx / total_tx) has real on-chain counts to draw from.
    function incrementTxCount(address device) external onlyEnergyTrade {
        devices[device].totalTxCount += 1;
    }

    function getDevice(address device) external view returns (DeviceProfile memory) {
        return devices[device];
    }

    function getDeviceCount() external view returns (uint256) {
        return deviceList.length;
    }
}
