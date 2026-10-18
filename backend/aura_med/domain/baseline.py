"""Rolling median baselines, trend estimates, persistence, and recovery."""

from __future__ import annotations

import math
from typing import Any

from .models import SimulatedRollingBaseline, SimulatedSignalSample
from .prng import clamp, round_value
from .scenarios import CHANNELS, SIGNAL_META


def _value(sample: SimulatedSignalSample | dict[str, Any], channel: str) -> float | None:
    values = sample.values if isinstance(sample, SimulatedSignalSample) else sample["values"]
    return values.get(channel)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _slope(values: list[tuple[float, int]]) -> float | None:
    if len(values) < 2:
        return None
    mean_x = (len(values) - 1) / 2
    mean_y = sum(item[0] for item in values) / len(values)
    numerator = sum((index - mean_x) * (item[0] - mean_y) for index, item in enumerate(values))
    denominator = sum((index - mean_x) ** 2 for index in range(len(values)))
    return numerator / denominator if denominator else 0.0


def compute_rolling_baseline(
    samples: list[SimulatedSignalSample] | list[dict[str, Any]],
    channel: str,
    window_size: int = 8,
) -> list[SimulatedRollingBaseline]:
    analysis: list[SimulatedRollingBaseline] = []
    for index, sample in enumerate(samples):
        prior = samples[max(0, index - window_size) : index]
        usable = [(_value(item, channel), offset) for offset, item in enumerate(prior)]
        usable = [(value, offset) for value, offset in usable if _finite(value)]
        minimum_history = min(4, window_size)
        baseline = _median([item[0] for item in usable]) if len(usable) >= minimum_history else None
        trend = _slope([(item[0], item[1]) for item in usable]) if len(usable) >= 3 else None
        current = _value(sample, channel)
        deviation = None if baseline is None or current is None else current - baseline
        analysis.append(
            SimulatedRollingBaseline(
                channel=channel,
                value=None if baseline is None else round_value(baseline, 4),
                deviation=None if deviation is None else round_value(deviation, 4),
                trend_per_sample=None if trend is None else round_value(trend, 5),
                persistent_deviation=False,
                recovery_detected=False,
                history_count=len(usable),
            )
        )
    return analysis


def add_persistence_and_recovery(
    analysis: list[SimulatedRollingBaseline],
    channel: str,
    required_persistence_samples: int = 3,
) -> list[SimulatedRollingBaseline]:
    scale = SIGNAL_META[channel]["deviation_scale"]
    consecutive = 0
    had_persistent = False
    result: list[SimulatedRollingBaseline] = []
    for item in analysis:
        changed = item.deviation is not None and abs(item.deviation) >= scale * 0.55
        consecutive = consecutive + 1 if changed else 0
        persistent_deviation = consecutive >= required_persistence_samples
        recovery_detected = had_persistent and not changed and item.deviation is not None
        if persistent_deviation:
            had_persistent = True
        result.append(
            SimulatedRollingBaseline(
                channel=item.channel,
                value=item.value,
                deviation=item.deviation,
                trend_per_sample=item.trend_per_sample,
                persistent_deviation=persistent_deviation,
                recovery_detected=recovery_detected,
                history_count=item.history_count,
            )
        )
    return result


def compute_rolling_analyses(
    samples: list[SimulatedSignalSample],
    window_size: int,
    required_persistence_samples: int,
) -> dict[str, list[SimulatedRollingBaseline]]:
    return {
        channel: add_persistence_and_recovery(
            compute_rolling_baseline(samples, channel, window_size),
            channel,
            required_persistence_samples,
        )
        for channel in CHANNELS
    }


def deviation_ratio(channel: str, deviation: float | None) -> float | None:
    if deviation is None:
        return None
    return clamp(abs(deviation) / SIGNAL_META[channel]["deviation_scale"])


def is_supporting_trend(channel: str, trend: float | None) -> bool:
    if trend is None:
        return False
    direction = -1 if channel == "spo2" else 1
    return trend * direction > SIGNAL_META[channel]["deviation_scale"] * 0.012


def summarize_prior_values(
    samples: list[SimulatedSignalSample] | list[dict[str, Any]], channel: str
) -> list[float]:
    return [value for sample in samples if (value := _value(sample, channel)) is not None and _finite(value)]
