"""Small process-local run store used until a persistence layer is selected."""

from __future__ import annotations

from collections import OrderedDict
from threading import RLock

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
