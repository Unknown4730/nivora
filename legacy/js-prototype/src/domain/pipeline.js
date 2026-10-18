import { stableHash, round } from './prng.js';
import { algorithmsFor } from './algorithms.js';
import { benchmarkAlgorithm, mergePredictions } from './benchmark.js';
import { computeRollingAnalyses } from './baseline.js';
import { generateSimulatedSignals } from './generator.js';
import { collectExplanationItems } from './explanations.js';
import { computeQualityWindows } from './quality.js';
import { CHANNELS, getScenarioDefinition, normalizeScenarioId } from './scenarios.js';
import { computeTrustSeries } from './trust.js';

const DEFAULTS = {
  durationSec: 60,
  sampleRateHz: 1,
  artifactIntensity: 0.48,
  algorithms: ['threshold-baseline', 'reliability-aware'],
  seed: 20261018,
  initialTrust: 0.8,
  qualityWindowSamples: 8,
  baselineWindowSamples: 8,
  requiredPersistenceSamples: 3,
};

function normalizeConfig(input) {
  const config = { ...DEFAULTS, ...input, scenario: normalizeScenarioId(input.scenario ?? 'stable-baseline') };
  if (!Array.isArray(config.algorithms) || !config.algorithms.length) throw new Error('At least one algorithm must be selected');
  if (config.algorithms.some((id) => !['threshold-baseline', 'reliability-aware'].includes(id))) throw new Error('Unknown algorithm selection');
  if (!Number.isInteger(config.sampleRateHz) || config.sampleRateHz <= 0) throw new Error('sampleRateHz must be a positive integer');
  if (!Number.isInteger(config.durationSec) || config.durationSec <= 0) throw new Error('durationSec must be a positive integer');
  if (config.artifactIntensity < 0 || config.artifactIntensity > 1) throw new Error('artifactIntensity must be between 0 and 1');
  return { ...config, algorithms: [...new Set(config.algorithms)] };
}

function makeEvidence(samples, qualityWindows, analyses, trustSeries, config) {
  return samples.map((sample, index) => {
    const baselineByChannel = Object.fromEntries(CHANNELS.map((channel) => [channel, analyses[channel][index]]));
    const unavailableChannels = CHANNELS.filter((channel) => sample.values[channel] == null);
    const changed = CHANNELS.filter((channel) => Math.abs(analyses[channel][index].deviation ?? 0) > 0).length;
    const contradictoryEvidence = changed >= 2 && trustSeries[index].agreement < 0.3;
    return {
      windowId: `window-${index}`,
      startSec: sample.tSec,
      endSec: round(sample.tSec + 1 / config.sampleRateHz, 4),
      quality: qualityWindows[index],
      trustByChannel: trustSeries[index].trustByChannel,
      baselineByChannel,
      crossSignalAgreement: trustSeries[index].agreement,
      unavailableChannels,
      contradictoryEvidence,
    };
  });
}

export function createSimulationRun(input = {}) {
  const config = normalizeConfig(input);
  const scenario = getScenarioDefinition(config.scenario, config.durationSec);
  const generated = generateSimulatedSignals(config, scenario);
  const analyses = computeRollingAnalyses(generated.samples, config.baselineWindowSamples, config.requiredPersistenceSamples);
  const qualityWindows = computeQualityWindows(generated.samples, generated.annotations, config.sampleRateHz, config.qualityWindowSamples);
  const trustSeries = computeTrustSeries({ samples: generated.samples, qualityWindows, analyses, initialTrust: config.initialTrust })
    .map((item, index) => ({ ...item, tSec: generated.samples[index].tSec }));
  const evidence = makeEvidence(generated.samples, qualityWindows, analyses, trustSeries, config);
  const algorithms = algorithmsFor(config.algorithms);
  const results = algorithms.map((algorithm) => {
    const outputs = evidence.map((window, index) => algorithm.classify({
      windowId: window.windowId,
      sample: generated.samples[index],
      quality: window.quality,
      trustByChannel: window.trustByChannel,
      baselineByChannel: window.baselineByChannel,
      crossSignalAgreement: window.crossSignalAgreement,
      unavailableChannels: window.unavailableChannels,
      contradictoryEvidence: window.contradictoryEvidence,
      requiredPersistenceSamples: config.requiredPersistenceSamples,
      sampleIntervalSec: 1 / config.sampleRateHz,
    }));
    const predictions = mergePredictions(outputs, algorithm.id);
    const metrics = benchmarkAlgorithm({
      truthAnnotations: generated.annotations,
      outputs,
      predictions,
      trustSeries,
      artifactAnnotations: generated.annotations.filter((item) => item.kind !== 'simulated-event'),
    });
    return { algorithmId: algorithm.id, algorithmName: algorithm.name, outputs, predictions, metrics };
  });
  const runId = `RUN-${stableHash({ config, annotations: generated.annotations })}`;
  return {
    schemaVersion: '1.0',
    runId,
    seed: config.seed,
    config,
    scenario,
    signals: generated.signals,
    samples: generated.samples,
    annotations: generated.annotations,
    evidence,
    results,
    explanations: collectExplanationItems(results),
  };
}

export { normalizeConfig };
