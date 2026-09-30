"""
Anomaly scoring module for ValiGuard AI.
Loads trained Isolation Forest model and provides scoring interface.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Optional, Any
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try imports with graceful fallback
try:
    import joblib
    JOBLIB_AVAILABLE = True
except ImportError:
    JOBLIB_AVAILABLE = False
    logger.warning("joblib not available, model loading disabled")

try:
    # Preferred: package-qualified import (works regardless of CWD/sys.path)
    from ml.feature_extraction import FeatureExtractor
    FEATURE_EXTRACTION_AVAILABLE = True
except ImportError:
    # Fallback: relative import for legacy invocation where backend/ is on sys.path
    try:
        from feature_extraction import FeatureExtractor
        FEATURE_EXTRACTION_AVAILABLE = True
    except ImportError:
        FEATURE_EXTRACTION_AVAILABLE = False
        logger.warning("feature_extraction not available")

# Canonical 4-tier severity scale (single source of truth, shared with app.py
# and the ingestion worker).
from core.severity import severity_from_score


class AnomalyModel:
    """
    Anomaly detection model wrapper for transaction scoring.
    
    Loads persisted Isolation Forest model and provides scoring interface.
    Falls back gracefully if model not found.
    """
    
    def __init__(self, model_dir: str = "backend/ml/models"):
        """
        Initialize anomaly model.
        
        Args:
            model_dir: Directory containing model files
        """
        self.model_dir = model_dir
        self.model: Optional[Any] = None
        self.feature_extractor: Optional[FeatureExtractor] = None
        self.model_version: str = "untrained"
        self.model_metadata: Dict[str, Any] = {}
        
        self._load_model()
    
    def _load_model(self) -> bool:
        """
        Load persisted model from disk.
        
        Returns:
            True if model loaded successfully, False otherwise
        """
        if not JOBLIB_AVAILABLE:
            logger.warning("Cannot load model: joblib not available")
            return False
        
        if not FEATURE_EXTRACTION_AVAILABLE:
            logger.warning("Cannot load model: feature_extraction not available")
            return False
        
        # Try latest model first, then search for timestamped models
        model_path = os.path.join(self.model_dir, "isolation_forest_latest.joblib")
        
        if not os.path.exists(model_path):
            # Search for any timestamped model
            if os.path.exists(self.model_dir):
                models = [f for f in os.listdir(self.model_dir) 
                         if f.startswith("isolation_forest_") and f.endswith(".joblib")
                         and f != "isolation_forest_latest.joblib"]
                if models:
                    models.sort(reverse=True)  # Most recent first
                    model_path = os.path.join(self.model_dir, models[0])
        
        if not os.path.exists(model_path):
            logger.warning(
                f"No trained model found in {self.model_dir}. "
                "Run train_model.py first. Scoring will use fallback defaults."
            )
            self._init_fallback()
            return False
        
        try:
            loaded_data = joblib.load(model_path)
            
            # Handle both wrapped and raw model formats
            if isinstance(loaded_data, dict):
                self.model = loaded_data.get("model")
                self.model_metadata = loaded_data
                self.model_version = loaded_data.get("trained_at", "unknown")
                norm_percentile = loaded_data.get("normalization_percentile", 95.0)
            else:
                self.model = loaded_data
                self.model_version = "unknown"
                norm_percentile = 95.0
            
            # Initialize feature extractor
            self.feature_extractor = FeatureExtractor(
                normalization_percentile=norm_percentile
            )
            
            logger.info(f"Model loaded successfully from {model_path}")
            logger.info(f"Model version: {self.model_version}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load model from {model_path}: {e}")
            self._init_fallback()
            return False
    
    def _init_fallback(self) -> None:
        """Initialize fallback state when model unavailable."""
        self.model = None
        self.model_version = "fallback"
        
        if FEATURE_EXTRACTION_AVAILABLE:
            self.feature_extractor = FeatureExtractor()
        else:
            self.feature_extractor = None
    
    def score(self, transaction) -> Dict[str, Any]:
        """
        Score a transaction for anomaly risk.
        
        Args:
            transaction: Transaction model instance with value, sender, timestamp
        
        Returns:
            Dictionary containing:
                - risk_score: 0-100 risk score (clamped)
                - confidence: 0-100 confidence level
                - severity: Critical/High/Medium/Low
                - reason: Human-readable explanation
                - model_version: Model identifier
                - features: Feature breakdown (optional)
        """
        # Fallback scoring if model not loaded
        if self.model is None:
            return self._fallback_score(transaction)
        
        try:
            # Extract features
            features = self.feature_extractor.extract_features(transaction)
            
            # Get anomaly score from Isolation Forest
            # IsolationForest returns: 1 = normal, -1 = anomaly
            prediction = self.model.predict([features])[0]
            
            # Get decision function score (higher = more normal)
            decision_score = self.model.decision_function([features])[0]
            
            # Convert to risk score (0-100)
            # decision_function typically ranges from ~-0.5 to ~0.5
            # Lower scores = more anomalous
            risk_score = self._convert_to_risk_score(decision_score)
            
            # Determine confidence based on distance from threshold
            confidence = self._calculate_confidence(decision_score)
            
            # Determine severity
            severity = self._get_severity(risk_score)
            
            # Generate reason
            reason = self._generate_reason(features, risk_score, prediction)
            
            return {
                "risk_score": risk_score,
                "confidence": confidence,
                "severity": severity,
                "reason": reason,
                "model_version": self.model_version,
                "prediction": "anomaly" if prediction == -1 else "normal",
                "features": features.tolist() if hasattr(features, "tolist") else list(features),
            }
            
        except Exception as e:
            logger.error(f"Error scoring transaction: {e}")
            return self._fallback_score(transaction)
    
    def _convert_to_risk_score(self, decision_score: float) -> int:
        """
        Convert Isolation Forest decision score to risk score.
        
        Decision score: negative = anomalous, positive = normal
        Typical range: -0.5 to 0.5
        
        Returns:
            Risk score 0-100 (clamped)
        """
        # Invert and scale: more negative decision = higher risk
        # Map from [-0.5, 0.5] to [100, 0]
        normalized = (0.5 - decision_score) / 1.0
        risk = int(normalized * 100)
        
        # Clamp to 0-100
        return max(0, min(100, risk))
    
    def _calculate_confidence(self, decision_score: float) -> int:
        """
        Calculate confidence based on decision score magnitude.
        
        Higher absolute scores = more confident prediction.
        
        Returns:
            Confidence 0-100
        """
        # Use absolute distance from 0 as confidence indicator
        # Typical range |decision_score|: 0 to 0.5
        abs_score = abs(decision_score)
        confidence = int(min(abs_score / 0.3 * 100, 100))
        
        return max(50, confidence)  # Minimum 50% confidence
    
    def _get_severity(self, risk_score: int) -> str:
        """
        Determine severity tier from risk score.

        Args:
            risk_score: 0-100 risk score

        Returns:
            Canonical severity tier string (lowercase)
        """
        return severity_from_score(risk_score)
    
    def _generate_reason(
        self, 
        features: np.ndarray, 
        risk_score: int,
        prediction: int
    ) -> str:
        """
        Generate human-readable reason for the anomaly score.
        
        Args:
            features: Extracted feature vector
            risk_score: Calculated risk score
            prediction: Model prediction (1 or -1)
        
        Returns:
            Human-readable reason string
        """
        if prediction == 1:  # Normal
            if risk_score < 20:
                return "Transaction within normal parameters"
            else:
                return "Slightly elevated risk indicators detected"
        
        # Anomaly - explain why
        reasons = []
        
        # Feature indices from feature_extraction.py
        # [value_normalized, freq_deviation, hour_sin, hour_cos, day_sin, day_cos]
        value_norm = features[0]
        freq_dev = features[1]
        
        # Check value spike
        if value_norm > 1.5:
            spike_ratio = value_norm / max(0.5, 1.0)
            reasons.append(f"{spike_ratio:.1f}x volume spike vs. baseline")
        elif value_norm > 1.0:
            reasons.append("elevated transaction value")
        
        # Check frequency deviation
        if freq_dev > 2.0:
            reasons.append(f"unusual transaction frequency ({freq_dev:.1f}x baseline)")
        elif freq_dev > 0.5:
            reasons.append("moderately elevated activity")
        
        # Check time patterns (hour_sin, hour_cos indicate odd hours when both near 0)
        hour_sin, hour_cos = features[2], features[3]
        # Near midnight when sin≈0 and cos≈-1
        if abs(hour_sin) < 0.3 and hour_cos < -0.7:
            reasons.append("unusual late-night timing")
        # Early morning (3-5 AM)
        elif hour_sin < -0.7 and hour_cos > -0.5:
            reasons.append("off-hours activity (early morning)")
        
        if not reasons:
            return "Multiple risk indicators detected"
        
        return "; ".join(reasons[:2])  # Max 2 reasons for readability
    
    def _fallback_score(self, transaction) -> Dict[str, Any]:
        """
        Fallback scoring when model not available.

        The caller persists the transaction with a NULL score and does not
        create anomaly or alert rows until a trained model is available.
        
        Args:
            transaction: Transaction model instance
        
        Returns:
            Scoring dictionary with conservative defaults
        """
        try:
            return {
                "risk_score": None,
                "confidence": 0,
                "severity": "low",
                "reason": "model_unavailable",
                "model_version": "fallback",
                "prediction": "unknown",
                "features": [],
                "model_unavailable": True,
            }
            
        except Exception as e:
            logger.error(f"Fallback scoring failed: {e}")
            return {
                "risk_score": None,
                "confidence": 0,
                "severity": "low",
                "reason": "model_unavailable",
                "model_version": "fallback",
                "prediction": "unknown",
                "features": [],
                "model_unavailable": True,
            }
    
    def is_loaded(self) -> bool:
        """Check if model is loaded and ready."""
        return self.model is not None
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get model information and metadata."""
        return {
            "loaded": self.is_loaded(),
            "model_version": self.model_version,
            "model_dir": self.model_dir,
            "feature_count": self.feature_extractor.get_feature_count() if self.feature_extractor else 0,
            "feature_names": self.feature_extractor.get_feature_names() if self.feature_extractor else []
        }


# Singleton instance for easy import
_model_instance: Optional[AnomalyModel] = None


def get_model(model_dir: str = "backend/ml/models") -> AnomalyModel:
    """
    Get or create singleton model instance.
    
    Args:
        model_dir: Directory containing model files
    
    Returns:
        AnomalyModel instance
    """
    global _model_instance
    
    if _model_instance is None:
        _model_instance = AnomalyModel(model_dir)
    
    return _model_instance


def reload_model(model_dir: str = "backend/ml/models") -> AnomalyModel:
    """
    Force reload of model from disk.
    
    Args:
        model_dir: Directory containing model files
    
    Returns:
        New AnomalyModel instance
    """
    global _model_instance
    _model_instance = AnomalyModel(model_dir)
    return _model_instance
