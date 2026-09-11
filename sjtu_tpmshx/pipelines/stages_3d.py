"""Historical 3D input and numerical-stage entry points.

Applications use controllers.compute_pipeline and the three public modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from sjtu_tpmshx.domain.compute_config import ComputeConfig, bc_to_dict
from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry
from sjtu_tpmshx.models.asym_split import (
    _asym_split_A, _per_side_eps_override, _eps_sides_for_run,
)

from sjtu_tpmshx.pipelines._stage_common import (
    validate_domain_dims, surrogate_extrap_reasons,
)
from sjtu_tpmshx.models.field_coordinates_3d import (  # Phase 3: extracted pure helpers
    _stream_axis, _dir_is_reverse, _inlet_index, _outlet_index,
    _face_slice, _real_outlet_slice, _dilate_one_step_3d, _box_smooth_3d,
    _build_partial_masks, _solver_velocity_to_real, _solver_staggered_to_real,
    _balance_stream_outflow, _build_chi_B_union_extrude,
    _build_chi_B_mass_flux_threshold, _build_chi_B_velocity_threshold,
)

# ── Re-exports (openspec split-pipelines, 2026-07-03) ────────────────────────
# External consumers (tests, runs/, validation/, projects/) import these
# names from pipelines.stages_3d; keep every moved name reachable here.
# The implementations moved VERBATIM to pipelines.flux_3d / pipelines.grid_3d
# / pipelines.run_stack_3d — behavior bit-identical.
from sjtu_tpmshx.solvers.backends.python.three_d.flux import (  # noqa: F401
    _UI_ROUGH_MODE_DEFAULT, _resolve_ui_roughness, _face_flux_weights,
    _mass_weighted_T_out, _mass_weighted_h_out, _sco2_hv_local_field,
    _simple_mass_flow, _apply_roughness_KcF, _apply_roughness_h_v,
)
from sjtu_tpmshx.models.grid_3d import (  # noqa: F401
    _resolve_axis_map, _build_zone_fields_3d, _build_grid_3d,
    _solver_spacings,
)
from sjtu_tpmshx.pipelines.run_stack_3d import (  # noqa: F401
    R_AIR, _MAX_OUTER, _OUTER_TOL, _ALPHA_T,
    _M4_DEFAULT_EXPONENT, _M4_DEFAULT_MODE,
    _seed_p_ref, _simple_tol_default, _apply_phase_flags, _apply_accel_flags,
    _prof_3d_enabled, _prof_res_trace, _run_two_simple_parallel,
    _conservation_diagnostics_3d, _run_3d_stack,
)


# B2 2.1c (2026-06-13): the legacy window entrypoints
# run_calculation_3d_inner / run_calculation_3d_inner_cfg and the
# _parse_inputs window adapter were DELETED — the GUI 3D path drives
# controllers.compute_pipeline.Pipeline3D (cfg stage functions below);
# B3 (2026-06-13) retired the transitional raw_3d carrier: the GUI 3D path
# now publishes the ComputeResult directly as window._result_3d
# (Main_Menu.write_result), so diagnostics['raw_3d'] no longer exists.


# ── 3D result visualisation (PyVistaQt panel + 2D mid-z slice canvases) was
#    extracted to ui/plot_3d_results.py (2026-06-09 Group-4 slice A1/A2):
#    finalize_plots_3d / _render_2d_slices_from_3d / _plot_3d_{temperature,
#    pressure,velocity} / _begin_canvas_plot / _style_axis /
#    _store_3d_result_labels / _fmt_metric. Moved out so this compute module
#    no longer imports ui.theme / matplotlib (C4 'Qt-free' contract).


# ─────────────────────────── internals ────────────────────────────

from sjtu_tpmshx.preprocess.three_d.preparation import _parse_inputs_3d_cfg  # noqa: F401


def _build_fields_3d_cfg(parsed: dict[str, Any]) -> dict[str, Any]:
    """Phase 2 (Qt-free) 3D: passthrough.

    Audit C4 (L-a-2). The 3D stack has no separate build phase — the
    cfg dict from :func:`_parse_inputs_3d_cfg` is consumed directly by
    :func:`_run_3d_stack`. This stub keeps the Pipeline ABC contract
    symmetric with 2D: ``build_fields → run_solvers → finalize``.
    """
    return parsed


def _run_solvers_3d_cfg(parsed: dict[str, Any], fields: dict[str, Any], *,
                         progress_cb: Callable[[int], None] | None = None,
                         cancel_token: Any = None,
                         iter_cb: Callable[[int, int], None] | None = None,
                         ) -> dict[str, Any]:
    """Phase 3 (Qt-free) 3D: drive :func:`_run_3d_stack` with the
    progress + cancel hooks read off the cfg dict.

    Audit C4 (L-a-2). Wraps the existing ``_run_3d_stack(cfg)`` body
    without modifying it.  ``parsed`` and ``fields`` are the same dict
    (the build phase is a passthrough); the Pipeline ABC contract
    surfaces both so the signature matches :class:`Pipeline2D`.

    ``iter_cb(outer, n_outer)`` (B2 2.1a) mirrors the legacy window
    path's ``cfg['_iter_cb']`` wiring — drives the UI "outer k/N"
    ticker label through the SIMPLE↔LTNE coupling loop.
    """
    cfg = dict(parsed)  # shallow copy — _run_3d_stack mutates a few keys

    # Progress + cancel hooks (mirrors legacy run_calculation_3d_inner_cfg).
    if progress_cb is not None:
        cfg['_progress_cb'] = (lambda pct, _cb=progress_cb: _cb(int(pct)))
    if cancel_token is not None:
        cfg['_cancel_check'] = (lambda _tok=cancel_token:
                                bool(getattr(_tok, 'cancelled', False)))
    if iter_cb is not None:
        cfg['_iter_cb'] = iter_cb

    # Phase A/B/C acceleration flags — see _apply_phase_flags.
    _apply_phase_flags(cfg)

    return _run_3d_stack(cfg)
