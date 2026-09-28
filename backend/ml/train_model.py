"""
Isolation Forest model training script for ValiGuard AI.
Generates synthetic transaction data, trains model, and evaluates on anomalies.
"""

import json
import os
from datetime import datetime, timedelta
from typing import List, Tuple
import numpy as np
from dataclasses import dataclass
from sklearn.ensemble import IsolationForest
from sklearn.metrics import precision_score, recall_score, f1_score
import joblib

from feature_extraction import FeatureExtractor


@dataclass
class MockTransaction:
    """Mock transaction for training without database dependency."""
    value: float
    sender: str
    timestamp: datetime


def generate_normal_transactions(
    n_samples: int = 1500,
    seed: int = 42
) -> List[MockTransaction]:
    """
    Generate normal transaction data with business-hours patterns.
    
    Args:
        n_samples: Number of normal transactions to generate
        seed: Random seed for reproducibility
    
    Returns:
        List of MockTransaction objects
    """
    np.random.seed(seed)
    transactions = []
    
    # Random senders
    senders = [f"0x{np.random.randint(1000, 9999):04x}" for _ in range(50)]
    
    base_time = datetime(2024, 1, 1, 0, 0, 0)
    
    for i in range(n_samples):
        # Business hours weighted (8 AM - 6 PM)
        hour_weights = np.zeros(24)
        hour_weights[8:18] = 3.0  # Business hours
        hour_weights[12:14] = 5.0  # Peak at noon
        hour_weights[0:6] = 0.2  # Low night activity
        hour_weights[18:22] = 1.5  # Evening
        hour_weights[22:24] = 0.5  # Late night
        hour_weights = hour_weights / hour_weights.sum()
        
        hour = int(np.random.choice(24, p=hour_weights))
        minute = int(np.random.randint(0, 60))
        second = int(np.random.randint(0, 60))
        
        # Day distribution (weekdays heavier)
        day_weights = np.array([1.0, 2.0, 2.0, 2.0, 2.0, 1.5, 0.5])
        day_weights = day_weights / day_weights.sum()
        day_offset = int(np.random.choice(7, p=day_weights))
        
        timestamp = base_time + timedelta(
            days=day_offset,
            hours=hour,
            minutes=minute,
            seconds=second
        )
        
        # Value: log-normal distribution (typical for transactions)
        value = np.random.lognormal(mean=5, sigma=1.5)
        value = round(min(max(value, 1.0), 50000.0), 2)
        
        sender = np.random.choice(senders)
        
        transactions.append(MockTransaction(
            value=value,
            sender=sender,
            timestamp=timestamp
        ))
    
    return transactions


def generate_anomaly_transactions(
    n_samples: int = 100,
    seed: int = 123
) -> List[MockTransaction]:
    """
    Generate anomalous transactions with spikes and unusual patterns.
    
    Args:
        n_samples: Number of anomalies to generate
        seed: Random seed
    
    Returns:
        List of anomalous MockTransaction objects
    """
    np.random.seed(seed)
    transactions = []
    
    senders = [f"0x{np.random.randint(1000, 9999):04x}" for _ in range(20)]
    base_time = datetime(2024, 1, 1, 0, 0, 0)
    
    for i in range(n_samples):
        # Anomaly type: randomly choose
        anomaly_type = np.random.choice(
            ["value_spike", "odd_hours", "both"], 
            p=[0.4, 0.4, 0.2]
        )
        
        if anomaly_type in ["value_spike", "both"]:
            # 10x value spike
            value = np.random.uniform(20000, 150000)
        else:
            value = np.random.lognormal(mean=5, sigma=1.5)
            value = round(min(max(value, 1.0), 5000.0), 2)
        
        if anomaly_type in ["odd_hours", "both"]:
            # 3 AM - 5 AM or 11 PM - 1 AM
            hour = int(np.random.choice([1, 2, 3, 4, 23, 0]))
        else:
            hour = int(np.random.randint(8, 18))
        
        minute = int(np.random.randint(0, 60))
        timestamp = base_time + timedelta(
            days=int(np.random.randint(0, 7)),
            hours=hour,
            minutes=minute
        )
        
        sender = np.random.choice(senders)
        
        transactions.append(MockTransaction(
            value=round(value, 2),
            sender=sender,
            timestamp=timestamp
        ))
    
    return transactions


def train_isolation_forest(
    normal_features: np.ndarray,
    contamination: float = 0.05,
    random_state: int = 42
) -> IsolationForest:
    """
    Train Isolation Forest on normal transaction features.
    
    Args:
        normal_features: Feature matrix from normal transactions
        contamination: Expected proportion of anomalies
        random_state: Random seed
    
    Returns:
        Trained IsolationForest model
    """
    model = IsolationForest(
        n_estimators=150,
        max_samples='auto',
        contamination=contamination,
        random_state=random_state,
        n_jobs=-1
    )
    
    model.fit(normal_features)
    return model


def evaluate_model(
    model: IsolationForest,
    normal_features: np.ndarray,
    anomaly_features: np.ndarray
) -> dict:
    """
    Evaluate model on normal and anomaly data.
    
    Args:
        model: Trained IsolationForest
        normal_features: Features from normal transactions
        anomaly_features: Features from anomalous transactions
    
    Returns:
        Dictionary of evaluation metrics
    """
    # Predict: -1 = anomaly, 1 = normal
    normal_preds = model.predict(normal_features)
    anomaly_preds = model.predict(anomaly_features)
    
    # True negatives (normal correctly identified)
    tn = np.sum(normal_preds == 1)
    fp = np.sum(normal_preds == -1)
    
    # True positives (anomalies correctly identified)
    tp = np.sum(anomaly_preds == -1)
    fn = np.sum(anomaly_preds == 1)
    
    # Metrics
    accuracy = (tp + tn) / (tp + tn + fp + fn)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    
    # False positive/negative rates
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0
    
    return {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1, 4),
        "false_positive_rate": round(fpr, 4),
        "false_negative_rate": round(fnr, 4),
        "true_positives": int(tp),
        "true_negatives": int(tn),
        "false_positives": int(fp),
        "false_negatives": int(fn),
        "total_normal": len(normal_features),
        "total_anomalies": len(anomaly_features)
    }


def save_model(
    model: IsolationForest,
    extractor: FeatureExtractor,
    metrics: dict,
    output_dir: str = "backend/ml/models"
) -> Tuple[str, str]:
    """
    Save trained model and metrics to disk.
    
    Args:
        model: Trained model
        extractor: Fitted feature extractor
        metrics: Evaluation metrics
        output_dir: Output directory
    
    Returns:
        Tuple of (model_path, metrics_path)
    """
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    model_path = os.path.join(output_dir, f"isolation_forest_{timestamp}.joblib")
    metrics_path = os.path.join(output_dir, f"metrics_{timestamp}.json")
    
    # Save model with metadata
    joblib.dump({
        "model": model,
        "feature_names": extractor.get_feature_names(),
        "normalization_percentile": extractor.normalization_percentile,
        "trained_at": datetime.utcnow().isoformat()
    }, model_path)
    
    # Save metrics
    metrics["model_version"] = timestamp
    metrics["trained_at"] = datetime.utcnow().isoformat()
    
    with open(metrics_path, 'w') as f:
        json.dump(metrics, f, indent=2)
    
    # Also save latest versions
    latest_model = os.path.join(output_dir, "isolation_forest_latest.joblib")
    latest_metrics = os.path.join(output_dir, "metrics_latest.json")
    
    joblib.dump({
        "model": model,
        "feature_names": extractor.get_feature_names(),
        "normalization_percentile": extractor.normalization_percentile,
        "trained_at": datetime.utcnow().isoformat()
    }, latest_model)
    
    with open(latest_metrics, 'w') as f:
        json.dump(metrics, f, indent=2)
    
    return model_path, metrics_path


def main():
    """Main training pipeline."""
    print("=" * 60)
    print("ValiGuard AI - Isolation Forest Training")
    print("=" * 60)
    
    # Generate data
    print("\n[1/5] Generating synthetic normal transactions...")
    normal_txs = generate_normal_transactions(n_samples=1500)
    print(f"      Generated {len(normal_txs)} normal transactions")
    
    print("\n[2/5] Generating synthetic anomalies...")
    anomaly_txs = generate_anomaly_transactions(n_samples=100)
    print(f"      Generated {len(anomaly_txs)} anomalous transactions")
    
    # Extract features
    print("\n[3/5] Extracting features...")
    extractor = FeatureExtractor(rolling_window_hours=24, history_size=2000)
    
    normal_features = extractor.extract_batch(normal_txs)
    print(f"      Normal features shape: {normal_features.shape}")
    
    # Do NOT reset the extractor here: anomalies must be scored against the
    # normal baseline (rolling history + value percentiles) so they occupy the
    # same feature space as the normal samples. Resetting would empty the
    # history and force fallback log1p scaling, degrading the model boundary.
    anomaly_features = extractor.extract_batch(anomaly_txs)
    print(f"      Anomaly features shape: {anomaly_features.shape}")
    
    # Train model
    print("\n[4/5] Training Isolation Forest...")
    model = train_isolation_forest(normal_features, contamination=0.05)
    print("      Model trained successfully")
    
    # Evaluate
    print("\n[5/5] Evaluating model...")
    metrics = evaluate_model(model, normal_features, anomaly_features)
    
    print("\n" + "-" * 60)
    print("EVALUATION METRICS")
    print("-" * 60)
    print(f"  Accuracy:  {metrics['accuracy']:.2%}")
    print(f"  Precision: {metrics['precision']:.2%}")
    print(f"  Recall:    {metrics['recall']:.2%}")
    print(f"  F1 Score:  {metrics['f1_score']:.2%}")
    print(f"\n  False Positive Rate: {metrics['false_positive_rate']:.2%}")
    print(f"  False Negative Rate: {metrics['false_negative_rate']:.2%}")
    print(f"\n  Confusion Matrix:")
    print(f"    TP: {metrics['true_positives']}  |  FN: {metrics['false_negatives']}")
    print(f"    FP: {metrics['false_positives']}  |  TN: {metrics['true_negatives']}")
    
    # Save model
    model_path, metrics_path = save_model(model, extractor, metrics)
    print(f"\n[OK] Model saved to: {model_path}")
    print(f"[OK] Metrics saved to: {metrics_path}")
    
    print("\n" + "=" * 60)
    print("Training complete!")
    print("=" * 60)
    
    return model, extractor, metrics


if __name__ == "__main__":
    main()
