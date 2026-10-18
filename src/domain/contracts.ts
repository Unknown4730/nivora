/**
 * Shared browser/domain contract for AURA-Med Lab.
 *
 * All values are simulated research-prototype data. Time is relative to a run
 * in seconds; no patient, device, or clinical fields belong in this contract.
 */

export type ScenarioId = 'clean' | 'motion-artifact' | 'dropout';
export type AlgorithmId = 'threshold-baseline' | 'reliability-aware';
export type ChannelId = 'spo2' | 'heart-rate' | 'respiration';
export type PredictionClass = 'normal' | 'alert' | 'uncertain';
export type AnnotationKind = 'simulated-event' | 'sensor-artifact';

export interface RunConfig {
  scenario: ScenarioId;
  durationSec: number;
  sampleRateHz: number;
  artifactIntensity: number; // 0..1
  algorithms: AlgorithmId[];
  seed: number;
}

export interface SignalSample {
  tSec: number;
  spo2Pct: number | null;
  heartRateBpm: number | null;
  respirationBpm: number | null;
}

export interface Annotation {
  id: string;
  kind: AnnotationKind;
  label: string;
  startSec: number;
  endSec: number;
  channels: ChannelId[];
  severity?: 'low' | 'medium' | 'high';
}

export interface QualityFeatures {
  missingFraction: number; // 0..1
  noiseEstimate: number; // 0..1, higher is noisier
  artifactOverlap: number; // 0..1
  morphologyConsistency: number; // 0..1
}

export interface ChannelQuality {
  channel: ChannelId;
  score: number; // 0..1
  features: QualityFeatures;
  reasons: string[];
}

export interface EvidenceWindow {
  startSec: number;
  endSec: number;
  quality: ChannelQuality[];
  crossSignalAgreement: number; // 0..1
  trustByChannel: Record<ChannelId, number>; // each 0..1
  baselineByChannel: Partial<Record<ChannelId, number>>;
  trendByChannel: Partial<Record<ChannelId, number>>;
}

export interface Prediction {
  algorithmId: AlgorithmId;
  startSec: number;
  endSec: number;
  classification: PredictionClass;
  confidence: number; // 0..1; confidence is algorithmic, not clinical
  channels: ChannelId[];
  reasonCodes: string[];
}

export interface BenchmarkMetrics {
  nuisanceAlerts: number;
  missedEvents: number;
  detectionLatencySec: Array<number | null>;
  uncertainWindowCount: number;
  uncertainDurationSec: number;
  truthEventCount: number;
  predictionCount: number;
}

export interface AlgorithmResult {
  algorithmId: AlgorithmId;
  predictions: Prediction[];
  metrics: BenchmarkMetrics;
}

export interface ExplanationItem {
  code: string;
  title: string;
  detail: string;
  evidenceWindow?: { startSec: number; endSec: number };
}

export interface SimulationRun {
  runId: string;
  config: RunConfig;
  samples: SignalSample[];
  annotations: Annotation[];
  evidence: EvidenceWindow[];
  results: AlgorithmResult[];
  explanations: ExplanationItem[];
}
