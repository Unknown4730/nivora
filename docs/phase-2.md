# Phase 2 implementation record

## Goal

Provide a working real-time laboratory workflow without requiring physical
hardware: a deterministic virtual sensor stream, durable session recording,
failure forensics, replay, exportable reports, and a readable React dashboard.

The virtual source is deliberately a hardware-ready boundary. Future LSL,
serial, BLE, MQTT, or vendor adapters can emit the same canonical live sample
model without changing the storage, failure, streaming, or UI contracts.

## What is implemented

### Live session backend

- Virtual sensor source derived from the existing domain scenarios.
- Wall-clock or accelerated delivery pacing.
- Session lifecycle: `created`, `streaming`, `degraded`, `reconnecting`,
  `stopped`, and `failed`.
- Bounded hot sample cache for low-latency state.
- WebSocket events for status, samples, quality, algorithm state, failures, and
  recovery.

### Failure injection and forensics

The virtual source can inject:

- packet loss;
- duplicates;
- out-of-order samples;
- missing channel values;
- out-of-range values;
- jitter and delivery delay;
- disconnect/reconnect events.

The failure ledger records technical event type, session, sensor, affected
channels, relative time, observed and expected values, severity, detector
version, review state, context, and recovery status. Failure records are not
silently discarded when they are inconvenient or brief.

Technical review flags are intentionally not clinical diagnoses. Plain-language
messages say things such as “The stream lost samples briefly; the system marked
the window uncertain.”

### Durable cache and exports

SQLite with WAL mode is the local durable source of truth. The data directory is
configured with `AURA_MED_DATA_DIR` and defaults to the ignored
`backend/.runtime/` directory. The bounded in-memory cache is only the live
working set; raw records, normalized samples, failures, quality events,
algorithm events, summaries, and review flags are persisted.

Session exports include:

```text
manifest.json
session-report.md
session-report.json
session-metadata.json
sensor-metadata.json
normalized-samples.csv
failure-events.json
failure-events.csv
quality-events.json
algorithm-events.json
raw-records.json
checksums.json
```

The ZIP export is replay-oriented and includes the non-clinical research note.
Recorded samples can be replayed through the backend source boundary.

### Non-technical-professional frontend

The React/Tailwind dashboard presents:

- “Stream healthy”, “Some readings are missing”, “Connection interrupted”, and
  “Review recommended” status language;
- live SpO₂, heart-rate, and respiration cards;
- a plain-English “What is happening?” panel;
- a live SVG signal chart;
- a review timeline with friendly failure titles;
- expandable engineer-only technical details;
- report, ZIP, samples CSV, and failures CSV exports;
- explicit research/non-clinical wording.

The frontend formats backend-derived fields. It does not recompute quality,
trust, classification, or failure decisions.

## API

```text
POST /api/v1/live/sessions
GET  /api/v1/live/sessions/{session_id}
POST /api/v1/live/sessions/{session_id}/start
POST /api/v1/live/sessions/{session_id}/stop
POST /api/v1/live/sessions/{session_id}/faults
GET  /api/v1/live/sessions/{session_id}/report
GET  /api/v1/live/sessions/{session_id}/failures
GET  /api/v1/live/sessions/{session_id}/export.zip
GET  /api/v1/live/sessions/{session_id}/report.md
GET  /api/v1/live/sessions/{session_id}/samples.csv
GET  /api/v1/live/sessions/{session_id}/failures.csv
WS   /api/v1/live/sessions/{session_id}/events
```

The API also preserves all Phase 0 simulation and Phase 1 experiment routes.

## Run the complete local system

Start the backend from the repository root:

```text
PYTHONPATH=backend .venv/Scripts/python.exe -m uvicorn aura_med.api.main --host 127.0.0.1 --port 8000
```

In another terminal, start the frontend:

```text
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`, create a virtual session, start it, inspect the
live stream, and use a fault profile to produce a review event. End the session
to enable the report and export links.

## Verification

Backend:

```text
PYTHONPATH=backend .venv/Scripts/python.exe -m compileall -q backend
PYTHONPATH=backend .venv/Scripts/python.exe -m unittest discover -s backend/tests -p "test_*.py"
```

Frontend:

```text
cd frontend
npm ci
npm test
npm run build
```

The backend suite covers lifecycle, failure types, recovery, SQLite isolation,
exports, replay equivalence, API endpoints, WebSocket delivery, and a bounded
thousands-of-samples stress case. The frontend suite uses deterministic API and
event contract tests; a real browser automation dependency is intentionally not
included in this compact phase.

## Explicit limits

- No physical sensor is required or claimed to be integrated.
- No BLE, serial, LSL, MQTT, or vendor protocol adapter is enabled yet.
- The default source is virtual/replay data, not patient data.
- SQLite storage is local and not a multi-user or production persistence layer.
- Technical review flags are not clinical risk scores or diagnoses.
- Authentication, encryption at rest, retention governance, and patient-data
  controls are required before real human data is used.
