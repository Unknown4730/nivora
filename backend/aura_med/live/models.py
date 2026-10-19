"""Typed schemas for live samples, events, failures, and session state."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceType(StrEnum):
    VIRTUAL = "virtual"
    REPLAY = "replay"


class SessionState(StrEnum):
    CREATED = "created"
    STREAMING = "streaming"
    DEGRADED = "degraded"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"
    FAILED = "failed"


class QualityFlag(StrEnum):
    MISSING = "missing"
    OUT_OF_RANGE = "out_of_range"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"
    DELAYED = "delayed"
    DISCONNECTED = "disconnected"
    RECONNECTED = "reconnected"
    UNCERTAIN = "uncertain"


class FailureType(StrEnum):
    PACKET_LOSS = "packet_loss"
    DUPLICATE_PACKET = "duplicate_packet"
    OUT_OF_ORDER_PACKET = "out_of_order_packet"
    TIMEOUT_DISCONNECT = "timeout_disconnect"
    RECONNECT = "reconnect"
    MISSING_VALUE = "missing_value"
    OUT_OF_RANGE = "out_of_range"
    JITTER_LATENCY_EXCEEDED = "jitter_latency_exceeded"
    STORAGE_FAILURE = "storage_failure"
    PROCESSING_BACKPRESSURE = "processing_backpressure"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class FailureStatus(StrEnum):
    OPEN = "open"
    RECOVERED = "recovered"
    REVIEWED = "reviewed"


class ReviewState(StrEnum):
    UNREVIEWED = "unreviewed"
    NEEDS_REVIEW = "needs_review"
    ACKNOWLEDGED = "acknowledged"


class FaultSpec(BaseModel):
    """A deterministic fault recipe accepted by the virtual source.

    ``at_samples`` and ``every`` make tests reproducible without relying on
    random probability.  ``probability`` is also deterministic because it is
    evaluated against a seeded PRNG.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    type: str
    at_samples: list[int] = Field(default_factory=list, alias="atSamples")
    every: int | None = Field(default=None, gt=0)
    probability: float | None = Field(default=None, ge=0, le=1)
    channels: list[str] = Field(default_factory=list)
    delay_sec: float = Field(default=0.0, ge=0, alias="delaySec")
    duration_samples: int | None = Field(default=None, gt=0, alias="durationSamples")
    start_sample: int | None = Field(default=None, ge=0, alias="startSample")
    end_sample: int | None = Field(default=None, ge=0, alias="endSample")
    count: int | None = Field(default=None, gt=0)

    @field_validator("type")
    @classmethod
    def non_empty_type(cls, value: str) -> str:
        value = value.strip().lower().replace("-", "_")
        aliases = {
            "packetloss": "packet_loss",
            "duplicate": "duplicates",
            "duplicate_packet": "duplicates",
            "duplicate_packets": "duplicates",
            "outoforder": "out_of_order",
            "missing": "missing_values",
            "missing_value": "missing_values",
            "outofrange": "out_of_range",
            "disconnect": "disconnect_reconnect",
            "disconnect_reconnect_fault": "disconnect_reconnect",
            "jitter": "jitter_delay",
            "latency": "jitter_delay",
        }
        return aliases.get(value, value)

    @field_validator("at_samples")
    @classmethod
    def valid_indices(cls, value: list[int]) -> list[int]:
        if any(item < 0 for item in value):
            raise ValueError("atSamples must contain non-negative indices")
        return sorted(set(value))


class LiveSample(BaseModel):
    """Canonical sample envelope used by both virtual acquisition and replay."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        use_enum_values=True,
    )

    session_id: str = Field(alias="sessionId", min_length=1)
    stream_id: str = Field(alias="streamId", min_length=1)
    sensor_id: str = Field(alias="sensorId", min_length=1)
    sample_id: str = Field(alias="sampleId", min_length=1)
    sequence_number: int = Field(alias="sequenceNumber", ge=0)
    source_timestamp: float = Field(alias="sourceTimestamp")
    received_timestamp: float = Field(alias="receivedTimestamp")
    processing_timestamp: float = Field(alias="processingTimestamp")
    relative_time_sec: float = Field(default=0.0, alias="relativeTimeSec")
    values: dict[str, float | None]
    units: dict[str, str]
    source_type: SourceType = Field(default=SourceType.VIRTUAL, alias="sourceType")
    quality_flags: list[str] = Field(default_factory=list, alias="qualityFlags")

    @field_validator(
        "source_timestamp",
        "received_timestamp",
        "processing_timestamp",
        "relative_time_sec",
    )
    @classmethod
    def finite_time(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("timestamps must be finite")
        return float(value)

    @field_validator("values")
    @classmethod
    def finite_values(cls, value: dict[str, float | None]) -> dict[str, float | None]:
        if not value:
            raise ValueError("values must contain at least one channel")
        for channel, item in value.items():
            if not channel:
                raise ValueError("channel names must not be empty")
            if item is not None and not math.isfinite(item):
                raise ValueError("sample values must be finite or null")
        return value

    @field_validator("units")
    @classmethod
    def non_empty_units(cls, value: dict[str, str]) -> dict[str, str]:
        if not value or any(not key or not unit for key, unit in value.items()):
            raise ValueError("units must contain non-empty channel/unit pairs")
        return value

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


# The two names make the schema easy to discover from integrations that use
# either the protocol or acquisition vocabulary.
AcquisitionSample = LiveSample
CanonicalSample = LiveSample
CanonicalLiveSample = LiveSample
LiveAcquisitionSample = LiveSample


class FailureEvent(BaseModel):
    """Technical failure record; it intentionally makes no clinical claim."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        use_enum_values=True,
    )

    failure_id: str = Field(alias="failureId", min_length=1)
    session_id: str = Field(alias="sessionId", min_length=1)
    stream_id: str = Field(default="", alias="streamId")
    sensor_id: str = Field(alias="sensorId", min_length=1)
    failure_type: FailureType = Field(alias="type")
    relative_time_sec: float = Field(default=0.0, alias="relativeTimeSec")
    affected_channels: list[str] = Field(default_factory=list, alias="affectedChannels")
    technical_severity: Literal["info", "warning", "error", "critical"] = Field(
        default="warning", alias="technicalSeverity"
    )
    observed: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    context_ids: dict[str, str] = Field(default_factory=dict, alias="contextIds")
    detector: str = "live-detector"
    detector_version: str = Field(default="1.0", alias="detectorVersion")
    status: FailureStatus = FailureStatus.OPEN
    review_state: ReviewState = Field(default=ReviewState.UNREVIEWED, alias="reviewState")
    recovery_info: dict[str, Any] = Field(default_factory=dict, alias="recoveryInfo")
    created_timestamp: float = Field(default=0.0, alias="createdTimestamp")

    @field_validator("relative_time_sec", "created_timestamp")
    @classmethod
    def finite_failure_time(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("failure times must be finite")
        return float(value)

    @property
    def type(self) -> FailureType:
        """Convenience property matching the wire field name."""

        return self.failure_type

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


FailureRecord = FailureEvent
FailureTaxonomy = FailureType


class LiveEvent(BaseModel):
    """Subscriber event envelope persisted in the event ledger."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    event_id: str = Field(alias="eventId", min_length=1)
    session_id: str = Field(alias="sessionId", min_length=1)
    event_type: str = Field(alias="type", min_length=1)
    relative_time_sec: float = Field(default=0.0, alias="relativeTimeSec")
    payload: dict[str, Any] = Field(default_factory=dict)
    created_timestamp: float = Field(default=0.0, alias="createdTimestamp")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class SessionReport(BaseModel):
    """Current human-readable and technical view of one session."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    session_id: str = Field(alias="sessionId")
    state: SessionState
    summary: str
    technical_summary: str = Field(alias="technicalSummary")
    metrics: dict[str, Any]
    review_flags: list[str] = Field(default_factory=list, alias="reviewFlags")
    failure_count: int = Field(default=0, alias="failureCount")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


__all__ = [
    "AcquisitionSample",
    "CanonicalSample",
    "CanonicalLiveSample",
    "FailureEvent",
    "FailureRecord",
    "FailureTaxonomy",
    "FailureStatus",
    "FailureType",
    "FaultSpec",
    "LiveEvent",
    "LiveSample",
    "LiveAcquisitionSample",
    "QualityFlag",
    "ReviewState",
    "SessionReport",
    "SessionState",
    "SourceType",
]
