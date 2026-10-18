export function serializeSimulationRun(run) {
  return `${JSON.stringify(run, null, 2)}\n`;
}

export function samplesToCsv(samples) {
  const lines = ['tSec,spo2Pct,heartRateBpm,respirationBpm'];
  for (const sample of samples) {
    lines.push([
      sample.tSec,
      sample.values.spo2 ?? '',
      sample.values['heart-rate'] ?? '',
      sample.values.respiration ?? '',
    ].join(','));
  }
  return `${lines.join('\n')}\n`;
}

export function exportManifest(run) {
  return {
    schemaVersion: run.schemaVersion,
    scenario: run.scenario,
    seed: run.seed,
    algorithmNames: run.results.map((result) => result.algorithmName),
    timeline: run.annotations,
    benchmarkMetrics: Object.fromEntries(run.results.map((result) => [result.algorithmId, result.metrics])),
    reasonCodes: run.results.flatMap((result) => result.outputs.flatMap((output) => output.reasonCodes)),
    simulatedGroundTruth: run.scenario.groundTruth,
  };
}
