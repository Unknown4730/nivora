"""Phase 2 live/replay HTTP and WebSocket endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from ..live.export import build_export_zip, failures_csv, report_markdown, samples_csv
from ..live.session import SessionManager
from ..live.storage import StorageError
from .schemas import LiveFaultRequest, LiveSessionRequest


live_manager = SessionManager()
router = APIRouter(prefix="/api/v1/live", tags=["live"])


def _unknown(session_id: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Live session '{session_id}' was not found")


def _session_id_or_404(session_id: str) -> str:
    try:
        live_manager.get_session(session_id)
    except KeyError as error:
        raise _unknown(session_id) from error
    return session_id


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
@router.post("", status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_live_session(request: LiveSessionRequest) -> JSONResponse:
    try:
        payload = live_manager.create_session(**request.model_dump(exclude_none=True))
    except (TypeError, ValueError, StorageError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=jsonable_encoder(payload))


@router.get("/sessions/{session_id}")
def get_live_session(session_id: str) -> JSONResponse:
    _session_id_or_404(session_id)
    return JSONResponse(content=jsonable_encoder(live_manager.get_session(session_id)))


@router.get("/sessions")
def list_live_sessions(limit: int = 100) -> JSONResponse:
    """Return persisted sessions for frontend history and review screens."""

    try:
        sessions = live_manager.list_sessions(limit)
    except (TypeError, ValueError, StorageError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    return JSONResponse(content=jsonable_encoder({"sessions": sessions, "limit": min(limit, 500)}))


@router.post("/sessions/{session_id}/start")
async def start_live_session(session_id: str) -> JSONResponse:
    _session_id_or_404(session_id)
    try:
        payload = await live_manager.start(session_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    return JSONResponse(content=jsonable_encoder(payload))


@router.post("/sessions/{session_id}/stop")
async def stop_live_session(session_id: str) -> JSONResponse:
    _session_id_or_404(session_id)
    try:
        payload = await live_manager.stop(session_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    return JSONResponse(content=jsonable_encoder(payload))


@router.post("/sessions/{session_id}/faults")
@router.post("/sessions/{session_id}/inject-fault")
@router.post("/sessions/{session_id}/inject-faults")
def inject_live_fault(session_id: str, request: LiveFaultRequest) -> JSONResponse:
    _session_id_or_404(session_id)
    try:
        payload = live_manager.inject_fault(session_id, request)
    except (TypeError, ValueError, StorageError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    return JSONResponse(content=jsonable_encoder(payload))


@router.get("/sessions/{session_id}/report")
@router.get("/sessions/{session_id}/current-report")
def get_live_report(session_id: str) -> JSONResponse:
    _session_id_or_404(session_id)
    return JSONResponse(content=jsonable_encoder(live_manager.get_report(session_id)))


@router.get("/sessions/{session_id}/failures")
def get_live_failures(session_id: str) -> JSONResponse:
    _session_id_or_404(session_id)
    return JSONResponse(content=jsonable_encoder({"sessionId": session_id, "failures": live_manager.get_failures(session_id)}))


@router.get("/sessions/{session_id}/replay")
def replay_live_session(session_id: str) -> JSONResponse:
    _session_id_or_404(session_id)
    replay = live_manager.replay(session_id)
    samples = replay.samples()
    return JSONResponse(
        content=jsonable_encoder(
            {
                "sessionId": session_id,
                "sourceType": "replay",
                "sampleCount": len(samples),
                "samples": [sample.to_dict() for sample in samples],
            }
        )
    )


def _export_or_404(session_id: str) -> dict[str, Any]:
    _session_id_or_404(session_id)
    return live_manager.export_data(session_id)


@router.get("/sessions/{session_id}/export.json")
@router.get("/sessions/{session_id}/export")
def export_live_json(session_id: str) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(_export_or_404(session_id)))


@router.get("/sessions/{session_id}/export.zip")
def export_live_zip(session_id: str) -> Response:
    data = _export_or_404(session_id)
    return Response(
        content=build_export_zip(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{session_id}.zip"'},
    )


@router.get("/sessions/{session_id}/report.md")
def export_live_report(session_id: str) -> PlainTextResponse:
    data = _export_or_404(session_id)
    return PlainTextResponse(
        report_markdown(data["report"], data["metadata"]),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{session_id}-report.md"'},
    )


@router.get("/sessions/{session_id}/samples.csv")
def export_live_samples(session_id: str) -> PlainTextResponse:
    data = _export_or_404(session_id)
    return PlainTextResponse(
        samples_csv(data["samples"]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{session_id}-samples.csv"'},
    )


@router.get("/sessions/{session_id}/failures.csv")
def export_live_failures(session_id: str) -> PlainTextResponse:
    data = _export_or_404(session_id)
    return PlainTextResponse(
        failures_csv(data["failures"]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{session_id}-failures.csv"'},
    )


@router.websocket("/sessions/{session_id}/events")
async def live_events(websocket: WebSocket, session_id: str) -> None:
    try:
        queue = live_manager.subscribe(session_id)
    except KeyError:
        await websocket.close(code=4404, reason="live session not found")
        return
    await websocket.accept()
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event.to_dict())
            if event.event_type == "status" and event.payload.get("state") == "stopped":
                break
    except WebSocketDisconnect:
        pass
    finally:
        live_manager.unsubscribe(session_id, queue)


__all__ = ["live_manager", "router"]
