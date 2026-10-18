# AURA-Med Lab

AURA-Med Lab is an open-source, browser-based research prototype for exploring reliability-aware interpretation of noisy, **simulated** physiological time-series data. It is not a clinical tool, diagnostic system, medical device, or patient-monitoring product.

## Run locally

Requirements: Python 3 or Node 20 (pinned in `.nvmrc`). No API keys, backend, database, GPU, or cloud service is required.

```bash
npm ci                 # no external runtime dependencies
make test              # deterministic domain tests
make build             # syntax and production-readiness check
npm start              # dependency-free local static server
```

Open http://localhost:8080. Configure a scenario and press **Start simulation** to inspect simulated SpO₂, heart rate, and respiration traces, signal quality, dynamic trust, cross-signal agreement, uncertainty windows, event/artifact annotations, and a baseline-vs-reliability-aware benchmark snapshot. Playback, pause, reset, algorithm view, duration, and artifact intensity are all local browser interactions.

## Docker

```bash
docker build -t aura-med-lab .
docker run --rm -p 8080:8080 aura-med-lab
```

The simulation uses browser-local generated data and makes no clinical claims.

## Domain engine

The deterministic, UI-independent processing layer lives in `src/domain/`:

1. `pipeline.js` accepts a `RunConfig` and returns one complete `SimulationRun`.
2. `scenarios.js` defines six named scenarios and their simulated ground-truth annotations.
3. `generator.js` creates seeded SpO₂, heart-rate, and respiration samples, including noise, clipping, motion artifacts, missing values, disconnection, simulated changes, and recovery.
4. `quality.js`, `trust.js`, and `baseline.js` calculate transparent bounded evidence values.
5. `algorithms.js` exposes the threshold baseline and reliability-aware `AlarmAlgorithm` implementations.
6. `benchmark.js`, `explanations.js`, and `export.js` provide simulation metrics, structured reason codes, deterministic explanations, and JSON/CSV serialization.

The quality formula is an intentionally non-clinical simulation heuristic:

```text
score = 0.20 stability
      + 0.15 plausibility
      + 0.15 continuity
      + 0.20 (1 - missing fraction)
      + 0.20 (1 - artifact overlap)
      + 0.10 cross-sensor consistency
```

The weights are not clinically validated. Sensor trust uses a faster bounded decay rate and slower recovery rate, so one clean sample cannot immediately restore trust. Time intervals use the half-open convention `[startSec, endSec)`.

### Frontend contract

The frontend can import `createSimulationRun` from `src/domain/pipeline.js` (or the re-export in `src/domain/index.js`) and render the returned `SimulationRun`. It should not recalculate quality, trust, algorithm states, benchmark metrics, or explanations. `src/domain/contracts.ts` is the shared TypeScript contract and is kept separate from the browser-loadable JavaScript modules.

`app.js` is a thin browser renderer and imports `createSimulationRun` from the domain pipeline as an ES module. The renderer reads the returned `SimulationRun` data without duplicating quality, trust, classification, or benchmark calculations. No cloud AI provider, API key, real patient data, or proprietary device integration is required.
