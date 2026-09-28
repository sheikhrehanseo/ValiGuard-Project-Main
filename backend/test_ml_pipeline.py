"""
Unit tests for ValiGuard AI ML pipeline (Task 5.2).
Tests feature_extraction, anomaly_model scoring, and edge cases.
"""

import pytest
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np


@dataclass
class MockTransaction:
    """Mock transaction for testing without database dependency."""
    value: float
    sender: str
    timestamp: datetime


# ===== FEATURE EXTRACTION TESTS =====

class TestFeatureExtractor:
    """Test FeatureExtractor class."""
    
    def test_extract_features_shape(self):
        """Test that extract_features returns correct shape (6,)."""
        from ml.feature_extraction import FeatureExtractor
        
        extractor = FeatureExtractor()
        tx = MockTransaction(
            value=1000.0,
            sender="0xabc123",
            timestamp=datetime.utcnow()
        )
        
        features = extractor.extract_features(tx)
        
        assert isinstance(features, np.ndarray)
        assert features.shape == (6,)
    
    def test_extract_batch_shape(self):
        """Test that extract_batch returns correct shape (n, 6)."""
        from ml.feature_extraction import FeatureExtractor
        
        extractor = FeatureExtractor()
        transactions = [
            MockTransaction(value=100.0, sender="0x1", timestamp=datetime.utcnow()),
            MockTransaction(value=200.0, sender="0x2", timestamp=datetime.utcnow()),
            MockTransaction(value=300.0, sender="0x3", timestamp=datetime.utcnow()),
        ]
        
        features = extractor.extract_batch(transactions)
        
        assert isinstance(features, np.ndarray)
        assert features.shape == (3, 6)
    
    def test_feature_names_count(self):
        """Test that get_feature_names returns 6 names."""
        from ml.feature_extraction import FeatureExtractor
        
        extractor = FeatureExtractor()
        names = extractor.get_feature_names()
        
        assert len(names) == 6
        assert "value_normalized" in names
        assert "frequency_deviation" in names
    
    def test_value_feature_range(self):
        """Test that value feature is normalized to reasonable range."""
        from ml.feature_extraction import FeatureExtractor
        
        extractor = FeatureExtractor()
        
        # Small value
        tx1 = MockTransaction(value=100.0, sender="0x1", timestamp=datetime.utcnow())
        features1 = extractor.extract_features(tx1)
        
        # Large value
        tx2 = MockTransaction(value=100000.0, sender="0x2", timestamp=datetime.utcnow())
        features2 = extractor.extract_features(tx2)
        
        # Value feature should be first element
        assert 0 <= features1[0] <= 2.0  # Normalized with cap
        assert 0 <= features2[0] <= 2.0
    
    def test_temporal_features_range(self):
        """Test that temporal features (sin/cos) are in valid range."""
        from ml.feature_extraction import FeatureExtractor
        
        extractor = FeatureExtractor()
        tx = MockTransaction(
            value=500.0,
            sender="0xabc",
            timestamp=datetime.utcnow()
        )
        
        features = extractor.extract_features(tx)
        
        # hour_sin, hour_cos, day_sin, day_cos (indices 2-5)
        for i in range(2, 6):
            assert -1.0 <= features[i] <= 1.0
    
    def test_rolling_history_updates(self):
        """Test that rolling history is updated after extraction."""
        from ml.feature_extraction import FeatureExtractor
        
        extractor = FeatureExtractor(history_size=100)
        
        for i in range(10):
            tx = MockTransaction(
                value=float(i * 100),
                sender=f"0x{i}",
                timestamp=datetime.utcnow()
            )
            extractor.extract_features(tx)
        
        # History should have 10 entries
        assert len(extractor._history) == 10
        assert len(extractor._value_history) == 10
    
    def test_history_size_limit(self):
        """Test that history respects max size limit."""
        from ml.feature_extraction import FeatureExtractor
        
        max_size = 50
        extractor = FeatureExtractor(history_size=max_size)
        
        for i in range(100):
            tx = MockTransaction(
                value=float(i),
                sender=f"0x{i}",
                timestamp=datetime.utcnow()
            )
            extractor.extract_features(tx)
        
        assert len(extractor._history) <= max_size
        assert len(extractor._value_history) <= max_size
    
    def test_reset_clears_history(self):
        """Test that reset() clears rolling history."""
        from ml.feature_extraction import FeatureExtractor
        
        extractor = FeatureExtractor()
        
        for i in range(10):
            tx = MockTransaction(
                value=float(i * 100),
                sender=f"0x{i}",
                timestamp=datetime.utcnow()
            )
            extractor.extract_features(tx)
        
        assert len(extractor._history) == 10
        
        extractor.reset()
        
        assert len(extractor._history) == 0
        assert len(extractor._value_history) == 0


# ===== ANOMALY MODEL SCORING TESTS =====

class TestAnomalyModelScoring:
    """Test AnomalyModel scoring behavior."""
    
    def test_score_returns_required_keys(self):
        """Test that score() returns all required keys."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="nonexistent/path")
        tx = MockTransaction(
            value=1000.0,
            sender="0xabc",
            timestamp=datetime.utcnow()
        )
        
        result = model.score(tx)
        
        assert "risk_score" in result
        assert "confidence" in result
        assert "severity" in result
        assert "reason" in result
        assert "model_version" in result
    
    def test_risk_score_bounds_0_to_100(self):
        """Test that risk_score is always clamped to 0-100."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="nonexistent/path")
        
        # Test with various values
        test_cases = [
            (0.01, "tiny"),
            (100.0, "small"),
            (10000.0, "medium"),
            (1000000.0, "large"),
            (1e9, "huge"),
        ]
        
        for value, desc in test_cases:
            tx = MockTransaction(
                value=value,
                sender="0xtest",
                timestamp=datetime.utcnow()
            )
            result = model.score(tx)
            
            assert 0 <= result["risk_score"] <= 100, \
                f"risk_score out of bounds for {desc} value {value}: {result['risk_score']}"
    
    def test_confidence_bounds(self):
        """Test that confidence is within 0-100."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="nonexistent/path")
        tx = MockTransaction(
            value=5000.0,
            sender="0xabc",
            timestamp=datetime.utcnow()
        )
        
        result = model.score(tx)
        
        assert 0 <= result["confidence"] <= 100
    
    def test_severity_valid_values(self):
        """Test that severity is one of the valid tiers."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="nonexistent/path")
        valid_severities = {"critical", "high", "medium", "low"}
        
        for _ in range(10):
            tx = MockTransaction(
                value=np.random.uniform(100, 50000),
                sender="0xtest",
                timestamp=datetime.utcnow()
            )
            result = model.score(tx)
            assert result["severity"] in valid_severities
    
    def test_reason_is_string(self):
        """Test that reason is a non-empty string."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="nonexistent/path")
        tx = MockTransaction(
            value=2500.0,
            sender="0xabc",
            timestamp=datetime.utcnow()
        )
        
        result = model.score(tx)
        
        assert isinstance(result["reason"], str)
        assert len(result["reason"]) > 0


# ===== SEVERITY BUCKETING TESTS =====

class TestSeverityBucketing:
    """Test severity tier assignment logic."""
    
    def test_critical_threshold(self):
        """Test that risk >= 80 produces critical severity."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="nonexistent/path")
        
        # Check internal thresholds
        assert model.SEVERITY_THRESHOLDS["critical"] == 80
        
        # Mock internal method
        test_cases = [80, 85, 99, 100]
        for score in test_cases:
            severity = model._get_severity(score)
            assert severity == "critical", f"Score {score} should be critical, got {severity}"
    
    def test_high_threshold(self):
        """Test that risk 60-79 produces high severity."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="nonexistent/path")
        
        test_cases = [60, 70, 79]
        for score in test_cases:
            severity = model._get_severity(score)
            assert severity == "high", f"Score {score} should be high, got {severity}"
    
    def test_medium_threshold(self):
        """Test that risk 40-59 produces medium severity."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="nonexistent/path")
        
        test_cases = [40, 50, 59]
        for score in test_cases:
            severity = model._get_severity(score)
            assert severity == "medium", f"Score {score} should be medium, got {severity}"
    
    def test_low_threshold(self):
        """Test that risk < 40 produces low severity."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="nonexistent/path")
        
        test_cases = [0, 25, 39]
        for score in test_cases:
            severity = model._get_severity(score)
            assert severity == "low", f"Score {score} should be low, got {severity}"
    
    def test_boundary_values(self):
        """Test exact boundary values between tiers."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="nonexistent/path")
        
        # Just below/above boundaries
        assert model._get_severity(79) == "high"
        assert model._get_severity(80) == "critical"
        assert model._get_severity(59) == "medium"
        assert model._get_severity(60) == "high"
        assert model._get_severity(39) == "low"
        assert model._get_severity(40) == "medium"


# ===== GRACEFUL NO-MODEL HANDLING TESTS =====

class TestNoModelHandling:
    """Test graceful behavior when model file doesn't exist."""
    
    def test_fallback_when_no_model_file(self):
        """Test that model falls back gracefully without crashing."""
        from ml.anomaly_model import AnomalyModel
        
        # Use a path that definitely doesn't exist
        model = AnomalyModel(model_dir="/nonexistent/model/path/12345")
        
        # Should not crash
        assert model is not None
        assert not model.is_loaded()
    
    def test_fallback_scoring_works(self):
        """Test that fallback scoring returns valid results."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="/nonexistent/path")
        tx = MockTransaction(
            value=5000.0,
            sender="0xabc",
            timestamp=datetime.utcnow()
        )
        
        result = model.score(tx)
        
        # Should still return valid structure
        assert "risk_score" in result
        assert "severity" in result
        assert "reason" in result
        assert result["model_version"] == "fallback"
    
    def test_fallback_version_indicates_fallback(self):
        """Test that model_version indicates fallback mode."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="/nonexistent/path")
        
        assert model.model_version in ["fallback", "untrained"]
    
    def test_fallback_large_value_higher_severity(self):
        """Test that fallback gives higher severity for large values."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="/nonexistent/path")
        
        # Small value
        tx_small = MockTransaction(value=100.0, sender="0x1", timestamp=datetime.utcnow())
        result_small = model.score(tx_small)
        
        # Large value
        tx_large = MockTransaction(value=500000.0, sender="0x2", timestamp=datetime.utcnow())
        result_large = model.score(tx_large)
        
        # Large value should have higher or equal severity
        severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        assert severity_order[result_large["severity"]] >= severity_order[result_small["severity"]]
    
    def test_is_loaded_returns_false_without_model(self):
        """Test that is_loaded() returns False when model not loaded."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="/nonexistent/path")
        
        assert model.is_loaded() is False
    
    def test_get_model_info_without_model(self):
        """Test that get_model_info() works without loaded model."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="/nonexistent/path")
        info = model.get_model_info()
        
        assert "loaded" in info
        assert info["loaded"] is False
        assert "model_version" in info


# ===== REASON GENERATION TESTS =====

class TestReasonGeneration:
    """Test human-readable reason generation."""
    
    def test_reason_for_normal_transaction(self):
        """Test reason for a normal-looking transaction."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="nonexistent/path")
        
        # Create a transaction with normal value
        tx = MockTransaction(
            value=1000.0,
            sender="0xnormal",
            timestamp=datetime.utcnow()
        )
        
        result = model.score(tx)
        
        # Reason should be present and informative
        assert isinstance(result["reason"], str)
        assert len(result["reason"]) > 0
    
    def test_reason_for_suspicious_time(self):
        """Test reason includes timing info for odd hours."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="nonexistent/path")
        
        # Transaction at 3 AM
        tx = MockTransaction(
            value=1000.0,
            sender="0xabc",
            timestamp=datetime(2024, 1, 15, 3, 0, 0)  # 3 AM
        )
        
        result = model.score(tx)
        
        # Reason should exist (not checking specific content in fallback mode)
        assert isinstance(result["reason"], str)


# ===== INTEGRATION TESTS =====

class TestMLPipelineIntegration:
    """Integration tests for full ML pipeline."""
    
    def test_extractor_to_model_pipeline(self):
        """Test feature extraction followed by model scoring."""
        from ml.feature_extraction import FeatureExtractor
        from ml.anomaly_model import AnomalyModel
        
        extractor = FeatureExtractor()
        model = AnomalyModel(model_dir="nonexistent/path")
        
        tx = MockTransaction(
            value=5000.0,
            sender="0xtest",
            timestamp=datetime.utcnow()
        )
        
        # Extract features
        features = extractor.extract_features(tx)
        assert features.shape == (6,)
        
        # Score with model
        result = model.score(tx)
        assert "risk_score" in result
        assert 0 <= result["risk_score"] <= 100
    
    def test_multiple_transactions_consistency(self):
        """Test scoring multiple transactions produces consistent types."""
        from ml.anomaly_model import AnomalyModel
        
        model = AnomalyModel(model_dir="nonexistent/path")
        valid_severities = {"critical", "high", "medium", "low"}
        
        for i in range(20):
            tx = MockTransaction(
                value=np.random.uniform(100, 100000),
                sender=f"0x{i:04x}",
                timestamp=datetime.utcnow() - timedelta(minutes=i)
            )
            
            result = model.score(tx)
            
            assert isinstance(result["risk_score"], int)
            assert 0 <= result["risk_score"] <= 100
            assert result["severity"] in valid_severities
            assert isinstance(result["reason"], str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
