// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./DeviceRegistry.sol";
import "./AuditLog.sol";

/// @title EnergyTrade
/// @notice CONTRACT 2 of 4. P2P energy offer/accept marketplace. Every entry
/// point is trust-gated: this is the concrete mechanism by which an
/// ML-derived reputation score becomes an enforceable economic consequence
/// for a misbehaving device (Section 1, Step 9: "transactions with trust<50
/// are REJECTED; events logged to AuditLog").
///
/// Deployment note (fixes a real issue in the brief's example code): the
/// brief's requiresTrust modifier uses `require()`, which REVERTS the whole
/// transaction on failure - and a reverted transaction's events are
/// discarded by the EVM, they never reach a log. That makes a literal
/// `event TradeDenied` inside a reverting modifier unobservable on-chain.
/// Fixed here with a soft-fail pattern: trust is checked manually, and a
/// denial returns `false` + emits TradeDenied + writes to AuditLog instead
/// of reverting, so "denied" is an actual observable on-chain outcome.
contract EnergyTrade {
    DeviceRegistry public registry;
    AuditLog public auditLog;
    uint256 public constant MIN_TRUST = 50;   // REQ: hardcoded, do not change

    struct EnergyOffer {
        address seller;
        uint256 quantityKWh;
        uint256 pricePerKWh; // wei per kWh
        bool active;
    }

    mapping(uint256 => EnergyOffer) public offers;
    uint256 public offerCount;

    event OfferPosted(uint256 indexed offerId, address indexed seller, uint256 qty, uint256 price);
    event TradeSettled(address indexed buyer, address indexed seller, uint256 qty, uint256 total, uint256 ts);
    event TradeDenied(address indexed initiator, uint256 trustScore, string reason);

    constructor(address _registry, address _auditLog) {
        registry = DeviceRegistry(_registry);
        auditLog = AuditLog(_auditLog);
    }

    function _isTrusted(address device) internal view returns (bool ok, uint256 score) {
        DeviceRegistry.DeviceProfile memory p = registry.getDevice(device);
        score = p.trustScore;
        ok = (!p.isSuspended) && (p.trustScore >= MIN_TRUST) && (p.registeredAt != 0);
    }

    /// @notice Soft-fails (no revert) on insufficient trust so the denial is
    /// itself an observable, loggable on-chain event.
    function postOffer(uint256 _qty, uint256 _price) external returns (bool) {
        (bool ok, uint256 score) = _isTrusted(msg.sender);
        if (!ok) {
            emit TradeDenied(msg.sender, score, "trust score below threshold or suspended");
            auditLog.logAction(AuditLog.ActionType.TRADE_DENIED, "postOffer denied: insufficient trust");
            return false;
        }
        offers[offerCount] = EnergyOffer(msg.sender, _qty, _price, true);
        emit OfferPosted(offerCount, msg.sender, _qty, _price);
        offerCount++;
        return true;
    }

    function acceptOffer(uint256 offerId) external payable returns (bool) {
        (bool ok, uint256 score) = _isTrusted(msg.sender);
        if (!ok) {
            emit TradeDenied(msg.sender, score, "trust score below threshold or suspended");
            auditLog.logAction(AuditLog.ActionType.TRADE_DENIED, "acceptOffer denied: insufficient trust");
            return false;
        }

        EnergyOffer storage offer = offers[offerId];
        require(offer.active, "Offer not active");
        uint256 total = offer.quantityKWh * offer.pricePerKWh;
        require(msg.value >= total, "Insufficient payment");

        offer.active = false;
        registry.incrementTxCount(offer.seller);
        registry.incrementTxCount(msg.sender);

        payable(offer.seller).transfer(total);
        if (msg.value > total) {
            payable(msg.sender).transfer(msg.value - total); // refund overpayment
        }

        emit TradeSettled(msg.sender, offer.seller, offer.quantityKWh, total, block.timestamp);
        auditLog.logAction(AuditLog.ActionType.TRADE_SETTLED, "acceptOffer settled");
        return true;
    }
}
