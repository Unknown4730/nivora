# AURA-Med Lab Implementation Audit

**Audit scope:** repository at commit `d07a142` plus the minimal syntax correction to `app.js` required for JavaScript parsing during this audit. This is an evidence-based architecture review; it does not claim clinical validity or real-world medical performance.

## Executive summary

The repository is a very small, local-first static browser prototype. It is suitable as a visual buildathon shell and can run without a backend, API key, database, GPU, or proprietary device integration. It is **not yet an implementation of the stated reliability-aware research platform**: its chart is generated from random trigonometric traces, its metrics are heuristic display values, there are no physiological events or ground-truth annotations, and no algorithmic comparison is actually computed from shared data.

The highest-priority blockers are:

1. The original `app.js` did not parse because three object literals used `color=` instead of `color:`. This was corrected minimally so the page can execute.
2. There is no deterministic seed or reproducible run model; `Math.random()` is used for traces, scores, and run IDs.
3. Scenario, duration, and algorithm controls are not wired into a simulation engine. Only scenario and intensity influence display formulas; duration and algorithm selection are ignored.
4. There is no domain/data contract, event model, artifact model, quality/trust model, baseline/trend model, classifier output, or benchmark evaluator.
5. The Dockerfile invokes `npx --yes serve` at container start, requiring a network fetch and without a lockfile. That conflicts with reproducible/offline buildathon requirements.
6. `make test` is only a file/string smoke test. It does not parse or execute the app logic and originally missed the syntax error.

**Recommendation:** keep the current visual shell, add a small deterministic TypeScript domain layer (or plain JavaScript domain modules if TypeScript tooling is intentionally deferred), then connect the UI to one `SimulationRun` result. Do not add a backend for the MVP.

## 1. Repository evidence

### Structure

```
.
├── .gitignore
├── .nvmrc
├── Dockerfile
├── Makefile
├── README.md
├── app.js
├── index.html
└── styles.css
```

There is one initial commit and no uncommitted source changes at the start of the audit. No `package.json`, package lockfile, TypeScript configuration, bundler configuration, test directory, or CI workflow exists.

### Actual stack

| Area | Evidence | Finding |
|---|---|---|
| Frontend framework | `index.html`, `app.js` | Vanilla HTML and browser JavaScript; no React/Vue/Svelte/etc. |
| Build tool | No configuration; `Makefile` only serves/tests | No build step or asset bundling. |
| Language | `app.js` | JavaScript, compressed into a few long lines. No TypeScript. |
| Styling | `styles.css` | Hand-written CSS, with an external Google Fonts `@import` and system fallback fonts. |
| Runtime | `.nvmrc`, `Dockerfile` | Node 20 is declared, but the local dev path uses Python's static server. The container uses `node:20-alpine` and runtime `npx`. |
| Tests | `Makefile:test` | Python assertions for file existence and marker strings only. No browser, unit, integration, or algorithm tests. |
| Documentation | `README.md` | Basic local/Docker instructions and scope disclaimer. No architecture or contribution guide. |

The available container has Node `v22.23.0`, npm `10.9.9`, and Python 3; Docker is not installed in the audit environment. The project declares Node 20 but has no package manifest or lockfile to make a Node dependency graph reproducible.

## 2. Current behavior and suitability

### What works in the current shell

- A static page with a responsive layout is present.
- The page clearly labels data as simulated and not a clinical, diagnostic, or monitoring tool.
- The run button draws three colored traces on a canvas and updates visible metric cards after a timeout.
- A local Python server can serve the files.
- No mandatory cloud AI, API key, GPU, database, or device integration is present.

### What is only visual or heuristic

- `signal()` in `app.js` creates three noisy sine-wave arrays; it does not model named physiological events or sensor artifacts.
- The SpO₂, heart-rate, and respiration labels are presentation labels, not typed signal channels with units and sampling metadata.
- Quality, trust, agreement, uncertainty, nuisance alerts, missed events, and latency are derived from simple formulas using intensity and random values. They are not computed from predictions versus ground truth.
- The explanation text is static after every run. It does not cite window IDs, scores, evidence, or actual decision reasons.
- The chart does not show event or artifact annotations, uncertainty bands, thresholds, or baseline/trend overlays.

### Suitability verdict

**Suitable as a browser-only local-first UI shell:** yes.

**Suitable as the requested reliability-aware MVP today:** no. The missing domain engine and reproducible benchmark contract are blockers, but they can be addressed within a two-day buildathon if the scope remains one deterministic scenario engine and a small set of explicit outputs.

## 3. Reusable components and integration points

The codebase has no reusable component library or utilities. The useful existing integration points are:

- `index.html`: controls (`scenario`, `duration`, `intensity`, `algorithm`), metric output IDs, chart canvas, explanation region, and benchmark cards. These should remain stable UI adapters while domain logic is extracted.
- `app.js`: `run()` is the current orchestration boundary. Replace its formulas with `createSimulationRun(config)` and render the returned contract.
- `draw()`: canvas renderer boundary. It can accept `SimulationRun.samples` and optional annotations instead of generating data itself.
- `styles.css`: visual system and responsive layout can be retained. Avoid a UI rewrite during the MVP.
- `Makefile`: natural place for a single offline `test` command and a static `serve` command, but the current smoke test must become meaningful.

There are no existing types, utilities, state stores, API clients, persistence adapters, or backend integration points to preserve.

## 4. Architecture risks and blockers

### P0 — correctness blockers

- **Parse failure fixed during audit:** the original `draw()` object literals had `color="..."`, causing `node --check app.js` to fail with `SyntaxError: Invalid shorthand property initializer`. The correction was limited to `color:` in the three trace definitions.
- **No reproducibility:** `Math.random()` appears in signal noise, metric values, and run IDs. A benchmark cannot be compared across runs without a seeded PRNG and a recorded configuration/seed.
- **No ground truth:** missed events and latency cannot be validly calculated without event annotations and a defined matching policy.
- **No actual algorithm comparison:** both cards are populated by arithmetic formulas; the selected algorithm is not used.

### P1 — build and integration blockers

- **No lockfile or package manifest:** the project cannot pin JavaScript dependencies because it has none declared. The Dockerfile's `npx --yes serve` may download a package at runtime, which is not offline/reproducible.
- **Weak test command:** the current test does not run JavaScript syntax checks or exercise the user flow. It passed even while `app.js` was syntactically invalid.
- **Controls are partly decorative:** `duration` and `algorithm` do not change the result. The chart axis is always labeled 0–60 seconds regardless of duration.
- **Single-file maintainability:** domain generation, rendering, scoring, and UI updates are in one minified file. This makes review and deterministic unit testing difficult.

### P2 — research/demo risks

- No explicit units, sampling rate, window size, threshold definitions, or missing-data representation.
- No explicit classification vocabulary or uncertainty policy.
- The UI labels `RECOMMENDED` for the reliability-aware algorithm without a real evaluation. Use neutral wording such as `Comparison arm` until metrics are computed from ground truth.
- External Google Fonts import introduces an unnecessary network dependency. The UI has fallbacks, so it is not a functional blocker, but local-first/offline styling should not depend on it.
- The current Docker path is documented but unverified here because Docker is unavailable.

## 5. Proposed minimal architecture

Keep everything in the browser and make the domain engine a pure deterministic pipeline:

```
RunConfig + seed
  → scenario definition
  → signal generator
  → artifact injector
  → ground-truth annotations
  → quality features/scores
  → rolling baseline/trend
  → threshold classifier + reliability-aware classifier
  → benchmark evaluator
  → explanation generator
  → UI adapter/canvas renderer
```

Suggested module map:

```
src/
  domain/
    contracts.ts        # shared data contract (added by this audit)
    prng.ts             # seeded deterministic random generator
    scenarios.ts        # named scenarios and event/artifact recipes
    generator.ts        # clean channels + injected artifacts + annotations
    quality.ts          # per-channel/window quality features and scores
    baseline.ts         # rolling median/mean, robust deviation, trend
    classifiers.ts      # threshold and reliability-aware decisions
    benchmark.ts        # alert/event matching, latency, uncertainty
    explanations.ts     # structured reasons, not free-form claims
    pipeline.ts         # createSimulationRun(config)
  ui/
    render.ts           # DOM metrics and explanations
    chart.ts            # canvas plotting and annotations
app.js                 # thin browser entry point, or app.ts if bundling is added
```

For a two-day buildathon, the files can initially remain plain `.js` with JSDoc types if adding a TypeScript compiler would slow delivery. The contract should still be treated as authoritative.

### Signal generation

- Use a fixed sampling rate such as 1 Hz or 2 Hz and document it.
- Generate normalized, simulated channel values with explicit units: SpO₂ `%`, heart rate `bpm`, respiration `breaths/min`.
- Use a seeded PRNG. Store the seed in the run result.
- Keep signal generation separate from artifact injection so clean signal, artifact, and event truth remain inspectable.

### Scenario definitions

Start with three deterministic scenarios only:

1. `clean`: one event with little artifact.
2. `motion-artifact`: event overlaps a bounded artifact interval.
3. `dropout`: one channel becomes missing or low quality for a bounded interval.

A scenario should define events and artifacts as time ranges and parameters, not implicit conditionals inside the renderer.

### Ground truth annotations

Represent simulated events as annotations with `kind`, `startSec`, `endSec`, optional severity/target channel, and a stable ID. Keep truth separate from algorithm predictions. Never call these patient outcomes.

### Signal quality

Calculate a bounded `0..1` score per channel/window from explainable features such as missing fraction, noise estimate, range plausibility for the simulation, and artifact overlap. Record feature values and reasons. Quality is a simulation quality signal, not clinical signal quality validation.

### Sensor trust

Update trust from quality and cross-signal agreement using a documented, bounded rule, for example:

`trust = clamp(0.6 * quality + 0.4 * agreement, 0, 1)`

Use a short rolling smoothing window and expose the components. Avoid opaque learned weights.

### Baseline and trend

Use a rolling median or mean over a documented window. Compute a simple slope or delta against the baseline. Define warm-up behavior explicitly; do not classify until enough history exists, or emit `uncertain` with reason `insufficient_history`.

### Algorithms

- **Threshold baseline:** fixed value/trend thresholds only; it should not use quality/trust or cross-signal agreement.
- **Reliability-aware:** combine deviation, trend, trust, and cross-signal evidence. If trust is below a configured threshold or evidence conflicts, emit `uncertain` rather than a hard alert.

Both algorithms must consume the same samples and return the same prediction contract so benchmark comparisons are fair.

### Benchmark metrics

Given truth annotations and predictions, define matching once and apply it to both algorithms. Minimum outputs:

- nuisance alerts: predicted alert windows with no matched truth event;
- missed events: truth events with no matched prediction;
- detection latency: first matching prediction time minus event start, or `null` if missed;
- uncertain windows: count and duration of `uncertain` windows;
- counts of truth events and predictions used in the denominator.

These are simulated benchmark metrics for this prototype, not clinical performance metrics.

### Explanations

Generate structured explanation items from actual pipeline values: baseline deviation, trend direction, quality, trust, agreement, and uncertainty reasons. The UI can format these items, but should not invent an explanation string after the fact.

## 6. Shared frontend/system contract

`src/domain/contracts.ts` is the proposed shared TypeScript contract. It is intentionally dependency-free and browser-safe. It defines configuration, samples, truth annotations, quality/trust evidence, predictions, benchmark metrics, explanations, and the complete `SimulationRun` returned to the frontend.

Contract rules:

- Time is relative to the run in seconds; no patient/date fields are needed.
- All values are simulated and must remain labeled as such in user-facing copy.
- `null` means unavailable/not computable; it must not be silently converted to zero.
- Scores use `0..1`; percentages are UI formatting only.
- Truth and prediction objects are separate.
- `algorithmId` values are stable: `threshold-baseline` and `reliability-aware`.
- The frontend should render only returned results; it should not recalculate benchmark metrics.
- The system/domain implementation should remain pure and deterministic for a given config and seed.

## 7. Minimum viable feature set

### Must have

- Three named simulated channels with units and documented sampling rate.
- A deterministic seed and a visible scenario/run configuration.
- Three scenarios: clean, motion artifact, dropout.
- Ground-truth event/artifact annotations visible on the chart or in a compact event list.
- Per-window quality and trust scores with a simple explanation of their inputs.
- A rolling baseline and trend value for at least one primary channel.
- Two algorithms consuming the same data and returning `alert`, `normal`, or `uncertain` predictions.
- Benchmark metrics computed from truth/prediction matching.
- A compact interpretation trace linked to actual evidence.
- Offline setup/test instructions and a meaningful test command.
- Explicit “simulated research prototype; not clinical/diagnostic/monitoring” wording in the UI and README.

### Do not attempt in the two-day MVP

- Cloud AI, LLM interpretation, prompt orchestration, or API-key flows.
- Real patient data, clinical validation, regulatory claims, or medical-device connectivity.
- Authentication, multi-user collaboration, database persistence, or a required backend.
- Real-time device streaming, WebRTC, Bluetooth, serial, or hardware integration.
- Learned models, neural networks, or tuning claims.
- Large scenario authoring tools, plugin systems, export pipelines, or advanced dashboards.
- Statistical confidence intervals or medical thresholds presented as validated cutoffs.
- A production-grade design system or a framework migration unless testing proves it necessary.

## 8. Safety and wording review

Safe current wording includes “simulated data only,” “research prototype,” and “not a clinical, diagnostic, or monitoring tool.” Preserve these statements in the UI, README, and any screenshots/demo script.

Avoid or replace:

- “patient,” “patient monitoring,” “clinical event,” “diagnosis,” “risk,” “safe,” or “validated”;
- “accuracy,” “sensitivity,” “specificity,” or “performance” without a clearly scoped simulated benchmark definition;
- “recommended” for an algorithm before a computed, reproducible comparison exists;
- real-looking hard physiological limits presented as medical guidance.

Preferred terms are “simulated event,” “artifact interval,” “research benchmark,” “comparison arm,” “uncertain,” and “algorithm output.” If the demo compares metrics, label the section “Simulated benchmark snapshot.”

## 9. Smallest meaningful test plan

1. **Static checks:** verify required files; run `node --check app.js` (or the future compiled entry point).
2. **Determinism:** same `RunConfig` and seed produce byte-equivalent samples, annotations, predictions, and metrics.
3. **Scenario truth:** each scenario emits its documented event/artifact types and bounded time ranges.
4. **Quality/trust boundaries:** clean windows score higher than artifact/dropout windows; all scores remain in `0..1`; missing data is not treated as zero.
5. **Classifier behavior:** threshold baseline ignores trust; reliability-aware produces `uncertain` under low trust/conflicting evidence.
6. **Benchmark matching:** known fixture cases verify nuisance alerts, missed events, and latency including `null` for missed events.
7. **UI smoke:** serve the app, click Run, and verify metrics, trace state, explanations, and benchmark output change from the empty state.
8. **No-network check:** tests and local run do not require API keys or cloud services. Remove the runtime `npx` download from the Docker path before calling Docker reproducible.

The current `make test` covers only item 1 partially (file/string existence) and none of items 2–8.

## 10. Recommended implementation sequence

1. Keep the current UI shell and correct/format the entry script (the syntax fix from this audit is already minimal).
2. Add seeded PRNG, contract types, and one deterministic `clean` scenario with truth annotations.
3. Add artifact injection and the two remaining scenarios.
4. Implement quality, trust, rolling baseline, and trend as pure functions with fixtures.
5. Implement both classifiers behind one prediction contract.
6. Implement benchmark matching and structured explanations.
7. Replace the current `run()` formulas with one pipeline call and render its returned result.
8. Add offline unit tests and a browser smoke test; update `README.md` and Docker to use only pinned/local assets.
9. Remove unsupported UI wording such as `RECOMMENDED` until the computed comparison justifies a neutral or explicitly simulated label.

## 11. Agent handoff

### Frontend agent

- Preserve the existing visual layout in `index.html` and `styles.css`.
- Split rendering from domain computation.
- Render `SimulationRun` samples, event/artifact annotations, quality/trust summaries, prediction states, benchmark metrics, and structured explanations.
- Wire all controls, including duration and algorithm selection, to the shared config.
- Keep all safety disclaimers visible and use “simulated benchmark” language.
- Add the UI smoke test and avoid external runtime assets where practical.

### System/domain agent

- Implement the pure deterministic pipeline under `src/domain/` using `contracts.ts`.
- Add seeded generation, scenario recipes, truth annotations, quality, trust, rolling baseline/trend, both classifiers, benchmark matching, and explanations.
- Write fixture-based unit tests for determinism, boundaries, uncertainty, and metric matching.
- Do not add cloud AI, backend requirements, medical-device integrations, or clinical claims.
- Return one complete `SimulationRun` object for the frontend; do not let the UI invent metric values.

## Exact commands

Current repository commands:

```bash
# Static smoke test (currently weak; should be expanded)
make test

# Syntax check for the browser entry script
node --check app.js

# Local static server
make serve
# then open http://localhost:8080

# Intended container path (not executed in this environment; Docker was unavailable)
docker build -t aura-med-lab .
docker run --rm -p 8080:8080 aura-med-lab
```

There is currently **no production build command** because there is no build tool or package manifest. The project is served as static source. Before a production-build claim is made, either document static files as the deliberate production artifact or add a pinned local toolchain and lockfile; do not rely on runtime `npx` downloads.
