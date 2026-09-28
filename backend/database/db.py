"""
Database initialization and management module for ValiGuard AI.
Handles database setup, migrations, session management, and monitoring.
"""

import os
import csv
import shutil
from datetime import datetime
from typing import Optional, List, Generator, Dict, Any
from contextlib import contextmanager
import logging

from sqlalchemy import create_engine, inspect, text, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
try:
    import alembic.config
    import alembic.command
except ImportError:
    alembic = None

from database.models import (
    Base, Bridge, Transaction, AnomalyDetection, Validator, Alert,
    BridgeStatus, TransactionStatus, SeverityLevel, AlertSeverity, AlertType
)

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


class DatabaseConfig:
    """Database configuration management."""
    
    def __init__(self, db_url: Optional[str] = None, echo_sql: bool = False):
        """
        Initialize database configuration.
        
        Args:
            db_url: Database URL (uses env var or SQLite by default)
            echo_sql: Enable SQL logging
        """
        self.db_url = db_url or self._get_db_url()
        self.echo_sql = echo_sql
        self.is_sqlite = self.db_url.startswith("sqlite")
        self.is_postgres = self.db_url.startswith("postgresql")
    
    @staticmethod
    def _get_db_url() -> str:
        """Get database URL from environment or use SQLite."""
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            return db_url
        
        # Default to SQLite in development
        db_path = os.path.join(os.path.dirname(__file__), "..", "..", "valiguard.db")
        return f"sqlite:///{db_path}"
    
    def get_engine(self):
        """Create and return SQLAlchemy engine."""
        engine_kwargs = {
            "echo": self.echo_sql,
            "future": True,
        }
        
        if self.is_sqlite:
            # SQLite-specific configuration
            engine_kwargs["connect_args"] = {"check_same_thread": False}
            engine_kwargs["poolclass"] = StaticPool
        else:
            # PostgreSQL connection pooling
            engine_kwargs["pool_size"] = 20
            engine_kwargs["max_overflow"] = 40
            engine_kwargs["pool_pre_ping"] = True
            engine_kwargs["pool_recycle"] = 3600
        
        engine = create_engine(self.db_url, **engine_kwargs)
        
        # Add logging for SQLAlchemy events in debug mode
        if self.echo_sql:
            @event.listens_for(engine, "before_cursor_execute")
            def receive_before_cursor_execute(conn, cursor, statement, params, context, executemany):
                logger.debug(f"SQL: {statement}")
        
        return engine


class DatabaseManager:
    """Database manager for operations like init, migrate, backup, etc."""
    
    def __init__(self, config: Optional[DatabaseConfig] = None):
        """
        Initialize database manager.
        
        Args:
            config: DatabaseConfig instance
        """
        self.config = config or DatabaseConfig()
        self.engine = self.config.get_engine()
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
            expire_on_commit=False
        )
    
    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        Context manager for database sessions with automatic cleanup.
        
        Yields:
            SQLAlchemy Session
            
        Example:
            with db_manager.get_session() as session:
                bridges = session.query(Bridge).all()
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            session.close()
    
    def init_db(self) -> bool:
        """
        Initialize database and create all tables.
        
        Returns:
            True if successful
        """
        try:
            logger.info(f"Initializing database: {self.config.db_url}")
            Base.metadata.create_all(bind=self.engine)
            logger.info("✅ Database initialized successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize database: {e}")
            return False
    
    def drop_db(self, confirm: bool = False) -> bool:
        """
        Drop all tables (development only).
        
        Args:
            confirm: Require confirmation to prevent accidental drops
            
        Returns:
            True if successful
        """
        if not confirm:
            logger.warning("⚠️  Database drop requires confirmation. Pass confirm=True")
            return False
        
        try:
            logger.warning("Dropping all database tables...")
            Base.metadata.drop_all(bind=self.engine)
            logger.warning("✅ All tables dropped successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to drop database: {e}")
            return False
    
    def reset_db(self, confirm: bool = False) -> bool:
        """
        Reset database (drop and recreate).
        
        Args:
            confirm: Require confirmation
            
        Returns:
            True if successful
        """
        if not confirm:
            logger.warning("⚠️  Database reset requires confirmation. Pass confirm=True")
            return False
        
        try:
            self.drop_db(confirm=True)
            self.init_db()
            logger.info("✅ Database reset successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to reset database: {e}")
            return False
    
    def migrate_db(self) -> bool:
        """
        Run pending Alembic migrations.
        
        Returns:
            True if successful
        """
        if alembic is None:
            logger.warning("Alembic not installed, skipping migrations")
            return False
        try:
            logger.info("Running database migrations...")
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            alembic_cfg = alembic.config.Config(
                os.path.join(backend_dir, "alembic.ini")
            )
            alembic_cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__)))
            alembic.command.upgrade(alembic_cfg, "head")
            logger.info("✅ Migrations applied successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            return False
    
    def backup_db(self, backup_dir: str = "backups") -> Optional[str]:
        """
        Backup database before migrations.
        
        Args:
            backup_dir: Directory to store backups
            
        Returns:
            Path to backup file or None if failed
        """
        if not self.config.is_sqlite:
            logger.warning("Backup only supported for SQLite")
            return None
        
        try:
            os.makedirs(backup_dir, exist_ok=True)
            
            # Extract database path from SQLite URL
            db_path = self.config.db_url.replace("sqlite:///", "")
            if not os.path.exists(db_path):
                logger.warning("Database file not found for backup")
                return None
            
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(backup_dir, f"valiguard_{timestamp}.db")
            
            shutil.copy2(db_path, backup_path)
            logger.info(f"✅ Database backed up to {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"❌ Backup failed: {e}")
            return None
    
    def export_to_csv(self, export_dir: str = "exports") -> bool:
        """
        Export all tables to CSV files.
        
        Args:
            export_dir: Directory to store exports
            
        Returns:
            True if successful
        """
        try:
            os.makedirs(export_dir, exist_ok=True)
            
            with self.get_session() as session:
                # Export Bridges
                bridges = session.query(Bridge).all()
                with open(os.path.join(export_dir, "bridges.csv"), "w", newline="") as f:
                    if bridges:
                        writer = csv.DictWriter(f, fieldnames=bridges[0].to_dict().keys())
                        writer.writeheader()
                        for bridge in bridges:
                            writer.writerow(bridge.to_dict())
                logger.info(f"Exported {len(bridges)} bridges")
                
                # Export Transactions
                transactions = session.query(Transaction).all()
                with open(os.path.join(export_dir, "transactions.csv"), "w", newline="") as f:
                    if transactions:
                        writer = csv.DictWriter(f, fieldnames=transactions[0].to_dict().keys())
                        writer.writeheader()
                        for tx in transactions:
                            writer.writerow(tx.to_dict())
                logger.info(f"Exported {len(transactions)} transactions")
                
                # Export Validators
                validators = session.query(Validator).all()
                with open(os.path.join(export_dir, "validators.csv"), "w", newline="") as f:
                    if validators:
                        writer = csv.DictWriter(f, fieldnames=validators[0].to_dict().keys())
                        writer.writeheader()
                        for val in validators:
                            writer.writerow(val.to_dict())
                logger.info(f"Exported {len(validators)} validators")
                
                # Export Alerts
                alerts = session.query(Alert).all()
                with open(os.path.join(export_dir, "alerts.csv"), "w", newline="") as f:
                    if alerts:
                        writer = csv.DictWriter(f, fieldnames=alerts[0].to_dict().keys())
                        writer.writeheader()
                        for alert in alerts:
                            writer.writerow(alert.to_dict())
                logger.info(f"Exported {len(alerts)} alerts")
            
            logger.info(f"✅ All data exported to {export_dir}")
            return True
        except Exception as e:
            logger.error(f"❌ Export failed: {e}")
            return False
    
    def health_check(self) -> Dict[str, Any]:
        """
        Check database health and connection.
        
        Returns:
            Dictionary with health status
        """
        health = {
            "status": "healthy",
            "database": self.config.db_url,
            "engine_type": "sqlite" if self.config.is_sqlite else "postgresql",
            "tables": 0,
            "pool_size": 0,
            "connection_ok": False
        }
        
        try:
            with self.engine.connect() as conn:
                health["connection_ok"] = True
                
                # Get table count
                inspector = inspect(self.engine)
                health["tables"] = len(inspector.get_table_names())
                
                # Get pool info if not SQLite
                if not self.config.is_sqlite:
                    pool_info = self.engine.pool
                    if hasattr(pool_info, 'size'):
                        health["pool_size"] = pool_info.size()
            
            return health
        except Exception as e:
            health["status"] = "unhealthy"
            health["error"] = str(e)
            return health
    
    def get_db_stats(self) -> Dict[str, Any]:
        """
        Get database statistics.
        
        Returns:
            Dictionary with statistics
        """
        stats = {}
        
        try:
            with self.get_session() as session:
                stats["bridges"] = session.query(Bridge).count()
                stats["transactions"] = session.query(Transaction).count()
                stats["anomalies"] = session.query(AnomalyDetection).count()
                stats["validators"] = session.query(Validator).count()
                stats["alerts"] = session.query(Alert).count()
                stats["alerts_unresolved"] = session.query(Alert).filter(
                    Alert.is_resolved == False
                ).count()
                stats["transactions_flagged"] = session.query(Transaction).filter(
                    Transaction.is_flagged == True
                ).count()
            
            return stats
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {}


class SeedData:
    """Generate seed data for testing and development."""
    
    @staticmethod
    def seed_bridges(session: Session, count: int = 3) -> List[Bridge]:
        """Create sample bridges."""
        bridges = []
        chains = ["QIE", "Ethereum", "Polygon"]
        
        for i in range(count):
            bridge = Bridge(
                address=f"0x{'a' * (64 - len(str(i)))}{i}",
                chain_name=chains[i % len(chains)],
                status=BridgeStatus.ACTIVE if i % 3 != 0 else BridgeStatus.PAUSED
            )
            session.add(bridge)
            bridges.append(bridge)
        
        session.commit()
        logger.info(f"✅ Created {len(bridges)} sample bridges")
        return bridges
    
    @staticmethod
    def seed_validators(session: Session, count: int = 5) -> List[Validator]:
        """Create sample validators."""
        validators = []
        
        for i in range(count):
            validator = Validator(
                address=f"qie1validator{i}{'a' * (50 - len(str(i)))}",
                name=f"Validator {i+1}",
                stake_amount=1000.0 + (i * 500),
                uptime_percentage=95.0 + (i * 0.5),
                is_active=i % 2 == 0
            )
            session.add(validator)
            validators.append(validator)
        
        session.commit()
        logger.info(f"✅ Created {len(validators)} sample validators")
        return validators
    
    @staticmethod
    def seed_transactions(
        session: Session,
        bridges: List[Bridge],
        count: int = 10
    ) -> List[Transaction]:
        """Create sample transactions."""
        transactions = []
        
        for i in range(count):
            bridge = bridges[i % len(bridges)]
            tx = Transaction(
                tx_hash=f"0x{'b' * (64 - len(str(i)))}{i}",
                bridge_id=bridge.id,
                source_chain="Ethereum",
                destination_chain="Polygon",
                value=100.5 + i,
                sender=f"0x{'c' * (40 - len(str(i)))}{i}",
                receiver=f"0x{'d' * (40 - len(str(i)))}{i}",
                status=TransactionStatus.CONFIRMED if i % 3 != 0 else TransactionStatus.PENDING,
                anomaly_score=10.0 if i % 5 != 0 else 75.0,
                is_flagged=i % 5 == 0
            )
            session.add(tx)
            transactions.append(tx)
        
        session.commit()
        logger.info(f"✅ Created {len(transactions)} sample transactions")
        return transactions
    
    @staticmethod
    def seed_anomalies(
        session: Session,
        transactions: List[Transaction]
    ) -> List[AnomalyDetection]:
        """Create sample anomaly detections."""
        anomalies = []
        severity_levels = [SeverityLevel.LOW, SeverityLevel.MEDIUM, SeverityLevel.HIGH, SeverityLevel.CRITICAL]
        
        for i, tx in enumerate(transactions):
            if tx.is_flagged or tx.anomaly_score > 50:
                anomaly = AnomalyDetection(
                    transaction_id=tx.id,
                    anomaly_score=tx.anomaly_score,
                    confidence=85.0 + (i % 10),
                    features_used={
                        "volume_deviation": True,
                        "frequency_anomaly": i % 3 == 0,
                        "pattern_match": i % 2 == 0
                    },
                    model_version="v1.0.0",
                    severity=severity_levels[i % len(severity_levels)],
                    reason=f"Transaction {i} flagged for manual review"
                )
                session.add(anomaly)
                anomalies.append(anomaly)
        
        session.commit()
        logger.info(f"✅ Created {len(anomalies)} sample anomaly detections")
        return anomalies
    
    @staticmethod
    def seed_alerts(
        session: Session,
        transactions: List[Transaction]
    ) -> List[Alert]:
        """Create sample alerts."""
        alerts = []
        alert_types = [AlertType.ANOMALY, AlertType.TIMEOUT, AlertType.ERROR]
        severities = [SeverityLevel.LOW, SeverityLevel.MEDIUM, SeverityLevel.HIGH, SeverityLevel.CRITICAL]
        
        for i, tx in enumerate(transactions):
            if i % 3 == 0:
                alert = Alert(
                    transaction_id=tx.id,
                    alert_type=alert_types[i % len(alert_types)],
                    severity=severities[i % len(severities)],
                    message=f"Alert for transaction {tx.tx_hash[:16]}... - Status: {tx.status.value}",
                    is_resolved=i % 5 == 0
                )
                session.add(alert)
                alerts.append(alert)
        
        session.commit()
        logger.info(f"✅ Created {len(alerts)} sample alerts")
        return alerts
    
    @staticmethod
    def seed_all(session: Session) -> Dict[str, int]:
        """Seed all sample data."""
        logger.info("🌱 Seeding database with sample data...")
        
        bridges = SeedData.seed_bridges(session, count=3)
        validators = SeedData.seed_validators(session, count=5)
        transactions = SeedData.seed_transactions(session, bridges, count=15)
        anomalies = SeedData.seed_anomalies(session, transactions)
        alerts = SeedData.seed_alerts(session, transactions)
        
        return {
            "bridges": len(bridges),
            "validators": len(validators),
            "transactions": len(transactions),
            "anomalies": len(anomalies),
            "alerts": len(alerts)
        }


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


def init_db_manager(db_url: Optional[str] = None, echo_sql: bool = False) -> DatabaseManager:
    """
    Initialize and return the global database manager.
    
    Args:
        db_url: Database URL
        echo_sql: Enable SQL logging
        
    Returns:
        DatabaseManager instance
    """
    global _db_manager
    config = DatabaseConfig(db_url=db_url, echo_sql=echo_sql)
    _db_manager = DatabaseManager(config)
    return _db_manager


def get_db_manager() -> DatabaseManager:
    """Get the global database manager."""
    if _db_manager is None:
        return init_db_manager()
    return _db_manager


# Convenience functions
def get_session() -> Session:
    """Get a new database session."""
    return get_db_manager().get_session()


def init_database(echo_sql: bool = False) -> bool:
    """Initialize the database."""
    return get_db_manager().init_db()


def seed_database() -> Dict[str, int]:
    """Seed database with sample data."""
    with get_db_manager().get_session() as session:
        return SeedData.seed_all(session)
