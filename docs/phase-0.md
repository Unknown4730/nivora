# Phase 0 implementation record

## Goal

Replace the JavaScript processing engine with a Python backend, expose it
through FastAPI, preserve deterministic research behavior, and fix the
sample-rate interval correctness issue before frontend migration.

## Acceptance criteria

- Python domain pipeline produces deterministic runs for the same config/seed.
- Invalid configuration is rejected explicitly.
- Output windows use the configured sample interval and stay inside the run.
- Ground truth, evidence, predictions, metrics, and explanations remain
  separate in the serialized run.
- FastAPI can create, read, and export a run.
- The repository has a pinned Python runtime, dependency lock file, Dockerfile,
  README setup/run/test/deploy instructions, and a single backend test command.
- Frontend code is not executed or migrated in this phase.

Frontend-specific findings from the previous audit, including the old browser
prototype's reset and comparison-view issues, are intentionally deferred until
the React/Tailwind client is requested. The archived JavaScript files are not
part of the active backend runtime.

## Verification record

The domain migration was verified with:

```text
python -m compileall -q backend/aura_med
python -m unittest discover -s backend/tests/domain -p "test_*.py"
```

The API test suite is run with the same unittest discovery command after the
project-local dependencies are installed:

```text
PYTHONPATH=backend python -m unittest discover -s backend/tests -p "test_*.py"
```

## Explicit non-goals

- React/Tailwind implementation
- real patient data
- device or Bluetooth integration
- durable persistence
- authentication and organization management
- clinical validation or regulatory claims
