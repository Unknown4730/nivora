# AURA-Med Lab

AURA-Med Lab is an open-source, browser-based research prototype for exploring reliability-aware interpretation of noisy, **simulated** physiological time-series data. It is not a clinical tool, diagnostic system, medical device, or patient-monitoring product.

## Run locally

Requirements: Python 3 or Node 20 (pinned in `.nvmrc`). No API keys, backend, database, GPU, or cloud service is required.

```bash
make test
make serve
```

Open http://localhost:8080. Configure a scenario and press **Run simulation** to inspect simulated SpO₂, heart rate, and respiration traces, signal quality, dynamic trust, cross-signal agreement, uncertainty windows, and a baseline-vs-reliability-aware benchmark snapshot.

## Docker

```bash
docker build -t aura-med-lab .
docker run --rm -p 8080:8080 aura-med-lab
```

The simulation uses browser-local generated data and makes no clinical claims.
