"""Shared output-schema contract for structured grid-array builders.

Two builders emit the same per-cell property dict consumed by the 2D
compute path (``pipelines/stages_2d.py``) and the optimizer:

  * ``zone_config.ZoneConfig.build_structured_arrays``  (UI zone table)
  * ``continuous_field.ContinuousFieldConfig.build_grid_arrays``
    (optimizer decision vector)

They are intentionally separate implementations (zone replication vs
unique-pair scatter); this module only pins their OUTPUT contract so a
key added to one builder cannot silently go missing from the other
(refactor B1 1.6, 2026-06-12). Extra builder-specific keys
(``zone_params``, ``L_field`` …) are allowed and not validated.
"""
from __future__ import annotations

import numpy as np

# Core per-cell property arrays every builder must emit, shape (Nx, Ny),
# dtype float64. Consumed by _run_solvers / SIMPLE closure overrides.
GRID_ARRAY_KEYS = (
    'eps_arr', 'eps_f_arr',
    'K_ffA_arr', 'K_ffB_arr', 'K_ss_arr',
    'h_vA_arr', 'h_vB_arr',
    'r_h_arr', 'A_0_arr',
)


def validate_grid_arrays(d: dict, Nx: int, Ny: int, *, where: str) -> dict:
    """Validate the grid-array output contract; return ``d`` unchanged.

    Raises ValueError naming ``where`` (builder identity) plus every
    violation found, so a contract drift fails loudly at build time
    instead of as a downstream KeyError/shape blowup inside the solver.
    """
    problems = []
    for key in GRID_ARRAY_KEYS:
        arr = d.get(key)
        if arr is None:
            problems.append(f"missing key {key!r}")
            continue
        if not isinstance(arr, np.ndarray):
            problems.append(f"{key!r} is {type(arr).__name__}, expected ndarray")
            continue
        if arr.shape != (Nx, Ny):
            problems.append(f"{key!r} shape {arr.shape}, expected {(Nx, Ny)}")
        if arr.dtype != np.float64:
            problems.append(f"{key!r} dtype {arr.dtype}, expected float64")
    zid = d.get('zone_id')
    if zid is None:
        problems.append("missing key 'zone_id'")
    elif not (isinstance(zid, np.ndarray) and zid.shape == (Nx, Ny)
              and np.issubdtype(zid.dtype, np.integer)):
        problems.append("'zone_id' must be an integer ndarray of shape (Nx, Ny)")
    if 'axis' not in d:
        problems.append("missing key 'axis'")
    if problems:
        raise ValueError(f"{where}: grid-array contract violated — "
                         + "; ".join(problems))
    return d
