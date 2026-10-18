import { clamp, round } from './prng.js';
import { CHANNELS } from './scenarios.js';

export function computeCrossSignalAgreement({ samples, analyses, quality }) {
  const available = CHANNELS.filter((channel) => samples.values[channel] != null);
  if (available.length < 2) return 0.1;
  const active = available.filter((channel) => {
    const item = analyses[channel];
    const ratio = item?.deviation == null ? 0 : Math.abs(item.deviation) / ({ spo2: 5, 'heart-rate': 24, respiration: 8 }[channel]);
    return ratio >= 0.55 || Math.abs(item?.trendPerSample ?? 0) > 0.08;
  }).length;
  let agreement = active === 0 ? 1 : active === 1 ? 0.35 : 0.72 + Math.min(0.28, (active - 2) * 0.14);
  const qualityMean = quality.reduce((sum, item) => sum + item.score, 0) / Math.max(1, quality.length);
  agreement *= 0.7 + qualityMean * 0.3;
  return round(clamp(agreement), 4);
}

export function updateSensorTrust(previousScore, qualityScore, agreement, options = {}) {
  const decayRate = options.decayRate ?? 0.34;
  const recoveryRate = options.recoveryRate ?? 0.08;
  const target = clamp(0.7 * qualityScore + 0.3 * agreement);
  const rate = target < previousScore ? decayRate : recoveryRate;
  const score = clamp(previousScore + rate * (target - previousScore));
  const epsilon = 0.001;
  const direction = score < previousScore - epsilon ? 'decreasing' : score > previousScore + epsilon ? 'recovering' : 'stable';
  return {
    score: round(score, 4),
    previousScore: round(previousScore, 4),
    direction,
    qualityContribution: round(qualityScore, 4),
    agreementContribution: round(agreement, 4),
  };
}

export function computeTrustSeries({ samples, qualityWindows, analyses, initialTrust = 0.8 }) {
  const current = Object.fromEntries(CHANNELS.map((channel) => [channel, clamp(initialTrust)]));
  return samples.map((sample, index) => {
    const quality = qualityWindows[index];
    const agreement = computeCrossSignalAgreement({ samples: sample, analyses: Object.fromEntries(CHANNELS.map((channel) => [channel, analyses[channel][index]])), quality });
    const trustByChannel = {};
    for (const channel of CHANNELS) {
      const update = updateSensorTrust(current[channel], quality.find((item) => item.channel === channel)?.score ?? 0, agreement);
      current[channel] = update.score;
      trustByChannel[channel] = { channel, ...update };
    }
    return { agreement, trustByChannel };
  });
}

export function trustRecoveryTime(trustSeries, channel, startIndex, threshold = 0.72) {
  const start = trustSeries[startIndex]?.trustByChannel[channel]?.score ?? 0;
  if (start >= threshold) return 0;
  for (let index = startIndex + 1; index < trustSeries.length; index += 1) {
    if ((trustSeries[index].trustByChannel[channel]?.score ?? 0) >= threshold) return index - startIndex;
  }
  return null;
}
