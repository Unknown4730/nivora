import { clamp, round } from './prng.js';
import { CHANNELS, SIGNAL_META, annotationOverlap } from './scenarios.js';

function channelValues(samples, channel) {
  return samples.map((sample) => sample.values[channel]);
}

function computeNoiseEstimate(values, meta) {
  const finite = values.filter((value) => Number.isFinite(value));
  if (finite.length < 2) return finite.length ? 0.25 : 1;
  const differences = [];
  for (let index = 1; index < finite.length; index += 1) differences.push(Math.abs(finite[index] - finite[index - 1]));
  const averageDifference = differences.reduce((sum, value) => sum + value, 0) / differences.length;
  return clamp(averageDifference / (meta.deviationScale * 0.8));
}

function computeStability(values, meta) {
  const finite = values.filter((value) => Number.isFinite(value));
  if (finite.length < 2) return finite.length ? 0.55 : 0;
  const mean = finite.reduce((sum, value) => sum + value, 0) / finite.length;
  const variance = finite.reduce((sum, value) => sum + (value - mean) ** 2, 0) / finite.length;
  return clamp(1 - Math.sqrt(variance) / (meta.deviationScale * 0.85));
}

function computeContinuity(values) {
  if (values.length < 2) return values.length ? 0.5 : 0;
  let transitions = 0;
  for (let index = 1; index < values.length; index += 1) if (values[index] != null && values[index - 1] != null) transitions += 1;
  return transitions / (values.length - 1);
}

function crossSensorConsistency(samples, channel) {
  const available = samples.map((sample) => CHANNELS.filter((item) => item !== channel && sample.values[item] != null).length);
  if (!available.length) return 0;
  return clamp(available.reduce((sum, value) => sum + value, 0) / (available.length * (CHANNELS.length - 1)));
}

export function computeArtifactOverlap(startSec, endSec, channel, annotations) {
  return annotations
    .filter((item) => item.kind !== 'simulated-event' && item.channels.includes(channel))
    .reduce((maximum, item) => Math.max(maximum, annotationOverlap(startSec, endSec, item)), 0);
}

export function computeChannelQuality({ samples, channel, startSec, endSec, annotations }) {
  const values = channelValues(samples, channel);
  const meta = SIGNAL_META[channel];
  const missingFraction = values.length ? values.filter((value) => value == null).length / values.length : 1;
  const finite = values.filter((value) => Number.isFinite(value));
  const valuePlausibility = finite.length ? finite.filter((value) => value >= meta.plausibility[0] && value <= meta.plausibility[1]).length / finite.length : 0;
  const artifactOverlap = computeArtifactOverlap(startSec, endSec, channel, annotations);
  const features = {
    shortWindowStability: round(computeStability(values, meta), 4),
    valuePlausibility: round(valuePlausibility, 4),
    continuity: round(computeContinuity(values), 4),
    missingDataPenalty: round(1 - missingFraction, 4),
    artifactPenalty: round(1 - artifactOverlap, 4),
    crossSensorConsistency: round(crossSensorConsistency(samples, channel), 4),
    missingFraction: round(missingFraction, 4),
    noiseEstimate: round(computeNoiseEstimate(values, meta), 4),
    artifactOverlap: round(artifactOverlap, 4),
  };
  const score = clamp(
    0.2 * features.shortWindowStability
      + 0.15 * features.valuePlausibility
      + 0.15 * features.continuity
      + 0.2 * features.missingDataPenalty
      + 0.2 * features.artifactPenalty
      + 0.1 * features.crossSensorConsistency,
  );
  const reasonCodes = [];
  if (score < 0.62) reasonCodes.push('SIGNAL_QUALITY_LOW');
  if (missingFraction > 0) reasonCodes.push('MISSING_DATA_PRESENT');
  if (artifactOverlap > 0.2) reasonCodes.push('MOTION_ARTIFACT_PRESENT');
  return { channel, score: round(score, 4), features, reasonCodes };
}

export function computeQualityWindows(samples, annotations, sampleRateHz, windowSamples = 8) {
  return samples.map((sample, index) => {
    const startIndex = Math.max(0, index - windowSamples + 1);
    const window = samples.slice(startIndex, index + 1);
    const startSec = window[0].tSec;
    const endSec = sample.tSec + (1 / sampleRateHz);
    return CHANNELS.map((channel) => computeChannelQuality({ samples: window, channel, startSec, endSec, annotations }));
  });
}

export function qualityScore(features) {
  return clamp(
    0.2 * features.shortWindowStability
      + 0.15 * features.valuePlausibility
      + 0.15 * features.continuity
      + 0.2 * features.missingDataPenalty
      + 0.2 * features.artifactPenalty
      + 0.1 * features.crossSensorConsistency,
  );
}
