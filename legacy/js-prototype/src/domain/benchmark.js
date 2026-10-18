import { isAlertClassification, isUncertainClassification } from './algorithms.js';
import { CHANNELS } from './scenarios.js';
import { trustRecoveryTime } from './trust.js';

function overlaps(left, right) {
  return left.startSec < right.endSec && right.startSec < left.endSec;
}

export function mergePredictions(outputs, algorithmId) {
  const merged = [];
  for (const output of outputs) {
    const current = merged[merged.length - 1];
    const step = output.endSec - output.startSec;
    if (current && current.classification === output.classification && Math.abs(current.endSec - output.startSec) < step + 0.0001) {
      current.endSec = output.endSec;
      current.channels = [...new Set([...current.channels, ...output.channels])];
      current.reasonCodes = [...new Set([...current.reasonCodes, ...output.reasonCodes])];
      current.explanation = output.explanation;
    } else {
      merged.push({
        startSec: output.startSec,
        endSec: output.endSec,
        label: output.classification,
        kind: 'prediction',
        sourceId: output.windowId,
        algorithmId,
        predictionId: `${algorithmId}-${merged.length}`,
        classification: output.classification,
        confidence: output.confidence,
        channels: [...output.channels],
        reasonCodes: [...output.reasonCodes],
        explanation: output.explanation,
      });
    }
  }
  return merged;
}

export function benchmarkAlgorithm({ truthAnnotations, outputs, predictions = mergePredictions(outputs, outputs[0]?.algorithmId), trustSeries, artifactAnnotations = [] }) {
  const truthEvents = truthAnnotations.filter((item) => item.kind === 'simulated-event');
  const alertPredictions = predictions.filter((item) => isAlertClassification(item.classification));
  const uncertaintyPredictions = predictions.filter((item) => isUncertainClassification(item.classification));
  const matches = new Set();
  const detectionLatencySec = truthEvents.map((event) => {
    const candidates = alertPredictions
      .filter((prediction) => overlaps(event, prediction))
      .sort((left, right) => left.startSec - right.startSec);
    if (!candidates.length) return null;
    const match = candidates.find((prediction) => !matches.has(prediction.predictionId));
    if (!match) return null;
    matches.add(match.predictionId);
    return Math.max(0, match.startSec - event.startSec);
  });
  const nuisanceAlerts = alertPredictions.filter((prediction) => !truthEvents.some((event) => overlaps(event, prediction))).length;
  const uncertainDurationSec = uncertaintyPredictions.reduce((sum, prediction) => sum + Math.max(0, prediction.endSec - prediction.startSec), 0);
  const artifactEnd = Math.max(0, ...artifactAnnotations.map((item) => item.endSec));
  const recoveryTimes = CHANNELS.map((channel) => {
    const relevant = artifactAnnotations.find((item) => item.channels.includes(channel));
    if (!relevant || !trustSeries?.length) return null;
    const index = trustSeries.findIndex((item) => item.tSec >= relevant.endSec);
    return index < 0 ? null : trustRecoveryTime(trustSeries, channel, index);
  });
  const explanationCompleteness = outputs.length ? outputs.filter((output) => output.explanation?.detail && output.reasonCodes.length).length / outputs.length : 0;
  return {
    totalAlerts: alertPredictions.length,
    nuisanceAlerts,
    detectedSimulatedEvents: detectionLatencySec.filter((item) => item != null).length,
    missedSimulatedEvents: detectionLatencySec.filter((item) => item == null).length,
    detectionLatencySec,
    uncertaintyClassificationCount: outputs.filter((output) => isUncertainClassification(output.classification)).length,
    uncertainWindowCount: uncertaintyPredictions.length,
    uncertainDurationSec,
    trustRecoveryTimeSec: recoveryTimes,
    explanationCompleteness,
    truthEventCount: truthEvents.length,
    predictionCount: predictions.length,
    artifactEndSec: artifactEnd,
  };
}
