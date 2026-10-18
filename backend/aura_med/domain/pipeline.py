"""End-to-end deterministic simulation pipeline and config boundary."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .algorithms import algorithms_for
from .baseline import compute_rolling_analyses
from .benchmark import benchmark_algorithm, merge_predictions
from .explanations import collect_explanation_items
from .generator import generate_simulated_signals
from .models import (
    AlgorithmInput,
    AlgorithmResult,
    EvidenceWindow,
    RunConfig,
    SimulationRun,
    to_jsonable,
)
from .prng import stable_hash, round_value
from .quality import compute_quality_windows
from .scenarios import CHANNELS, get_scenario_definition, normalize_scenario_id
from .trust import compute_trust_series

DEFAULTS: dict[str, Any] = {
    "duration_sec": 60,
    "sample_rate_hz": 1,
    "artifact_intensity": 0.48,
    "algorithms": ["threshold-baseline", "reliability-aware"],
    "seed": 20261018,
    "initial_trust": 0.8,
    "quality_window_samples": 8,
    "baseline_window_samples": 8,
    "required_persistence_samples": 3,
}
SUPPORTED_ALGORITHMS = {"threshold-baseline", "reliability-aware"}


def _get(config: Mapping[str, Any], snake: str, camel: str, default: Any = None) -> Any:
    if snake in config:
        return config[snake]
    if camel in config:
        return config[camel]
    return default


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive_integer(value: Any, label: str) -> int:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
        or int(value) != value
    ):
        raise ValueError(f"{label} must be a positive integer")
    return int(value)


def normalize_config(input_config: RunConfig | Mapping[str, Any] | None = None) -> RunConfig:
    """Normalize and validate a dict or :class:`RunConfig` at the domain boundary."""

    if isinstance(input_config, RunConfig):
        raw: Mapping[str, Any] = {
            "scenario": input_config.scenario,
            "duration_sec": input_config.duration_sec,
            "sample_rate_hz": input_config.sample_rate_hz,
            "artifact_intensity": input_config.artifact_intensity,
            "algorithms": input_config.algorithms,
            "seed": input_config.seed,
            "initial_trust": input_config.initial_trust,
            "quality_window_samples": input_config.quality_window_samples,
            "baseline_window_samples": input_config.baseline_window_samples,
            "required_persistence_samples": input_config.required_persistence_samples,
        }
    elif input_config is None:
        raw = {}
    elif isinstance(input_config, Mapping):
        raw = input_config
    else:
        raise TypeError("config must be a dict or RunConfig")

    scenario_value = _get(raw, "scenario", "scenario", "stable-baseline")
    if not isinstance(scenario_value, str):
        raise ValueError("scenario must be a supported scenario ID")
    scenario = normalize_scenario_id(scenario_value)
    duration_sec = _get(raw, "duration_sec", "durationSec", DEFAULTS["duration_sec"])
    sample_rate_hz = _get(raw, "sample_rate_hz", "sampleRateHz", DEFAULTS["sample_rate_hz"])
    artifact_intensity = _get(raw, "artifact_intensity", "artifactIntensity", DEFAULTS["artifact_intensity"])
    algorithms = _get(raw, "algorithms", "algorithms", DEFAULTS["algorithms"])
    seed = _get(raw, "seed", "seed", DEFAULTS["seed"])
    initial_trust = _get(raw, "initial_trust", "initialTrust", DEFAULTS["initial_trust"])
    quality_window_samples = _get(raw, "quality_window_samples", "qualityWindowSamples", DEFAULTS["quality_window_samples"])
    baseline_window_samples = _get(raw, "baseline_window_samples", "baselineWindowSamples", DEFAULTS["baseline_window_samples"])
    required_persistence_samples = _get(raw, "required_persistence_samples", "requiredPersistenceSamples", DEFAULTS["required_persistence_samples"])

    duration_sec = _positive_integer(duration_sec, "durationSec")
    sample_rate_hz = _positive_integer(sample_rate_hz, "sampleRateHz")
    if not _finite_number(artifact_intensity) or not 0 <= artifact_intensity <= 1:
        raise ValueError("artifactIntensity must be between 0 and 1")
    if not _finite_number(seed) or int(seed) != seed:
        raise ValueError("seed must be a finite integer")
    if not _finite_number(initial_trust) or not 0 <= initial_trust <= 1:
        raise ValueError("initialTrust must be finite and between 0 and 1")
    quality_window_samples = _positive_integer(quality_window_samples, "qualityWindowSamples")
    baseline_window_samples = _positive_integer(baseline_window_samples, "baselineWindowSamples")
    required_persistence_samples = _positive_integer(required_persistence_samples, "requiredPersistenceSamples")
    if not isinstance(algorithms, (list, tuple)) or not algorithms:
        raise ValueError("At least one algorithm must be selected")
    if any(not isinstance(item, str) or item not in SUPPORTED_ALGORITHMS for item in algorithms):
        raise ValueError("Unknown algorithm selection")
    unique_algorithms = list(dict.fromkeys(algorithms))
    return RunConfig(
        scenario=scenario,
        duration_sec=duration_sec,
        sample_rate_hz=sample_rate_hz,
        artifact_intensity=float(artifact_intensity),
        algorithms=unique_algorithms,
        seed=int(seed),
        initial_trust=float(initial_trust),
        quality_window_samples=quality_window_samples,
        baseline_window_samples=baseline_window_samples,
        required_persistence_samples=required_persistence_samples,
    )


def _make_evidence(
    samples,
    quality_windows,
    analyses,
    trust_series,
    config: RunConfig,
) -> list[EvidenceWindow]:
    evidence: list[EvidenceWindow] = []
    interval = 1 / config.sample_rate_hz
    for index, sample in enumerate(samples):
        if sample.t_sec >= config.duration_sec:
            continue
        baseline_by_channel = {channel: analyses[channel][index] for channel in CHANNELS}
        unavailable_channels = [channel for channel in CHANNELS if sample.values.get(channel) is None]
        changed = sum(
            abs(analyses[channel][index].deviation or 0) > 0 for channel in CHANNELS
        )
        contradictory_evidence = changed >= 2 and trust_series[index].agreement < 0.3
        evidence.append(
            EvidenceWindow(
                window_id=f"window-{index}",
                start_sec=round_value(sample.t_sec, 4),
                end_sec=round_value(min(config.duration_sec, sample.t_sec + interval), 4),
                quality=quality_windows[index],
                trust_by_channel=trust_series[index].trust_by_channel,
                baseline_by_channel=baseline_by_channel,
                cross_signal_agreement=trust_series[index].agreement,
                unavailable_channels=unavailable_channels,
                contradictory_evidence=contradictory_evidence,
            )
        )
    return evidence


def create_simulation_run(config: dict[str, Any] | RunConfig | None = None) -> SimulationRun:
    """Create a complete serializable deterministic simulation run."""

    normalized = normalize_config(config)
    scenario = get_scenario_definition(normalized.scenario, normalized.duration_sec)
    generated = generate_simulated_signals(normalized, scenario)
    samples, signals, annotations = generated.samples, generated.signals, generated.annotations
    analyses = compute_rolling_analyses(
        samples,
        normalized.baseline_window_samples,
        normalized.required_persistence_samples,
    )
    quality_windows = compute_quality_windows(
        samples,
        annotations,
        normalized.sample_rate_hz,
        normalized.quality_window_samples,
        normalized.duration_sec,
    )
    trust_series = compute_trust_series(
        samples=samples,
        quality_windows=quality_windows,
        analyses=analyses,
        initial_trust=normalized.initial_trust,
    )
    evidence = _make_evidence(samples, quality_windows, analyses, trust_series, normalized)
    algorithm_results: list[AlgorithmResult] = []
    interval = 1 / normalized.sample_rate_hz
    for algorithm in algorithms_for(normalized.algorithms):
        outputs = [
            algorithm.classify(
                AlgorithmInput(
                    window_id=window.window_id,
                    sample=samples[index],
                    quality=window.quality,
                    trust_by_channel=window.trust_by_channel,
                    baseline_by_channel=window.baseline_by_channel,
                    cross_signal_agreement=window.cross_signal_agreement,
                    unavailable_channels=window.unavailable_channels,
                    contradictory_evidence=window.contradictory_evidence,
                    required_persistence_samples=normalized.required_persistence_samples,
                    sample_interval_sec=interval,
                    duration_sec=normalized.duration_sec,
                )
            )
            for index, window in enumerate(evidence)
        ]
        predictions = merge_predictions(outputs, algorithm.id)
        metrics = benchmark_algorithm(
            truth_annotations=annotations,
            outputs=outputs,
            predictions=predictions,
            trust_series=trust_series,
            artifact_annotations=[item for item in annotations if item.kind != "simulated-event"],
        )
        algorithm_results.append(
            AlgorithmResult(
                algorithm_id=algorithm.id,
                algorithm_name=algorithm.name,
                outputs=outputs,
                predictions=predictions,
                metrics=metrics,
            )
        )
    config_for_hash = {
        "durationSec": normalized.duration_sec,
        "sampleRateHz": normalized.sample_rate_hz,
        "artifactIntensity": normalized.artifact_intensity,
        "algorithms": normalized.algorithms,
        "seed": normalized.seed,
        "initialTrust": normalized.initial_trust,
        "qualityWindowSamples": normalized.quality_window_samples,
        "baselineWindowSamples": normalized.baseline_window_samples,
        "requiredPersistenceSamples": normalized.required_persistence_samples,
        "scenario": normalized.scenario,
    }
    run_id = f"RUN-{stable_hash({'config': config_for_hash, 'annotations': to_jsonable(annotations)})}"
    return SimulationRun(
        schema_version="1.0",
        run_id=run_id,
        seed=normalized.seed,
        config=normalized,
        scenario=scenario,
        signals=signals,
        samples=samples,
        annotations=annotations,
        evidence=evidence,
        results=algorithm_results,
        explanations=collect_explanation_items(algorithm_results),
    )
