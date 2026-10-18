"""Stable JSON, CSV, and manifest exports for simulation runs."""

from __future__ import annotations

import json
from typing import Any

from .models import SimulatedSignalSample, SimulationRun, to_jsonable


def serialize_simulation_run(run: SimulationRun | dict[str, Any]) -> str:
    payload = run.to_dict() if isinstance(run, SimulationRun) else to_jsonable(run)
    return f"{json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)}\n"


def _sample_fields(sample: SimulatedSignalSample | dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    if isinstance(sample, SimulatedSignalSample):
        return sample.t_sec, sample.values
    return sample.get("tSec", sample.get("t_sec")), sample["values"]


def samples_to_csv(samples: list[SimulatedSignalSample] | list[dict[str, Any]]) -> str:
    lines = ["tSec,spo2Pct,heartRateBpm,respirationBpm"]
    for sample in samples:
        t_sec, values = _sample_fields(sample)
        lines.append(
            ",".join(
                str(item)
                if item is not None
                else ""
                for item in (t_sec, values.get("spo2"), values.get("heart-rate"), values.get("respiration"))
            )
        )
    return "\n".join(lines) + "\n"


def export_manifest(run: SimulationRun) -> dict[str, Any]:
    return {
        "schemaVersion": run.schema_version,
        "scenario": to_jsonable(run.scenario),
        "seed": run.seed,
        "algorithmNames": [result.algorithm_name for result in run.results],
        "timeline": to_jsonable(run.annotations),
        "benchmarkMetrics": {
            result.algorithm_id: to_jsonable(result.metrics) for result in run.results
        },
        "reasonCodes": [
            reason
            for result in run.results
            for output in result.outputs
            for reason in output.reason_codes
        ],
        "simulatedGroundTruth": to_jsonable(run.scenario.ground_truth),
    }
