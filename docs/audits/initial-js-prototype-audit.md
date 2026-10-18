# AURA-Med Lab implementation audit

**Audit date:** 2026-10-18
**Audited revision:** `0fb808a` (`feat: build reliability research dashboard`)
**Scope:** repository structure, runtime/build setup, domain engine, browser adapter, tests, documentation, safety wording, and the requested two-day local-first MVP architecture.

This is an implementation audit, not a clinical or scientific validation. All observations below are about simulated research-prototype software. No simulated metric should be described as a clinical result, medical performance claim, or evidence about real patients or devices.

## Executive verdict

The repository is now a credible browser-only, local-first MVP foundation. It has a deterministic, dependency-free JavaScript domain engine, six scenario definitions, simulated annotations, quality and trust calculations, rolling baselines, two comparison algorithms, benchmark matching, structured explanations, a browser renderer, a lockfile, a pinned Node major version, an offline test command, and a Dockerfile that does not require a cloud service or runtime package download.

It is **not ready to call the implementation complete**. The most important correctness issue is that algorithm output windows use a one-second duration regardless of `sampleRateHz`; runs at rates above 1 Hz therefore produce overlapping or overlong predictions and distorted uncertainty/benchmark intervals. The existing tests use `sampleRateHz: 2` only for determinism and do not catch this. The TypeScript contract is present but is not compiled or checked, and there are smaller frontend contract mismatches around the “both” algorithm option and reset behavior.

**Suitability:** suitable for a local-first two-day buildathon MVP after the P0 interval fix and focused regression tests. Do not add a backend, cloud AI provider, API-key flow, GPU dependency, device integration, or framework migration for this scope.

## Evidence and verification

Files inspected:

```text
.
├── .gitignore
├── .nvmrc
├── AUDIT.md
├── Dockerfile
├── Makefile
├── README.md
├── app.js
├── index.html
├── package.json
├── package-lock.json
├── server.mjs
├── styles.css
├── src/domain/
│   ├── algorithms.js
│   ├── baseline.js
│   ├── benchmark.js
│   ├── contracts.ts
│   ├── explanations.js
│   ├── export.js
│   ├── generator.js
│   ├── index.js
│   ├── pipeline.js
│   ├── prng.js
│   ├── quality.js
│   ├── scenarios.js
│   └── trust.js
└── test/
    ├── domain.test.js
    └── frontend.test.js
```

Observed repository history shows a progression from the visual prototype to the deterministic domain engine and then the dashboard integration. The audited working tree was clean before this report was refreshed.

Checks run during this audit:

| Command | Result | Notes |
|---|---|---|
| `npm ci --ignore-scripts` | Passed with warning | Host is Node `v24.14.0`; project pins Node 20, so the engine warning is expected on this machine. |
| `npm test` | Passed | 15 tests; includes `node --check app.js`, domain tests, and static frontend tests. |
| `npm run build` | Passed | Syntax checks `app.js` and `server.mjs`, then runs the same 15 tests. |
| `node server.mjs` + `curl http://127.0.0.1:8080/` | Passed | Served `index.html` locally. |
| `docker --version` | Available | Docker CLI is installed. |
| `docker build -t aura-med-lab-audit .` | Not run to completion | Docker daemon/Windows named pipe was unavailable in this environment. The Dockerfile remains unverified here. |
| Browser click-through | Not automated | No browser automation dependency or browser smoke command exists in the repository. |

The domain reproduction used for this audit also showed the interval problem: with `sampleRateHz: 2`, a dropout run produced predictions such as `42–45`, `44.5–45.5`, and `45–49` for half-second samples, instead of one non-overlapping interval per contiguous classification. At 1 Hz the same path produced the expected one-second windows.

## 1. Actual stack

| Concern | Repository evidence | Finding |
|---|---|---|
| Frontend framework | `index.html`, `app.js` | Vanilla HTML, DOM APIs, and Canvas 2D. No React, Vue, Svelte, or component framework. |
| Browser module system | `index.html` line 223; imports in `app.js` | Native ES modules loaded directly by the browser. |
| Build tool/bundler | No Vite/Webpack/Rollup config; `package.json` scripts | No bundling or transpilation. `npm run build` is a validation/test command, not an asset build. |
| Language | `.js` domain/UI files; `contracts.ts` | Runtime is JavaScript. TypeScript exists only as an uncompiled shared contract. |
| Styling | `styles.css` | Hand-authored CSS with responsive media queries; no CSS framework. |
| Server | `server.mjs` | Small Node 20-compatible static HTTP server; no application API or database. `Makefile` also offers Python's static server. |
| Dependencies | `package.json`, lockfile | No runtime or development npm dependencies. `package-lock.json` is present and lockfile version 3. |
| Runtime pin | `.nvmrc`, `package.json`, `Dockerfile` | Node 20 is the intended runtime (`>=20 <21`), and the image starts from `node:20-alpine`. |
| Tests | `test/domain.test.js`, `test/frontend.test.js` | Node's built-in test runner and static source assertions; no browser runner and no TypeScript checker. |
| External services | Repository-wide search | No cloud AI, API client, API key, network fetch, GPU, proprietary device, or real-data path. |

### Setup/reproducibility assessment

The project meets the important buildathon hygiene requirements: the runtime major version is declared, a lockfile is committed, there are no global-install instructions, `make test` is local and deterministic, and the runtime server has no package download step. `npm ci` is technically unnecessary because there are no declared packages, but it is harmless and confirms the lockfile/package metadata relationship.

The Dockerfile copies the source and runs `node server.mjs`; it does not run `npm install` or `npx` at container startup. A clean machine still needs access to the `node:20-alpine` base image for the first Docker build, and the daemon must be available. Docker build success should be verified in CI or on a machine with a running daemon before release.

## 2. Current behavior and reusable integration points

### End-to-end flow

1. The user selects scenario, duration, artifact intensity, and algorithm view in `index.html`.
2. `app.js` derives a stable seed from those UI values, constructs a `RunConfig`, and calls `createSimulationRun`.
3. `pipeline.js` normalizes the config, resolves a scenario, generates samples and truth annotations, computes rolling quality, trust, baselines, evidence, algorithm outputs, merged predictions, metrics, and explanations.
4. `app.js` reads the resulting `SimulationRun` to render cards, Canvas traces, timeline entries, the selected interpretation, and the simulated benchmark table.
5. Playback advances a local playhead through already-generated samples; it does not stream from a device or service.

### Reusable pieces

| File/module | Existing responsibility | Reuse/integration point |
|---|---|---|
| `index.html` | Stable control IDs, metric cards, chart, interpretation, comparison, timeline, safety copy | Preserve as the UI shell; add only contract-backed fields. |
| `styles.css` | Visual language, responsive layout, missing-data and uncertainty treatments | Keep for the MVP; no design-system rewrite needed. |
| `app.js` | Browser adapter, playback state, DOM rendering, Canvas rendering | Keep thin; it should consume the domain result and avoid domain recalculation. |
| `src/domain/pipeline.js` | Complete `createSimulationRun(config)` orchestration | Primary system/frontend integration boundary. |
| `src/domain/scenarios.js` | Channel metadata, six scenario recipes, aliases, half-open interval helpers | Authoritative scenario and annotation vocabulary. |
| `src/domain/generator.js` | Seeded channel generation, event deltas, artifact injection, dropout | Replaceable pure signal generator. |
| `src/domain/quality.js` | Bounded per-channel features and rolling quality windows | Unit-testable signal-quality layer. |
| `src/domain/trust.js` | Cross-signal agreement, bounded trust update, recovery time | Evidence weighting layer; needs semantic tightening noted below. |
| `src/domain/baseline.js` | Rolling median, deviation, trend, persistence, recovery | Baseline/trend layer. |
| `src/domain/algorithms.js` | Threshold and reliability-aware classifiers | Comparison arms consuming common evidence. |
| `src/domain/benchmark.js` | Alert matching, nuisance alerts, missed events, latency, uncertainty duration | Single benchmark policy used for both algorithms. |
| `src/domain/explanations.js` | Structured reason codes and evidence-linked detail | Source of UI explanation content. |
| `src/domain/export.js` | Deterministic JSON/CSV helpers | Useful later; not currently exposed by the UI. |
| `src/domain/contracts.ts` | Intended shared TypeScript data contract | Authority for cross-agent shape, but currently not type-checked. |
| `test/domain.test.js` | Determinism, scenarios, quality/trust, baseline, algorithms, benchmarks, exports | Extend with interval and invalid-config regression fixtures. |
| `test/frontend.test.js` | Safety markers, module wiring, CSS markers | Extend with reset/algorithm-view checks or add a small browser smoke test. |

There is no backend integration point because the current architecture does not need one. If a later system agent is called “backend,” its MVP responsibility should remain a pure domain package or worker-compatible module, not a required server/API.

## 3. Domain implementation audit

### Signal generation — implemented, with defined limits

`generator.js` creates SpO₂, heart-rate, and respiration channels with units from `SIGNAL_META`, a documented sample rate in `RunConfig`, seeded pseudo-random noise, scenario event deltas, artifact noise/clipping, and nullable dropout values. `samples` and column-oriented `signals` are both returned. The generator is deterministic for a given config and seed, and the tests verify byte-equivalent serialized runs.

The generator is a hand-authored educational signal recipe, not a physiological or sensor model. It should be described as “simulated signal generation,” not as a model of real physiology. The current UI runs at 1 Hz, which avoids the interval bug in normal use but does not make the domain contract correct for other valid rates.

### Scenario definitions and ground truth — implemented

`scenarios.js` contains six recipes:

| ID | Truth/annotation behavior | UI exposure |
|---|---|---|
| `stable-baseline` | No event or artifact | Via `clean` alias |
| `loose-spo2-sensor` | SpO₂ artifact interval | Not exposed in select |
| `motion-artifact` | All-channel artifact interval | Exposed |
| `simulated-event` | Coordinated simulated event | Not exposed in select |
| `gradual-deterioration` | Gradual simulated event and recovery shape | Not exposed in select |
| `multi-sensor-dropout` | SpO₂/heart-rate disconnection interval | Via `dropout` alias |

Annotations have stable IDs, kind, label, half-open time range, channels, and optional severity. Truth is separate from predictions. This is the correct basic structure for benchmark matching. The UI currently exposes only three of six domain recipes; that is acceptable for a deliberately small UI, but README/UI copy should not imply that all six are user-selectable.

### Signal-quality scoring — implemented, but terminology needs care

`quality.js` computes bounded `0..1` features for stability, plausibility, continuity, missingness, annotation overlap, and a cross-channel availability factor, then applies the documented weights. Quality reasons are structured. Tests verify bounds and that missing/artifact fixtures score lower than a clean fixture.

The `crossSensorConsistency` feature is currently a count of other channels that are available, not a comparison of their movement or values. Consequently, “cross-signal agreement” is partly a proxy for availability rather than actual corroboration. This is acceptable as a transparent MVP heuristic only if the UI and report call it “availability-weighted simulated agreement” or otherwise document the limitation. Do not present it as validated sensor agreement.

### Sensor trust — implemented and deterministic

`trust.js` computes a bounded agreement value and updates per-channel trust toward `0.7 * quality + 0.3 * agreement`, with faster decay and slower recovery. Direction and contributions are retained for explanations. Tests cover clamping and asymmetric decay/recovery.

The trust rule is explainable and suitable for the prototype. It should remain a comparison heuristic, not a calibrated confidence or reliability estimate. Invalid values for optional config fields are not comprehensively rejected, so boundary validation should be added before accepting external configs.

### Baseline and trend analysis — implemented

`baseline.js` uses a rolling median of prior samples, excludes the current sample, computes a simple slope, and marks persistent deviations/recovery. Warm-up is represented with `null` baseline/deviation/trend values and `historyCount`; classifiers can therefore emit uncertainty rather than silently converting missing history to zero.

The baseline window, persistence count, units, and deviation scales are configured in the domain defaults but are not surfaced in the UI. That is fine for the MVP if the report calls them fixed simulation parameters. They should not be described as medical thresholds.

### Algorithms — implemented as comparison arms

`algorithms.js` provides:

- `threshold-baseline`: value/deviation threshold behavior without trust or agreement gating;
- `reliability-aware`: quality, trust, artifact, availability, persistence, and cross-signal gating, with explicit uncertain states.

Both consume the same evidence windows and return the same output vocabulary. The threshold algorithm is not clinically meaningful; it is a transparent value-only comparison arm. The reliability-aware algorithm is not a recommendation engine. Keep neutral terms such as “comparison arm” and “algorithmic confidence.”

**Correctness issue:** `outputFor()` sets `endSec` to `input.sample.tSec + 1` instead of using `input.sampleIntervalSec`. This violates the contract for any sample rate other than 1 Hz and is the highest-priority fix.

### Benchmark metrics — implemented, with a sample-rate dependency

`benchmark.js` matches overlapping alert predictions to simulated truth events using half-open interval overlap. It returns nuisance alerts, detected/missed simulated events, per-event latency, uncertain counts/duration, trust recovery values, explanation completeness, and denominator counts. This is a reasonable minimum benchmark surface.

Because prediction windows are wrong at rates above 1 Hz, merged predictions and uncertainty duration are also wrong at those rates. The benchmark must be fixed and regression-tested before comparing results across configurations. Metrics must continue to be labeled “simulated benchmark” and never “clinical performance.”

### Explanation generation — implemented

`explanations.js` derives titles, details, reason codes, and numeric evidence from the same input used by the classifier. The browser renders these values rather than inventing a second explanation. This is a strong integration choice. Keep “confidence” explicitly algorithmic and make sure future copy does not imply calibrated probability.

## 4. Frontend audit and risks

### What the browser shell does well

- It is a static browser app with no mandatory service, key, login, database, or device permission.
- It displays strong simulated/research/not-for-clinical-use framing in the hero, safety notice, benchmark section, limitations, and footer.
- It uses `textContent` for dynamic explanation and timeline content, avoiding an obvious HTML injection path from generated labels.
- It preserves `null` channel values as em dashes and visibly marks missing channels.
- It renders annotations, rolling baselines, quality/trust bars, uncertainty, reason codes, and two benchmark rows from the domain result.
- Playback is local and deterministic after a run is built; speed changes only the playhead timer.
- `styles.css` already handles desktop, tablet, and mobile layouts. A framework migration would add risk without helping the MVP.

### Findings requiring action

#### P0 — algorithm windows are invalid for `sampleRateHz > 1`

- **Location:** `src/domain/algorithms.js:51`.
- **Trigger:** call `createSimulationRun` with `sampleRateHz: 2` or another supported rate.
- **Evidence:** `pipeline.js` passes `sampleIntervalSec`, but `outputFor` ignores it and hard-codes a one-second end time. A dropout reproduction created overlapping predictions beginning at `42`, `44.5`, `45`, `48.5`, and so on, rather than half-second windows merged by classification.
- **Consequence:** prediction timelines, merged intervals, uncertain duration, nuisance-alert overlap, and detection latency are not comparable across sample rates. The shared contract says time is in seconds, so this is a contract correctness failure.
- **Smallest correction:** set `endSec` to `input.sample.tSec + (input.sampleIntervalSec ?? 1)` and add a test that every raw output has the configured interval and that merged predictions do not exceed the run duration except for an explicitly documented terminal convention.

#### P1 — the TypeScript contract is not enforced

- **Location:** `src/domain/contracts.ts`, `package.json`.
- **Trigger:** a system or frontend agent changes the contract or JS result shape.
- **Consequence:** JavaScript can drift from the shared contract without CI feedback. There is already observable drift: `benchmark.js` returns `artifactEndSec`, but `BenchmarkMetrics` does not declare it; runtime output window timing is not represented as an explicit interval contract.
- **Smallest correction:** either add a pinned local TypeScript checker and a minimal `tsconfig.json`, or explicitly mark the file as documentation and add runtime validators/JSDoc checks. For a two-day MVP, the lowest-risk choice is a narrow typecheck only if it does not require a framework or cloud dependency.

#### P1 — “Compare both algorithms” is not a distinct interpretation mode

- **Location:** `index.html:71–72`, `app.js:71–77`.
- **Trigger:** select `both` under Algorithm view.
- **Consequence:** `selectedAlgorithm()` maps every value other than `threshold-baseline` to `reliability-aware`. The UI therefore shows only the reliability-aware interpretation trace while the option says “Compare both algorithms.” The benchmark table still shows both rows, but the selected trace is not a true both mode.
- **Smallest correction:** either remove the `both` option and say the table always compares both, or implement a comparison view that renders both current predictions/reasons. Do not silently map a third option to one algorithm.

#### P1 — reset leaves stale signal-card values

- **Location:** `app.js:435–453` and `app.js:519–530`.
- **Trigger:** complete a run, then press Reset.
- **Consequence:** `render()` clears metrics, interpretation, timeline, and chart state, but only calls `renderSignalCard` when a sample/evidence pair exists. The three channel cards can retain the previous sample, baseline, trend, bars, and missing indicator while the rest of the UI says “Awaiting run.”
- **Smallest correction:** add a `resetSignalCards()` renderer or make `renderSignalCard` accept an empty state, and cover it with a browser-level smoke test or a DOM fixture test.

#### P1 — cross-signal “agreement” is an availability heuristic

- **Location:** `src/domain/quality.js:32–36`, `src/domain/trust.js:4–16`.
- **Trigger:** interpret the displayed agreement/trust as corroboration of physiological movement.
- **Consequence:** available channels can increase agreement even when their directions or deviations disagree. The result is explainable but semantically weaker than the UI phrase “Shared movement across channels.”
- **Smallest correction:** for the MVP, rename/document the value as a simulated availability-and-change agreement heuristic; or implement a simple direction-sign comparison against baseline. Keep any change deterministic and fixture-tested.

#### P1 — config validation is incomplete for programmatic callers

- **Location:** `src/domain/pipeline.js:23–30` and optional `RunConfig` fields in `contracts.ts`.
- **Trigger:** call the domain API with `NaN`, infinity, zero, negative, or non-integer optional window/trust values.
- **Consequence:** the UI's fixed controls are safe, but a future worker, test fixture, or external adapter could produce `NaN` scores or unexpected empty windows. `initialTrust`, `qualityWindowSamples`, `baselineWindowSamples`, and `requiredPersistenceSamples` should have explicit finite/range checks.
- **Smallest correction:** validate normalized numeric fields before generation and return a clear error. Do not silently coerce malformed research configurations.

#### P2 — “build” is validation, not a production artifact build

- **Location:** `package.json:9–11`, `README.md:12–14`.
- **Consequence:** `npm run build` runs syntax checks and tests but emits no `dist/` directory or packaged artifact. This is valid for a deliberately source-served static app, but deployment docs must call it a validation check rather than imply bundling/minification.
- **Smallest correction:** document “static source deployment” explicitly, or add a pinned bundler only if deployment needs it. Do not add a bundler merely to satisfy the word build.

#### P2 — no automated browser interaction check

- **Location:** `test/frontend.test.js`.
- **Consequence:** the current frontend tests can prove that strings and imports exist, but not that `Start simulation`, `Reset`, playback, Canvas drawing, `both`, or missing-data rendering work in a real browser. The server smoke check also only proves that HTML is served.
- **Smallest correction:** manually smoke-test the three exposed scenarios for the two-day MVP, then add a browser test only if a suitable local runner is already available. Do not introduce a large browser-toolchain dependency unless the buildathon environment supports it offline.

### Additional frontend integration notes

- The UI selects `sampleRateHz: 1`, so the P0 issue is latent in normal UI usage rather than immediately visible through the current controls.
- The domain supports six scenarios, while the select exposes three aliases. This is a scope choice, not a blocker; document it and either expose the remaining recipes or keep them as system test fixtures.
- The seed is deterministic but derived from scenario, duration, and intensity. There is no user-editable seed, so the “rerun with a different seed” suggestion in the UI is not actionable without changing another control. Either add a seed control later or change the wording to “change the configuration and rerun.”
- `export.js` provides JSON/CSV serialization but no download control. Export is not required for the two-day MVP and should remain out of scope unless the demo needs a reproducible artifact.

## 5. Proposed minimal architecture

Keep the current vanilla browser shell and pure local domain engine. The recommended boundary is:

```text
RunConfig + seed
  -> scenario definition and truth annotations
  -> deterministic clean signal generator
  -> artifact/dropout injection
  -> per-window quality features and score
  -> cross-signal agreement heuristic
  -> sensor-trust update
  -> rolling baseline, deviation, trend, persistence
  -> threshold baseline classifier
  -> reliability-aware classifier
  -> common prediction merge and benchmark matcher
  -> structured explanations
  -> SimulationRun
  -> browser renderer/playback
```

### Proposed file/module map

The current repository already implements most of this map. The names below reflect the actual files, not a hypothetical framework migration:

```text
src/
  domain/
    contracts.ts       # shared contract; enforce or explicitly document its status
    prng.js            # seeded PRNG, clamp, stable hash, rounding
    scenarios.js       # channel metadata, scenario recipes, truth annotations
    generator.js       # clean signals plus event/artifact/dropout injection
    quality.js         # windowed quality features and bounded score
    trust.js           # agreement heuristic, trust update, recovery time
    baseline.js        # rolling median, deviation, slope, persistence/recovery
    algorithms.js      # threshold and reliability-aware comparison arms
    benchmark.js       # alert matching and simulated benchmark metrics
    explanations.js    # reason codes and evidence-linked explanations
    export.js          # deterministic JSON/CSV helpers (optional MVP surface)
    pipeline.js        # createSimulationRun orchestration
    index.js           # public domain exports
  ui/                  # optional later split; not needed for two-day MVP
    render.js           # future DOM adapter extracted from app.js
    chart.js            # future Canvas adapter extracted from app.js
app.js                 # current thin browser entry point and playback adapter
index.html              # static UI shell and safety wording
styles.css              # responsive styling
test/
  domain.test.js        # deterministic domain fixtures
  frontend.test.js      # static shell invariants
  browser.smoke.*       # optional later real-browser flow test
```

Do not create a backend folder, API route, database schema, or cloud client for the MVP. If the system agent later needs a worker boundary, `createSimulationRun` is already close to a worker-safe pure function; pass a serializable `RunConfig` in and return a serializable `SimulationRun` out.

## 6. Shared frontend/system data contract

`src/domain/contracts.ts` already exists and should be the shared contract rather than creating a second schema. It defines:

- `RunConfig`: scenario, duration, sample rate, artifact intensity, algorithm IDs, seed, and optional analysis windows;
- `SimulatedSignalSample` and `SimulatedVitalSignal`: relative time, nullable channel values, and units;
- `SimulatedScenarioDefinition` and `SimulatedGroundTruthAnnotation`: named scenario metadata and half-open truth/artifact/disconnection intervals;
- `SignalQuality` and `SignalQualityFeatures`: bounded score, features, missingness/artifact values, and reason codes;
- `SensorTrust`, `SimulatedRollingBaseline`, and `EvidenceWindow`: update direction, baseline/deviation/trend, cross-signal agreement, unavailable channels, and contradiction flag;
- `AlgorithmInput`, `AlgorithmOutput`, `Prediction`, and `AlgorithmResult`: common classifier input/output and merged timeline intervals;
- `BenchmarkMetrics`: simulated alert/event/latency/uncertainty/recovery/explanation metrics;
- `StructuredExplanation`, `ExplanationItem`, and `SimulationRun`: evidence-linked explanation content and the complete pipeline result.

### Contract rules for both agents

1. Time is run-relative seconds. Use half-open intervals `[startSec, endSec)` everywhere.
2. `null` means unavailable or not computable; it must never be silently converted to zero.
3. Scores and confidence-like values are `0..1` simulation values. UI percentages are formatting only.
4. Ground truth annotations and algorithm predictions are separate objects and must never be conflated.
5. Stable algorithm IDs are `threshold-baseline` and `reliability-aware`.
6. `SimulationRun` must include the effective normalized config and seed so a run can be reproduced.
7. Every prediction interval must use the configured sample interval and remain inside the run's time domain, with the terminal boundary documented.
8. Explanations must cite actual reason codes/evidence values. The UI must not invent classifications or metrics.
9. All event/artifact/benchmark wording remains explicitly simulated and non-clinical.

### Contract gaps to resolve before another agent integrates

- Add `artifactEndSec` to `BenchmarkMetrics`, or stop returning it; do not allow runtime-only fields to silently drift.
- Decide whether `AlgorithmOutput.endSec` is a raw sample window or whether outputs are only point decisions. The current implementation uses intervals, so use the configured interval consistently.
- Decide whether `both` is a view-only UI value or add it to `AlgorithmId`; it is currently not an algorithm ID and should not be passed to the domain.
- Decide whether the `crossSensorConsistency` field means availability or actual direction agreement. Rename or document it to prevent semantic overclaiming.
- Add a validation policy for optional numeric config fields.

## 7. Minimum viable feature set

### Keep in the two-day MVP

The current implementation already covers most of this list. The remaining work is to fix the interval bug, tighten the contract, and make the UI behavior truthful:

- three simulated channels with explicit units and a documented 1 Hz UI sampling rate;
- a reproducible seed/config and stable run ID;
- three exposed scenarios: clean/stable, motion artifact, and multi-sensor dropout;
- system fixtures for the additional event and sensor recipes;
- ground-truth event/artifact/disconnection annotations with bounded relative-time ranges;
- per-window quality and trust values with visible missing-data behavior;
- rolling baseline, deviation, trend, persistence, and recovery for all channels;
- threshold and reliability-aware comparison arms on shared inputs;
- simulated benchmark metrics with a single matching policy;
- structured explanation titles, reason codes, and evidence values;
- local playback, reset, algorithm view, and responsive chart/timeline;
- offline `make test`, syntax/build validation, and explicit safety copy;
- a short manual smoke script or browser test for Start, Pause, Reset, scenario change, and missing values.

### Do not attempt in this MVP

- cloud AI, LLM interpretation, prompt orchestration, or API-key configuration;
- real patient data, clinical validation, regulatory claims, diagnosis, treatment, or medical advice;
- proprietary medical-device integrations, Bluetooth, serial, WebRTC, or real-time hardware streaming;
- authentication, collaboration, database persistence, required backend services, or hosted job runners;
- learned models, neural networks, model tuning, calibration, or claims of generalization;
- medical thresholds, clinical confidence intervals, or claims of accuracy, sensitivity, specificity, safety, or validated performance;
- a large scenario authoring tool, plugin system, advanced statistical dashboard, or production design system;
- export/download UI unless the buildathon demo explicitly needs a reproducible artifact;
- framework migration or bundling solely for aesthetic or fashion reasons.

## 8. Safety and wording review

### Wording that is currently safe and should remain visible

The UI and README consistently use “simulated,” “research prototype,” “local,” “not for diagnosis,” “not for clinical monitoring,” and “not for clinical use.” The benchmark panel explicitly says its metrics are not clinical performance measures. Preserve these statements in screenshots, demo scripts, README text, and any future export.

### Risks to monitor

- “Physiological event,” “deterioration,” “high evidence,” and “confidence” can sound clinical if shown without “simulated” or “algorithmic.” Prefer “simulated event,” “simulated change,” and “algorithmic confidence.”
- “Cross-signal agreement,” “sensor trust,” and “signal quality” are heuristic values over generated data. They must not be presented as validated device quality, patient reliability, or clinical confidence.
- “Benchmark” is acceptable only when scoped as “simulated benchmark snapshot” or “research benchmark for this configured run.”
- Never call an algorithm “recommended,” “safe,” “validated,” or “better” based on the current single-run metrics.
- Do not report the current output as a patient state or diagnosis. `NOMINAL`, `MULTI_SIGNAL_SUPPORTED_EVENT`, and similar labels are algorithmic simulation classifications only.
- Keep missing evidence distinct from nominal evidence. The dropout behavior and tests correctly move in this direction; preserve it in future changes.
- The words “detection,” “missed,” and “nuisance” should remain tied to simulated annotations and predictions, not real clinical outcomes.

Recommended UI copy adjustments are small: change the “rerun with a different scenario or seed” instruction to mention changing configuration unless a seed control is added, and clarify that the displayed agreement is a simulation heuristic. No large safety redesign is needed.

## 9. Smallest meaningful test plan

### Existing coverage

The current 15-test suite already covers:

1. deterministic serialization for the same seed/config;
2. seed variation with stable scenario truth;
3. bounded scenario annotations and dropout values;
4. quality formula bounds and clean/missing/artifact ordering;
5. trust clamping and asymmetric decay/recovery;
6. baseline warm-up, current-value exclusion, deviation, and persistence;
7. both algorithms consuming the same run;
8. insufficient evidence for multi-sensor dropout;
9. benchmark matching, nuisance alerts, missed events, latency, uncertainty duration, and half-open boundaries;
10. deterministic JSON/CSV serialization and null preservation;
11. shell safety markers, domain import wiring, no `Math.random()` in the UI, and responsive CSS markers.

### Add before implementation handoff

1. **Interval regression:** at 2 Hz, assert every raw output duration is `0.5` seconds and merged predictions stay within the run's declared time domain.
2. **Benchmark regression:** compare a 1 Hz and 2 Hz fixture with equivalent scenario timing; ensure uncertainty duration and event overlap are not inflated by sample rate.
3. **Config boundaries:** reject invalid optional windows, initial trust, non-finite values, and unsupported algorithm/scenario IDs with explicit errors.
4. **Agreement semantics:** fixture two channels with opposite movement and assert the chosen agreement policy reflects the documented behavior.
5. **Frontend reset:** after a run, reset and verify all three channel cards return to em dashes/zero-width bars and hide missing notices.
6. **Algorithm view:** verify `threshold-baseline`, `reliability-aware`, and `both` each have an intentional behavior rather than silent fallback.
7. **Manual browser smoke:** serve locally, start each exposed scenario, pause/resume, change speed, reset, switch algorithm view, and inspect the dropout missing-value interval.
8. **No-network check:** run `make test` with network unavailable; it must not call a cloud service or download a runtime package.

Do not add a large test framework to satisfy this list. Node's built-in test runner is sufficient for the domain; a browser runner is optional only if it can be pinned and run offline in the buildathon environment.

## 10. Prioritized blockers

| Priority | Blocker | Owner | Exit criterion |
|---|---|---|---|
| P0 | Prediction end times ignore sample interval | System/domain | `sampleRateHz: 2` interval and benchmark regression tests pass. |
| P1 | TypeScript contract can drift from runtime JS | System + frontend | Contract fields and runtime result agree; typecheck or documented runtime validation exists. |
| P1 | `both` algorithm view silently selects reliability-aware | Frontend | Option removed or both-mode rendering is explicit and tested. |
| P1 | Reset leaves stale signal cards | Frontend | Reset returns every panel to a coherent empty state. |
| P1 | Agreement label overstates availability heuristic | System + frontend | Semantics are implemented or wording is scoped as a simulation heuristic. |
| P1 | Optional domain config values lack complete validation | System/domain | Invalid configs fail deterministically with clear errors. |
| P2 | No browser interaction test | Frontend/build | Manual smoke checklist is recorded; automated test only if toolchain remains offline/reproducible. |
| P2 | Docker image not verified in this environment | Build/release | Run Docker daemon and complete `docker build`/`docker run` on CI or a developer machine. |
| P2 | `npm run build` emits no artifact | Build/release | Docs call it validation/static deployment, or a justified pinned bundler is added later. |

## 11. Recommended implementation sequence

1. **System/domain fix:** use `sampleIntervalSec` for raw algorithm output end times; add the 2 Hz regression fixtures.
2. **System/domain contract pass:** align `contracts.ts` with actual benchmark fields, validate optional numeric config, and document the agreement heuristic.
3. **Frontend correctness pass:** fix reset empty state and either remove or implement the `both` interpretation mode.
4. **Frontend wording pass:** make seed/re-run guidance truthful and keep all simulated/non-clinical labels intact.
5. **Verification:** run `make test`, `make build`, the local server smoke check, and the manual browser checklist for clean, motion-artifact, and dropout.
6. **Optional polish only if time remains:** split `app.js` into `ui/render.js` and `ui/chart.js`, expose more scenarios, or add export downloads. None is required to demonstrate the core architecture.

This order keeps the domain contract stable before UI polishing and avoids parallel implementations of quality, trust, benchmark, or explanation logic.

## 12. Agent handoff

### Frontend agent should implement

- Keep `index.html` and `styles.css` as the visual shell; do not migrate frameworks.
- Make the empty/reset state clear all signal cards, baselines, trends, bars, and missing notices.
- Remove the `both` option or implement an explicit two-trace interpretation view. Keep the benchmark table as the always-available comparison surface.
- Render only the normalized `SimulationRun` result. Do not recalculate quality, trust, benchmark metrics, classification, or explanations in the browser.
- Keep the Canvas timeline, annotation bands, missing-value gaps, and uncertainty presentation tied to contract intervals.
- Make the seed/re-run copy match the actual controls and preserve simulated/non-clinical wording.
- Add the smallest possible UI smoke coverage, or at minimum run the manual checklist in this report.

### System/domain agent should implement

- Fix `src/domain/algorithms.js` to use `input.sampleIntervalSec` for `endSec`.
- Add sample-rate-aware raw-output and benchmark regression fixtures.
- Validate all normalized config fields, including optional window sizes, initial trust, seed finiteness, and supported IDs.
- Align `contracts.ts` with runtime fields and decide whether to add a pinned typecheck or explicit runtime validation.
- Either improve cross-signal agreement to compare direction/evidence or rename/document its availability-based heuristic.
- Keep the pure, deterministic `createSimulationRun` boundary and the current algorithm/benchmark separation.
- Do not add cloud AI, APIs, credentials, real patient data, proprietary device integration, or clinical thresholds.

### Backend/system boundary

No backend is required for the MVP. If a backend/system workstream exists, it should implement or test the pure domain engine and return the shared `SimulationRun` contract. A server, database, authentication layer, or network API would be scope expansion rather than an unblocker.

## 13. Exact setup, test, run, and production commands

Run these from the repository root:

```bash
# Check the intended runtime (Node 20.x; .nvmrc and package.json pin it)
node --version

# Install the project-local dependency graph from the committed lockfile.
# There are currently no declared npm dependencies.
npm ci

# Single offline test command required by the buildathon.
make test

# Equivalent direct test command.
npm test

# Syntax checks plus the same deterministic test suite.
make build
# or: npm run build

# Run the local static server.
npm start
# or: make serve

# Open http://localhost:8080 in a modern browser.

# Production/static validation: no bundle is emitted. Deploy the repository's
# static files with the included server or a static host after make build.

# Optional container path, requiring a running Docker daemon:
docker build -t aura-med-lab .
docker run --rm -p 8080:8080 aura-med-lab
```

The current `make test` command is the required reproducible check and does not need a cloud service or API key. `make build` is a syntax/test validation step, not a bundling step. Docker build/run was not verified in this audit because the local Docker daemon was unavailable, even though the Docker CLI was installed.

## Final assessment

The repository has moved beyond the original visual shell: the local-first deterministic domain engine and the frontend integration contract are present and testable. The architecture is appropriately small for a two-day buildathon and already avoids the prohibited dependencies and medical claims. The implementation should proceed with the P0 interval correction, contract alignment, and two small frontend fixes before demo or benchmark comparisons are treated as reliable within the simulation's own definitions.

No major feature or redesign was implemented as part of this audit. This report refreshes `AUDIT.md` to match the current repository evidence and records the smallest next steps for the frontend and system/domain agents.
