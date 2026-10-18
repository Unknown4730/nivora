"""Pydantic request models for the versioned HTTP API.

The domain engine remains independent from FastAPI and Pydantic.  These models
are the boundary that turns untrusted JSON into a validated domain config.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class ServiceInfo(BaseModel):
    service: str
    version: str
    status: str


class ScenarioListResponse(BaseModel):
    scenarios: list[dict[str, object]]


class ErrorResponse(BaseModel):
    detail: str
