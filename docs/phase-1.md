# Phase 1 implementation record

## Goal

Turn the single-run simulation backend into a reproducible research benchmark
engine. Researchers can define a suite of scenarios, seeds, common
configuration, and algorithm arms; execute the Cartesian product; and receive
comparable aggregate metrics with explicit denominators and confidence
intervals.

## Acceptance criteria

- A validated experiment spec contains `suiteId`, `scenarios`, `seeds`,
  `baseConfig`, and `algorithms`.
- The engine executes scenario × seed in caller-provided order, capped at 100
  runs per batch.
- Every run calls the existing Python domain pipeline; benchmark calculations
  are not duplicated in the experiment layer.
- Each batch is deterministic for the same normalized spec.
- Each algorithm summary includes run/event totals and scalar summaries for
  detection rate, nuisance alerts, nuisance alerts per hour, uncertain
  duration, uncertain fraction, detected latency, and explanation completeness.
- Scalar summaries expose count, mean, standard deviation, total, explicit
  denominator, and a 95% interval when meaningful.
- Detection rate uses a Wilson interval. Run-level scalar values use a
  documented normal approximation: mean ± 1.96 × sample standard deviation /
  √count for count >= 2.
- Zero truth events and empty detected-latency populations remain `null`, not
  synthetic zeroes.
- Manifests include stable algorithm versions, normalized spec, scenarios,
  seeds, run IDs, and an explicit non-clinical metrics note.
- FastAPI exposes algorithm metadata, batch creation, read-back, and manifest
  retrieval.
- No frontend code is executed or migrated in this phase.

## API

```text
GET  /api/v1/algorithms
POST /api/v1/experiments
GET  /api/v1/experiments/{experiment_id}
GET  /api/v1/experiments/{experiment_id}/manifest
```

The API uses a bounded process-local store. It supports read-after-create for a
working local system but is not durable persistence.

## Verification

```text
PYTHONPATH=backend .venv/Scripts/python.exe -m unittest discover -s backend/tests -p "test_*.py"
```

The Phase 1 tests cover deterministic serialization, Cartesian ordering,
aggregation denominators, zero-event handling, Wilson/normal interval bounds,
validation, manifest provenance, algorithm metadata, API read-back, and the
real engine through FastAPI.

## Research limitations

The metrics are still computed over deterministic simulated scenarios. They are
useful for implementation regression, algorithm comparison within the
simulation, and experiment-pipeline development. They are not clinical
performance measures and must not be generalized to patients, devices, or
populations.
