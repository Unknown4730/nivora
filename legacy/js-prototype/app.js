/*
 * Nivora Lab browser adapter.
 *
 * The visual layer consumes the shared SimulationRun returned by the
 * dependency-free domain pipeline. It does not recalculate quality, trust,
 * algorithm classifications, or benchmark metrics. Everything shown here is
 * simulated research data, not clinical logic.
 */

"use strict";

import { createSimulationRun } from "./src/domain/pipeline.js";

const CHANNELS = {
  spo2: { label: "SpO₂", unit: "%", color: "#137f77", domain: [70, 100], decimals: 1, scale: 5 },
  "heart-rate": { label: "Heart rate", unit: "bpm", color: "#d88242", domain: [35, 140], decimals: 0, scale: 24 },
  respiration: { label: "Respiration", unit: "breaths/min", color: "#6f63c6", domain: [5, 45], decimals: 1, scale: 8 },
};
const CHANNEL_IDS = Object.keys(CHANNELS);
const ALGORITHM_LABELS = {
  "threshold-baseline": "THRESHOLD BASELINE",
  "reliability-aware": "NIVORA",
};
const SCENARIO_HELP = {
  clean: "Mostly stable simulated signals with small deterministic variation.",
  "motion-artifact": "Motion-like noise and clipping affect all simulated channels.",
  dropout: "Multiple channels become unavailable for a bounded interval.",
};

const $ = (id) => document.getElementById(id);
const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));
const round = (value, digits = 2) => Number(value.toFixed(digits));
const percent = (value) => `${Math.round(clamp(value) * 100)}%`;

function hashString(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function mean(values) {
  const usable = values.filter((value) => value !== null && Number.isFinite(value));
  return usable.length ? usable.reduce((sum, value) => sum + value, 0) / usable.length : null;
}
function getDomState() {
  return {
    canvas: $("chart"),
    chartEmpty: $("chart-empty"),
    scenario: $("scenario"),
    duration: $("duration"),
    intensity: $("intensity"),
    intensityValue: $("intensity-value"),
    algorithm: $("algorithm"),
    speed: $("playback-speed"),
    runButton: $("run-button"),
    resetButton: $("reset-button"),
    traceState: $("trace-state"),
    runId: $("run-id"),
    transportDot: $("transport-dot"),
    transportLabel: $("transport-label"),
    statusMessage: $("status-message"),
  };
}

const dom = getDomState();
const state = { run: null, running: false, playhead: 0, timer: null, speed: 1 };

function selectedAlgorithm() {
  return dom.algorithm.value === "threshold-baseline" ? "threshold-baseline" : "reliability-aware";
}

function selectedResult() {
  if (!state.run) return null;
  return state.run.results.find((result) => result.algorithmId === selectedAlgorithm()) || state.run.results[0];
}

function setStatus(message, error = false) {
  dom.statusMessage.textContent = message;
  dom.statusMessage.classList.toggle("error", error);
}

function updateConfigCopy() {
  dom.intensityValue.textContent = `${dom.intensity.value}%`;
  $("scenario-help").textContent = SCENARIO_HELP[dom.scenario.value];
  $("config-scenario").textContent = `SCENARIO · ${dom.scenario.value.replaceAll("-", " ").toUpperCase()}`;
  $("config-duration").textContent = `${dom.duration.value} S`;
  const seed = hashString(`${dom.scenario.value}:${dom.duration.value}:${dom.intensity.value}`).toString(16).slice(-6).toUpperCase();
  $("config-seed").textContent = `SEED · ${seed}`;
  if (!state.run) {
    $("chart-window-label").textContent = `0s / ${dom.duration.value}s`;
    $("axis-quarter").textContent = `${Math.round(Number(dom.duration.value) * .25)}s`;
    $("axis-half").textContent = `${Math.round(Number(dom.duration.value) * .5)}s`;
    $("axis-three-quarter").textContent = `${Math.round(Number(dom.duration.value) * .75)}s`;
    $("axis-end").textContent = `${dom.duration.value}s`;
    $("timeline-range").textContent = `0s → ${dom.duration.value}s`;
  }
}

function formatChannelValue(channel, value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toFixed(CHANNELS[channel].decimals);
}

function findEvidence(run, time) {
  return run.evidence.find((window) => time >= window.startSec && time < window.endSec) || run.evidence.at(-1);
}

function findPrediction(result, time) {
  return result?.predictions.find((prediction) => time >= prediction.startSec && time < prediction.endSec) || result?.predictions.at(-1);
}

function trustScore(value) {
  return value && typeof value === "object" ? value.score : value;
}

function baselineValue(value) {
  return value && typeof value === "object" ? value.value : value;
}

function trendValue(value) {
  return value && typeof value === "object" ? value.trendPerSample : value;
}

function classificationKind(classification) {
  if (!classification) return "normal";
  if (classification.includes("EVENT") || classification.includes("ANOMALY")) return "alert";
  if (classification.includes("LOW_CONFIDENCE") || classification.includes("INSUFFICIENT")) return "uncertain";
  return "normal";
}

function classificationLabel(classification) {
  const kind = classificationKind(classification);
  if (kind === "alert") return "Simulated alert";
  if (kind === "uncertain") return "Uncertain evidence";
  if (classification === "NOMINAL") return "Nominal simulation";
  return classification ? classification.toLowerCase().replaceAll("_", " ") : "Awaiting run";
}

function renderSignalCard(channel, sample, evidence) {
  const value = sample.values[channel];
  const quality = evidence?.quality.find((item) => item.channel === channel);
  const trust = trustScore(evidence?.trustByChannel[channel]);
  const analysis = evidence?.baselineByChannel[channel];
  const baseline = baselineValue(analysis);
  const trend = trendValue(analysis);
  $(`${channel}-value`).textContent = formatChannelValue(channel, value);
  $(`${channel}-baseline`).textContent = formatChannelValue(channel, baseline);
  $(`${channel}-time`).textContent = `${Math.round(state.playhead)}s`;
  $(`${channel}-quality`).textContent = quality ? percent(quality.score) : "—";
  $(`${channel}-trust`).textContent = trust === undefined ? "—" : percent(trust);
  $(`${channel}-quality-bar`).style.width = quality ? percent(quality.score) : "0%";
  $(`${channel}-trust-bar`).style.width = trust === undefined ? "0%" : percent(trust);
  const trendLabel = trend === null || trend === undefined ? "↔ unavailable" : Math.abs(trend) < CHANNELS[channel].scale * .01 ? "↔ stable" : trend > 0 ? "↗ rising" : "↘ falling";
  const trendElement = $(`${channel}-trend`);
  trendElement.textContent = trendLabel;
  trendElement.className = `signal-trend ${trend === null || trend === undefined || Math.abs(trend) < CHANNELS[channel].scale * .01 ? "flat" : trend < 0 ? "down" : ""}`;
  $(`${channel}-missing`).hidden = value !== null && value !== undefined;
}

function renderMetrics(evidence, result) {
  const quality = evidence ? mean(evidence.quality.map((item) => item.score)) || 0 : 0;
  const trust = evidence ? mean(CHANNEL_IDS.map((channel) => trustScore(evidence.trustByChannel[channel]))) || 0 : 0;
  const agreement = evidence?.crossSignalAgreement || 0;
  $("quality").textContent = evidence ? percent(quality) : "—";
  $("trust").textContent = evidence ? percent(trust) : "—";
  $("agreement").textContent = evidence ? percent(agreement) : "—";
  $("uncertain").textContent = result ? result.metrics.uncertainWindowCount : "—";
  $("quality-sub").textContent = !evidence ? "Waiting for run" : quality > .8 ? "Stable local morphology" : "Artifact-affected window";
  $("trust-sub").textContent = !evidence ? "Quality-weighted evidence" : trust > .75 ? "Higher evidence weight" : "Reduced during artifacts";
  $("agreement-sub").textContent = !evidence ? "Shared movement across channels" : agreement > .75 ? "Channels move together" : "Partial corroboration";
  $("uncertain-sub").textContent = result ? `${round(result.metrics.uncertainDurationSec, 1)}s held out from hard calls` : "Held out from hard calls";
}

function renderInterpretation(run, evidence, result) {
  const block = $("classification-block");
  const prediction = findPrediction(result, state.playhead);
  const classification = prediction?.classification || "normal";
  const kind = classificationKind(classification);
  block.className = `classification-block ${kind === "alert" ? "alert" : kind === "uncertain" ? "uncertain" : state.run ? "" : "empty"}`;
  $("active-algorithm").textContent = ALGORITHM_LABELS[result?.algorithmId] || "NIVORA";
  $("classification-state").textContent = state.run ? classificationLabel(classification) : "Awaiting run";
  $("classification-confidence").textContent = prediction ? `${percent(prediction.confidence)} algorithmic confidence` : "—";
  $("classification-summary").textContent = !state.run
    ? "The evidence trail will appear when a local simulation is started."
    : kind === "alert"
      ? "A simulated event-aligned window crossed this algorithm's evidence rule. Review the annotations and comparison arms."
      : kind === "uncertain"
        ? "The selected algorithm is withholding a hard call because the current evidence window is limited or conflicting."
        : "The selected algorithm found no event-aligned alert in this evidence window.";

  const evidenceList = $("evidence-list");
  evidenceList.innerHTML = "";
  if (!run || !evidence) {
    evidenceList.className = "evidence-list empty-list";
    const empty = document.createElement("p");
    empty.textContent = "No evidence yet.";
    evidenceList.appendChild(empty);
  } else {
    evidenceList.className = "evidence-list";
    const items = [
      ...(prediction?.explanation ? [prediction.explanation] : []),
      ...run.explanations,
    ].filter((item, index, all) => item?.title && all.findIndex((candidate) => candidate.title === item.title) === index).slice(0, 3);
    items.forEach((item, index) => {
      const row = document.createElement("div");
      row.className = "evidence-item";
      const bar = document.createElement("div");
      bar.className = `evidence-bar ${index === 1 ? "orange" : index === 2 ? "purple" : ""}`;
      const body = document.createElement("div");
      const title = document.createElement("h3");
      title.textContent = item.title;
      const detail = document.createElement("p");
      detail.textContent = item.detail;
      body.append(title, detail);
      row.append(bar, body);
      evidenceList.appendChild(row);
    });
  }

  const uncertainty = $("uncertainty-text");
  $("uncertainty-box").classList.toggle("active", classification === "uncertain");
  const quality = evidence ? mean(evidence.quality.map((item) => item.score)) || 0 : 0;
  uncertainty.textContent = !state.run
    ? "Uncertainty is shown explicitly when signal quality or cross-signal agreement is limited."
    : kind === "uncertain"
      ? "This window is intentionally labeled uncertain. Inspect missing samples, artifact overlap, and cross-signal agreement before comparing it with a hard classification."
      : `Current window quality is ${percent(quality)} with ${percent(evidence.crossSignalAgreement)} cross-signal agreement.`;

  const reasons = $("reason-codes");
  reasons.innerHTML = "";
  (prediction?.reasonCodes || ["—"]).forEach((reason) => {
    const code = document.createElement("span");
    code.textContent = reason;
    reasons.appendChild(code);
  });
}

function renderComparison(run) {
  const ready = Boolean(run);
  $("benchmark-badge").textContent = ready ? "Run complete · simulated" : "Awaiting data";
  ["threshold-baseline", "reliability-aware"].forEach((algorithmId) => {
    const result = run?.results.find((item) => item.algorithmId === algorithmId);
    const prefix = algorithmId === "threshold-baseline" ? "base" : "aware";
    const metrics = result?.metrics;
    $(`${prefix}-alerts`).textContent = metrics ? metrics.nuisanceAlerts : "—";
    $(`${prefix}-missed`).textContent = metrics ? metrics.missedSimulatedEvents : "—";
    $(`${prefix}-latency`).textContent = metrics ? metrics.detectionLatencySec.map((value) => value === null ? "—" : `${value.toFixed(1)}s`).join(", ") : "—";
    $(`${prefix}-uncertain`).textContent = metrics ? `${metrics.uncertainDurationSec.toFixed(1)}s` : "—";
  });
  $("baseline-row").classList.toggle("active-row", selectedAlgorithm() === "threshold-baseline");
  $("aware-row").classList.toggle("active-row", selectedAlgorithm() === "reliability-aware");
}

function makeTimelineEvent(entry) {
  const item = document.createElement("article");
  item.className = `timeline-event ${entry.kind}`;
  const time = document.createElement("div");
  time.className = "timeline-time";
  time.textContent = `${entry.startSec}s${entry.endSec !== undefined ? `–${entry.endSec}s` : ""}`;
  const title = document.createElement("h3");
  title.textContent = entry.title;
  const detail = document.createElement("p");
  detail.textContent = entry.detail;
  const tag = document.createElement("span");
  tag.className = "timeline-tag";
  tag.textContent = entry.tag;
  item.append(time, title, detail, tag);
  return item;
}

function renderTimeline(run, result) {
  const timeline = $("timeline");
  timeline.innerHTML = "";
  if (!run) {
    const empty = document.createElement("div");
    empty.className = "timeline-empty";
    const icon = document.createElement("span");
    icon.textContent = "↔";
    const copy = document.createElement("p");
    copy.textContent = "Run a scenario to see relative-time annotations and classification transitions.";
    empty.append(icon, copy);
    timeline.appendChild(empty);
    return;
  }
  const entries = run.annotations.map((annotation) => ({
    kind: annotation.kind === "simulated-event" ? "event" : "artifact",
    startSec: annotation.startSec,
    endSec: annotation.endSec,
    title: annotation.label,
    detail: annotation.kind === "simulated-event" ? "A simulated ground-truth annotation used for benchmark matching." : "A bounded interval changes channel quality or availability.",
    tag: annotation.kind === "simulated-event" ? "SIMULATED EVENT" : "SENSOR ARTIFACT",
  }));
  let previous = null;
  (result?.predictions || []).forEach((prediction) => {
    if (prediction.classification !== previous) {
      entries.push({
        kind: "transition",
        startSec: prediction.startSec,
        title: `Classification → ${prediction.classification}`,
        detail: `${ALGORITHM_LABELS[result.algorithmId]} output changed at this relative-time window.`,
        tag: "ALGORITHM CHANGE",
      });
      previous = prediction.classification;
    }
  });
  entries.sort((a, b) => a.startSec - b.startSec);
  entries.slice(0, 8).forEach((entry) => timeline.appendChild(makeTimelineEvent(entry)));
  $("timeline-range").textContent = `0s → ${run.config.durationSec}s`;
}

function drawChart(run) {
  const canvas = dom.canvas;
  const context = canvas.getContext("2d");
  if (!context) return;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, rect.width || 900);
  const height = Math.max(240, rect.height || 350);
  const pixelRatio = window.devicePixelRatio || 1;
  canvas.width = Math.floor(width * pixelRatio);
  canvas.height = Math.floor(height * pixelRatio);
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#fbfdfc";
  context.fillRect(0, 0, width, height);
  if (!run) {
    dom.chartEmpty.hidden = false;
    return;
  }
  dom.chartEmpty.hidden = true;
  const left = 51;
  const right = width - 12;
  const top = 10;
  const laneGap = 20;
  const laneHeight = (height - top - 36 - laneGap * 2) / 3;
  const xFor = (time) => left + (time / run.config.durationSec) * (right - left);
  const yFor = (channel, value, lane) => {
    if (value === null || value === undefined) return null;
    const [min, max] = CHANNELS[channel].domain;
    return top + lane * (laneHeight + laneGap) + laneHeight - ((value - min) / (max - min)) * laneHeight;
  };

  run.annotations.forEach((annotation) => {
    context.fillStyle = annotation.kind === "simulated-event" ? "rgba(179,85,98,.09)" : "rgba(216,130,66,.10)";
    context.fillRect(xFor(annotation.startSec), top, Math.max(2, xFor(annotation.endSec) - xFor(annotation.startSec)), height - 35);
  });

  CHANNEL_IDS.forEach((channel, lane) => {
    const laneTop = top + lane * (laneHeight + laneGap);
    context.strokeStyle = "#e1e9e5";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(left, laneTop + laneHeight);
    context.lineTo(right, laneTop + laneHeight);
    context.stroke();
    context.strokeStyle = "#edf2ef";
    context.setLineDash([2, 4]);
    for (let split = 1; split < 3; split += 1) {
      const y = laneTop + (laneHeight * split) / 3;
      context.beginPath();
      context.moveTo(left, y);
      context.lineTo(right, y);
      context.stroke();
    }
    context.setLineDash([]);
    context.fillStyle = CHANNELS[channel].color;
    context.font = "10px DM Mono, monospace";
    context.fillText(`${CHANNELS[channel].label} · ${CHANNELS[channel].unit}`, 4, laneTop + 10);
    context.fillStyle = "#9aa9a4";
    context.fillText(`${CHANNELS[channel].domain[1]}`, right - 31, laneTop + 10);
    context.fillText(`${CHANNELS[channel].domain[0]}`, right - 31, laneTop + laneHeight - 2);

    context.strokeStyle = CHANNELS[channel].color;
    context.lineWidth = 2;
    context.lineJoin = "round";
    context.beginPath();
    let connected = false;
    run.samples.forEach((sample) => {
      const y = yFor(channel, sample.values[channel], lane);
      if (y === null) {
        connected = false;
        return;
      }
      const x = xFor(sample.tSec);
      if (!connected) context.moveTo(x, y);
      else context.lineTo(x, y);
      connected = true;
    });
    context.stroke();

    const evidenceWindow = findEvidence(run, state.playhead);
    const baseline = baselineValue(evidenceWindow?.baselineByChannel[channel]);
    if (baseline !== undefined && baseline !== null) {
      const y = yFor(channel, baseline, lane);
      context.strokeStyle = `${CHANNELS[channel].color}66`;
      context.setLineDash([5, 4]);
      context.beginPath();
      context.moveTo(left, y);
      context.lineTo(right, y);
      context.stroke();
      context.setLineDash([]);
    }
  });

  const playheadX = xFor(state.playhead);
  context.strokeStyle = "#172522";
  context.lineWidth = 1;
  context.beginPath();
  context.moveTo(playheadX, top);
  context.lineTo(playheadX, height - 35);
  context.stroke();
  context.fillStyle = "#172522";
  context.beginPath();
  context.arc(playheadX, top, 3.5, 0, Math.PI * 2);
  context.fill();

  const evidence = findEvidence(run, state.playhead);
  const qualityBarY = height - 23;
  context.fillStyle = "#e8efec";
  context.fillRect(left, qualityBarY, right - left, 5);
  context.fillStyle = "#b9d9d3";
  const qualityAverage = evidence ? mean(evidence.quality.map((item) => item.score)) || 0 : 0;
  const trustAverage = evidence ? mean(CHANNEL_IDS.map((channel) => trustScore(evidence.trustByChannel[channel]) || 0)) || 0 : 0;
  context.fillRect(left, qualityBarY, (right - left) * qualityAverage, 5);
  context.fillStyle = "#9f94dc";
  context.fillRect(left, qualityBarY + 8, (right - left) * trustAverage, 5);
  context.fillStyle = "#93a29d";
  context.font = "9px DM Mono, monospace";
  context.fillText("QUALITY", 4, qualityBarY + 5);
  context.fillText("TRUST", 4, qualityBarY + 13);
}

function render() {
  updateConfigCopy();
  const run = state.run;
  const sampleIndex = run ? Math.min(run.samples.length - 1, Math.round(state.playhead * run.config.sampleRateHz)) : 0;
  const sample = run?.samples[sampleIndex];
  const evidence = run ? findEvidence(run, state.playhead) : null;
  const result = selectedResult();
  if (sample && evidence) CHANNEL_IDS.forEach((channel) => renderSignalCard(channel, sample, evidence));
  renderMetrics(evidence, result);
  renderInterpretation(run, evidence, result);
  renderComparison(run);
  renderTimeline(run, result);
  $("chart-window-label").textContent = run ? `${Math.round(state.playhead)}s / ${run.config.durationSec}s` : `0s / ${dom.duration.value}s`;
  $("axis-quarter").textContent = `${Math.round((run?.config.durationSec || Number(dom.duration.value)) * .25)}s`;
  $("axis-half").textContent = `${Math.round((run?.config.durationSec || Number(dom.duration.value)) * .5)}s`;
  $("axis-three-quarter").textContent = `${Math.round((run?.config.durationSec || Number(dom.duration.value)) * .75)}s`;
  $("axis-end").textContent = `${run?.config.durationSec || dom.duration.value}s`;
  drawChart(run);
}

function stopTimer() {
  if (state.timer) window.clearInterval(state.timer);
  state.timer = null;
}

function pausePlayback() {
  state.running = false;
  stopTimer();
  dom.runButton.textContent = state.run && state.playhead >= state.run.config.durationSec ? "↻ Run again" : "▶ Resume simulation";
  dom.traceState.textContent = state.run && state.playhead >= state.run.config.durationSec ? "COMPLETE" : "PAUSED";
  dom.transportLabel.textContent = state.run && state.playhead >= state.run.config.durationSec ? "Run complete" : `Paused at ${Math.round(state.playhead)}s`;
  dom.transportDot.style.background = "#a2afab";
  setStatus(state.run && state.playhead >= state.run.config.durationSec ? "Run complete. Review the simulated benchmark and timeline." : "Playback paused. Resume or reset to change the run.");
}

function startPlayback() {
  if (!state.run) return;
  state.running = true;
  stopTimer();
  dom.runButton.textContent = "Ⅱ Pause simulation";
  dom.traceState.textContent = "RUNNING";
  dom.transportLabel.textContent = `Playing at ${state.speed}×`;
  dom.transportDot.style.background = "#42a982";
  setStatus("Playback is local and deterministic for this configuration.");
  state.timer = window.setInterval(() => {
    state.playhead = Math.min(state.run.config.durationSec, state.playhead + .25 * state.speed);
    render();
    if (state.playhead >= state.run.config.durationSec) pausePlayback();
  }, 250);
}

function buildRun() {
  const config = {
    scenario: dom.scenario.value,
    durationSec: Number(dom.duration.value),
    sampleRateHz: 1,
    artifactIntensity: Number(dom.intensity.value) / 100,
    algorithms: ["threshold-baseline", "reliability-aware"],
    seed: hashString(`${dom.scenario.value}:${dom.duration.value}:${dom.intensity.value}`),
  };
  state.run = createSimulationRun(config);
  state.playhead = 0;
  dom.runId.textContent = state.run.runId;
  dom.resetButton.disabled = false;
  render();
}

function handleRunButton() {
  try {
    if (state.running) {
      pausePlayback();
      return;
    }
    if (!state.run || state.playhead >= state.run.config.durationSec) buildRun();
    startPlayback();
  } catch (error) {
    state.running = false;
    stopTimer();
    dom.traceState.textContent = "ERROR";
    dom.transportLabel.textContent = "Unable to render run";
    setStatus(`Local run error: ${error.message}`, true);
  }
}

function reset() {
  state.running = false;
  stopTimer();
  state.run = null;
  state.playhead = 0;
  dom.runId.textContent = "RUN-0000";
  dom.traceState.textContent = "READY";
  dom.runButton.textContent = "▶ Start simulation";
  dom.transportLabel.textContent = "Ready for a run";
  dom.transportDot.style.background = "#a2afab";
  setStatus("Configuration is ready. Start a local simulation when you are ready.");
  render();
}

dom.runButton.addEventListener("click", handleRunButton);
dom.resetButton.addEventListener("click", reset);
dom.speed.addEventListener("change", () => {
  state.speed = Number(dom.speed.value);
  if (state.running) dom.transportLabel.textContent = `Playing at ${state.speed}×`;
});
[dom.scenario, dom.duration, dom.intensity].forEach((control) => control.addEventListener("input", updateConfigCopy));
[dom.scenario, dom.duration].forEach((control) => control.addEventListener("change", () => {
  if (state.run) setStatus("Configuration changed. Reset and start again to create a new deterministic run.");
  updateConfigCopy();
}));
dom.algorithm.addEventListener("change", () => {
  render();
  if (state.run) setStatus(`Interpretation trace switched to ${ALGORITHM_LABELS[selectedAlgorithm()].toLowerCase()}. Benchmark arms remain unchanged.`);
});
window.addEventListener("resize", () => drawChart(state.run));

updateConfigCopy();
reset();

if (typeof window !== "undefined") {
  window.AuraMedUI = { createSimulationRun, render, reset };
}
