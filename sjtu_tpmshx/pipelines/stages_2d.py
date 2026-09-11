"""Historical 2D input and numerical-stage entry points.

Applications use controllers.compute_pipeline and the three public modules.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import os

import numpy as np
from sjtu_tpmshx.domain.compute_config import ComputeConfig, bc_to_dict
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.models.tpms_calc import compute as tpms_compute, geometry as tpms_geometry
from sjtu_tpmshx.solvers.df_projection import override_simple_K_cF, extract_dP_from_simple
from sjtu_tpmshx.pipelines._stage_common import (
    validate_domain_dims, surrogate_extrap_reasons,
)
from sjtu_tpmshx.logutil import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

# Re-exports — external consumers (controllers/compute_pipeline, tests)
# import these from pipelines.stages_2d; keep every moved name reachable.
from sjtu_tpmshx.solvers.backends.python.two_d.coupling import (
    _enthalpy_balance_2d, _PipelineWindowShim, _compute_pressure_2d,
    _apply_zone_stats_2d, _compute_Q_richardson, _run_solvers,
)

_log = get_logger(__name__)


# B2 2.1b (2026-06-13): the legacy window entrypoints
# run_calculation_inner / run_calculation_inner_cfg and the
# _parse_inputs window adapter were DELETED — the GUI 2D path now drives
# controllers.compute_pipeline.Pipeline2D (cfg-only stage functions
# below) and copies the ComputeResult back via Main_Menu.write_result.


from sjtu_tpmshx.preprocess.two_d.preparation import (
    _check_zoned_fluid_support, _parse_inputs_cfg, _prepare_grid,
)


def _build_fields_cfg(cfg: dict[str, Any], *, live_residuals=None):
    from sjtu_tpmshx.solvers.backends.python.two_d.runtime import build_runtime
    return build_runtime(cfg, _prepare_grid(cfg), live_residuals=live_residuals)


def _run_solvers_cfg(cfg: dict[str, Any], fields: dict[str, Any], *,
                     progress_cb: Callable[[int], None] | None = None,
                     cancel_token: Any = None,
                     ui_hooks: dict | None = None) -> dict[str, Any]:
    """Phase 3 (Qt-free): drive ``_run_solvers`` via the
    :class:`_PipelineWindowShim` adapter.

    Audit C4 (L-a-2). ``progress_cb`` is fired indirectly: the shim's
    ``__setattr__`` forwards any ``_compute_progress`` write inside
    the solver loop to ``progress_cb`` as an integer 0–100. The
    enclosing :class:`ComputePipeline.run` adds its own 20 / 90 / 100
    ticks around the three phases.

    ``cancel_token`` is polled at solver iteration/chunk boundaries.

    ``ui_hooks`` (B2 2.1a): optional dict; ``'iter_label_cb'`` receives
    the shim-captured ``_iter_label_now`` strings ("iter k/N").
    """
    compute_cfg = cfg['compute_cfg']
    _hooks = ui_hooks or {}
    shim = _PipelineWindowShim(compute_cfg, progress_cb=progress_cb,
                               iter_label_cb=_hooks.get('iter_label_cb'))
    cancel_check = (None if cancel_token is None else
                    lambda: bool(getattr(cancel_token, 'cancelled', False)))
    result = _run_solvers(shim, cfg, fields, cancel_check=cancel_check)
    # Forward shim-captured state into the result dict so Pipeline2D's
    # finalize step can promote it into ComputeResult slots.
    result['_shim_zone_axis_dir'] = shim._zone_axis_dir
    result['_shim_zone_stats'] = shim._zone_stats
    result['_shim_zone_boundaries'] = shim._zone_boundaries
    result['_shim_zone_boundaries_x'] = shim._zone_boundaries_x
    result['_shim_zone_boundaries_y'] = shim._zone_boundaries_y
    # Fluid + solid properties — needed by ComputeResult.props.
    result['_shim_rho_A'] = shim._rho_A
    result['_shim_rho_B'] = shim._rho_B
    result['_shim_mu_A'] = shim._mu_A
    result['_shim_mu_B'] = shim._mu_B
    result['_shim_K_ffA'] = shim._K_ffA
    result['_shim_K_ffB'] = shim._K_ffB
    result['_shim_K_ss'] = shim._K_ss
    result['_shim_h_vA'] = shim._h_vA
    result['_shim_h_vB'] = shim._h_vB
    return result
