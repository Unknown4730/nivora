# AURA-Med backend architecture

## Boundary

```text
HTTP JSON
  -> FastAPI/Pydantic request validation
  -> normalized RunConfig
  -> deterministic Python domain pipeline
  -> SimulationRun dataclasses
  -> JSON / CSV / manifest exports
```

Batch research execution uses a separate orchestration boundary:

```text
ExperimentSpec
  -> ordered scenario × seed matrix
  -> create_simulation_run for every matrix cell
  -> compact run receipts
  -> algorithm aggregate summaries
  -> reproducibility manifest
```

The experiment layer owns suite validation and statistics only. It does not
reimplement signal generation, algorithm classification, or per-run benchmark
matching.

The domain package has no FastAPI dependency. It can be called from HTTP,
batch experiments, a worker process, or a future CLI without changing its
processing rules.

## Processing stages

1. Normalize and validate configuration.
2. Resolve a named scenario and bounded annotations.
3. Generate seeded simulated signal samples.
4. Compute rolling quality features.
5. Compute rolling baselines, trends, persistence, and recovery.
6. Update bounded sensor-trust values.
7. Build evidence windows.
8. Run each selected comparison algorithm against the same evidence.
9. Merge output windows into predictions.
10. Match predictions to simulated ground truth.
11. Produce structured explanations and reproducibility exports.

## API state

The current API stores created runs in a bounded, thread-safe process-local
store. This is sufficient for a working local backend and read-after-create
workflow. It is not a production persistence strategy. Any database addition
must include provenance, retention, authorization, privacy, and migration
decisions rather than being added as infrastructure by default.

## Future frontend contract

The React client should call the API and render the returned `SimulationRun`.
It must not reimplement quality, trust, classification, benchmark, or
explanation calculations. The backend remains authoritative for all derived
values.
