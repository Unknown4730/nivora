"""Sensor trust updates and cross-signal agreement."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .models import (
    SensorTrust,
    SimulatedRollingBaseline,
    SimulatedSignalSample,
    SignalQuality,
    TrustSnapshot,
)
from .prng import clamp, round_value
from .scenarios import CHANNELS, SIGNAL_META


def compute_cross_signal_agreement(
    *,
    sample: SimulatedSignalSample,
    analyses: dict[str, SimulatedRollingBaseline],
    quality: list[SignalQuality],
) -> float:
    available = [channel for channel in CHANNELS if sample.values.get(channel) is not None]
    if len(available) < 2:
        return 0.1
    active = 0
    for channel in available:
        item = analyses.get(channel)
        ratio = 0.0 if item is None or item.deviation is None else abs(item.deviation) / SIGNAL_META[channel]["deviation_scale"]
        trend = 0.0 if item is None or item.trend_per_sample is None else abs(item.trend_per_sample)
        if ratio >= 0.55 or trend > 0.08:
            active += 1
    agreement = 1 if active == 0 else 0.35 if active == 1 else 0.72 + min(0.28, (active - 2) * 0.14)
    quality_mean = sum(item.score for item in quality) / max(1, len(quality))
    agreement *= 0.7 + quality_mean * 0.3
    return round_value(clamp(agreement), 4)


def update_sensor_trust(
    previous_score: float,
    quality_score: float,
    agreement: float,
    options: dict[str, float] | None = None,
) -> dict[str, Any]:
    options = options or {}
    decay_rate = options.get("decay_rate", options.get("decayRate", 0.34))
    recovery_rate = options.get("recovery_rate", options.get("recoveryRate", 0.08))
    target = clamp(0.7 * quality_score + 0.3 * agreement)
    rate = decay_rate if target < previous_score else recovery_rate
    score = clamp(previous_score + rate * (target - previous_score))
    epsilon = 0.001
    direction = (
        "decreasing"
        if score < previous_score - epsilon
        else "recovering"
        if score > previous_score + epsilon
        else "stable"
    )
    return {
        "score": round_value(score, 4),
        "previous_score": round_value(previous_score, 4),
        "direction": direction,
        "quality_contribution": round_value(quality_score, 4),
        "agreement_contribution": round_value(agreement, 4),
    }


def compute_trust_series(
    *,
    samples: list[SimulatedSignalSample],
    quality_windows: list[list[SignalQuality]],
    analyses: dict[str, list[SimulatedRollingBaseline]],
    initial_trust: float = 0.8,
) -> list[TrustSnapshot]:
    current = {channel: clamp(initial_trust) for channel in CHANNELS}
    series: list[TrustSnapshot] = []
    for index, sample in enumerate(samples):
        quality = quality_windows[index]
        per_channel_analysis = {channel: analyses[channel][index] for channel in CHANNELS}
        agreement = compute_cross_signal_agreement(
            sample=sample,
            analyses=per_channel_analysis,
            quality=quality,
        )
        trust_by_channel: dict[str, SensorTrust] = {}
        for channel in CHANNELS:
            channel_quality = next((item for item in quality if item.channel == channel), None)
            update = update_sensor_trust(
                current[channel],
                channel_quality.score if channel_quality is not None else 0.0,
                agreement,
            )
            current[channel] = update["score"]
            trust_by_channel[channel] = SensorTrust(channel=channel, **update)
        series.append(TrustSnapshot(t_sec=sample.t_sec, agreement=agreement, trust_by_channel=trust_by_channel))
    return series


def trust_recovery_time(
    trust_series: list[TrustSnapshot],
    channel: str,
    start_index: int,
    threshold: float = 0.72,
) -> int | None:
    start = trust_series[start_index].trust_by_channel.get(channel).score if 0 <= start_index < len(trust_series) and trust_series[start_index].trust_by_channel.get(channel) else 0.0
    if start >= threshold:
        return 0
    for index in range(start_index + 1, len(trust_series)):
        trust = trust_series[index].trust_by_channel.get(channel)
        if trust is not None and trust.score >= threshold:
            return index - start_index
    return None
