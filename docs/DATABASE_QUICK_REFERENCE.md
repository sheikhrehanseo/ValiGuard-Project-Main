# Database Quick Reference

## File Structure

```
backend/database/
├── __init__.py          # Package exports
├── models.py            # 5 SQLAlchemy models (20 KB)
├── db.py                # DatabaseManager & SeedData (20 KB)
├── alembic_env.py       # Migration configuration
└── valiguard.db       # SQLite database (auto-created)

backend/
├── manage_db.py         # CLI management tool
└── test_database.py     # Unit tests (45 tests)

docs/
├── DATABASE_SCHEMA.md       # Complete reference
└── DATABASE_INTEGRATION.md  # Flask examples
```

## Database Models

| Model | Purpose | Key Fields |
|-------|---------|-----------|
| **Bridge** | Cross-chain bridge | address, chain_name, status, created_at |
| **Transaction** | Cross-chain TX | tx_hash, bridge_id, value, status, anomaly_score, is_flagged |
| **AnomalyDetection** | ML detection | transaction_id, anomaly_score, severity, reason, model_version |
| **Validator** | QIE validators | address, name, stake_amount, uptime_percentage, is_active |
| **Alert** | System alerts | transaction_id, alert_type, severity, message, is_resolved |

## CLI Commands

```bash
# Initialize database
python backend/manage_db.py init

# Reset (drop & recreate)
python backend/manage_db.py reset

# Seed sample data
python backend/manage_db.py seed

# Export to CSV
python backend/manage_db.py export

# Backup database
python backend/manage_db.py backup

# Check health
python backend/manage_db.py health

# View statistics
python backend/manage_db.py stats

# Run migrations
python backend/manage_db.py migrate
```

## Python API

```python
from database import (
    get_db_manager,
    get_session,
    Bridge,
    Transaction,
    BridgeStatus,
    TransactionStatus,
    SeverityLevel,
)

# Initialize
db = get_db_manager()

# Session context manager
with db.get_session() as session:
    # Query
    bridges = session.query(Bridge).all()
    
    # Create
    bridge = Bridge(address="0x...", chain_name="QIE")
    session.add(bridge)
    
    # Update
    bridge.status = BridgeStatus.PAUSED
    
    # Delete
    session.delete(bridge)
    
    # Auto-commit on exit, auto-rollback on error

# Get statistics
stats = db.get_db_stats()

# Health check
health = db.health_check()

# Backup
backup_path = db.backup_db()

# Export
db.export_to_csv()
```

## Flask Integration

```python
from flask import Flask, request, jsonify
from database import get_db_manager, Bridge, BridgeStatus

app = Flask(__name__)

@app.route('/api/bridges', methods=['GET'])
def get_bridges():
    db = get_db_manager()
    with db.get_session() as session:
        bridges = session.query(Bridge).all()
        return {
            "status": "success",
            "data": [b.to_dict() for b in bridges]
        }

@app.route('/api/bridges', methods=['POST'])
def create_bridge():
    db = get_db_manager()
    data = request.get_json()
    
    with db.get_session() as session:
        bridge = Bridge(
            address=data['address'],
            chain_name=data['chain_name'],
            status=BridgeStatus.ACTIVE
        )
        session.add(bridge)
        session.commit()
        return {"status": "success", "data": bridge.to_dict()}, 201
```

## Query Examples

```python
# Filter
active_bridges = session.query(Bridge).filter(
    Bridge.status == BridgeStatus.ACTIVE
).all()

# Order
recent_tx = session.query(Transaction).order_by(
    Transaction.timestamp.desc()
).limit(10).all()

# Join
anomalies_with_tx = session.query(
    AnomalyDetection
).join(Transaction).filter(
    AnomalyDetection.severity == SeverityLevel.CRITICAL
).all()

# Group count
from sqlalchemy import func
tx_per_bridge = session.query(
    Bridge.id,
    func.count(Transaction.id)
).join(Transaction).group_by(Bridge.id).all()

# Count
total_bridges = session.query(Bridge).count()

# Get one
bridge = session.query(Bridge).filter_by(id=1).first()

# Get with relationships
from sqlalchemy.orm import joinedload
bridge = session.query(Bridge).options(
    joinedload(Bridge.transactions)
).first()
```

## Enumerations

```python
# BridgeStatus
ACTIVE = "active"
PAUSED = "paused"
INACTIVE = "inactive"

# TransactionStatus
PENDING = "pending"
CONFIRMED = "confirmed"
FAILED = "failed"

# SeverityLevel
LOW = "low"
MEDIUM = "medium"
HIGH = "high"
CRITICAL = "critical"

# AlertType
ANOMALY = "anomaly"
TIMEOUT = "timeout"
ERROR = "error"

# AlertSeverity
INFO = "info"
WARNING = "warning"
ERROR = "error"
CRITICAL = "critical"
```

## Seed Data

```python
from database import SeedData

with db.get_session() as session:
    # Seed all data types
    counts = SeedData.seed_all(session)
    # Returns: {bridges: 3, validators: 5, transactions: 15, ...}
    
    # Or seed individually
    SeedData.seed_bridges(session, count=5)
    SeedData.seed_validators(session, count=10)
    SeedData.seed_transactions(session, bridges, count=20)
    SeedData.seed_anomalies(session, transactions)
    SeedData.seed_alerts(session, transactions)
```

## Configuration (.env)

```env
# Development (SQLite - default)
DATABASE_URL=sqlite:///valiguard.db

# Production (PostgreSQL)
DATABASE_URL=postgresql://user:password@localhost:5432/valiguard
```

## Relationships Diagram

```
Bridge (1) ─────┬─→ Transaction (M)
                      ├─→ AnomalyDetection (M)
                      └─→ Alert (M)

Validator (Standalone)
```

## Performance Tips

1. **Use eager loading** for relationships
   ```python
   from sqlalchemy.orm import joinedload
   bridges = session.query(Bridge).options(
       joinedload(Bridge.transactions)
   ).all()
   ```

2. **Batch inserts** for large datasets
   ```python
   session.bulk_save_objects(list_of_objects)
   session.commit()
   ```

3. **Index key columns** (already done in models)
   - address, tx_hash, timestamp, created_at

4. **Enable query caching** in production

5. **Use connection pooling** (PostgreSQL)

## Error Handling

```python
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

try:
    with db.get_session() as session:
        # Operations
        pass
except IntegrityError:
    # Handle duplicate keys, constraints
    pass
except SQLAlchemyError as e:
    # Handle database errors
    pass
```

## Testing

```bash
# Run all database tests
pytest backend/test_database.py -v

# Run specific test
pytest backend/test_database.py::TestBridgeModel -v

# With coverage
pytest backend/test_database.py --cov=database
```

## Database Size

- SQLite development: ~1-5 MB (depending on data)
- Each model table: ~100-500 KB with 1000 records

## Backup & Export

```python
# Backup database
backup_path = db.backup_db(backup_dir="backups")

# Export data
db.export_to_csv(export_dir="exports")

# Files created
# - backups/valiguard_20251204_214443.db
# - exports/bridges.csv
# - exports/transactions.csv
# - exports/validators.csv
# - exports/alerts.csv
```

## Common Issues

| Issue | Solution |
|-------|----------|
| Table not found | Run `python backend/manage_db.py init` |
| Import error | Ensure venv has sqlalchemy installed |
| Lock issues (SQLite) | Switch to PostgreSQL or use WAL mode |
| Slow queries | Add indexes, enable query logging |
| Connection timeout | Check DATABASE_URL in .env |

## Production Checklist

- [ ] Switch to PostgreSQL
- [ ] Configure connection pooling
- [ ] Enable SSL/TLS
- [ ] Set up backups (daily)
- [ ] Enable query logging
- [ ] Configure timeout handling
- [ ] Set up read replicas
- [ ] Implement caching
- [ ] Add monitoring/alerting
- [ ] Test migrations

## Resources

- **Schema**: `docs/DATABASE_SCHEMA.md`
- **Integration**: `docs/DATABASE_INTEGRATION.md`
- **Tests**: `backend/test_database.py`
- **CLI**: `python backend/manage_db.py --help`
