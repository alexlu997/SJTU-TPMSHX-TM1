"""Qt-free computation contracts and input validation.

Case/result contracts, runtime controls, units and physical-input validation
live in this package. UI code supplies scalar/dict values and presents the
returned findings; domain helpers never read widgets or decide GUI behavior.

This module exports the current geometry, port and unit-conversion helpers. Fixed geometry/D-F coverage is distinct from the selected
Nu correlation, experimental correction and property-envelope checks.
"""
from __future__ import annotations

from .validator import (
    validate_geometry,
    compute_volumetric_htc,
    wall_for_dir,
    cross_axes_for_dir,
    parse_unit_value,
    validate_pipe_config,
    geometry_extrapolation_warning,
    Warning as DomainWarning,
)

__all__ = [
    'validate_geometry',
    'compute_volumetric_htc',
    'wall_for_dir',
    'cross_axes_for_dir',
    'parse_unit_value',
    'validate_pipe_config',
    'geometry_extrapolation_warning',
    'DomainWarning',
]
