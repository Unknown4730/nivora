"""The two educational alarm-algorithm arms used by the simulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .explanations import create_structured_explanation
from .models import AlgorithmInput, AlgorithmOutput
from .prng import clamp, round_value
from .scenarios import SIGNAL_META

CHANGE_RATIO = 0.55


class AlarmAlgorithm(Protocol):
    id: str
    name: str

    def classify(self, input: AlgorithmInput) -> AlgorithmOutput: ...


def _quality_mean(input: AlgorithmInput) -> float:
    return sum(item.score for item in input.quality) / max(1, len(input.quality))


def _trust_mean(input: AlgorithmInput) -> float:
    values = [item.score for item in input.trust_by_channel.values()]
    return sum(values) / max(1, len(values))


def _changed_channels(input: AlgorithmInput) -> list[str]:
    return [
        item.channel
        for item in input.baseline_by_channel.values()
        if item.deviation is not None
        and abs(item.deviation) >= SIGNAL_META[item.channel]["deviation_scale"] * CHANGE_RATIO
    ]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _base_reasons(input: AlgorithmInput, channels: list[str]) -> list[str]:
    reasons: list[str] = []
    spo2 = input.baseline_by_channel.get("spo2")
    quality = _quality_mean(input)
    trust = _trust_mean(input)
    spo2_value = input.sample.values.get("spo2")
    if spo2_value is not None and spo2_value < 90:
        reasons.append("SPO2_BELOW_SIMULATED_THRESHOLD")
    if quality < 0.62:
        reasons.append("SIGNAL_QUALITY_LOW")
    if any("MOTION_ARTIFACT_PRESENT" in item.reason_codes for item in input.quality):
        reasons.append("MOTION_ARTIFACT_PRESENT")
    if any(item.direction == "decreasing" for item in input.trust_by_channel.values()):
        reasons.append("SENSOR_TRUST_DECREASING")
    if any(item.direction == "recovering" for item in input.trust_by_channel.values()):
        reasons.append("SENSOR_TRUST_RECOVERING")
    heart_rate = input.baseline_by_channel.get("heart-rate")
    respiration = input.baseline_by_channel.get("respiration")
    if heart_rate is not None and (
        (heart_rate.deviation is not None and heart_rate.deviation > SIGNAL_META["heart-rate"]["deviation_scale"] * CHANGE_RATIO)
        or (heart_rate.trend_per_sample is not None and heart_rate.trend_per_sample > 0.08)
    ):
        reasons.append("HEART_RATE_SUPPORTING_TREND")
    if respiration is not None and (
        (respiration.deviation is not None and respiration.deviation > SIGNAL_META["respiration"]["deviation_scale"] * CHANGE_RATIO)
        or (respiration.trend_per_sample is not None and respiration.trend_per_sample > 0.08)
    ):
        reasons.append("RESPIRATION_SUPPORTING_TREND")
    if input.cross_signal_agreement < 0.6:
        reasons.append("CROSS_SIGNAL_SUPPORT_WEAK")
    elif len(channels) >= 2:
        reasons.append("CROSS_SIGNAL_SUPPORT_STRONG")
    if len(input.unavailable_channels) >= 2:
        reasons.append("MULTIPLE_SIGNALS_UNAVAILABLE")
    elif input.unavailable_channels:
        reasons.append("MISSING_DATA_PRESENT")
    if any(input.baseline_by_channel[channel].persistent_deviation for channel in channels):
        reasons.append("PERSISTENT_DEVIATION")
    if any(input.baseline_by_channel[channel].recovery_detected for channel in channels):
        reasons.append("RECOVERY_DETECTED")
    if not reasons and spo2 is not None and spo2.value is not None:
        reasons.append("NOMINAL_SIGNAL")
    return _unique(reasons)


def _output_for(
    input: AlgorithmInput,
    algorithm_id: str,
    classification: str,
    reason_codes: list[str],
    channels: list[str],
) -> AlgorithmOutput:
    confidence = 0.0 if classification == "INSUFFICIENT_EVIDENCE" else clamp(
        _quality_mean(input) * 0.35
        + _trust_mean(input) * 0.35
        + input.cross_signal_agreement * 0.3
    )
    start_sec = max(0.0, input.sample.t_sec)
    end_sec = start_sec + max(0.0, input.sample_interval_sec)
    if input.duration_sec is not None:
        start_sec = min(start_sec, input.duration_sec)
        end_sec = min(end_sec, input.duration_sec)
    output = AlgorithmOutput(
        algorithm_id=algorithm_id,
        window_id=input.window_id,
        start_sec=round_value(start_sec, 4),
        end_sec=round_value(end_sec, 4),
        classification=classification,  # type: ignore[arg-type]
        confidence=round_value(confidence, 4),
        channels=list(channels),
        reason_codes=_unique(reason_codes),
        explanation=create_structured_explanation(input, classification, reason_codes),  # type: ignore[arg-type]
    )
    return output


@dataclass
class ThresholdBaselineAlgorithm:
    id: str = "threshold-baseline"
    name: str = "Threshold baseline"
    threshold: float = 90

    def classify(self, input: AlgorithmInput) -> AlgorithmOutput:
        channels = _changed_channels(input)
        reasons = _base_reasons(input, channels)
        spo2_value = input.sample.values.get("spo2")
        spo2_baseline = input.baseline_by_channel["spo2"]
        if spo2_value is None:
            return _output_for(input, self.id, "INSUFFICIENT_EVIDENCE", _unique(reasons + ["EVIDENCE_INSUFFICIENT"]), channels)
        crossed = spo2_value < self.threshold or (spo2_baseline.deviation if spo2_baseline.deviation is not None else 0) < -5
        if crossed and spo2_baseline.persistent_deviation:
            return _output_for(input, self.id, "MULTI_SIGNAL_SUPPORTED_EVENT", reasons, ["spo2"])
        if crossed:
            return _output_for(input, self.id, "LOW_CONFIDENCE_CHANGE", _unique(reasons + ["EVIDENCE_INSUFFICIENT"]), ["spo2"])
        return _output_for(input, self.id, "NOMINAL", reasons, [])


@dataclass
class ReliabilityAwareAlgorithm:
    id: str = "reliability-aware"
    name: str = "Reliability-aware comparison arm"
    minimum_trust: float = 0.55
    minimum_agreement: float = 0.58

    def classify(self, input: AlgorithmInput) -> AlgorithmOutput:
        channels = _changed_channels(input)
        reasons = _base_reasons(input, channels)
        if len(input.unavailable_channels) >= 2 or input.contradictory_evidence:
            return _output_for(input, self.id, "INSUFFICIENT_EVIDENCE", _unique(reasons + ["EVIDENCE_INSUFFICIENT"]), channels)
        low_quality = _quality_mean(input) < 0.62
        low_trust = _trust_mean(input) < self.minimum_trust
        artifact = any(item.features.artifact_overlap > 0.2 for item in input.quality)
        if not channels:
            if input.unavailable_channels or artifact or low_quality or low_trust:
                state = "ARTIFACT_CONSISTENT_ANOMALY" if artifact else "INSUFFICIENT_EVIDENCE" if len(input.unavailable_channels) >= 1 else "LOW_CONFIDENCE_CHANGE"
                return _output_for(input, self.id, state, _unique(reasons + ["EVIDENCE_INSUFFICIENT"]), [])
            return _output_for(input, self.id, "NOMINAL", reasons, [])
        if artifact or low_quality or low_trust:
            state = "ARTIFACT_CONSISTENT_ANOMALY" if artifact else "LOW_CONFIDENCE_CHANGE"
            return _output_for(input, self.id, state, reasons, channels)
        if len(channels) >= 3 and input.cross_signal_agreement >= 0.78 and any(input.baseline_by_channel[channel].persistent_deviation for channel in channels):
            return _output_for(input, self.id, "HIGH_EVIDENCE_MULTI_SIGNAL_CHANGE", reasons, channels)
        if len(channels) >= 2 and input.cross_signal_agreement >= self.minimum_agreement:
            return _output_for(input, self.id, "MULTI_SIGNAL_SUPPORTED_EVENT", reasons, channels)
        return _output_for(input, self.id, "LOW_CONFIDENCE_CHANGE", _unique(reasons + ["EVIDENCE_INSUFFICIENT"]), channels)


def create_threshold_baseline_algorithm(options: dict[str, float] | None = None) -> ThresholdBaselineAlgorithm:
    options = options or {}
    return ThresholdBaselineAlgorithm(threshold=options.get("spo2_threshold", options.get("spo2Threshold", 90)))


def create_reliability_aware_algorithm(options: dict[str, float] | None = None) -> ReliabilityAwareAlgorithm:
    options = options or {}
    return ReliabilityAwareAlgorithm(
        minimum_trust=options.get("minimum_trust", options.get("minimumTrust", 0.55)),
        minimum_agreement=options.get("minimum_agreement", options.get("minimumAgreement", 0.58)),
    )


def algorithms_for(ids: list[str]) -> list[AlarmAlgorithm]:
    available = {
        "threshold-baseline": create_threshold_baseline_algorithm(),
        "reliability-aware": create_reliability_aware_algorithm(),
    }
    unknown = [algorithm_id for algorithm_id in ids if algorithm_id not in available]
    if unknown:
        raise ValueError(f"Unknown algorithm selection: {unknown[0]}")
    return [available[algorithm_id] for algorithm_id in ids]


def is_alert_classification(classification: str) -> bool:
    return classification in {
        "ARTIFACT_CONSISTENT_ANOMALY",
        "MULTI_SIGNAL_SUPPORTED_EVENT",
        "HIGH_EVIDENCE_MULTI_SIGNAL_CHANGE",
    }


def is_uncertain_classification(classification: str) -> bool:
    return classification in {"LOW_CONFIDENCE_CHANGE", "INSUFFICIENT_EVIDENCE"}
