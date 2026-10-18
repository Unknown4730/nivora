import { clamp, round } from './prng.js';
import { CHANNELS, SIGNAL_META } from './scenarios.js';

function finiteValues(samples, channel) {
  return samples.map((sample) => sample.values[channel]).filter((value) => Number.isFinite(value));
}

function median(values) {
  if (!values.length) return null;
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
}

function slope(values) {
  if (values.length < 2) return null;
  const meanX = (values.length - 1) / 2;
  const meanY = values.reduce((sum, item) => sum + item.value, 0) / values.length;
  const numerator = values.reduce((sum, item, index) => sum + (index - meanX) * (item.value - meanY), 0);
  const denominator = values.reduce((sum, _, index) => sum + (index - meanX) ** 2, 0);
  return denominator ? numerator / denominator : 0;
}

export function computeRollingBaseline(samples, channel, windowSize = 8) {
  const analysis = [];
  for (let index = 0; index < samples.length; index += 1) {
    const prior = samples.slice(Math.max(0, index - windowSize), index);
    const usable = prior
      .map((sample, offset) => ({ value: sample.values[channel], offset }))
      .filter((item) => Number.isFinite(item.value));
    const baseline = usable.length >= Math.min(4, windowSize) ? median(usable.map((item) => item.value)) : null;
    const trend = usable.length >= 3 ? slope(usable) : null;
    const current = samples[index].values[channel];
    const deviation = baseline == null || current == null ? null : current - baseline;
    analysis.push({
      channel,
      value: baseline == null ? null : round(baseline, 4),
      deviation: deviation == null ? null : round(deviation, 4),
      trendPerSample: trend == null ? null : round(trend, 5),
      persistentDeviation: false,
      recoveryDetected: false,
      historyCount: usable.length,
    });
  }
  return analysis;
}

export function addPersistenceAndRecovery(analysis, channel, requiredPersistenceSamples = 3) {
  const scale = SIGNAL_META[channel].deviationScale;
  let consecutive = 0;
  let hadPersistent = false;
  return analysis.map((item) => {
    const changed = item.deviation != null && Math.abs(item.deviation) >= scale * 0.55;
    consecutive = changed ? consecutive + 1 : 0;
    const persistentDeviation = consecutive >= requiredPersistenceSamples;
    const recoveryDetected = hadPersistent && !changed && item.deviation != null;
    if (persistentDeviation) hadPersistent = true;
    return { ...item, persistentDeviation, recoveryDetected };
  });
}

export function computeRollingAnalyses(samples, windowSize, requiredPersistenceSamples) {
  return Object.fromEntries(CHANNELS.map((channel) => [
    channel,
    addPersistenceAndRecovery(computeRollingBaseline(samples, channel, windowSize), channel, requiredPersistenceSamples),
  ]));
}

export function deviationRatio(channel, deviation) {
  if (deviation == null) return null;
  return clamp(Math.abs(deviation) / SIGNAL_META[channel].deviationScale);
}

export function isSupportingTrend(channel, trend) {
  if (trend == null) return false;
  const direction = channel === 'spo2' ? -1 : 1;
  return trend * direction > SIGNAL_META[channel].deviationScale * 0.012;
}

export function summarizePriorValues(samples, channel) {
  return finiteValues(samples, channel);
}
