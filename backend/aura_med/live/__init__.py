"""Phase 2 virtual/replay live acquisition subsystem.

The package is deliberately local-first.  It contains no device drivers and
uses the Phase 1 deterministic domain generator as its only signal source.
"""

from .models import (
    AcquisitionSample,
    CanonicalLiveSample,
    CanonicalSample,
    FailureEvent,
    FailureRecord,
    FailureTaxonomy,
    FailureType,
    FaultSpec,
    LiveEvent,
    LiveAcquisitionSample,
    LiveSample,
    SessionState,
)
from .source import ReplaySource, VirtualSource
from .storage import SQLiteRecorder, StorageError
from .session import SessionManager

__all__ = [
    "AcquisitionSample",
    "CanonicalLiveSample",
    "CanonicalSample",
    "FailureEvent",
    "FailureRecord",
    "FailureTaxonomy",
    "FailureType",
    "FaultSpec",
    "LiveEvent",
    "LiveAcquisitionSample",
    "LiveSample",
    "SessionState",
    "ReplaySource",
    "VirtualSource",
    "SQLiteRecorder",
    "StorageError",
    "SessionManager",
]
