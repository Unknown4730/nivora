from __future__ import annotations

import pathlib
import sys
import unittest
from copy import deepcopy
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from aura_med.api.main import app  # noqa: E402
from aura_med.api.routes import experiment_store, run_store  # noqa: E402


class FakeExperimentBatch:
    """Small test double for the engine's required batch interface."""

    def __init__(self, spec: dict[str, object]) -> None:
        suite_id = spec["suite_id"]
        scenarios = spec["scenarios"]
        seeds = spec["seeds"]
        algorithms = spec["algorithms"]
        self.experiment_id = f"EXP-{suite_id}-001"
        self._payload = {
            "schemaVersion": "1.0",
            "experimentId": self.experiment_id,
            "suiteId": suite_id,
            "scenarios": scenarios,
            "seeds": seeds,
            "algorithms": algorithms,
            "runs": [
                {"scenario": scenario, "seed": seed, "algorithmIds": algorithms}
                for scenario in scenarios
                for seed in seeds
            ],
            "manifest": {
                "schemaVersion": "1.0",
                "experimentId": self.experiment_id,
                "suiteId": suite_id,
                "scenarios": scenarios,
                "seeds": seeds,
                "algorithms": algorithms,
            },
        }

    def to_dict(self) -> dict[str, object]:
        return deepcopy(self._payload)


def fake_run_experiment_batch(spec: dict[str, object]) -> FakeExperimentBatch:
    if "unknown" in spec["algorithms"] or "unknown" in spec["scenarios"]:
        raise ValueError("Unknown experiment selection")
    return FakeExperimentBatch(spec)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def setUp(self) -> None:
        run_store.clear()
        experiment_store.clear()

    def test_health_and_service_info(self) -> None:
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(self.client.get("/").json()["service"], "nivora-backend")

    def test_scenario_catalog_exposes_all_domain_scenarios(self) -> None:
        response = self.client.get("/api/v1/scenarios")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["scenarios"]), 6)
        self.assertEqual(
            {item["id"] for item in payload["scenarios"]},
            {
                "stable-baseline",
                "loose-spo2-sensor",
                "motion-artifact",
                "simulated-event",
                "gradual-deterioration",
                "multi-sensor-dropout",
            },
        )

    def test_algorithm_metadata_is_versioned(self) -> None:
        catalog = [
            {
                "id": "threshold-baseline",
                "name": "Threshold baseline",
                "version": "1.0.0",
            },
            {
                "id": "reliability-aware",
                "name": "Reliability-aware comparison arm",
                "version": "1.0.0",
            },
        ]
        with patch("aura_med.api.routes.ALGORITHM_CATALOG", catalog):
            response = self.client.get("/api/v1/algorithms")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"schemaVersion": "1.0", "algorithms": catalog})

    def test_create_read_and_manifest_for_multi_run_experiment(self) -> None:
        request = {
            "suite_id": "phase-1",
            "scenarios": ["stable-baseline", "motion-artifact"],
            "seeds": [11, 22],
            "base_config": {"durationSec": 4, "sampleRateHz": 2},
            "algorithms": ["threshold-baseline", "reliability-aware"],
        }
        with patch(
            "aura_med.api.routes.run_experiment_batch",
            side_effect=fake_run_experiment_batch,
        ):
            created = self.client.post("/api/v1/experiments", json=request)
            self.assertEqual(created.status_code, 201)
            batch = created.json()
            experiment_id = batch["experimentId"]

            fetched = self.client.get(f"/api/v1/experiments/{experiment_id}")
            manifest = self.client.get(f"/api/v1/experiments/{experiment_id}/manifest")

        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json(), batch)
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json(), batch["manifest"])
        self.assertEqual(len(batch["runs"]), 4)

    def test_real_engine_creates_deterministic_multi_run_batch(self) -> None:
        # Keep the fake-boundary test above independent, but also verify that
        # the registered FastAPI route reaches the actual Phase 1 engine.
        import aura_med.api.routes as routes

        request = {
            "suiteId": "phase-1-real-engine",
            "scenarios": ["stable-baseline", "simulated-event"],
            "seeds": [7, 11],
            "baseConfig": {"durationSec": 20, "sampleRateHz": 1},
            "algorithms": ["reliability-aware"],
        }
        with patch.object(routes, "run_experiment_batch", None):
            first = self.client.post("/api/v1/experiments", json=request)
            second = self.client.post("/api/v1/experiments", json=request)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        first_payload = first.json()
        self.assertEqual(first_payload, second.json())
        self.assertEqual(len(first_payload["runReceipts"]), 4)
        self.assertEqual(
            list(first_payload["algorithmSummaries"]), ["reliability-aware"]
        )

    def test_experiment_transport_and_engine_validation_are_422(self) -> None:
        empty = self.client.post(
            "/api/v1/experiments",
            json={
                "suite_id": "phase-1",
                "scenarios": [],
                "seeds": [11],
                "base_config": {},
                "algorithms": ["threshold-baseline"],
            },
        )
        self.assertEqual(empty.status_code, 422)

        with patch(
            "aura_med.api.routes.run_experiment_batch",
            side_effect=fake_run_experiment_batch,
        ):
            unknown = self.client.post(
                "/api/v1/experiments",
                json={
                    "suite_id": "phase-1",
                    "scenarios": ["unknown"],
                    "seeds": [11],
                    "base_config": {},
                    "algorithms": ["threshold-baseline"],
                },
            )
        self.assertEqual(unknown.status_code, 422)

    def test_unknown_experiment_is_explicit(self) -> None:
        self.assertEqual(self.client.get("/api/v1/experiments/EXP-missing").status_code, 404)
        self.assertEqual(
            self.client.get("/api/v1/experiments/EXP-missing/manifest").status_code,
            404,
        )

    def test_create_read_and_export_run(self) -> None:
        response = self.client.post(
            "/api/v1/simulations",
            json={
                "scenario": "multi-sensor-dropout",
                "durationSec": 4,
                "sampleRateHz": 2,
                "artifactIntensity": 0.4,
                "algorithms": ["reliability-aware"],
                "seed": 1234,
            },
        )
        self.assertEqual(response.status_code, 201)
        run = response.json()
        run_id = run["runId"]
        self.assertEqual(run["config"]["sampleRateHz"], 2)
        self.assertEqual(run["results"][0]["outputs"][0]["endSec"], 0.5)

        fetched = self.client.get(f"/api/v1/simulations/{run_id}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["runId"], run_id)

        manifest = self.client.get(f"/api/v1/simulations/{run_id}/manifest")
        self.assertEqual(manifest.status_code, 200)
        self.assertIn("benchmarkMetrics", manifest.json())

        csv = self.client.get(f"/api/v1/simulations/{run_id}/samples.csv")
        self.assertEqual(csv.status_code, 200)
        self.assertEqual(csv.headers["content-type"], "text/csv; charset=utf-8")
        self.assertIn("tSec,spo2Pct,heartRateBpm,respirationBpm", csv.text)

        json_export = self.client.get(f"/api/v1/simulations/{run_id}/run.json")
        self.assertEqual(json_export.status_code, 200)
        self.assertEqual(json_export.json()["runId"], run_id)

    def test_invalid_and_unknown_runs_are_explicit(self) -> None:
        invalid = self.client.post(
            "/api/v1/simulations",
            json={"durationSec": 0},
        )
        self.assertEqual(invalid.status_code, 422)

        unknown_scenario = self.client.post(
            "/api/v1/simulations",
            json={"scenario": "not-a-scenario"},
        )
        self.assertEqual(unknown_scenario.status_code, 422)

        missing = self.client.get("/api/v1/simulations/RUN-missing")
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
