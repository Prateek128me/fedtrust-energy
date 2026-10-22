// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./DeviceRegistry.sol";
import "./AuditLog.sol";

/// @title TrustOracle
/// @notice CONTRACT 3 of 4. The single bridge between the off-chain ML
/// pipeline (TW-FIF + ATSU, which cannot run on the EVM) and on-chain
/// enforcement in DeviceRegistry/EnergyTrade.
///
/// RESEARCH SIGNIFICANCE: centralizing that bridge in one contract, owned by
/// one account, is precisely what Section 8's "Oracle account = Hardhat
/// accounts[0]" and the acknowledged "oracle is centralized" limitation are
/// about. A production system would decentralize this (Chainlink or a
/// committee of oracles, per the brief's Future Scope) - this prototype
/// makes the centralization explicit and auditable rather than hidden.
contract TrustOracle {
    address public owner;
    DeviceRegistry public registry;
    AuditLog public auditLog;

    event TrustScoreSubmitted(address indexed device, uint256 newScore, uint256 timestamp);

    modifier onlyOwner() {
        require(msg.sender == owner, "TrustOracle: caller is not the owner");
        _;
    }

    constructor(address _registry, address _auditLog) {
        owner = msg.sender;
        registry = DeviceRegistry(_registry);
        auditLog = AuditLog(_auditLog);
    }

    /// @notice Pushes one device's ATSU-computed trust score on-chain.
    /// Called by oracle_bridge.py (Web3.py), signed by accounts[0] (owner).
    function submitTrustScore(address device, uint256 newScore) external onlyOwner {
        require(newScore <= 100, "TrustOracle: score out of range");
        registry.updateTrustScore(device, newScore);
        emit TrustScoreSubmitted(device, newScore, block.timestamp);
        auditLog.logAction(AuditLog.ActionType.TRUST_UPDATE, "oracle trust score update");
    }

    /// @notice Batched version - oracle_bridge.py uses this to push all 20
    /// devices' scores in a single transaction instead of 20 separate ones.
    function submitBatch(address[] calldata devicesList, uint256[] calldata scores) external onlyOwner {
        require(devicesList.length == scores.length, "TrustOracle: length mismatch");
        for (uint256 i = 0; i < devicesList.length; i++) {
            require(scores[i] <= 100, "TrustOracle: score out of range");
            registry.updateTrustScore(devicesList[i], scores[i]);
            emit TrustScoreSubmitted(devicesList[i], scores[i], block.timestamp);
        }
        auditLog.logAction(AuditLog.ActionType.TRUST_UPDATE, "oracle batch trust score update");
    }
}
