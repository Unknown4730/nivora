import assert from 'node:assert/strict';
import test from 'node:test';
import {
  benchmarkAlgorithm,
  computeChannelQuality,
  computeRollingBaseline,
  createSimulationRun,
  createThresholdBaselineAlgorithm,
  getScenarioDefinition,
  qualityScore,
  samplesToCsv,
  serializeSimulationRun,
  updateSensorTrust,
} from '../src/domain/index.js';

// Keep a small fixture local to the test layer so the engine remains dependency-free.
const fixture = (values) => values.map((value, index) => ({
  tSec: index,
  values: { spo2: value, 'heart-rate': 72, respiration: 16 },
}));

test('same seed and config produce byte-equivalent simulation runs', () => {
  const config = { scenario: 'simulated-event', durationSec: 60, sampleRateHz: 2, artifactIntensity: 0.4, algorithms: ['threshold-baseline', 'reliability-aware'], seed: 1234 };
  const first = createSimulationRun(config);
  const second = createSimulationRun(config);
  assert.equal(serializeSimulationRun(first), serializeSimulationRun(second));
  assert.equal(first.samples.length, 121);
  assert.deepEqual(first.samples[1].tSec, 0.5);
});

test('different seeds change simulated samples without changing scenario truth recipe', () => {
  const first = createSimulationRun({ scenario: 'stable-baseline', durationSec: 20, sampleRateHz: 1, seed: 10 });
  const second = createSimulationRun({ scenario: 'stable-baseline', durationSec: 20, sampleRateHz: 1, seed: 11 });
  assert.notDeepEqual(first.samples, second.samples);
  assert.deepEqual(first.annotations, second.annotations);
  assert.equal(first.scenario.groundTruth.physiologicalEventExists, false);
});

test('all requested scenarios expose explicit bounded simulated ground truth', () => {
  const scenarios = ['stable-baseline', 'loose-spo2-sensor', 'motion-artifact', 'simulated-event', 'gradual-deterioration', 'multi-sensor-dropout'];
  for (const scenario of scenarios) {
    const run = createSimulationRun({ scenario, durationSec: 120, sampleRateHz: 1, seed: 3 });
    for (const annotation of run.annotations) {
      assert.ok(annotation.startSec >= 0 && annotation.endSec <= 120 && annotation.startSec < annotation.endSec);
    }
    assert.equal(typeof run.scenario.groundTruth.knownLimitation, 'string');
  }
  assert.equal(createSimulationRun({ scenario: 'motion-artifact', durationSec: 60, sampleRateHz: 1, seed: 3 }).annotations[0].kind, 'sensor-artifact');
  const dropout = createSimulationRun({ scenario: 'multi-sensor-dropout', durationSec: 75, sampleRateHz: 1, seed: 3 });
  assert.ok(dropout.samples.some((sample) => sample.values.spo2 == null && sample.values['heart-rate'] == null));
});

test('quality formula is bounded and transparent', () => {
  const features = { shortWindowStability: 0.8, valuePlausibility: 0.7, continuity: 0.9, missingDataPenalty: 0.8, artifactPenalty: 0.5, crossSensorConsistency: 0.6 };
  assert.equal(qualityScore(features), 0.72);
  const clean = computeChannelQuality({ samples: fixture([96, 96.1, 95.9, 96]), channel: 'spo2', startSec: 0, endSec: 4, annotations: [] });
  const missing = computeChannelQuality({ samples: fixture([96, null, null, 96]), channel: 'spo2', startSec: 0, endSec: 4, annotations: [] });
  const artifact = computeChannelQuality({ samples: fixture([96, 96, 96, 96]), channel: 'spo2', startSec: 0, endSec: 4, annotations: [{ id: 'a', kind: 'sensor-artifact', label: 'artifact', startSec: 1, endSec: 3, channels: ['spo2'] }] });
  assert.ok(clean.score > missing.score);
  assert.ok(clean.score > artifact.score);
  assert.equal(missing.features.missingFraction, 0.5);
  assert.ok(clean.score >= 0 && clean.score <= 1 && missing.score >= 0 && missing.score <= 1);
});

test('trust decays faster than it recovers and remains clamped', () => {
  const degraded = updateSensorTrust(0.9, 0.1, 0.1);
  const recovered = updateSensorTrust(degraded.score, 1, 1);
  assert.ok(degraded.score < 0.9);
  assert.ok(recovered.score > degraded.score);
  assert.ok((recovered.score - degraded.score) < (0.9 - degraded.score));
  assert.equal(updateSensorTrust(-2, -1, -1).score, 0);
  assert.equal(updateSensorTrust(2, 2, 2).score, 1);
  const continued = updateSensorTrust(degraded.score, 0.1, 0.1);
  assert.ok(continued.score < recovered.score);
});

test('rolling baseline excludes current value and detects a persistent deviation', () => {
  const values = fixture([100, 102, 101, 100, 110]).map((sample) => ({ ...sample, values: { ...sample.values, spo2: sample.values.spo2 } }));
  const analysis = computeRollingBaseline(values, 'spo2', 3);
  assert.equal(analysis[0].value, null);
  assert.equal(analysis[3].value, 101);
  assert.equal(analysis[4].value, 101);
  assert.equal(analysis[4].deviation, 9);
});

test('threshold and reliability-aware algorithms run on the same scenario', () => {
  const run = createSimulationRun({ scenario: 'simulated-event', durationSec: 90, sampleRateHz: 1, seed: 7, algorithms: ['threshold-baseline', 'reliability-aware'] });
  assert.deepEqual(run.results.map((result) => result.algorithmId), ['threshold-baseline', 'reliability-aware']);
  assert.equal(run.results[0].outputs.length, run.samples.length);
  assert.equal(run.results[1].outputs.length, run.samples.length);
  assert.ok(run.results.every((result) => result.metrics.truthEventCount === 1));
});

test('multi-sensor dropout is insufficient evidence, never silently nominal', () => {
  const run = createSimulationRun({ scenario: 'multi-sensor-dropout', durationSec: 75, sampleRateHz: 1, seed: 17, algorithms: ['reliability-aware'] });
  const outputs = run.results[0].outputs;
  assert.ok(outputs.some((output) => output.classification === 'INSUFFICIENT_EVIDENCE'));
  for (const output of outputs.filter((item) => item.classification === 'INSUFFICIENT_EVIDENCE')) assert.ok(output.reasonCodes.includes('EVIDENCE_INSUFFICIENT'));
});

test('benchmark matching counts alerts, nuisance alerts, missed events, latency, and uncertainty', () => {
  const truth = [{ id: 'e1', kind: 'simulated-event', startSec: 10, endSec: 15, channels: ['spo2'] }, { id: 'e2', kind: 'simulated-event', startSec: 40, endSec: 45, channels: ['spo2'] }];
  const makeOutput = (startSec, endSec, classification) => ({ algorithmId: 'reliability-aware', windowId: `${startSec}`, startSec, endSec, classification, confidence: 0.8, channels: ['spo2'], reasonCodes: ['NOMINAL_SIGNAL'], explanation: { detail: 'fixture', reasonCodes: ['NOMINAL_SIGNAL'] } });
  const outputs = [makeOutput(12, 14, 'MULTI_SIGNAL_SUPPORTED_EVENT'), makeOutput(20, 25, 'LOW_CONFIDENCE_CHANGE'), makeOutput(50, 52, 'HIGH_EVIDENCE_MULTI_SIGNAL_CHANGE')];
  const metrics = benchmarkAlgorithm({ truthAnnotations: truth, outputs, predictions: outputs.map((item, index) => ({ ...item, predictionId: `p${index}`, kind: 'prediction', label: item.classification, sourceId: item.windowId })) });
  assert.equal(metrics.totalAlerts, 2);
  assert.equal(metrics.nuisanceAlerts, 1);
  assert.equal(metrics.detectedSimulatedEvents, 1);
  assert.equal(metrics.missedSimulatedEvents, 1);
  assert.deepEqual(metrics.detectionLatencySec, [2, null]);
  assert.equal(metrics.uncertainWindowCount, 1);
  assert.equal(metrics.uncertainDurationSec, 5);
});

test('touching half-open intervals do not match', () => {
  const truth = [{ id: 'e1', kind: 'simulated-event', startSec: 10, endSec: 15, channels: ['spo2'] }];
  const output = { algorithmId: 'threshold-baseline', windowId: 'p', startSec: 15, endSec: 20, classification: 'MULTI_SIGNAL_SUPPORTED_EVENT', confidence: 1, channels: ['spo2'], reasonCodes: [], explanation: { detail: 'fixture', reasonCodes: [] } };
  const metrics = benchmarkAlgorithm({ truthAnnotations: truth, outputs: [output], predictions: [{ ...output, predictionId: 'p', kind: 'prediction', label: output.classification, sourceId: 'p' }] });
  assert.equal(metrics.missedSimulatedEvents, 1);
  assert.equal(metrics.nuisanceAlerts, 1);
});

test('JSON and CSV exports are deterministic and preserve missing values', () => {
  const run = createSimulationRun({ scenario: 'stable-baseline', durationSec: 3, sampleRateHz: 1, seed: 2 });
  const before = JSON.stringify(run);
  assert.equal(serializeSimulationRun(run), serializeSimulationRun(run));
  const csv = samplesToCsv([{ tSec: 0, values: { spo2: 96, 'heart-rate': null, respiration: 16 } }]);
  assert.equal(csv, 'tSec,spo2Pct,heartRateBpm,respirationBpm\n0,96,,16\n');
  assert.equal(JSON.stringify(run), before);
});

test('scenario aliases remain compatible with the original UI values', () => {
  assert.equal(getScenarioDefinition('clean', 60).id, 'stable-baseline');
  assert.equal(getScenarioDefinition('motion', 60).id, 'motion-artifact');
  assert.equal(getScenarioDefinition('dropout', 60).id, 'multi-sensor-dropout');
});
