"""
SQLAlchemy database models for ValiGuard AI.
Includes Bridge, Transaction, AnomalyDetection, Validator, and Alert models.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, JSON, Index, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum
import json

Base = declarative_base()


class BridgeStatus(enum.Enum):
    """Enumeration for bridge status."""
    ACTIVE = "active"
    PAUSED = "paused"
    INACTIVE = "inactive"


class TransactionStatus(enum.Enum):
    """Enumeration for transaction status."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class SeverityLevel(enum.Enum):
    """Enumeration for severity levels (used by anomaly_detections AND alerts).

    Canonical 4-tier scale per FR-10 — shared with backend/core/severity.py,
    whose threshold map is the single source of truth for score->tier.
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Backward-compat alias: alerts now use the same 4-tier SeverityLevel scale.
AlertSeverity = SeverityLevel


class AlertType(enum.Enum):
    """Enumeration for alert types."""
    ANOMALY = "anomaly"
    TIMEOUT = "timeout"
    ERROR = "error"


class Bridge(Base):
    """
    Represents a cross-chain bridge on the QIE network.
    
    Attributes:
        id: Primary key
        address: Unique bridge contract address
        chain_name: Source chain name (QIE, Ethereum, Polygon)
        status: Current bridge status (active, paused, inactive)
        created_at: Creation timestamp
        last_verified_at: Last verification timestamp
        transactions: Related transactions
    """
    __tablename__ = "bridges"
    
    id = Column(Integer, primary_key=True, index=True)
    address = Column(String(255), unique=True, nullable=False, index=True)
    chain_name = Column(String(50), nullable=False)
    status = Column(Enum(BridgeStatus), default=BridgeStatus.ACTIVE, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    last_verified_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    transactions = relationship("Transaction", back_populates="bridge", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index("idx_bridge_address", "address"),
        Index("idx_bridge_chain_created", "chain_name", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"<Bridge(id={self.id}, address={self.address}, chain={self.chain_name}, status={self.status})>"
    
    def to_dict(self, include_transactions: bool = False) -> Dict[str, Any]:
        """
        Convert Bridge to dictionary for JSON serialization.
        
        Args:
            include_transactions: Include related transactions
            
        Returns:
            Dictionary representation of the bridge
        """
        data = {
            "id": self.id,
            "address": self.address,
            "chain_name": self.chain_name,
            "status": self.status.value if self.status else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_verified_at": self.last_verified_at.isoformat() if self.last_verified_at else None,
        }
        if include_transactions:
            data["transactions"] = [tx.to_dict() for tx in self.transactions]
        return data


class Transaction(Base):
    """
    Represents a cross-chain transaction.
    
    Attributes:
        id: Primary key
        tx_hash: Unique transaction hash
        bridge_id: Foreign key to Bridge
        source_chain: Source blockchain
        destination_chain: Destination blockchain
        value: Transaction value
        sender: Sender address
        receiver: Receiver address
        timestamp: Transaction timestamp
        status: Transaction status (pending, confirmed, failed)
        anomaly_score: Anomaly detection score (0-100)
        is_flagged: Whether transaction is flagged
        anomalies: Related anomaly detections
        alerts: Related alerts
    """
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    tx_hash = Column(String(255), unique=True, nullable=False, index=True)
    bridge_id = Column(Integer, ForeignKey("bridges.id"), nullable=True, index=True)
    source_chain = Column(String(50), nullable=True)
    destination_chain = Column(String(50), nullable=True)
    value = Column(Float, nullable=True)
    sender = Column(String(255), nullable=True)
    receiver = Column(String(255), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    status = Column(Enum(TransactionStatus), default=TransactionStatus.PENDING, nullable=False)
    anomaly_score = Column(Float, default=0.0)
    is_flagged = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    bridge = relationship("Bridge", back_populates="transactions")
    anomalies = relationship("AnomalyDetection", back_populates="transaction", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="transaction", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index("idx_tx_hash", "tx_hash"),
        Index("idx_tx_bridge_created", "bridge_id", "created_at"),
        Index("idx_tx_timestamp", "timestamp"),
        Index("idx_tx_flagged", "is_flagged"),
    )
    
    def __repr__(self) -> str:
        return f"<Transaction(id={self.id}, tx_hash={self.tx_hash}, status={self.status}, anomaly={self.anomaly_score})>"
    
    def to_dict(self, include_anomalies: bool = False, include_alerts: bool = False) -> Dict[str, Any]:
        """
        Convert Transaction to dictionary for JSON serialization.
        
        Args:
            include_anomalies: Include related anomaly detections
            include_alerts: Include related alerts
            
        Returns:
            Dictionary representation of the transaction
        """
        data = {
            "id": self.id,
            "tx_hash": self.tx_hash,
            "bridge_id": self.bridge_id,
            "source_chain": self.source_chain,
            "destination_chain": self.destination_chain,
            "value": self.value,
            "sender": self.sender,
            "receiver": self.receiver,
            "raw_entry": self.sender is None,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "status": self.status.value if self.status else None,
            "anomaly_score": self.anomaly_score,
            "is_flagged": self.is_flagged,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_anomalies:
            data["anomalies"] = [anom.to_dict() for anom in self.anomalies]
        if include_alerts:
            data["alerts"] = [alert.to_dict() for alert in self.alerts]
        return data


class AnomalyDetection(Base):
    """
    Records anomaly detection results for a transaction.
    
    Attributes:
        id: Primary key
        transaction_id: Foreign key to Transaction
        anomaly_score: Anomaly score (0-100)
        confidence: Confidence level (0-100)
        features_used: JSON object of features used
        model_version: ML model version used
        detected_at: Detection timestamp
        severity: Severity level (low, medium, high, critical)
        reason: Human-readable reason for the anomaly
        transaction: Related transaction
    """
    __tablename__ = "anomaly_detections"
    
    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False, index=True)
    anomaly_score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    features_used = Column(JSON, nullable=True)
    model_version = Column(String(50), nullable=False)
    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    severity = Column(Enum(SeverityLevel), default=SeverityLevel.LOW, nullable=False)
    reason = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    transaction = relationship("Transaction", back_populates="anomalies")
    
    # Indexes
    __table_args__ = (
        Index("idx_anomaly_transaction", "transaction_id"),
        Index("idx_anomaly_severity", "severity"),
        Index("idx_anomaly_detected", "detected_at"),
    )
    
    def __repr__(self) -> str:
        return f"<AnomalyDetection(id={self.id}, score={self.anomaly_score}, severity={self.severity})>"
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert AnomalyDetection to dictionary for JSON serialization.
        
        Returns:
            Dictionary representation of the anomaly detection
        """
        return {
            "id": self.id,
            "transaction_id": self.transaction_id,
            "anomaly_score": self.anomaly_score,
            "confidence": self.confidence,
            "features_used": self.features_used,
            "model_version": self.model_version,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "severity": self.severity.value if self.severity else None,
            "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Validator(Base):
    """
    Represents a QIE network validator.
    
    Attributes:
        id: Primary key
        address: Unique validator address
        name: Validator name
        stake_amount: Amount staked
        uptime_percentage: Uptime percentage (0-100)
        is_active: Whether validator is currently active
        joined_at: Timestamp when validator joined
    """
    __tablename__ = "validators"
    
    id = Column(Integer, primary_key=True, index=True)
    address = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    stake_amount = Column(Float, default=0.0, nullable=False)
    uptime_percentage = Column(Float, default=100.0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    joined_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Indexes
    __table_args__ = (
        Index("idx_validator_address", "address"),
        Index("idx_validator_active", "is_active"),
        Index("idx_validator_joined", "joined_at"),
    )
    
    def __repr__(self) -> str:
        return f"<Validator(id={self.id}, address={self.address}, name={self.name}, active={self.is_active})>"
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert Validator to dictionary for JSON serialization.
        
        Returns:
            Dictionary representation of the validator
        """
        return {
            "id": self.id,
            "address": self.address,
            "name": self.name,
            "stake_amount": self.stake_amount,
            "uptime_percentage": self.uptime_percentage,
            "is_active": self.is_active,
            "joined_at": self.joined_at.isoformat() if self.joined_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Alert(Base):
    """
    Represents an alert triggered by anomaly or system events.
    
    Attributes:
        id: Primary key
        transaction_id: Foreign key to Transaction
        alert_type: Type of alert (anomaly, timeout, error)
        severity: Severity level (low, medium, high, critical)
        message: Alert message
        is_resolved: Whether alert is resolved
        created_at: Alert creation timestamp
        resolved_at: Alert resolution timestamp
        transaction: Related transaction
    """
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False, index=True)
    alert_type = Column(Enum(AlertType), nullable=False)
    severity = Column(Enum(SeverityLevel), default=SeverityLevel.MEDIUM, nullable=False)
    message = Column(String(500), nullable=False)
    is_resolved = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    resolved_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    transaction = relationship("Transaction", back_populates="alerts")
    
    # Indexes
    __table_args__ = (
        Index("idx_alert_transaction", "transaction_id"),
        Index("idx_alert_type", "alert_type"),
        Index("idx_alert_severity", "severity"),
        Index("idx_alert_resolved", "is_resolved"),
        Index("idx_alert_created", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"<Alert(id={self.id}, type={self.alert_type}, severity={self.severity}, resolved={self.is_resolved})>"
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert Alert to dictionary for JSON serialization.
        
        Returns:
            Dictionary representation of the alert
        """
        return {
            "id": self.id,
            "transaction_id": self.transaction_id,
            "alert_type": self.alert_type.value if self.alert_type else None,
            "severity": self.severity.value if self.severity else None,
            "message": self.message,
            "is_resolved": self.is_resolved,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
