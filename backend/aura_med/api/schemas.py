"""Pydantic request models for the versioned HTTP API.

The domain engine remains independent from FastAPI and Pydantic.  These models
are the boundary that turns untrusted JSON into a validated domain config.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from ..live.models import FaultSpec


AlgorithmId = Literal["threshold-baseline", "reliability-aware"]


class SimulationRequest(BaseModel):
    """Validated configuration accepted by ``POST /api/v1/simulations``."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    scenario: str = "stable-baseline"
    duration_sec: int = Field(60, alias="durationSec", gt=0)
    sample_rate_hz: int = Field(1, alias="sampleRateHz", gt=0)
    artifact_intensity: float = Field(0.48, alias="artifactIntensity", ge=0, le=1)
    algorithms: list[AlgorithmId] = Field(
        default_factory=lambda: ["threshold-baseline", "reliability-aware"]
    )
    seed: int = 20261018
    initial_trust: float = Field(0.8, alias="initialTrust", ge=0, le=1)
    quality_window_samples: int = Field(8, alias="qualityWindowSamples", gt=0)
    baseline_window_samples: int = Field(8, alias="baselineWindowSamples", gt=0)
    required_persistence_samples: int = Field(3, alias="requiredPersistenceSamples", gt=0)

    def to_domain_config(self) -> dict[str, object]:
        """Return the normalized snake_case shape expected by the domain."""

        return self.model_dump()


NonEmptyString = Annotated[StrictStr, Field(min_length=1)]


class ExperimentRequest(BaseModel):
    """Transport-level request for one deterministic experiment batch.

    The experiment engine owns semantic validation (for example, whether a
    scenario or algorithm exists).  This model only validates the shape that
    can cross the HTTP boundary and rejects accidental extra fields.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    suite_id: NonEmptyString = Field(alias="suiteId")
    scenarios: list[NonEmptyString] = Field(min_length=1)
    seeds: list[StrictInt] = Field(min_length=1)
    base_config: dict[str, Any] = Field(default_factory=dict, alias="baseConfig")
    algorithms: list[NonEmptyString] = Field(min_length=1)

    def to_engine_spec(self) -> dict[str, Any]:
        """Return the stable snake_case mapping consumed by the engine."""

        return self.model_dump()


class ServiceInfo(BaseModel):
    service: str
    version: str
    status: str


class ScenarioListResponse(BaseModel):
    scenarios: list[dict[str, object]]


class ErrorResponse(BaseModel):
    detail: str


class LiveSessionRequest(BaseModel):
    """Validated configuration for a virtual/replay live session."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    session_id: str | None = Field(default=None, alias="sessionId", min_length=1)
    stream_id: str = Field(default="stream-1", alias="streamId", min_length=1)
    sensor_id: str = Field(default="virtual-sensor-1", alias="sensorId", min_length=1)
    scenario: str = "stable-baseline"
    duration_sec: float = Field(default=10.0, alias="durationSec", gt=0)
    sample_rate_hz: float = Field(default=1.0, alias="sampleRateHz", gt=0)
    speed: float = Field(default=1.0, gt=0)
    seed: int = 20261018
    artifact_intensity: float = Field(default=0.48, alias="artifactIntensity", ge=0, le=1)
    faults: list[FaultSpec] | dict[str, Any] = Field(default_factory=list)
    fault_injection: dict[str, Any] | None = Field(default=None, alias="faultInjection")
    no_wait: bool = Field(default=True, alias="noWait")


class LiveFaultRequest(FaultSpec):
    """Fault injection body; kept as a named API schema for OpenAPI clients."""
