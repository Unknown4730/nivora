import { round } from './prng.js';
import { SIGNAL_META } from './scenarios.js';

function label(channel) {
  return SIGNAL_META[channel]?.label ?? channel;
}

function percent(value) {
  return value == null ? 'unavailable' : `${Math.round(value * 100)}%`;
}

export function createStructuredExplanation(input, classification, reasonCodes) {
  const spo2 = input.baselineByChannel.spo2;
  const spo2Quality = input.quality.find((item) => item.channel === 'spo2');
  const spo2Trust = input.trustByChannel.spo2;
  const changedChannels = Object.values(input.baselineByChannel)
    .filter((item) => item.deviation != null && Math.abs(item.deviation) >= 0.55 * ({ spo2: 5, 'heart-rate': 24, respiration: 8 }[item.channel] ?? 1))
    .map((item) => label(item.channel));
  const artifact = spo2Quality?.features.artifactOverlap > 0.2 || input.quality.some((item) => item.features.artifactOverlap > 0.2);
  let title = 'Nominal simulated window';
  if (classification === 'INSUFFICIENT_EVIDENCE') title = 'Insufficient simulated evidence';
  else if (classification === 'ARTIFACT_CONSISTENT_ANOMALY') title = 'Artifact-consistent simulated anomaly';
  else if (classification === 'LOW_CONFIDENCE_CHANGE') title = 'Low-confidence simulated change';
  else if (classification === 'MULTI_SIGNAL_SUPPORTED_EVENT') title = 'Multi-signal supported simulated change';
  else if (classification === 'HIGH_EVIDENCE_MULTI_SIGNAL_CHANGE') title = 'High-evidence multi-signal simulated change';

  let detail;
  if (classification === 'INSUFFICIENT_EVIDENCE') {
    detail = `${input.unavailableChannels.length} of ${Object.keys(input.sample.values).length} simulated signals were unavailable or contradictory. The algorithmic state remains uncertain rather than treating missing evidence as nominal.`;
  } else if (classification === 'ARTIFACT_CONSISTENT_ANOMALY') {
    detail = `${changedChannels.join(', ') || 'A simulated signal'} changed while signal quality or sensor trust was reduced${artifact ? ' and an artifact indicator was present' : ''}. The result is artifact-consistent; the underlying simulated state cannot be determined from this window.`;
  } else if (classification === 'LOW_CONFIDENCE_CHANGE') {
    detail = `${changedChannels.join(', ') || 'A simulated signal'} moved away from its simulated rolling baseline, but persistence, trust, quality, or cross-signal support was not sufficient for a stronger algorithmic state.`;
  } else if (classification === 'NOMINAL') {
    detail = 'Simulated signals remained close to their rolling baselines with sufficient available evidence for this window.';
  } else {
    detail = `${changedChannels.join(', ') || 'Multiple simulated signals'} showed a persistent change with cross-signal support. This is an algorithmic simulation state, not a clinical diagnosis.`;
  }
  return {
    title,
    detail,
    reasonCodes: [...reasonCodes],
    evidenceWindowId: input.windowId,
    values: {
      spo2Value: input.sample.values.spo2,
      spo2Baseline: spo2?.value ?? null,
      spo2Deviation: spo2?.deviation ?? null,
      spo2Quality: spo2Quality?.score ?? null,
      spo2Trust: spo2Trust?.score ?? null,
      crossSignalAgreement: round(input.crossSignalAgreement, 4),
      changedChannelCount: changedChannels.length,
      artifactIndicator: artifact,
    },
  };
}

export function explanationForOutput(output) {
  return output.explanation;
}

export function collectExplanationItems(results) {
  return results.flatMap((result) => result.outputs
    .filter((output, index) => output.classification !== 'NOMINAL' || index === result.outputs.length - 1)
    .map((output) => ({
      algorithmId: output.algorithmId,
      classification: output.classification,
      startSec: output.startSec,
      endSec: output.endSec,
      ...output.explanation,
    })));
}
