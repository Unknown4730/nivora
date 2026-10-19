"""Append-oriented SQLite recorder for live sessions."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

from .models import FailureEvent, LiveEvent, LiveSample


class StorageError(RuntimeError):
    """A bounded, actionable local persistence error."""


def default_data_dir() -> Path:
    configured = os.getenv("AURA_MED_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    # backend/.runtime is project-local and can be safely ignored by a caller's
    # repository policy without relying on an absolute machine path.
    return Path(__file__).resolve().parents[2] / ".runtime"


def default_db_path() -> Path:
    return default_data_dir() / "aura_med.sqlite3"


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise StorageError(f"record is not JSON serializable: {error}") from error


class SQLiteRecorder:
    """Thread-safe SQLite WAL recorder.

    Each table is append-oriented.  Updating review state is an explicit new
    ledger row rather than destructive mutation of raw/sample history.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        db_path: str | Path | None = None,
        data_dir: str | Path | None = None,
    ) -> None:
        if path is not None and db_path is not None:
            raise ValueError("pass path or db_path, not both")
        if db_path is not None:
            path = db_path
        if path is not None and data_dir is not None:
            raise ValueError("pass a database path or data_dir, not both")
        if path is None:
            path = Path(data_dir) / "aura_med.sqlite3" if data_dir is not None else default_db_path()
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        try:
            self._connection = sqlite3.connect(self.path, check_same_thread=False, timeout=5.0)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._create_schema()
        except sqlite3.Error as error:
            raise StorageError(f"unable to initialize SQLite recorder: {error}") from error

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    metadata_json TEXT NOT NULL,
                    created_timestamp REAL NOT NULL,
                    updated_timestamp REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS raw_records (
                    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    record_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_timestamp REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS raw_records_session ON raw_records(session_id, record_id);
                CREATE TABLE IF NOT EXISTS samples (
                    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    sample_json TEXT NOT NULL,
                    source_timestamp REAL NOT NULL,
                    received_timestamp REAL NOT NULL,
                    created_timestamp REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS samples_session ON samples(session_id, record_id);
                CREATE TABLE IF NOT EXISTS failures (
                    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    failure_id TEXT NOT NULL,
                    failure_type TEXT NOT NULL,
                    failure_json TEXT NOT NULL,
                    created_timestamp REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS failures_session ON failures(session_id, record_id);
                CREATE TABLE IF NOT EXISTS events (
                    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_timestamp REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_session ON events(session_id, record_id);
                CREATE TABLE IF NOT EXISTS review_flags (
                    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    flag TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_timestamp REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS summaries (
                    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_timestamp REAL NOT NULL
                );
                """
            )

    def _execute(self, sql: str, parameters: tuple[Any, ...]) -> int:
        try:
            with self._lock, self._connection:
                cursor = self._connection.execute(sql, parameters)
                return int(cursor.lastrowid or 0)
        except (sqlite3.Error, StorageError) as error:
            raise StorageError(f"SQLite append failed: {error}") from error

    def record_session(self, session_id: str, metadata: dict[str, Any]) -> None:
        now = time.time()
        payload = _json(metadata)
        self._execute(
            "INSERT OR REPLACE INTO sessions(session_id, metadata_json, created_timestamp, updated_timestamp) "
            "VALUES (?, ?, COALESCE((SELECT created_timestamp FROM sessions WHERE session_id = ?), ?), ?)",
            (session_id, payload, session_id, now, now),
        )

    def update_session(self, session_id: str, metadata: dict[str, Any]) -> None:
        self.record_session(session_id, metadata)

    def record_raw(self, session_id: str, record_type: str, payload: Any) -> int:
        return self._execute(
            "INSERT INTO raw_records(session_id, record_type, payload_json, created_timestamp) VALUES (?, ?, ?, ?)",
            (session_id, record_type, _json(payload), time.time()),
        )

    def record_sample(self, sample: LiveSample | dict[str, Any]) -> int:
        model = sample if isinstance(sample, LiveSample) else LiveSample.model_validate(sample)
        return self._execute(
            "INSERT INTO samples(session_id, sequence_number, sample_json, source_timestamp, received_timestamp, created_timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                model.session_id,
                model.sequence_number,
                _json(model.to_dict()),
                model.source_timestamp,
                model.received_timestamp,
                time.time(),
            ),
        )

    def record_failure(self, failure: FailureEvent | dict[str, Any]) -> int:
        model = failure if isinstance(failure, FailureEvent) else FailureEvent.model_validate(failure)
        return self._execute(
            "INSERT INTO failures(session_id, failure_id, failure_type, failure_json, created_timestamp) VALUES (?, ?, ?, ?, ?)",
            (model.session_id, model.failure_id, str(model.failure_type), _json(model.to_dict()), time.time()),
        )

    def record_event(self, event: LiveEvent | dict[str, Any]) -> int:
        model = event if isinstance(event, LiveEvent) else LiveEvent.model_validate(event)
        return self._execute(
            "INSERT INTO events(session_id, event_type, event_json, created_timestamp) VALUES (?, ?, ?, ?)",
            (model.session_id, model.event_type, _json(model.to_dict()), time.time()),
        )

    def record_review_flag(self, session_id: str, flag: str, detail: dict[str, Any] | None = None) -> int:
        return self._execute(
            "INSERT INTO review_flags(session_id, flag, detail_json, created_timestamp) VALUES (?, ?, ?, ?)",
            (session_id, flag, _json(detail or {}), time.time()),
        )

    def record_summary(self, session_id: str, summary: dict[str, Any]) -> int:
        return self._execute(
            "INSERT INTO summaries(session_id, summary_json, created_timestamp) VALUES (?, ?, ?)",
            (session_id, _json(summary), time.time()),
        )

    @staticmethod
    def _decode(rows: Iterable[sqlite3.Row], key: str) -> list[dict[str, Any]]:
        return [json.loads(row[key]) for row in rows]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT metadata_json FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return None if row is None else json.loads(row["metadata_json"])

    def get_samples(self, session_id: str) -> list[LiveSample]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT sample_json FROM samples WHERE session_id = ? ORDER BY record_id", (session_id,)
            ).fetchall()
        return [LiveSample.model_validate(json.loads(row["sample_json"])) for row in rows]

    def get_failures(self, session_id: str) -> list[FailureEvent]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT failure_json FROM failures WHERE session_id = ? ORDER BY record_id", (session_id,)
            ).fetchall()
        return [FailureEvent.model_validate(json.loads(row["failure_json"])) for row in rows]

    def get_events(self, session_id: str) -> list[LiveEvent]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT event_json FROM events WHERE session_id = ? ORDER BY record_id", (session_id,)
            ).fetchall()
        return [LiveEvent.model_validate(json.loads(row["event_json"])) for row in rows]

    def get_raw_records(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT record_type, payload_json, created_timestamp FROM raw_records WHERE session_id = ? ORDER BY record_id",
                (session_id,),
            ).fetchall()
        return [
            {"recordType": row["record_type"], "payload": json.loads(row["payload_json"]), "createdTimestamp": row["created_timestamp"]}
            for row in rows
        ]

    def get_latest_summary(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT summary_json FROM summaries WHERE session_id = ? ORDER BY record_id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return None if row is None else json.loads(row["summary_json"])

    def count(self, table: str, session_id: str | None = None) -> int:
        allowed = {"raw_records", "samples", "failures", "events", "review_flags", "summaries", "sessions"}
        if table not in allowed:
            raise ValueError("unsupported table")
        with self._lock:
            if session_id is None:
                row = self._connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
            else:
                row = self._connection.execute(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE session_id = ?", (session_id,)
                ).fetchone()
        return int(row["count"])

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    # Small verb aliases keep the recorder convenient for adapters without
    # duplicating any write/read behavior.
    write_raw = record_raw
    write_sample = record_sample
    write_failure = record_failure
    write_event = record_event
    read_samples = get_samples
    read_failures = get_failures
    read_events = get_events


__all__ = ["SQLiteRecorder", "StorageError", "default_data_dir", "default_db_path"]
