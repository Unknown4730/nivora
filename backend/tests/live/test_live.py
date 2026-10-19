from __future__ import annotations

import asyncio
import csv
import io
import pathlib
import sys
import tempfile
import threading
import unittest
import uuid
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from aura_med.api.main import app  # noqa: E402
from aura_med.live.export import build_export_zip  # noqa: E402
from aura_med.live.failures import FailureDetector, FailureLedger  # noqa: E402
from aura_med.live.models import FailureType, LiveSample  # noqa: E402
from aura_med.live.session import SessionManager  # noqa: E402
from aura_med.live.source import VirtualSource  # noqa: E402
from aura_med.live.storage import SQLiteRecorder  # noqa: E402


class LiveTests(unittest.TestCase):
    def test_canonical_sample_and_failure_validation(self) -> None:
        sample = LiveSample(
            sessionId="s",
            streamId="stream",
            sensorId="sensor",
            sampleId="sample-1",
            sequenceNumber=1,
            sourceTimestamp=0.5,
            receivedTimestamp=0.5,
            processingTimestamp=0.5,
            values={"spo2": 96.0},
            units={"spo2": "%"},
        )
        self.assertEqual(sample.to_dict()["sequenceNumber"], 1)
        with self.assertRaises(ValueError):
            LiveSample.model_validate({**sample.to_dict(), "values": {"spo2": "bad"}})

    def test_virtual_source_is_deterministic_and_faults_are_explicit(self) -> None:
        faults = [
            {"type": "packet_loss", "atSamples": [2]},
            {"type": "duplicates", "atSamples": [1]},
            {"type": "out_of_order", "atSamples": [4]},
            {"type": "missing_values", "atSamples": [5], "channels": ["spo2"]},
            {"type": "out_of_range", "atSamples": [6], "channels": ["heart-rate"]},
            {"type": "jitter_delay", "atSamples": [7], "delaySec": 5},
            {"type": "disconnect_reconnect", "startSample": 8, "durationSamples": 2},
        ]
        first = VirtualSource("s", duration_sec=6, sample_rate_hz=2, seed=4, faults=faults)
        second = VirtualSource("s", duration_sec=6, sample_rate_hz=2, seed=4, faults=faults)
        self.assertEqual([item.model_dump() for item in first.samples()], [item.model_dump() for item in second.samples()])
        items = first.items()
        self.assertTrue(any(item.kind == "event" and item.event_type == "disconnect" for item in items))
        self.assertTrue(any(item.kind == "event" and item.event_type == "reconnect" for item in items))
        self.assertTrue(any("missing" in item.sample.quality_flags for item in items if item.sample))
        self.assertTrue(any("out_of_range" in item.sample.quality_flags for item in items if item.sample))
        self.assertTrue(any(item.sample and item.sample.received_timestamp > item.sample.source_timestamp for item in items))

    def test_sqlite_persistence_isolated_by_temp_directory(self) -> None:
        first_dir = pathlib.Path(tempfile.mkdtemp())
        second_dir = pathlib.Path(tempfile.mkdtemp())
        first = SQLiteRecorder(data_dir=first_dir)
        second = SQLiteRecorder(data_dir=second_dir)
        sample = VirtualSource("persist", duration_sec=1, sample_rate_hz=1).samples()[0]
        first.record_session("persist", {"sessionId": "persist"})
        first.record_raw("persist", "input", {"unparsed": True})
        first.record_sample(sample)
        self.assertEqual(first.count("samples", "persist"), 1)
        self.assertEqual(first.count("raw_records", "persist"), 1)
        self.assertIsNone(second.get_session("persist"))
        first.close()
        second.close()

    def test_failure_detection_and_recovery(self) -> None:
        recorder = SQLiteRecorder(data_dir=pathlib.Path(tempfile.mkdtemp()))
        ledger = FailureLedger(recorder)
        detector = FailureDetector("s", "stream", "sensor", ledger, sample_rate_hz=1)
        source = VirtualSource("s", duration_sec=4, sample_rate_hz=1, faults=[
            {"type": "packet_loss", "atSamples": [1]},
            {"type": "disconnect_reconnect", "startSample": 2, "durationSamples": 1},
        ])
        for item in source.items():
            if item.sample:
                detector.on_sample(item.sample)
            else:
                detector.on_source_event(item.event_type or "event", payload=item.payload)
        types = {failure.failure_type for failure in recorder.get_failures("s")}
        self.assertIn(FailureType.PACKET_LOSS, types)
        self.assertIn(FailureType.TIMEOUT_DISCONNECT, types)
        self.assertIn(FailureType.RECONNECT, types)
        self.assertTrue(any(failure.status == "recovered" for failure in recorder.get_failures("s")))
        recorder.close()

    def test_session_lifecycle_event_delivery_export_and_replay(self) -> None:
        manager = SessionManager(SQLiteRecorder(data_dir=pathlib.Path(tempfile.mkdtemp())), max_hot_samples=4)
        manager.create_session(session_id="session-test", duration_sec=3, sample_rate_hz=4, faults=[{"type": "packet_loss", "atSamples": [2]}])

        async def flow() -> None:
            queue = manager.subscribe("session-test")
            await manager.start("session-test")
            event_types = []
            while not queue.empty():
                event_types.append(queue.get_nowait().event_type)
            self.assertIn("sample", event_types)
            await manager.stop("session-test")

        asyncio.run(flow())
        session = manager.get_session("session-test")
        self.assertEqual(session["state"], "stopped")
        self.assertEqual(session["hotCacheSize"], 4)
        self.assertGreater(session["failureCount"], 0)
        replay = manager.replay("session-test")
        self.assertEqual([sample.values for sample in replay.samples()], [sample.values for sample in manager.get_samples("session-test")])
        archive = build_export_zip(manager.export_data("session-test"))
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            names = set(bundle.namelist())
            for required in ("manifest.json", "session-report.md", "session-report.json", "session-metadata.json", "normalized-samples.csv", "failure-events.csv", "failure-events.json", "quality-events.json", "algorithm-events.json", "checksums.json"):
                self.assertIn(required, names)

    def test_api_live_endpoints_and_websocket(self) -> None:
        client = TestClient(app)
        session_id = f"api-live-{uuid.uuid4().hex[:8]}"
        created = client.post("/api/v1/live/sessions", json={"sessionId": session_id, "durationSec": 2, "sampleRateHz": 2, "noWait": True})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(client.get("/api/v1/live/sessions/missing").status_code, 404)
        self.assertEqual(client.post(f"/api/v1/live/sessions/{session_id}/faults", json={"type": "packet_loss", "atSamples": [1]}).status_code, 200)
        with client.websocket_connect(f"/api/v1/live/sessions/{session_id}/events") as websocket:
            self.assertEqual(websocket.receive_json()["type"], "status")
            responses: list[object] = []
            starter_client = TestClient(app)
            starter = threading.Thread(
                target=lambda: responses.append(starter_client.post(f"/api/v1/live/sessions/{session_id}/start")),
                daemon=True,
            )
            starter.start()
            event_types = {websocket.receive_json()["type"] for _ in range(3)}
            starter.join(timeout=10)
            self.assertTrue(responses)
            self.assertEqual(responses[0].status_code, 200)  # type: ignore[union-attr]
            self.assertTrue(event_types & {"sample", "quality", "algorithm"})
            starter_client.close()
        report = client.get(f"/api/v1/live/sessions/{session_id}/report")
        self.assertEqual(report.status_code, 200)
        self.assertIn("summary", report.json())
        self.assertEqual(client.get(f"/api/v1/live/sessions/{session_id}/failures").status_code, 200)
        self.assertEqual(client.get(f"/api/v1/live/sessions/{session_id}/export.zip").status_code, 200)
        self.assertEqual(client.post(f"/api/v1/live/sessions/{session_id}/stop").status_code, 200)

    def test_bounded_thousands_sample_stress(self) -> None:
        recorder = SQLiteRecorder(data_dir=pathlib.Path(tempfile.mkdtemp()))
        manager = SessionManager(recorder, max_hot_samples=32, queue_size=32)
        manager.create_session(session_id="stress", duration_sec=2000, sample_rate_hz=2, faults=[{"type": "duplicates", "every": 97}])

        async def flow() -> None:
            await manager.start("stress")

        asyncio.run(flow())
        session = manager.get_session("stress")
        self.assertLessEqual(session["hotCacheSize"], 32)
        self.assertGreater(session["metrics"]["received"], 3000)
        self.assertEqual(recorder.count("samples", "stress"), session["metrics"]["received"])
        self.assertGreaterEqual(recorder.count("failures", "stress"), 1)


if __name__ == "__main__":
    unittest.main()
