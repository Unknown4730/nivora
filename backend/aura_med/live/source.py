"""Deterministic virtual and recorded replay sources."""

from __future__ import annotations

import asyncio
import copy
import math
import random
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any, AsyncIterator, Iterable

from ..domain.generator import generate_simulated_signals
from ..domain.scenarios import SIGNAL_META
from .models import FaultSpec, LiveSample, QualityFlag, SourceType


@dataclass(frozen=True)
class SourceItem:
    """One item emitted by a source worker."""

    kind: str
    sample: LiveSample | None = None
    event_type: str | None = None
    payload: dict[str, Any] | None = None


def _as_fault(value: FaultSpec | dict[str, Any] | str) -> FaultSpec:
    if isinstance(value, FaultSpec):
        return value
    if isinstance(value, str):
        return FaultSpec(type=value)
    return FaultSpec.model_validate(value)


def _fault_list(values: Iterable[FaultSpec | dict[str, Any] | str] | Mapping[str, Any] | None) -> list[FaultSpec]:
    if values is None:
        return []
    if isinstance(values, Mapping):
        result: list[FaultSpec] = []
        for fault_type, recipe in values.items():
            if isinstance(recipe, Mapping):
                result.append(_as_fault({"type": fault_type, **dict(recipe)}))
            elif isinstance(recipe, list):
                result.append(_as_fault({"type": fault_type, "atSamples": recipe}))
            elif recipe:
                result.append(_as_fault({"type": fault_type}))
        return result
    return [_as_fault(item) for item in values]


class VirtualSource:
    """Replay the Phase 1 deterministic domain samples as a live stream.

    The source never uses wall-clock time to construct a sample.  Wall-clock
    pacing is only an optional delivery concern, so ``no_wait=True`` gives
    exact, fast, deterministic test runs.
    """

    def __init__(
        self,
        session_id: str,
        stream_id: str = "stream-1",
        sensor_id: str = "virtual-sensor-1",
        *,
        scenario: str = "stable-baseline",
        sample_rate_hz: float = 1.0,
        duration_sec: float = 10.0,
        speed: float = 1.0,
        seed: int = 20261018,
        artifact_intensity: float = 0.48,
        faults: Iterable[FaultSpec | dict[str, Any] | str] | Mapping[str, Any] | None = None,
        fault_injection: Iterable[FaultSpec | dict[str, Any] | str] | Mapping[str, Any] | None = None,
        no_wait: bool = True,
    ) -> None:
        if not session_id or not stream_id or not sensor_id:
            raise ValueError("session_id, stream_id, and sensor_id are required")
        if sample_rate_hz <= 0 or not math.isfinite(sample_rate_hz):
            raise ValueError("sample_rate_hz must be greater than zero")
        if duration_sec <= 0 or not math.isfinite(duration_sec):
            raise ValueError("duration_sec must be greater than zero")
        if speed <= 0 or not math.isfinite(speed):
            raise ValueError("speed must be greater than zero")
        self.session_id = session_id
        self.stream_id = stream_id
        self.sensor_id = sensor_id
        self.scenario = scenario
        self.sample_rate_hz = float(sample_rate_hz)
        self.duration_sec = float(duration_sec)
        self.speed = float(speed)
        self.seed = int(seed)
        self.artifact_intensity = float(artifact_intensity)
        self.no_wait = bool(no_wait)
        self._faults: list[FaultSpec] = _fault_list(faults)
        self._faults.extend(_fault_list(fault_injection))
        self._cancelled = False

    @property
    def faults(self) -> list[FaultSpec]:
        return list(self._faults)

    def add_fault(self, fault: FaultSpec | dict[str, Any] | str) -> FaultSpec:
        parsed = _as_fault(fault)
        self._faults.append(parsed)
        return parsed

    def cancel(self) -> None:
        self._cancelled = True

    def _fault_applies(self, fault: FaultSpec, index: int, randomizer: random.Random) -> bool:
        if fault.start_sample is not None and index < fault.start_sample:
            return False
        end_sample = fault.end_sample
        if end_sample is None and fault.start_sample is not None and fault.duration_samples is not None:
            end_sample = fault.start_sample + fault.duration_samples
        if end_sample is None and fault.start_sample is not None and fault.count is not None:
            end_sample = fault.start_sample + fault.count
        if end_sample is not None and index >= end_sample:
            return False
        if fault.start_sample is not None:
            return True
        if fault.at_samples and index in fault.at_samples:
            return True
        if fault.every is not None and index % fault.every == 0:
            return True
        if fault.probability is not None and randomizer.random() < fault.probability:
            return True
        return False

    def _active(self, fault: FaultSpec, index: int) -> bool:
        return fault.start_sample is not None and self._fault_applies(fault, index, random.Random(self.seed + index))

    def _faults_for(self, fault_type: str) -> list[FaultSpec]:
        return [fault for fault in self._faults if fault.type == fault_type]

    def _base_samples(self) -> list[LiveSample]:
        generated = generate_simulated_signals(
            {
                "scenario": self.scenario,
                "duration_sec": self.duration_sec,
                "sample_rate_hz": self.sample_rate_hz,
                "artifact_intensity": self.artifact_intensity,
                "seed": self.seed,
            }
        )
        # The domain intentionally retains its terminal inspection sample.  A
        # live stream emits only scheduled instants before the duration bound.
        source_samples = generated.samples[: max(1, len(generated.samples) - 1)]
        units = {signal.channel: signal.unit for signal in generated.signals}
        return [
            LiveSample(
                session_id=self.session_id,
                stream_id=self.stream_id,
                sensor_id=self.sensor_id,
                sample_id=f"sample-{index:08d}",
                sequence_number=index,
                source_timestamp=float(item.t_sec),
                received_timestamp=float(item.t_sec),
                processing_timestamp=float(item.t_sec),
                relative_time_sec=float(item.t_sec),
                values=dict(item.values),
                units=units,
                source_type=SourceType.VIRTUAL,
            )
            for index, item in enumerate(source_samples)
        ]

    def _transform(self, base: list[LiveSample]) -> list[SourceItem]:
        randomizer = random.Random(self.seed ^ 0xA17A)
        packet_loss = self._faults_for("packet_loss")
        duplicates = self._faults_for("duplicates") + self._faults_for("duplicate_packets")
        out_of_order = self._faults_for("out_of_order")
        missing = self._faults_for("missing_values")
        out_of_range = self._faults_for("out_of_range")
        jitter = self._faults_for("jitter_delay")
        disconnect = self._faults_for("disconnect_reconnect")

        # Apply value faults and packet omissions first, retaining the original
        # sequence number so detectors can explain every gap.
        prepared: list[tuple[int, LiveSample]] = []
        disconnect_indices: set[int] = set()
        for index, original in enumerate(base):
            disconnected = any(
                self._fault_applies(fault, index, randomizer) or self._active(fault, index)
                for fault in disconnect
            )
            if disconnected:
                disconnect_indices.add(index)
                continue
            if any(self._fault_applies(fault, index, randomizer) for fault in packet_loss):
                continue

            sample = original
            flags: list[str] = []
            values = dict(sample.values)
            channels = set(channel for fault in missing for channel in fault.channels) or set(values)
            if any(self._fault_applies(fault, index, randomizer) for fault in missing):
                for channel in channels:
                    if channel in values:
                        values[channel] = None
                flags.append(QualityFlag.MISSING.value)
            channels = set(channel for fault in out_of_range for channel in fault.channels) or set(values)
            if any(self._fault_applies(fault, index, randomizer) for fault in out_of_range):
                for channel in channels:
                    if channel in values:
                        minimum, maximum = SIGNAL_META.get(channel, {}).get("plausibility", (-1e6, 1e6))
                        values[channel] = float(maximum + 10)
                flags.append(QualityFlag.OUT_OF_RANGE.value)
            delay = 0.0
            if any(self._fault_applies(fault, index, randomizer) for fault in jitter):
                delays = [fault.delay_sec for fault in jitter if self._fault_applies(fault, index, randomizer)]
                delay = max(delays or [0.0])
                if delay <= 0:
                    delay = 0.25 / self.sample_rate_hz
                flags.append(QualityFlag.DELAYED.value)
            if flags:
                sample = sample.model_copy(
                    update={
                        "values": values,
                        "quality_flags": sorted(set(sample.quality_flags + flags)),
                        "received_timestamp": sample.source_timestamp + delay,
                        "processing_timestamp": sample.source_timestamp + delay,
                    }
                )
            prepared.append((index, sample))

        # Reordering is a deterministic adjacent swap.  The payload's sequence
        # remains authoritative, allowing the detector to identify the issue.
        if out_of_order:
            swapped: list[tuple[int, LiveSample]] = []
            index = 0
            while index < len(prepared):
                if index + 1 < len(prepared) and any(
                    self._fault_applies(fault, prepared[index][0], randomizer) for fault in out_of_order
                ):
                    swapped.extend([prepared[index + 1], prepared[index]])
                    index += 2
                else:
                    swapped.append(prepared[index])
                    index += 1
            prepared = swapped

        result: list[SourceItem] = []
        disconnect_reported = False
        reconnect_reported = False
        for index, sample in prepared:
            if disconnect_indices and any(missing < index for missing in disconnect_indices):
                first_missing = min(missing for missing in disconnect_indices if missing < index)
                if not disconnect_reported:
                    result.append(SourceItem("event", event_type="disconnect", payload={"sequenceNumber": first_missing}))
                    disconnect_reported = True
                if not reconnect_reported:
                    result.append(SourceItem("event", event_type="reconnect", payload={"sequenceNumber": index}))
                    reconnect_reported = True
            result.append(SourceItem("sample", sample=sample))
            if any(self._fault_applies(fault, index, randomizer) for fault in duplicates):
                duplicate = sample.model_copy(
                    update={"quality_flags": sorted(set(sample.quality_flags + [QualityFlag.DUPLICATE.value]))}
                )
                result.append(SourceItem("sample", sample=duplicate))
        # A disconnect extending to the end is still explicit for reports.
        if disconnect_indices and not disconnect_reported:
            first_missing = min(disconnect_indices)
            result.append(SourceItem("event", event_type="disconnect", payload={"sequenceNumber": first_missing, "atEnd": True}))
        elif disconnect_indices and not reconnect_reported:
            result.append(SourceItem("event", event_type="disconnect", payload={"atEnd": True}))
        return result

    def items(self) -> list[SourceItem]:
        return self._transform(self._base_samples())

    def samples(self) -> list[LiveSample]:
        return [item.sample for item in self.items() if item.sample is not None]

    generate_samples = samples

    async def aiter_items(self) -> AsyncIterator[SourceItem]:
        previous_time = 0.0
        for item in self.items():
            if self._cancelled:
                return
            if not self.no_wait and item.sample is not None:
                elapsed = max(0.0, item.sample.source_timestamp - previous_time)
                if elapsed:
                    await asyncio.sleep(elapsed / self.speed)
                previous_time = item.sample.source_timestamp
            # Yield control even in accelerated mode so producer/worker tasks
            # never monopolize the FastAPI event loop.
            await asyncio.sleep(0)
            yield item

    async def aiter_samples(self) -> AsyncIterator[LiveSample]:
        async for item in self.aiter_items():
            if item.sample is not None:
                yield item.sample

    def __iter__(self):
        return iter(self.samples())


class ReplaySource:
    """Source that reproduces normalized samples from a recorder."""

    def __init__(self, samples: Iterable[LiveSample | dict[str, Any]], *, no_wait: bool = True, speed: float = 1.0):
        self._samples = [
            item if isinstance(item, LiveSample) else LiveSample.model_validate(item)
            for item in samples
        ]
        self.no_wait = no_wait
        self.speed = speed
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def samples(self) -> list[LiveSample]:
        return [sample.model_copy(deep=True, update={"source_type": SourceType.REPLAY}) for sample in self._samples]

    async def aiter_items(self) -> AsyncIterator[SourceItem]:
        previous = 0.0
        for sample in self._samples:
            if self._cancelled:
                return
            if not self.no_wait:
                await asyncio.sleep(max(0.0, sample.source_timestamp - previous) / self.speed)
            previous = sample.source_timestamp
            await asyncio.sleep(0)
            yield SourceItem(
                "sample",
                sample=sample.model_copy(deep=True, update={"source_type": SourceType.REPLAY}),
            )


__all__ = ["ReplaySource", "SourceItem", "VirtualSource"]
