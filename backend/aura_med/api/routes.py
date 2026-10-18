"""Versioned API routes for simulation and reproducibility workflows."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
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
from .schemas import ScenarioListResponse, SimulationRequest
from .store import InMemoryRunStore


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
