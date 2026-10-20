"""Dataclasses shared by the Nivora domain modules.

The Python attributes use snake_case.  :meth:`SimulationRun.to_dict` emits the
camelCase schema used by the original local-first engine, so the API layer can
serialize a complete run without knowing the implementation details.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Literal, TypeAlias

ScenarioId: TypeAlias = str
AlgorithmId: TypeAlias = str
ChannelId: TypeAlias = str
ClassificationState: TypeAlias = Literal[
    "NOMINAL",
    "LOW_CONFIDENCE_CHANGE",
    "ARTIFACT_CONSISTENT_ANOMALY",
    "MULTI_SIGNAL_SUPPORTED_EVENT",
    "HIGH_EVIDENCE_MULTI_SIGNAL_CHANGE",
    "INSUFFICIENT_EVIDENCE",
]
AnnotationKind: TypeAlias = Literal[
    "simulated-event", "sensor-artifact", "sensor-disconnection"
]
ReasonCode: TypeAlias = str


def _camel_case(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def to_jsonable(value: Any) -> Any:
    """Convert domain dataclasses to JSON-compatible values without dropping None."""

    if is_dataclass(value) and not isinstance(value, type):
        return {
            _camel_case(item.name): to_jsonable(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class RunConfig:
    scenario: ScenarioId
    duration_sec: int
    sample_rate_hz: int
    artifact_intensity: float
    algorithms: list[AlgorithmId]
    seed: int
    initial_trust: float = 0.8
    quality_window_samples: int = 8
    baseline_window_samples: int = 8
    required_persistence_samples: int = 3


@dataclass
class SimulatedVitalSignal:
    channel: ChannelId
    unit: str
    values: list[float | None]


@dataclass
class SimulatedSignalSample:
    t_sec: float
    values: dict[ChannelId, float | None]


@dataclass
class GeneratedSignals:
    """Intermediate generator result before analysis and algorithms run."""

    samples: list[SimulatedSignalSample]
    signals: list[SimulatedVitalSignal]
    annotations: list[SimulatedGroundTruthAnnotation]


@dataclass
class SimulatedGroundTruth:
    physiological_event_exists: bool
    artifact_exists: bool
    affected_channels: list[ChannelId]
    event_start_sec: float | None
    event_end_sec: float | None
    artifact_start_sec: float | None
    artifact_end_sec: float | None
    expected_evidence_quality: Literal["high", "mixed", "low", "unavailable"]
    known_limitation: str


@dataclass
class SimulatedGroundTruthAnnotation:
    id: str
    kind: AnnotationKind
    label: str
    start_sec: float
    end_sec: float
    channels: list[ChannelId]
    severity: Literal["low", "medium", "high"] | None = None


Annotation = SimulatedGroundTruthAnnotation


@dataclass
class SimulatedScenarioDefinition:
    id: ScenarioId
    label: str
    description: str
    default_duration_sec: int
    ground_truth: SimulatedGroundTruth
    annotations: list[SimulatedGroundTruthAnnotation]


@dataclass
class SignalQualityFeatures:
    short_window_stability: float
    value_plausibility: float
    continuity: float
    missing_data_penalty: float
    artifact_penalty: float
    cross_sensor_consistency: float
    missing_fraction: float
    noise_estimate: float
    artifact_overlap: float


@dataclass
class SignalQuality:
    channel: ChannelId
    score: float
    features: SignalQualityFeatures
    reason_codes: list[ReasonCode]


ChannelQuality = SignalQuality


@dataclass
class SensorTrust:
    channel: ChannelId
    score: float
    previous_score: float
    direction: Literal["decreasing", "stable", "recovering"]
    quality_contribution: float
    agreement_contribution: float


@dataclass
class SimulatedRollingBaseline:
    channel: ChannelId
    value: float | None
    deviation: float | None
    trend_per_sample: float | None
    persistent_deviation: bool
    recovery_detected: bool
    history_count: int


@dataclass
class EvidenceWindow:
    window_id: str
    start_sec: float
    end_sec: float
    quality: list[SignalQuality]
    trust_by_channel: dict[ChannelId, SensorTrust]
    baseline_by_channel: dict[ChannelId, SimulatedRollingBaseline]
    cross_signal_agreement: float
    unavailable_channels: list[ChannelId]
    contradictory_evidence: bool


@dataclass
class AlgorithmInput:
    window_id: str
    sample: SimulatedSignalSample
    quality: list[SignalQuality]
    trust_by_channel: dict[ChannelId, SensorTrust]
    baseline_by_channel: dict[ChannelId, SimulatedRollingBaseline]
    cross_signal_agreement: float
    unavailable_channels: list[ChannelId]
    contradictory_evidence: bool
    required_persistence_samples: int
    sample_interval_sec: float = 1.0
    duration_sec: float | None = None


@dataclass
class StructuredExplanation:
    title: str
    detail: str
    reason_codes: list[ReasonCode]
    evidence_window_id: str
    values: dict[str, float | str | bool | None]


@dataclass
class AlgorithmOutput:
    algorithm_id: AlgorithmId
    window_id: str
    start_sec: float
    end_sec: float
    classification: ClassificationState
    confidence: float
    channels: list[ChannelId]
    reason_codes: list[ReasonCode]
    explanation: StructuredExplanation


@dataclass
class Prediction:
    start_sec: float
    end_sec: float
    label: str
    kind: Literal["prediction"]
    source_id: str
    algorithm_id: AlgorithmId
    prediction_id: str
    classification: ClassificationState
    confidence: float
    channels: list[ChannelId]
    reason_codes: list[ReasonCode]
    explanation: StructuredExplanation


@dataclass
class TrustSnapshot:
    t_sec: float
    agreement: float
    trust_by_channel: dict[ChannelId, SensorTrust]


@dataclass
class BenchmarkMetrics:
    total_alerts: int
    nuisance_alerts: int
    detected_simulated_events: int
    missed_simulated_events: int
    detection_latency_sec: list[float | None]
    uncertainty_classification_count: int
    uncertain_window_count: int
    uncertain_duration_sec: float
    trust_recovery_time_sec: list[float | None]
    explanation_completeness: float
    truth_event_count: int
    prediction_count: int
    artifact_end_sec: float


@dataclass
class AlgorithmResult:
    algorithm_id: AlgorithmId
    algorithm_name: str
    outputs: list[AlgorithmOutput]
    predictions: list[Prediction]
    metrics: BenchmarkMetrics


@dataclass
class ExplanationItem:
    algorithm_id: AlgorithmId
    classification: ClassificationState
    start_sec: float
    end_sec: float
    title: str
    detail: str
    reason_codes: list[ReasonCode]
    evidence_window_id: str
    values: dict[str, float | str | bool | None]


@dataclass
class SimulationRun:
    schema_version: Literal["1.0"]
    run_id: str
    seed: int
    config: RunConfig
    scenario: SimulatedScenarioDefinition
    signals: list[SimulatedVitalSignal]
    samples: list[SimulatedSignalSample]
    annotations: list[SimulatedGroundTruthAnnotation]
    evidence: list[EvidenceWindow]
    results: list[AlgorithmResult]
    explanations: list[ExplanationItem]

    def to_dict(self) -> dict[str, Any]:
        """Return the complete stable JSON-shaped simulation run."""

        return to_jsonable(self)


__all__ = [
    "ScenarioId",
    "AlgorithmId",
    "ChannelId",
    "ClassificationState",
    "AnnotationKind",
    "ReasonCode",
    "RunConfig",
    "SimulatedVitalSignal",
    "SimulatedSignalSample",
    "GeneratedSignals",
    "SimulatedGroundTruth",
    "SimulatedGroundTruthAnnotation",
    "Annotation",
    "SimulatedScenarioDefinition",
    "SignalQualityFeatures",
    "SignalQuality",
    "ChannelQuality",
    "SensorTrust",
    "SimulatedRollingBaseline",
    "EvidenceWindow",
    "AlgorithmInput",
    "StructuredExplanation",
    "AlgorithmOutput",
    "Prediction",
    "TrustSnapshot",
    "BenchmarkMetrics",
    "AlgorithmResult",
    "ExplanationItem",
    "SimulationRun",
    "to_jsonable",
]
