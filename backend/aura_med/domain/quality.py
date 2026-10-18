"""Signal-quality feature calculations and rolling quality windows."""

from __future__ import annotations

import math
from typing import Any

from .models import (
    SimulatedGroundTruthAnnotation,
    SimulatedSignalSample,
    SignalQuality,
    SignalQualityFeatures,
)
from .prng import clamp, round_value
from .scenarios import CHANNELS, SIGNAL_META, annotation_overlap


def _sample_value(sample: SimulatedSignalSample | dict[str, Any], channel: str) -> float | None:
    values = sample.values if isinstance(sample, SimulatedSignalSample) else sample["values"]
    return values.get(channel)


def _sample_time(sample: SimulatedSignalSample | dict[str, Any]) -> float:
    return sample.t_sec if isinstance(sample, SimulatedSignalSample) else sample["tSec"]


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _channel_values(samples: list[SimulatedSignalSample] | list[dict[str, Any]], channel: str) -> list[float | None]:
    return [_sample_value(sample, channel) for sample in samples]


def _compute_noise_estimate(values: list[float | None], meta: dict[str, Any]) -> float:
    finite = [value for value in values if _finite(value)]
    if len(finite) < 2:
        return 0.25 if finite else 1.0
    differences = [abs(finite[index] - finite[index - 1]) for index in range(1, len(finite))]
    average_difference = sum(differences) / len(differences)
    return clamp(average_difference / (meta["deviation_scale"] * 0.8))


def _compute_stability(values: list[float | None], meta: dict[str, Any]) -> float:
    finite = [value for value in values if _finite(value)]
    if len(finite) < 2:
        return 0.55 if finite else 0.0
    mean = sum(finite) / len(finite)
    variance = sum((value - mean) ** 2 for value in finite) / len(finite)
    return clamp(1 - math.sqrt(variance) / (meta["deviation_scale"] * 0.85))


def _compute_continuity(values: list[float | None]) -> float:
    if len(values) < 2:
        return 0.5 if values else 0.0
    transitions = sum(
        1
        for index in range(1, len(values))
        if values[index] is not None and values[index - 1] is not None
    )
    return transitions / (len(values) - 1)


def _cross_sensor_consistency(
    samples: list[SimulatedSignalSample] | list[dict[str, Any]], channel: str
) -> float:
    available = [
        sum(1 for other in CHANNELS if other != channel and _sample_value(sample, other) is not None)
        for sample in samples
    ]
    if not available:
        return 0.0
    return clamp(sum(available) / (len(available) * (len(CHANNELS) - 1)))


def compute_artifact_overlap(
    start_sec: float,
    end_sec: float,
    channel: str,
    annotations: list[SimulatedGroundTruthAnnotation],
) -> float:
    return max(
        (
            annotation_overlap(start_sec, end_sec, item)
            for item in annotations
            if item.kind != "simulated-event" and channel in item.channels
        ),
        default=0.0,
    )


def compute_channel_quality(
    *,
    samples: list[SimulatedSignalSample] | list[dict[str, Any]],
    channel: str,
    start_sec: float,
    end_sec: float,
    annotations: list[SimulatedGroundTruthAnnotation],
) -> SignalQuality:
    values = _channel_values(samples, channel)
    meta = SIGNAL_META[channel]
    missing_fraction = sum(value is None for value in values) / len(values) if values else 1.0
    finite = [value for value in values if _finite(value)]
    minimum, maximum = meta["plausibility"]
    value_plausibility = (
        sum(minimum <= value <= maximum for value in finite) / len(finite) if finite else 0.0
    )
    artifact_overlap = compute_artifact_overlap(start_sec, end_sec, channel, annotations)
    features = SignalQualityFeatures(
        short_window_stability=round_value(_compute_stability(values, meta), 4),
        value_plausibility=round_value(value_plausibility, 4),
        continuity=round_value(_compute_continuity(values), 4),
        missing_data_penalty=round_value(1 - missing_fraction, 4),
        artifact_penalty=round_value(1 - artifact_overlap, 4),
        cross_sensor_consistency=round_value(_cross_sensor_consistency(samples, channel), 4),
        missing_fraction=round_value(missing_fraction, 4),
        noise_estimate=round_value(_compute_noise_estimate(values, meta), 4),
        artifact_overlap=round_value(artifact_overlap, 4),
    )
    score = quality_score(features)
    reason_codes: list[str] = []
    if score < 0.62:
        reason_codes.append("SIGNAL_QUALITY_LOW")
    if missing_fraction > 0:
        reason_codes.append("MISSING_DATA_PRESENT")
    if artifact_overlap > 0.2:
        reason_codes.append("MOTION_ARTIFACT_PRESENT")
    return SignalQuality(
        channel=channel,
        score=round_value(score, 4),
        features=features,
        reason_codes=reason_codes,
    )


def compute_quality_windows(
    samples: list[SimulatedSignalSample],
    annotations: list[SimulatedGroundTruthAnnotation],
    sample_rate_hz: float,
    window_samples: int = 8,
    duration_sec: float | None = None,
) -> list[list[SignalQuality]]:
    windows: list[list[SignalQuality]] = []
    for index, sample in enumerate(samples):
        start_index = max(0, index - window_samples + 1)
        window = samples[start_index : index + 1]
        start_sec = window[0].t_sec
        end_sec = sample.t_sec + (1 / sample_rate_hz)
        if duration_sec is not None:
            end_sec = min(end_sec, duration_sec)
        windows.append(
            [
                compute_channel_quality(
                    samples=window,
                    channel=channel,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    annotations=annotations,
                )
                for channel in CHANNELS
            ]
        )
    return windows


def quality_score(features: SignalQualityFeatures | dict[str, float]) -> float:
    get = (lambda name: getattr(features, name)) if isinstance(features, SignalQualityFeatures) else features.__getitem__
    return clamp(
        0.2 * get("short_window_stability")
        + 0.15 * get("value_plausibility")
        + 0.15 * get("continuity")
        + 0.2 * get("missing_data_penalty")
        + 0.2 * get("artifact_penalty")
        + 0.1 * get("cross_sensor_consistency")
    )
