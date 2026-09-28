# ValiGuard AI - Database Integration Guide

## Overview

This guide explains how to integrate the SQLAlchemy database models into the Flask API and use them in endpoints.

## Quick Start

### 1. Initialize Database

```bash
# Initialize database and create tables
python backend/manage_db.py init

# Seed with sample data
python backend/manage_db.py seed

# Check health
python backend/manage_db.py health

# View statistics
python backend/manage_db.py stats
```

### 2. Import Database Components

```python
from database import (
    get_db_manager,
    get_session,
    Bridge,
    Transaction,
    AnomalyDetection,
    Validator,
    Alert,
    BridgeStatus,
    TransactionStatus,
    SeverityLevel,
    AlertType,
    AlertSeverity,
)
```

### 3. Use Sessions in Flask Routes

```python
@app.route('/api/bridges', methods=['GET'])
def get_bridges():
    """Get all bridges from database."""
    db = get_db_manager()
    with db.get_session() as session:
        bridges = session.query(Bridge).all()
        return {
            "status": "success",
            "data": [b.to_dict() for b in bridges]
        }
```

## Common Query Patterns

### Getting Data

```python
# Get all records
bridges = session.query(Bridge).all()

# Get one record
bridge = session.query(Bridge).filter_by(id=1).first()

# Get by custom condition
active_bridges = session.query(Bridge).filter(
    Bridge.status == BridgeStatus.ACTIVE
).all()

# Get with ordering
recent_tx = session.query(Transaction).order_by(
    Transaction.timestamp.desc()
).limit(10).all()

# Get with multiple filters
flagged_recent = session.query(Transaction).filter(
    Transaction.is_flagged == True,
    Transaction.timestamp >= datetime.utcnow() - timedelta(hours=24)
).all()
```

### Creating Records

```python
# Create a new bridge
new_bridge = Bridge(
    address="0xabc123",
    chain_name="QIE",
    status=BridgeStatus.ACTIVE
)
session.add(new_bridge)
session.commit()

# Create with relationships
bridge = session.query(Bridge).first()
tx = Transaction(
    tx_hash="0xdef456",
    bridge_id=bridge.id,
    source_chain="Ethereum",
    destination_chain="Polygon",
    value=100.0,
    sender="0xsender",
    receiver="0xreceiver"
)
session.add(tx)
session.commit()
```

### Updating Records

```python
# Update single record
bridge = session.query(Bridge).filter_by(id=1).first()
bridge.status = BridgeStatus.PAUSED
session.commit()

# Update multiple records
session.query(Transaction).filter(
    Transaction.status == TransactionStatus.PENDING
).update({
    Transaction.status: TransactionStatus.CONFIRMED
})
session.commit()
```

### Deleting Records

```python
# Delete single record
bridge = session.query(Bridge).filter_by(id=1).first()
session.delete(bridge)
session.commit()

# Delete multiple records
session.query(Alert).filter(Alert.is_resolved == True).delete()
session.commit()
```

## Flask Endpoint Examples

### 1. Get All Bridges with Statistics

```python
@app.route('/api/bridges', methods=['GET'])
def get_bridges():
    """Get all bridges with transaction counts."""
    try:
        db = get_db_manager()
        with db.get_session() as session:
            bridges = session.query(Bridge).all()
            result = []
            for bridge in bridges:
                data = bridge.to_dict()
                data['transaction_count'] = len(bridge.transactions)
                result.append(data)
            return {
                "status": "success",
                "count": len(result),
                "data": result
            }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500
```

### 2. Get Recent Transactions with Anomalies

```python
@app.route('/api/transactions/recent', methods=['GET'])
def get_recent_transactions():
    """Get recent transactions with anomaly information."""
    try:
        hours = request.args.get('hours', 24, type=int)
        db = get_db_manager()
        
        with db.get_session() as session:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            transactions = session.query(Transaction).filter(
                Transaction.timestamp >= cutoff
            ).order_by(Transaction.timestamp.desc()).all()
            
            result = []
            for tx in transactions:
                data = tx.to_dict(include_anomalies=True, include_alerts=True)
                result.append(data)
            
            return {
                "status": "success",
                "count": len(result),
                "data": result
            }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500
```

### 3. Get Flagged Transactions

```python
@app.route('/api/transactions/flagged', methods=['GET'])
def get_flagged_transactions():
    """Get flagged transactions requiring review."""
    try:
        db = get_db_manager()
        
        with db.get_session() as session:
            flagged = session.query(Transaction).filter(
                Transaction.is_flagged == True
            ).order_by(Transaction.created_at.desc()).all()
            
            return {
                "status": "success",
                "count": len(flagged),
                "data": [tx.to_dict() for tx in flagged]
            }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500
```

### 4. Get Anomalies by Severity

```python
@app.route('/api/anomalies/severity/<severity>', methods=['GET'])
def get_anomalies_by_severity(severity):
    """Get anomalies filtered by severity level."""
    try:
        severity_level = SeverityLevel[severity.upper()]
        db = get_db_manager()
        
        with db.get_session() as session:
            anomalies = session.query(AnomalyDetection).filter(
                AnomalyDetection.severity == severity_level
            ).order_by(AnomalyDetection.detected_at.desc()).all()
            
            return {
                "status": "success",
                "severity": severity,
                "count": len(anomalies),
                "data": [a.to_dict() for a in anomalies]
            }, 200
    except KeyError:
        return {
            "status": "error",
            "message": f"Invalid severity: {severity}",
            "valid_values": [s.value for s in SeverityLevel]
        }, 400
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500
```

### 5. Get Active Validators with Stats

```python
@app.route('/api/validators/active', methods=['GET'])
def get_active_validators():
    """Get active validators sorted by stake amount."""
    try:
        db = get_db_manager()
        
        with db.get_session() as session:
            validators = session.query(Validator).filter(
                Validator.is_active == True
            ).order_by(Validator.stake_amount.desc()).all()
            
            return {
                "status": "success",
                "count": len(validators),
                "total_stake": sum(v.stake_amount for v in validators),
                "avg_uptime": sum(v.uptime_percentage for v in validators) / len(validators) if validators else 0,
                "data": [v.to_dict() for v in validators]
            }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500
```

### 6. Get Unresolved Alerts

```python
@app.route('/api/alerts/unresolved', methods=['GET'])
def get_unresolved_alerts():
    """Get unresolved alerts requiring attention."""
    try:
        db = get_db_manager()
        
        with db.get_session() as session:
            alerts = session.query(Alert).filter(
                Alert.is_resolved == False
            ).order_by(Alert.created_at.desc()).all()
            
            # Group by severity
            by_severity = {}
            for alert in alerts:
                severity = alert.severity.value
                if severity not in by_severity:
                    by_severity[severity] = []
                by_severity[severity].append(alert.to_dict())
            
            return {
                "status": "success",
                "total_unresolved": len(alerts),
                "by_severity": by_severity
            }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500
```

### 7. Create Transaction from API

```python
@app.route('/api/transactions', methods=['POST'])
def create_transaction():
    """Create a new transaction in the database."""
    try:
        data = request.get_json()
        db = get_db_manager()
        
        with db.get_session() as session:
            # Validate bridge exists
            bridge = session.query(Bridge).filter_by(
                id=data.get('bridge_id')
            ).first()
            if not bridge:
                return {
                    "status": "error",
                    "message": "Bridge not found"
                }, 404
            
            # Create transaction
            tx = Transaction(
                tx_hash=data.get('tx_hash'),
                bridge_id=data.get('bridge_id'),
                source_chain=data.get('source_chain'),
                destination_chain=data.get('destination_chain'),
                value=data.get('value'),
                sender=data.get('sender'),
                receiver=data.get('receiver'),
                status=TransactionStatus.PENDING,
                anomaly_score=data.get('anomaly_score', 0.0),
                is_flagged=data.get('is_flagged', False)
            )
            session.add(tx)
            session.commit()
            
            return {
                "status": "success",
                "message": "Transaction created",
                "data": tx.to_dict()
            }, 201
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500
```

### 8. Get Database Statistics

```python
@app.route('/api/stats/database', methods=['GET'])
def get_database_stats():
    """Get database statistics."""
    try:
        db = get_db_manager()
        stats = db.get_db_stats()
        health = db.health_check()
        
        return {
            "status": "success",
            "health": health,
            "statistics": stats
        }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500
```

## Error Handling

Always use try-except blocks and handle database errors gracefully:

```python
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

@app.route('/api/bridge', methods=['POST'])
def create_bridge():
    try:
        data = request.get_json()
        db = get_db_manager()
        
        with db.get_session() as session:
            bridge = Bridge(
                address=data['address'],
                chain_name=data['chain_name']
            )
            session.add(bridge)
            session.commit()
            
            return {
                "status": "success",
                "data": bridge.to_dict()
            }, 201
            
    except IntegrityError as e:
        return {
            "status": "error",
            "message": "Bridge address already exists"
        }, 409
    except SQLAlchemyError as e:
        return {
            "status": "error",
            "message": f"Database error: {str(e)}"
        }, 500
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }, 500
```

## Performance Tips

### 1. Lazy Loading vs Eager Loading

```python
# Lazy loading (default) - queries on access
bridge = session.query(Bridge).first()
# This triggers a new query:
transactions = bridge.transactions

# Eager loading - query with relationships
from sqlalchemy.orm import joinedload
bridge = session.query(Bridge).options(
    joinedload(Bridge.transactions)
).first()
# No additional query needed
transactions = bridge.transactions
```

### 2. Batch Operations

```python
# Create many records efficiently
bridges = [
    Bridge(address=f"0x{i}", chain_name="QIE")
    for i in range(1000)
]
session.bulk_save_objects(bridges)
session.commit()
```

### 3. Query Optimization

```python
# Only select needed columns
from sqlalchemy import select

result = session.query(Bridge.id, Bridge.address).all()

# Use count() for counts
count = session.query(Transaction).count()
```

## Database Backup and Export

### Backup Before Updates

```python
db = get_db_manager()
backup_path = db.backup_db()
print(f"Backup created: {backup_path}")
```

### Export to CSV

```python
db = get_db_manager()
db.export_to_csv(export_dir="data_exports")
```

## Testing

Run the database test suite:

```bash
pytest backend/test_database.py -v
```

## Migration Management

### Create a Migration

```bash
alembic revision --autogenerate -m "Add new field"
```

### Apply Migrations

```bash
alembic upgrade head
```

### Rollback

```bash
alembic downgrade -1
```

## Production Checklist

- [ ] Use PostgreSQL instead of SQLite
- [ ] Configure connection pooling
- [ ] Enable SSL for database connections
- [ ] Set up automated backups
- [ ] Enable query logging for monitoring
- [ ] Implement connection timeout handling
- [ ] Use read replicas for scaling
- [ ] Set up proper indexes on all queries
- [ ] Implement query result caching
- [ ] Set up alerting for database issues

## Next Steps

1. Integrate database models with existing Flask API
2. Add database query caching with Redis
3. Implement audit logging for data changes
4. Set up scheduled database maintenance
5. Add monitoring and alerting for database health
6. Implement data retention policies
7. Add full-text search capabilities
