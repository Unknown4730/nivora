import { clamp, createSeededRandom, round } from './prng.js';
import { CHANNELS, SIGNAL_META, getScenarioDefinition, isInInterval } from './scenarios.js';

function smoothPulse(tSec, startSec, endSec) {
  if (tSec < startSec || tSec >= endSec) return 0;
  const progress = (tSec - startSec) / Math.max(0.001, endSec - startSec);
  return Math.sin(Math.PI * progress);
}

function ramp(tSec, startSec, endSec) {
  if (tSec < startSec || tSec >= endSec) return 0;
  return clamp((tSec - startSec) / Math.max(0.001, endSec - startSec));
}

function gaussianish(random) {
  return (random() + random() + random() + random() - 2) / 2;
}

function cleanValue(channel, tSec, random) {
  const meta = SIGNAL_META[channel];
  const phase = { spo2: 0.7, 'heart-rate': 1.9, respiration: 2.8 }[channel];
  const cycle = { spo2: 0.08, 'heart-rate': 0.19, respiration: 0.32 }[channel];
  const amplitude = { spo2: 0.35, 'heart-rate': 2.2, respiration: 0.8 }[channel];
  return meta.baseline + Math.sin(tSec * cycle + phase) * amplitude + gaussianish(random) * { spo2: 0.12, 'heart-rate': 0.8, respiration: 0.35 }[channel];
}

function eventDelta(channel, tSec, scenario) {
  const event = scenario.groundTruth;
  if (!event.physiologicalEventExists || event.eventStartSec == null || event.eventEndSec == null) return 0;
  const strength = scenario.id === 'gradual-deterioration'
    ? Math.min(ramp(tSec, event.eventStartSec, event.eventStartSec + 24), 1 - ramp(tSec, event.eventEndSec - 18, event.eventEndSec))
    : smoothPulse(tSec, event.eventStartSec, event.eventEndSec);
  const maximum = { spo2: -8, 'heart-rate': 25, respiration: 9 }[channel];
  return maximum * Math.max(0, strength);
}

function artifactValue(channel, value, tSec, scenario, intensity, random) {
  const artifact = scenario.annotations.find((item) => item.kind !== 'simulated-event' && item.channels.includes(channel));
  if (!artifact || !isInInterval(tSec, artifact.startSec, artifact.endSec)) return value;
  const level = clamp(intensity);
  const motionNoise = { spo2: 7, 'heart-rate': 25, respiration: 11 }[channel] * level;
  let result = value + gaussianish(random) * motionNoise;
  if (scenario.id === 'loose-spo2-sensor' && channel === 'spo2') {
    result += Math.sin(tSec * 2.2) * 5 * level;
    if (random() < 0.12 * level) result = random() < 0.5 ? 82 : 100;
  }
  if (scenario.id === 'motion-artifact' && random() < 0.1 * level) {
    const meta = SIGNAL_META[channel];
    result = random() < 0.5 ? meta.plausibility[0] : meta.plausibility[1];
  }
  return result;
}

function shouldDisconnect(channel, tSec, scenario, random) {
  const artifact = scenario.annotations.find((item) => item.kind === 'sensor-disconnection' && item.channels.includes(channel));
  if (!artifact || !isInInterval(tSec, artifact.startSec, artifact.endSec)) return false;
  return random() < (channel === 'spo2' || channel === 'heart-rate' ? 0.96 : 0.35);
}

export function validateGenerationConfig(config) {
  if (!Number.isFinite(config.durationSec) || config.durationSec <= 0) throw new Error('durationSec must be greater than zero');
  if (!Number.isFinite(config.sampleRateHz) || config.sampleRateHz <= 0) throw new Error('sampleRateHz must be greater than zero');
  if (!Number.isFinite(config.artifactIntensity) || config.artifactIntensity < 0 || config.artifactIntensity > 1) throw new Error('artifactIntensity must be between 0 and 1');
}

export function generateSimulatedSignals(config, scenarioInput = getScenarioDefinition(config.scenario, config.durationSec)) {
  validateGenerationConfig(config);
  const random = createSeededRandom(config.seed);
  const sampleCount = Math.round(config.durationSec * config.sampleRateHz);
  const samples = [];
  const valuesByChannel = Object.fromEntries(CHANNELS.map((channel) => [channel, []]));

  for (let index = 0; index <= sampleCount; index += 1) {
    const tSec = index / config.sampleRateHz;
    const values = {};
    for (const channel of CHANNELS) {
      let value = cleanValue(channel, tSec, random) + eventDelta(channel, tSec, scenarioInput);
      value = artifactValue(channel, value, tSec, scenarioInput, config.artifactIntensity, random);
      if (shouldDisconnect(channel, tSec, scenarioInput, random)) {
        value = null;
      } else {
        const [minimum, maximum] = SIGNAL_META[channel].plausibility;
        value = round(value < minimum || value > maximum ? value : value, 4);
      }
      values[channel] = value;
      valuesByChannel[channel].push(value);
    }
    samples.push({ tSec: round(tSec, 4), values });
  }

  return {
    samples,
    signals: CHANNELS.map((channel) => ({ channel, unit: SIGNAL_META[channel].unit, values: valuesByChannel[channel] })),
    annotations: scenarioInput.annotations.map((item) => ({ ...item })),
  };
}
