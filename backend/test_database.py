"""
Unit tests for ValiGuard AI database models and operations.
"""

import pytest
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import (
    DatabaseConfig, DatabaseManager, SeedData,
    Bridge, Transaction, AnomalyDetection, Validator, Alert,
    BridgeStatus, TransactionStatus, SeverityLevel, AlertType, AlertSeverity,
)
from sqlalchemy.orm import Session


@pytest.fixture
def test_db():
    """Create an in-memory SQLite database for testing."""
    config = DatabaseConfig("sqlite:///:memory:", echo_sql=False)
    db = DatabaseManager(config)
    db.init_db()
    return db


@pytest.fixture
def session(test_db):
    """Create a test session."""
    with test_db.get_session() as sess:
        yield sess


class TestBridgeModel:
    """Test Bridge model."""
    
    def test_create_bridge(self, session):
        """Test creating a bridge."""
        bridge = Bridge(
            address="0xabc123",
            chain_name="QIE",
            status=BridgeStatus.ACTIVE
        )
        session.add(bridge)
        session.commit()
        
        retrieved = session.query(Bridge).first()
        assert retrieved.address == "0xabc123"
        assert retrieved.chain_name == "QIE"
        assert retrieved.status == BridgeStatus.ACTIVE
    
    def test_bridge_to_dict(self, session):
        """Test Bridge.to_dict() serialization."""
        bridge = Bridge(
            address="0xdef456",
            chain_name="Ethereum",
            status=BridgeStatus.PAUSED
        )
        session.add(bridge)
        session.commit()
        
        data = bridge.to_dict()
        assert data["address"] == "0xdef456"
        assert data["chain_name"] == "Ethereum"
        assert data["status"] == "paused"
        assert "created_at" in data
    
    def test_bridge_repr(self, session):
        """Test Bridge.__repr__()."""
        bridge = Bridge(
            address="0xghi789",
            chain_name="Polygon",
            status=BridgeStatus.INACTIVE
        )
        assert "Bridge" in repr(bridge)
        assert "0xghi789" in repr(bridge)


class TestTransactionModel:
    """Test Transaction model."""
    
    def test_create_transaction(self, session):
        """Test creating a transaction."""
        bridge = Bridge(address="0x111", chain_name="QIE")
        session.add(bridge)
        session.commit()
        
        tx = Transaction(
            tx_hash="0xabc",
            bridge_id=bridge.id,
            source_chain="Ethereum",
            destination_chain="Polygon",
            value=100.0,
            sender="0xsender",
            receiver="0xreceiver",
            status=TransactionStatus.CONFIRMED
        )
        session.add(tx)
        session.commit()
        
        retrieved = session.query(Transaction).first()
        assert retrieved.tx_hash == "0xabc"
        assert retrieved.value == 100.0
        assert retrieved.status == TransactionStatus.CONFIRMED
    
    def test_transaction_flagged(self, session):
        """Test transaction flagging."""
        bridge = Bridge(address="0x222", chain_name="QIE")
        session.add(bridge)
        session.commit()
        
        tx = Transaction(
            tx_hash="0xdef",
            bridge_id=bridge.id,
            source_chain="Ethereum",
            destination_chain="Polygon",
            value=50.0,
            sender="0xsender",
            receiver="0xreceiver",
            anomaly_score=85.0,
            is_flagged=True
        )
        session.add(tx)
        session.commit()
        
        retrieved = session.query(Transaction).filter_by(is_flagged=True).first()
        assert retrieved.is_flagged is True
        assert retrieved.anomaly_score == 85.0
    
    def test_transaction_to_dict(self, session):
        """Test Transaction.to_dict()."""
        bridge = Bridge(address="0x333", chain_name="QIE")
        session.add(bridge)
        session.commit()
        
        tx = Transaction(
            tx_hash="0xghi",
            bridge_id=bridge.id,
            source_chain="Ethereum",
            destination_chain="Polygon",
            value=75.5,
            sender="0xsender",
            receiver="0xreceiver"
        )
        session.add(tx)
        session.commit()
        
        data = tx.to_dict()
        assert data["tx_hash"] == "0xghi"
        assert data["value"] == 75.5
        assert data["status"] == "pending"


class TestAnomalyDetectionModel:
    """Test AnomalyDetection model."""
    
    def test_create_anomaly(self, session):
        """Test creating an anomaly detection."""
        bridge = Bridge(address="0x444", chain_name="QIE")
        session.add(bridge)
        session.commit()
        
        tx = Transaction(
            tx_hash="0xjkl",
            bridge_id=bridge.id,
            source_chain="Ethereum",
            destination_chain="Polygon",
            value=100.0,
            sender="0xsender",
            receiver="0xreceiver"
        )
        session.add(tx)
        session.commit()
        
        anomaly = AnomalyDetection(
            transaction_id=tx.id,
            anomaly_score=92.5,
            confidence=88.0,
            features_used={"feature1": True, "feature2": False},
            model_version="v1.0.0",
            severity=SeverityLevel.CRITICAL,
            reason="Suspicious volume pattern detected"
        )
        session.add(anomaly)
        session.commit()
        
        retrieved = session.query(AnomalyDetection).first()
        assert retrieved.anomaly_score == 92.5
        assert retrieved.severity == SeverityLevel.CRITICAL
        assert "feature1" in retrieved.features_used
    
    def test_anomaly_to_dict(self, session):
        """Test AnomalyDetection.to_dict()."""
        bridge = Bridge(address="0x555", chain_name="QIE")
        session.add(bridge)
        session.commit()
        
        tx = Transaction(
            tx_hash="0xmno",
            bridge_id=bridge.id,
            source_chain="Ethereum",
            destination_chain="Polygon",
            value=100.0,
            sender="0xsender",
            receiver="0xreceiver"
        )
        session.add(tx)
        session.commit()
        
        anomaly = AnomalyDetection(
            transaction_id=tx.id,
            anomaly_score=75.0,
            confidence=90.0,
            features_used={"feature": "value"},
            model_version="v1.0.0",
            severity=SeverityLevel.HIGH
        )
        session.add(anomaly)
        session.commit()
        
        data = anomaly.to_dict()
        assert data["anomaly_score"] == 75.0
        assert data["severity"] == "high"
        assert data["model_version"] == "v1.0.0"


class TestValidatorModel:
    """Test Validator model."""
    
    def test_create_validator(self, session):
        """Test creating a validator."""
        validator = Validator(
            address="qie1validator123",
            name="Test Validator",
            stake_amount=1000.0,
            uptime_percentage=99.5,
            is_active=True
        )
        session.add(validator)
        session.commit()
        
        retrieved = session.query(Validator).first()
        assert retrieved.address == "qie1validator123"
        assert retrieved.name == "Test Validator"
        assert retrieved.stake_amount == 1000.0
        assert retrieved.is_active is True
    
    def test_validator_to_dict(self, session):
        """Test Validator.to_dict()."""
        validator = Validator(
            address="qie1validator456",
            name="Another Validator",
            stake_amount=2000.0,
            uptime_percentage=98.0,
            is_active=False
        )
        session.add(validator)
        session.commit()
        
        data = validator.to_dict()
        assert data["address"] == "qie1validator456"
        assert data["stake_amount"] == 2000.0
        assert data["is_active"] is False


class TestAlertModel:
    """Test Alert model."""
    
    def test_create_alert(self, session):
        """Test creating an alert."""
        bridge = Bridge(address="0x666", chain_name="QIE")
        session.add(bridge)
        session.commit()
        
        tx = Transaction(
            tx_hash="0xpqr",
            bridge_id=bridge.id,
            source_chain="Ethereum",
            destination_chain="Polygon",
            value=100.0,
            sender="0xsender",
            receiver="0xreceiver"
        )
        session.add(tx)
        session.commit()
        
        alert = Alert(
            transaction_id=tx.id,
            alert_type=AlertType.ANOMALY,
            severity=AlertSeverity.CRITICAL,
            message="Critical anomaly detected",
            is_resolved=False
        )
        session.add(alert)
        session.commit()
        
        retrieved = session.query(Alert).first()
        assert retrieved.alert_type == AlertType.ANOMALY
        assert retrieved.severity == SeverityLevel.CRITICAL
        assert retrieved.is_resolved is False
    
    def test_alert_to_dict(self, session):
        """Test Alert.to_dict()."""
        bridge = Bridge(address="0x777", chain_name="QIE")
        session.add(bridge)
        session.commit()
        
        tx = Transaction(
            tx_hash="0xstu",
            bridge_id=bridge.id,
            source_chain="Ethereum",
            destination_chain="Polygon",
            value=100.0,
            sender="0xsender",
            receiver="0xreceiver"
        )
        session.add(tx)
        session.commit()
        
        alert = Alert(
            transaction_id=tx.id,
            alert_type=AlertType.ERROR,
            severity=SeverityLevel.MEDIUM,
            message="Warning message"
        )
        session.add(alert)
        session.commit()
        
        data = alert.to_dict()
        assert data["alert_type"] == "error"
        assert data["severity"] == "medium"


class TestRelationships:
    """Test model relationships."""
    
    def test_bridge_transactions_relationship(self, session):
        """Test Bridge -> Transaction relationship."""
        bridge = Bridge(address="0x888", chain_name="QIE")
        session.add(bridge)
        session.commit()
        
        tx1 = Transaction(
            tx_hash="0xvwx1",
            bridge_id=bridge.id,
            source_chain="Ethereum",
            destination_chain="Polygon",
            value=100.0,
            sender="0xsender",
            receiver="0xreceiver"
        )
        tx2 = Transaction(
            tx_hash="0xvwx2",
            bridge_id=bridge.id,
            source_chain="Ethereum",
            destination_chain="Polygon",
            value=200.0,
            sender="0xsender",
            receiver="0xreceiver"
        )
        session.add_all([tx1, tx2])
        session.commit()
        
        retrieved = session.query(Bridge).first()
        assert len(retrieved.transactions) == 2
    
    def test_transaction_anomalies_relationship(self, session):
        """Test Transaction -> AnomalyDetection relationship."""
        bridge = Bridge(address="0x999", chain_name="QIE")
        session.add(bridge)
        session.commit()
        
        tx = Transaction(
            tx_hash="0xyza",
            bridge_id=bridge.id,
            source_chain="Ethereum",
            destination_chain="Polygon",
            value=100.0,
            sender="0xsender",
            receiver="0xreceiver"
        )
        session.add(tx)
        session.commit()
        
        anomaly1 = AnomalyDetection(
            transaction_id=tx.id,
            anomaly_score=50.0,
            confidence=80.0,
            model_version="v1.0.0",
            severity=SeverityLevel.MEDIUM
        )
        anomaly2 = AnomalyDetection(
            transaction_id=tx.id,
            anomaly_score=75.0,
            confidence=90.0,
            model_version="v1.0.0",
            severity=SeverityLevel.HIGH
        )
        session.add_all([anomaly1, anomaly2])
        session.commit()
        
        retrieved = session.query(Transaction).first()
        assert len(retrieved.anomalies) == 2


class TestSeedData:
    """Test SeedData generation."""
    
    def test_seed_bridges(self, session):
        """Test seeding bridges."""
        bridges = SeedData.seed_bridges(session, count=3)
        assert len(bridges) == 3
        assert all(isinstance(b, Bridge) for b in bridges)
    
    def test_seed_validators(self, session):
        """Test seeding validators."""
        validators = SeedData.seed_validators(session, count=5)
        assert len(validators) == 5
        assert all(isinstance(v, Validator) for v in validators)
    
    def test_seed_all(self, session):
        """Test seeding all data."""
        counts = SeedData.seed_all(session)
        assert counts["bridges"] > 0
        assert counts["transactions"] > 0
        assert counts["validators"] > 0


class TestDatabaseManager:
    """Test DatabaseManager operations."""
    
    def test_health_check(self, test_db):
        """Test database health check."""
        health = test_db.health_check()
        assert health["status"] == "healthy"
        assert health["connection_ok"] is True
    
    def test_get_db_stats(self, test_db):
        """Test getting database statistics."""
        with test_db.get_session() as session:
            SeedData.seed_all(session)
        
        stats = test_db.get_db_stats()
        assert stats["bridges"] > 0
        assert stats["transactions"] > 0
        assert stats["validators"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
