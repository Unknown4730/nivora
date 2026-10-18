import { clamp } from './prng.js';

export const CHANNELS = ['spo2', 'heart-rate', 'respiration'];

export const SIGNAL_META = {
  spo2: { label: 'SpO₂', unit: '%', baseline: 96, plausibility: [70, 100], deviationScale: 5 },
  'heart-rate': { label: 'Heart rate', unit: 'bpm', baseline: 72, plausibility: [35, 180], deviationScale: 24 },
  respiration: { label: 'Respiration', unit: 'breaths/min', baseline: 16, plausibility: [5, 45], deviationScale: 8 },
};

function annotation(id, kind, label, startSec, endSec, channels, severity) {
  return { id, kind, label, startSec, endSec, channels, severity };
}

const DEFINITIONS = {
  'stable-baseline': {
    id: 'stable-baseline', label: 'Stable simulated baseline',
    description: 'Mostly stable simulated signals with small deterministic variation.',
    defaultDurationSec: 60,
    groundTruth: { physiologicalEventExists: false, artifactExists: false, affectedChannels: [], eventStartSec: null, eventEndSec: null, artifactStartSec: null, artifactEndSec: null, expectedEvidenceQuality: 'high', knownLimitation: 'A stable simulation does not represent all possible sensor behavior.' },
    annotations: [],
  },
  'loose-spo2-sensor': {
    id: 'loose-spo2-sensor', label: 'Loose SpO₂ sensor',
    description: 'SpO₂ is affected by a bounded artifact interval while other channels remain comparatively stable.',
    defaultDurationSec: 60,
    groundTruth: { physiologicalEventExists: false, artifactExists: true, affectedChannels: ['spo2'], eventStartSec: null, eventEndSec: null, artifactStartSec: 24, artifactEndSec: 42, expectedEvidenceQuality: 'low', knownLimitation: 'The simulation uses a hand-authored artifact recipe rather than a physical sensor model.' },
    annotations: [annotation('artifact-spo2-loose', 'sensor-artifact', 'Loose SpO₂ sensor artifact', 24, 42, ['spo2'], 'medium')],
  },
  'motion-artifact': {
    id: 'motion-artifact', label: 'Motion artifact burst',
    description: 'Motion-like noise and clipping affect all simulated channels for a bounded interval.',
    defaultDurationSec: 60,
    groundTruth: { physiologicalEventExists: false, artifactExists: true, affectedChannels: CHANNELS, eventStartSec: null, eventEndSec: null, artifactStartSec: 20, artifactEndSec: 38, expectedEvidenceQuality: 'low', knownLimitation: 'Motion is represented as deterministic noise and clipping, not measured movement.' },
    annotations: [annotation('artifact-motion', 'sensor-artifact', 'Motion artifact interval', 20, 38, CHANNELS, 'high')],
  },
  'simulated-event': {
    id: 'simulated-event', label: 'Simulated physiological event',
    description: 'A coordinated simulated change is introduced without claiming a clinical interpretation.',
    defaultDurationSec: 90,
    groundTruth: { physiologicalEventExists: true, artifactExists: false, affectedChannels: CHANNELS, eventStartSec: 34, eventEndSec: 58, artifactStartSec: null, artifactEndSec: null, expectedEvidenceQuality: 'high', knownLimitation: 'The event shape and thresholds are educational simulation parameters, not validated medical cutoffs.' },
    annotations: [annotation('event-coordinated-change', 'simulated-event', 'Simulated coordinated change', 34, 58, CHANNELS, 'high')],
  },
  'gradual-deterioration': {
    id: 'gradual-deterioration', label: 'Gradual simulated deterioration',
    description: 'Signals drift gradually from their simulated baseline and then begin recovery.',
    defaultDurationSec: 120,
    groundTruth: { physiologicalEventExists: true, artifactExists: false, affectedChannels: CHANNELS, eventStartSec: 30, eventEndSec: 86, artifactStartSec: null, artifactEndSec: null, expectedEvidenceQuality: 'high', knownLimitation: 'Gradual change can be missed during rolling-baseline warm-up or recovery.' },
    annotations: [annotation('event-gradual-change', 'simulated-event', 'Gradual simulated change', 30, 86, CHANNELS, 'medium')],
  },
  'multi-sensor-dropout': {
    id: 'multi-sensor-dropout', label: 'Multi-sensor dropout',
    description: 'Multiple channels become unavailable, creating an insufficient-evidence interval.',
    defaultDurationSec: 75,
    groundTruth: { physiologicalEventExists: false, artifactExists: true, affectedChannels: ['spo2', 'heart-rate'], eventStartSec: null, eventEndSec: null, artifactStartSec: 42, artifactEndSec: 60, expectedEvidenceQuality: 'unavailable', knownLimitation: 'Unavailable values cannot establish an underlying simulated physiological state.' },
    annotations: [annotation('artifact-multi-dropout', 'sensor-disconnection', 'Multi-sensor disconnection', 42, 60, ['spo2', 'heart-rate'], 'high')],
  },
};

const ALIASES = {
  clean: 'stable-baseline',
  motion: 'motion-artifact',
  dropout: 'multi-sensor-dropout',
  mixed: 'motion-artifact',
};

export function normalizeScenarioId(value) {
  const normalized = ALIASES[value] || value;
  if (!DEFINITIONS[normalized]) throw new Error(`Unknown simulated scenario: ${value}`);
  return normalized;
}

export function getScenarioDefinition(value, durationSec) {
  const id = normalizeScenarioId(value);
  const definition = DEFINITIONS[id];
  const duration = durationSec ?? definition.defaultDurationSec;
  const annotations = definition.annotations
    .map((item) => ({ ...item, endSec: Math.min(item.endSec, duration) }))
    .filter((item) => item.startSec < item.endSec);
  return {
    ...definition,
    annotations,
    groundTruth: {
      ...definition.groundTruth,
      eventEndSec: definition.groundTruth.eventEndSec == null ? null : Math.min(definition.groundTruth.eventEndSec, duration),
      artifactEndSec: definition.groundTruth.artifactEndSec == null ? null : Math.min(definition.groundTruth.artifactEndSec, duration),
    },
  };
}

export function isInInterval(tSec, startSec, endSec) {
  return tSec >= startSec && tSec < endSec;
}

export function annotationOverlap(startSec, endSec, annotationItem) {
  if (endSec <= startSec || annotationItem.endSec <= annotationItem.startSec) return 0;
  const overlap = Math.max(0, Math.min(endSec, annotationItem.endSec) - Math.max(startSec, annotationItem.startSec));
  return clamp(overlap / (endSec - startSec));
}
