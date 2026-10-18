"""Small process-local run store used until a persistence layer is selected."""

from __future__ import annotations

from collections import OrderedDict
from threading import RLock
from typing import Any

from ..domain.models import SimulationRun


class InMemoryRunStore:
    """Bounded, thread-safe storage for API-created runs.

    This is intentionally not presented as durable persistence.  It gives the
    current stateless backend a useful read-after-create workflow without
    introducing a database before the data and governance requirements are
    decided.
    """

    def __init__(self, max_runs: int = 128) -> None:
        if max_runs <= 0:
            raise ValueError("max_runs must be positive")
        self._max_runs = max_runs
        self._runs: OrderedDict[str, SimulationRun] = OrderedDict()
        self._lock = RLock()

    def put(self, run: SimulationRun) -> SimulationRun:
        with self._lock:
            self._runs.pop(run.run_id, None)
            self._runs[run.run_id] = run
            while len(self._runs) > self._max_runs:
                self._runs.popitem(last=False)
        return run

    def get(self, run_id: str) -> SimulationRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()


class InMemoryExperimentStore:
    """Bounded, thread-safe process-local storage for experiment batches.

    The store deliberately depends only on the engine boundary: an experiment
    batch must expose an ``experiment_id`` attribute.  Keeping that boundary
    loose lets the API use the engine's result type without importing or
    reimplementing experiment-domain models.
    """

    def __init__(self, max_experiments: int = 128) -> None:
        if max_experiments <= 0:
            raise ValueError("max_experiments must be positive")
        self._max_experiments = max_experiments
        self._experiments: OrderedDict[str, Any] = OrderedDict()
        self._lock = RLock()

    def put(self, batch: Any) -> Any:
        experiment_id = getattr(batch, "experiment_id", None)
        if not isinstance(experiment_id, str) or not experiment_id:
            raise ValueError("experiment batch must expose a non-empty experiment_id")
        with self._lock:
            self._experiments.pop(experiment_id, None)
            self._experiments[experiment_id] = batch
            while len(self._experiments) > self._max_experiments:
                self._experiments.popitem(last=False)
        return batch

    def get(self, experiment_id: str) -> Any | None:
        with self._lock:
            return self._experiments.get(experiment_id)

    def clear(self) -> None:
        """Reset all batches; intentionally public for API test isolation."""

        with self._lock:
            self._experiments.clear()

    reset = clear
