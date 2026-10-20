"""Deterministic, local-first Nivora simulation domain."""

from .algorithms import (
    algorithms_for,
    create_reliability_aware_algorithm,
    create_threshold_baseline_algorithm,
    is_alert_classification,
    is_uncertain_classification,
)
from .baseline import (
    add_persistence_and_recovery,
    compute_rolling_analyses,
    compute_rolling_baseline,
    deviation_ratio,
    is_supporting_trend,
    summarize_prior_values,
)
from .benchmark import benchmark_algorithm, merge_predictions
from .export import export_manifest, samples_to_csv, serialize_simulation_run
from .explanations import collect_explanation_items, create_structured_explanation, explanation_for_output
from .generator import generate_simulated_signals, validate_generation_config
from .models import *
from .pipeline import create_simulation_run, normalize_config
from .prng import clamp, create_seeded_random, round, round_value, stable_hash
from .quality import (
    compute_artifact_overlap,
    compute_channel_quality,
    compute_quality_windows,
    quality_score,
)
from .scenarios import (
    CHANNELS,
    SIGNAL_META,
    annotation_overlap,
    get_scenario_definition,
    is_in_interval,
    normalize_scenario_id,
)
from .trust import (
    compute_cross_signal_agreement,
    compute_trust_series,
    trust_recovery_time,
    update_sensor_trust,
)

__all__ = [
    "algorithms_for",
    "create_reliability_aware_algorithm",
    "create_threshold_baseline_algorithm",
    "is_alert_classification",
    "is_uncertain_classification",
    "add_persistence_and_recovery",
    "compute_rolling_analyses",
    "compute_rolling_baseline",
    "deviation_ratio",
    "is_supporting_trend",
    "summarize_prior_values",
    "benchmark_algorithm",
    "merge_predictions",
    "export_manifest",
    "samples_to_csv",
    "serialize_simulation_run",
    "collect_explanation_items",
    "create_structured_explanation",
    "explanation_for_output",
    "generate_simulated_signals",
    "validate_generation_config",
    "create_simulation_run",
    "normalize_config",
    "clamp",
    "create_seeded_random",
    "round_value",
    "round",
    "stable_hash",
    "compute_artifact_overlap",
    "compute_channel_quality",
    "compute_quality_windows",
    "quality_score",
    "CHANNELS",
    "SIGNAL_META",
    "annotation_overlap",
    "get_scenario_definition",
    "is_in_interval",
    "normalize_scenario_id",
    "compute_cross_signal_agreement",
    "compute_trust_series",
    "trust_recovery_time",
    "update_sensor_trust",
]
