from __future__ import annotations

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from aura_med.experiments import (  # noqa: E402
    ALGORITHM_CATALOG,
    ExperimentSpec,
    run_experiment_batch,
)


def spec(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "suiteId": "phase-1-fixture",
        "scenarios": ["stable-baseline", "simulated-event"],
        "seeds": [7, 11],
        "baseConfig": {
            "durationSec": 20,
            "sampleRateHz": 1,
            "artifactIntensity": 0.48,
        },
        "algorithms": ["threshold-baseline", "reliability-aware"],
    }
    value.update(overrides)
    return value


class ExperimentEngineTests(unittest.TestCase):
    def test_same_spec_produces_byte_equivalent_batches(self) -> None:
        first = run_experiment_batch(spec())
        second = run_experiment_batch(
            {
                "algorithms": ["threshold-baseline", "reliability-aware"],
                "base_config": {
                    "artifactIntensity": 0.48,
                    "sampleRateHz": 1,
                    "durationSec": 20,
                },
                "seeds": [7, 11],
                "scenarios": ["stable-baseline", "simulated-event"],
                "suite_id": "phase-1-fixture",
            }
        )
        first_bytes = json.dumps(first.to_dict(), ensure_ascii=False, separators=(",", ":"))
        second_bytes = json.dumps(second.to_dict(), ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(first_bytes, second_bytes)

    def test_cartesian_run_count_and_order(self) -> None:
        batch = run_experiment_batch(spec())
        self.assertEqual(
            [(receipt.scenario, receipt.seed) for receipt in batch.run_receipts],
            [
                ("stable-baseline", 7),
                ("stable-baseline", 11),
                ("simulated-event", 7),
                ("simulated-event", 11),
            ],
        )
        for receipt in batch.run_receipts:
            self.assertEqual(
                list(receipt.algorithm_metrics),
                ["threshold-baseline", "reliability-aware"],
            )

    def test_aggregation_denominators_and_metrics(self) -> None:
        batch = run_experiment_batch(spec())
        summary = batch.algorithm_summaries["threshold-baseline"]
        self.assertEqual(summary.total_runs, 4)
        self.assertEqual(summary.metrics["total_runs"].count, 4)
        self.assertEqual(summary.metrics["total_runs"].total, 4.0)
        self.assertEqual(summary.metrics["total_runs"].denominator_label, "runs")
        self.assertEqual(
            summary.total_truth_events,
            summary.detected_events + summary.missed_events,
        )
        self.assertEqual(
            summary.detection_rate.denominator,
            summary.total_truth_events,
        )
        self.assertIn("nuisance_alerts_per_hour", summary.metrics)
        self.assertIn("uncertain_fraction", summary.metrics)
        self.assertIn("explanation_completeness", summary.metrics)

    def test_zero_event_and_zero_latency_are_null(self) -> None:
        batch = run_experiment_batch(
            spec(scenarios=["stable-baseline"], seeds=[1])
        )
        summary = batch.algorithm_summaries["reliability-aware"]
        self.assertEqual(summary.total_truth_events, 0)
        self.assertIsNone(summary.detection_rate.mean)
        self.assertIsNone(summary.detection_rate.confidence_interval_95)
        self.assertEqual(summary.mean_detected_latency_sec.count, 0)
        self.assertIsNone(summary.mean_detected_latency_sec.mean)
        self.assertIsNone(summary.mean_detected_latency_sec.total)
        receipt_metrics = batch.run_receipts[0].algorithm_metrics["reliability-aware"]
        self.assertEqual(receipt_metrics.detection_latency_sec, [])
        self.assertIsNone(receipt_metrics.mean_detected_latency_sec)

    def test_wilson_and_normal_confidence_interval_bounds(self) -> None:
        batch = run_experiment_batch(
            spec(baseConfig={"durationSec": 90, "sampleRateHz": 1, "artifactIntensity": 0.48})
        )
        detection = batch.algorithm_summaries["reliability-aware"].detection_rate
        self.assertEqual(detection.confidence_interval_95.method, "wilson")
        self.assertLessEqual(0, detection.confidence_interval_95.lower)
        self.assertLessEqual(detection.confidence_interval_95.upper, 1)

        explanation = batch.algorithm_summaries["reliability-aware"].explanation_completeness
        self.assertEqual(explanation.confidence_interval_95.method, "normal-approximation")
        self.assertLessEqual(explanation.confidence_interval_95.lower, explanation.mean)
        self.assertLessEqual(explanation.mean, explanation.confidence_interval_95.upper)

    def test_validation_errors(self) -> None:
        invalid_specs = [
            spec(scenarios=[]),
            spec(seeds=[]),
            spec(algorithms=[]),
            spec(scenarios=["not-a-scenario"]),
            spec(algorithms=["not-an-algorithm"]),
            spec(seeds=[1.0]),
            spec(scenarios=["stable-baseline"] * 11, seeds=list(range(10))),
        ]
        for invalid in invalid_specs:
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    run_experiment_batch(invalid)
        with self.assertRaises(ValueError):
            run_experiment_batch({"suiteId": "missing-fields"})
        with self.assertRaises(ValueError):
            ExperimentSpec("", ["stable-baseline"], [1], {}, ["threshold-baseline"])

    def test_manifest_provenance_and_camel_case_serialization(self) -> None:
        batch = run_experiment_batch(spec())
        manifest = batch.manifest
        self.assertEqual(manifest["schemaVersion"], "1.0")
        self.assertEqual(manifest["experimentId"], batch.experiment_id)
        self.assertEqual(manifest["suiteId"], "phase-1-fixture")
        self.assertEqual(manifest["scenarioIds"], ["stable-baseline", "simulated-event"])
        self.assertEqual(manifest["seeds"], [7, 11])
        self.assertEqual(manifest["runIds"], [receipt.run_id for receipt in batch.run_receipts])
        self.assertIn("not clinical performance", manifest["note"].lower())
        payload = batch.to_dict()
        self.assertIn("runReceipts", payload)
        self.assertIn("algorithmSummaries", payload)
        self.assertIn("baseConfig", payload["spec"])
        self.assertNotIn("run_receipts", json.dumps(payload))

    def test_algorithm_metadata_is_static_and_provenant(self) -> None:
        self.assertEqual(
            list(ALGORITHM_CATALOG),
            ["threshold-baseline", "reliability-aware"],
        )
        for algorithm_id, metadata in ALGORITHM_CATALOG.items():
            self.assertEqual(metadata["id"], algorithm_id)
            self.assertRegex(metadata["version"], r"^\d+\.\d+\.\d+$")
            self.assertNotIn("timestamp", metadata)
        batch = run_experiment_batch(spec(algorithms=["reliability-aware"]))
        self.assertEqual(
            batch.manifest["algorithmMetadata"]["reliability-aware"],
            ALGORITHM_CATALOG["reliability-aware"],
        )


if __name__ == "__main__":
    unittest.main()
