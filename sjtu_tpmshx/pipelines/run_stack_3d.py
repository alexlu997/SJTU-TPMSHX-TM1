"""Prepare legacy dictionary inputs and sequence the numerical 3D stages.

Public CaseData execution enters the backend directly. This scripted entry
keeps preprocessing at the orchestration boundary without modifying backend
globals. Numerical implementations live in solvers.backends.python.three_d.
"""

from sjtu_tpmshx.solvers.backends.python.three_d.runtime import (  # noqa: F401
    _seed_p_ref,
    _simple_tol_default,
    _simple_max_iter,
    _apply_phase_flags,
    _apply_accel_flags,
    _prof_3d_enabled,
    _prof_res_trace,
    _run_two_simple_parallel,
    _conservation_diagnostics_3d,
    _Problem3D,
    _HvMachinery,
    _OuterState,
    _Metrics3D,
    _build_hv_machinery,
    _extract_3d_metrics,
    _assemble_3d_verdict,
    _run_outer_coupling_3d,
    R_AIR,
    _MAX_OUTER,
    _OUTER_TOL,
    _ALPHA_T,
    _M4_DEFAULT_EXPONENT,
    _M4_DEFAULT_MODE,
)


def _build_3d_problem(cfg):
    """Prepare legacy inputs at the orchestration boundary, then build runtime."""
    from sjtu_tpmshx.preprocess.three_d.preparation import _prepare_problem_data
    from sjtu_tpmshx.solvers.backends.python.three_d.runtime import build_problem
    prepared = _prepare_problem_data(cfg)
    return build_problem(prepared['cfg'], prepared)


def _run_3d_stack(cfg):
    """Unified 3D stack: SIMPLE3D (A) + frozen Tb + LTNE3D.

    Supports fluid-A streamwise direction ∈ {+x, -x, +y, -y} and partial
    inlet/outlet in the cross-stream dimension (z-partial optional via
    `in_z_ctr`/`in_z_w` etc. in `fluid_A_cfg`).

    Sweep profiles (cfg['sweep_profile']):
      'fast_sweep'    — 15³ grid, outer cap 3 (BELOW the converging count —
                        a screening scan, reports converged=False by design),
                        max_iter=20000, compact diag
      'full_validate' — cfg grid,  outer cap 12, max_iter=50000, full diag
      None (default)  — cfg values, outer cap 12 (_MAX_OUTER), full diagnostic
    """
    prob = _build_3d_problem(cfg)
    cfg = prob.cfg   # fast_sweep profile may rebind cfg inside seam A
    hv = _build_hv_machinery(prob)

    outer = _run_outer_coupling_3d(prob, hv)

    met = _extract_3d_metrics(prob, hv, outer)

    # Conservation diagnostics (energy + mass balance + interior-corrected Q) —
    # extracted to _conservation_diagnostics_3d (F1). Always computed so the
    # user spots non-physical regressions without re-running validation.
    _result = _assemble_3d_verdict(prob, hv, outer, met)
    return _result
