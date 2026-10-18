from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from aura_med.api.main import app  # noqa: E402
from aura_med.api.routes import run_store  # noqa: E402


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def setUp(self) -> None:
        run_store.clear()

    def test_health_and_service_info(self) -> None:
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(self.client.get("/").json()["service"], "aura-med-backend")

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
