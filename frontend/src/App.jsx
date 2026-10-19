import { useEffect, useMemo, useRef, useState } from "react";
import {
  createLiveSession,
  createLiveSocket,
  exportUrl,
  getLiveFailures,
  getLiveReport,
  getLiveSession,
  listScenarios,
  startLiveSession,
  stopLiveSession,
} from "./api.js";
import {
  CHANNELS,
  CHANNEL_IDS,
  SCENARIO_FALLBACKS,
  channelQuality,
  channelTrust,
  channelTrend,
  channelValue,
  failureDuration,
  failureTitle,
  friendlyChannel,
  initialLiveState,
  mergeSnapshot,
  reduceLiveEvent,
  statusCopy,
} from "./sessionModel.js";

const DEFAULT_CONFIG = {
  scenario: "stable-baseline",
  durationSec: 45,
  sampleRateHz: 1,
  seed: 20261018,
  speed: 1,
  faultProfile: "none",
};

const FAULT_PROFILES = [
  { id: "none", label: "No injected fault", help: "A clean simulated transport stream." },
  { id: "packet-loss", label: "Missing packets", help: "Drops a small set of scheduled packets." },
  { id: "missing-values", label: "Missing channel values", help: "Leaves selected values unavailable for review." },
  { id: "disconnect", label: "Sensor interruption", help: "Temporarily interrupts the virtual connection." },
  { id: "jitter", label: "Delayed readings", help: "Adds deterministic delivery delay to selected readings." },
];

function buildFaults(config) {
  const sampleCount = Math.max(2, Math.round(Number(config.durationSec) * Number(config.sampleRateHz)));
  const middle = Math.max(1, Math.floor(sampleCount * 0.45));
  if (config.faultProfile === "packet-loss") return [{ type: "packet_loss", atSamples: [middle, middle + 2] }];
  if (config.faultProfile === "missing-values") return [{ type: "missing_values", atSamples: [middle], channels: ["spo2", "heart-rate"] }];
  if (config.faultProfile === "disconnect") return [{ type: "disconnect_reconnect", startSample: middle, durationSamples: Math.max(2, Math.floor(sampleCount * 0.08)) }];
  if (config.faultProfile === "jitter") return [{ type: "jitter_delay", atSamples: [middle], delaySec: 1.5 }];
  return [];
}

function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return Number(value).toFixed(digits);
}

function formatSeconds(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toFixed(2)} s`;
}

function formatFaultType(type) {
  return String(type || "not recorded").replaceAll("_", " ");
}

function toneClasses(tone) {
  return {
    teal: "border-teal-100 bg-teal-50 text-teal-700",
    amber: "border-amber-100 bg-amber-50 text-amber-600",
    coral: "border-coral-100 bg-coral-50 text-coral-600",
    slate: "border-slate-200 bg-slate-50 text-slate-600",
  }[tone] || "border-slate-200 bg-slate-50 text-slate-600";
}

function StatusDot({ tone = "slate" }) {
  const colors = { teal: "bg-teal-500", amber: "bg-amber-600", coral: "bg-coral-600", slate: "bg-slate-400" };
  return <span aria-hidden="true" className={`inline-block h-2.5 w-2.5 rounded-full ${colors[tone] || colors.slate}`} />;
}

function StatusSummary({ liveState }) {
  const copy = statusCopy(liveState);
  return (
    <section className={`rounded-2xl border p-5 ${toneClasses(copy.tone)}`} aria-live="polite">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <StatusDot tone={copy.tone} />
          <div>
            <p className="mono-label">Live stream status</p>
            <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em]">{copy.label}</h2>
          </div>
        </div>
        <p className="max-w-md text-sm leading-6">{copy.detail}</p>
      </div>
    </section>
  );
}

function SignalCard({ channel, sample, qualityEvent }) {
  const meta = CHANNELS[channel];
  const missing = sample?.values?.[channel] === null || sample?.values?.[channel] === undefined;
  const quality = channelQuality(sample, qualityEvent, channel);
  return (
    <article className="panel p-5" aria-label={`${meta.label} live signal`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="mono-label flex items-center gap-2">
            <span aria-hidden="true" className="h-2 w-2 rounded-full" style={{ backgroundColor: meta.color }} />
            Live signal
          </p>
          <h2 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-ink">{meta.label}</h2>
        </div>
        <span className="font-mono text-[11px] text-quiet">{meta.unit}</span>
      </div>

      <div className="mt-6 flex items-baseline gap-3">
        <span className="text-3xl font-semibold tracking-[-0.06em] text-ink">{channelValue(sample, channel)}</span>
        <span className={`text-xs font-semibold ${missing ? "text-amber-600" : "text-quiet"}`}>
          {missing ? "Missing" : channelTrend(sample, channel)}
        </span>
      </div>
      <p className="mt-1 text-xs text-quiet">
        {sample ? `Latest reading at ${formatNumber(sample.relativeTimeSec, 1)} s` : "Waiting for the first reading"}
      </p>

      <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-line pt-4 text-xs">
        <div>
          <dt className="text-quiet">Quality</dt>
          <dd className="mt-1 font-semibold capitalize text-ink">{quality}</dd>
        </div>
        <div>
          <dt className="text-quiet">Trust</dt>
          <dd className="mt-1 font-semibold text-ink">{channelTrust(sample, channel)}</dd>
        </div>
      </dl>
      <p className={`mt-4 min-h-5 text-xs ${missing ? "font-semibold text-amber-600" : "text-quiet"}`}>
        {missing ? "This channel has no usable value in the latest sample." : "Missing state: no missing value reported."}
      </p>
    </article>
  );
}

function Chart({ samples, durationSec }) {
  const width = 760;
  const height = 285;
  const pad = { top: 18, right: 16, bottom: 28, left: 16 };
  const innerWidth = width - pad.left - pad.right;
  const innerHeight = height - pad.top - pad.bottom;

  function pathFor(channel) {
    const [minimum, maximum] = CHANNELS[channel].domain;
    let path = "";
    let drawing = false;
    samples.forEach((sample) => {
      const value = sample?.values?.[channel];
      if (value === null || value === undefined || !Number.isFinite(Number(value))) {
        drawing = false;
        return;
      }
      const x = pad.left + (Math.max(0, Number(sample.relativeTimeSec) || 0) / Math.max(1, durationSec)) * innerWidth;
      const y = pad.top + (1 - Math.min(1, Math.max(0, (Number(value) - minimum) / (maximum - minimum)))) * innerHeight;
      path += `${drawing ? " L" : "M"}${x.toFixed(2)} ${y.toFixed(2)}`;
      drawing = true;
    });
    return path;
  }

  const labels = [0, 0.25, 0.5, 0.75, 1].map((fraction) => `${formatNumber(Number(durationSec) * fraction, 0)}s`);
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="mono-label">Signal traces</p>
          <h2 className="section-title mt-1">Live sample history</h2>
        </div>
        <div className="flex flex-wrap gap-3 text-xs text-quiet" aria-label="Chart legend">
          {CHANNEL_IDS.map((channel) => (
            <span key={channel} className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: CHANNELS[channel].color }} />
              {CHANNELS[channel].label}
            </span>
          ))}
        </div>
      </div>
      <div className="overflow-hidden rounded-xl border border-line bg-slate-50/60">
        {samples.length === 0 ? (
          <div className="flex h-[285px] flex-col items-center justify-center gap-2 px-6 text-center text-sm text-quiet">
            <span className="text-3xl text-teal-500" aria-hidden="true">⌁</span>
            <p>No samples yet. Start a session to see the stream draw here.</p>
          </div>
        ) : (
          <svg className="block h-auto w-full" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Live traces for the three simulated channels">
            {[0, 0.25, 0.5, 0.75, 1].map((fraction) => {
              const y = pad.top + fraction * innerHeight;
              return <line key={fraction} x1={pad.left} x2={width - pad.right} y1={y} y2={y} stroke="#dce9e4" strokeWidth="1" />;
            })}
            {CHANNEL_IDS.map((channel) => (
              <path key={channel} d={pathFor(channel)} fill="none" stroke={CHANNELS[channel].color} strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" />
            ))}
          </svg>
        )}
      </div>
      <div className="mt-2 flex justify-between px-1 font-mono text-[10px] text-quiet" aria-hidden="true">
        {labels.map((label) => <span key={label}>{label}</span>)}
      </div>
      <p className="mt-4 text-xs leading-5 text-quiet">The chart shows values supplied by the stream. Missing values create visible gaps; no frontend quality or classification score is calculated.</p>
    </div>
  );
}

function WhatIsHappening({ liveState, report }) {
  const copy = statusCopy(liveState);
  const reportSummary = report?.summary;
  return (
    <section className="panel h-full p-5" aria-live="polite">
      <p className="mono-label">Plain-English view</p>
      <h2 className="section-title mt-1">What is happening?</h2>
      <div className={`mt-5 rounded-xl border p-4 ${toneClasses(copy.tone)}`}>
        <div className="flex items-start gap-3">
          <StatusDot tone={copy.tone} />
          <p className="text-sm font-semibold leading-6">{reportSummary || copy.detail}</p>
        </div>
      </div>
      <div className="mt-5 space-y-4 text-sm leading-6 text-quiet">
        <p>
          This panel translates transport and signal-quality events into plain English. It does not make a diagnosis or a clinical judgment.
        </p>
        <p>
          {liveState.latestSample ? `The latest sample arrived at ${formatNumber(liveState.latestSample.relativeTimeSec, 1)} seconds in the virtual timeline.` : "The stream has not supplied a sample yet."}
        </p>
      </div>
    </section>
  );
}

function TechnicalDetails({ liveState, report }) {
  const metrics = report?.metrics || liveState.metrics || {};
  const metricRows = [
    ["Expected sequence extent", metrics.expected],
    ["Received samples", metrics.received],
    ["Missing packets / values", metrics.missing],
    ["Duplicate packets", metrics.duplicates ?? metrics.duplicate],
    ["Out-of-order packets", metrics.outOfOrder ?? metrics.out_of_order],
    ["Mean latency", formatSeconds(metrics.latencyMeanSec ?? metrics.latency?.meanSec)],
    ["Maximum latency", formatSeconds(metrics.latencyMaxSec ?? metrics.latency?.maxSec)],
    ["Mean jitter", formatSeconds(metrics.jitterMeanSec ?? metrics.jitter?.meanSec)],
    ["Maximum jitter", formatSeconds(metrics.jitterMaxSec ?? metrics.jitter?.maxSec)],
    ["Queue depth", metrics.queueDepth],
    ["Dropped events", metrics.dropped],
    ["Disconnects / reconnects", `${metrics.disconnects ?? 0} / ${metrics.reconnects ?? 0}`],
  ];
  return (
    <details className="panel group" defaultOpen={Boolean(liveState.snapshot)}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 p-5 [&::-webkit-details-marker]:hidden">
        <div>
          <p className="mono-label">For engineers</p>
          <h2 className="section-title mt-1">Technical details</h2>
        </div>
        <span className="rounded-full border border-line px-3 py-1 text-xs font-semibold text-quiet transition group-open:bg-slate-50">Expand</span>
      </summary>
      <div className="border-t border-line px-5 pb-5 pt-4">
        {!liveState.snapshot ? (
          <p className="text-sm text-quiet">Technical metrics will appear after a session is created.</p>
        ) : (
          <>
            <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
              {metricRows.map(([label, value]) => (
                <div key={label} className="border-b border-line/70 pb-2">
                  <p className="text-xs text-quiet">{label}</p>
                  <p className="mt-1 font-mono text-sm font-semibold text-ink">{value ?? "—"}</p>
                </div>
              ))}
            </div>
            <div className="mt-6 grid gap-5 lg:grid-cols-2">
              <div>
                <p className="mono-label">Failure IDs</p>
                {liveState.failures.length ? (
                  <ul className="mt-2 space-y-1 font-mono text-xs text-ink">
                    {liveState.failures.map((failure, index) => <li key={`${failure.failureId}-${index}`}>{failure.failureId}</li>)}
                  </ul>
                ) : <p className="mt-2 text-sm text-quiet">No failure IDs recorded.</p>}
              </div>
              <div>
                <p className="mono-label">Failure types</p>
                {liveState.failures.length ? (
                  <ul className="mt-2 space-y-1 font-mono text-xs text-ink">
                    {liveState.failures.map((failure, index) => <li key={`${failure.failureId || "failure"}-type-${index}`}>{formatFaultType(failure.type)}</li>)}
                  </ul>
                ) : <p className="mt-2 text-sm text-quiet">No failure types recorded.</p>}
              </div>
            </div>
          </>
        )}
      </div>
    </details>
  );
}

function FailureTimeline({ failures }) {
  return (
    <section className="panel p-5" aria-labelledby="timeline-heading">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="mono-label">Review trail</p>
          <h2 id="timeline-heading" className="section-title mt-1">Failure and review timeline</h2>
        </div>
        <span className="tag">{failures.length} recorded</span>
      </div>
      {failures.length === 0 ? (
        <div className="mt-5 rounded-xl border border-dashed border-line bg-slate-50/60 p-6 text-center text-sm text-quiet">
          No technical events have been recorded. Events from the live stream will appear here.
        </div>
      ) : (
        <div className="mt-5 space-y-3">
          {failures.map((failure, index) => {
            const status = failure.status || "open";
            const affected = failure.affectedChannels?.length ? failure.affectedChannels.map(friendlyChannel).join(", ") : "Not channel-specific";
            return (
              <article key={`${failure.failureId || "failure"}-${index}`} className="rounded-xl border border-line bg-slate-50/50 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-quiet">{formatNumber(failure.relativeTimeSec, 2)} s</p>
                    <h3 className="mt-1 text-sm font-semibold text-ink">{failureTitle(failure.type)}</h3>
                  </div>
                  <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize ${status === "recovered" ? "bg-teal-100 text-teal-700" : status === "reviewed" ? "bg-slate-200 text-slate-700" : "bg-amber-100 text-amber-600"}`}>{status}</span>
                </div>
                <p className="mt-3 text-sm leading-5 text-quiet">{status === "recovered" ? "The backend recorded recovery for this technical event." : `The event affected ${affected.toLowerCase()}.`}</p>
                <dl className="mt-4 grid gap-3 border-t border-line pt-3 text-xs sm:grid-cols-3">
                  <div><dt className="text-quiet">Duration</dt><dd className="mt-1 font-semibold text-ink">{failureDuration(failure, failures)}</dd></div>
                  <div><dt className="text-quiet">Affected channels</dt><dd className="mt-1 font-semibold text-ink">{affected}</dd></div>
                  <div><dt className="text-quiet">Review state</dt><dd className="mt-1 font-semibold capitalize text-ink">{String(failure.reviewState || "unreviewed").replaceAll("_", " ")}</dd></div>
                </dl>
                <details className="mt-4 border-t border-line pt-3 text-xs">
                  <summary className="cursor-pointer font-semibold text-teal-700">Show technical code details</summary>
                  <div className="mt-3 grid gap-2 font-mono text-[11px] text-quiet sm:grid-cols-2">
                    <p>id: {failure.failureId || "—"}</p>
                    <p>type: {failure.type || "—"}</p>
                    <p>severity: {failure.technicalSeverity || "—"}</p>
                    <p>detector: {failure.detector || "—"} {failure.detectorVersion || ""}</p>
                    <pre className="overflow-auto whitespace-pre-wrap sm:col-span-2">observed: {JSON.stringify(failure.observed || {}, null, 2)}</pre>
                    <pre className="overflow-auto whitespace-pre-wrap sm:col-span-2">expected: {JSON.stringify(failure.expected || {}, null, 2)}</pre>
                  </div>
                </details>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

function ExportLinks({ sessionId }) {
  const links = [
    ["Report", "report.md", "Human-readable session summary"],
    ["ZIP bundle", "export.zip", "Complete technical archive"],
    ["Samples CSV", "samples.csv", "Normalized sample rows"],
    ["Failures CSV", "failures.csv", "Failure and review records"],
  ];
  return (
    <section className="panel p-5" aria-labelledby="exports-heading">
      <p className="mono-label">Session complete</p>
      <h2 id="exports-heading" className="section-title mt-1">Export the recorded session</h2>
      <p className="mt-2 text-sm leading-6 text-quiet">These links read the backend’s stored session records. Exported data remains a technical research record.</p>
      <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {links.map(([label, file, description]) => (
          <a key={file} className="rounded-xl border border-line bg-slate-50/60 p-3 transition hover:border-teal-500 hover:bg-teal-50" href={exportUrl(sessionId, file)} download>
            <span className="block text-sm font-semibold text-teal-700">{label} <span aria-hidden="true">↗</span></span>
            <span className="mt-1 block text-xs leading-5 text-quiet">{description}</span>
          </a>
        ))}
      </div>
    </section>
  );
}

export default function App() {
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [scenarios, setScenarios] = useState(SCENARIO_FALLBACKS);
  const [liveState, setLiveState] = useState(initialLiveState);
  const [session, setSession] = useState(null);
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const socketRef = useRef(null);
  const intentionalClose = useRef(false);
  const loadedArtifactsFor = useRef("");

  useEffect(() => {
    let active = true;
    listScenarios()
      .then((payload) => {
        if (!active || !Array.isArray(payload?.scenarios) || payload.scenarios.length === 0) return;
        setScenarios(payload.scenarios);
      })
      .catch(() => {
        // The fallback catalog keeps configuration usable when the API is offline.
      });
    return () => { active = false; };
  }, []);

  useEffect(() => () => {
    intentionalClose.current = true;
    socketRef.current?.close();
  }, []);

  useEffect(() => {
    const sessionId = session?.sessionId;
    if (!sessionId) return undefined;
    let active = true;
    const refresh = async () => {
      try {
        const snapshot = await getLiveSession(sessionId);
        if (!active) return;
        setSession((current) => ({ ...current, ...snapshot }));
        setLiveState((current) => mergeSnapshot(current, snapshot));
        if (snapshot.state === "stopped" && loadedArtifactsFor.current !== sessionId) {
          loadedArtifactsFor.current = sessionId;
          const [nextReport, nextFailures] = await Promise.all([getLiveReport(sessionId), getLiveFailures(sessionId)]);
          if (active) {
            setReport(nextReport);
            setLiveState((current) => ({ ...current, failures: nextFailures?.failures || current.failures }));
          }
        }
      } catch {
        // The WebSocket remains the live source; a poll failure is surfaced only if the stream is also interrupted.
      }
    };
    const interval = window.setInterval(refresh, 1200);
    return () => { active = false; window.clearInterval(interval); };
  }, [session?.sessionId]);

  const selectedScenario = useMemo(
    () => scenarios.find((scenario) => scenario.id === config.scenario) || scenarios[0],
    [config.scenario, scenarios],
  );

  function updateConfig(key, value) {
    setConfig((current) => ({ ...current, [key]: value }));
  }

  function closeSocket() {
    intentionalClose.current = true;
    socketRef.current?.close();
    socketRef.current = null;
  }

  async function loadArtifacts(sessionId) {
    try {
      const [nextReport, nextFailures] = await Promise.all([getLiveReport(sessionId), getLiveFailures(sessionId)]);
      setReport(nextReport);
      setLiveState((current) => ({ ...current, failures: nextFailures?.failures || current.failures }));
    } catch (loadError) {
      setError(loadError.message || "The finished session could not be loaded.");
    }
  }

  async function startSession() {
    setError("");
    setReport(null);
    loadedArtifactsFor.current = "";
    closeSocket();
    setBusy("creating");
    setLiveState(initialLiveState);
    try {
      const created = await createLiveSession({
        scenario: config.scenario,
        durationSec: Number(config.durationSec),
        sampleRateHz: Number(config.sampleRateHz),
        speed: Number(config.speed),
        seed: Number(config.seed),
        faults: buildFaults(config),
        noWait: false,
      });
      const sessionId = created.sessionId;
      setSession(created);
      setLiveState((current) => mergeSnapshot(current, created));
      setBusy("connecting");
      intentionalClose.current = false;

      let resolveOpen;
      let rejectOpen;
      let opened = false;
      const socketOpened = new Promise((resolve, reject) => { resolveOpen = resolve; rejectOpen = reject; });
      const socket = createLiveSocket(sessionId, {
        onOpen: () => { opened = true; setLiveState((current) => ({ ...current, connection: "connected" })); resolveOpen(); },
        onEvent: (event) => {
          setLiveState((current) => reduceLiveEvent(current, event));
          if (event.type === "status" && event.payload?.state === "stopped") {
            setBusy("");
            loadArtifacts(sessionId);
          }
        },
        onError: (message) => {
          setLiveState((current) => ({ ...current, connection: "interrupted" }));
          if (!opened) rejectOpen(new Error(message));
        },
        onClose: () => {
          if (!intentionalClose.current) setLiveState((current) => ({ ...current, connection: "interrupted" }));
        },
      });
      socketRef.current = socket;
      await Promise.race([
        socketOpened,
        new Promise((_, reject) => window.setTimeout(() => reject(new Error("The live stream did not open in time.")), 8000)),
      ]);
      setBusy("starting");
      const started = await startLiveSession(sessionId);
      setSession((current) => ({ ...current, ...started }));
      setLiveState((current) => mergeSnapshot(current, started));
      setBusy("");
    } catch (startError) {
      closeSocket();
      setBusy("");
      setError(startError.message || "The session could not be started.");
      setLiveState((current) => ({ ...current, connection: "interrupted" }));
    }
  }

  async function stopSession() {
    if (!session?.sessionId) return;
    setError("");
    setBusy("stopping");
    try {
      const stopped = await stopLiveSession(session.sessionId);
      setSession((current) => ({ ...current, ...stopped }));
      setLiveState((current) => mergeSnapshot(current, stopped));
      await loadArtifacts(session.sessionId);
      setBusy("");
      closeSocket();
    } catch (stopError) {
      setBusy("");
      setError(stopError.message || "The session could not be stopped.");
    }
  }

  function resetSession() {
    closeSocket();
    setSession(null);
    setReport(null);
    setLiveState(initialLiveState);
    setError("");
    setBusy("");
    loadedArtifactsFor.current = "";
  }

  const isRunning = ["streaming", "degraded", "reconnecting"].includes(liveState.sessionState);
  const isStopped = liveState.sessionState === "stopped";
  const canStart = !busy && !isRunning && !session;
  const showExports = Boolean(session?.sessionId && isStopped);
  const qualityEvent = liveState.latestSample ? liveState.qualityBySample[liveState.latestSample.sampleId] : null;

  return (
    <div className="min-h-screen bg-[#f5f9f7] text-ink">
      <header className="border-b border-line bg-white/80">
        <div className="mx-auto flex max-w-[1320px] items-center justify-between gap-4 px-5 py-4 lg:px-8">
          <div className="flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-teal-600 font-semibold text-white shadow-sm" aria-hidden="true">A</span>
            <div>
              <p className="text-sm font-bold tracking-[-0.03em] text-ink">AURA-Med</p>
              <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-quiet">Live reliability lab</p>
            </div>
          </div>
          <div className="hidden items-center gap-3 text-xs text-quiet sm:flex">
            <span className="flex items-center gap-2"><StatusDot tone={liveState.connection === "interrupted" ? "coral" : "teal"} /> {liveState.connection === "connected" ? "Live link" : "Local research mode"}</span>
            {session?.sessionId && <span className="tag">{session.sessionId}</span>}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1320px] px-5 pb-12 lg:px-8">
        <section className="grid gap-6 py-9 lg:grid-cols-[1fr_330px] lg:items-end lg:py-12">
          <div>
            <p className="eyebrow">Phase 2 · Virtual live session</p>
            <h1 className="mt-3 max-w-3xl text-4xl font-semibold leading-[1.05] tracking-[-0.06em] text-ink sm:text-5xl">See what the stream knows, and where it needs review.</h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-quiet">A compact view of simulated SpO₂, heart rate, and respiration signals. Technical stream telemetry is translated into clear language for research teams.</p>
          </div>
          <aside className="rounded-2xl border border-teal-100 bg-teal-50 p-4 text-sm leading-6 text-teal-700">
            <p className="font-semibold">Research simulation only</p>
            <p className="mt-1 text-xs leading-5">This dashboard is not a diagnostic tool, clinical monitor, or source of medical advice.</p>
          </aside>
        </section>

        <section className="panel p-5 sm:p-6" aria-labelledby="config-heading">
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div>
              <p className="mono-label">Session setup</p>
              <h2 id="config-heading" className="section-title mt-1">Create a virtual live session</h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-quiet">Choose a deterministic scenario, then watch events arrive through the live API connection.</p>
            </div>
            <div className="flex gap-2">
              <button className="primary-button" type="button" onClick={startSession} disabled={!canStart}>
                {busy === "creating" ? "Creating…" : busy === "connecting" ? "Connecting…" : busy === "starting" ? "Starting…" : "Start session"}
              </button>
              <button className="secondary-button" type="button" onClick={stopSession} disabled={!session?.sessionId || !isRunning || Boolean(busy)}>{busy === "stopping" ? "Ending…" : "End session"}</button>
            </div>
          </div>

          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            <label>
              <span className="field-label">Scenario</span>
              <select className="field-control" value={config.scenario} onChange={(event) => updateConfig("scenario", event.target.value)} disabled={Boolean(busy) || Boolean(session)}>
                {scenarios.map((scenario) => <option key={scenario.id} value={scenario.id}>{scenario.label || scenario.id}</option>)}
              </select>
              <span className="mt-2 block min-h-8 text-xs leading-4 text-quiet">{selectedScenario?.description || "Scenario description supplied by the API."}</span>
            </label>
            <label>
              <span className="field-label">Duration (seconds)</span>
              <input className="field-control" type="number" min="5" max="600" step="1" value={config.durationSec} onChange={(event) => updateConfig("durationSec", event.target.value)} disabled={Boolean(busy) || Boolean(session)} />
              <span className="mt-2 block min-h-8 text-xs leading-4 text-quiet">How long the virtual source is scheduled to run.</span>
            </label>
            <label>
              <span className="field-label">Sample rate</span>
              <select className="field-control" value={config.sampleRateHz} onChange={(event) => updateConfig("sampleRateHz", event.target.value)} disabled={Boolean(busy) || Boolean(session)}>
                {[0.5, 1, 2, 4].map((rate) => <option key={rate} value={rate}>{rate} Hz</option>)}
              </select>
              <span className="mt-2 block min-h-8 text-xs leading-4 text-quiet">Scheduled samples per second.</span>
            </label>
            <label>
              <span className="field-label">Seed</span>
              <input className="field-control" type="number" step="1" value={config.seed} onChange={(event) => updateConfig("seed", event.target.value)} disabled={Boolean(busy) || Boolean(session)} />
              <span className="mt-2 block min-h-8 text-xs leading-4 text-quiet">Keeps the virtual run repeatable.</span>
            </label>
            <label>
              <span className="field-label">Playback speed</span>
              <select className="field-control" value={config.speed} onChange={(event) => updateConfig("speed", event.target.value)} disabled={Boolean(busy) || Boolean(session)}>
                {[0.5, 1, 2, 4].map((speed) => <option key={speed} value={speed}>{speed}×</option>)}
              </select>
              <span className="mt-2 block min-h-8 text-xs leading-4 text-quiet">Controls live delivery pacing.</span>
            </label>
            <label>
              <span className="field-label">Fault profile</span>
              <select className="field-control" value={config.faultProfile} onChange={(event) => updateConfig("faultProfile", event.target.value)} disabled={Boolean(busy) || Boolean(session)}>
                {FAULT_PROFILES.map((profile) => <option key={profile.id} value={profile.id}>{profile.label}</option>)}
              </select>
              <span className="mt-2 block min-h-8 text-xs leading-4 text-quiet">{FAULT_PROFILES.find((profile) => profile.id === config.faultProfile)?.help}</span>
            </label>
          </div>
          {error && <p className="mt-4 rounded-lg border border-coral-100 bg-coral-50 px-3 py-2 text-sm text-coral-600" role="alert">{error}</p>}
        </section>

        <div className="mt-5"><StatusSummary liveState={liveState} /></div>

        <section className="mt-5 grid gap-4 lg:grid-cols-3" aria-label="Live signal cards">
          {CHANNEL_IDS.map((channel) => <SignalCard key={channel} channel={channel} sample={liveState.latestSample} qualityEvent={qualityEvent} />)}
        </section>

        <section className="mt-5 grid gap-5 lg:grid-cols-[1.45fr_0.85fr]">
          <div className="panel p-5"><Chart samples={liveState.samples} durationSec={Number(config.durationSec) || 1} /></div>
          <WhatIsHappening liveState={liveState} report={report} />
        </section>

        <div className="mt-5"><TechnicalDetails liveState={liveState} report={report} /></div>
        <div className="mt-5"><FailureTimeline failures={liveState.failures} /></div>
        {showExports && <div className="mt-5"><ExportLinks sessionId={session.sessionId} /></div>}

        <footer className="mt-8 flex flex-col gap-2 border-t border-line pt-5 text-xs text-quiet sm:flex-row sm:items-center sm:justify-between">
          <span>All values shown are simulated research data.</span>
          <div className="flex flex-wrap gap-3">
            {session && <span className="font-mono">{session.scenario} · {session.durationSec}s · seed {session.seed}</span>}
            {session && isStopped && <button className="font-semibold text-teal-700 underline underline-offset-2" type="button" onClick={resetSession}>Create another session</button>}
          </div>
        </footer>
      </main>
    </div>
  );
}
