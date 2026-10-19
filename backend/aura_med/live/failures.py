"""Deterministic technical failure detection and durable failure ledger."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from ..domain.scenarios import SIGNAL_META
from .models import (
    FailureEvent,
    FailureStatus,
    FailureType,
    LiveSample,
    QualityFlag,
    ReviewState,
)
from .storage import SQLiteRecorder, StorageError


class FailureLedger:
    """Append failures to durable storage and retain only a bounded hot view."""

    def __init__(self, recorder: SQLiteRecorder | None = None, *, max_hot: int = 512) -> None:
        if max_hot <= 0:
            raise ValueError("max_hot must be positive")
        self.recorder = recorder
        self._hot: deque[FailureEvent] = deque(maxlen=max_hot)
        self._counter = 0

    @property
    def hot_size(self) -> int:
        return len(self._hot)

    def append(self, failure: FailureEvent) -> FailureEvent:
        if self.recorder is not None:
            self.recorder.record_failure(failure)
        self._hot.append(failure)
        self._counter += 1
        return failure

    def list(self, session_id: str | None = None) -> list[FailureEvent]:
        if self.recorder is not None and session_id is not None:
            return self.recorder.get_failures(session_id)
        values = list(self._hot)
        return [item for item in values if session_id is None or item.session_id == session_id]


class FailureDetector:
    """Detect transport, timing, quality, and processing failures."""

    detector = "phase2-live-detector"
    version = "1.0.0"

    def __init__(
        self,
        session_id: str,
        stream_id: str,
        sensor_id: str,
        ledger: FailureLedger,
        *,
        sample_rate_hz: float = 1.0,
        latency_threshold_sec: float | None = None,
        jitter_threshold_sec: float | None = None,
    ) -> None:
        self.session_id = session_id
        self.stream_id = stream_id
        self.sensor_id = sensor_id
        self.ledger = ledger
        self.sample_rate_hz = sample_rate_hz
        self.latency_threshold_sec = latency_threshold_sec if latency_threshold_sec is not None else max(0.5, 2 / sample_rate_hz)
        self.jitter_threshold_sec = jitter_threshold_sec if jitter_threshold_sec is not None else max(0.25, 1 / sample_rate_hz)
        self.last_sequence: int | None = None
        self.last_timestamp: float | None = None
        self.last_latency: float | None = None
        self.seen_sample_ids: set[str] = set()
        self.expected = 0
        self.received = 0
        self.missing = 0
        self.missing_packets = 0
        self.missing_values = 0
        self.duplicates = 0
        self.out_of_order = 0
        self.latencies: list[float] = []
        self.jitters: list[float] = []
        self.reconnects = 0
        self.disconnects = 0
        self._open_by_type: dict[FailureType, list[str]] = {}

    def _make(
        self,
        failure_type: FailureType,
        sample: LiveSample | None = None,
        *,
        relative_time_sec: float = 0.0,
        channels: list[str] | None = None,
        severity: str = "warning",
        observed: dict[str, Any] | None = None,
        expected: dict[str, Any] | None = None,
        context_ids: dict[str, str] | None = None,
        recovery_info: dict[str, Any] | None = None,
        status: FailureStatus = FailureStatus.OPEN,
        failure_id: str | None = None,
    ) -> FailureEvent:
        number = self.ledger._counter + 1
        failure = FailureEvent(
            failureId=failure_id or f"failure-{number:08d}",
            sessionId=self.session_id,
            streamId=self.stream_id,
            sensorId=self.sensor_id,
            type=failure_type,
            relativeTimeSec=relative_time_sec,
            affectedChannels=channels or [],
            technicalSeverity=severity,  # type: ignore[arg-type]
            observed=observed or {},
            expected=expected or {},
            contextIds=context_ids or {},
            detector=self.detector,
            detectorVersion=self.version,
            status=status,
            recoveryInfo=recovery_info or {},
            createdTimestamp=time.time(),
        )
        try:
            self.ledger.append(failure)
        except StorageError:
            # A storage failure cannot be written to the failed database.  It
            # remains visible to the session manager as a processing error.
            raise
        self._open_by_type.setdefault(failure_type, []).append(failure.failure_id)
        return failure

    def on_sample(self, sample: LiveSample) -> list[FailureEvent]:
        failures: list[FailureEvent] = []
        self.received += 1
        self.expected = max(self.expected, sample.sequence_number + 1)
        if self.last_sequence is not None:
            if sample.sequence_number > self.last_sequence + 1:
                gap = sample.sequence_number - self.last_sequence - 1
                self.missing += gap
                self.missing_packets += gap
                failures.append(
                    self._make(
                        FailureType.PACKET_LOSS,
                        sample,
                        relative_time_sec=sample.relative_time_sec,
                        channels=list(sample.values),
                        severity="error",
                        observed={"missingCount": gap, "previousSequence": self.last_sequence},
                        expected={"nextSequence": self.last_sequence + 1},
                        context_ids={"sampleId": sample.sample_id},
                        recovery_info={"recoveredAtSequence": sample.sequence_number},
                    )
                )
            if sample.sequence_number < self.last_sequence:
                self.out_of_order += 1
                failures.append(
                    self._make(
                        FailureType.OUT_OF_ORDER_PACKET,
                        sample,
                        relative_time_sec=sample.relative_time_sec,
                        channels=list(sample.values),
                        observed={"sequence": sample.sequence_number, "lastSequence": self.last_sequence},
                        expected={"sequenceAtLeast": self.last_sequence},
                        context_ids={"sampleId": sample.sample_id},
                    )
                )
        if sample.sample_id in self.seen_sample_ids or (
            self.last_sequence is not None and sample.sequence_number == self.last_sequence
        ):
            self.duplicates += 1
            failures.append(
                self._make(
                    FailureType.DUPLICATE_PACKET,
                    sample,
                    relative_time_sec=sample.relative_time_sec,
                    channels=list(sample.values),
                    observed={"sampleId": sample.sample_id, "sequence": sample.sequence_number},
                    expected={"sampleIdUnique": True},
                    context_ids={"sampleId": sample.sample_id},
                )
            )
        self.seen_sample_ids.add(sample.sample_id)
        self.last_sequence = max(self.last_sequence or 0, sample.sequence_number)
        latency = max(0.0, sample.received_timestamp - sample.source_timestamp)
        self.latencies.append(latency)
        if self.last_latency is not None:
            jitter = abs(latency - self.last_latency)
            self.jitters.append(jitter)
            if jitter > self.jitter_threshold_sec:
                failures.append(
                    self._make(
                        FailureType.JITTER_LATENCY_EXCEEDED,
                        sample,
                        relative_time_sec=sample.relative_time_sec,
                        observed={"jitterSec": jitter, "latencySec": latency},
                        expected={"maxJitterSec": self.jitter_threshold_sec},
                        context_ids={"sampleId": sample.sample_id},
                    )
                )
        self.last_latency = latency
        if latency > self.latency_threshold_sec:
            failures.append(
                self._make(
                    FailureType.JITTER_LATENCY_EXCEEDED,
                    sample,
                    relative_time_sec=sample.relative_time_sec,
                    observed={"latencySec": latency},
                    expected={"maxLatencySec": self.latency_threshold_sec},
                    context_ids={"sampleId": sample.sample_id},
                )
            )

        missing_channels = [channel for channel, value in sample.values.items() if value is None]
        if missing_channels:
            self.missing += len(missing_channels)
            self.missing_values += len(missing_channels)
            failures.append(
                self._make(
                    FailureType.MISSING_VALUE,
                    sample,
                    relative_time_sec=sample.relative_time_sec,
                    channels=missing_channels,
                    observed={"missingChannels": missing_channels},
                    expected={"valuePresent": True},
                    context_ids={"sampleId": sample.sample_id},
                )
            )
            if len(missing_channels) == len(sample.values):
                failures.append(
                    self._make(
                        FailureType.INSUFFICIENT_EVIDENCE,
                        sample,
                        relative_time_sec=sample.relative_time_sec,
                        channels=missing_channels,
                        severity="error",
                        observed={"availableChannels": 0},
                        expected={"minimumAvailableChannels": 1},
                        context_ids={"sampleId": sample.sample_id},
                    )
                )
        out_of_range = []
        for channel, value in sample.values.items():
            if value is None or channel not in SIGNAL_META:
                continue
            minimum, maximum = SIGNAL_META[channel]["plausibility"]
            if value < minimum or value > maximum:
                out_of_range.append(channel)
        if out_of_range:
            failures.append(
                self._make(
                    FailureType.OUT_OF_RANGE,
                    sample,
                    relative_time_sec=sample.relative_time_sec,
                    channels=out_of_range,
                    observed={"channels": out_of_range},
                    expected={"plausibilityBounds": {channel: SIGNAL_META[channel]["plausibility"] for channel in out_of_range}},
                    context_ids={"sampleId": sample.sample_id},
                )
            )
        return failures

    def on_source_event(self, event_type: str, *, relative_time_sec: float = 0.0, payload: dict[str, Any] | None = None) -> list[FailureEvent]:
        payload = payload or {}
        if event_type == "disconnect":
            self.disconnects += 1
            return [
                self._make(
                    FailureType.TIMEOUT_DISCONNECT,
                    relative_time_sec=relative_time_sec,
                    channels=[],
                    severity="error",
                    observed=payload,
                    expected={"connection": "connected"},
                    recovery_info={"reconnectExpected": True},
                )
            ]
        if event_type == "reconnect":
            self.reconnects += 1
            recovery: list[FailureEvent] = []
            for failure_id in self._open_by_type.pop(FailureType.TIMEOUT_DISCONNECT, []):
                recovery.append(
                    self._make(
                        FailureType.TIMEOUT_DISCONNECT,
                        relative_time_sec=relative_time_sec,
                        severity="info",
                        status=FailureStatus.RECOVERED,
                        failure_id=failure_id,
                        observed=payload,
                        expected={"connection": "reconnected"},
                        recovery_info={"recovered": True, "reconnectSequence": payload.get("sequenceNumber")},
                    )
                )
            recovery.append(self._make(
                FailureType.RECONNECT,
                relative_time_sec=relative_time_sec,
                channels=[],
                severity="info",
                observed=payload,
                expected={"connection": "reconnected"},
                recovery_info={"recovered": True},
            ))
            return recovery
        return []

    def on_backpressure(self, *, queue_depth: int, queue_limit: int, relative_time_sec: float = 0.0) -> list[FailureEvent]:
        return [
            self._make(
                FailureType.PROCESSING_BACKPRESSURE,
                relative_time_sec=relative_time_sec,
                severity="error",
                observed={"queueDepth": queue_depth},
                expected={"queueLimit": queue_limit},
                recovery_info={"workerContinues": True},
            )
        ]

    def metrics(self, *, queue_depth: int = 0, dropped: int = 0, source_complete: bool = False) -> dict[str, Any]:
        return {
            "expected": self.expected,
            "received": self.received,
            "missing": self.missing,
            "missingPackets": self.missing_packets,
            "missingValues": self.missing_values,
            "duplicate": self.duplicates,
            "duplicates": self.duplicates,
            "outOfOrder": self.out_of_order,
            "out_of_order": self.out_of_order,
            "latency": {
                "meanSec": sum(self.latencies) / len(self.latencies) if self.latencies else 0.0,
                "maxSec": max(self.latencies, default=0.0),
            },
            "latencyMeanSec": sum(self.latencies) / len(self.latencies) if self.latencies else 0.0,
            "latencyMaxSec": max(self.latencies, default=0.0),
            "jitter": {
                "meanSec": sum(self.jitters) / len(self.jitters) if self.jitters else 0.0,
                "maxSec": max(self.jitters, default=0.0),
            },
            "jitterMeanSec": sum(self.jitters) / len(self.jitters) if self.jitters else 0.0,
            "jitterMaxSec": max(self.jitters, default=0.0),
            "reconnects": self.reconnects,
            "disconnects": self.disconnects,
            "queueDepth": queue_depth,
            "dropped": dropped,
            "sourceComplete": source_complete,
        }


__all__ = ["FailureDetector", "FailureLedger"]
