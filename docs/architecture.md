# Nivora backend architecture

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

Live sessions add a separate acquisition and evidence-preservation path:

```text
Virtual/future source
  -> raw packet recorder
  -> canonical LiveSample validation
  -> bounded hot cache + SQLite WAL recorder
  -> failure detectors and append-oriented ledger
  -> streaming quality/algorithm events
  -> report, replay, and export bundle
```

The live source is virtual in Phase 2 because no physical sensor is available.
The adapter boundary is intentionally independent from the processing and
storage layers so LSL, serial, BLE, MQTT, or vendor sources can be added later.

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

For a live session, each incoming sample is also recorded with source,
received, and processing timestamps. Raw records are kept separately from
normalized samples. Technical failures are persisted as structured events with
review state and recovery information rather than being reduced to a current
status label.

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
