"""Immutable model references shared by the three-module contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np


def freeze_value(value: Any) -> Any:
    """Detach portable data; reject runtime objects at every nesting level.

    Arrays own an immutable bytes buffer, so consumers cannot re-enable
    writes to a shared case or result. NaN remains legal diagnostic data.
    """
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if isinstance(value, np.generic):
        return freeze_value(value.item())
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("contract mapping keys must be strings")
        return MappingProxyType({key: freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_value(item) for item in value)
    if isinstance(value, np.ndarray):
        if value.dtype.kind not in "biuf":
            raise TypeError("contract arrays must contain real numbers or booleans, not objects")
        return np.frombuffer(value.tobytes(), dtype=value.dtype).reshape(value.shape)
    raise TypeError("contract data cannot contain callables or runtime objects")


def freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("contract field must be a mapping")
    return freeze_value(value)


@dataclass(frozen=True)
class ModelRef:
    """A resolvable, backend-neutral model resource declaration."""

    name: str
    version: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    applicability: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.version:
            raise ValueError("ModelRef requires a name and a version")
        object.__setattr__(self, "parameters", freeze_mapping(self.parameters))
