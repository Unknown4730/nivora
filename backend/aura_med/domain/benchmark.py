"""Prediction merging and benchmark metrics for simulated ground truth."""

from __future__ import annotations

from .algorithms import is_alert_classification, is_uncertain_classification
from .models import (
    AlgorithmOutput,
    BenchmarkMetrics,
    Prediction,
    SimulatedGroundTruthAnnotation,
    TrustSnapshot,
)
from .scenarios import CHANNELS
from .trust import trust_recovery_time


def _overlaps(left: object, right: object) -> bool:
    return left.start_sec < right.end_sec and right.start_sec < left.end_sec  # type: ignore[attr-defined]


def merge_predictions(outputs: list[AlgorithmOutput], algorithm_id: str | None = None) -> list[Prediction]:
    if algorithm_id is None and outputs:
        algorithm_id = outputs[0].algorithm_id
    algorithm_id = algorithm_id or "unknown"
    merged: list[Prediction] = []
    for output in outputs:
        current = merged[-1] if merged else None
        step = output.end_sec - output.start_sec
        if (
            current is not None
            and current.classification == output.classification
            and abs(current.end_sec - output.start_sec) < step + 0.0001
        ):
            current.end_sec = output.end_sec
            current.channels = list(dict.fromkeys(current.channels + output.channels))
            current.reason_codes = list(dict.fromkeys(current.reason_codes + output.reason_codes))
            current.explanation = output.explanation
        else:
            merged.append(
                Prediction(
                    start_sec=output.start_sec,
                    end_sec=output.end_sec,
                    label=output.classification,
                    kind="prediction",
                    source_id=output.window_id,
                    algorithm_id=algorithm_id,
                    prediction_id=f"{algorithm_id}-{len(merged)}",
                    classification=output.classification,
                    confidence=output.confidence,
                    channels=list(output.channels),
                    reason_codes=list(output.reason_codes),
                    explanation=output.explanation,
                )
            )
    return merged


def benchmark_algorithm(
    *,
    truth_annotations: list[SimulatedGroundTruthAnnotation],
    outputs: list[AlgorithmOutput],
    predictions: list[Prediction] | None = None,
    trust_series: list[TrustSnapshot] | None = None,
    artifact_annotations: list[SimulatedGroundTruthAnnotation] | None = None,
) -> BenchmarkMetrics:
    predictions = predictions if predictions is not None else merge_predictions(outputs)
    artifact_annotations = artifact_annotations or []
    truth_events = [item for item in truth_annotations if item.kind == "simulated-event"]
    alert_predictions = [item for item in predictions if is_alert_classification(item.classification)]
    uncertainty_predictions = [item for item in predictions if is_uncertain_classification(item.classification)]
    matched: set[str] = set()
    detection_latency_sec: list[float | None] = []
    for event in truth_events:
        candidates = sorted(
            [item for item in alert_predictions if _overlaps(event, item)],
            key=lambda item: item.start_sec,
        )
        match = next((item for item in candidates if item.prediction_id not in matched), None)
        if match is None:
            detection_latency_sec.append(None)
        else:
            matched.add(match.prediction_id)
            detection_latency_sec.append(max(0.0, match.start_sec - event.start_sec))
    nuisance_alerts = sum(
        not any(_overlaps(event, prediction) for event in truth_events)
        for prediction in alert_predictions
    )
    uncertain_duration_sec = sum(max(0.0, item.end_sec - item.start_sec) for item in uncertainty_predictions)
    artifact_end = max((item.end_sec for item in artifact_annotations), default=0.0)
    recovery_times: list[int | None] = []
    for channel in CHANNELS:
        relevant = next((item for item in artifact_annotations if channel in item.channels), None)
        if relevant is None or not trust_series:
            recovery_times.append(None)
            continue
        index = next((index for index, item in enumerate(trust_series) if item.t_sec >= relevant.end_sec), -1)
        recovery_times.append(None if index < 0 else trust_recovery_time(trust_series, channel, index))
    completeness = (
        sum(bool(item.explanation.detail and item.reason_codes) for item in outputs) / len(outputs)
        if outputs
        else 0.0
    )
    return BenchmarkMetrics(
        total_alerts=len(alert_predictions),
        nuisance_alerts=nuisance_alerts,
        detected_simulated_events=sum(item is not None for item in detection_latency_sec),
        missed_simulated_events=sum(item is None for item in detection_latency_sec),
        detection_latency_sec=detection_latency_sec,
        uncertainty_classification_count=sum(is_uncertain_classification(item.classification) for item in outputs),
        uncertain_window_count=len(uncertainty_predictions),
        uncertain_duration_sec=uncertain_duration_sec,
        trust_recovery_time_sec=recovery_times,
        explanation_completeness=completeness,
        truth_event_count=len(truth_events),
        prediction_count=len(predictions),
        artifact_end_sec=artifact_end,
    )
