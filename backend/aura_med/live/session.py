"""Process-local session orchestration with durable SQLite records."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..domain.scenarios import get_scenario_definition
from .failures import FailureDetector, FailureLedger
from .models import FailureEvent, FaultSpec, LiveEvent, LiveSample, SessionReport, SessionState
from .source import ReplaySource, SourceItem, VirtualSource
from .storage import SQLiteRecorder, StorageError


@dataclass
class _LiveSession:
    session_id: str
    source: VirtualSource | ReplaySource
    stream_id: str
    sensor_id: str
    metadata: dict[str, Any]
    state: SessionState = SessionState.CREATED
    queue: asyncio.Queue[SourceItem] | None = None
    worker_task: asyncio.Task[None] | None = None
    producer_task: asyncio.Task[None] | None = None
    run_task: asyncio.Task[None] | None = None
    subscribers: set[asyncio.Queue[LiveEvent]] = field(default_factory=set)
    hot_samples: deque[LiveSample] = field(default_factory=deque)
    detector: FailureDetector | None = None
    ledger: FailureLedger | None = None
    dropped: int = 0
    source_complete: bool = False
    event_counter: int = 0
    stop_requested: bool = False


class SessionManager:
    """Manage live workers while SQLite remains the source of durable truth."""

    def __init__(
        self,
        recorder: SQLiteRecorder | None = None,
        *,
        db_path: str | None = None,
        data_dir: str | None = None,
        max_hot_samples: int = 256,
        queue_size: int = 256,
        max_subscriber_queue: int = 256,
    ) -> None:
        if max_hot_samples <= 0 or queue_size <= 0 or max_subscriber_queue <= 0:
            raise ValueError("cache and queue bounds must be positive")
        if recorder is not None and (db_path is not None or data_dir is not None):
            raise ValueError("pass recorder or db_path/data_dir, not both")
        self.recorder = recorder or SQLiteRecorder(db_path=db_path, data_dir=data_dir)
        self.max_hot_samples = max_hot_samples
        self.queue_size = queue_size
        self.max_subscriber_queue = max_subscriber_queue
        self._sessions: dict[str, _LiveSession] = {}

    def _session(self, session_id: str) -> _LiveSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def has_active_session(self, session_id: str) -> bool:
        return session_id in self._sessions

    def has_readable_session(self, session_id: str) -> bool:
        return self.has_active_session(session_id) or self.recorder.get_session(session_id) is not None

    def _stored_metadata(self, session_id: str) -> dict[str, Any]:
        metadata = self.recorder.get_session(session_id)
        if metadata is None:
            raise KeyError(session_id)
        return metadata

    def create_session(
        self,
        *,
        session_id: str | None = None,
        stream_id: str = "stream-1",
        sensor_id: str = "virtual-sensor-1",
        scenario: str = "stable-baseline",
        sample_rate_hz: float = 1.0,
        duration_sec: float = 10.0,
        speed: float = 1.0,
        seed: int = 20261018,
        artifact_intensity: float = 0.48,
        faults: list[FaultSpec | dict[str, Any] | str] | Mapping[str, Any] | None = None,
        fault_injection: Mapping[str, Any] | None = None,
        no_wait: bool = True,
    ) -> dict[str, Any]:
        session_id = session_id or f"session-{uuid.uuid4().hex[:12]}"
        if session_id in self._sessions or self.recorder.get_session(session_id) is not None:
            raise ValueError(f"session '{session_id}' already exists")
        # Validate scenario and source parameters at creation so malformed API
        # requests produce 422 before a worker is scheduled.
        get_scenario_definition(scenario, duration_sec)
        source = VirtualSource(
            session_id=session_id,
            stream_id=stream_id,
            sensor_id=sensor_id,
            scenario=scenario,
            sample_rate_hz=sample_rate_hz,
            duration_sec=duration_sec,
            speed=speed,
            seed=seed,
            artifact_intensity=artifact_intensity,
            faults=faults,
            fault_injection=fault_injection,
            no_wait=no_wait,
        )
        ledger = FailureLedger(self.recorder)
        detector = FailureDetector(session_id, stream_id, sensor_id, ledger, sample_rate_hz=sample_rate_hz)
        metadata = {
            "sessionId": session_id,
            "streamId": stream_id,
            "sensorId": sensor_id,
            "scenario": scenario,
            "sampleRateHz": sample_rate_hz,
            "durationSec": duration_sec,
            "speed": speed,
            "seed": seed,
            "artifactIntensity": artifact_intensity,
            "faults": [fault.model_dump(by_alias=True, mode="json") for fault in source.faults],
            "sourceType": "virtual",
            "state": SessionState.CREATED.value,
            "createdTimestamp": time.time(),
        }
        self.recorder.record_session(session_id, metadata)
        self._sessions[session_id] = _LiveSession(
            session_id=session_id,
            source=source,
            stream_id=stream_id,
            sensor_id=sensor_id,
            metadata=metadata,
            detector=detector,
            ledger=ledger,
            hot_samples=deque(maxlen=self.max_hot_samples),
        )
        return self.get_session(session_id)

    async def start(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        if session.state == SessionState.STREAMING:
            return self.get_session(session_id)
        if session.state not in (SessionState.CREATED, SessionState.RECONNECTING):
            raise ValueError(f"session is {session.state.value} and cannot be started")
        session.stop_requested = False
        session.state = SessionState.STREAMING
        session.metadata["state"] = session.state.value
        session.metadata["startedTimestamp"] = time.time()
        self.recorder.update_session(session_id, session.metadata)
        session.queue = asyncio.Queue(maxsize=self.queue_size)
        session.run_task = asyncio.create_task(self._run_session(session))
        # Let producer/worker receive at least one scheduling turn before the
        # REST response, while leaving all actual pacing off the event loop.
        if isinstance(session.source, VirtualSource) and session.source.no_wait:
            # Accelerated mode is explicitly intended for deterministic tests
            # and replay jobs.  Awaiting its cooperative worker here gives a
            # REST client a complete read-after-start result even when the
            # client creates a short-lived event loop per request.
            await session.run_task
        else:
            await asyncio.sleep(0)
        return self.get_session(session_id)

    async def _run_session(self, session: _LiveSession) -> None:
        assert session.queue is not None

        async def produce() -> None:
            try:
                async for item in session.source.aiter_items():
                    if session.queue.full() and session.detector is not None:
                        try:
                            pressure_failures = session.detector.on_backpressure(
                                queue_depth=session.queue.qsize(),
                                queue_limit=session.queue.maxsize,
                            )
                            for failure in pressure_failures:
                                await self._publish(session, "failure", {"failure": failure.to_dict()})
                        except StorageError:
                            session.dropped += 1
                    await session.queue.put(item)
            finally:
                try:
                    session.queue.put_nowait(SourceItem("end"))
                except asyncio.QueueFull:
                    # Stop/cancel cleanup must never wait behind a full queue.
                    try:
                        session.queue.get_nowait()
                        session.queue.task_done()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        session.queue.put_nowait(SourceItem("end"))
                    except asyncio.QueueFull:
                        pass

        async def consume() -> None:
            while True:
                item = await session.queue.get()
                try:
                    if item.kind == "end":
                        session.source_complete = True
                        return
                    await self._process_item(session, item)
                finally:
                    session.queue.task_done()

        session.producer_task = asyncio.create_task(produce())
        session.worker_task = asyncio.create_task(consume())
        try:
            await asyncio.gather(session.producer_task, session.worker_task)
            if session.source_complete and not session.stop_requested and session.state != SessionState.FAILED:
                await self._finalize_stopped(session)
        except asyncio.CancelledError:
            session.source.cancel()
            raise
        except Exception as error:
            session.state = SessionState.FAILED
            session.metadata["state"] = session.state.value
            session.metadata["error"] = str(error)
            try:
                self.recorder.record_session(session.session_id, session.metadata)
            except StorageError:
                pass
        finally:
            session.producer_task = None
            session.worker_task = None

    async def _process_item(self, session: _LiveSession, item: SourceItem) -> None:
        if item.kind == "event":
            payload = item.payload or {}
            try:
                self.recorder.record_raw(
                    session.session_id,
                    "source_event",
                    {"type": item.event_type or "source", "payload": payload},
                )
            except StorageError as error:
                failure = self._storage_failure(session, str(error), 0.0)
                await self._publish(session, "failure", {"failure": failure.to_dict()})
            relative = float(payload.get("relativeTimeSec", payload.get("sequenceNumber", 0))) / max(
                0.001, session.detector.sample_rate_hz if session.detector else 1
            )
            try:
                failures = session.detector.on_source_event(item.event_type or "event", relative_time_sec=relative, payload=payload) if session.detector else []
            except StorageError as error:
                failures = [self._storage_failure(session, str(error), relative)]
            if item.event_type == "disconnect":
                session.state = SessionState.RECONNECTING
            elif item.event_type == "reconnect":
                session.state = SessionState.DEGRADED if failures else SessionState.STREAMING
            await self._publish(session, item.event_type or "source", {"payload": payload})
            for failure in failures:
                await self._publish(session, "failure", {"failure": failure.to_dict()})
            return
        if item.sample is None:
            return
        sample = item.sample
        # Preserve the source envelope before any processing or detector work.
        try:
            self.recorder.record_raw(session.session_id, "sample_input", sample.to_dict())
            self.recorder.record_sample(sample)
        except StorageError as error:
            failure = self._storage_failure(session, str(error), sample.relative_time_sec)
            await self._publish(session, "failure", {"failure": failure.to_dict()})
            session.state = SessionState.FAILED
            return
        session.hot_samples.append(sample)
        failures: list[FailureEvent] = []
        try:
            failures = session.detector.on_sample(sample) if session.detector else []
        except StorageError as error:
            failures = [self._storage_failure(session, str(error), sample.relative_time_sec)]
        if failures:
            session.state = SessionState.DEGRADED
        await self._publish(session, "sample", {"sample": sample.to_dict()})
        await self._publish(
            session,
            "quality",
            {
                "sampleId": sample.sample_id,
                "qualityFlags": list(sample.quality_flags),
                "channels": list(sample.values),
            },
        )
        await self._publish(
            session,
            "algorithm",
            {
                "algorithmId": "phase2-quality-monitor",
                "algorithmVersion": "1.0.0",
                "sampleId": sample.sample_id,
                "technicalReview": "quality flags are transport and signal-shape observations",
            },
        )
        for failure in failures:
            await self._publish(session, "failure", {"failure": failure.to_dict()})

    def _storage_failure(self, session: _LiveSession, detail: str, relative: float) -> FailureEvent:
        # This fallback is kept in the hot ledger when the primary database is
        # unavailable; it ensures the failure remains visible to subscribers.
        return FailureEvent(
            failureId=f"failure-storage-{uuid.uuid4().hex[:8]}",
            sessionId=session.session_id,
            streamId=session.stream_id,
            sensorId=session.sensor_id,
            type="storage_failure",
            relativeTimeSec=relative,
            technicalSeverity="critical",
            observed={"error": detail},
            expected={"storage": "writable"},
            detector="session-manager",
            detectorVersion="1.0.0",
            reviewState="needs_review",
        )

    async def _publish(self, session: _LiveSession, event_type: str, payload: dict[str, Any]) -> None:
        session.event_counter += 1
        relative = 0.0
        if "sample" in payload:
            relative = float(payload["sample"].get("relativeTimeSec", 0.0))
        elif "failure" in payload:
            relative = float(payload["failure"].get("relativeTimeSec", 0.0))
        event = LiveEvent(
            eventId=f"event-{session.event_counter:08d}",
            sessionId=session.session_id,
            type=event_type,
            relativeTimeSec=relative,
            payload=payload,
            createdTimestamp=time.time(),
        )
        try:
            self.recorder.record_event(event)
        except StorageError:
            session.dropped += 1
        for subscriber in list(session.subscribers):
            self._enqueue_subscriber(session, subscriber, event)

    @staticmethod
    def _enqueue_subscriber(session: _LiveSession, subscriber: asyncio.Queue[LiveEvent], event: LiveEvent) -> None:
        """Wake a WebSocket loop safely when a worker runs in another loop."""

        def put() -> None:
            if subscriber.full():
                try:
                    subscriber.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                session.dropped += 1
            try:
                subscriber.put_nowait(event)
            except asyncio.QueueFull:
                session.dropped += 1

        queue_loop = getattr(subscriber, "_loop", None)
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if queue_loop is not None and queue_loop is not current_loop and not queue_loop.is_closed():
            queue_loop.call_soon_threadsafe(put)
        else:
            put()

    async def _finalize_stopped(self, session: _LiveSession) -> None:
        if session.state == SessionState.STOPPED:
            return
        session.state = SessionState.STOPPED
        session.metadata["state"] = session.state.value
        session.metadata["stoppedTimestamp"] = time.time()
        metrics = self._metrics(session)
        self.recorder.update_session(session.session_id, session.metadata)
        report = self._report_payload(session, metrics)
        for flag in report["reviewFlags"]:
            self.recorder.record_review_flag(session.session_id, flag, {"state": session.state.value})
        self.recorder.record_summary(session.session_id, report)
        await self._publish(session, "status", {"state": session.state.value, "metrics": metrics})
        session.subscribers.clear()

    async def stop(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        if session.state == SessionState.STOPPED:
            return self.get_session(session_id)
        session.stop_requested = True
        session.source.cancel()
        task = session.run_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        session.run_task = None
        await self._finalize_stopped(session)
        return self.get_session(session_id)

    def inject_fault(self, session_id: str, fault: FaultSpec | dict[str, Any] | str) -> dict[str, Any]:
        session = self._session(session_id)
        if not isinstance(session.source, VirtualSource):
            raise ValueError("fault injection is available only for virtual sessions")
        parsed = session.source.add_fault(fault)
        session.metadata.setdefault("faults", []).append(parsed.model_dump(by_alias=True, mode="json"))
        self.recorder.record_raw(session_id, "fault_injection", parsed.model_dump(by_alias=True, mode="json"))
        return {"sessionId": session_id, "fault": parsed.model_dump(by_alias=True, mode="json")}

    def subscribe(self, session_id: str) -> asyncio.Queue[LiveEvent]:
        session = self._session(session_id)
        queue: asyncio.Queue[LiveEvent] = asyncio.Queue(maxsize=self.max_subscriber_queue)
        session.subscribers.add(queue)
        # A subscriber joining after creation still receives an immediate
        # lifecycle snapshot, avoiding a silent WebSocket while a source is
        # between samples.
        queue.put_nowait(
            LiveEvent(
                eventId=f"event-subscribe-{session.session_id}-{session.event_counter}",
                sessionId=session.session_id,
                type="status",
                payload={"state": session.state.value, "metrics": self._metrics(session)},
                createdTimestamp=time.time(),
            )
        )
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[LiveEvent]) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.subscribers.discard(queue)

    def _metrics(self, session: _LiveSession) -> dict[str, Any]:
        return session.detector.metrics(
            queue_depth=session.queue.qsize() if session.queue is not None else 0,
            dropped=session.dropped,
            source_complete=session.source_complete,
        ) if session.detector else {}

    def metrics(self, session_id: str) -> dict[str, Any]:
        return self._metrics(self._session(session_id))

    def hot_cache_size(self, session_id: str) -> int:
        return len(self._session(session_id).hot_samples)

    def _report_payload(self, session: _LiveSession, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
        metrics = metrics or self._metrics(session)
        failures = self.recorder.get_failures(session.session_id)
        review_flags: list[str] = []
        if failures:
            review_flags.append("technical-failures-present")
        if metrics.get("missing", 0) or metrics.get("dropped", 0):
            review_flags.append("window-uncertain")
        if session.state in (SessionState.RECONNECTING, SessionState.FAILED):
            review_flags.append("connection-review-required")
        if failures:
            summary = "The stream experienced technical quality issues; affected windows were marked for review."
        elif metrics.get("sourceComplete"):
            summary = "The virtual stream completed without detected technical failures."
        else:
            summary = "The virtual stream is active; incoming windows are being monitored."
        if metrics.get("missing", 0):
            summary = "The stream lost samples briefly; the system marked the window uncertain."
        technical = (
            f"Received {metrics.get('received', 0)} samples; expected sequence extent is "
            f"{metrics.get('expected', 0)}. Missing={metrics.get('missing', 0)}, "
            f"duplicates={metrics.get('duplicates', 0)}, out-of-order={metrics.get('outOfOrder', 0)}."
        )
        return {
            "sessionId": session.session_id,
            "state": session.state.value,
            "summary": summary,
            "technicalSummary": technical,
            "metrics": metrics,
            "reviewFlags": review_flags,
            "failureCount": len(failures),
        }

    def get_report(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is not None:
            return SessionReport.model_validate(self._report_payload(session)).to_dict()
        metadata = self._stored_metadata(session_id)
        persisted = self.recorder.get_latest_summary(session_id)
        if persisted is not None:
            return SessionReport.model_validate(persisted).to_dict()
        failures = self.recorder.get_failures(session_id)
        samples = self.recorder.get_samples(session_id)
        metrics = {
            "expected": round(float(metadata.get("durationSec", 0)) * float(metadata.get("sampleRateHz", 0))),
            "received": len(samples),
            "missing": 0,
            "duplicates": 0,
            "outOfOrder": 0,
            "disconnects": 0,
            "reconnects": 0,
            "sourceComplete": False,
        }
        report = {
            "sessionId": session_id,
            "state": metadata.get("state", SessionState.FAILED.value),
            "summary": "This recorded session does not have a finalized summary; review the stored evidence before using it.",
            "technicalSummary": f"Received {len(samples)} samples; {len(failures)} failure records are stored.",
            "metrics": metrics,
            "reviewFlags": ["summary-not-finalized"],
            "failureCount": len(failures),
        }
        return SessionReport.model_validate(report).to_dict()

    def get_failures(self, session_id: str) -> list[dict[str, Any]]:
        self._stored_metadata(session_id)
        return [failure.to_dict() for failure in self.recorder.get_failures(session_id)]

    def get_session(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            metadata = self._stored_metadata(session_id)
            report = self.recorder.get_latest_summary(session_id)
            payload = dict(metadata)
            payload.update({
                "state": metadata.get("state", "stopped"),
                "metrics": (report or {}).get("metrics", {}),
                "hotCacheSize": 0,
                "hotCacheLimit": self.max_hot_samples,
                "failureCount": self.recorder.count("failures", session_id),
                "historical": True,
            })
            return payload
        payload = dict(session.metadata)
        payload.update({"state": session.state.value, "metrics": self._metrics(session)})
        payload["hotCacheSize"] = len(session.hot_samples)
        payload["hotCacheLimit"] = self.max_hot_samples
        payload["failureCount"] = self.recorder.count("failures", session_id)
        return payload

    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        """List durable sessions for a future history/review interface."""

        return self.recorder.list_sessions(limit)

    def get_samples(self, session_id: str) -> list[LiveSample]:
        self._stored_metadata(session_id)
        return self.recorder.get_samples(session_id)

    def replay(self, session_id: str, *, no_wait: bool = True, speed: float = 1.0) -> ReplaySource:
        self._stored_metadata(session_id)
        return ReplaySource(self.recorder.get_samples(session_id), no_wait=no_wait, speed=speed)

    def export_data(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        metadata = session.metadata if session is not None else self._stored_metadata(session_id)
        normalized_samples = self.get_samples(session_id)
        return {
            "manifest": {
                "schemaVersion": "2.0",
                "sessionId": session_id,
                "sourceType": metadata.get("sourceType", "virtual"),
                "recordedAt": time.time(),
                "files": [
                    "manifest.json",
                    "session-report.md",
                    "session-report.json",
                    "session-metadata.json",
                    "sensor-metadata.json",
                    "normalized-samples.csv",
                    "failure-events.json",
                    "failure-events.csv",
                    "quality-events.json",
                    "algorithm-events.json",
                    "raw-records.json",
                    "checksums.json",
                ],
            },
            "metadata": metadata,
            "sensorMetadata": {
                "sensorId": metadata.get("sensorId", ""),
                "streamId": metadata.get("streamId", ""),
                "sourceType": metadata.get("sourceType", "virtual"),
                "units": normalized_samples[0].units if normalized_samples else {},
            },
            "report": self.get_report(session_id),
            "samples": [sample.to_dict() for sample in normalized_samples],
            "failures": self.get_failures(session_id),
            "events": [event.to_dict() for event in self.recorder.get_events(session_id)],
            "raw": self.recorder.get_raw_records(session_id),
        }

    def clear_process_sessions(self) -> None:
        self._sessions.clear()

    create = create_session
    start_session = start
    stop_session = stop


__all__ = ["SessionManager"]
