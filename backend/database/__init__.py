"""
ValiGuard AI Database Package

Provides SQLAlchemy models and database management functionality.
"""

from database.models import (
    Base,
    Bridge, BridgeStatus,
    Transaction, TransactionStatus,
    AnomalyDetection, SeverityLevel,
    Validator,
    Alert, AlertSeverity, AlertType
)

from database.db import (
    DatabaseConfig,
    DatabaseManager,
    SeedData,
    init_db_manager,
    get_db_manager,
    get_session,
    init_database,
    seed_database
)

__all__ = [
    # Models
    "Base",
    "Bridge", "BridgeStatus",
    "Transaction", "TransactionStatus",
    "AnomalyDetection", "SeverityLevel",
    "Validator",
    "Alert", "AlertSeverity", "AlertType",
    
    # Database Management
    "DatabaseConfig",
    "DatabaseManager",
    "SeedData",
    "init_db_manager",
    "get_db_manager",
    "get_session",
    "init_database",
    "seed_database",
]
