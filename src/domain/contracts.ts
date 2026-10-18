/**
 * Shared contracts for the local-first AURA-Med Lab simulation engine.
 *
 * Every value in this file describes simulated research-prototype data. These
 * contracts intentionally contain no patient identifiers, device integrations,
 * clinical diagnoses, or validated medical thresholds.
 */

export type ScenarioId =
  | 'stable-baseline'
  | 'loose-spo2-sensor'
  | 'motion-artifact'
  | 'simulated-event'
  | 'gradual-deterioration'
  | 'multi-sensor-dropout';

export type AlgorithmId = 'threshold-baseline' | 'reliability-aware';
export type ChannelId = 'spo2' | 'heart-rate' | 'respiration';
export type ClassificationState =
  | 'NOMINAL'
  | 'LOW_CONFIDENCE_CHANGE'
  | 'ARTIFACT_CONSISTENT_ANOMALY'
  | 'MULTI_SIGNAL_SUPPORTED_EVENT'
  | 'HIGH_EVIDENCE_MULTI_SIGNAL_CHANGE'
  | 'INSUFFICIENT_EVIDENCE';
export type AnnotationKind =
  | 'simulated-event'
  | 'sensor-artifact'
  | 'sensor-disconnection';

export type ReasonCode =
  | 'SPO2_BELOW_SIMULATED_THRESHOLD'
  | 'SIGNAL_QUALITY_LOW'
  | 'MOTION_ARTIFACT_PRESENT'
  | 'SENSOR_TRUST_DECREASING'
  | 'SENSOR_TRUST_RECOVERING'
  | 'HEART_RATE_SUPPORTING_TREND'
  | 'RESPIRATION_SUPPORTING_TREND'
  | 'CROSS_SIGNAL_SUPPORT_WEAK'
  | 'CROSS_SIGNAL_SUPPORT_STRONG'
  | 'MULTIPLE_SIGNALS_UNAVAILABLE'
  | 'PERSISTENT_DEVIATION'
  | 'RECOVERY_DETECTED'
  | 'EVIDENCE_INSUFFICIENT'
  | 'MISSING_DATA_PRESENT'
  | 'ARTIFACT_CONSISTENT'
  | 'SIMULATED_EVENT_WINDOW'
  | 'NOMINAL_SIGNAL';

export interface RunConfig {
  scenario: ScenarioId;
  durationSec: number;
  sampleRateHz: number;
  artifactIntensity: number;
  algorithms: AlgorithmId[];
  seed: number;
  initialTrust?: number;
  qualityWindowSamples?: number;
  baselineWindowSamples?: number;
  requiredPersistenceSamples?: number;
}

export interface SimulatedVitalSignal {
  channel: ChannelId;
  unit: '%' | 'bpm' | 'breaths/min';
  values: Array<number | null>;
}

export interface SimulatedSignalSample {
  tSec: number;
  values: Record<ChannelId, number | null>;
}

export type VitalSignal = SimulatedVitalSignal;
export type SignalSample = SimulatedSignalSample;

export interface SimulatedGroundTruth {
  physiologicalEventExists: boolean;
  artifactExists: boolean;
  affectedChannels: ChannelId[];
  eventStartSec: number | null;
  eventEndSec: number | null;
  artifactStartSec: number | null;
  artifactEndSec: number | null;
  expectedEvidenceQuality: 'high' | 'mixed' | 'low' | 'unavailable';
  knownLimitation: string;
}

export interface SimulatedScenarioDefinition {
  id: ScenarioId;
  label: string;
  description: string;
  defaultDurationSec: number;
  groundTruth: SimulatedGroundTruth;
  annotations: SimulatedGroundTruthAnnotation[];
}

export interface SimulatedGroundTruthAnnotation {
  id: string;
  kind: AnnotationKind;
  label: string;
  startSec: number;
  endSec: number;
  channels: ChannelId[];
  severity?: 'low' | 'medium' | 'high';
}

export type Annotation = SimulatedGroundTruthAnnotation;

export interface SignalQualityFeatures {
  shortWindowStability: number;
  valuePlausibility: number;
  continuity: number;
  missingDataPenalty: number;
  artifactPenalty: number;
  crossSensorConsistency: number;
  missingFraction: number;
  noiseEstimate: number;
  artifactOverlap: number;
}

export interface SignalQuality {
  channel: ChannelId;
  score: number;
  features: SignalQualityFeatures;
  reasonCodes: ReasonCode[];
}

export type ChannelQuality = SignalQuality;

export interface SensorTrust {
  channel: ChannelId;
  score: number;
  previousScore: number;
  direction: 'decreasing' | 'stable' | 'recovering';
  qualityContribution: number;
  agreementContribution: number;
}

export interface SimulatedRollingBaseline {
  channel: ChannelId;
  value: number | null;
  deviation: number | null;
  trendPerSample: number | null;
  persistentDeviation: boolean;
  recoveryDetected: boolean;
  historyCount: number;
}

export interface EvidenceWindow {
  windowId: string;
  startSec: number;
  endSec: number;
  quality: SignalQuality[];
  trustByChannel: Record<ChannelId, SensorTrust>;
  baselineByChannel: Record<ChannelId, SimulatedRollingBaseline>;
  crossSignalAgreement: number;
  unavailableChannels: ChannelId[];
  contradictoryEvidence: boolean;
}

export interface AlgorithmInput {
  windowId: string;
  sample: SimulatedSignalSample;
  quality: SignalQuality[];
  trustByChannel: Record<ChannelId, SensorTrust>;
  baselineByChannel: Record<ChannelId, SimulatedRollingBaseline>;
  crossSignalAgreement: number;
  unavailableChannels: ChannelId[];
  contradictoryEvidence: boolean;
  requiredPersistenceSamples: number;
  sampleIntervalSec?: number;
}

export interface AlgorithmOutput {
  algorithmId: AlgorithmId;
  windowId: string;
  startSec: number;
  endSec: number;
  classification: ClassificationState;
  confidence: number;
  channels: ChannelId[];
  reasonCodes: ReasonCode[];
  explanation: StructuredExplanation;
}

export interface AlarmAlgorithm {
  id: AlgorithmId;
  name: string;
  classify(input: AlgorithmInput): AlgorithmOutput;
}

export interface TimelineEvent {
  startSec: number;
  endSec: number;
  label: string;
  kind: 'truth' | 'prediction' | 'quality' | 'trust' | 'recovery';
  sourceId: string;
}

export interface Prediction extends TimelineEvent {
  algorithmId: AlgorithmId;
  predictionId: string;
  classification: ClassificationState;
  confidence: number;
  channels: ChannelId[];
  reasonCodes: ReasonCode[];
  explanation: StructuredExplanation;
}

export interface BenchmarkMetrics {
  totalAlerts: number;
  nuisanceAlerts: number;
  detectedSimulatedEvents: number;
  missedSimulatedEvents: number;
  detectionLatencySec: Array<number | null>;
  uncertaintyClassificationCount: number;
  uncertainWindowCount: number;
  uncertainDurationSec: number;
  trustRecoveryTimeSec: Array<number | null>;
  explanationCompleteness: number;
  truthEventCount: number;
  predictionCount: number;
}

export interface AlgorithmResult {
  algorithmId: AlgorithmId;
  algorithmName: string;
  outputs: AlgorithmOutput[];
  predictions: Prediction[];
  metrics: BenchmarkMetrics;
}

export interface StructuredExplanation {
  title: string;
  detail: string;
  reasonCodes: ReasonCode[];
  evidenceWindowId: string;
  values: Record<string, number | string | boolean | null>;
}

export interface ExplanationItem extends StructuredExplanation {
  algorithmId: AlgorithmId;
  classification: ClassificationState;
  startSec: number;
  endSec: number;
}

export interface SimulationRun {
  schemaVersion: '1.0';
  runId: string;
  seed: number;
  config: RunConfig;
  scenario: SimulatedScenarioDefinition;
  signals: SimulatedVitalSignal[];
  samples: SimulatedSignalSample[];
  annotations: SimulatedGroundTruthAnnotation[];
  evidence: EvidenceWindow[];
  results: AlgorithmResult[];
  explanations: ExplanationItem[];
}
