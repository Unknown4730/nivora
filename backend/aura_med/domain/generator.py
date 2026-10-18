"""Deterministic simulated signal generation."""

from __future__ import annotations

import math
from typing import Any

from .models import GeneratedSignals, RunConfig, SimulatedScenarioDefinition, SimulatedSignalSample, SimulatedVitalSignal
from .prng import clamp, create_seeded_random, round_value
from .scenarios import CHANNELS, SIGNAL_META, get_scenario_definition, is_in_interval


def _smooth_pulse(t_sec: float, start_sec: float, end_sec: float) -> float:
    if t_sec < start_sec or t_sec >= end_sec:
        return 0.0
    progress = (t_sec - start_sec) / max(0.001, end_sec - start_sec)
    return math.sin(math.pi * progress)


def _ramp(t_sec: float, start_sec: float, end_sec: float) -> float:
    if t_sec < start_sec or t_sec >= end_sec:
        return 0.0
    return clamp((t_sec - start_sec) / max(0.001, end_sec - start_sec))


def _gaussianish(random: Any) -> float:
    return (random() + random() + random() + random() - 2) / 2


def _clean_value(channel: str, t_sec: float, random: Any) -> float:
    meta = SIGNAL_META[channel]
    phase = {"spo2": 0.7, "heart-rate": 1.9, "respiration": 2.8}[channel]
    cycle = {"spo2": 0.08, "heart-rate": 0.19, "respiration": 0.32}[channel]
    amplitude = {"spo2": 0.35, "heart-rate": 2.2, "respiration": 0.8}[channel]
    noise = {"spo2": 0.12, "heart-rate": 0.8, "respiration": 0.35}[channel]
    return meta["baseline"] + math.sin(t_sec * cycle + phase) * amplitude + _gaussianish(random) * noise


def _event_delta(channel: str, t_sec: float, scenario: SimulatedScenarioDefinition) -> float:
    event = scenario.ground_truth
    if not event.physiological_event_exists or event.event_start_sec is None or event.event_end_sec is None:
        return 0.0
    if scenario.id == "gradual-deterioration":
        strength = min(
            _ramp(t_sec, event.event_start_sec, event.event_start_sec + 24),
            1 - _ramp(t_sec, event.event_end_sec - 18, event.event_end_sec),
        )
    else:
        strength = _smooth_pulse(t_sec, event.event_start_sec, event.event_end_sec)
    maximum = {"spo2": -8, "heart-rate": 25, "respiration": 9}[channel]
    return maximum * max(0.0, strength)


def _artifact_value(
    channel: str,
    value: float,
    t_sec: float,
    scenario: SimulatedScenarioDefinition,
    intensity: float,
    random: Any,
) -> float:
    artifact = next(
        (
            item
            for item in scenario.annotations
            if item.kind != "simulated-event" and channel in item.channels
        ),
        None,
    )
    if artifact is None or not is_in_interval(t_sec, artifact.start_sec, artifact.end_sec):
        return value
    level = clamp(intensity)
    motion_noise = {"spo2": 7, "heart-rate": 25, "respiration": 11}[channel] * level
    result = value + _gaussianish(random) * motion_noise
    if scenario.id == "loose-spo2-sensor" and channel == "spo2":
        result += math.sin(t_sec * 2.2) * 5 * level
        if random() < 0.12 * level:
            result = 82 if random() < 0.5 else 100
    if scenario.id == "motion-artifact" and random() < 0.1 * level:
        minimum, maximum = SIGNAL_META[channel]["plausibility"]
        result = minimum if random() < 0.5 else maximum
    return result


def _should_disconnect(channel: str, t_sec: float, scenario: SimulatedScenarioDefinition, random: Any) -> bool:
    artifact = next(
        (
            item
            for item in scenario.annotations
            if item.kind == "sensor-disconnection" and channel in item.channels
        ),
        None,
    )
    if artifact is None or not is_in_interval(t_sec, artifact.start_sec, artifact.end_sec):
        return False
    return random() < (0.96 if channel in ("spo2", "heart-rate") else 0.35)


def validate_generation_config(config: RunConfig | dict[str, Any]) -> None:
    """Validate the numeric fields needed by signal generation."""

    if isinstance(config, RunConfig):
        duration_sec = config.duration_sec
        sample_rate_hz = config.sample_rate_hz
        artifact_intensity = config.artifact_intensity
        seed = config.seed
    else:
        duration_sec = config.get("duration_sec", config.get("durationSec"))
        sample_rate_hz = config.get("sample_rate_hz", config.get("sampleRateHz"))
        artifact_intensity = config.get("artifact_intensity", config.get("artifactIntensity"))
        seed = config.get("seed")
    if not isinstance(duration_sec, (int, float)) or isinstance(duration_sec, bool) or not math.isfinite(duration_sec) or duration_sec <= 0:
        raise ValueError("durationSec must be greater than zero")
    if not isinstance(sample_rate_hz, (int, float)) or isinstance(sample_rate_hz, bool) or not math.isfinite(sample_rate_hz) or sample_rate_hz <= 0:
        raise ValueError("sampleRateHz must be greater than zero")
    if not isinstance(artifact_intensity, (int, float)) or isinstance(artifact_intensity, bool) or not math.isfinite(artifact_intensity) or not 0 <= artifact_intensity <= 1:
        raise ValueError("artifactIntensity must be between 0 and 1")
    if not isinstance(seed, (int, float)) or isinstance(seed, bool) or not math.isfinite(seed):
        raise ValueError("seed must be finite")


def generate_simulated_signals(
    config: RunConfig | dict[str, Any],
    scenario_input: SimulatedScenarioDefinition | None = None,
) -> GeneratedSignals:
    """Generate samples, channel series, and copied annotations.

    The terminal sample at ``durationSec`` is retained for signal inspection;
    the pipeline turns only samples before that boundary into evidence windows.
    """

    validate_generation_config(config)
    if isinstance(config, RunConfig):
        duration_sec = config.duration_sec
        sample_rate_hz = config.sample_rate_hz
        artifact_intensity = config.artifact_intensity
        seed = config.seed
        scenario_value = config.scenario
    else:
        duration_sec = config.get("duration_sec", config.get("durationSec"))
        sample_rate_hz = config.get("sample_rate_hz", config.get("sampleRateHz"))
        artifact_intensity = config.get("artifact_intensity", config.get("artifactIntensity"))
        seed = config.get("seed")
        scenario_value = config.get("scenario", "stable-baseline")
    scenario = scenario_input or get_scenario_definition(scenario_value, duration_sec)
    random = create_seeded_random(int(seed))
    sample_count = math.floor(duration_sec * sample_rate_hz + 0.5)
    samples: list[SimulatedSignalSample] = []
    values_by_channel: dict[str, list[float | None]] = {channel: [] for channel in CHANNELS}

    for index in range(sample_count + 1):
        t_sec = index / sample_rate_hz
        values: dict[str, float | None] = {}
        for channel in CHANNELS:
            value = _clean_value(channel, t_sec, random) + _event_delta(channel, t_sec, scenario)
            value = _artifact_value(channel, value, t_sec, scenario, artifact_intensity, random)
            if _should_disconnect(channel, t_sec, scenario, random):
                final_value = None
            else:
                minimum, maximum = SIGNAL_META[channel]["plausibility"]
                # Keep the original behavior: values are rounded whether or not
                # they are outside the educational plausibility bounds.
                final_value = round_value(value, 4) if value < minimum or value > maximum else round_value(value, 4)
            values[channel] = final_value
            values_by_channel[channel].append(final_value)
        samples.append(SimulatedSignalSample(t_sec=round_value(t_sec, 4), values=values))

    signals = [
        SimulatedVitalSignal(channel=channel, unit=SIGNAL_META[channel]["unit"], values=values_by_channel[channel])
        for channel in CHANNELS
    ]
    annotations = [
        type(item)(
            id=item.id,
            kind=item.kind,
            label=item.label,
            start_sec=item.start_sec,
            end_sec=item.end_sec,
            channels=list(item.channels),
            severity=item.severity,
        )
        for item in scenario.annotations
    ]
    return GeneratedSignals(samples=samples, signals=signals, annotations=annotations)
