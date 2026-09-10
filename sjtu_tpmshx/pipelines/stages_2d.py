"""pipelines/stages_2d.py — 2D compute stage functions for SJTU-TPMSHX.

The cfg-only stage functions consumed by
controllers.compute_pipeline.Pipeline2D (_parse_inputs_cfg →
_build_fields_cfg → _run_solvers_cfg → _finalize_cfg).  Compute-only
(Qt/matplotlib-free); 2D result rendering lives in
``ui/plot_2d_results.py``.

Moved out of `runs/run_calculation.py` in batch-3 (2026-06-13) — completing
the controllers→runs layer-inversion fix.  This module imports nothing from
`runs/` or `controllers/` (contracts-layer split 2026-07-02: ComputeConfig /
ComputeResult now come from `domain`, so the old pipelines↔controllers cycle
— and the deferred imports that held it shut — is gone).

Originally extracted from main.py (Task B.9). C3 audit (2026-05-28, L-a-1):
scalar UI inputs route through ``ui.window_config.config_from_window`` rather
than direct ``le_*`` widget reads; the window is still required for non-le
state (zone config, _eps_A, extrap reasons, _temp_to_K hook, _DIR_MAP).
"""
from __future__ import annotations

from sjtu_tpmshx.solvers.nu_correlations import sco2_nu_metadata, sco2_nu_notices

from typing import TYPE_CHECKING, Any

import os

import numpy as np
from sjtu_tpmshx.domain.compute_config import ComputeConfig, bc_to_dict
from sjtu_tpmshx.domain.compute_result import ComputeResult
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.solvers.tpms_calc import compute as tpms_compute, geometry as tpms_geometry
from sjtu_tpmshx.solvers.df_projection import override_simple_K_cF, extract_dP_from_simple
from sjtu_tpmshx.pipelines._stage_common import (
    validate_domain_dims, surrogate_extrap_reasons, safe_float,
    geometry_props,
)
from sjtu_tpmshx.logutil import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

# Re-exports — external consumers (controllers/compute_pipeline, tests)
# import these from pipelines.stages_2d; keep every moved name reachable.
from sjtu_tpmshx.pipelines.solve_2d import (
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


def _finalize_cfg(raw: dict[str, Any],
                  fields: dict[str, Any]) -> ComputeResult:
    """Phase 4 (Qt-free): assemble a :class:`ComputeResult` from the
    raw ``_run_solvers_cfg`` output and the original ``fields`` dict.

    Audit C4 (L-a-2): no window writes; everything moves through the
    returned :class:`domain.compute_result.ComputeResult`.
    Legacy ``_store_results(window, cfg, result)`` becomes a thin
    adapter that copies the result's slots into the UI attributes
    that ``finalize_plots`` already reads from ``window``.

    The ``fields`` dict still holds the parsed-input cfg dict under
    key ``compute_cfg`` (the original :class:`ComputeConfig`) plus
    ``N_x`` / ``N_y`` / ``L`` / ``H`` / ``dir_A`` / ``dir_B`` /
    ``zone_config`` / ``za`` — the same keys ``_store_results`` read
    from the parsed-cfg dict.
    """
    Ta, Tb, Ts = raw['Ta'], raw['Tb'], raw['Ts']
    ucA, vcA = raw['ucA'], raw['vcA']
    ucB, vcB = raw['ucB'], raw['vcB']

    compute_cfg = fields['compute_cfg']

    # Zone slot — None when zones disabled.
    zones_slot = None
    if (raw.get('_shim_zone_axis_dir') is not None
            or raw.get('_shim_zone_stats') is not None):
        zones_slot = {
            'axis_dir': raw.get('_shim_zone_axis_dir'),
            'stats': raw.get('_shim_zone_stats'),
            'boundaries': raw.get('_shim_zone_boundaries'),
            'boundaries_x': raw.get('_shim_zone_boundaries_x'),
            'boundaries_y': raw.get('_shim_zone_boundaries_y'),
        }

    # TPMS geometry derived from cfg (eps + D_h + A_0) for props slot.
    eps_geom, D_h_m, A_0_m2 = geometry_props(compute_cfg)

    return ComputeResult(
        Q_W=safe_float(raw['Q_total']),
        dP_A_Pa=safe_float(raw['dP_A']),
        dP_B_Pa=safe_float(raw['dP_B']),
        # Fail-safe default: a missing/renamed key must read as NOT converged,
        # not silently report success (blind-spot audit W5, 2026-07-07).
        converged=bool(raw.get('solver_converged', False)),
        T_out_A_K=raw['T_out_A_K'],
        T_out_B_K=raw['T_out_B_K'],
        fields={
            'Ta': Ta, 'Tb': Tb, 'Ts': Ts,
            'ucA': ucA, 'vcA': vcA, 'ucB': ucB, 'vcB': vcB,
            # N5: display-smoothed copies (None on full-face runs ⇒ use raw)
            'ucA_disp': raw.get('ucA_disp'), 'vcA_disp': raw.get('vcA_disp'),
            'ucB_disp': raw.get('ucB_disp'), 'vcB_disp': raw.get('vcB_disp'),
            'P_fA': raw['P_fA'], 'P_fB': raw['P_fB'],
            'dx_arr': raw['energy_dx'], 'dy_arr': raw['energy_dy'],
            'N_x': fields['N_x'], 'N_y': fields['N_y'],
            'L': fields['L'], 'H': fields['H'],
            'dir_A': fields['dir_A'], 'dir_B': fields['dir_B'],
            'zone_config': fields['zone_config'],
            'za': fields['za'],
        },
        coeffs={
            'K_ffA': raw.get('_shim_K_ffA'),
            'K_ffB': raw.get('_shim_K_ffB'),
            'K_ss': raw.get('_shim_K_ss'),
            'h_vA': raw.get('_shim_h_vA'),
            'h_vB': raw.get('_shim_h_vB'),
        },
        props={
            'rho_A': raw.get('_shim_rho_A'),
            'rho_B': raw.get('_shim_rho_B'),
            'mu_A': raw.get('_shim_mu_A'),
            'mu_B': raw.get('_shim_mu_B'),
            'eps_A': eps_geom,
            'D_h_m': D_h_m,
            'A_0_m2': A_0_m2,
        },
        residuals={
            'r_dP_A': float('nan'),  # _run_solvers does not surface
            'r_dP_B': float('nan'),
            'r_Q': 1.0 if raw.get('Q_richardson_warn') else 0.0,
            'simple_A': raw.get('residuals_A'),
            'simple_B': raw.get('residuals_B'),
            'mass_imbalance_rel_A': float(
                raw.get('mass_imbalance_rel_A', float('nan'))),
            'mass_imbalance_rel_B': float(
                raw.get('mass_imbalance_rel_B', float('nan'))),
            'Q_A': float(raw.get('Q_A', float('nan'))),
            'Q_B': float(raw.get('Q_B', float('nan'))),
            'Q_net': float(raw.get('Q_net', float('nan'))),
            'energy_imbalance_rel': float(
                raw.get('energy_imbalance_rel', float('nan'))),
            'enthalpy_imbalance_rel': float(
                raw.get('energy_imbalance_rel', float('nan'))),
        },
        zones=zones_slot,
        warnings=list(raw.get('warnings_list', [])) + sco2_nu_notices(fields.get('compute_cfg')),
        extrap_reasons=list(fields.get('extrap_reasons', [])),
        diagnostics={
            # Dimension marker for write_result dispatch (C4).
            'mode': '2d',
            'Q_enthalpy_A': raw.get('Q_enthalpy_A'),
            'Q_enthalpy_B': raw.get('Q_enthalpy_B'),
            'Q_solid_richardson': raw.get('Q_solid_richardson'),
            'Q_richardson_warn': bool(raw.get('Q_richardson_warn', False)),
            'richardson_info': raw.get('richardson_info'),
            'true_h_balance': raw.get('true_h_balance'),
            'model_h_balance': raw.get('model_h_balance'),
            'mass_flow_A_kg_s_per_m': float(
                raw.get('mass_flow_A_kg_s_per_m', float('nan'))),
            'mass_flow_B_kg_s_per_m': float(
                raw.get('mass_flow_B_kg_s_per_m', float('nan'))),
            # 2026-07-12: solve_2d produced all three of these on the raw dict
            # and none of them were forwarded — every ComputeResult consumer
            # was blind to the 2D compressible-envelope verdict and to the
            # P_abs-clip engagement (the 3D side had the same gap for
            # p_clip_hits; both are closed now).
            'envelope_valid': raw.get('envelope_valid', True),
            'envelope_reasons': list(raw.get('envelope_reasons', [])),
            'p_clip_hits': int(raw.get('p_clip_hits', 0)),
            # C8 shooting diagnostics (openspec c8-p-in-shooting): realized
            # inlet absolute pressure vs the specified P_in, per ideal-gas
            # side (NaN otherwise). Forwarded here for the same reason as
            # envelope_valid above — a raw-dict-only key is invisible to
            # every ComputeResult consumer.
            'P_in_realized_A': float(raw.get('P_in_realized_A', float('nan'))),
            'P_in_shoot_resid_A': float(
                raw.get('P_in_shoot_resid_A', float('nan'))),
            'P_in_realized_B': float(raw.get('P_in_realized_B', float('nan'))),
            'P_in_shoot_resid_B': float(
                raw.get('P_in_shoot_resid_B', float('nan'))),
            # Per-gate breakdown behind ComputeResult.converged, so a caller
            # can see WHICH gate failed (convergence truth-table).
            'convergence_detail': raw.get('convergence_detail'),
            'sco2_nu_observations': raw.get('sco2_nu_observations', {}),
        },
        metadata={'darcy_forchheimer': raw.get('df_metadata'),
                  'sco2_nu': sco2_nu_metadata(getattr(fields.get('compute_cfg'), 'sco2_nu', None))},
    )


# B2 2.1b: the _store_results(window, cfg, result) adapter was DELETED —
# Main_Menu.write_result (ui/mixins/run_controller.py) is the single
# ComputeResult→window copy now. Note: the old dict's residuals_A/B
# snapshots are not forwarded (they only fed the removed 2D convergence
# plot; verified no UI consumer).
