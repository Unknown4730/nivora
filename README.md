# AURA-Med Signal Reliability Backend

AURA-Med is a local-first research and algorithm-validation workbench for
reliability-aware interpretation of noisy physiological time-series data.

The current phase delivers a Python processing backend and a versioned FastAPI
boundary. It operates on deterministic simulated data and is **not** a clinical
tool, diagnostic system, medical device, or patient-monitoring product.

## Current product boundary

The backend currently provides:

- deterministic simulated SpO₂, heart-rate, and respiration signals;
- six named scenarios with separate simulated ground-truth annotations;
- signal quality, rolling baselines, trend, persistence, and sensor-trust values;
- threshold and reliability-aware comparison algorithms;
- explicit missing-data and insufficient-evidence states;
- simulated benchmark metrics and structured explanations;
- stable JSON, CSV, and manifest exports;
- deterministic Phase 1 batch experiments across scenario × seed matrices;
- aggregate metrics with explicit denominators and confidence intervals;
- a FastAPI API under `/api/v1`;
- reproducible run IDs based on configuration, annotations, and seed.

The React/Tailwind frontend is intentionally not part of this phase. The
previous browser prototype is preserved under `legacy/js-prototype/` and is not
used by the Python backend.

## Repository layout

```text
backend/
  aura_med/
    api/
      main.py       # FastAPI application and service endpoints
      routes.py     # Versioned simulation, catalog, and export routes
      schemas.py    # Pydantic HTTP request boundary
      store.py      # Bounded process-local run store
    domain/
      pipeline.py   # Complete deterministic processing boundary
      models.py     # Typed domain dataclasses and serialization
      scenarios.py  # Scenario recipes and interval semantics
      generator.py  # Seeded simulated signal generation
      quality.py    # Windowed quality features and score
      trust.py      # Agreement heuristic and trust updates
      baseline.py   # Rolling baseline, trend, persistence, recovery
      algorithms.py # Comparison arms
      benchmark.py  # Prediction merging and simulated metrics
      explanations.py
      export.py
      prng.py
  tests/
    api/
    domain/
docs/
  audits/            # Preserved audit of the original JS prototype
legacy/
  js-prototype/      # Archived browser prototype; not part of the backend
```

## Requirements

- Python 3.12, pinned by `.python-version` and `pyproject.toml`.
- A project-local virtual environment.
- Network access only during dependency installation, unless the pinned wheels
  are already available in a local package cache.
- No API keys, database, GPU, cloud service, or real patient data are required.

## Setup

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --requirement requirements.lock
.\.venv\Scripts\Activate.ps1
```

### Linux/macOS

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --requirement requirements.lock
source .venv/bin/activate
```

The lock file is `requirements.lock`. `requirements.txt` points to it for
tools that expect the conventional filename. Dependencies must stay inside
`.venv`; do not install them globally.

## Test

The single reproducible backend test command is:

```bash
PYTHONPATH=backend python -m unittest discover -s backend/tests -p "test_*.py"
```

With the virtual environment active, use the project helper on Linux/macOS:

```bash
make test
```

On Windows PowerShell, use:

```powershell
$env:PYTHONPATH = "backend"
python -m unittest discover -s backend/tests -p "test_*.py"
```

The suite covers domain determinism, config validation, scenario annotations,
missing data, benchmark boundaries, sample-rate-aware output intervals, API
creation/read-back, and export endpoints.

## Run the API

From the repository root:

### Windows PowerShell

```powershell
$env:PYTHONPATH = "backend"
python -m uvicorn aura_med.api.main:app --host 127.0.0.1 --port 8000
```

### Linux/macOS

```bash
PYTHONPATH=backend python -m uvicorn aura_med.api.main:app \
  --host 127.0.0.1 --port 8000
```

The API is available at `http://127.0.0.1:8000`.

- OpenAPI UI: `http://127.0.0.1:8000/docs`
- Health: `GET /health`
- Scenario catalog: `GET /api/v1/scenarios`
- Create run: `POST /api/v1/simulations`
- Read run: `GET /api/v1/simulations/{run_id}`
- Run manifest: `GET /api/v1/simulations/{run_id}/manifest`
- Samples CSV: `GET /api/v1/simulations/{run_id}/samples.csv`
- Full JSON export: `GET /api/v1/simulations/{run_id}/run.json`
- Algorithm catalog: `GET /api/v1/algorithms`
- Create experiment: `POST /api/v1/experiments`
- Read experiment: `GET /api/v1/experiments/{experiment_id}`
- Experiment manifest: `GET /api/v1/experiments/{experiment_id}/manifest`

The run store is process-local and bounded to 128 runs. It is deliberately not
described as durable persistence. A future persistence layer should be added
only after data governance, provenance, retention, and access-control
requirements are agreed.

### Example request

```bash
curl -X POST http://127.0.0.1:8000/api/v1/simulations \
  -H "Content-Type: application/json" \
  -d '{
    "scenario": "multi-sensor-dropout",
    "durationSec": 75,
    "sampleRateHz": 2,
    "artifactIntensity": 0.48,
    "algorithms": ["threshold-baseline", "reliability-aware"],
    "seed": 20261018
  }'
```

The response is a complete deterministic `SimulationRun` in the original
camelCase JSON vocabulary, so the future React client can consume the backend
without duplicating domain calculations.

## Batch experiments

Phase 1 supports bounded, deterministic experiment suites. A suite executes the
Cartesian product of the requested scenarios and seeds, in the order supplied
by the caller:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/experiments \
  -H "Content-Type: application/json" \
  -d '{
    "suiteId": "artifact-sensitivity-v1",
    "scenarios": ["stable-baseline", "motion-artifact", "multi-sensor-dropout"],
    "seeds": [7, 11, 19],
    "baseConfig": {
      "durationSec": 60,
      "sampleRateHz": 1,
      "artifactIntensity": 0.48
    },
    "algorithms": ["threshold-baseline", "reliability-aware"]
  }'
```

The response contains compact run receipts, algorithm summaries, and a
reproducibility manifest. Aggregate scalar metrics include denominators and
95% intervals. Detection rate uses a Wilson interval; run-level scalar metrics
use a normal approximation with `1.96` and sample standard deviation. Empty
truth-event or detected-latency populations are represented as `null`.

Each batch is limited to 100 scenario × seed runs. The engine always delegates
signal processing and per-run benchmark calculations to the existing domain
pipeline; it does not maintain a second implementation of those rules.

## Docker

```bash
docker build -t aura-med-backend .
docker run --rm -p 8000:8000 aura-med-backend
```

The image installs only the pinned Python dependencies, copies the backend, and
starts Uvicorn. It does not install Node, download code at startup, or require
an external service.

## Domain contract

The public processing boundary is:

```python
from aura_med.domain import create_simulation_run

run = create_simulation_run({
    "scenario": "simulated-event",
    "durationSec": 90,
    "sampleRateHz": 2,
    "seed": 1234,
})
payload = run.to_dict()
```

The domain accepts both the historical camelCase configuration keys and the
Python snake_case keys. Runtime output uses camelCase for compatibility with
the archived prototype and future web clients. Python implementation names
remain snake_case.

Contract rules:

1. All time is run-relative seconds.
2. All intervals use half-open `[startSec, endSec)` semantics.
3. `None` means unavailable or not computable; it is not converted to zero.
4. Scores are bounded simulation heuristics in `[0, 1]`, not calibrated medical
   probabilities.
5. Ground-truth annotations and algorithm predictions are separate objects.
6. Every raw algorithm interval uses the configured sample interval and remains
   within `[0, durationSec]`.
7. A run stores its normalized config and seed for reproducibility.
8. Explanations cite the algorithm's reason codes and evidence values.

## Research and safety position

The system is intended to become a research and validation workbench for
biomedical engineers, wearable-device researchers, signal-processing teams,
and algorithm QA. The current generator is a transparent, hand-authored
simulation recipe. It is not a physiological model and does not establish
clinical performance.

Before real-world or clinical use, the project would require a governed data
ingestion layer, provenance, de-identification, risk management, cybersecurity,
external validation, usability evaluation, and an intended-use/regulatory
assessment. Those are explicitly outside this backend-first phase.

## Project status

Completed in this phase:

- migrated the deterministic processing engine from JavaScript to Python;
- fixed sample-rate-dependent output intervals;
- enforced finite and bounded configuration validation;
- aligned runtime benchmark fields with the domain model;
- added a FastAPI service boundary with OpenAPI documentation;
- added API read-back and export paths;
- moved the old browser prototype to `legacy/js-prototype/`;
- pinned Python dependencies and added a Python Docker runtime;
- added domain and API tests without executing frontend work.
- added Phase 1 multi-scenario/multi-seed experiment execution and aggregate
  benchmark summaries.

Known limits:

- no durable database or authentication;
- no public dataset or real-device adapter;
- no CI service or automated Docker build in this environment;
- no React/Tailwind frontend yet, by request;
- experiment results are process-local and not durable;
- cross-signal agreement remains an availability-and-change heuristic and must
  not be presented as validated sensor agreement.
