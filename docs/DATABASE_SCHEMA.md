# ValiGuard AI Database Schema Documentation

## Overview

ValiGuard AI uses SQLAlchemy as the ORM layer with support for both SQLite (development) and PostgreSQL (production). The database stores bridge information, transactions, anomaly detections, validators, and alerts.

## Database Models

### 1. Bridge

Represents a cross-chain bridge on the QIE network.

**Attributes:**
- `id` (PK): Primary key, auto-increment
- `address` (UNIQUE, INDEX): Bridge contract address
- `chain_name`: Source chain name (QIE, Ethereum, Polygon)
- `status`: Bridge status (ACTIVE, PAUSED, INACTIVE)
- `created_at` (INDEX): Creation timestamp (auto)
- `last_verified_at`: Last verification timestamp (auto-update)

**Relationships:**
- One-to-Many: `transactions` - Related cross-chain transactions

**Indexes:**
- `idx_bridge_address`: Address lookup
- `idx_bridge_chain_created`: Chain and creation time queries

**Methods:**
- `to_dict(include_transactions=False)`: Convert to dictionary for JSON serialization

---

### 2. Transaction

Represents a cross-chain transaction routed through a bridge.

**Attributes:**
- `id` (PK): Primary key, auto-increment
- `tx_hash` (UNIQUE, INDEX): Transaction hash
- `bridge_id` (FK, INDEX): Reference to Bridge
- `source_chain`: Source blockchain name
- `destination_chain`: Destination blockchain name
- `value`: Transaction value/amount
- `sender`: Sender address
- `receiver`: Receiver address
- `timestamp` (INDEX): Transaction timestamp (auto)
- `status`: Status (PENDING, CONFIRMED, FAILED)
- `anomaly_score`: Anomaly detection score (0-100)
- `is_flagged`: Whether flagged for review
- `created_at` (INDEX): Record creation (auto)
- `updated_at`: Last update timestamp (auto-update)

**Relationships:**
- Many-to-One: `bridge` - Parent bridge
- One-to-Many: `anomalies` - Anomaly detection results
- One-to-Many: `alerts` - Related alerts

**Indexes:**
- `idx_tx_hash`: Hash lookup
- `idx_tx_bridge_created`: Bridge and time queries
- `idx_tx_timestamp`: Time-based queries
- `idx_tx_flagged`: Flagged transaction queries

**Methods:**
- `to_dict(include_anomalies=False, include_alerts=False)`: JSON serialization

---

### 3. AnomalyDetection

Records ML model anomaly detection results for transactions.

**Attributes:**
- `id` (PK): Primary key, auto-increment
- `transaction_id` (FK, INDEX): Reference to Transaction
- `anomaly_score`: Score (0-100)
- `confidence`: Confidence level (0-100)
- `features_used`: JSON object of ML features
- `model_version`: Version of ML model used
- `detected_at` (INDEX): Detection timestamp (auto)
- `severity`: Severity level (LOW, MEDIUM, HIGH, CRITICAL)
- `reason`: Human-readable description
- `created_at`: Record creation (auto)
- `updated_at`: Last update (auto-update)

**Relationships:**
- Many-to-One: `transaction` - Parent transaction

**Indexes:**
- `idx_anomaly_transaction`: Transaction lookup
- `idx_anomaly_severity`: Severity filtering
- `idx_anomaly_detected`: Time-based queries

**Methods:**
- `to_dict()`: JSON serialization

---

### 4. Validator

Represents a QIE network validator node.

**Attributes:**
- `id` (PK): Primary key, auto-increment
- `address` (UNIQUE, INDEX): Validator address
- `name`: Validator name/moniker
- `stake_amount`: Amount staked (default: 0.0)
- `uptime_percentage`: Uptime percentage (0-100)
- `is_active`: Whether currently active (default: True)
- `joined_at` (INDEX): Join timestamp (auto)
- `created_at`: Record creation (auto)
- `updated_at`: Last update (auto-update)

**Indexes:**
- `idx_validator_address`: Address lookup
- `idx_validator_active`: Active validator queries
- `idx_validator_joined`: Joined time queries

**Methods:**
- `to_dict()`: JSON serialization

---

### 5. Alert

Represents system alerts triggered by anomalies or events.

**Attributes:**
- `id` (PK): Primary key, auto-increment
- `transaction_id` (FK, INDEX): Reference to Transaction
- `alert_type`: Type (ANOMALY, TIMEOUT, ERROR)
- `severity`: Severity (INFO, WARNING, ERROR, CRITICAL)
- `message`: Alert message
- `is_resolved`: Resolution status (default: False)
- `created_at` (INDEX): Creation timestamp (auto)
- `resolved_at`: Resolution timestamp
- `updated_at`: Last update (auto-update)

**Relationships:**
- Many-to-One: `transaction` - Parent transaction

**Indexes:**
- `idx_alert_transaction`: Transaction lookup
- `idx_alert_type`: Alert type filtering
- `idx_alert_severity`: Severity filtering
- `idx_alert_resolved`: Resolution status queries
- `idx_alert_created`: Time-based queries

**Methods:**
- `to_dict()`: JSON serialization

---

## Enum Types

```python
# Bridge status
BridgeStatus: ACTIVE, PAUSED, INACTIVE

# Transaction status
TransactionStatus: PENDING, CONFIRMED, FAILED

# Anomaly severity
SeverityLevel: LOW, MEDIUM, HIGH, CRITICAL

# Alert severity
AlertSeverity: INFO, WARNING, ERROR, CRITICAL

# Alert type
AlertType: ANOMALY, TIMEOUT, ERROR
```

---

## Relationships Diagram

```
Bridge (1)
  ├── Transaction (Many)
  │     ├── AnomalyDetection (Many)
  │     └── Alert (Many)
  │
Validator (Standalone)
```

---

## Database Configuration

### Development (SQLite)

```python
# .env
DATABASE_URL=sqlite:///valiguard.db
```

**Pros:**
- No setup required
- File-based, portable
- Good for development/testing

**Cons:**
- Single-threaded
- Not suitable for production
- Limited scalability

### Production (PostgreSQL)

```python
# .env
DATABASE_URL=postgresql://user:password@localhost:5432/valiguard
```

**Pros:**
- Multi-user support
- Better performance
- Advanced features (full-text search, etc.)

**Cons:**
- Requires PostgreSQL server
- More complex setup

---

## Database Management

### Initialize Database

```bash
# CLI
python backend/manage_db.py init

# Python
from database import init_database
init_database()
```

### Seed Sample Data

```bash
# CLI
python backend/manage_db.py seed

# Python
from database import seed_database
counts = seed_database()
```

### Reset Database

```bash
# CLI (requires confirmation)
python backend/manage_db.py reset

# Python
db = get_db_manager()
db.reset_db(confirm=True)
```

### Backup Database

```bash
# CLI
python backend/manage_db.py backup

# Python
db = get_db_manager()
backup_path = db.backup_db()
```

### Export to CSV

```bash
# CLI
python backend/manage_db.py export

# Python
db = get_db_manager()
db.export_to_csv()
```

### Check Health

```bash
# CLI
python backend/manage_db.py health

# Python
db = get_db_manager()
health = db.health_check()
```

### View Statistics

```bash
# CLI
python backend/manage_db.py stats

# Python
db = get_db_manager()
stats = db.get_db_stats()
```

---

## Using Sessions

### Context Manager (Recommended)

```python
from database import get_db_manager

db = get_db_manager()

with db.get_session() as session:
    # Query
    bridges = session.query(Bridge).all()
    
    # Create
    new_bridge = Bridge(
        address="0x...",
        chain_name="QIE",
        status=BridgeStatus.ACTIVE
    )
    session.add(new_bridge)
    
    # Update
    bridge = session.query(Bridge).first()
    bridge.status = BridgeStatus.PAUSED
    
    # Delete
    session.delete(bridge)
    
    # Automatic commit on exit, rollback on exception
```

### Manual Session Management

```python
session = db.SessionLocal()
try:
    # Your operations
    session.commit()
except Exception as e:
    session.rollback()
    raise
finally:
    session.close()
```

---

## Query Examples

### Find Bridge by Address

```python
with db.get_session() as session:
    bridge = session.query(Bridge).filter(
        Bridge.address == "0x..."
    ).first()
```

### Get Recent Transactions

```python
from datetime import datetime, timedelta

with db.get_session() as session:
    yesterday = datetime.utcnow() - timedelta(days=1)
    
    transactions = session.query(Transaction).filter(
        Transaction.timestamp >= yesterday
    ).order_by(Transaction.timestamp.desc()).all()
```

### Get Flagged Transactions

```python
with db.get_session() as session:
    flagged = session.query(Transaction).filter(
        Transaction.is_flagged == True
    ).all()
```

### Get Anomalies by Severity

```python
with db.get_session() as session:
    critical = session.query(AnomalyDetection).filter(
        AnomalyDetection.severity == SeverityLevel.CRITICAL
    ).all()
```

### Get Active Validators

```python
with db.get_session() as session:
    validators = session.query(Validator).filter(
        Validator.is_active == True
    ).order_by(Validator.stake_amount.desc()).all()
```

### Get Unresolved Alerts

```python
with db.get_session() as session:
    alerts = session.query(Alert).filter(
        Alert.is_resolved == False
    ).order_by(Alert.created_at.desc()).all()
```

### Join Query: Transactions with Anomalies

```python
with db.get_session() as session:
    results = session.query(Transaction, AnomalyDetection).join(
        AnomalyDetection
    ).filter(
        AnomalyDetection.severity == SeverityLevel.HIGH
    ).all()
```

---

## Migrations with Alembic

### Create a New Migration

```bash
# Auto-detect changes
alembic revision --autogenerate -m "Add new column to transactions"

# Create empty migration
alembic revision -m "Migration message"
```

### Apply Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Apply specific revision
alembic upgrade 1975ea83b712

# Rollback
alembic downgrade -1
```

### View Migration History

```bash
alembic history
```

---

## Performance Considerations

1. **Indexes**: All critical queries have indexes for fast lookups
2. **Connection Pooling**: Configured for PostgreSQL in production
3. **Query Optimization**: Use specific fields in SELECT, avoid N+1 queries
4. **Batch Operations**: Use bulk inserts for large amounts of data

Example - Batch Insert:

```python
with db.get_session() as session:
    transactions = [
        Transaction(...),
        Transaction(...),
        Transaction(...),
    ]
    session.bulk_save_objects(transactions)
    session.commit()
```

---

## Troubleshooting

### Connection Issues

```python
db = get_db_manager()
health = db.health_check()
if not health['connection_ok']:
    print(f"Connection error: {health['error']}")
```

### Table Not Found

```python
# Reinitialize database
db.init_db()

# Or migrate
db.migrate_db()
```

### Lock Issues (SQLite)

SQLite can have issues with concurrent writes. Solutions:

1. Use PostgreSQL for production
2. Use WAL mode for SQLite:
   ```python
   engine.execute("PRAGMA journal_mode=WAL")
   ```

### Slow Queries

Enable SQL echo to see queries:

```python
db = init_db_manager(echo_sql=True)
```

---

## Best Practices

1. **Always use context managers** for sessions
2. **Use async sessions** for web frameworks
3. **Implement proper error handling** and logging
4. **Backup before migrations**
5. **Test queries in development** before production
6. **Use connection pooling** for PostgreSQL
7. **Keep models simple** and focused
8. **Document custom queries** and relationships

---

## Next Steps

1. Integrate with Flask API endpoints
2. Add query caching (Redis)
3. Implement audit logging
4. Add data retention policies
5. Set up monitoring and alerting
6. Create scheduled maintenance tasks
7. Implement data validation hooks
