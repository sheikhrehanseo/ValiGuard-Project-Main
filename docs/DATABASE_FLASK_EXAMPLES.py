"""
Example: Integrating ValiGuard AI Database with Flask API

This file demonstrates how to use the SQLAlchemy database models
in Flask endpoints. Copy these patterns into your app.py
"""

from flask import Flask, request, jsonify
from datetime import datetime, timedelta
from database import (
    get_db_manager,
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
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

app = Flask(__name__)
db = get_db_manager()


# ============================================================================
# BRIDGE ENDPOINTS
# ============================================================================

@app.route('/api/bridges', methods=['GET'])
def get_bridges():
    """Get all bridges with transaction counts."""
    try:
        with db.get_session() as session:
            bridges = session.query(Bridge).all()
            result = []
            for bridge in bridges:
                data = bridge.to_dict()
                data['transaction_count'] = len(bridge.transactions)
                data['transactions'] = [t.to_dict() for t in bridge.transactions]
                result.append(data)
            
            return {
                "status": "success",
                "count": len(result),
                "data": result
            }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route('/api/bridges/<int:bridge_id>', methods=['GET'])
def get_bridge(bridge_id):
    """Get specific bridge with all relationships."""
    try:
        with db.get_session() as session:
            bridge = session.query(Bridge).filter_by(id=bridge_id).first()
            
            if not bridge:
                return {"status": "error", "message": "Bridge not found"}, 404
            
            return {
                "status": "success",
                "data": bridge.to_dict(include_transactions=True)
            }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route('/api/bridges', methods=['POST'])
def create_bridge():
    """Create new bridge."""
    try:
        data = request.get_json()
        
        # Validate required fields
        required = ['address', 'chain_name']
        if not all(k in data for k in required):
            return {
                "status": "error",
                "message": f"Missing required fields: {required}"
            }, 400
        
        with db.get_session() as session:
            bridge = Bridge(
                address=data['address'],
                chain_name=data['chain_name'],
                status=BridgeStatus[data.get('status', 'ACTIVE').upper()]
            )
            session.add(bridge)
            session.commit()
            
            return {
                "status": "success",
                "message": "Bridge created",
                "data": bridge.to_dict()
            }, 201
    
    except IntegrityError:
        return {
            "status": "error",
            "message": "Bridge address already exists"
        }, 409
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


# ============================================================================
# TRANSACTION ENDPOINTS
# ============================================================================

@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    """Get recent transactions with optional filtering."""
    try:
        hours = request.args.get('hours', 24, type=int)
        is_flagged = request.args.get('flagged', None)
        
        with db.get_session() as session:
            query = session.query(Transaction)
            
            # Filter by time
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            query = query.filter(Transaction.timestamp >= cutoff)
            
            # Filter by flagged status
            if is_flagged is not None:
                query = query.filter(Transaction.is_flagged == (is_flagged.lower() == 'true'))
            
            transactions = query.order_by(Transaction.timestamp.desc()).all()
            
            return {
                "status": "success",
                "count": len(transactions),
                "timeframe": f"Last {hours} hours",
                "data": [tx.to_dict() for tx in transactions]
            }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route('/api/transactions/flagged', methods=['GET'])
def get_flagged_transactions():
    """Get flagged transactions requiring review."""
    try:
        with db.get_session() as session:
            flagged = session.query(Transaction).filter(
                Transaction.is_flagged == True
            ).order_by(Transaction.created_at.desc()).all()
            
            return {
                "status": "success",
                "count": len(flagged),
                "data": [tx.to_dict(include_anomalies=True) for tx in flagged]
            }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route('/api/transactions', methods=['POST'])
def create_transaction():
    """Create new transaction."""
    try:
        data = request.get_json()
        
        required = ['tx_hash', 'bridge_id', 'source_chain', 'destination_chain',
                   'value', 'sender', 'receiver']
        if not all(k in data for k in required):
            return {
                "status": "error",
                "message": f"Missing required fields: {required}"
            }, 400
        
        with db.get_session() as session:
            # Verify bridge exists
            bridge = session.query(Bridge).filter_by(id=data['bridge_id']).first()
            if not bridge:
                return {
                    "status": "error",
                    "message": "Bridge not found"
                }, 404
            
            tx = Transaction(
                tx_hash=data['tx_hash'],
                bridge_id=data['bridge_id'],
                source_chain=data['source_chain'],
                destination_chain=data['destination_chain'],
                value=float(data['value']),
                sender=data['sender'],
                receiver=data['receiver'],
                status=TransactionStatus[data.get('status', 'PENDING').upper()],
                anomaly_score=float(data.get('anomaly_score', 0.0)),
                is_flagged=data.get('is_flagged', False)
            )
            session.add(tx)
            session.commit()
            
            return {
                "status": "success",
                "message": "Transaction created",
                "data": tx.to_dict()
            }, 201
    
    except IntegrityError:
        return {
            "status": "error",
            "message": "Transaction hash already exists"
        }, 409
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route('/api/transactions/<int:tx_id>', methods=['GET'])
def get_transaction(tx_id):
    """Get specific transaction with all relationships."""
    try:
        with db.get_session() as session:
            tx = session.query(Transaction).filter_by(id=tx_id).first()
            
            if not tx:
                return {"status": "error", "message": "Transaction not found"}, 404
            
            return {
                "status": "success",
                "data": tx.to_dict(include_anomalies=True, include_alerts=True)
            }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


# ============================================================================
# ANOMALY ENDPOINTS
# ============================================================================

@app.route('/api/anomalies', methods=['GET'])
def get_anomalies():
    """Get anomalies with optional severity filtering."""
    try:
        severity = request.args.get('severity', None)
        
        with db.get_session() as session:
            query = session.query(AnomalyDetection)
            
            if severity:
                severity_level = SeverityLevel[severity.upper()]
                query = query.filter(AnomalyDetection.severity == severity_level)
            
            anomalies = query.order_by(AnomalyDetection.detected_at.desc()).all()
            
            return {
                "status": "success",
                "count": len(anomalies),
                "severity_filter": severity,
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


@app.route('/api/anomalies/critical', methods=['GET'])
def get_critical_anomalies():
    """Get critical severity anomalies."""
    try:
        with db.get_session() as session:
            critical = session.query(AnomalyDetection).filter(
                AnomalyDetection.severity == SeverityLevel.CRITICAL
            ).order_by(AnomalyDetection.detected_at.desc()).all()
            
            return {
                "status": "success",
                "count": len(critical),
                "data": [a.to_dict() for a in critical]
            }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


# ============================================================================
# VALIDATOR ENDPOINTS
# ============================================================================

@app.route('/api/validators', methods=['GET'])
def get_validators():
    """Get all validators with statistics."""
    try:
        active_only = request.args.get('active_only', 'false').lower() == 'true'
        
        with db.get_session() as session:
            query = session.query(Validator)
            
            if active_only:
                query = query.filter(Validator.is_active == True)
            
            validators = query.order_by(Validator.stake_amount.desc()).all()
            
            total_stake = sum(v.stake_amount for v in validators)
            avg_uptime = sum(v.uptime_percentage for v in validators) / len(validators) if validators else 0
            
            return {
                "status": "success",
                "count": len(validators),
                "total_stake": total_stake,
                "average_uptime": round(avg_uptime, 2),
                "data": [v.to_dict() for v in validators]
            }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route('/api/validators/<int:validator_id>', methods=['GET'])
def get_validator(validator_id):
    """Get specific validator."""
    try:
        with db.get_session() as session:
            validator = session.query(Validator).filter_by(id=validator_id).first()
            
            if not validator:
                return {"status": "error", "message": "Validator not found"}, 404
            
            return {
                "status": "success",
                "data": validator.to_dict()
            }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


# ============================================================================
# ALERT ENDPOINTS
# ============================================================================

@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    """Get alerts with optional filtering."""
    try:
        resolved_only = request.args.get('resolved_only', 'false').lower() == 'true'
        
        with db.get_session() as session:
            query = session.query(Alert)
            
            if resolved_only:
                query = query.filter(Alert.is_resolved == True)
            else:
                query = query.filter(Alert.is_resolved == False)
            
            alerts = query.order_by(Alert.created_at.desc()).all()
            
            return {
                "status": "success",
                "count": len(alerts),
                "data": [a.to_dict() for a in alerts]
            }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route('/api/alerts/critical', methods=['GET'])
def get_critical_alerts():
    """Get critical alerts."""
    try:
        with db.get_session() as session:
            critical = session.query(Alert).filter(
                Alert.severity == AlertSeverity.CRITICAL,
                Alert.is_resolved == False
            ).order_by(Alert.created_at.desc()).all()
            
            return {
                "status": "success",
                "count": len(critical),
                "data": [a.to_dict() for a in critical]
            }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


# ============================================================================
# STATISTICS & MONITORING
# ============================================================================

@app.route('/api/stats/database', methods=['GET'])
def get_database_stats():
    """Get database statistics."""
    try:
        stats = db.get_db_stats()
        health = db.health_check()
        
        return {
            "status": "success",
            "health": health,
            "statistics": stats
        }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route('/api/stats/summary', methods=['GET'])
def get_summary_stats():
    """Get summary statistics dashboard."""
    try:
        with db.get_session() as session:
            stats = {
                "bridges": {
                    "total": session.query(Bridge).count(),
                    "active": session.query(Bridge).filter(
                        Bridge.status == BridgeStatus.ACTIVE
                    ).count(),
                },
                "transactions": {
                    "total": session.query(Transaction).count(),
                    "pending": session.query(Transaction).filter(
                        Transaction.status == TransactionStatus.PENDING
                    ).count(),
                    "flagged": session.query(Transaction).filter(
                        Transaction.is_flagged == True
                    ).count(),
                },
                "anomalies": {
                    "total": session.query(AnomalyDetection).count(),
                    "critical": session.query(AnomalyDetection).filter(
                        AnomalyDetection.severity == SeverityLevel.CRITICAL
                    ).count(),
                },
                "validators": {
                    "total": session.query(Validator).count(),
                    "active": session.query(Validator).filter(
                        Validator.is_active == True
                    ).count(),
                },
                "alerts": {
                    "total": session.query(Alert).count(),
                    "unresolved": session.query(Alert).filter(
                        Alert.is_resolved == False
                    ).count(),
                }
            }
            
            return {"status": "success", "data": stats}, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
