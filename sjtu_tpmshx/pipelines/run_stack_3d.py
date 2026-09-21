"""Prepare legacy dictionary inputs and sequence the numerical 3D stages.

Public CaseData execution enters the backend directly. This scripted entry
keeps preprocessing at the orchestration boundary without modifying backend
globals. Numerical implementations live in solvers.backends.python.three_d.
"""

from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.solvers.backends.python.three_d.runtime import (
    _build_hv_machinery,
    _extract_3d_metrics,
    _assemble_3d_verdict,
    _run_outer_coupling_3d,
)


def _build_3d_problem(cfg, *, control: RunControl = RunControl()):
    """Prepare legacy inputs at the orchestration boundary, then build runtime."""
    for key, port in (('_cancel_check', 'cancel_check'),
                      ('_progress_cb', 'progress'), ('_iter_cb', 'outer_iteration')):
        if key in cfg:
            raise ValueError(f'{key} is no longer supported in cfg; '
                             f'pass control=RunControl({port}=...) instead')
    if control.backend != 'python':
        raise ValueError(f'unsupported backend: {control.backend}')
    control.check_cancelled()
    from sjtu_tpmshx.preprocess.three_d.preparation import _prepare_problem_data
    from sjtu_tpmshx.solvers.backends.python.three_d.runtime import build_problem
    prepared = _prepare_problem_data(cfg)
    return build_problem(prepared['cfg'], prepared, control=control)


def _run_3d_stack(cfg, *, control: RunControl = RunControl()):
    """Full 3D stack: per-side SIMPLE3D coupled to the thermal solve.

    Runtime callbacks are supplied through ``control``, never through ``cfg``.

    Both sides support ±x, ±y and ±z with partial openings in both
    cross-stream coordinates. An explicit ``fluid_B_cfg=None`` selects the
    single-fluid path; it is distinct from the frozen-B screening model.

    Sweep profiles (cfg['sweep_profile']):
      'fast_sweep'    — 15³ grid, outer cap 3 (BELOW the converging count —
                        a screening scan, reports converged=False by design),
                        max_iter=20000, compact diag
      'full_validate' — cfg grid,  outer cap 12, max_iter=50000, full diag
      None (default)  — cfg values, outer cap 12 (_MAX_OUTER), full diagnostic
    """
    prob = _build_3d_problem(cfg, control=control)
    cfg = prob.cfg   # fast_sweep profile may rebind cfg inside seam A
    hv = _build_hv_machinery(prob)

    outer = _run_outer_coupling_3d(prob, hv, control=control)

    met = _extract_3d_metrics(prob, outer)

    # Conservation diagnostics (energy + mass balance + interior-corrected Q) —
    # extracted to _conservation_diagnostics_3d (F1). Always computed so the
    # user spots non-physical regressions without re-running validation.
    _result, _diagnostics = _assemble_3d_verdict(prob, outer, met)
    return _result
