// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title AuditLog
/// @notice CONTRACT 4 of 4. Append-only log of system actions (trust
/// updates, settled/denied trades, registrations, suspensions).
///
/// RESEARCH SIGNIFICANCE: every trust update and every accepted/denied trade
/// needs a tamper-evident record for the system's fraud-resistance claim to
/// mean anything - the whole point of putting enforcement on-chain instead
/// of in a database is that nobody, including the oracle operator, can
/// quietly edit history after the fact. There is deliberately no delete or
/// update function - only logAction() - which is what makes this
/// "append-only" rather than just "a log".
contract AuditLog {
    enum ActionType { TRUST_UPDATE, TRADE_SETTLED, TRADE_DENIED, DEVICE_REGISTERED, DEVICE_SUSPENDED }

    struct LogEntry {
        address actor;
        ActionType actionType;
        string details;
        uint256 timestamp;
    }

    LogEntry[] private logs;

    event ActionLogged(uint256 indexed logId, address indexed actor, ActionType actionType,
                        string details, uint256 timestamp);

    function logAction(ActionType _type, string calldata _details) external {
        logs.push(LogEntry(msg.sender, _type, _details, block.timestamp));
        emit ActionLogged(logs.length - 1, msg.sender, _type, _details, block.timestamp);
    }

    function getLogCount() external view returns (uint256) {
        return logs.length;
    }

    function getLog(uint256 index) external view returns (address, ActionType, string memory, uint256) {
        LogEntry memory entry = logs[index];
        return (entry.actor, entry.actionType, entry.details, entry.timestamp);
    }
}
