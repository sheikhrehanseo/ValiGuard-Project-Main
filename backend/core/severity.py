"""
Canonical severity tiers for ValiGuard AI.

Single source of truth for the 4-tier severity scale (Low / Medium / High /
Critical, per FR-10 of the Phase 1 documentation) and the risk-score
thresholds that map a 0-100 anomaly score onto those tiers.

Used by the ML model (ml/anomaly_model.py), the ingestion worker, the Flask
API, and the database enums so all components classify identically.
Deliberately free of SQLAlchemy/Flask imports so the ML layer stays decoupled
(NFR-09).
"""

from typing import Dict, Union

# Canonical tier names, lowest to highest. All components must use these
# exact lowercase strings in APIs, DB rows, and WebSocket events.
SEVERITY_TIERS = ("low", "medium", "high", "critical")

# Risk score (0-100) at/above which a transaction falls into each tier.
SEVERITY_THRESHOLDS = {
    "critical": 80.0,
    "high": 60.0,
    "medium": 40.0,
    "low": 0.0,
}

# All four tiers are recorded in anomaly_detections. Alerts and the
# Transaction.is_flagged flag fire at Medium+.
ALERTING_TIERS = ("medium", "high", "critical")


def severity_from_score(score_0_100: float) -> str:
    """Map a 0-100 anomaly score to a canonical severity tier string."""
    if score_0_100 >= SEVERITY_THRESHOLDS["critical"]:
        return "critical"
    if score_0_100 >= SEVERITY_THRESHOLDS["high"]:
        return "high"
    if score_0_100 >= SEVERITY_THRESHOLDS["medium"]:
        return "medium"
    return "low"


def severity_rank(severity: str) -> int:
    """Rank of a tier (0=low .. 3=critical); unknown tiers rank as 'low'."""
    try:
        return SEVERITY_TIERS.index(str(severity).lower())
    except ValueError:
        return 0


def is_alerting_severity(severity: str) -> bool:
    """True if the tier warrants an Alert row and is_flagged (Medium+)."""
    return str(severity).lower() in ALERTING_TIERS
