import { clamp, round } from './prng.js';
import { SIGNAL_META } from './scenarios.js';
import { createStructuredExplanation } from './explanations.js';

const CHANGE_RATIO = 0.55;

function qualityMean(input) {
  return input.quality.reduce((sum, item) => sum + item.score, 0) / Math.max(1, input.quality.length);
}

function trustMean(input) {
  const values = Object.values(input.trustByChannel).map((item) => item.score);
  return values.reduce((sum, item) => sum + item, 0) / Math.max(1, values.length);
}

function changedChannels(input) {
  return Object.values(input.baselineByChannel)
    .filter((item) => item.deviation != null && Math.abs(item.deviation) >= SIGNAL_META[item.channel].deviationScale * CHANGE_RATIO)
    .map((item) => item.channel);
}

function baseReasons(input, channels) {
  const reasons = [];
  const spo2 = input.baselineByChannel.spo2;
  const quality = qualityMean(input);
  const trust = trustMean(input);
  if (input.sample.values.spo2 != null && input.sample.values.spo2 < 90) reasons.push('SPO2_BELOW_SIMULATED_THRESHOLD');
  if (quality < 0.62) reasons.push('SIGNAL_QUALITY_LOW');
  if (input.quality.some((item) => item.reasonCodes.includes('MOTION_ARTIFACT_PRESENT'))) reasons.push('MOTION_ARTIFACT_PRESENT');
  if (Object.values(input.trustByChannel).some((item) => item.direction === 'decreasing')) reasons.push('SENSOR_TRUST_DECREASING');
  if (Object.values(input.trustByChannel).some((item) => item.direction === 'recovering')) reasons.push('SENSOR_TRUST_RECOVERING');
  if (input.baselineByChannel['heart-rate']?.deviation > SIGNAL_META['heart-rate'].deviationScale * CHANGE_RATIO || input.baselineByChannel['heart-rate']?.trendPerSample > 0.08) reasons.push('HEART_RATE_SUPPORTING_TREND');
  if (input.baselineByChannel.respiration?.deviation > SIGNAL_META.respiration.deviationScale * CHANGE_RATIO || input.baselineByChannel.respiration?.trendPerSample > 0.08) reasons.push('RESPIRATION_SUPPORTING_TREND');
  if (input.crossSignalAgreement < 0.6) reasons.push('CROSS_SIGNAL_SUPPORT_WEAK');
  else if (channels.length >= 2) reasons.push('CROSS_SIGNAL_SUPPORT_STRONG');
  if (input.unavailableChannels.length >= 2) reasons.push('MULTIPLE_SIGNALS_UNAVAILABLE');
  else if (input.unavailableChannels.length) reasons.push('MISSING_DATA_PRESENT');
  if (channels.some((channel) => input.baselineByChannel[channel].persistentDeviation)) reasons.push('PERSISTENT_DEVIATION');
  if (channels.some((channel) => input.baselineByChannel[channel].recoveryDetected)) reasons.push('RECOVERY_DETECTED');
  if (!reasons.length && spo2?.value != null) reasons.push('NOMINAL_SIGNAL');
  return [...new Set(reasons)];
}

function outputFor(input, algorithmId, classification, reasonCodes, channels) {
  const confidence = classification === 'INSUFFICIENT_EVIDENCE'
    ? 0
    : clamp((qualityMean(input) * 0.35) + (trustMean(input) * 0.35) + (input.crossSignalAgreement * 0.3));
  const output = {
    algorithmId,
    windowId: input.windowId,
    startSec: input.sample.tSec,
    endSec: input.sample.tSec + 1,
    classification,
    confidence: round(confidence, 4),
    channels,
    reasonCodes,
  };
  return { ...output, explanation: createStructuredExplanation(input, classification, reasonCodes) };
}

export function createThresholdBaselineAlgorithm(options = {}) {
  const threshold = options.spo2Threshold ?? 90;
  return {
    id: 'threshold-baseline',
    name: 'Threshold baseline',
    classify(input) {
      const channels = changedChannels(input);
      const reasons = baseReasons(input, channels);
      const spo2Value = input.sample.values.spo2;
      if (spo2Value == null) return outputFor(input, this.id, 'INSUFFICIENT_EVIDENCE', [...new Set([...reasons, 'EVIDENCE_INSUFFICIENT'])], channels);
      const crossed = spo2Value < threshold || (input.baselineByChannel.spo2.deviation ?? 0) < -5;
      if (crossed && input.baselineByChannel.spo2.persistentDeviation) return outputFor(input, this.id, 'MULTI_SIGNAL_SUPPORTED_EVENT', reasons, ['spo2']);
      if (crossed) return outputFor(input, this.id, 'LOW_CONFIDENCE_CHANGE', [...new Set([...reasons, 'EVIDENCE_INSUFFICIENT'])], ['spo2']);
      return outputFor(input, this.id, 'NOMINAL', reasons, []);
    },
  };
}

export function createReliabilityAwareAlgorithm(options = {}) {
  const minimumTrust = options.minimumTrust ?? 0.55;
  const minimumAgreement = options.minimumAgreement ?? 0.58;
  return {
    id: 'reliability-aware',
    name: 'Reliability-aware comparison arm',
    classify(input) {
      const channels = changedChannels(input);
      const reasons = baseReasons(input, channels);
      if (input.unavailableChannels.length >= 2 || input.contradictoryEvidence) {
        return outputFor(input, this.id, 'INSUFFICIENT_EVIDENCE', [...new Set([...reasons, 'EVIDENCE_INSUFFICIENT'])], channels);
      }
      if (!channels.length) return outputFor(input, this.id, 'NOMINAL', reasons, []);
      const lowQuality = qualityMean(input) < 0.62;
      const lowTrust = trustMean(input) < minimumTrust;
      const artifact = input.quality.some((item) => item.features.artifactOverlap > 0.2);
      if (artifact || lowQuality || lowTrust) {
        return outputFor(input, this.id, artifact ? 'ARTIFACT_CONSISTENT_ANOMALY' : 'LOW_CONFIDENCE_CHANGE', reasons, channels);
      }
      if (channels.length >= 3 && input.crossSignalAgreement >= 0.78 && channels.some((channel) => input.baselineByChannel[channel].persistentDeviation)) {
        return outputFor(input, this.id, 'HIGH_EVIDENCE_MULTI_SIGNAL_CHANGE', reasons, channels);
      }
      if (channels.length >= 2 && input.crossSignalAgreement >= minimumAgreement) {
        return outputFor(input, this.id, 'MULTI_SIGNAL_SUPPORTED_EVENT', reasons, channels);
      }
      return outputFor(input, this.id, 'LOW_CONFIDENCE_CHANGE', [...new Set([...reasons, 'EVIDENCE_INSUFFICIENT'])], channels);
    },
  };
}

export function algorithmsFor(ids) {
  const available = { 'threshold-baseline': createThresholdBaselineAlgorithm(), 'reliability-aware': createReliabilityAwareAlgorithm() };
  return ids.map((id) => available[id]).filter(Boolean);
}

export function isAlertClassification(classification) {
  return classification === 'ARTIFACT_CONSISTENT_ANOMALY' || classification === 'MULTI_SIGNAL_SUPPORTED_EVENT' || classification === 'HIGH_EVIDENCE_MULTI_SIGNAL_CHANGE';
}

export function isUncertainClassification(classification) {
  return classification === 'LOW_CONFIDENCE_CHANGE' || classification === 'INSUFFICIENT_EVIDENCE';
}
