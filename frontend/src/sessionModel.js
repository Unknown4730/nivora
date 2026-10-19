export const CHANNELS = {
  spo2: { label: "SpO₂", unit: "%", color: "#148a7e", domain: [70, 100], decimals: 1 },
  "heart-rate": { label: "Heart rate", unit: "bpm", color: "#d4793b", domain: [35, 180], decimals: 0 },
  respiration: { label: "Respiration", unit: "breaths/min", color: "#7165c8", domain: [5, 45], decimals: 1 },
};

export const CHANNEL_IDS = Object.keys(CHANNELS);

export const SCENARIO_FALLBACKS = [
  { id: "stable-baseline", label: "Stable simulated baseline", description: "Mostly stable simulated signals with small deterministic variation.", default_duration_sec: 60 },
  { id: "loose-spo2-sensor", label: "Loose SpO₂ sensor", description: "SpO₂ is affected by a bounded artifact interval.", default_duration_sec: 60 },
  { id: "motion-artifact", label: "Motion artifact burst", description: "Motion-like noise and clipping affect simulated channels.", default_duration_sec: 60 },
  { id: "simulated-event", label: "Simulated coordinated change", description: "A coordinated simulated change is introduced.", default_duration_sec: 90 },
  { id: "gradual-deterioration", label: "Gradual simulated change", description: "Signals drift gradually from their simulated baseline.", default_duration_sec: 120 },
  { id: "multi-sensor-dropout", label: "Multi-sensor dropout", description: "Multiple channels become unavailable for a bounded interval.", default_duration_sec: 75 },
];

export const initialLiveState = {
  sessionState: "idle",
  connection: "idle",
  snapshot: null,
  latestSample: null,
  samples: [],
  failures: [],
  qualityBySample: {},
  technicalEvents: [],
  metrics: {},
  sourceComplete: false,
};

export function mergeSnapshot(state, snapshot) {
  if (!snapshot) return state;
  return {
    ...state,
    snapshot,
    sessionState: snapshot.state || state.sessionState,
    metrics: snapshot.metrics || state.metrics,
    sourceComplete: Boolean(snapshot.metrics?.sourceComplete),
  };
}

export function mergeReviewArtifacts(state, session, report, failures, replay) {
  const samples = Array.isArray(replay?.samples) ? replay.samples : [];
  return {
    ...state,
    snapshot: session,
    sessionState: session?.state || report?.state || "stopped",
    connection: "closed",
    latestSample: samples.at(-1) || null,
    samples,
    failures: Array.isArray(failures?.failures) ? failures.failures : [],
    metrics: report?.metrics || session?.metrics || {},
    sourceComplete: Boolean(report?.metrics?.sourceComplete),
    technicalEvents: [],
  };
}

export function reduceLiveEvent(state, event) {
  if (!event || typeof event !== "object") return state;
  const payload = event.payload || {};

  if (event.type === "status") {
    return {
      ...state,
      sessionState: payload.state || state.sessionState,
      metrics: payload.metrics || state.metrics,
      connection: payload.state === "stopped" ? "closed" : state.connection,
      sourceComplete: Boolean(payload.metrics?.sourceComplete),
    };
  }

  if (event.type === "sample" && payload.sample) {
    const sample = payload.sample;
    return {
      ...state,
      latestSample: sample,
      samples: [...state.samples, sample].slice(-240),
      technicalEvents: [...state.technicalEvents, event].slice(-120),
    };
  }

  if (event.type === "quality") {
    const nextQuality = { ...state.qualityBySample };
    if (payload.sampleId) nextQuality[payload.sampleId] = payload;
    return {
      ...state,
      qualityBySample: nextQuality,
      technicalEvents: [...state.technicalEvents, event].slice(-120),
    };
  }

  if (event.type === "failure" && payload.failure) {
    return {
      ...state,
      failures: [...state.failures, payload.failure],
      technicalEvents: [...state.technicalEvents, event].slice(-120),
    };
  }

  if (event.type === "disconnect") {
    return {
      ...state,
      connection: "interrupted",
      technicalEvents: [...state.technicalEvents, event].slice(-120),
    };
  }

  if (event.type === "reconnect") {
    return {
      ...state,
      connection: "connected",
      technicalEvents: [...state.technicalEvents, event].slice(-120),
    };
  }

  return {
    ...state,
    technicalEvents: [...state.technicalEvents, event].slice(-120),
  };
}

function hasMissingReading(state) {
  return Boolean(
    state.metrics?.missing > 0 ||
      state.latestSample?.qualityFlags?.some((flag) => ["missing", "delayed"].includes(flag)) ||
      Object.values(state.latestSample?.values || {}).some((value) => value === null),
  );
}

export function statusCopy(state) {
  if (state.connection === "interrupted" || state.connection === "error" || state.sessionState === "reconnecting") {
    return { label: "Connection interrupted", tone: "coral", detail: "A sensor connection interruption was detected." };
  }
  if (hasMissingReading(state)) {
    return { label: "Some readings are missing", tone: "amber", detail: "Some readings were delayed or missing, so the system is being cautious." };
  }
  if (state.failures.length > 0 || state.metrics?.dropped > 0) {
    return { label: "Review recommended", tone: "amber", detail: "The system recorded a technical event and marked the affected window for review." };
  }
  if (state.sessionState === "stopped") {
    return { label: "Session stopped", tone: "slate", detail: "The stream has ended. Review the recorded technical timeline before exporting." };
  }
  if (["streaming", "degraded", "reconnecting"].includes(state.sessionState)) {
    return { label: "Stream healthy", tone: "teal", detail: "The system is receiving readings normally." };
  }
  if (state.sessionState === "created") {
    return { label: "Session prepared", tone: "slate", detail: "The virtual session is ready to start." };
  }
  return { label: "Ready to begin", tone: "slate", detail: "Choose the simulation settings, then start a virtual stream." };
}

export function channelValue(sample, channel) {
  const value = sample?.values?.[channel];
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return Number(value).toFixed(CHANNELS[channel].decimals);
}

function readBackendChannelField(sample, names, channel) {
  for (const name of names) {
    const candidate = sample?.[name]?.[channel];
    if (candidate !== undefined && candidate !== null) return candidate;
  }
  return undefined;
}

export function channelTrend(sample, channel) {
  const value = readBackendChannelField(sample, ["trendByChannel", "trends", "analysis"], channel);
  if (typeof value === "string") return value.replaceAll("_", " ");
  if (value && typeof value === "object") {
    const label = value.label || value.direction || value.trend;
    if (typeof label === "string") return label.replaceAll("_", " ");
  }
  return "Not supplied by live stream";
}

export function channelTrust(sample, channel) {
  const value = readBackendChannelField(sample, ["trustByChannel", "trust"], channel);
  if (typeof value === "number" && Number.isFinite(value)) return `${Math.round(value * 100)}%`;
  if (value && typeof value === "object") {
    if (typeof value.score === "number" && Number.isFinite(value.score)) return `${Math.round(value.score * 100)}%`;
    if (typeof value.label === "string") return value.label;
  }
  return "Not supplied";
}

export function channelQuality(sample, qualityEvent, channel) {
  const flags = sample?.qualityFlags || qualityEvent?.qualityFlags || [];
  if (sample?.values?.[channel] === null || flags.includes("missing")) return "Missing reading";
  if (flags.includes("disconnected")) return "Connection interrupted";
  if (flags.length) return flags.map((flag) => flag.replaceAll("_", " ")).join(", ");
  if (!sample) return "Waiting for reading";
  return "No quality flags";
}

export function failureTitle(type) {
  const titles = {
    packet_loss: "Some packets were missing",
    duplicate_packet: "A duplicate packet was received",
    out_of_order_packet: "Packets arrived out of order",
    timeout_disconnect: "Sensor connection interruption",
    reconnect: "Sensor connection restored",
    missing_value: "A reading was missing",
    out_of_range: "A reading was outside expected bounds",
    jitter_latency_exceeded: "Timing varied more than expected",
    storage_failure: "Recording was interrupted",
    processing_backpressure: "The processing queue was busy",
    insufficient_evidence: "There was not enough data in this window",
  };
  return titles[type] || "A technical stream event was recorded";
}

export function failureDuration(failure, failures) {
  if (failure?.recoveryInfo?.durationSec !== undefined) return `${Number(failure.recoveryInfo.durationSec).toFixed(1)}s`;
  if (failure?.status === "recovered") {
    const earlier = failures.find(
      (candidate) => candidate.failureId === failure.failureId && candidate !== failure && candidate.relativeTimeSec <= failure.relativeTimeSec,
    );
    if (earlier) return `${Math.max(0, failure.relativeTimeSec - earlier.relativeTimeSec).toFixed(1)}s`;
  }
  return failure?.status === "open" ? "Open" : "Not provided";
}

export function friendlyChannel(channel) {
  return CHANNELS[channel]?.label || channel || "All channels";
}
