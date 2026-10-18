"""Structured, inspectable explanations for algorithm outputs."""

from __future__ import annotations

from .models import AlgorithmInput, AlgorithmOutput, ExplanationItem, StructuredExplanation
from .prng import round_value
from .scenarios import SIGNAL_META


def _label(channel: str) -> str:
    return SIGNAL_META.get(channel, {}).get("label", channel)


def _percent(value: float | None) -> str:
    return "unavailable" if value is None else f"{round_value(value * 100, 0):.0f}%"


def create_structured_explanation(
    input: AlgorithmInput,
    classification: str,
    reason_codes: list[str],
) -> StructuredExplanation:
    spo2 = input.baseline_by_channel.get("spo2")
    spo2_quality = next((item for item in input.quality if item.channel == "spo2"), None)
    spo2_trust = input.trust_by_channel.get("spo2")
    changed_channels = [
        _label(item.channel)
        for item in input.baseline_by_channel.values()
        if item.deviation is not None
        and abs(item.deviation) >= 0.55 * SIGNAL_META.get(item.channel, {"deviation_scale": 1})["deviation_scale"]
    ]
    artifact = (
        (spo2_quality is not None and spo2_quality.features.artifact_overlap > 0.2)
        or any(item.features.artifact_overlap > 0.2 for item in input.quality)
    )
    title = {
        "INSUFFICIENT_EVIDENCE": "Insufficient simulated evidence",
        "ARTIFACT_CONSISTENT_ANOMALY": "Artifact-consistent simulated anomaly",
        "LOW_CONFIDENCE_CHANGE": "Low-confidence simulated change",
        "MULTI_SIGNAL_SUPPORTED_EVENT": "Multi-signal supported simulated change",
        "HIGH_EVIDENCE_MULTI_SIGNAL_CHANGE": "High-evidence multi-signal simulated change",
    }.get(classification, "Nominal simulated window")
    if classification == "INSUFFICIENT_EVIDENCE":
        detail = (
            f"{len(input.unavailable_channels)} of {len(input.sample.values)} simulated signals were unavailable or contradictory. "
            "The algorithmic state remains uncertain rather than treating missing evidence as nominal."
        )
    elif classification == "ARTIFACT_CONSISTENT_ANOMALY":
        detail = (
            f"{', '.join(changed_channels) or 'A simulated signal'} changed while signal quality or sensor trust was reduced"
            f"{' and an artifact indicator was present' if artifact else ''}. The result is artifact-consistent; the underlying simulated state cannot be determined from this window."
        )
    elif classification == "LOW_CONFIDENCE_CHANGE":
        detail = (
            f"{', '.join(changed_channels) or 'A simulated signal'} moved away from its simulated rolling baseline, but persistence, trust, quality, or cross-signal support was not sufficient for a stronger algorithmic state."
        )
    elif classification == "NOMINAL":
        detail = "Simulated signals remained close to their rolling baselines with sufficient available evidence for this window."
    else:
        detail = (
            f"{', '.join(changed_channels) or 'Multiple simulated signals'} showed a persistent change with cross-signal support. "
            "This is an algorithmic simulation state, not a clinical diagnosis."
        )
    return StructuredExplanation(
        title=title,
        detail=detail,
        reason_codes=list(reason_codes),
        evidence_window_id=input.window_id,
        values={
            "spo2Value": input.sample.values.get("spo2"),
            "spo2Baseline": spo2.value if spo2 is not None else None,
            "spo2Deviation": spo2.deviation if spo2 is not None else None,
            "spo2Quality": spo2_quality.score if spo2_quality is not None else None,
            "spo2Trust": spo2_trust.score if spo2_trust is not None else None,
            "crossSignalAgreement": round_value(input.cross_signal_agreement, 4),
            "changedChannelCount": len(changed_channels),
            "artifactIndicator": artifact,
        },
    )


def explanation_for_output(output: AlgorithmOutput) -> StructuredExplanation:
    return output.explanation


def collect_explanation_items(results: list) -> list[ExplanationItem]:
    items: list[ExplanationItem] = []
    for result in results:
        for index, output in enumerate(result.outputs):
            if output.classification != "NOMINAL" or index == len(result.outputs) - 1:
                explanation = output.explanation
                items.append(
                    ExplanationItem(
                        algorithm_id=output.algorithm_id,
                        classification=output.classification,
                        start_sec=output.start_sec,
                        end_sec=output.end_sec,
                        title=explanation.title,
                        detail=explanation.detail,
                        reason_codes=list(explanation.reason_codes),
                        evidence_window_id=explanation.evidence_window_id,
                        values=dict(explanation.values),
                    )
                )
    return items
