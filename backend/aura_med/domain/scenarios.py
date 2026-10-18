"""Scenario recipes, signal metadata, and half-open interval helpers."""

from __future__ import annotations

from dataclasses import replace

from .models import (
    SimulatedGroundTruth,
    SimulatedGroundTruthAnnotation,
    SimulatedScenarioDefinition,
)
from .prng import clamp

CHANNELS = ["spo2", "heart-rate", "respiration"]

SIGNAL_META = {
    "spo2": {
        "label": "SpO₂",
        "unit": "%",
        "baseline": 96,
        "plausibility": (70, 100),
        "deviation_scale": 5,
    },
    "heart-rate": {
        "label": "Heart rate",
        "unit": "bpm",
        "baseline": 72,
        "plausibility": (35, 180),
        "deviation_scale": 24,
    },
    "respiration": {
        "label": "Respiration",
        "unit": "breaths/min",
        "baseline": 16,
        "plausibility": (5, 45),
        "deviation_scale": 8,
    },
}


def _annotation(
    annotation_id: str,
    kind: str,
    label: str,
    start_sec: float,
    end_sec: float,
    channels: list[str],
    severity: str | None = None,
) -> SimulatedGroundTruthAnnotation:
    return SimulatedGroundTruthAnnotation(
        id=annotation_id,
        kind=kind,  # type: ignore[arg-type]
        label=label,
        start_sec=start_sec,
        end_sec=end_sec,
        channels=list(channels),
        severity=severity,  # type: ignore[arg-type]
    )


def _ground_truth(
    physiological_event_exists: bool,
    artifact_exists: bool,
    affected_channels: list[str],
    event_start_sec: float | None,
    event_end_sec: float | None,
    artifact_start_sec: float | None,
    artifact_end_sec: float | None,
    expected_evidence_quality: str,
    known_limitation: str,
) -> SimulatedGroundTruth:
    return SimulatedGroundTruth(
        physiological_event_exists=physiological_event_exists,
        artifact_exists=artifact_exists,
        affected_channels=list(affected_channels),
        event_start_sec=event_start_sec,
        event_end_sec=event_end_sec,
        artifact_start_sec=artifact_start_sec,
        artifact_end_sec=artifact_end_sec,
        expected_evidence_quality=expected_evidence_quality,  # type: ignore[arg-type]
        known_limitation=known_limitation,
    )


def _definitions() -> dict[str, SimulatedScenarioDefinition]:
    return {
        "stable-baseline": SimulatedScenarioDefinition(
            id="stable-baseline",
            label="Stable simulated baseline",
            description="Mostly stable simulated signals with small deterministic variation.",
            default_duration_sec=60,
            ground_truth=_ground_truth(
                False,
                False,
                [],
                None,
                None,
                None,
                None,
                "high",
                "A stable simulation does not represent all possible sensor behavior.",
            ),
            annotations=[],
        ),
        "loose-spo2-sensor": SimulatedScenarioDefinition(
            id="loose-spo2-sensor",
            label="Loose SpO₂ sensor",
            description="SpO₂ is affected by a bounded artifact interval while other channels remain comparatively stable.",
            default_duration_sec=60,
            ground_truth=_ground_truth(
                False,
                True,
                ["spo2"],
                None,
                None,
                24,
                42,
                "low",
                "The simulation uses a hand-authored artifact recipe rather than a physical sensor model.",
            ),
            annotations=[
                _annotation("artifact-spo2-loose", "sensor-artifact", "Loose SpO₂ sensor artifact", 24, 42, ["spo2"], "medium")
            ],
        ),
        "motion-artifact": SimulatedScenarioDefinition(
            id="motion-artifact",
            label="Motion artifact burst",
            description="Motion-like noise and clipping affect all simulated channels for a bounded interval.",
            default_duration_sec=60,
            ground_truth=_ground_truth(
                False,
                True,
                CHANNELS,
                None,
                None,
                20,
                38,
                "low",
                "Motion is represented as deterministic noise and clipping, not measured movement.",
            ),
            annotations=[_annotation("artifact-motion", "sensor-artifact", "Motion artifact interval", 20, 38, CHANNELS, "high")],
        ),
        "simulated-event": SimulatedScenarioDefinition(
            id="simulated-event",
            label="Simulated physiological event",
            description="A coordinated simulated change is introduced without claiming a clinical interpretation.",
            default_duration_sec=90,
            ground_truth=_ground_truth(
                True,
                False,
                CHANNELS,
                34,
                58,
                None,
                None,
                "high",
                "The event shape and thresholds are educational simulation parameters, not validated medical cutoffs.",
            ),
            annotations=[_annotation("event-coordinated-change", "simulated-event", "Simulated coordinated change", 34, 58, CHANNELS, "high")],
        ),
        "gradual-deterioration": SimulatedScenarioDefinition(
            id="gradual-deterioration",
            label="Gradual simulated deterioration",
            description="Signals drift gradually from their simulated baseline and then begin recovery.",
            default_duration_sec=120,
            ground_truth=_ground_truth(
                True,
                False,
                CHANNELS,
                30,
                86,
                None,
                None,
                "high",
                "Gradual change can be missed during rolling-baseline warm-up or recovery.",
            ),
            annotations=[_annotation("event-gradual-change", "simulated-event", "Gradual simulated change", 30, 86, CHANNELS, "medium")],
        ),
        "multi-sensor-dropout": SimulatedScenarioDefinition(
            id="multi-sensor-dropout",
            label="Multi-sensor dropout",
            description="Multiple channels become unavailable, creating an insufficient-evidence interval.",
            default_duration_sec=75,
            ground_truth=_ground_truth(
                False,
                True,
                ["spo2", "heart-rate"],
                None,
                None,
                42,
                60,
                "unavailable",
                "Unavailable values cannot establish an underlying simulated physiological state.",
            ),
            annotations=[_annotation("artifact-multi-dropout", "sensor-disconnection", "Multi-sensor disconnection", 42, 60, ["spo2", "heart-rate"], "high")],
        ),
    }


ALIASES = {
    "clean": "stable-baseline",
    "motion": "motion-artifact",
    "dropout": "multi-sensor-dropout",
    "mixed": "motion-artifact",
}


def normalize_scenario_id(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Unknown simulated scenario: {value}")
    normalized = ALIASES.get(value, value)
    if normalized not in _definitions():
        raise ValueError(f"Unknown simulated scenario: {value}")
    return normalized


def _bounded(value: float | None, duration_sec: float) -> float | None:
    if value is None:
        return None
    return max(0.0, min(value, duration_sec))


def get_scenario_definition(value: str, duration_sec: float | None = None) -> SimulatedScenarioDefinition:
    scenario_id = normalize_scenario_id(value)
    definition = _definitions()[scenario_id]
    duration = definition.default_duration_sec if duration_sec is None else duration_sec
    annotations: list[SimulatedGroundTruthAnnotation] = []
    for item in definition.annotations:
        start = max(0.0, min(item.start_sec, duration))
        end = max(0.0, min(item.end_sec, duration))
        if start < end:
            annotations.append(replace(item, start_sec=start, end_sec=end, channels=list(item.channels)))
    ground_truth = replace(
        definition.ground_truth,
        affected_channels=list(definition.ground_truth.affected_channels),
        event_start_sec=_bounded(definition.ground_truth.event_start_sec, duration),
        event_end_sec=_bounded(definition.ground_truth.event_end_sec, duration),
        artifact_start_sec=_bounded(definition.ground_truth.artifact_start_sec, duration),
        artifact_end_sec=_bounded(definition.ground_truth.artifact_end_sec, duration),
    )
    return SimulatedScenarioDefinition(
        id=definition.id,
        label=definition.label,
        description=definition.description,
        default_duration_sec=definition.default_duration_sec,
        ground_truth=ground_truth,
        annotations=annotations,
    )


def is_in_interval(t_sec: float, start_sec: float, end_sec: float) -> bool:
    return t_sec >= start_sec and t_sec < end_sec


def annotation_overlap(start_sec: float, end_sec: float, annotation: SimulatedGroundTruthAnnotation) -> float:
    if end_sec <= start_sec or annotation.end_sec <= annotation.start_sec:
        return 0.0
    overlap = max(0.0, min(end_sec, annotation.end_sec) - max(start_sec, annotation.start_sec))
    return clamp(overlap / (end_sec - start_sec))
