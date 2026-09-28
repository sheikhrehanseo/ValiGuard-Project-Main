"""
Feature extraction module for Isolation Forest anomaly detection.
Extracts feature vectors from Transaction objects for ML pipeline (FR-08).

Features extracted:
- Transaction value (normalized)
- Frequency deviation from rolling baseline
- Time-of-day/temporal patterns
"""

from datetime import datetime, timedelta
from typing import List, Optional, Tuple
import numpy as np
from collections import deque


class FeatureExtractor:
    """
    Extracts feature vectors from transactions for anomaly detection.
    
    Maintains rolling baseline statistics for frequency calculations.
    Thread-safe for single-threaded applications.
    """
    
    def __init__(
        self,
        rolling_window_hours: int = 24,
        history_size: int = 1000,
        normalization_percentile: float = 95.0
    ):
        """
        Initialize feature extractor.
        
        Args:
            rolling_window_hours: Time window for baseline calculation
            history_size: Max transactions to keep in rolling history
            normalization_percentile: Percentile for value normalization
        """
        self.rolling_window_hours = rolling_window_hours
        self.history_size = history_size
        self.normalization_percentile = normalization_percentile
        
        # Rolling history: (timestamp, sender, value)
        self._history: deque = deque(maxlen=history_size)
        self._value_history: deque = deque(maxlen=history_size)
    
    def extract_features(
        self,
        transaction,
        historical_transactions: Optional[List] = None
    ) -> np.ndarray:
        """
        Extract feature vector from a transaction.
        
        Args:
            transaction: Transaction model instance
            historical_transactions: Optional list of historical transactions
                                     for baseline calculation. If None, uses
                                     internal rolling history.
        
        Returns:
            Feature vector as numpy array with shape (6,)
            [value_normalized, freq_deviation, hour_sin, hour_cos,
             day_sin, day_cos]
        """
        # Value feature
        value_normalized = self._extract_value_feature(transaction)
        
        # Frequency feature
        freq_deviation = self._extract_frequency_feature(
            transaction, historical_transactions
        )
        
        # Temporal features
        hour_sin, hour_cos, day_sin, day_cos = self._extract_temporal_features(
            transaction
        )
        
        # Update rolling history
        self._update_history(transaction)
        
        return np.array([
            value_normalized,
            freq_deviation,
            hour_sin,
            hour_cos,
            day_sin,
            day_cos
        ])
    
    def extract_batch(
        self,
        transactions: List,
        historical_transactions: Optional[List] = None
    ) -> np.ndarray:
        """
        Extract features from multiple transactions.
        
        Args:
            transactions: List of Transaction instances
            historical_transactions: Historical data for baseline
        
        Returns:
            Feature matrix of shape (n_transactions, 6)
        """
        features = []
        for tx in transactions:
            features.append(
                self.extract_features(tx, historical_transactions)
            )
        return np.array(features)
    
    def _extract_value_feature(self, transaction) -> float:
        """
        Extract normalized transaction value.
        
        Uses rolling percentile-based normalization for robustness
        against outliers.
        
        Returns:
            Normalized value in [0, ~1] range
        """
        value = float(transaction.value)
        
        if len(self._value_history) < 10:
            # Not enough history, use log scaling
            return min(np.log1p(value) / 20.0, 1.0)
        
        # Percentile-based normalization
        values = np.array(list(self._value_history))
        cap = np.percentile(values, self.normalization_percentile)
        
        if cap <= 0:
            return 0.0
        
        return min(value / cap, 2.0)  # Cap at 2.0 for outliers
    
    def _extract_frequency_feature(
        self,
        transaction,
        historical_transactions: Optional[List] = None
    ) -> float:
        """
        Calculate frequency deviation from rolling baseline.
        
        Compares recent transaction rate for this sender against
        the baseline rate.
        
        Returns:
            Deviation score where 0 = baseline, >0 = higher frequency
        """
        sender = transaction.sender
        timestamp = transaction.timestamp or datetime.utcnow()
        
        # Get relevant history
        if historical_transactions is not None:
            history = historical_transactions
        else:
            history = list(self._history)
        
        if len(history) < 5:
            return 0.0
        
        # Calculate baseline frequency (all transactions)
        cutoff_time = timestamp - timedelta(hours=self.rolling_window_hours)
        recent_all = sum(1 for ts, _, _ in history if ts >= cutoff_time)
        baseline_rate = recent_all / self.rolling_window_hours  # tx/hour
        
        # Calculate sender frequency
        recent_sender = sum(
            1 for ts, s, _ in history
            if s == sender and ts >= cutoff_time
        )
        sender_rate = recent_sender / self.rolling_window_hours
        
        # Calculate deviation
        if baseline_rate <= 0:
            return 0.0
        
        # Ratio of sender rate to baseline
        deviation = (sender_rate / baseline_rate) - 1.0
        
        # Normalize to reasonable range
        return min(max(deviation, -1.0), 10.0)
    
    def _extract_temporal_features(
        self, transaction
    ) -> Tuple[float, float, float, float]:
        """
        Extract cyclical time features.
        
        Uses sin/cos encoding for hour of day and day of week to
        capture temporal patterns without discontinuity.
        
        Returns:
            Tuple of (hour_sin, hour_cos, day_sin, day_cos)
        """
        timestamp = transaction.timestamp or datetime.utcnow()
        
        # Hour of day (0-23)
        hour = timestamp.hour + timestamp.minute / 60.0
        hour_rad = (hour / 24.0) * 2 * np.pi
        hour_sin = np.sin(hour_rad)
        hour_cos = np.cos(hour_rad)
        
        # Day of week (0-6)
        day = timestamp.weekday()
        day_rad = (day / 7.0) * 2 * np.pi
        day_sin = np.sin(day_rad)
        day_cos = np.cos(day_rad)
        
        return hour_sin, hour_cos, day_sin, day_cos
    
    def _update_history(self, transaction) -> None:
        """Update rolling history with new transaction."""
        timestamp = transaction.timestamp or datetime.utcnow()
        sender = transaction.sender
        value = float(transaction.value)
        
        self._history.append((timestamp, sender, value))
        self._value_history.append(value)
    
    def reset(self) -> None:
        """Clear rolling history."""
        self._history.clear()
        self._value_history.clear()
    
    def get_feature_count(self) -> int:
        """Return number of features in the vector."""
        return 6
    
    def get_feature_names(self) -> List[str]:
        """Return names of features in order."""
        return [
            "value_normalized",
            "frequency_deviation",
            "hour_sin",
            "hour_cos",
            "day_sin",
            "day_cos"
        ]
