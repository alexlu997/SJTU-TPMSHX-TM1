"""Immutable model references shared by the three-module contracts."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


def freeze_value(value: Any) -> Any:
    """Copy nested contract data without retaining mutable caller state."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(freeze_value(item) for item in value)
    if hasattr(value, "setflags") and hasattr(value, "copy"):
        copied = value.copy()
        copied.setflags(write=False)
        return copied
    return deepcopy(value)


def freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return freeze_value(value)


@dataclass(frozen=True)
class ModelRef:
    """A resolvable, backend-neutral model resource declaration."""

    name: str
    version: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    applicability: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", freeze_mapping(self.parameters))

