"""Deterministic pseudo-random, hashing, and numeric helpers."""

from __future__ import annotations

import json
import math
from typing import Any, Callable


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return min(maximum, max(minimum, value))


def _uint32(value: int) -> int:
    return value & 0xFFFFFFFF


def create_seeded_random(seed: int) -> Callable[[], float]:
    """Return the same Mulberry32-style stream used by the JavaScript engine."""

    state = _uint32(int(seed)) or 0x9E3779B9

    def next_random() -> float:
        nonlocal state
        state = _uint32(state + 0x6D2B79F5)
        value = _uint32((state ^ (state >> 15)) * (1 | state))
        value = _uint32(value ^ _uint32(value + _uint32((value ^ (value >> 7)) * (61 | value))))
        return _uint32(value ^ (value >> 14)) / 4294967296

    return next_random


def _json_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def stable_hash(value: Any) -> str:
    """Compute the original eight-character FNV-1a hash.

    JavaScript iterates UTF-16 code units with ``charCodeAt``.  Encoding as
    UTF-16 little-endian preserves that behavior for non-BMP characters too.
    """

    text = _json_string(value)
    encoded = text.encode("utf-16-le", errors="surrogatepass")
    hash_value = 2166136261
    for index in range(0, len(encoded), 2):
        code_unit = encoded[index] | (encoded[index + 1] << 8)
        hash_value = _uint32((hash_value ^ code_unit) * 16777619)
    return f"{hash_value:08x}"


def round_value(value: float, decimals: int = 6) -> float:
    """Round like ``Math.round(value * factor) / factor`` in JavaScript."""

    factor = 10**decimals
    return math.floor(value * factor + 0.5) / factor


# A short compatibility alias for callers that prefer the JS module name.
round = round_value
