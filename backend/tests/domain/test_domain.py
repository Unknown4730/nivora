from __future__ import annotations

import json
import math
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from aura_med.domain import (  # noqa: E402
    CHANNELS,
    AlgorithmOutput,
    RunConfig,
    SimulatedGroundTruthAnnotation,
    SimulatedSignalSample,
    SignalQualityFeatures,
    StructuredExplanation,
    benchmark_algorithm,
    compute_channel_quality,
    compute_rolling_baseline,
    create_simulation_run,
    get_scenario_definition,
    quality_score,
    samples_to_csv,
    serialize_simulation_run,
    update_sensor_trust,
)


def fixture(values: list[float | None]) -> list[SimulatedSignalSample]:
    return [
        SimulatedSignalSample(
            t_sec=index,
            values={"spo2": value, "heart-rate": 72, "respiration": 16},
        )
        for index, value in enumerate(values)
    ]


class DomainTests(unittest.TestCase):
    def test_determinism_and_seed_difference(self) -> None:
        config = {
            "scenario": "simulated-event",
            "durationSec": 20,
            "sampleRateHz": 2,
            "artifactIntensity": 0.4,
            "algorithms": ["threshold-baseline", "reliability-aware"],
            "seed": 1234,
        }
        first = create_simulation_run(config)
        second = create_simulation_run(config)
        self.assertEqual(serialize_simulation_run(first), serialize_simulation_run(second))
        self.assertNotEqual(
            create_simulation_run({**config, "seed": 1235}).samples,
            first.samples,
        )

    def test_scenarios_and_annotations_are_bounded_and_explicit(self) -> None:
        scenario_ids = [
            "stable-baseline",
            "loose-spo2-sensor",
            "motion-artifact",
            "simulated-event",
            "gradual-deterioration",
            "multi-sensor-dropout",
        ]
        for scenario_id in scenario_ids:
            run = create_simulation_run({"scenario": scenario_id, "durationSec": 120, "seed": 3})
            for annotation in run.annotations:
                self.assertGreaterEqual(annotation.start_sec, 0)
                self.assertLessEqual(annotation.end_sec, 120)
                self.assertLess(annotation.start_sec, annotation.end_sec)
            self.assertTrue(run.scenario.ground_truth.known_limitation)
        self.assertEqual(get_scenario_definition("motion", 60).id, "motion-artifact")
        dropout = create_simulation_run({"scenario": "multi-sensor-dropout", "durationSec": 75, "seed": 3})
        self.assertTrue(any(sample.values["spo2"] is None and sample.values["heart-rate"] is None for sample in dropout.samples))

    def test_quality_is_bounded_and_missing_is_worse(self) -> None:
        features = SignalQualityFeatures(
            short_window_stability=0.8,
            value_plausibility=0.7,
            continuity=0.9,
            missing_data_penalty=0.8,
            artifact_penalty=0.5,
            cross_sensor_consistency=0.6,
            missing_fraction=0,
            noise_estimate=0,
            artifact_overlap=0,
        )
        self.assertEqual(quality_score(features), 0.72)
        clean = compute_channel_quality(samples=fixture([96, 96.1, 95.9, 96]), channel="spo2", start_sec=0, end_sec=4, annotations=[])
        missing = compute_channel_quality(samples=fixture([96, None, None, 96]), channel="spo2", start_sec=0, end_sec=4, annotations=[])
        artifact = compute_channel_quality(
            samples=fixture([96, 96, 96, 96]),
            channel="spo2",
            start_sec=0,
            end_sec=4,
            annotations=[SimulatedGroundTruthAnnotation("a", "sensor-artifact", "artifact", 1, 3, ["spo2"])],
        )
        self.assertGreater(clean.score, missing.score)
        self.assertGreater(clean.score, artifact.score)
        self.assertEqual(missing.features.missing_fraction, 0.5)
        self.assertTrue(0 <= clean.score <= 1 and 0 <= missing.score <= 1)

    def test_trust_decay_and_recovery(self) -> None:
        degraded = update_sensor_trust(0.9, 0.1, 0.1)
        recovered = update_sensor_trust(degraded["score"], 1, 1)
        self.assertLess(degraded["score"], 0.9)
        self.assertGreater(recovered["score"], degraded["score"])
        self.assertLess(recovered["score"] - degraded["score"], 0.9 - degraded["score"])
        self.assertEqual(update_sensor_trust(-2, -1, -1)["score"], 0)
        self.assertEqual(update_sensor_trust(2, 2, 2)["score"], 1)

    def test_baseline_warms_up_without_using_current_value(self) -> None:
        analysis = compute_rolling_baseline(fixture([100, 102, 101, 100, 110]), "spo2", 3)
        self.assertIsNone(analysis[0].value)
        self.assertEqual(analysis[3].value, 101)
        self.assertEqual(analysis[4].value, 101)
        self.assertEqual(analysis[4].deviation, 9)

    def test_dropout_is_never_silently_nominal(self) -> None:
        run = create_simulation_run({
            "scenario": "multi-sensor-dropout",
            "durationSec": 75,
            "sampleRateHz": 1,
            "seed": 17,
            "algorithms": ["reliability-aware"],
        })
        outputs = run.results[0].outputs
        uncertain = [item for item in outputs if item.classification == "INSUFFICIENT_EVIDENCE"]
        self.assertTrue(uncertain)
        self.assertTrue(all("EVIDENCE_INSUFFICIENT" in item.reason_codes for item in uncertain))
        self.assertTrue(all(item.classification != "NOMINAL" for item in outputs if 42 <= item.start_sec < 60))

    def test_benchmark_matching_and_runtime_fields(self) -> None:
        truth = [
            SimulatedGroundTruthAnnotation("e1", "simulated-event", "event", 10, 15, ["spo2"]),
            SimulatedGroundTruthAnnotation("e2", "simulated-event", "event", 40, 45, ["spo2"]),
        ]

        def output(start: float, end: float, classification: str) -> AlgorithmOutput:
            return AlgorithmOutput(
                algorithm_id="reliability-aware",
                window_id=str(start),
                start_sec=start,
                end_sec=end,
                classification=classification,
                confidence=0.8,
                channels=["spo2"],
                reason_codes=["NOMINAL_SIGNAL"],
                explanation=StructuredExplanation("fixture", "fixture", ["NOMINAL_SIGNAL"], str(start), {}),
            )

        outputs = [output(12, 14, "MULTI_SIGNAL_SUPPORTED_EVENT"), output(20, 25, "LOW_CONFIDENCE_CHANGE"), output(50, 52, "HIGH_EVIDENCE_MULTI_SIGNAL_CHANGE")]
        predictions = []
        for index, item in enumerate(outputs):
            from aura_med.domain.models import Prediction

            predictions.append(Prediction(item.start_sec, item.end_sec, item.classification, "prediction", item.window_id, item.algorithm_id, f"p{index}", item.classification, item.confidence, item.channels, item.reason_codes, item.explanation))
        metrics = benchmark_algorithm(truth_annotations=truth, outputs=outputs, predictions=predictions)
        self.assertEqual(metrics.total_alerts, 2)
        self.assertEqual(metrics.nuisance_alerts, 1)
        self.assertEqual(metrics.detected_simulated_events, 1)
        self.assertEqual(metrics.missed_simulated_events, 1)
        self.assertEqual(metrics.detection_latency_sec, [2, None])
        self.assertEqual(metrics.uncertain_window_count, 1)
        self.assertEqual(metrics.uncertain_duration_sec, 5)
        run = create_simulation_run({"scenario": "stable-baseline", "durationSec": 2, "seed": 1})
        self.assertTrue(hasattr(run.results[0].metrics, "artifact_end_sec"))

    def test_half_open_boundaries_and_configured_intervals(self) -> None:
        truth = [SimulatedGroundTruthAnnotation("e1", "simulated-event", "event", 10, 15, ["spo2"])]
        output = AlgorithmOutput(
            "threshold-baseline", "p", 15, 20, "MULTI_SIGNAL_SUPPORTED_EVENT", 1, ["spo2"], [],
            StructuredExplanation("fixture", "fixture", [], "p", {}),
        )
        from aura_med.domain.models import Prediction

        prediction = Prediction(15, 20, output.classification, "prediction", "p", output.algorithm_id, "p", output.classification, 1, ["spo2"], [], output.explanation)
        metrics = benchmark_algorithm(truth_annotations=truth, outputs=[output], predictions=[prediction])
        self.assertEqual(metrics.missed_simulated_events, 1)
        self.assertEqual(metrics.nuisance_alerts, 1)

        run = create_simulation_run({"scenario": "stable-baseline", "durationSec": 3, "sampleRateHz": 2, "seed": 1})
        outputs = run.results[0].outputs
        self.assertEqual(len(run.samples), 7)
        self.assertEqual(len(outputs), 6)
        for item in outputs:
            self.assertAlmostEqual(item.end_sec - item.start_sec, 0.5)
            self.assertGreaterEqual(item.start_sec, 0)
            self.assertLessEqual(item.end_sec, 3)
        self.assertEqual(outputs[-1].end_sec, 3)

    def test_invalid_configs_and_null_serialization(self) -> None:
        invalid = [
            {"durationSec": 0},
            {"durationSec": math.inf},
            {"sampleRateHz": math.nan},
            {"artifactIntensity": 2},
            {"scenario": "unknown"},
            {"algorithms": ["unknown"]},
            {"algorithms": []},
        ]
        for config in invalid:
            with self.subTest(config=config):
                with self.assertRaises((ValueError, TypeError)):
                    create_simulation_run(config)
        run = create_simulation_run({"scenario": "multi-sensor-dropout", "durationSec": 50, "seed": 2})
        payload = run.to_dict()
        self.assertIn(None, payload["signals"][0]["values"])
        self.assertEqual(json.loads(serialize_simulation_run(run)), payload)
        self.assertEqual(samples_to_csv([SimulatedSignalSample(0, {"spo2": 0, "heart-rate": None, "respiration": 16})]), "tSec,spo2Pct,heartRateBpm,respirationBpm\n0,0,,16\n")


if __name__ == "__main__":
    unittest.main()
