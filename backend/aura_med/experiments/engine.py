"""Deterministic multi-scenario experiment batches.

This module is deliberately a thin orchestration layer around
``aura_med.domain.create_simulation_run``.  The domain remains the sole owner
of signal generation, algorithm execution, and per-run benchmark calculations;
this module only normalizes a suite, collects receipts, and aggregates those
domain metrics.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from ..domain import create_simulation_run, normalize_scenario_id
from ..domain.prng import stable_hash


SCHEMA_VERSION: Final[str] = "1.0"
MAX_BATCH_RUNS: Final[int] = 100
_NORMAL_CI_Z: Final[float] = 1.96


# The catalog is intentionally static.  In particular, versions are not based
# on the current time, so a manifest and experiment ID remain reproducible.
ALGORITHM_CATALOG: Final[dict[str, dict[str, str]]] = {
    "threshold-baseline": {
        "id": "threshold-baseline",
        "name": "Threshold baseline",
        "version": "1.0.0",
        "description": "Fixed SpO2 threshold comparison arm.",
    },
    "reliability-aware": {
        "id": "reliability-aware",
        "name": "Reliability-aware comparison arm",
        "version": "1.0.0",
        "description": "Comparison arm that incorporates quality, trust, and agreement.",
    },
}

_SCENARIO_IDS: Final[tuple[str, ...]] = (
    "stable-baseline",
    "loose-spo2-sensor",
    "motion-artifact",
    "simulated-event",
    "gradual-deterioration",
    "multi-sensor-dropout",
)


def _camel_case(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _camelize(value: Any) -> Any:
    """Return a deterministic JSON-shaped copy with camelCase object keys."""

    if isinstance(value, Mapping):
        return {
            _camel_case(str(key)): _camelize(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [_camelize(item) for item in value]
    return value


def _json_safe_copy(value: Any, path: str = "value") -> Any:
    """Copy supported configuration values and reject unstable values."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain only finite numbers")
        return value
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key in sorted(value, key=lambda item: str(item)):
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            copied[key] = _json_safe_copy(value[key], f"{path}.{key}")
        return copied
    if isinstance(value, (list, tuple)):
        return [_json_safe_copy(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise ValueError(f"{path} contains a value that cannot be serialized deterministically")


def _list_value(value: Any, label: str) -> list[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be a non-empty list")
    result = list(value)
    if not result:
        raise ValueError(f"{label} must be a non-empty list")
    return result


def _mapping_value(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    joined = " or ".join(keys)
    raise ValueError(f"Missing required experiment field: {joined}")


@dataclass(frozen=True)
class ExperimentSpec:
    """Validated, normalized definition of one experiment suite.

    Lists are copied during construction so a caller mutating its input after
    submission cannot change the provenance represented by a batch.
    """

    suite_id: str
    scenarios: list[str]
    seeds: list[int]
    base_config: dict[str, Any]
    algorithms: list[str]

    def __post_init__(self) -> None:
        if not isinstance(self.suite_id, str) or not self.suite_id.strip():
            raise ValueError("suite_id must be a non-empty string")

        raw_scenarios = _list_value(self.scenarios, "scenarios")
        scenarios: list[str] = []
        for scenario in raw_scenarios:
            if not isinstance(scenario, str):
                raise ValueError(f"Unsupported scenario ID: {scenario!r}")
            try:
                normalized = normalize_scenario_id(scenario)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Unsupported scenario ID: {scenario!r}") from error
            if normalized not in _SCENARIO_IDS:
                raise ValueError(f"Unsupported scenario ID: {scenario!r}")
            scenarios.append(normalized)

        raw_seeds = _list_value(self.seeds, "seeds")
        seeds: list[int] = []
        for seed in raw_seeds:
            # bool is an int subclass, but accepting True as seed 1 would make
            # provenance needlessly ambiguous.
            if not isinstance(seed, int) or isinstance(seed, bool):
                raise ValueError(f"Seed must be an integer: {seed!r}")
            seeds.append(seed)

        raw_algorithms = _list_value(self.algorithms, "algorithms")
        algorithms: list[str] = []
        for algorithm in raw_algorithms:
            if not isinstance(algorithm, str) or algorithm not in ALGORITHM_CATALOG:
                raise ValueError(f"Unsupported algorithm ID: {algorithm!r}")
            if algorithm not in algorithms:
                algorithms.append(algorithm)

        if not isinstance(self.base_config, Mapping):
            raise ValueError("base_config must be a mapping")
        base_config = _json_safe_copy(self.base_config, "base_config")

        run_count = len(scenarios) * len(seeds)
        if run_count > MAX_BATCH_RUNS:
            raise ValueError(
                f"Experiment batch has {run_count} runs; the maximum is {MAX_BATCH_RUNS}"
            )

        object.__setattr__(self, "suite_id", self.suite_id.strip())
        object.__setattr__(self, "scenarios", scenarios)
        object.__setattr__(self, "seeds", seeds)
        object.__setattr__(self, "base_config", base_config)
        object.__setattr__(self, "algorithms", algorithms)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ExperimentSpec:
        if not isinstance(value, Mapping):
            raise TypeError("experiment spec must be a mapping or ExperimentSpec")
        return cls(
            suite_id=_mapping_value(value, "suite_id", "suiteId"),
            scenarios=_mapping_value(value, "scenarios"),
            seeds=_mapping_value(value, "seeds"),
            base_config=_mapping_value(value, "base_config", "baseConfig"),
            algorithms=_mapping_value(value, "algorithms"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the normalized spec in the future API's JSON vocabulary."""

        return {
            "suiteId": self.suite_id,
            "scenarios": list(self.scenarios),
            "seeds": list(self.seeds),
            "baseConfig": _camelize(self.base_config),
            "algorithms": list(self.algorithms),
        }


@dataclass(frozen=True)
class ConfidenceInterval:
    """A deterministic two-sided 95% interval."""

    lower: float
    upper: float
    method: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "lower": self.lower,
            "upper": self.upper,
            "method": self.method,
            "confidenceLevel": 0.95,
        }


@dataclass(frozen=True)
class ScalarSummary:
    """Summary statistics for one aggregate scalar.

    ``count`` is the number of non-null observations.  ``total`` is the sum of
    observations when a sum is meaningful.  ``denominator`` identifies the
    explicit population used by a rate or run-level metric.  Normal intervals
    use ``mean +/- 1.96 * sampleStandardDeviation / sqrt(count)`` for count >=
    2. Detection rate uses the Wilson score interval over truth-event
    observations instead.
    """

    count: int
    mean: float | None
    standard_deviation: float | None
    confidence_interval_95: ConfidenceInterval | None
    total: float | None
    denominator: int | float | None
    denominator_label: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "mean": self.mean,
            "standardDeviation": self.standard_deviation,
            "confidenceInterval95": (
                self.confidence_interval_95.to_dict()
                if self.confidence_interval_95 is not None
                else None
            ),
            "total": self.total,
            "denominator": self.denominator,
            "denominatorLabel": self.denominator_label,
        }


def _clean_float(value: float) -> float:
    # Avoid negative zero in serialized research receipts.
    rounded = round(float(value), 12)
    return 0.0 if rounded == 0 else rounded


def _normal_summary(
    values: Sequence[float],
    *,
    denominator: int | float | None,
    denominator_label: str | None,
) -> ScalarSummary:
    observations = [float(value) for value in values]
    count = len(observations)
    if not observations:
        return ScalarSummary(0, None, None, None, None, denominator, denominator_label)
    mean = sum(observations) / count
    standard_deviation: float | None = None
    interval: ConfidenceInterval | None = None
    if count > 1:
        variance = sum((value - mean) ** 2 for value in observations) / (count - 1)
        standard_deviation = _clean_float(math.sqrt(max(0.0, variance)))
        margin = _NORMAL_CI_Z * standard_deviation / math.sqrt(count)
        interval = ConfidenceInterval(
            _clean_float(mean - margin),
            _clean_float(mean + margin),
            "normal-approximation",
        )
    return ScalarSummary(
        count=count,
        mean=_clean_float(mean),
        standard_deviation=standard_deviation,
        confidence_interval_95=interval,
        total=_clean_float(sum(observations)),
        denominator=denominator,
        denominator_label=denominator_label,
    )


def _wilson_summary(
    successes: int,
    trials: int,
) -> ScalarSummary:
    if trials <= 0:
        return ScalarSummary(0, None, None, None, None, 0, "truth-events")
    proportion = successes / trials
    standard_deviation = None
    if trials > 1:
        standard_deviation = _clean_float(
            math.sqrt((trials / (trials - 1)) * proportion * (1 - proportion))
        )
    z_squared = _NORMAL_CI_Z**2
    denominator = 1 + z_squared / trials
    center = (proportion + z_squared / (2 * trials)) / denominator
    half_width = (
        _NORMAL_CI_Z
        * math.sqrt(
            proportion * (1 - proportion) / trials
            + z_squared / (4 * trials**2)
        )
        / denominator
    )
    interval = ConfidenceInterval(
        _clean_float(max(0.0, center - half_width)),
        _clean_float(min(1.0, center + half_width)),
        "wilson",
    )
    return ScalarSummary(
        count=trials,
        mean=_clean_float(proportion),
        standard_deviation=standard_deviation,
        confidence_interval_95=interval,
        total=float(successes),
        denominator=trials,
        denominator_label="truth-events",
    )


@dataclass(frozen=True)
class AlgorithmRunMetrics:
    """Receipt-sized metrics derived from one domain ``AlgorithmResult``."""

    algorithm_id: str
    total_alerts: int
    truth_event_count: int
    detected_events: int
    missed_events: int
    detection_latency_sec: list[float | None]
    nuisance_alerts: int
    nuisance_alerts_per_hour: float | None
    uncertain_duration_sec: float
    uncertain_fraction: float | None
    mean_detected_latency_sec: float | None
    explanation_completeness: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithmId": self.algorithm_id,
            "totalAlerts": self.total_alerts,
            "truthEventCount": self.truth_event_count,
            "detectedEvents": self.detected_events,
            "missedEvents": self.missed_events,
            "detectionLatencySec": list(self.detection_latency_sec),
            "nuisanceAlerts": self.nuisance_alerts,
            "nuisanceAlertsPerHour": self.nuisance_alerts_per_hour,
            "uncertainDurationSec": self.uncertain_duration_sec,
            "uncertainFraction": self.uncertain_fraction,
            "meanDetectedLatencySec": self.mean_detected_latency_sec,
            "explanationCompleteness": self.explanation_completeness,
        }


@dataclass(frozen=True)
class ExperimentRunReceipt:
    """The compact, provenance-oriented output for one scenario/seed run."""

    run_id: str
    scenario: str
    seed: int
    duration_sec: int
    algorithm_metrics: dict[str, AlgorithmRunMetrics]

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "scenario": self.scenario,
            "seed": self.seed,
            "durationSec": self.duration_sec,
            "algorithmMetrics": {
                algorithm_id: metrics.to_dict()
                for algorithm_id, metrics in self.algorithm_metrics.items()
            },
        }


@dataclass(frozen=True)
class AlgorithmAggregateSummary:
    """Aggregate metrics for one algorithm across all batch runs."""

    algorithm_id: str
    algorithm_metadata: dict[str, str]
    total_runs: int
    total_truth_events: int
    detected_events: int
    missed_events: int
    metrics: dict[str, ScalarSummary]
    denominators: dict[str, int | float]

    @property
    def detection_rate(self) -> ScalarSummary:
        return self.metrics["detection_rate"]

    @property
    def nuisance_alerts(self) -> int:
        return int(self.metrics["nuisance_alerts"].total or 0)

    @property
    def nuisance_alerts_per_hour(self) -> ScalarSummary:
        return self.metrics["nuisance_alerts_per_hour"]

    @property
    def uncertain_duration_sec(self) -> ScalarSummary:
        return self.metrics["uncertain_duration_sec"]

    @property
    def uncertain_fraction(self) -> ScalarSummary:
        return self.metrics["uncertain_fraction"]

    @property
    def mean_detected_latency_sec(self) -> ScalarSummary:
        return self.metrics["mean_detected_latency_sec"]

    @property
    def explanation_completeness(self) -> ScalarSummary:
        return self.metrics["explanation_completeness"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithmId": self.algorithm_id,
            "algorithmMetadata": _camelize(self.algorithm_metadata),
            "totalRuns": self.total_runs,
            "totalTruthEvents": self.total_truth_events,
            "detectedEvents": self.detected_events,
            "missedEvents": self.missed_events,
            "metrics": {
                _camel_case(name): summary.to_dict()
                for name, summary in self.metrics.items()
            },
            "denominators": _camelize(self.denominators),
        }


@dataclass(frozen=True)
class ExperimentBatch:
    """Complete deterministic batch result and reproducibility manifest."""

    experiment_id: str
    spec: ExperimentSpec
    run_receipts: list[ExperimentRunReceipt]
    algorithm_summaries: dict[str, AlgorithmAggregateSummary]
    manifest: dict[str, Any]

    @property
    def receipts(self) -> list[ExperimentRunReceipt]:
        return self.run_receipts

    @property
    def runs(self) -> list[ExperimentRunReceipt]:
        return self.run_receipts

    @property
    def aggregates(self) -> dict[str, AlgorithmAggregateSummary]:
        return self.algorithm_summaries

    @property
    def aggregate_summaries(self) -> dict[str, AlgorithmAggregateSummary]:
        return self.algorithm_summaries

    @property
    def normalized_spec(self) -> dict[str, Any]:
        return self.spec.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "experimentId": self.experiment_id,
            "spec": self.spec.to_dict(),
            "runReceipts": [receipt.to_dict() for receipt in self.run_receipts],
            "algorithmSummaries": {
                algorithm_id: summary.to_dict()
                for algorithm_id, summary in self.algorithm_summaries.items()
            },
            "manifest": copy.deepcopy(self.manifest),
        }


def _run_metrics(result: Any, duration_sec: int) -> AlgorithmRunMetrics:
    metrics = result.metrics
    latencies = list(metrics.detection_latency_sec)
    detected_latencies = [value for value in latencies if value is not None]
    duration_hours = duration_sec / 3600
    return AlgorithmRunMetrics(
        algorithm_id=result.algorithm_id,
        total_alerts=metrics.total_alerts,
        truth_event_count=metrics.truth_event_count,
        detected_events=metrics.detected_simulated_events,
        missed_events=metrics.missed_simulated_events,
        detection_latency_sec=latencies,
        nuisance_alerts=metrics.nuisance_alerts,
        nuisance_alerts_per_hour=(
            metrics.nuisance_alerts / duration_hours if duration_hours > 0 else None
        ),
        uncertain_duration_sec=metrics.uncertain_duration_sec,
        uncertain_fraction=(
            metrics.uncertain_duration_sec / duration_sec if duration_sec > 0 else None
        ),
        mean_detected_latency_sec=(
            sum(detected_latencies) / len(detected_latencies)
            if detected_latencies
            else None
        ),
        explanation_completeness=metrics.explanation_completeness,
    )


def _aggregate_algorithm(
    algorithm_id: str,
    receipts: Sequence[ExperimentRunReceipt],
) -> AlgorithmAggregateSummary:
    values = [receipt.algorithm_metrics[algorithm_id] for receipt in receipts]
    total_runs = len(values)
    total_truth_events = sum(item.truth_event_count for item in values)
    detected_events = sum(item.detected_events for item in values)
    missed_events = sum(item.missed_events for item in values)
    metrics: dict[str, ScalarSummary] = {
        "total_runs": _normal_summary(
            [1.0] * total_runs,
            denominator=total_runs,
            denominator_label="runs",
        ),
        "total_truth_events": _normal_summary(
            [item.truth_event_count for item in values],
            denominator=total_runs,
            denominator_label="runs",
        ),
        "detected_events": _normal_summary(
            [item.detected_events for item in values],
            denominator=total_runs,
            denominator_label="runs",
        ),
        "missed_events": _normal_summary(
            [item.missed_events for item in values],
            denominator=total_runs,
            denominator_label="runs",
        ),
        "detection_rate": _wilson_summary(detected_events, total_truth_events),
        "nuisance_alerts": _normal_summary(
            [item.nuisance_alerts for item in values],
            denominator=total_runs,
            denominator_label="runs",
        ),
        "nuisance_alerts_per_hour": _normal_summary(
            [item.nuisance_alerts_per_hour for item in values if item.nuisance_alerts_per_hour is not None],
            denominator=total_runs,
            denominator_label="runs",
        ),
        "uncertain_duration_sec": _normal_summary(
            [item.uncertain_duration_sec for item in values],
            denominator=total_runs,
            denominator_label="runs",
        ),
        "uncertain_fraction": _normal_summary(
            [item.uncertain_fraction for item in values if item.uncertain_fraction is not None],
            denominator=total_runs,
            denominator_label="runs",
        ),
        "mean_detected_latency_sec": _normal_summary(
            [item.mean_detected_latency_sec for item in values if item.mean_detected_latency_sec is not None],
            denominator=sum(item.mean_detected_latency_sec is not None for item in values),
            denominator_label="runs-with-detected-latency",
        ),
        "explanation_completeness": _normal_summary(
            [item.explanation_completeness for item in values if item.explanation_completeness is not None],
            denominator=total_runs,
            denominator_label="runs",
        ),
    }
    return AlgorithmAggregateSummary(
        algorithm_id=algorithm_id,
        algorithm_metadata=dict(ALGORITHM_CATALOG[algorithm_id]),
        total_runs=total_runs,
        total_truth_events=total_truth_events,
        detected_events=detected_events,
        missed_events=missed_events,
        metrics=metrics,
        denominators={
            "runs": total_runs,
            "truth_events": total_truth_events,
            "detected_events": detected_events,
            "duration_hours": sum(
                receipt.duration_sec / 3600 for receipt in receipts
            ),
            "runs_with_detected_latency": sum(
                item.mean_detected_latency_sec is not None for item in values
            ),
        },
    )


def _experiment_id(spec: ExperimentSpec) -> str:
    provenance = {
        "schemaVersion": SCHEMA_VERSION,
        "normalizedSpec": spec.to_dict(),
        "algorithmMetadata": [
            ALGORITHM_CATALOG[algorithm_id] for algorithm_id in spec.algorithms
        ],
    }
    return f"EXP-{stable_hash(provenance)}"


def run_experiment_batch(
    spec: Mapping[str, Any] | ExperimentSpec,
) -> ExperimentBatch:
    """Run every requested scenario/seed pair in stable input order."""

    normalized = spec if isinstance(spec, ExperimentSpec) else ExperimentSpec.from_mapping(spec)
    if not isinstance(normalized, ExperimentSpec):  # pragma: no cover - defensive
        raise TypeError("experiment spec must be a mapping or ExperimentSpec")

    experiment_id = _experiment_id(normalized)
    receipts: list[ExperimentRunReceipt] = []
    for scenario in normalized.scenarios:
        for seed in normalized.seeds:
            run_config = dict(normalized.base_config)
            # These three values are owned by the suite dimensions and always
            # win over similarly named values in base_config.
            run_config.update(
                {
                    "scenario": scenario,
                    "seed": seed,
                    "algorithms": list(normalized.algorithms),
                }
            )
            run = create_simulation_run(run_config)
            algorithm_metrics = {
                result.algorithm_id: _run_metrics(result, run.config.duration_sec)
                for result in run.results
            }
            receipts.append(
                ExperimentRunReceipt(
                    run_id=run.run_id,
                    scenario=run.scenario.id,
                    seed=run.seed,
                    duration_sec=run.config.duration_sec,
                    algorithm_metrics=algorithm_metrics,
                )
            )

    summaries = {
        algorithm_id: _aggregate_algorithm(algorithm_id, receipts)
        for algorithm_id in normalized.algorithms
    }
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "experimentId": experiment_id,
        "suiteId": normalized.suite_id,
        "normalizedSpec": normalized.to_dict(),
        "scenarioIds": list(normalized.scenarios),
        "seeds": list(normalized.seeds),
        "algorithmMetadata": {
            algorithm_id: dict(ALGORITHM_CATALOG[algorithm_id])
            for algorithm_id in normalized.algorithms
        },
        "runIds": [receipt.run_id for receipt in receipts],
        "note": "Metrics are simulated and not clinical performance.",
    }
    return ExperimentBatch(
        experiment_id=experiment_id,
        spec=normalized,
        run_receipts=receipts,
        algorithm_summaries=summaries,
        manifest=manifest,
    )


__all__ = [
    "ALGORITHM_CATALOG",
    "AlgorithmAggregateSummary",
    "AlgorithmRunMetrics",
    "ConfidenceInterval",
    "ExperimentBatch",
    "ExperimentRunReceipt",
    "ExperimentSpec",
    "ScalarSummary",
    "run_experiment_batch",
]
