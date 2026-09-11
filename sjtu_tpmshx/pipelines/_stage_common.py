"""Shared non-kernel scaffolding for the 2D/3D pipeline stages.

Extracted (openspec pipeline-stage-dedup, 2026-07-03) from copy-pasted blocks
in ``stages_2d._parse_inputs`` / ``stages_3d._parse_inputs_3d_cfg`` and the
two ``ComputeResult`` assembly sites. Pure input validation / result plumbing
— nothing here touches solver numerics, so the golden 2D/3D gates must stay
bit-identical across this extraction.

The numba kernels themselves stay per-dimension by design (unification
rejected — the stencils genuinely differ); only Qt-free, kernel-free glue
belongs in this module.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sjtu_tpmshx.domain.compute_config import ComputeConfig

from sjtu_tpmshx.models.input_validation import (  # noqa: F401 - existing stage entry points
    validate_domain_dims, surrogate_extrap_reasons,
)


def safe_float(v: Any) -> float:
    """float(v) with None / non-numeric → nan (headline-scalar guard).

    ``raw.get(key, default)`` only returns ``default`` when ``key`` is
    absent — explicit ``None`` values (e.g. when fluid B is frozen) would
    crash ``float(None)``.
    """
    try:
        return float(v) if v is not None else float('nan')
    except (TypeError, ValueError):
        return float('nan')


def geometry_props(compute_cfg: ComputeConfig) -> tuple[float, float, float]:
    """(epsilon, D_h_m, A_0_m2) triple for the ComputeResult ``props`` slot,
    derived from cfg geometry via the closed-form tpms_calc.geometry."""
    from sjtu_tpmshx.solvers.tpms_calc import geometry as _tpms_geom
    g = _tpms_geom(compute_cfg.geometry.tpms,
                   compute_cfg.geometry.L_cell_mm,
                   compute_cfg.geometry.t_wall_mm,
                   compute_cfg.geometry.k_s_W_mK)
    return g['epsilon'], g['D_h'], g['A_0']
