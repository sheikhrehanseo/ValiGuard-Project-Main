"""
ValiGuard AI Ingestion Package

Contains the continuous transaction ingestion worker (Task 5.3) that polls
the QIE mempool/blocks via QIENodeManager and normalizes new transactions
into the Transaction schema shape.
"""

from ingestion.worker import IngestionWorker, normalize_transaction

__all__ = ["IngestionWorker", "normalize_transaction"]
