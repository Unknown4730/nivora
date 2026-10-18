"""Versioned API routes for simulation and reproducibility workflows."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, PlainTextResponse

from ..domain import (
    create_simulation_run,
    export_manifest,
    get_scenario_definition,
    samples_to_csv,
    serialize_simulation_run,
    to_jsonable,
)
from ..domain.pipeline import normalize_config
from .schemas import ExperimentRequest, ScenarioListResponse, SimulationRequest
from .store import InMemoryExperimentStore, InMemoryRunStore


SCENARIO_IDS = (
    "stable-baseline",
    "loose-spo2-sensor",
    "motion-artifact",
    "simulated-event",
    "gradual-deterioration",
    "multi-sensor-dropout",
)

router = APIRouter(prefix="/api/v1", tags=["simulations"])
run_store = InMemoryRunStore()
experiment_store = InMemoryExperimentStore()

# The experiment engine is intentionally not implemented in the API package.
# Keeping these names available also makes the boundary straightforward to
# replace in API tests while the engine package is developed independently.
run_experiment_batch: Callable[[dict[str, Any]], Any] | None = None
ALGORITHM_CATALOG: Any | None = None


def _load_experiment_runner() -> Callable[[dict[str, Any]], Any]:
    global run_experiment_batch
    if run_experiment_batch is None:
        try:
            module = importlib.import_module("aura_med.experiments")
        except ModuleNotFoundError as error:
            if error.name == "aura_med.experiments":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="The experiment engine is not available",
                ) from error
            raise
        candidate = getattr(module, "run_experiment_batch", None)
        if not callable(candidate):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The experiment engine does not expose run_experiment_batch",
            )
        run_experiment_batch = candidate
    return run_experiment_batch


def _load_algorithm_catalog() -> Any:
    global ALGORITHM_CATALOG
    if ALGORITHM_CATALOG is None:
        try:
            module = importlib.import_module("aura_med.experiments")
        except ModuleNotFoundError as error:
            if error.name == "aura_med.experiments":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="The experiment engine is not available",
                ) from error
            raise
        if not hasattr(module, "ALGORITHM_CATALOG"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The experiment engine does not expose ALGORITHM_CATALOG",
            )
        ALGORITHM_CATALOG = getattr(module, "ALGORITHM_CATALOG")
    return ALGORITHM_CATALOG


def _batch_payload(batch: Any) -> dict[str, Any]:
    to_dict = getattr(batch, "to_dict", None)
    if not callable(to_dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The experiment engine returned an invalid batch",
        )
    try:
        payload = to_dict()
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error) or "The experiment engine returned an invalid batch",
        ) from error
    if not isinstance(payload, Mapping):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The experiment engine returned an invalid batch",
        )
    return jsonable_encoder(dict(payload))


def _experiment_not_found(experiment_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Experiment '{experiment_id}' was not found in this process",
    )


def _not_found(run_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Simulation run '{run_id}' was not found in this process",
    )


@router.get("/scenarios", response_model=ScenarioListResponse)
def list_scenarios() -> ScenarioListResponse:
    """Return the complete scenario catalog used by the domain engine."""

    return ScenarioListResponse(
        scenarios=[
            to_jsonable(get_scenario_definition(scenario_id))
            for scenario_id in SCENARIO_IDS
        ]
    )


@router.get("/algorithms", tags=["experiments"])
def list_algorithms() -> JSONResponse:
    """Return the engine-owned, versioned algorithm catalog."""

    catalog = _load_algorithm_catalog()
    if isinstance(catalog, Mapping) and "algorithms" in catalog:
        payload = dict(catalog)
        payload.setdefault("schemaVersion", "1.0")
    else:
        payload = {"schemaVersion": "1.0", "algorithms": catalog}
    return JSONResponse(content=jsonable_encoder(payload))


@router.post(
    "/experiments",
    status_code=status.HTTP_201_CREATED,
    tags=["experiments"],
)
def create_experiment(request: ExperimentRequest) -> JSONResponse:
    """Run, store, and return one complete deterministic experiment batch."""

    runner = _load_experiment_runner()
    try:
        batch = runner(request.to_engine_spec())
        # Validate the engine result before putting it in the process-local
        # store so a malformed result cannot create an unreadable record.
        payload = _batch_payload(batch)
        experiment_store.put(batch)
    except HTTPException:
        raise
    except Exception as error:
        # The engine owns semantic validation.  Its validation failures must
        # remain client errors at this HTTP boundary rather than becoming 500s.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error) or "Invalid experiment specification",
        ) from error
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=payload)


@router.get("/experiments/{experiment_id}", tags=["experiments"])
def get_experiment(experiment_id: str) -> JSONResponse:
    """Read an experiment batch created by this process."""

    batch = experiment_store.get(experiment_id)
    if batch is None:
        raise _experiment_not_found(experiment_id)
    return JSONResponse(content=_batch_payload(batch))


@router.get("/experiments/{experiment_id}/manifest", tags=["experiments"])
def get_experiment_manifest(experiment_id: str) -> JSONResponse:
    """Return the reproducibility manifest emitted by the experiment engine."""

    batch = experiment_store.get(experiment_id)
    if batch is None:
        raise _experiment_not_found(experiment_id)

    payload = _batch_payload(batch)
    for key in ("manifest", "reproducibilityManifest", "reproducibility_manifest"):
        if key in payload:
            return JSONResponse(content=payload[key])

    manifest = getattr(batch, "manifest", None)
    if manifest is not None:
        return JSONResponse(content=jsonable_encoder(manifest))

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="The experiment batch does not contain a reproducibility manifest",
    )


@router.post("/simulations", status_code=status.HTTP_201_CREATED)
def create_simulation(request: SimulationRequest) -> JSONResponse:
    """Create, store, and return one deterministic simulation run."""

    try:
        # Normalize once at the API boundary so callers receive a clear 422 for
        # domain-level validation errors rather than a server error.
        config = normalize_config(request.to_domain_config())
        run = run_store.put(create_simulation_run(config))
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=run.to_dict())


@router.get("/simulations/{run_id}")
def get_simulation(run_id: str) -> JSONResponse:
    """Read a run created by this process."""

    run = run_store.get(run_id)
    if run is None:
        raise _not_found(run_id)
    return JSONResponse(content=run.to_dict())


@router.get("/simulations/{run_id}/manifest")
def get_simulation_manifest(run_id: str) -> JSONResponse:
    run = run_store.get(run_id)
    if run is None:
        raise _not_found(run_id)
    return JSONResponse(content=export_manifest(run))


@router.get("/simulations/{run_id}/samples.csv")
def get_simulation_samples_csv(run_id: str) -> Response:
    run = run_store.get(run_id)
    if run is None:
        raise _not_found(run_id)
    return PlainTextResponse(
        content=samples_to_csv(run.samples),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{run.run_id}.csv"'},
    )


@router.get("/simulations/{run_id}/run.json")
def get_simulation_json(run_id: str) -> Response:
    run = run_store.get(run_id)
    if run is None:
        raise _not_found(run_id)
    return PlainTextResponse(
        content=serialize_simulation_run(run),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{run.run_id}.json"'},
    )
