"""Prepared 3D numerical execution, runtime state and local helpers.

Originally extracted from run_stack_3d.py (2026-07-21), then moved into the
Python backend for TM1. Public execution consumes prepared inputs; current
callers import owning modules directly. Former stages_3d re-exports are retired.
This backend does not import preprocessing, pipelines or formal postprocessing.
"""

from __future__ import annotations
import os
import time as _time
from dataclasses import dataclass
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING
import numpy as np
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.run_environment import run_environment
from sjtu_tpmshx.domain.run_warnings import range_context
from sjtu_tpmshx.models.nu_correlations import record_raw_nu_range, warn_sco2_nu_evidence
from sjtu_tpmshx.models.tpms_props import record_temperature_ranges
from sjtu_tpmshx.models.local_heat_transfer import _sco2_hv_local_field, local_nusselt, local_speed
from sjtu_tpmshx.models.grid import cell_average

from sjtu_tpmshx.solvers.coupling_skeleton import OuterConvergence, run_outer_coupling
from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D, _should_parallelize
from sjtu_tpmshx.solvers._solve_common import (
    configure_convergence, inlet_pressure_state, pressure_shooting_reference,
    pressure_initial_reference,
)
from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d, _inlet_transport_3d
from sjtu_tpmshx.models.tpms_calc import (
    air_density, air_viscosity,
    air_conductivity, air_cp,
)
from sjtu_tpmshx.models import fluid_props
from sjtu_tpmshx.models import sco2_props
from sjtu_tpmshx.models.envelope import (gate_solution,
                               mach_field_max, ChokedFlowError,
                               PRESSURE_FLOOR_PA)

from .flux import (
    _face_flux_weights, _mass_weighted_T_out, _mass_weighted_h_out,
    _simple_mass_flow,
    _apply_roughness_h_v,
)
from sjtu_tpmshx.models.grid_3d import _solver_spacings
from sjtu_tpmshx.models.field_coordinates_3d import (  # Phase 3: extracted pure helpers
    _stream_axis, _inlet_index, _outlet_index,
    _real_outlet_slice,
    _port_rectangles, _solver_velocity_to_real, _solver_staggered_to_real,
    _balance_stream_outflow,
)
from sjtu_tpmshx.logutil import get_logger

if TYPE_CHECKING:
    from sjtu_tpmshx.solvers.anderson_acceleration import AndersonOuterCoupling

_log = get_logger(__name__)


def _prepared_eps_overrides(cfg, eps):
    if float(cfg.get('delta_levelset', 0.)) == 0.:
        return None, None
    split = cfg['thermal_geometry']['split_A']
    return float(eps) * split, float(eps) * (1. - split)


def _pressure_real_3d(solver, axis_map, offset):
    """Map gauge pressure using the caller's existing absolute-P offset."""
    field = (offset + solver.P).transpose(axis_map['solver_to_real_perm'])
    if axis_map['is_reverse']:
        field = np.flip(field, axis=axis_map['stream_real_axis'])
    return np.ascontiguousarray(field)


# Retained call argument: captured environment > config > 1e-5.
# SIMPLE's F2 gates use mom_tol/mass_local_tol/mass_global_tol, not this value.
def _simple_tol_default(cfg=None):
    env = run_environment(cfg, 'TPMSHX_SIMPLE_TOL')
    if env is not None:
        return float(env)
    if cfg is not None and cfg.get('tol_simple') is not None:
        return float(cfg['tol_simple'])
    return 1e-5


def _simple_max_iter(cfg, default):
    """R3: SolverConfig.max_iter_simple overrides the per-stage auto."""
    v = cfg.get('max_iter_simple') if cfg is not None else None
    return int(v) if v is not None else int(default)


def _apply_accel_flags(solver, cfg):
    """Apply shared convergence and the supported 3D acceleration controls."""
    solver.use_adaptive_amg_tol = bool(cfg.get('use_adaptive_amg_tol', True))
    solver.use_anderson = bool(cfg.get('use_anderson', False))
    solver.use_coarse_bootstrap = bool(cfg.get('use_coarse_bootstrap', False))
    solver.coarse_bootstrap_max_iter = int(cfg.get('coarse_bootstrap_max_iter', 200))
    configure_convergence(solver, cfg)
    if cfg.get('track_momentum_residual'):
        solver.track_momentum_residual = True
    if solver.use_anderson:
        raise ValueError(
            "use_anderson=True in SIMPLE has been retired with legacy "
            "convergence; disable TPMSHX_PHASE_B/use_anderson")


# ─────────────────────────────────────────────────────────────────────────
#  3D solver profiler (opt-in, zero-cost when off)
# ─────────────────────────────────────────────────────────────────────────
#  WHY: 3D runtime is dominated by the SIMPLE↔LTNE coupling. When a run is
#  slow, you need per-solve attribution to know whether SIMPLE-A, SIMPLE-B,
#  or the LTNE solve is the bottleneck — and whether a solve is genuinely
#  converging or burning iterations on a residual plateau. This profiler
#  emits exactly that.
#
#  This is the instrument that diagnosed the low-Re water bottleneck
#  (2026-06-02): it showed SIMPLE_B hitting its iteration cap (2000/600,
#  conv=False) while its velocity field was already settled — i.e. the
#  absolute mass residual plateaus above the air-tuned tol for slow water.
#  That historical finding predates the current shared F2 exit gates.
#
#  OUTPUT (stdout, grep-friendly):
#    [PROF]     <stage>: <wall>s  iters=<n>  conv=<bool>  (cap=<n>)
#    [PROF-RES] <stage>: n=<N> first=[..] last=[..] min=<r>@<it> final=<r>
#               — the pressure-subproblem residual history (head/tail/min), to
#               distinguish a slow-but-monotone descent from a plateau.
#
#  COST: gated behind _prof_3d_enabled(); when off, no perf_counter call, no
#  array copy, no print — pure `if False:`. Safe to leave in production.
#
#  ENABLE: TPMSHX_PROFILE_3D=1  (or drop an empty `.profile_3d` file at the
#  package root for GUI / IDE launches that carry no shell env).
def _prof_3d_enabled():
    """B1 profiler gate. Prints per-outer wall-clock + iteration counts for
    each SIMPLE / LTNE solve so the 3D runtime can be attributed to a specific
    solver. Zero cost when off. Enable by EITHER:
      - env var:  TPMSHX_PROFILE_3D=1   (PowerShell: $env:TPMSHX_PROFILE_3D=1)
      - flag file: drop an empty file named ``.profile_3d`` in the package root
        (same dir as main.py) — handy when the GUI is launched without a shell
        env (double-click, IDE run config, etc.)."""
    if os.environ.get('TPMSHX_PROFILE_3D', '0') == '1':
        return True
    try:
        _flag = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            '.profile_3d')
        return os.path.exists(_flag)
    except Exception:
        return False


def _prof_res_trace(tag, solver):
    """Print the pressure-subproblem residual history (per-iter ``residuals``
    list) so we can tell a slow-but-monotone descent (raise cap / accelerate)
    from a plateau / limit-cycle (needs a scheme change). Samples first 5,
    last 5, and the min residual + the iter it occurred."""
    try:
        r = list(getattr(solver, 'residuals', []) or [])
        if not r:
            _log.info(f"[PROF-RES] {tag}: (no residuals)")
            return
        import numpy as _np
        arr = _np.asarray(r, dtype=float)
        i_min = int(_np.argmin(arr))
        head = " ".join(f"{x:.2e}" for x in arr[:5])
        tail = " ".join(f"{x:.2e}" for x in arr[-5:])
        _log.info(f"[PROF-RES] {tag}: n={len(arr)} first=[{head}] "
                  f"last=[{tail}] min={arr[i_min]:.2e}@{i_min} "
                  f"final={arr[-1]:.2e}")
    except Exception as _e:
        _log.warning(f"[PROF-RES] {tag}: trace failed: {_e}")


def _run_two_simple(sA, sB, *, max_iter=2000, tol=None,
                    cancel_check=None):
    """Use parallelism across sides or inside sweeps, never both at once.

    Small-grid sides have independent state and may overlap on two threads.
    If either side uses parallel sweeps, solve A then B on the caller thread:
    Numba's workqueue cannot accept concurrent parallel kernel launches.
    The same rule also avoids two inner thread pools competing on other backends.

    `cancel_check` (optional callable -> bool) is forwarded to both solves so
    each side exits its SIMPLE loop on cancel.

    After both sides finish, real failures take precedence over cancellation.
    """
    import threading
    from sjtu_tpmshx.logutil import current_output, output_scope
    parent_output = current_output()
    from sjtu_tpmshx.domain.run_warnings import (
        current_warnings, merge_warnings, warning_scope,
    )
    if tol is None:
        tol = _simple_tol_default()
    parallel_sweeps = any(_should_parallelize(s.Nx, s.Ny, s.Nz) for s in (sA, sB))

    err = [None, None]
    parent_warnings = current_warnings()
    side_warnings = [{} if parent_warnings is not None else None for _ in range(2)]
    res = [None, None]   # (converged, iters) per fluid for the B1 profiler
    _prof = _prof_3d_enabled()
    _t0 = _time.perf_counter() if _prof else None

    def _solve_side(index, solver):
        try:
            with output_scope(parent_output), warning_scope(side_warnings[index]), range_context(
                    side=('A', 'B')[index], stage='initial', layout='solver-cell(cross1,stream,cross2)'):
                res[index] = solver.solve(max_iter=max_iter, tol=tol, verbose=False,
                                          cancel_check=cancel_check)
        except Exception as e:
            err[index] = e

    if parallel_sweeps:
        _solve_side(0, sA)
        _solve_side(1, sB)
    else:
        tA = threading.Thread(target=_solve_side, args=(0, sA), daemon=True)
        tB = threading.Thread(target=_solve_side, args=(1, sB), daemon=True)
        tA.start(); tB.start()
        tA.join(); tB.join()
    merge_warnings(parent_warnings, side_warnings)

    if _prof:
        _dt = _time.perf_counter() - _t0
        _mode = 'A then B, parallel sweeps' if parallel_sweeps else 'A||B, serial sweeps'
        _log.info(f"[PROF] initial SIMPLE ({_mode}) {_dt:7.2f}s  "
                  f"A={res[0]}  B={res[1]}  (cap={max_iter})")
        _prof_res_trace("initial SIMPLE_A", sA)
        _prof_res_trace("initial SIMPLE_B", sB)

    for exc in err:
        if exc is not None and not isinstance(exc, CancelledError):
            raise exc
    for exc in err:
        if exc is not None:
            raise exc
    # Also catch a request arriving after the last solver checkpoint.
    if cancel_check is not None and cancel_check():
        raise CancelledError("compute cancelled by user")
    return res    # [(converged_A, iters_A), (converged_B, iters_B)|None]


R_AIR = 287.05
# 2026-07-12 — bump _MAX_OUTER 5→8. This mirrors the SAME fix 2D already took
# on 2026-05-09 (`solve_2d.py:683`: "bump _MAX_COUPLING 5→10 … cases that
# previously hit iter 5 with dT_B still bouncing now have headroom to settle
# without firing the 'not converged' warning") — 3D was left behind at 5.
#
# It is a CAP, not a budget: `run_outer_coupling` exits the moment the tracked
# ΔT fields drop under `_OUTER_TOL`, so a bigger cap costs a converging case
# nothing. At 5 the production Shanghai-grid case was being TRUNCATED one
# iteration before it converged — it needs 6, and the honest verdict (2026-07-12)
# duly reported converged=False on every such run.
#
# Measured outer-iteration counts to convergence (0.182×0.182×0.042, 20×10×3
# unless noted):
#     mild      ΔT=50 K,  u=2      → 4
#     partial-BC air-air 8×6×6     → 5      (the cross-flow class that forced 2D)
#     baseline  ΔT=180 K, u=6      → 6      (production Shanghai grid)
#     partial-BC air-air 20×10×3   → 6
#     hot+fast  ΔT=500 K, u=20     → 7
#     golden-3D air_air            → 8
#     golden-3D asym_b (δ=0.6)     → 9      (worst measured)
# 8 was the first guess and is NOT enough: it truncates golden-3D's asym_b
# (needs 9) and leaves air_air with zero spare — the exact failure mode being
# fixed. 12 gives three iterations of headroom over the worst measured case.
# The margin is free: the loop exits on convergence, so every case above runs
# the same number of iterations (and returns bit-identical numbers) whether the
# cap is 12, 20 or 100. Only a case that genuinely needs >12 would notice.
_MAX_OUTER = 12       # outer SIMPLE ↔ LTNE iterations (cap, not a budget)
_OUTER_TOL = 0.5      # K
_ALPHA_T = 0.6

def _conservation_diagnostics_3d(Ta, Tb, Ts, h_vA_field, h_vB_field,
                                 sA, sB, fA, fB, dx, dy, dz):
    """Energy + mass conservation diagnostics for a converged 3D solve
    (extracted from _run_3d_stack, 2026-06-09 F1). Returns a dict:
    domain-total balances (Q_sA/Q_sB/Q_net/energy_rel/mass_rel_A/mass_rel_B)
    + end-layer-excluded subvolume metrics (Q_sA_interior /
    Q_sB_interior / Q_interior_primary / AB_interior). Always computed so the
    user spots non-physical regressions without re-running validation; any
    failure warns + reports NaN (never silently swallowed)."""
    try:
        from sjtu_tpmshx.solvers.ltne_energy_3d import energy_balance_3d, mass_balance_3d
        e_bal = energy_balance_3d(Ta, Tb, Ts, h_vA_field, h_vB_field, dx, dy, dz)
        Q_sA = e_bal['Q_sA']
        Q_sB = e_bal['Q_sB']
        Q_net = e_bal['Q_net']
        energy_rel = abs(Q_net) / (abs(Q_sA) + abs(Q_sB) + 1e-30)
        m_bal_A = mass_balance_3d(
            sA.u, sA.v, sA.w, sA.rho_field, sA.dy, sA.dx, sA.dz, 2)
        mass_rel_A = m_bal_A.get('rel', 0.0)
        mass_rel_B = 0.0
        if sB is not None:
            m_bal_B = mass_balance_3d(
                sB.u, sB.v, sB.w, sB.rho_field, sB.dy, sB.dx, sB.dz, 2)
            mass_rel_B = m_bal_B.get('rel', 0.0)
    except Exception as _e:
        # Surface the failure instead of nan-ing it away silently: these
        # diagnostics exist precisely to flag non-physical regressions, so a
        # swallowed exception here would hide the very thing they watch for.
        import warnings as _w
        _w.warn(f"3D conservation diagnostics failed ({_e!r}); reporting NaN.",
                stacklevel=2)
        Q_sA = Q_sB = Q_net = energy_rel = mass_rel_A = mass_rel_B = float('nan')

    # Historical subvolume diagnostics exclude two physical CV layers.
    # These are neither corrected full-core duty nor an external heat budget.
    # Full-volume solid exchange is reported above as Q_sA/Q_sB/Q_net.
    try:
        Nx_g, Ny_g, Nz_g = Ta.shape
        cell_vol = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]
        integ_A = h_vA_field * (Ts - Ta) * cell_vol
        integ_B = h_vB_field * (Ts - Tb) * cell_vol

        def _bc_face_mask(dir_code, NxG, NyG, NzG):
            m = np.zeros((NxG, NyG, NzG), dtype=bool)
            sl = [slice(None)] * 3
            sl[_stream_axis(dir_code)] = _inlet_index(dir_code)
            m[tuple(sl)] = True
            return m

        def _outlet_mask(dir_code, NxG, NyG, NzG):
            m = np.zeros((NxG, NyG, NzG), dtype=bool)
            sl = [slice(None)] * 3
            sl[_stream_axis(dir_code)] = _outlet_index(dir_code)
            m[tuple(sl)] = True
            return m

        bc_A_in  = _bc_face_mask(fA['dir'], Nx_g, Ny_g, Nz_g)
        bc_A_out = _outlet_mask(fA['dir'], Nx_g, Ny_g, Nz_g)
        bc_A = bc_A_in | bc_A_out
        Q_sA_interior = float(np.sum(integ_A[~bc_A]))

        if fB is not None:
            bc_B_in  = _bc_face_mask(fB['dir'], Nx_g, Ny_g, Nz_g)
            bc_B_out = _outlet_mask(fB['dir'], Nx_g, Ny_g, Nz_g)
            bc_B = bc_B_in | bc_B_out
            Q_sB_interior = float(np.sum(integ_B[~bc_B]))
        else:
            Q_sB_interior = 0.0

        Q_interior_primary = 0.5 * (abs(Q_sA_interior) + abs(Q_sB_interior)) \
            if Q_sB_interior != 0.0 else abs(Q_sA_interior)
        AB_interior = (abs(abs(Q_sA_interior) - abs(Q_sB_interior))
                       / max(abs(Q_sA_interior), abs(Q_sB_interior), 1e-30))
    except Exception as _e:
        import warnings as _w
        _w.warn(f"3D subvolume Q diagnostics failed ({_e!r}); "
                f"reporting NaN.", stacklevel=2)
        Q_sA_interior = Q_sB_interior = Q_interior_primary = float('nan')
        AB_interior = float('nan')

    return dict(
        Q_sA=Q_sA, Q_sB=Q_sB, Q_net=Q_net, energy_rel=energy_rel,
        mass_rel_A=mass_rel_A, mass_rel_B=mass_rel_B,
        Q_sA_interior=Q_sA_interior, Q_sB_interior=Q_sB_interior,
        Q_interior_primary=Q_interior_primary, AB_interior=AB_interior)


@dataclass
class _Problem3D:
    """Prepared problem plus live solver references, not an immutable snapshot.

    Cell arrays use real (x,y,z) axes; SIMPLE owns its staggered solver axes.
    K_ffA is refreshed in place. K_ffB may be rebound and is returned by
    _OuterState. B velocities are refreshed in place for existing consumers.
    """
    D_h: float  # m
    G_A: float  # kg/(m2 s)
    G_B: float | None
    H: float
    K_disp_A: float | None
    K_disp_B: float | None
    K_ffA: np.ndarray  # W/(m K)
    K_ffB: np.ndarray
    K_pred: float  # m2
    K_pred_B: float
    K_ss: np.ndarray  # W/(m K)
    L: float
    L_mm_field: np.ndarray | None
    L_stream: float
    L_stream_B: float | None
    Lcell: float  # mm
    Lz: float
    Nx: int
    Ny: int
    Nz: int
    P_inA: float  # Pa, inlet targets
    P_inB: float
    T_inA: float  # K
    T_inB: float
    Tb_presc: np.ndarray | None
    _compact_diag: bool
    _env_mode: str
    _env_warnings: list[str]
    _ltne_info: list[dict[str, object]]
    _ltne_max_iter: int
    _mA: fluid_props.FluidModel
    _mB: fluid_props.FluidModel
    _max_outer: int
    _outer_tol: float
    _simple_nonconv: list[str]
    axis_map: dict[str, object]
    axis_map_B: dict[str, object] | None
    cF_pred: float  # 1/m
    cF_pred_B: float
    cfg: dict[str, object]
    cp_A: float  # J/(kg K), inlet properties
    cp_B: float
    disp_C_A: float
    disp_C_B: float
    dx: np.ndarray  # m, real-axis cell widths
    dy: np.ndarray
    dz: np.ndarray
    eps: float
    eps_arr: np.ndarray
    eps_fA_arr: np.ndarray
    eps_fB_arr: np.ndarray
    fA: dict[str, object]
    fB: dict[str, object] | None
    fluid_type_A: str
    fluid_type_B: str
    in_mask_2d: np.ndarray  # geometric opening fractions, solver (cross1,cross2)
    in_mask_B: np.ndarray | None
    is_reverse: bool
    k_s: float
    mu_A: float  # Pa s, inlet properties
    mu_B: float | None
    out_mask_2d: np.ndarray
    out_mask_B: np.ndarray | None
    perm_B: Sequence[int] | None
    rho_A: float  # kg/m3, inlet properties
    rho_B: float | None
    rho_B_ltne: float
    sA: SIMPLESolver3D
    sB: SIMPLESolver3D | None
    sB_info: dict[str, object] | None
    solver_to_real_perm: Sequence[int]
    stream_real_axis: int
    t_field_3d: np.ndarray | None  # mm
    t_wall: float  # mm
    tpms_type: str
    u_A: float  # m/s
    u_B: float | None
    ucB: np.ndarray
    vcB: np.ndarray
    wcB: np.ndarray


@dataclass
class _HvMachinery:
    """Seam-B state bundle (P2.0): _build_hv_machinery's return, as fields."""
    _build_hv_local_3d: object
    _hv_ratio_A: object
    _hv_ratio_B: object
    h_vA_field: object
    h_vB_field: object
    u_B_val: object


@dataclass
class _OuterState:
    """Live outer-coupling state, returned directly after the loop.

    Cell arrays use real (x,y,z) axes. Temperatures and h_v belong to the
    last thermal solve; K_ffB and rho_cp may include the final post update.
    """
    K_ffB: np.ndarray  # W/(m K)
    Ta: np.ndarray | None  # K
    Tb: np.ndarray | None
    Ts: np.ndarray | None
    _and_A: AndersonOuterCoupling | None
    _and_B: AndersonOuterCoupling | None
    _assemble_real_velocity: Callable[[], tuple[np.ndarray, np.ndarray, np.ndarray]]
    _eps_A_strict: float | None
    _eps_A_strict_cellmax: float | None
    _eps_B_strict: float | None
    _eps_B_strict_cellmax: float | None
    _ltne_mask_A: np.ndarray | None
    _ltne_mask_B: np.ndarray | None
    _outer_converged: bool
    _outer_dT_hist: list[dict[str, float]]
    _outer_last_iter: int
    _use_outer_and: bool
    h_vA_field: np.ndarray  # W/(m3 K)
    h_vB_field: np.ndarray
    rho_cp_fA: np.ndarray  # J/(m3 K)
    rho_cp_fB: np.ndarray
    native_evidence: dict[str, object] | None  # detached last thermal state, before post


@dataclass
class _ThermalInputs3D:
    """One thermal call's real-axis inputs; no copies or cross-iteration state.

    model_kwargs contains mass faces captured before capacity balancing.
    faces_A/B are the temperature-route velocities; true-h separately balances
    and projects copies into its own mass faces.
    """
    velocity_A: tuple[np.ndarray, np.ndarray, np.ndarray]
    faces_A: tuple[np.ndarray, np.ndarray, np.ndarray]
    faces_B: tuple[np.ndarray, np.ndarray, np.ndarray]
    model_kwargs: dict[str, object]
    inlet_flux_A: np.ndarray
    inlet_flux_B: np.ndarray | None
    mode: str


@dataclass
class _Metrics3D:
    """Seam-D state bundle (P2.0): _extract_3d_metrics's return, as fields."""
    L_mm: object
    P_kPa: object
    P_real: object
    P_real_B: object
    Q: object
    Q_AB_imbalance_rel: object
    Q_enthalpy_A: object
    Q_enthalpy_B: object
    Q_solid_B: object
    T_A_out: object
    T_B_out: object
    cell_vol: object
    dP: object
    dP_B: object
    m_dot_A_simple: object
    m_dot_B_phys_in: object
    m_dot_B_phys_out: object
    m_dot_B_simple: object
    uc_real: object
    vc_real: object
    vmag: object
    vmag_B: object
    wc_real: object


def build_problem(cfg, prepared, *, control: RunControl = RunControl()):
    """Seam-A extraction (P1.5, 2026-07-20): problem setup/build --
    profile/grid/axis-map resolution, D-F surrogate, SIMPLE A/B build,
    initial (parallel) SIMPLE solve, LTNE input fields. Moved VERBATIM
    from _run_3d_stack; returns the cross-seam state bundle. Contract:
    bit-identical behavior (golden gate).
    """
    from sjtu_tpmshx.domain.compute_config import reject_retired_boundary_options
    reject_retired_boundary_options(cfg)
    # Conditionally-bound cross-seam names (surgery tool definite-
    # assignment pass): None-init so the unconditional return below
    # cannot raise UnboundLocalError on guarded paths. Downstream
    # reads keep their original guards.
    G_B = None
    K_disp_A = None
    K_disp_B = None
    K_pred = None
    K_pred_B = None
    L_stream_B = None
    Tb_presc = None
    axis_map_B = None
    cF_pred = None
    cF_pred_B = None
    in_mask_B = None
    mu_B = None
    out_mask_B = None
    perm_B = None
    rho_B = None
    u_B = None
    ucB = None
    vcB = None
    wcB = None
    _max_outer = prepared['max_outer'] if prepared['max_outer'] is not None else _MAX_OUTER
    _ltne_max_iter = prepared['ltne_max_iter']
    _compact_diag = prepared['compact']
    _outer_tol = float(cfg['outer_tol_K']) if cfg.get('outer_tol_K') is not None else _OUTER_TOL

    # Compressible validity-envelope mode (robustness, 2026-06-25):
    #   'raise' (default) -> ChokedFlowError on a choked/supersonic case
    #   'warn'            -> run anyway, flag the result invalid + collect msgs
    #   'off'             -> legacy silent behaviour
    _env_mode = cfg.get('envelope_mode', 'raise')
    _env_warnings = []
    # Track SIMPLE non-convergence across the outer loop so it can be surfaced
    # as a user warning (the 2D pipeline already does; 3D used to only print it
    # under the profiler). Each entry: "A@outer3" etc.
    _simple_nonconv = []

    _ltne_info = []  # per-outer {outer, iters, converged, residual}

    L, H, Lz = cfg['L'], cfg['H'], cfg['Lz']
    u_A = cfg['u_A']
    T_inA, T_inB = cfg['T_inA'], cfg['T_inB']
    P_inA = cfg['P_inA']
    P_inB = cfg.get('P_inB', P_inA)
    tpms_type = cfg['tpms_type']
    Lcell, t_wall, k_s = cfg['Lcell'], cfg['t_wall'], cfg['k_s']
    eps = cfg['eps']
    fA = cfg['fluid_A_cfg']

    # 2026-05-13 — derive D_h locally so roughness helpers can compute Re.
    _g_3d = prepared['geometry']
    D_h = _g_3d['D_h']

    dx, dy, dz = prepared['dx'], prepared['dy'], prepared['dz']
    Nx, Ny, Nz = len(dx), len(dy), len(dz)

    # Resolve streamwise geometry from dir_A
    axis_map = prepared['axes']['A']
    is_reverse = axis_map['is_reverse']
    N_cross2 = axis_map['N_cross2']
    L_stream = axis_map['L_stream']
    dcross2 = axis_map['dcross2']
    stream_real_axis = axis_map['stream_real_axis']
    solver_init = axis_map['solver_init']
    N_stream = axis_map['N_stream']
    solver_to_real_perm = axis_map['solver_to_real_perm']

    # Fluid A properties at inlet — via the registry (parity with side B, B1 1.1).
    # air: rho=air_density(T,P), cp/mu/k ignore P (value-identical to the old
    # air_* calls → golden-safe). water: incompressible registry path.
    # sco2: real-gas properties at (T,P).
    fluid_type_A = cfg.get('fluid_type_A', 'air')
    fluid_type_B = cfg.get('fluid_type_B', 'air')
    fluid_props.check_water_state(fluid_type_A, T_inA, P_inA, where='3D direct inlet A')
    fluid_props.check_water_state(fluid_type_B, T_inB, P_inB, where='3D direct inlet B')
    _mA = cfg['_models']['fluid_A'] if '_models' in cfg else fluid_props.get(fluid_type_A)
    with range_context(side='A', stage='inlet', layout='scalar'):
        rho_A = prepared['properties']['A']['rho']
        mu_A = prepared['properties']['A']['mu']
        cp_A = prepared['properties']['A']['cp']
        k_A = prepared['properties']['A']['k']

    # D-F surrogate. SIMPLE3D K_arr/cF_arr shape = (Ny_sA, Nz) where Ny_sA
    # is the solver streamwise axis = N_stream in real coords.
    # If zones enabled: per-cell K/cF via 2D grid zones broadcast over z.
    zone_cells = cfg.get('zone_grid_cells')
    _df_mode = cfg.get('df_mode', 'cfd_smooth')
    if _df_mode == 'experimental' and zone_cells:
        raise ValueError(
            "experimental calibration currently requires uniform L/t; zoned "
            "geometry remains available in CFD smooth-wall mode")
    L_mm_field = None      # (Nx, Ny, Nz) for vis; None → uniform Lcell later
    t_field_3d = None      # per-cell wall thickness
    eps_field_3d = None    # per-cell porosity if zoned
    if zone_cells:
        L_mm_field = prepared['design']['L_field_m'] * 1e3
        t_field_3d = prepared['design']['t_field_m'] * 1e3
        eps_field_3d = prepared['design']['eps_arr']
        K_field_3d, cF_field_3d = prepared['design']['K_m2'], prepared['design']['cF_per_m']
        # Real → solver coord permutation (inverse equals same tuple for 2-swaps),
        # then mean over solver Nx axis (cross1) → (N_stream, N_cross2) for K_arr.
        K_sol = K_field_3d.transpose(solver_to_real_perm)
        cF_sol = cF_field_3d.transpose(solver_to_real_perm)
        K_A_arr = np.ascontiguousarray(K_sol.mean(axis=0))
        cF_A_arr = np.ascontiguousarray(cF_sol.mean(axis=0))
        K_pred = float(K_A_arr.mean())
        cF_pred = float(cF_A_arr.mean())
        _log.info(f"[3D zones] using {len(zone_cells)} zone cells; "
                  f"K range [{K_field_3d.min():.2e}, {K_field_3d.max():.2e}]")
        # Zoned path is a uniform-only-δ exception: no asymmetric split here.
        K_pred_B, cF_pred_B = K_pred, cF_pred
    else:
        K0, cF0 = float(prepared['design']['K_m2'].flat[0]), float(prepared['design']['cF_per_m'].flat[0])
        # V2 fixed CFD closure depends on TPMS/L/t only. Both channels of the
        # same core use the same K/cF; porosity, fluid and Reynolds number do
        # not alter these coefficients.
        K_pred = K_pred_B = K0
        cF_pred = cF_pred_B = cF0
        K_A_arr = np.full((N_stream, N_cross2), K_pred)
        cF_A_arr = np.full((N_stream, N_cross2), cF_pred)

    from sjtu_tpmshx.df_surrogate.experimental_correction import (
        apply_prepared_correction, cfd_metadata)
    if _df_mode == 'experimental':
        with range_context(side='A', stage='df-application', layout='scalar'):
            K_A_arr, cF_A_arr, _df_meta_A = apply_prepared_correction(
                K_A_arr, cF_A_arr, cfg['df_application']['A'])
        K_pred = float(np.asarray(K_A_arr).mean())
        cF_pred = float(np.asarray(cF_A_arr).mean())
    else:
        _df_meta_A = cfd_metadata(K_A_arr, cF_A_arr)

    # P_ref_abs 1D closed-form seed (uses streamwise length L_stream).
    solver_fluid_type_A = fluid_props.flow_model(fluid_type_A)
    G_A = rho_A * u_A
    # C = μG/K + cF·G² where G = ρu (mass flux, constant along pipe by continuity).
    C_est = mu_A * G_A / max(K_pred, 1e-16) + cF_pred * G_A * G_A
    pressure_history_A = []
    if _mA.compressible:
        # The 1D estimate is a startup hint, not a coupled-flow verdict.
        P_out_sq = P_inA ** 2 - 2.0 * R_AIR * T_inA * C_est * L_stream
        P_ref_A = pressure_initial_reference(P_out_sq, P_inA, history=pressure_history_A)
    else:
        # sco2 Phase-A is incompressible (ρ frozen) → simple 1D Darcy-Forchheimer
        # pressure-drop seed sets the gauge level; no choke path.
        P_ref_A = max(float(P_inA - C_est * L_stream / rho_A), 1.0e4)

    # Partial inlet / outlet on the 2-axis inlet face.
    in_mask_2d, out_mask_2d = prepared['openings']['A']['inlet'], prepared['openings']['A']['outlet']
    v_inlet_field = in_mask_2d * u_A

    # ── SIMPLE A (3D, compressible) — BUILD ONLY ──
    # Consume the physical Case grid in solver coordinates for every mode.
    _sdxA, _sdyA, _sdzA = _solver_spacings(dx, dy, dz, solver_to_real_perm)
    with range_context(side='A', stage='inlet', layout='solver-initial'):
        sA = SIMPLESolver3D(
            **solver_init,
            rho=rho_A, mu=mu_A, T_in=T_inA, v_inlet=v_inlet_field,
            eps=eps, K_arr=K_A_arr, cF_arr=cF_A_arr,
            P_ref_abs=P_ref_A, fluid_type=solver_fluid_type_A,
            dx_arr=_sdxA, dy_arr=_sdyA, dz_arr=_sdzA,
            **_port_rectangles(fA, float(np.sum(dcross2))),
        )
    sA._df_metadata = _df_meta_A
    sA.pressure_iterations = pressure_history_A
    # Phase A/B/C acceleration flags (Phase A on by default; B/C opt-in).
    _apply_accel_flags(sA, cfg)
    # Water also has rho(T): an outer update must not change inlet throughput.
    # Air already captures its target in the compressible SIMPLE path.
    if fluid_type_A in ('sco2', 'water'):
        sA._massflux_target = (v_inlet_field * rho_A).copy()
    # Zoned ε → push to SIMPLE so its continuity ∇·(ε·ρ·u)=0 picks up the
    # ∇ε contribution. Uniform ε leaves the default unchanged.
    if eps_field_3d is not None:
        eps_sol = np.ascontiguousarray(
            eps_field_3d.transpose(axis_map['solver_to_real_perm'])
            if axis_map['solver_to_real_perm'] != (0, 1, 2)
            else eps_field_3d, dtype=np.float64)
        if eps_sol.shape == sA.eps_field.shape:
            sA.eps_field = eps_sol
            sA._mu_eff_field = np.ascontiguousarray(
                sA.mu_field / sA.eps_field, dtype=np.float64)
    if fluid_type_A != 'sco2':
        sA.apply_outlet_taper(n_taper=8, min_frac=0.2)
    # Rectangles set both raw BC support and staggered wall areas.
    # A.solve() deferred — build B first, then select one level of parallelism.

    # Fluid A type was resolved through the same registry path as side B.

    # ── Fluid B: cross-flow SIMPLE — BUILD ONLY (dispatch with A below) ──
    fB = cfg.get('fluid_B_cfg')
    # B1 1.1: property primitives + flow model for side B via the registry
    # (frozen-B / stiffness semantics keep using is_water_B).
    _mB = cfg['_models']['fluid_B'] if '_models' in cfg else fluid_props.get(fluid_type_B)
    sB = None
    sB_info = None
    if fB is not None:
        u_B = cfg.get('u_B', u_A)
        with range_context(side='B', stage='inlet', layout='scalar'):
            rho_B = prepared['properties']['B']['rho']   # water rho ignores P; sco2 (T,P)
            mu_B = prepared['properties']['B']['mu']     # air/water ignore P; sco2 needs P
        axis_map_B = prepared['axes']['B']
        N_stream_B = axis_map_B['N_stream']
        N_cross2_B = axis_map_B['N_cross2']
        L_stream_B = axis_map_B['L_stream']
        dcross2_B = axis_map_B['dcross2']
        perm_B = axis_map_B['solver_to_real_perm']
        K_B_arr = np.full((N_stream_B, N_cross2_B), K_pred_B)
        cF_B_arr = np.full((N_stream_B, N_cross2_B), cF_pred_B)
        if _df_mode == 'experimental':
            with range_context(side='B', stage='df-application', layout='scalar'):
                K_B_arr, cF_B_arr, _df_meta_B = apply_prepared_correction(
                    K_B_arr, cF_B_arr, cfg['df_application']['B'])
            K_pred_B = float(np.asarray(K_B_arr).mean())
            cF_pred_B = float(np.asarray(cF_B_arr).mean())
        else:
            _df_meta_B = cfd_metadata(K_B_arr, cF_B_arr)
        G_B = rho_B * u_B
        C_B = mu_B * G_B / max(K_pred_B, 1e-16) + cF_pred_B * G_B * G_B
        solver_fluid_type_B = fluid_props.flow_model(fluid_type_B)
        pressure_history_B = []
        if _mB.compressible:
            P_out_sq_B = P_inB ** 2 - 2.0 * R_AIR * T_inB * C_B * L_stream_B
            P_ref_B = pressure_initial_reference(P_out_sq_B, P_inB, history=pressure_history_B)
        else:
            P_ref_B = float(P_inB - C_B * L_stream_B / rho_B)
            P_ref_B = max(P_ref_B, 1.0e4)
        in_mask_B, out_mask_B = prepared['openings']['B']['inlet'], prepared['openings']['B']['outlet']
        v_inlet_B = in_mask_B * u_B
        # Zoned ε for sB: same eps_field but transposed via B's perm (built
        # below after sB construction).
        _sdxB, _sdyB, _sdzB = _solver_spacings(dx, dy, dz, perm_B)
        with range_context(side='B', stage='inlet', layout='solver-initial'):
            sB = SIMPLESolver3D(
                **axis_map_B['solver_init'],
                rho=rho_B, mu=mu_B, T_in=T_inB, v_inlet=v_inlet_B,
                eps=eps, K_arr=K_B_arr, cF_arr=cF_B_arr,
                P_ref_abs=P_ref_B, fluid_type=solver_fluid_type_B,
                dx_arr=_sdxB, dy_arr=_sdyB, dz_arr=_sdzB,
                **_port_rectangles(fB, float(np.sum(dcross2_B))),
            )
        sB._df_metadata = _df_meta_B
        sB.pressure_iterations = pressure_history_B
        # Mirror Phase A/B/C flags onto sB (sweep config consistent with sA).
        _apply_accel_flags(sB, cfg)
        if fluid_type_B in ('sco2', 'water'):
            sB._massflux_target = (v_inlet_B * rho_B).copy()
        # Zoned ε for sB.
        if eps_field_3d is not None:
            eps_sol_B = np.ascontiguousarray(
                eps_field_3d.transpose(axis_map_B['solver_to_real_perm'])
                if axis_map_B['solver_to_real_perm'] != (0, 1, 2)
                else eps_field_3d, dtype=np.float64)
            if eps_sol_B.shape == sB.eps_field.shape:
                sB.eps_field = eps_sol_B
                sB._mu_eff_field = np.ascontiguousarray(
                    sB.mu_field / sB.eps_field, dtype=np.float64)
        if fluid_type_B != 'sco2':
            sB.apply_outlet_taper(n_taper=8, min_frac=0.2)
        # Rectangles set both raw BC support and staggered wall areas.
        # sB.solve deferred — dispatched with sA below.
        sB_info = dict(
            axis_map=axis_map_B,
            u_B=u_B, rho_B=rho_B, mu_B=mu_B,
            G_B=G_B, T_inB=T_inB,
        )
        # ── Dual-side SIMPLE: parallel sides or parallel sweeps ──
        # SolverConfig propagation (2026-07-12): this call used to pass NEITHER
        # max_iter NOR tol, so the dual-fluid INITIAL solve silently fell back
        # to the helper's signature defaults (max_iter=2000, tol=None →
        # _simple_tol_default() with cfg=None, which skips the cfg['tol_simple']
        # branch). Only the A-alone branch below and the `post` re-solves obeyed
        # SolverConfig — i.e. a user-set max_iter_simple / tol_simple governed
        # every SIMPLE solve EXCEPT the first one. Same resolution helpers as
        # the A-alone branch, so a config leaving both knobs at None (and no
        # TPMSHX_SIMPLE_TOL) is bit-identical to before.
        _init_res = _run_two_simple(
            sA, sB,
            max_iter=_simple_max_iter(cfg, 2000),
            tol=_simple_tol_default(cfg),
            cancel_check=control.cancel_check)
        if _init_res and _init_res[0] is not None and not _init_res[0][0]:
            _simple_nonconv.append(
                f"A@init[{getattr(sA, 'exit_reason', '?')}]")
        if _init_res and _init_res[1] is not None and not _init_res[1][0]:
            _simple_nonconv.append(
                f"B@init[{getattr(sB, 'exit_reason', '?')}]")
        # LTNE fluid B velocity: full vector remapped to real coordinates.
        ucB, vcB, wcB = _solver_velocity_to_real(
            sB, axis_map_B, (Nx, Ny, Nz))
        Tb_presc = None  # let LTNE solve Tb from convection
    else:
        # No B: run A alone (serial)
        _prof_t_a0 = _time.perf_counter() if _prof_3d_enabled() else None
        with range_context(side='A', stage='initial', layout='solver-cell(cross1,stream,cross2)'):
            _a0_conv, _a0_it = sA.solve(max_iter=_simple_max_iter(cfg, 2000),
                                        tol=_simple_tol_default(cfg),
                                        verbose=False,
                                        cancel_check=control.cancel_check)
        if not _a0_conv:
            _simple_nonconv.append(
                f"A@init[{getattr(sA, 'exit_reason', '?')}]")
        if _prof_t_a0 is not None:
            _log.info(f"[PROF] initial SIMPLE_A (serial, no-B) "
                      f"{_time.perf_counter()-_prof_t_a0:7.2f}s  "
                      f"iters={_a0_it}  conv={_a0_conv}  "
                      f"(cap={_simple_max_iter(cfg, 2000)})")
        ucB = np.zeros((Nx, Ny, Nz))
        vcB = np.zeros((Nx, Ny, Nz))
        wcB = np.zeros((Nx, Ny, Nz))
        Tb_presc = np.full((Nx, Ny, Nz), T_inB, dtype=np.float64)

    # LTNE inputs — Fluid A and B via the registry. air/water ignore P
    # (value-identical); sco2 needs P (real-gas).
    with range_context(side='B', stage='inlet', layout='scalar'):
        cp_B = prepared['properties']['B']['cp']
        k_B = prepared['properties']['B']['k']
        rho_B_ltne = prepared['properties']['B']['rho']   # water rho ignores P; sco2 (T,P)
    eps_arr = prepared['design']['eps_arr']
    # Per-cell single-channel void fraction (#2/#3). When zoned, eps varies
    # with (L, t) over space, so K_ffA/B and K_ss must track local eps too.
    # Per-side (asymmetric offset-isosurface δ) single-channel void fractions.
    # δ=0 → both are the symmetric eps_f_arr object (bit-identical legacy path);
    # δ≠0 → geometry-derived A:B split preserving total eps_arr. Threaded into
    # the LTNE kernel (eps_A/eps_B), Q/dP extraction and balance projection.
    eps_fA_arr, eps_fB_arr = prepared['design']['eps_A'], prepared['design']['eps_B']
    K_ffA = eps_fA_arr * k_A
    K_ffB = eps_fB_arr * k_B
    # Optional thermal dispersion: K_disp = C * ρ·cp·|u|·D_h added to K_ff.
    # Off by default (disp_C_* = 0). Standard homogenisation has K_ff = ε·k_f
    # (molecular only); at high Pe the effective fluid conductivity is larger
    # due to tortuous-channel mixing. Turn on by setting disp_C_A / disp_C_B
    # in the config (typical values 0.05-0.3 depending on TPMS type). D_h
    # here uses the uniform cell geometry; once zoned K-field support lands,
    # promote this to per-cell using local D_h and |u|.
    disp_C_A = float(cfg.get('disp_C_A', 0.0))
    disp_C_B = float(cfg.get('disp_C_B', 0.0))
    if disp_C_A > 0.0:
        D_h_A = _g_3d['D_h']
        K_disp_A = disp_C_A * rho_A * cp_A * abs(u_A) * D_h_A
        K_ffA = K_ffA + K_disp_A
    if disp_C_B > 0.0:
        D_h_B = _g_3d['D_h']
        K_disp_B = disp_C_B * rho_B_ltne * cp_B * abs(cfg.get('u_B', u_A)) * D_h_B
        K_ffB = K_ffB + K_disp_B
    # K_ss = χ_s(type, ε) · (1 − eps_local) · k_s, tracks zoned porosity (#3).
    # B2 (2026-07-06): χ_s from unit-cell homogenization fit (chi_s_eff).
    K_ss = prepared['design']['K_ss']

    return _Problem3D(
        D_h=D_h,
        G_A=G_A,
        G_B=G_B,
        H=H,
        K_disp_A=K_disp_A,
        K_disp_B=K_disp_B,
        K_ffA=K_ffA,
        K_ffB=K_ffB,
        K_pred=K_pred,
        K_pred_B=K_pred_B,
        K_ss=K_ss,
        L=L,
        L_mm_field=L_mm_field,
        L_stream=L_stream,
        L_stream_B=L_stream_B,
        Lcell=Lcell,
        Lz=Lz,
        Nx=Nx,
        Ny=Ny,
        Nz=Nz,
        P_inA=P_inA,
        P_inB=P_inB,
        T_inA=T_inA,
        T_inB=T_inB,
        Tb_presc=Tb_presc,
        _compact_diag=_compact_diag,
        _env_mode=_env_mode,
        _env_warnings=_env_warnings,
        _ltne_info=_ltne_info,
        _ltne_max_iter=_ltne_max_iter,
        _mA=_mA,
        _mB=_mB,
        _max_outer=_max_outer,
        _outer_tol=_outer_tol,
        _simple_nonconv=_simple_nonconv,
        axis_map=axis_map,
        axis_map_B=axis_map_B,
        cF_pred=cF_pred,
        cF_pred_B=cF_pred_B,
        cfg=cfg,
        cp_A=cp_A,
        cp_B=cp_B,
        disp_C_A=disp_C_A,
        disp_C_B=disp_C_B,
        dx=dx,
        dy=dy,
        dz=dz,
        eps=eps,
        eps_arr=eps_arr,
        eps_fA_arr=eps_fA_arr,
        eps_fB_arr=eps_fB_arr,
        fA=fA,
        fB=fB,
        fluid_type_A=fluid_type_A,
        fluid_type_B=fluid_type_B,
        in_mask_2d=in_mask_2d,
        in_mask_B=in_mask_B,
        is_reverse=is_reverse,
        k_s=k_s,
        mu_A=mu_A,
        mu_B=mu_B,
        out_mask_2d=out_mask_2d,
        out_mask_B=out_mask_B,
        perm_B=perm_B,
        rho_A=rho_A,
        rho_B=rho_B,
        rho_B_ltne=rho_B_ltne,
        sA=sA,
        sB=sB,
        sB_info=sB_info,
        solver_to_real_perm=solver_to_real_perm,
        stream_real_axis=stream_real_axis,
        t_field_3d=t_field_3d,
        t_wall=t_wall,
        tpms_type=tpms_type,
        u_A=u_A,
        u_B=u_B,
        ucB=ucB,
        vcB=vcB,
        wcB=wcB,
    )


def _build_hv_machinery(prob: _Problem3D):
    """Seam-B extraction (P1.5, 2026-07-20): h_v machinery factory --
    the five h_v/transport closures (now capturing THIS function's
    read-only params) + the initial bulk h_v fields. Moved VERBATIM
    from _run_3d_stack; returns callables + fields as the cross-seam
    bundle. Contract: bit-identical behavior (golden gate).
    """
    D_h = prob.D_h
    L_mm_field = prob.L_mm_field
    Lcell = prob.Lcell
    Nx = prob.Nx
    Ny = prob.Ny
    Nz = prob.Nz
    P_inA = prob.P_inA
    P_inB = prob.P_inB
    T_inA = prob.T_inA
    T_inB = prob.T_inB
    eps = prob.eps
    fluid_type_A = prob.fluid_type_A
    fluid_type_B = prob.fluid_type_B
    mu_A = prob.mu_A
    mu_B = prob.mu_B
    rho_A = prob.rho_A
    rho_B = prob.rho_B
    sB = prob.sB
    t_field_3d = prob.t_field_3d
    tpms_type = prob.tpms_type
    u_A = prob.u_A
    cfg = prob.cfg
    # Conditionally-bound cross-seam names (surgery tool definite-
    # assignment pass): None-init so the unconditional return below
    # cannot raise UnboundLocalError on guarded paths. Downstream
    # reads keep their original guards.
    h_vB_field = None
    # The producer records fixed geometry and the original air bulk closure.
    # Local Nu and fluid properties still follow the current numerical state.
    from sjtu_tpmshx.models.nu_correlations import NU_LAM_FLOOR as _NU_LAM_FLOOR  # Hagen-Poiseuille single-tube limit
    cfg['sco2_nu_observations'] = {'A': {}, 'B': {}}
    u_B_val = cfg.get('u_B', u_A)

    def _fluid_transport_props(fluid_type, T_side, P_side):
        fluid_props.check_water_state(fluid_type, T_side, P_side,
                                      where='3D h_v property refresh')
        m = fluid_props.get(fluid_type, sco2_nu=cfg.get('sco2_nu'))
        # air/water ignore P (value-identical to the old T-only calls → golden-
        # safe); sco2 is real-gas and REQUIRES P.
        with range_context(layout='scalar-hv-property'):
            rho = float(m.rho(T_side, P_side))
            mu = float(m.mu(T_side, P_side))
            k_f = float(m.k(T_side, P_side))
            if not m.compressible:               # water/sco2: Pr-substitution (3D: k guard)
                Pr_f = float(m.cp(T_side, P_side)) * mu / max(k_f, 1e-30)
                return rho, mu, k_f, Pr_f
            return rho, mu, k_f, None

    def _nu_for_fluid(fluid_type, Re_val, eps_f_val, L_mm_val, D_h_mm_val, Pr_val=None):
        Re_eff = max(float(Re_val), 1.0)
        m = fluid_props.get(fluid_type, sco2_nu=cfg.get('sco2_nu'))
        # water: Pr-substitution with 7.0 fallback; air ignores Pr (built-in default).
        Pr = float(Pr_val if Pr_val is not None else 7.0) if not m.compressible else None
        Nu_val = m.nu(tpms_type, Re_eff, float(eps_f_val), float(L_mm_val),
                      float(D_h_mm_val), Pr)
        return max(float(Nu_val), _NU_LAM_FLOOR)

    def _build_hv_field_3d(L_fld, t_fld, u_side, T_side, P_side, fluid_type='air', *, side):
        """Bulk h_v = A_0(L,t) × H_sf(Re_bulk) on 3D mesh."""
        if fluid_type == 'air':
            return np.array(cfg['thermal_geometry']['air_bulk_hv'][side], copy=True)
        if L_fld is None:
            g = cfg['thermal_geometry']['uniform']
            rho, mu, k_f, Pr_f = _fluid_transport_props(fluid_type, T_side, P_side)
            D_h_m = max(float(g['D_h']), 1e-12)
            Re_val = rho * max(abs(float(u_side)), 0.0) * D_h_m / max(mu, 1e-30)
            record_raw_nu_range(fluid_type, tpms_type, Re_val)
            Nu_val = _nu_for_fluid(
                fluid_type, Re_val, float(g['epsilon']) / 2.0,
                Lcell, D_h_m * 1000.0, Pr_f,
            )
            return np.full((Nx, Ny, Nz), g['A_0'] * Nu_val * k_f / D_h_m, dtype=np.float64)
        out = np.empty((Nx, Ny, Nz), dtype=np.float64)
        raw_Re = np.empty_like(out)
        rho, mu, k_f, Pr_f = _fluid_transport_props(fluid_type, T_side, P_side)
        for i in range(Nx):
            for j in range(Ny):
                for k in range(Nz):
                    Li = float(L_fld[i, j, k])
                    g = {key: value[i, j, k] for key, value in cfg['thermal_geometry']['fields'].items()}
                    D_h_m = max(float(g['D_h']), 1e-12)
                    Re_val = rho * max(abs(float(u_side)), 0.0) * D_h_m / max(mu, 1e-30)
                    raw_Re[i, j, k] = Re_val
                    with range_context(layout='scalar-zoned-call'):
                        Nu_val = _nu_for_fluid(
                            fluid_type, Re_val, float(g['epsilon']) / 2.0,
                            Li, D_h_m * 1000.0, Pr_f,
                        )
                    out[i, j, k] = g['A_0'] * Nu_val * k_f / D_h_m
        with range_context(layout='real-cell(x,y,z)-bulk-Re'):
            record_raw_nu_range(fluid_type, tpms_type, raw_Re)
        return out

    # The caller supplies the full local pore speed, independent of port axis.
    # Retain the existing Re/Nu floors for true low-speed cells. Applying a
    # bulk-fitted scalar correlation locally remains a closure assumption.
    def _build_hv_local_3d(
        L_fld, t_fld, speed_field, T_side, P_side, fluid_type='air',
        A_0_scalar=None, observation=None,
    ):
        """Per-cell h_v from Re = ρ |U| D_h / μ and the existing Nu floor."""
        u_abs = np.abs(speed_field) + 1e-12
        # Uniform sCO2 evaluates ρ,μ,k,Pr at the lagged local temperature.
        # Without a temperature field, use inlet properties for initialization;
        # air/water retain the scalar-inlet property branch below.
        if fluid_type == 'sco2' and L_fld is None and np.ndim(T_side) > 0:
            g = cfg['thermal_geometry']['uniform']
            return _sco2_hv_local_field(T_side, P_side, u_abs,
                                        g['A_0'], g['D_h'], tpms_type, Lcell,
                                        sco2_nu=cfg.get('sco2_nu'), observation=observation)
        rho, mu, k_f, Pr_f = _fluid_transport_props(fluid_type, T_side, P_side)
        if L_fld is None:
            g = cfg['thermal_geometry']['uniform']
            A_0 = g['A_0']; D_h_m = g['D_h']
            D_h_mm = D_h_m * 1000.0
            Re_loc = rho * u_abs * D_h_m / mu
            record_raw_nu_range(fluid_type, tpms_type, Re_loc)
            _m = fluid_props.get(fluid_type, sco2_nu=cfg.get('sco2_nu'))
            _Pr = (None if _m.compressible
                   else float(Pr_f if Pr_f is not None else 7.0))
            Nu_loc = local_nusselt(_m, tpms_type, Re_loc,
                                   g['epsilon'] / 2.0, Lcell, D_h_mm, _Pr)
            H_sf_loc = Nu_loc * k_f / D_h_m
            return A_0 * H_sf_loc
        # Zoned (L,t): consume the prepared per-cell geometry.
        out = np.empty((Nx, Ny, Nz), dtype=np.float64)
        raw_Re = np.empty_like(out)
        for i in range(Nx):
            for j in range(Ny):
                for k in range(Nz):
                    L_ij = float(L_fld[i, j, k])
                    g = {key: value[i, j, k] for key, value in cfg['thermal_geometry']['fields'].items()}
                    D_h_m_l = g['D_h']
                    Re_l = rho * float(u_abs[i,j,k]) * D_h_m_l / mu
                    raw_Re[i, j, k] = Re_l
                    # single-stream: ε_f = ε/2
                    with range_context(layout='scalar-zoned-call'):
                        Nu_l = _nu_for_fluid(
                            fluid_type, Re_l, g['epsilon'] / 2.0,
                            L_ij, D_h_m_l * 1000.0, Pr_f,
                        )
                    out[i,j,k] = g['A_0'] * Nu_l * k_f / D_h_m_l
        record_raw_nu_range(fluid_type, tpms_type, raw_Re)
        return out

    # Per-side h_v geometric multiplier for asymmetric offset-isosurface δ.
    # h_v = A_0·Nu·k/D_h; for δ≠0 each side's (A_0, D_h) shifts. The ratio is
    # taken vs asym_geometry's OWN δ=0 reference (same method) so it is EXACTLY
    # 1.0 at δ=0 → multiplying the existing symmetric h_v is bit-identical
    # (×1.0). k_f cancels; Nu's ε arg is inert (air/water Nu ignore ε); the
    # inlet-reference ratio is applied to bulk and later local-Re h_v. Re/Nu
    # floors can put side and reference on different branches; the diameter
    # ratio alone does not prove speed independence. Captures the geometric
    # Nu/area effect; the residual (κ_Nu) is a CFD calibration left to
    # ingest_cfd_kappa (Nu is secondary per the Phase-1 plan; dP is primary).
    def _hv_side_geom_ratio(fluid_type, u_side, T_side, P_side, side):
        if float(cfg.get('delta_levelset', 0.0)) == 0.0:
            return 1.0
        A0_s, Dh_s, A0_r, Dh_r = cfg['thermal_geometry']['side_geometry'][side]
        _rho, _mu, _kf, _Pr = _fluid_transport_props(fluid_type, T_side, P_side)

        def _hv(A0, Dh):
            Dh_m = max(float(Dh), 1e-12)
            Re = _rho * max(abs(float(u_side)), 0.0) * Dh_m / max(_mu, 1e-30)
            record_raw_nu_range(fluid_type, tpms_type, Re)
            Nu = _nu_for_fluid(fluid_type, Re, 0.5 * float(eps),
                               Lcell, Dh_m * 1000.0, _Pr)
            return A0 * Nu / Dh_m
        with range_context(layout='scalar-geometry-reference'):
            _ref = _hv(A0_r, Dh_r)
        with range_context(layout='scalar-geometry-side'):
            return (_hv(A0_s, Dh_s) / _ref) if _ref > 0 else 1.0

    with range_context(side='A', stage='inlet', layout='scalar-geometry-ratio'):
        _hv_ratio_A = _hv_side_geom_ratio(fluid_type_A, u_A, T_inA, P_inA, 'A')
    with range_context(side='B', stage='inlet', layout='scalar-geometry-ratio'):
        _hv_ratio_B = _hv_side_geom_ratio(fluid_type_B, u_B_val, T_inB, P_inB, 'B')

    # Initial bulk h_v (used at outer=0 before SIMPLE solves; becomes local
    # after first outer iter when ucA/B are available).
    with range_context(side='A', stage='inlet', layout='scalar-hv-bulk'):
        h_vA_field = _build_hv_field_3d(
            L_mm_field, t_field_3d, u_A, T_inA, P_inA, fluid_type_A, side='A')
    h_vA_field = _apply_roughness_h_v(
        h_vA_field, fluid_type_A, rho_A, mu_A, u_A, D_h, resolved=cfg['roughness_resolved'])
    h_vA_field = h_vA_field * _hv_ratio_A
    if sB is not None:
        with range_context(side='B', stage='inlet', layout='scalar-hv-bulk'):
            h_vB_field = _build_hv_field_3d(
                L_mm_field, t_field_3d, u_B_val, T_inB, P_inB, fluid_type_B, side='B')
        h_vB_field = _apply_roughness_h_v(
            h_vB_field, fluid_type_B, rho_B, mu_B, u_B_val, D_h, resolved=cfg['roughness_resolved'])
        h_vB_field = h_vB_field * _hv_ratio_B
    else:
        # No B fluid solver → "no B fluid" should mean ZERO B-side coupling,
        # not "infinite reservoir at T_inB". The previous behaviour kept
        # h_vB at the bulk Nu·k/D_h value while Tb_prescribed pinned Tb to
        # T_inB everywhere, so the LTNE source term h_vB·(Ts−Tb) acted as
        # a phantom infinite heat sink/source on the solid. Setting
        # h_vB_field=0 makes the solid energy equation degenerate cleanly
        # to the single-fluid LTNE limit driven only by Q_sA.
        h_vB_field = np.zeros((Nx, Ny, Nz), dtype=np.float64)

    return _HvMachinery(
        _build_hv_local_3d=_build_hv_local_3d,
        _hv_ratio_A=_hv_ratio_A,
        _hv_ratio_B=_hv_ratio_B,
        h_vA_field=h_vA_field,
        h_vB_field=h_vB_field,
        u_B_val=u_B_val,
    )


def _extract_3d_metrics(prob: _Problem3D, outer: _OuterState):
    """Build final-flow compatibility summaries and real-axis display fields.

    These reporting values retain final-pressure property calls and warnings.
    Formal postprocessing instead reduces the detached native thermal evidence.
    """
    L_mm_field = prob.L_mm_field
    Lcell = prob.Lcell
    Nx = prob.Nx
    Ny = prob.Ny
    Nz = prob.Nz
    P_inA = prob.P_inA
    P_inB = prob.P_inB
    T_inA = prob.T_inA
    T_inB = prob.T_inB
    Ta = outer.Ta
    Tb = outer.Tb
    Ts = outer.Ts
    _assemble_real_velocity = outer._assemble_real_velocity
    cp_A = prob.cp_A
    cp_B = prob.cp_B
    dx = prob.dx
    dy = prob.dy
    dz = prob.dz
    eps = prob.eps
    fA = prob.fA
    fB = prob.fB
    fluid_type_A = prob.fluid_type_A
    fluid_type_B = prob.fluid_type_B
    h_vB_field = outer.h_vB_field
    is_reverse = prob.is_reverse
    sA = prob.sA
    sB = prob.sB
    sB_info = prob.sB_info
    solver_to_real_perm = prob.solver_to_real_perm
    stream_real_axis = prob.stream_real_axis
    ucB = prob.ucB
    vcB = prob.vcB
    wcB = prob.wcB
    cfg = prob.cfg
    # Conditionally-bound cross-seam names (surgery tool definite-
    # assignment pass): None-init so the unconditional return below
    # cannot raise UnboundLocalError on guarded paths. Downstream
    # reads keep their original guards.
    P_real_B = None
    Q_enthalpy_A = None
    dP_B = None
    m_dot_B_phys_in = None
    m_dot_B_phys_out = None
    m_dot_B_simple = None
    vmag_B = None
    # ── Extract metrics + fields ──
    # Solid-fluid exchange is diagnostic; headline Q uses A-side advection.
    cell_vol = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]
    Q_solid_B = float(np.sum(h_vB_field * (Ts - Tb) * cell_vol))

    out_idx = 0 if is_reverse else -1
    T_A_out = float(np.mean(np.take(Ta, out_idx, axis=stream_real_axis)))
    T_B_out = None
    if sB is not None:
        axis_B = sB_info['axis_map']['stream_real_axis']
        out_idx_B = 0 if sB_info['axis_map']['is_reverse'] else -1
        T_B_out = float(np.mean(np.take(Tb, out_idx_B, axis=axis_B)))
    # Mass flow from the solver's actual inlet face: ρ·v_face × full-face area.
    # sA.v has shape (solver Nx, solver Ny+1, solver Nz); inlet face is
    # j=0. The prescribed v_face already contains the open-area fraction f.
    # Q_enthalpy via **SIMPLE-native** mass flow (2026-04-25 FV hardening).
    # Earlier used cell-centered ucA/vcA/wcA reconstructed via
    # _solver_velocity_to_real, but that cell-averaged interpolation lost
    # ~40% mass flow on wall-refined grids (the averaging leaked no-slip
    # wall cells into the mean). Now m_dot comes directly from the SIMPLE
    # staggered v-face + ρ-face which the pressure-correction enforces to
    # be divergence-free. T_out is a pipe-masked mean on the real outlet
    # face using Ta/Tb cell-centered values.
    #
    # _face_flux_weights / _mass_weighted_T_out / _real_outlet_slice /
    # _simple_mass_flow are now module-level (hoisted 2026-05-15) so they can
    # be unit-tested for stagnant-cell suppression. `eps_f_per_side` is
    # passed explicitly instead of captured by closure.

    # LTNE uses ε_A = ε_B = ε/2 per side (symmetric 2-fluid split). Metric
    # must mirror that so m_dot ≡ ∫ ε_A·ρ·u·dA matches the solver's
    # internal advective mass flow.
    eps_f_per_side = 0.5 * float(eps)   # ε_A (symmetric)
    # Asymmetric per-side single-channel void fractions (offset-isosurface δ).
    # None at δ=0 → symmetric 0.5·ε path (bit-identical). δ≠0 → per-side ε_side
    # so m_dot/Q weight by the actual channel void fraction, not 0.5·ε
    # (else ṁ_A/ṁ_B mis-scale by split/0.5 on the asymmetric geometry).
    _eps_ov_A, _eps_ov_B = _prepared_eps_overrides(cfg, eps)

    # Fluid A — unified face-flux weights for T_out and m_dot consistency
    m_dot_A_simple = _simple_mass_flow(sA, fA['dir'], eps_f_per_side=eps_f_per_side,
                                       eps_side_override=_eps_ov_A)
    T_A_out_face = _real_outlet_slice(Ta, fA['dir'])
    T_A_out = _mass_weighted_T_out(T_A_out_face, sA, fA['dir'], eps_f_per_side,
                                   eps_side_override=_eps_ov_A)
    # A pair containing sCO2 is solved in true enthalpy for BOTH streams, so
    # report the same boundary-face quantity for both fluids. Other routes
    # retain cp·ΔT unless the completed thermal solve supplied a model-h ledger.
    _true_h_pair = 'sco2' in (fluid_type_A, fluid_type_B)
    if _true_h_pair:
        from sjtu_tpmshx.solvers.ltne_enthalpy_3d import _h_scalar, _prop_field
        _P_A_real = (sA.P_ref_abs + sA.P).transpose(solver_to_real_perm)
        if is_reverse:
            _P_A_real = np.flip(_P_A_real, axis=stream_real_axis)
        _P_A_out = _real_outlet_slice(_P_A_real, fA['dir'])
        with range_context(side='A', stage='final', layout='outlet-cell-face(real-transverse-axes)'):
            h_A_out = _mass_weighted_h_out(
                T_A_out_face, _P_A_out,
                lambda T, P: _prop_field('H', T, P, fluid_type_A), sA, fA['dir'],
                eps_f_per_side, eps_side_override=_eps_ov_A)
        with range_context(side='A', stage='final', layout='scalar-inlet-reference'):
            Q_enthalpy_A = abs(m_dot_A_simple * (
                _h_scalar(float(T_inA), P_inA, fluid_type_A) - h_A_out))
    else:
        with range_context(side='A', stage='final', layout='outlet-cell-face(real-transverse-axes)'):
            record_temperature_ranges(fluid_type_A, T_A_out_face)
        Q_enthalpy_A = abs(m_dot_A_simple * cp_A * (T_inA - T_A_out))

    # Fluid B
    Q_enthalpy_B = 0.0
    if sB is not None:
        m_dot_B_simple = _simple_mass_flow(sB, fB['dir'], eps_f_per_side=eps_f_per_side,
                                           eps_side_override=_eps_ov_B)
        T_B_out_face = _real_outlet_slice(Tb, fB['dir'])
        T_B_out = _mass_weighted_T_out(T_B_out_face, sB, fB['dir'], eps_f_per_side,
                                        eps_side_override=_eps_ov_B)
        # m_dot variants for diagnostic
        m_dot_B_phys_in = float(np.sum(_face_flux_weights(
            sB, fB['dir'], face='real_inlet', eps_mode='physical')))
        m_dot_B_phys_out = float(np.sum(_face_flux_weights(
            sB, fB['dir'], face='real_outlet', eps_mode='physical')))
        if _true_h_pair:
            _P_B_real_h = (sB.P_ref_abs + sB.P).transpose(
                sB_info['axis_map']['solver_to_real_perm'])
            if sB_info['axis_map']['is_reverse']:
                _P_B_real_h = np.flip(
                    _P_B_real_h, axis=sB_info['axis_map']['stream_real_axis'])
            _P_B_out = _real_outlet_slice(_P_B_real_h, fB['dir'])
            with range_context(side='B', stage='final', layout='outlet-cell-face(real-transverse-axes)'):
                h_B_out = _mass_weighted_h_out(
                    T_B_out_face, _P_B_out,
                    lambda T, P: _prop_field('H', T, P, fluid_type_B), sB, fB['dir'],
                    eps_f_per_side,
                    eps_side_override=_eps_ov_B)
            with range_context(side='B', stage='final', layout='scalar-inlet-reference'):
                Q_enthalpy_B = abs(m_dot_B_simple * (
                    _h_scalar(float(T_inB), P_inB, fluid_type_B) - h_B_out))
        else:
            with range_context(side='B', stage='final', layout='outlet-cell-face(real-transverse-axes)'):
                record_temperature_ranges(fluid_type_B, T_B_out_face)
            Q_enthalpy_B = abs(m_dot_B_simple * cp_B * (T_inB - T_B_out))

    # Reported duties use a different pressure anchor from the last true-h
    # kernel. Their mismatch alone cannot establish a kernel closure defect.
    Q_AB_imbalance_rel = float('nan')
    if (sB is not None and (fluid_type_A == 'sco2' or fluid_type_B == 'sco2')
            and Q_enthalpy_A > 1.0 and Q_enthalpy_B > 1.0):
        Q_AB_imbalance_rel = (abs(Q_enthalpy_A - Q_enthalpy_B)
                              / max(Q_enthalpy_A, Q_enthalpy_B))
        if Q_AB_imbalance_rel > 0.10:
            import warnings as _w5
            _w5.warn(
                f"[sCO2 3D energy] A/B enthalpy duties differ by "
                f"{Q_AB_imbalance_rel*100:.0f}% (Q_A={Q_enthalpy_A/1e6:.2f} MW, "
                f"Q_B={Q_enthalpy_B/1e6:.2f} MW). The reported duty balance "
                "did not close; compare the last true-h ledger and pressure "
                "sources before attributing the discrepancy to the kernel.", stacklevel=2)

    # Use the actual last thermal model-h flux, before any final post update.
    # Its presence identifies the solved route without duplicating its gate.
    model_balance = (prob._ltne_info[-1].get('model_h_balance')
                     if prob._ltne_info else None)
    if model_balance is not None:
        sides = (model_balance['sides']['A'], model_balance['sides']['B'])
        Q_enthalpy_A, Q_enthalpy_B = (
            abs(side['convective_inward_W'])
            if side['physical_boundary_complete'] and np.isfinite(side['convective_inward_W'])
            else float('nan') for side in sides)
    # Headline duty remains A-side advection; inlet diffusion belongs only
    # to the complete energy ledger, not this convective heat-duty report.
    Q = Q_enthalpy_A

    dP = float(SIMPLESolver3D.extract_dP_face_extrap(sA))

    uc_real, vc_real, wc_real = _assemble_real_velocity()
    vmag = np.sqrt(uc_real ** 2 + vc_real ** 2 + wc_real ** 2)

    # P field → real coords via solver perm. DISPLAY ABSOLUTE pressure anchored
    # so the INLET reads exactly the user-input P_in — identical convention to
    # the 2D-native path (run_calculation.py:821, P_fA = P_inA + (P_g - P_ref
    # _inlet)). SIMPLE's self.P is the gauge field (outlet pinned ~0, inlet ≈
    # dP); abs = (P_in - dP) + gauge ⇒ inlet=P_in, outlet=P_in-dP. Pure baseline
    # shift, physics-free — dP itself is reported via extract_dP_face_extrap
    # (line above), and this anchor does NOT depend on the P_ref_abs
    # reconstruction (which for
    # water is a fixed 1D seed, not loop-converged → would over-shoot the inlet).
    P_disp_A = (P_inA - dP) + sA.P
    P_real = np.ascontiguousarray(P_disp_A.transpose(solver_to_real_perm))
    P_kPa = P_real / 1000.0
    L_mm = (L_mm_field.copy() if L_mm_field is not None
            else np.full((Nx, Ny, Nz), Lcell, dtype=np.float64))

    # Fluid B fields (if sB solved): real-coord P + velocity magnitude
    if sB is not None:
        axis_map_B = sB_info['axis_map']
        perm_B = axis_map_B['solver_to_real_perm']
        dP_B = float(SIMPLESolver3D.extract_dP_face_extrap(sB))
        # ABSOLUTE pressure anchored so inlet == input P_inB (same convention as
        # fluid A and the 2D path). Works for both water (incompressible) and
        # air B without depending on the P_ref_abs reconstruction.
        P_disp_B = (P_inB - dP_B) + sB.P
        P_real_B = np.ascontiguousarray(P_disp_B.transpose(perm_B))
        # approach-(a) reverse convention: sB.P is in SOLVER coords (inlet at
        # solver y=0, high P). For a reverse-dir fluid the real inlet is at the
        # OPPOSITE stream end, so the pressure must be spatially flipped along
        # the real stream axis — exactly like _solver_velocity_to_real and the
        # LTNE temperature solve. Pressure is a scalar, so NO sign change
        # (unlike the stream velocity component). Without this flip the
        # displayed P_B put the inlet's high pressure at the real OUTLET end.
        # The constant baseline shift commutes with transpose+flip.
        # Display-only field (feeds the vis panels; no physics consumes it).
        if axis_map_B.get('is_reverse'):
            P_real_B = np.ascontiguousarray(
                np.flip(P_real_B, axis=axis_map_B['stream_real_axis']))
        vmag_B = np.sqrt(ucB ** 2 + vcB ** 2 + wcB ** 2)
    else:
        P_real_B = None
        vmag_B = None
        dP_B = 0.0

    return _Metrics3D(
        L_mm=L_mm,
        P_kPa=P_kPa,
        P_real=P_real,
        P_real_B=P_real_B,
        Q=Q,
        Q_AB_imbalance_rel=Q_AB_imbalance_rel,
        Q_enthalpy_A=Q_enthalpy_A,
        Q_enthalpy_B=Q_enthalpy_B,
        Q_solid_B=Q_solid_B,
        T_A_out=T_A_out,
        T_B_out=T_B_out,
        cell_vol=cell_vol,
        dP=dP,
        dP_B=dP_B,
        m_dot_A_simple=m_dot_A_simple,
        m_dot_B_phys_in=m_dot_B_phys_in,
        m_dot_B_phys_out=m_dot_B_phys_out,
        m_dot_B_simple=m_dot_B_simple,
        uc_real=uc_real,
        vc_real=vc_real,
        vmag=vmag,
        vmag_B=vmag_B,
        wc_real=wc_real,
    )


def _assemble_3d_verdict(prob: _Problem3D, outer: _OuterState, met: _Metrics3D) -> tuple[dict, dict]:
    """Return compatibility fields and explicit final-state diagnostics.

    Thermal evidence was detached by the outer loop. These reporting reductions
    retain their distinct final-flow timing and do not replace native metrics.
    """
    H = prob.H
    K_ffA = prob.K_ffA
    K_ffB = outer.K_ffB
    K_ss = prob.K_ss
    L = prob.L
    L_mm = met.L_mm
    Lz = prob.Lz
    P_inA = prob.P_inA
    P_inB = prob.P_inB
    P_kPa = met.P_kPa
    P_real = met.P_real
    P_real_B = met.P_real_B
    Q = met.Q
    Q_AB_imbalance_rel = met.Q_AB_imbalance_rel
    Q_enthalpy_A = met.Q_enthalpy_A
    Q_enthalpy_B = met.Q_enthalpy_B
    Q_solid_B = met.Q_solid_B
    T_A_out = met.T_A_out
    T_B_out = met.T_B_out
    T_inA = prob.T_inA
    T_inB = prob.T_inB
    Ta = outer.Ta
    Tb = outer.Tb
    Ts = outer.Ts
    _and_A = outer._and_A
    _and_B = outer._and_B
    _compact_diag = prob._compact_diag
    _env_mode = prob._env_mode
    _env_warnings = prob._env_warnings
    _eps_A_strict = outer._eps_A_strict
    _eps_A_strict_cellmax = outer._eps_A_strict_cellmax
    _eps_B_strict = outer._eps_B_strict
    _eps_B_strict_cellmax = outer._eps_B_strict_cellmax
    _ltne_info = prob._ltne_info
    _ltne_mask_A = outer._ltne_mask_A
    _ltne_mask_B = outer._ltne_mask_B
    _ltne_max_iter = prob._ltne_max_iter
    _max_outer = prob._max_outer
    _outer_converged = outer._outer_converged
    _outer_dT_hist = outer._outer_dT_hist
    _outer_last_iter = outer._outer_last_iter
    _simple_nonconv = prob._simple_nonconv
    _use_outer_and = outer._use_outer_and
    cell_vol = met.cell_vol
    cp_A = prob.cp_A
    cp_B = prob.cp_B
    dP = met.dP
    dP_B = met.dP_B
    dx = prob.dx
    dy = prob.dy
    dz = prob.dz
    eps = prob.eps
    eps_arr = prob.eps_arr
    fA = prob.fA
    fB = prob.fB
    h_vA_field = outer.h_vA_field
    h_vB_field = outer.h_vB_field
    in_mask_2d = prob.in_mask_2d
    in_mask_B = prob.in_mask_B
    m_dot_A_simple = met.m_dot_A_simple
    m_dot_B_phys_in = met.m_dot_B_phys_in
    m_dot_B_phys_out = met.m_dot_B_phys_out
    m_dot_B_simple = met.m_dot_B_simple
    out_mask_2d = prob.out_mask_2d
    out_mask_B = prob.out_mask_B
    rho_cp_fA = outer.rho_cp_fA
    rho_cp_fB = outer.rho_cp_fB
    sA = prob.sA
    sB = prob.sB
    sB_info = prob.sB_info
    solver_to_real_perm = prob.solver_to_real_perm
    u_A = prob.u_A
    u_B = prob.u_B
    ucB = prob.ucB
    uc_real = met.uc_real
    vcB = prob.vcB
    vc_real = met.vc_real
    vmag = met.vmag
    vmag_B = met.vmag_B
    wcB = prob.wcB
    wc_real = met.wc_real
    cfg = prob.cfg
    # Conditionally-bound cross-seam names (surgery tool definite-
    # assignment pass): None-init so the unconditional return below
    # cannot raise UnboundLocalError on guarded paths. Downstream
    # reads keep their original guards.
    _cdiag = _conservation_diagnostics_3d(
        Ta, Tb, Ts, h_vA_field, h_vB_field, sA, sB, fA, fB, dx, dy, dz)
    Q_sA = _cdiag['Q_sA']; Q_sB = _cdiag['Q_sB']; Q_net = _cdiag['Q_net']
    energy_rel = _cdiag['energy_rel']
    mass_rel_A = _cdiag['mass_rel_A']; mass_rel_B = _cdiag['mass_rel_B']
    Q_sA_interior = _cdiag['Q_sA_interior']
    Q_sB_interior = _cdiag['Q_sB_interior']
    Q_interior_primary = _cdiag['Q_interior_primary']
    AB_interior = _cdiag['AB_interior']

    # Physical face pressures; frozen-pressure incompressible sides stay out.
    pressure_states = {'A': inlet_pressure_state(sA, P_inA),
                       'B': inlet_pressure_state(sB, P_inB)}
    P_in_realized_A = (pressure_states['A']['realized_Pa']
                       if pressure_states['A'] is not None else float('nan'))
    P_in_shoot_resid_A = (pressure_states['A']['relative_error']
                          if pressure_states['A'] is not None else float('nan'))
    P_in_realized_B = (pressure_states['B']['realized_Pa']
                       if pressure_states['B'] is not None else float('nan'))
    P_in_shoot_resid_B = (pressure_states['B']['relative_error']
                          if pressure_states['B'] is not None else float('nan'))

    # ═══════════════════════════════════════════════════════════════════
    # Phase 2 diagnostics (Plan A v3): REQ_1–4 data dump
    # ═══════════════════════════════════════════════════════════════════
    if _compact_diag:
        # Fast sweep: single CSV-style row, skip full diagnostic dump
        _ltne_iters = [d['iters'] for d in _ltne_info]
        _ltne_conv = [d['converged'] for d in _ltne_info]
        _ltne_hit_max = [d['iters'] >= _ltne_max_iter for d in _ltne_info]
        eps_obs = ((T_B_out - T_inB) / (T_inA - T_inB)
                   if sB is not None and T_inA != T_inB else 0.0)
        _log.info(f"[SWEEP-CSV] {cfg.get('_case_label','?')},"
                  f"{len(_ltne_info)},{_ltne_iters},{_ltne_conv},"
                  f"{any(_ltne_hit_max)},{_ltne_info[-1]['residual']:.2e},"
                  f"{T_A_out:.1f},{T_B_out:.1f},{Q:.1f},"
                  f"{Q_sA:.1f},{Q_sB:.1f},{Q_sA+Q_sB:.1f},"
                  f"{energy_rel:.6f},{eps_obs:.4f}")
    # Run diagnostics (Q-DIAG) — OPT-IN, skipped in production.
    # None of these locals feed the return dict; gating avoids the extra
    # _face_flux_weights recompute and extra lines of
    # console spam on every run. Enable via the 3D profiler (.profile_3d /
    # TPMSHX_PROFILE_3D=1) or cfg['_verbose_diag']=True. 2026-06-09 perf B2.
    if _prof_3d_enabled() or bool(cfg.get('_verbose_diag', False)):
        _dbg = np
        Q_solid_A_val = float(_dbg.sum(h_vA_field * (Ts - Ta) * cell_vol))
        Q_solid_B_val = float(_dbg.sum(h_vB_field * (Ts - Tb) * cell_vol))

        # Group 1: LTNE-effective Q (uses eps_f and LTNE volume source)
        Q_enth_A_ltne = abs(m_dot_A_simple * cp_A * (T_inA - T_A_out))
        Q_enth_B_ltne = abs(m_dot_B_simple * cp_B * (T_inB - T_B_out)) if sB is not None else 0.0

        # Group 2: Physical-boundary Q (no eps_f, physical m_dot at inlet)
        m_A_phys_in = float(_dbg.sum(_face_flux_weights(
            sA, fA['dir'], face='real_inlet', eps_mode='physical')))
        Q_enth_A_phys = abs(m_A_phys_in * cp_A * (T_inA - T_A_out))
        if sB is not None:
            Q_enth_B_phys = abs(m_dot_B_phys_in * cp_B * (T_inB - T_B_out))
        else:
            Q_enth_B_phys = 0.0

        _log.info("[Q-DIAG] === LTNE-effective group ===")
        _log.info(f"[Q-DIAG] m_dot_A_ltne={m_dot_A_simple:.5f} kg/s  "
                  f"T_A_out={T_A_out:.1f} K  Q_enth_A_ltne={Q_enth_A_ltne:.1f} W")
        if sB is not None:
            _log.info(f"[Q-DIAG] m_dot_B_ltne={m_dot_B_simple:.5f} kg/s  "
                      f"T_B_out={T_B_out:.1f} K  "
                      f"Q_enth_B_ltne={Q_enth_B_ltne:.1f} W")
        _log.info(f"[Q-DIAG] Q_solid_A={Q_solid_A_val:.1f}  Q_solid_B={Q_solid_B_val:.1f}  "
                  f"balance={Q_solid_A_val+Q_solid_B_val:.1f} W")
        _log.info(f"[Q-DIAG] Q_ltne_consistency: |Q_sA|-Q_enth_A_ltne="
                  f"{abs(Q_solid_A_val)-Q_enth_A_ltne:.1f}  "
                  f"|Q_sB|-Q_enth_B_ltne={abs(Q_solid_B_val)-Q_enth_B_ltne:.1f}")

        _log.info("[Q-DIAG] === Physical-boundary group ===")
        _log.info(f"[Q-DIAG] m_A_phys_in={m_A_phys_in:.5f} kg/s  "
                  f"Q_enth_A_phys={Q_enth_A_phys:.1f} W")
        if sB is not None:
            _log.info(f"[Q-DIAG] m_B_phys_in={m_dot_B_phys_in:.5f}  "
                      f"m_B_phys_out={m_dot_B_phys_out:.5f} kg/s  "
                      f"T_B_out={T_B_out:.1f} K")
            _log.info(f"[Q-DIAG] Q_enth_B_phys={Q_enth_B_phys:.1f} W")

    # ═══════════════════════════════════════════════════════════════════

    result = dict(
        Ta=Ta, Tb=Tb, Ts=Ts, vmag=vmag, P_kPa=P_kPa, L_mm=L_mm,
        P_Pa=P_real, uc_real=uc_real, vc_real=vc_real, wc_real=wc_real,
        P_Pa_B=P_real_B, uc_real_B=ucB, vc_real_B=vcB, wc_real_B=wcB,
        vmag_B=vmag_B, dx=dx, dy=dy, dz=dz,
        h_vA_field=h_vA_field, h_vB_field=h_vB_field)
    diagnostics = dict(
        dP_B=dP_B,
        Lx=L, Ly=H, Lz=Lz,
        Q=Q, Q_total=Q, Q_enthalpy_A=Q_enthalpy_A, Q_enthalpy_B=Q_enthalpy_B,
        Q_solid_B=Q_solid_B,
        mass_flow_A_kg_s=m_dot_A_simple,
        mass_flow_B_kg_s=(m_dot_B_simple if sB is not None else None),
        dP=dP, dP_A=dP, u_A=u_A, T_in=T_inA,
        # C8 shooting diagnostics: realized inlet abs P vs specified P_in
        # (NaN on non-ideal-gas sides; see computation above).
        P_in_realized_A=P_in_realized_A,
        P_in_shoot_resid_A=P_in_shoot_resid_A,
        P_in_realized_B=P_in_realized_B,
        P_in_shoot_resid_B=P_in_shoot_resid_B,
        T_A_out=T_A_out, T_B_out=T_B_out,
        T_out_A=T_A_out, T_out_B=T_B_out,
        dir_A=fA['dir'], dir_B=(fB['dir'] if fB is not None else None),
        # Conservation diagnostics
        Q_sA=Q_sA, Q_sB=Q_sB, Q_net=Q_net,
        energy_imbalance_rel=energy_rel,
        mass_imbalance_rel_A=mass_rel_A,
        mass_imbalance_rel_B=mass_rel_B,
        # #5: sCO2 A/B enthalpy-duty imbalance (nan for air/water) — the residual
        # after the reverse-dir mass-flow fix; >10% ⇒ trust 2D coupled duty.
        Q_AB_imbalance_rel=Q_AB_imbalance_rel,
        # Historical subvolume metrics (physical end CVs excluded)
        Q_sA_interior=Q_sA_interior,
        Q_sB_interior=Q_sB_interior,
        Q_interior=Q_interior_primary,
        AB_interior=AB_interior,
        # B2 strict-conservation certificate (None unless conservative_ltne)
        eps_A_strict=_eps_A_strict,
        eps_B_strict=_eps_B_strict,
        eps_A_strict_cellmax=_eps_A_strict_cellmax,
        eps_B_strict_cellmax=_eps_B_strict_cellmax,
        # Sweep profile diagnostics
        _ltne_info=_ltne_info,
        _max_outer=_max_outer,
        _ltne_max_iter=_ltne_max_iter,
        _needs_full_validate=(_compact_diag and not all(
            d['converged'] for d in _ltne_info)),
    )
    diagnostics['sco2_nu_observations'] = cfg.get('sco2_nu_observations', {})
    diagnostics['df_metadata'] = {
        'mode': prob.cfg.get('df_mode', 'cfd_smooth'),
        'A': getattr(sA, '_df_metadata', None),
        'B': getattr(sB, '_df_metadata', None) if sB is not None else None,
    }

    # ── Post-solve compressible validity gate (robustness, 2026-06-25) ──
    # Catches dynamic choking the 1D pre-seed missed: a supersonic |v| or a
    # pressure clipped to the floor in the converged field. Mach is the load-
    # bearing signal (the _update_density floor bounds the stored gauge, but a
    # choked solve still drives v=G/rho supersonic); it is computed per-cell
    # against the LOCAL temperature so a cold low-density region isn't missed.
    # BOTH ideal-gas sides are checked — fluid B (air-air) can choke too.
    _clip_hits = int(getattr(sA, '_p_clip_hits', 0))
    if sB is not None:
        _clip_hits += int(getattr(sB, '_p_clip_hits', 0))
    _env_valid, _env_reasons = True, []
    if cfg.get('fluid_type_A', 'air') == 'air':
        _vA, _rA = gate_solution(
            float((sA.P_ref_abs + sA.P).min()), float(vmag.max()),
            float(T_inA), mode=_env_mode, dims='3D-A',
            ma_max=mach_field_max(vmag, Ta))
        _env_valid = _env_valid and _vA
        _env_reasons += [f"[A] {r}" for r in _rA]
    if (sB is not None and vmag_B is not None
            and cfg.get('fluid_type_B', 'air') == 'air'):
        _vB, _rB = gate_solution(
            float((sB.P_ref_abs + sB.P).min()), float(vmag_B.max()),
            float(T_inB), mode=_env_mode, dims='3D-B',
            ma_max=mach_field_max(vmag_B, Tb))
        _env_valid = _env_valid and _vB
        _env_reasons += [f"[B] {r}" for r in _rB]
    # ── SIMPLE verdict: judge the FINAL solve, not the whole history ─────────
    # `_simple_nonconv` is a STICKY list of every SIMPLE solve that failed,
    # including the cold-start one. But outer iteration 0 can never satisfy the
    # coupling criterion (there is no previous iterate to diff against), so
    # `post(0)` ALWAYS runs and ALWAYS re-solves SIMPLE — the cold-start
    # velocity/pressure field is therefore ALWAYS superseded before anything is
    # reported. Gating the verdict on the sticky list meant a run whose every
    # reported field came from a converged solve still said converged=False
    # because a transient warm-up solve had stalled. (Shanghai: the u≈22 m/s
    # cases log `A@init[stall]` while every subsequent re-solve exits
    # 'velocity'.) The verdict now measures the state that produced the answer;
    # the full history stays in convergence_detail for diagnosis, and a
    # superseded stall still raises a (differently worded) warning.
    #
    # Only a final F2 'tol' exit certifies the returned momentum state.
    _OK_EXITS = ('tol',)

    def _final_ok(s):
        return s is None or getattr(s, 'exit_reason', None) in _OK_EXITS
    _simple_final_ok = _final_ok(sA) and _final_ok(sB)
    _simple_nonconv_transient = [
        t for t in _simple_nonconv if t.startswith(('A@init', 'B@init'))]
    _simple_nonconv_final = [
        t for t in _simple_nonconv if t not in _simple_nonconv_transient]

    if not _simple_final_ok:
        _env_warnings.append(
            "SIMPLE momentum solve did not converge in the FINAL solve: "
            + ", ".join(_simple_nonconv_final or _simple_nonconv)
            + " — the reported velocity/pressure field is not converged (inspect "
              "the F2 residuals and iteration budget).")
    elif _simple_nonconv_transient:
        _env_warnings.append(
            "SIMPLE momentum solve stalled in a TRANSIENT (superseded) solve: "
            + ", ".join(_simple_nonconv_transient)
            + " — the cold-start field was re-solved by the outer loop and the "
              "reported field DID converge, so this is informational. It does "
              "flag a hard cold start (typically high u).")
    _env_warnings = list(dict.fromkeys(_env_warnings))   # dedup, keep order
    diagnostics['envelope_valid'] = _env_valid
    diagnostics['envelope_reasons'] = _env_reasons
    diagnostics['envelope_warnings'] = _env_warnings
    diagnostics['p_clip_hits'] = _clip_hits
    # ── Convergence verdict — explicit AND over every gate (2026-07-12) ──
    # robustness-hardening (2026-07-03) introduced this key but only ANDed
    # SIMPLE with the FINAL outer LTNE pass. Three ways a bad solve could still
    # report success, all closed here:
    #   (a) outer coupling never converged  — the skeleton's verdict was
    #       discarded at the call site (see run_outer_coupling above);
    #   (b) `max_outer_ltne=0` → zero iterations → `_ltne_info` empty → the
    #       `not _ltne_info` short-circuit returned True on a run that solved
    #       nothing;
    #   (c) a non-finite (NaN/inf) temperature or velocity field — the envelope
    #       gate flags non-finite P/Mach, but a NaN inside Ta/Tb/Ts alone did
    #       not touch the verdict.
    # Only the verdict changes; no numeric field is touched (golden gates hash
    # fields + headline scalars, not this key).
    _fields_finite = bool(
        np.all(np.isfinite(Ta)) and np.all(np.isfinite(Tb))
        and np.all(np.isfinite(Ts)) and np.all(np.isfinite(vmag))
        and (vmag_B is None or np.all(np.isfinite(vmag_B))))
    if not _fields_finite:
        _env_warnings.append(
            "Non-finite (NaN/inf) cells in the converged temperature or "
            "velocity field — the result is not physical; solver_converged "
            "is forced False.")
        _env_warnings = list(dict.fromkeys(_env_warnings))
        diagnostics['envelope_warnings'] = _env_warnings
    _ltne_ok = bool(_ltne_info) and bool(
        _ltne_info[-1].get('converged', False))
    diagnostics['solver_converged'] = bool(
        _simple_final_ok               # the FINAL SIMPLE solve on EACH side
        and _ltne_ok                   # FINAL outer LTNE inner pass converged
        and bool(_outer_converged)     # outer coupling converged (not capped)
        and _fields_finite             # no NaN/inf in the reported fields
        and bool(_env_valid))          # post-solve compressible envelope gate
    # A2 (2026-07-06): structured convergence detail. Additive result keys
    # only (the golden gate hashes fields + headline scalars, not these).
    #   simple_*   : final SIMPLE exit per solver — reason ('tol'|'velocity'|
    #                'stall'|'max_iter'|'cancelled'), final normalised
    #                residual, and the kg/s normalisation reference.
    #   outer_dT   : per-outer-iteration {Ta,Tb,Ts: max|Δ| [K]} history.
    #   outer_converged : the tracked-field AND-gate verdict of the last
    #                outer iteration; reaching the budget is not convergence.
    def _simple_detail(s):
        if s is None:
            return None
        return dict(exit_reason=getattr(s, 'exit_reason', None),
                    # LEGACY mass residual. Ledger C6: on 3D this is the
                    # Dirichlet-outlet-row artifact, NOT a convergence measure.
                    # Kept because it still drives the adaptive-AMG scheduler and
                    # every historical number was produced against it.
                    final_res=getattr(s, 'final_res', None),
                    res_norm_ref=getattr(s, 'res_norm_ref', None),
                    iterations=len(getattr(s, 'residuals', []) or []),
                    # Native F2 convergence diagnostics.
                    # unless track_momentum_residual was set.
                    convergence_mode=getattr(s, 'convergence_mode', 'f2'),
                    final_res_mom=getattr(s, 'final_res_mom', None),
                    final_res_mass_local=getattr(
                        s, 'final_res_mass_local', None),
                    final_res_mass_global=getattr(
                        s, 'final_res_mass_global', None),
                    outlet_backflow_frac=getattr(
                        s, 'outlet_backflow_frac', None))
    diagnostics['convergence_detail'] = dict(
        inlet_pressure=pressure_states,
        simple_A=_simple_detail(sA),
        simple_B=_simple_detail(sB),
        simple_nonconv=list(_simple_nonconv),
        outer_dT=[{k: float(v) for k, v in d.items()}
                  for d in _outer_dT_hist],
        # The skeleton's OWN verdict, not a reconstruction from the ΔT history
        # (the reconstruction could disagree with the loop that actually ran —
        # e.g. it returned True for a converged-on-the-first-pass run whose
        # history the skeleton never marks). Also records WHY it stopped.
        outer_converged=bool(_outer_converged),
        outer_iters=int(_outer_last_iter) + 1,
        outer_hit_cap=bool(not _outer_converged),
        # Per-gate breakdown so a caller can see WHICH gate failed rather than
        # just that the AND is False (convergence truth-table, 2026-07-12).
        # simple_ok gates the verdict and judges the FINAL solve on each side.
        # simple_nonconv (above) stays the FULL sticky history; the two lists
        # below split it, so a caller can tell "the reported field is bad" from
        # "a superseded warm-up solve stalled" — they used to be indistinguishable
        # and both forced converged=False.
        simple_ok=bool(_simple_final_ok),
        simple_nonconv_final=list(_simple_nonconv_final),
        simple_nonconv_transient=list(_simple_nonconv_transient),
        simple_exit_A=getattr(sA, 'exit_reason', None),
        simple_exit_B=getattr(sB, 'exit_reason', None) if sB is not None else None,
        ltne_ok=_ltne_ok,
        fields_finite=_fields_finite,
        envelope_ok=bool(_env_valid),
        # Outer-coupling Anderson (None when the opt-in knob is off). Records
        # how many candidates were accepted / rejected by the admissibility
        # gate / dropped by the staleness reset, plus the fixed-point residual
        # history — so the acceleration is auditable, never a black box.
        outer_anderson=(None if not _use_outer_and else dict(
            A=_and_A.stats(), B=(_and_B.stats() if sB is not None else None))),
    )

    diagnostics['true_h_balance'] = (dict(
        _ltne_info[-1]['true_h_balance'], outer_converged=bool(_outer_converged),
        post_after_last_thermal=bool(not _outer_converged),
        state='last true-h solve, before any final post update')
        if _ltne_info and 'true_h_balance' in _ltne_info[-1] else None)
    diagnostics['model_h_balance'] = (dict(
        _ltne_info[-1]['model_h_balance'], outer_converged=bool(_outer_converged),
        post_after_last_thermal=bool(not _outer_converged),
        state='last model-h thermal solve, before any final post update')
        if _ltne_info and 'model_h_balance' in _ltne_info[-1] else None)

    # ── Audit-only additive exports (read-only, deep-copied) ── OPT-IN.
    # Passthrough of SIMPLE face arrays + masks for the standalone partial-B
    # LTNE conservation diagnostics (historical audit: docs/history/README.md).
    # 2026-06-09 perf C1: gated behind cfg['_emit_audit'] (default False) —
    # these deep-copy both solvers' full u/v/w/ρ fields + K/eps/rho_cp arrays,
    # a large memory + wall-time cost paid on EVERY run. Only the audit scripts
    # and test_partial_bc_ghost_b consume them, so those callers set
    # _emit_audit=True. Consumers must not mutate. No physics change.
    if cfg.get('_emit_audit', False):
        diagnostics.update(
        _audit_sA_face=dict(
            u=sA.u.copy(), v=sA.v.copy(), w=sA.w.copy(),
            rho=sA.rho_field.copy(),
            outlet_coeff=sA.outlet_coeff.copy(),
            inlet_frac=(np.asarray(sA.inlet_frac).copy()
                        if getattr(sA, 'inlet_frac', None) is not None else None),
            outlet_frac=(np.asarray(sA.outlet_frac).copy()
                         if getattr(sA, 'outlet_frac', None) is not None else None),
            eps=(np.asarray(sA.eps_field).copy()
                 if getattr(sA, 'eps_field', None) is not None else None),
            dx=sA.dx.copy(), dy=sA.dy.copy(), dz=sA.dz.copy(),
            dir_real=fA['dir'],
            solver_to_real_perm=solver_to_real_perm,
        ),
        _audit_sB_face=(dict(
            u=sB.u.copy(), v=sB.v.copy(), w=sB.w.copy(),
            rho=sB.rho_field.copy(),
            outlet_coeff=sB.outlet_coeff.copy(),
            inlet_frac=(np.asarray(sB.inlet_frac).copy()
                        if getattr(sB, 'inlet_frac', None) is not None else None),
            outlet_frac=(np.asarray(sB.outlet_frac).copy()
                         if getattr(sB, 'outlet_frac', None) is not None else None),
            eps=(np.asarray(sB.eps_field).copy()
                 if getattr(sB, 'eps_field', None) is not None else None),
            dx=sB.dx.copy(), dy=sB.dy.copy(), dz=sB.dz.copy(),
            dir_real=fB['dir'],
            solver_to_real_perm=sB_info['axis_map']['solver_to_real_perm'],
        ) if sB is not None else None),
        _audit_m_dot_A_simple=float(m_dot_A_simple),
        _audit_m_dot_B_simple=(float(m_dot_B_simple) if sB is not None else None),
        _audit_m_dot_B_phys_in=(float(m_dot_B_phys_in) if sB is not None else None),
        _audit_m_dot_B_phys_out=(float(m_dot_B_phys_out) if sB is not None else None),
        _audit_cp_A=float(cp_A),
        _audit_cp_B=(float(cp_B) if sB is not None else None),
        _audit_T_inA=float(T_inA),
        _audit_T_inB=(float(T_inB) if sB is not None else None),
        _audit_u_A=float(u_A),
        _audit_u_B=(float(u_B) if sB is not None else None),
        _audit_eps=float(eps),
        _audit_fA=dict(fA),
        _audit_fB=(dict(fB) if fB is not None else None),
        _audit_P_inA=float(P_inA),
        _audit_P_inB=float(P_inB),
        )

        result.update(
        _audit_ltne_mask_B=(np.asarray(_ltne_mask_B).copy()
                             if _ltne_mask_B is not None else None),
        _audit_ltne_mask_A=(np.asarray(_ltne_mask_A).copy()
                             if _ltne_mask_A is not None else None),
        _audit_in_mask_B=(np.asarray(in_mask_B).copy()
                          if (sB is not None and in_mask_B is not None) else None),
        _audit_out_mask_B=(np.asarray(out_mask_B).copy()
                           if (sB is not None and out_mask_B is not None) else None),
        _audit_in_mask_2d=(np.asarray(in_mask_2d).copy()
                           if in_mask_2d is not None else None),
        _audit_out_mask_2d=(np.asarray(out_mask_2d).copy()
                            if out_mask_2d is not None else None),
        # Phase 2 conservation-residual exports
        _audit_K_ffA=K_ffA.copy(),
        _audit_K_ffB=K_ffB.copy(),
        _audit_K_ss=K_ss.copy(),
        _audit_eps_arr=eps_arr.copy(),
        _audit_rho_cp_fA=rho_cp_fA.copy(),
        _audit_rho_cp_fB=rho_cp_fB.copy(),
        )
        for key in ('_audit_ltne_mask_B', '_audit_ltne_mask_A', '_audit_in_mask_B',
                    '_audit_out_mask_B', '_audit_in_mask_2d', '_audit_out_mask_2d'):
            if result[key] is None:
                diagnostics[key] = None

    # Preserve absent-field diagnostic placeholders used by existing archives.
    for key in ('P_Pa_B', 'vmag_B'):
        if result[key] is None:
            diagnostics[key] = None
    result.update(diagnostics)
    return result, diagnostics


def _run_outer_coupling_3d(prob: _Problem3D, hv: _HvMachinery, *,
                           control: RunControl = RunControl(), capture_native=False):
    """Run thermal-first coupling; detach native evidence before any final post."""
    D_h = prob.D_h
    G_A = prob.G_A
    G_B = prob.G_B
    H = prob.H
    K_disp_A = prob.K_disp_A
    K_disp_B = prob.K_disp_B
    K_ffA = prob.K_ffA
    K_pred = prob.K_pred
    K_pred_B = prob.K_pred_B
    K_ss = prob.K_ss
    L = prob.L
    L_mm_field = prob.L_mm_field
    L_stream = prob.L_stream
    L_stream_B = prob.L_stream_B
    Lcell = prob.Lcell
    Lz = prob.Lz
    Nx = prob.Nx
    Ny = prob.Ny
    Nz = prob.Nz
    P_inA = prob.P_inA
    P_inB = prob.P_inB
    T_inA = prob.T_inA
    T_inB = prob.T_inB
    Tb_presc = prob.Tb_presc
    _build_hv_local_3d = hv._build_hv_local_3d
    _env_mode = prob._env_mode
    _env_warnings = prob._env_warnings
    _hv_ratio_A = hv._hv_ratio_A
    _hv_ratio_B = hv._hv_ratio_B
    _ltne_info = prob._ltne_info
    _ltne_max_iter = prob._ltne_max_iter
    _mA = prob._mA
    _mB = prob._mB
    _max_outer = prob._max_outer
    _outer_tol = prob._outer_tol
    _simple_nonconv = prob._simple_nonconv
    axis_map = prob.axis_map
    axis_map_B = prob.axis_map_B
    cF_pred = prob.cF_pred
    cF_pred_B = prob.cF_pred_B
    cp_A = prob.cp_A
    cp_B = prob.cp_B
    disp_C_A = prob.disp_C_A
    disp_C_B = prob.disp_C_B
    dx = prob.dx
    dy = prob.dy
    dz = prob.dz
    eps = prob.eps
    eps_arr = prob.eps_arr
    eps_fA_arr = prob.eps_fA_arr
    eps_fB_arr = prob.eps_fB_arr
    fA = prob.fA
    fB = prob.fB
    fluid_type_A = prob.fluid_type_A
    fluid_type_B = prob.fluid_type_B
    in_mask_2d = prob.in_mask_2d
    in_mask_B = prob.in_mask_B
    mu_A = prob.mu_A
    mu_B = prob.mu_B
    perm_B = prob.perm_B
    rho_A = prob.rho_A
    rho_B = prob.rho_B
    rho_B_ltne = prob.rho_B_ltne
    sA = prob.sA
    sB = prob.sB
    solver_to_real_perm = prob.solver_to_real_perm
    t_field_3d = prob.t_field_3d
    t_wall = prob.t_wall
    tpms_type = prob.tpms_type
    u_A = prob.u_A
    u_B_val = hv.u_B_val
    ucB = prob.ucB
    vcB = prob.vcB
    wcB = prob.wcB
    cfg = prob.cfg
    # Air pressure correction is on by default; explicit OFF is diagnostic.
    # Convergence still requires the physical inlet pressure to meet its target.
    _p_shoot = bool(cfg.get('p_in_shooting',
                            run_environment(cfg, 'TPMSHX_P_IN_SHOOT', '1') == '1'))
    # Default ON (2026-06-09): build the LTNE convective rho_cp from SIMPLE's
    # LOCAL density field ρ(P_local,T) instead of ρ(T,P_inlet). For compressible
    # fluids the kernel then telescopes cp·(ε·ρ_local·u) = cp·(SIMPLE mass flux),
    # so ∮(ε·ρcp·u) ≈ cp·∮(mass flux) ≈ 0 (SIMPLE continuity) and the strict
    # conservative kernel is mass-conserving for COMPRESSIBLE reverse flow too
    # (fixes the air-air reverse ε-NTU/full-face cases). Strict certificate
    # machine-zero on all 6 audit cases; Shanghai bit-identical to the old
    # inlet-P path. Env `TPMSHX_VAR_RHOCP=0/1` is an explicit override; otherwise
    # cfg/flags default True. Scripted cfg['variable_rho_cp']=False restores
    # the legacy inlet-pressure density; the desktop fixes this setting ON.
    _env_vrc = run_environment(cfg, 'TPMSHX_VAR_RHOCP')
    if _env_vrc in ('0', '1'):
        _var_rhocp = _env_vrc == '1'
    else:
        _var_rhocp = bool(cfg.get('variable_rho_cp', True))

    # Map all three solver velocity components into real coordinates.
    def _assemble_real_velocity():
        return _solver_velocity_to_real(sA, axis_map, (Nx, Ny, Nz))

    def _rho_real(solver, amap):
        field = solver.rho_field.transpose(amap['solver_to_real_perm'])
        if amap['is_reverse']:
            field = np.flip(field, axis=amap['stream_real_axis'])
        return np.ascontiguousarray(field, dtype=np.float64)

    # One live owner for state shared by thermal, diagnostic and post steps.
    # SIMPLE and problem-owned arrays retain their existing in-place ownership.
    state = _OuterState(
        K_ffB=prob.K_ffB, Ta=None, Tb=None, Ts=None,
        _and_A=None, _and_B=None, _assemble_real_velocity=_assemble_real_velocity,
        _eps_A_strict=None, _eps_A_strict_cellmax=None,
        _eps_B_strict=None, _eps_B_strict_cellmax=None,
        _ltne_mask_A=None, _ltne_mask_B=None,
        _outer_converged=False, _outer_dT_hist=[], _outer_last_iter=-1,
        _use_outer_and=False,
        h_vA_field=hv.h_vA_field, h_vB_field=hv.h_vB_field,
        rho_cp_fA=np.full((Nx, Ny, Nz), rho_A * cp_A, dtype=np.float64),
        rho_cp_fB=np.full((Nx, Ny, Nz), rho_B_ltne * cp_B, dtype=np.float64),
        native_evidence=None,
    )

    # Warm-start delta tracker (shared with the 2D driver). A2 (2026-07-06):
    # gate on ALL THREE temperature fields — the old ('Ta',)-only criterion
    # let Tb/Ts drift unmonitored (a cross-flow B side or slow solid could
    # still be moving when Ta settled).
    _outer_conv = OuterConvergence(tol_T=_outer_tol, track=('Ta', 'Tb', 'Ts'))

    # ── Anderson acceleration on the OUTER coupling map (opt-in, 2026-07-12) ──
    # The outer loop's relaxation is a fixed constant (_ALPHA_T = 0.6) applied
    # to the property fields (rho, mu) in `_outer_post_3d`. Measured on three
    # air cases (mild / baseline / hot+fast), the resulting Picard iteration is
    # OSCILLATORY — the residual grows x1.36 on the 2nd iteration before
    # collapsing — i.e. it is under-damped, and the constant alpha is leaving
    # convergence rate on the table.
    #
    # `AndersonOuterCoupling` replaces the constant with a least-squares mix
    # over the last m (x, G(x)) pairs for SIMPLE<->LTNE coupling BETWEEN
    # solves. The old inner SIMPLE `use_anderson` option is retired.
    #
    # OFF by default: when disabled, `_outer_post_3d` runs the original blend
    # expression verbatim, so the production path and the golden gates are
    # bit-identical.
    state._use_outer_and = bool(cfg.get('outer_anderson', False))
    if state._use_outer_and:
        from sjtu_tpmshx.solvers.anderson_acceleration import AndersonOuterCoupling
        _and_kw = dict(m=int(cfg.get('outer_anderson_m', 3)),
                       trust=float(cfg.get('outer_anderson_trust', 5.0)),
                       patience=int(cfg.get('outer_anderson_patience', 3)))
        state._and_A = AndersonOuterCoupling(**_and_kw)
        state._and_B = AndersonOuterCoupling(**_and_kw)
    # Optional solid warm-start seed from the UI. Empty → solver default
    # (Ta=T_inA, Tb=T_inB, Ts=0.5*(T_inA+T_inB) inside solve_full_domain_3d).
    # Filled → only Ts is overridden with the user value; Ta/Tb stay at the
    # per-fluid inlet T (the 2026-04-24 FV fix in solvers/ltne_energy_3d.py
    # showed that 0.5*mean for Ta/Tb leaks into non-pipe inlet cells and
    # breaks energy balance by 20–25% on partial-inlet runs). The solid
    # energy equation still updates Ts each sweep; this is *not* prescribed.
    _Ts_init_user = cfg.get('T_s_init')
    if _Ts_init_user is not None:
        _shape3d = (Nx, Ny, Nz)
        state.Ta = np.full(_shape3d, float(T_inA), dtype=np.float64)
        state.Tb = np.full(_shape3d, float(T_inB), dtype=np.float64)
        state.Ts = np.full(_shape3d, float(_Ts_init_user), dtype=np.float64)
    _cancel_check = control.cancel_check

    # 3D remains thermal-first. The last nonconverged iteration still runs post;
    # its native thermal evidence must be detached before those working updates.
    def _check_property_water(where):
        # The temperature path refreshes properties at frozen inlet pressure.
        # It does not consume the separate true-h kernel pressure offset.
        fluid_props.check_water_state(fluid_type_A, T_inA if state.Ta is None else state.Ta,
                                      P_inA, where=f'{where} A')
        fluid_props.check_water_state(fluid_type_B, T_inB if state.Tb is None else state.Tb,
                                      P_inB, where=f'{where} B')

    def _record_temperature_state(stage, layout):
        # Only called for the empirical temperature/model-h route, not HEOS.
        for side, fluid, temperature in (('A', fluid_type_A, state.Ta), ('B', fluid_type_B, state.Tb)):
            with range_context(side=side, stage=stage, layout=layout):
                record_temperature_ranges(fluid, temperature)

    def _snapshot_thermal(outer, info, mode, mass_A, mass_B,
                          pressure_A, pressure_B, faces_A, faces_B):
        # Detach now: post can mutate capacities, conductivities and SIMPLE
        # arrays even on the last budget iteration. These are thermal inputs.
        from sjtu_tpmshx.domain.portable_data import mutable_data
        return mutable_data(dict(
            Ta=state.Ta, Tb=state.Tb, Ts=state.Ts, h_vA=state.h_vA_field, h_vB=state.h_vB_field,
            K_ss=K_ss, outer_index=int(outer), mode=mode,
            true_h=info.get('_native_state') if mode == 'true_h' else None,
            model_h=info.get('_native_model_h'),
            mass_A=mass_A, mass_B=mass_B,
            P_thermal_A=pressure_A, P_thermal_B=pressure_B,
            face_velocity_A=faces_A, face_velocity_B=faces_B,
            rho_cp_A=state.rho_cp_fA, rho_cp_B=state.rho_cp_fB))

    def _refresh_heat_transfer(outer, velocity_A):
        """Refresh each side's h_v and physical inlet masks in real axes."""
        ucA, vcA, wcA = velocity_A
        # Rebuild from the latest full vector: turning flow is not stagnation
        # merely because its component normal to the inlet becomes small.
        speed_A = local_speed(ucA, vcA, wcA)
        # D3: sCO2 uses the LOCAL temperature field (lagged Ta) for h_v props;
        # iter-0 Ta is None → scalar T_inA (frozen, = old behaviour).
        _T_hvA = state.Ta if (fluid_type_A == 'sco2' and state.Ta is not None) else T_inA
        with range_context(side='A', stage='main', layout='real-cell(x,y,z)-hv-speed'):
            state.h_vA_field = _build_hv_local_3d(
                L_mm_field, t_field_3d, speed_A, _T_hvA, P_inA, fluid_type_A,
                    observation=cfg['sco2_nu_observations']['A'])
        if outer == 0 and fluid_type_A == 'sco2':
            warn_sco2_nu_evidence(
                side='A', stage='3D h_v property refresh',
                tpms_type=tpms_type, L_mm=Lcell if L_mm_field is None else L_mm_field,
                t_mm=t_wall if L_mm_field is None else t_field_3d,
                P_in=P_inA)
        state.h_vA_field = _apply_roughness_h_v(
            state.h_vA_field, fluid_type_A, rho_A, mu_A, u_A, D_h, resolved=cfg['roughness_resolved'])
        state.h_vA_field = state.h_vA_field * _hv_ratio_A   # per-side asym geom (1.0 at δ=0)
        # Pre-compute physical LTNE inlet masks.
        # approach-(a): the kernel applies the inlet BC at its inlet face using
        # this mask; with the reverse spatial flip + no mask swap, the physical
        # inlet patch is in_mask for BOTH forward and reverse dirs.
        state._ltne_mask_A = in_mask_2d
        state._ltne_mask_B = None
        if fB is not None:
            state._ltne_mask_B = in_mask_B

        if sB is not None:
            speed_B = local_speed(ucB, vcB, wcB)
            _T_hvB = state.Tb if (fluid_type_B == 'sco2' and state.Tb is not None) else T_inB
            with range_context(side='B', stage='main', layout='real-cell(x,y,z)-hv-speed'):
                state.h_vB_field = _build_hv_local_3d(
                    L_mm_field, t_field_3d, speed_B, _T_hvB, P_inB, fluid_type_B,
                    observation=cfg['sco2_nu_observations']['B'])
            if outer == 0 and fluid_type_B == 'sco2':
                warn_sco2_nu_evidence(
                    side='B', stage='3D h_v property refresh',
                    tpms_type=tpms_type, L_mm=Lcell if L_mm_field is None else L_mm_field,
                    t_mm=t_wall if L_mm_field is None else t_field_3d,
                    P_in=P_inB)
            state.h_vB_field = _apply_roughness_h_v(
                state.h_vB_field, fluid_type_B, rho_B, mu_B, u_B_val, D_h, resolved=cfg['roughness_resolved'])
            state.h_vB_field = state.h_vB_field * _hv_ratio_B   # per-side asym geom (1.0 at δ=0)

    def _prepare_thermal_inputs(outer):
        """Keep model-h mass faces before balancing the temperature faces."""
        ucA, vcA, wcA = _assemble_real_velocity()
        _enth_gate = (sB is not None
                      and 'sco2' in (fluid_type_A, fluid_type_B))
        if not _enth_gate:
            _check_property_water('3D temperature warm start')
        fluid_props.check_finite_temperatures(
            state.Ta, state.Tb, state.Ts, where='3D temperature warm start')
        if not _enth_gate:
            _record_temperature_state('main', 'real-cell(x,y,z)-warm')

        _refresh_heat_transfer(outer, (ucA, vcA, wcA))

        # Extract SIMPLE's staggered face velocities in REAL coords for the
        # mass-conserving LTNE kernel (2026-04-25 FV#6).
        ufA, vfA, wfA = _solver_staggered_to_real(sA, axis_map, (Nx, Ny, Nz))
        if sB is not None:
            ufB, vfB, wfB = _solver_staggered_to_real(sB, axis_map_B, (Nx, Ny, Nz))
        else:
            ufB = np.zeros((Nx+1, Ny, Nz), dtype=np.float64)
            vfB = np.zeros((Nx, Ny+1, Nz), dtype=np.float64)
            wfB = np.zeros((Nx, Ny, Nz+1), dtype=np.float64)

        # Only the qualified temperature route consumes raw mass transport.
        # Capture before any capacity balance; all other callers keep their path.
        _model_kwargs = {}
        _model_h_gate = (
            Nz > 1 and _var_rhocp and sB is not None and Tb_presc is None
            and (fluid_type_A, fluid_type_B) in (('air', 'air'), ('air', 'water'), ('water', 'air'))
            and bool(cfg.get('conservative_ltne', True))
            and float(cfg.get('delta_levelset', 0.0)) == 0.0)
        if _model_h_gate:
            from sjtu_tpmshx.solvers.ltne_enthalpy_3d import face_mass_fluxes
            _model_kwargs = dict(
                model_mass_A=face_mass_fluxes(
                    ufA, vfA, wfA, _rho_real(sA, axis_map), eps_fA_arr, dx, dy, dz),
                model_mass_B=face_mass_fluxes(
                    ufB, vfB, wfB, _rho_real(sB, axis_map_B), eps_fB_arr, dx, dy, dz),
                model_fluids=(fluid_type_A, fluid_type_B))

        # Capture the physical inlet before the existing thermal-face balancing.
        inlet_flux_A = _inlet_transport_3d(
            (ufA, vfA, wfA), eps_fA_arr, _rho_real(sA, axis_map),
            cp_A, dx, dy, dz, fA['dir'])
        inlet_flux_B = None if sB is None else _inlet_transport_3d(
            (ufB, vfB, wfB), eps_fB_arr, _rho_real(sB, axis_map_B),
            cp_B, dx, dy, dz, fB['dir'])

        # Pair air's current thermal cp with this completed SIMPLE state,
        # including the first call and B's post-SIMPLE density refresh.
        if _var_rhocp and fluid_type_A == 'air' and _mA.compressible:
            with range_context(side='A', stage='property-refresh', layout='real-cell(x,y,z)-thermal-cp'):
                state.rho_cp_fA[:] = _rho_real(sA, axis_map) * air_cp(T_inA if state.Ta is None else state.Ta)
        if (_var_rhocp and fluid_type_B == 'air' and _mB.compressible
                and sB is not None):
            with range_context(side='B', stage='property-refresh', layout='real-cell(x,y,z)-thermal-cp'):
                state.rho_cp_fB[:] = _rho_real(sB, axis_map_B) * air_cp(T_inB if state.Tb is None else state.Tb)

        # Strict-conservation prerequisite (2026-06-09): enforce discrete global
        # mass balance ∮F·n=0 on the extracted stream-boundary faces so the
        # conservative-LTNE kernel's telescoping sum closes to machine
        # precision. SIMPLE's small continuity residual (amplified by partial-BC
        # + outlet taper on offset/reverse fluids) otherwise leaves a net ΣD the
        # homogeneous-Neumann MAC projection cannot remove → reverse heat-load
        # drift. coef = eps_f·ρcp = 0.5·ε·ρcp matches the projection.
        #
        # INCOMPRESSIBLE ONLY. The kernel telescopes ε·ρcp·u with a CONSTANT
        # ρcp, so enforcing ∮(ε·ρcp·u)=0 means enforcing volume-flux balance
        # ∮(εu)=0. For incompressible flow that IS mass conservation (ρ const).
        # For compressible (ideal-gas) flow mass conservation is ∮(ερu)=0 with
        # ρ=ρ(P,T) varying, so ∮(εu)≠0 is PHYSICAL — forcing it would corrupt
        # the velocity field (measured: air scale 0.58–0.94, +300 % Q error).
        # Compressible reverse-dir conservation is a separate kernel-level
        # (constant-ρcp) limitation, out of scope here.
        if (not _model_h_gate and bool(cfg.get('conservative_ltne', True))
                and cfg.get('strict_mass_balance', True)):
            # Incompressible always; compressible only with variable_rho_cp (then
            # rho_cp = ρ_local·cp matches SIMPLE's conserved mass flux, so the
            # balance scale ≈ 1 and it removes only the residual — see _var_rhocp).
            if (not fluid_props.get(fluid_type_A).compressible) or _var_rhocp:
                # Per-side ε must match the LTNE kernel's eps_fA/eps_fB exactly,
                # else the MAC projection corrupts and reverse-dir Q drift
                # silently returns. δ=0 → eps_fA_arr == eps_arr/2 (identical).
                _coefA = eps_fA_arr * state.rho_cp_fA
                _balance_stream_outflow([ufA, vfA, wfA], axis_map, _coefA, dx, dy, dz)
            if sB is not None and (
                    (not fluid_props.get(fluid_type_B).compressible) or _var_rhocp):
                _coefB = eps_fB_arr * state.rho_cp_fB
                _balance_stream_outflow([ufB, vfB, wfB], axis_map_B, _coefB, dx, dy, dz)

        return _ThermalInputs3D(
            velocity_A=(ucA, vcA, wcA),
            faces_A=(ufA, vfA, wfA), faces_B=(ufB, vfB, wfB),
            model_kwargs=_model_kwargs,
            inlet_flux_A=inlet_flux_A, inlet_flux_B=inlet_flux_B,
            mode=('true_h' if _enth_gate else
                  'model_h' if _model_h_gate else 'legacy_temperature'),
        )

    def _solve_temperature(inputs):
        """Run model-h/temperature, or the two-sweep true-h warm start."""
        ucA, vcA, wcA = inputs.velocity_A
        ufA, vfA, wfA = inputs.faces_A
        ufB, vfB, wfB = inputs.faces_B
        _enth_gate = inputs.mode == 'true_h'
        _model_h_gate = inputs.mode == 'model_h'
        _model_kwargs = inputs.model_kwargs
        inlet_flux_A, inlet_flux_B = inputs.inlet_flux_A, inputs.inlet_flux_B
        # B-plan B5: strict face-centered energy conservation is now the 3D
        # production default (telescoping aP + face-shared HO + MAC projection).
        # The legacy cell-local-|u_c| kernel remains an explicit fallback via
        # cfg['conservative_ltne']=False.
        _conservative_ltne = bool(cfg.get('conservative_ltne', True))

        # MMS source fields (Air-Air V&V Phase A.1). Default None → no-op.
        # Solver accepts (Nx, Ny, Nz) arrays; volume-integrated source per
        # cell injected into FVM equation RHS. Used by validation/cases/mms_3d_*.py.
        _mms_S_A = cfg.get('mms_S_A_field', None)
        _mms_S_B = cfg.get('mms_S_B_field', None)
        _mms_S_s = cfg.get('mms_S_s_field', None)
        # 2026-05-19 ε contract (Option A — supersedes the wrong 2026-05-14
        # "fix"): pass FULL porosity `eps_arr`. The kernel itself does
        # eps_f = 0.5*epsilon (single halving → ε_A = ε_full/2). The
        # 2026-05-14 change to `eps_f_arr` here double-halved ε to ε_full/4
        # (the "ΔT_A 90→105°C" it celebrated was the BUG, not a fix —
        # half the LTNE fluid heat capacity). K_ffA/K_ffB stay built from
        # eps_f_arr (= ε_A, correct for diffusion); only the convective
        # epsilon arg must be FULL ε.
        # Any pair containing sCO2 uses true enthalpy. The face-flux kernel
        # supports every real axis and arbitrary inlet/outlet patches.
        # When the enthalpy solve will overwrite the result below, run the legacy
        # ρcp·u·T solve for only a couple of sweeps (a cheap warm-start) rather
        # than to full convergence. Its returned temperatures seed true-h.
        _eff_ltne_max_iter = 2 if _enth_gate else _ltne_max_iter
        _refined_thermal = {}
        if cfg.get('port_wall_refine', False) and _model_h_gate:
            _refined_thermal = dict(accelerate=True, alpha_T_s=1.)
        _ltne_result = solve_full_domain_3d(
            L, H, Lz, Nx, Ny, Nz, T_inA, T_inB,
            K_ffA, state.K_ffB, K_ss, state.h_vA_field, state.h_vB_field,
            state.rho_cp_fA, state.rho_cp_fB, eps_arr,
            ucA, vcA, wcA, ucB, vcB, wcB,
            dir_A=fA['dir'],
            dir_B=(fB['dir'] if fB is not None else 3),
            dx_arr=dx, dy_arr=dy, dz_arr=dz,
            inlet_flux_A=inlet_flux_A,
            inlet_flux_B=inlet_flux_B,
            inlet_mask_A=state._ltne_mask_A,
            inlet_mask_B=state._ltne_mask_B,
            Tb_prescribed=Tb_presc, max_iter=_eff_ltne_max_iter, tol=1e-5,
            Ta_init=state.Ta, Tb_init=state.Tb, Ts_init=state.Ts,
            alpha_T=float(cfg.get('ltne_alpha_T', 0.7)),
            **_refined_thermal,
            # force_cc_ltne: drop face velocities so the LTNE uses the cc
            # (non-stag) advection chunk — same scheme as the V&V'd 2D solver.
            # The face (stag) chunk's SOU uses a cc-reconstructed flux magnitude
            # inconsistent with its face base fluxes, which limit-cycles the
            # deferred correction for stiff low-Re water (point-0 root cause).
            # conservative_ltne (B-plan B2) overrides force_cc_ltne: the strict
            # face-centered conservation form lives in the stag kernel, so the
            # SIMPLE face velocities MUST flow through regardless.
            ufA=(ufA if _conservative_ltne or not cfg.get('force_cc_ltne', True) else None),
            vfA=(vfA if _conservative_ltne or not cfg.get('force_cc_ltne', True) else None),
            wfA=(wfA if _conservative_ltne or not cfg.get('force_cc_ltne', True) else None),
            ufB=ufB, vfB=vfB, wfB=wfB,
            mms_S_A_field=_mms_S_A,
            mms_S_B_field=_mms_S_B,
            mms_S_s_field=_mms_S_s,
            conservative_ltne=_conservative_ltne,
            # Asymmetric per-side ε (offset-isosurface δ). Passed ONLY when δ≠0
            # → δ=0 omits the kwargs → kernel's symmetric 0.5·ε default path →
            # bit-identical. eps_fA/eps_fB are single-channel (already-split)
            # fractions in the same real axes as eps_arr; kernel consumes them
            # without further halving.
            eps_A=(eps_fA_arr if float(cfg.get('delta_levelset', 0.0)) != 0.0
                   else None),
            eps_B=(eps_fB_arr if float(cfg.get('delta_levelset', 0.0)) != 0.0
                   else None),
            cancel_check=_cancel_check,
            return_info=True, **_model_kwargs)
        state.Ta, state.Tb, state.Ts, _ltne_info_d = _ltne_result
        if not _enth_gate:
            _check_property_water('3D temperature return')
            fluid_props.check_finite_temperatures(
                state.Ta, state.Tb, state.Ts, where='3D temperature return')
            _record_temperature_state('main', 'real-cell(x,y,z)-return')

        return _ltne_info_d

    def _solve_true_enthalpy(inputs):
        """Balance and project separate mass faces, then consume the warm start."""
        ufA, vfA, wfA = inputs.faces_A
        ufB, vfB, wfB = inputs.faces_B
        from sjtu_tpmshx.solvers.ltne_enthalpy_3d import (
            face_mass_fluxes, solve_ltne_enthalpy_3d_pipeline,
        )
        from sjtu_tpmshx.solvers.ltne_energy_3d import _project_faces_div_free
        _epsps = 0.5 * float(eps)
        # N4 (2026-06-28): under δ≠0 the per-side ṁ must weight by the actual
        # channel void (ε·split), matching the duty-extraction path and the
        # asymmetric eps_A/eps_B fields handed to the kernel. None at δ=0 →
        # symmetric 0.5·ε (every 703/production config; bit-identical).
        _ov_A_e, _ov_B_e = _prepared_eps_overrides(cfg, eps)
        _mdA = (1.0 if fA['dir'] % 2 == 0 else -1.0) * abs(
            _simple_mass_flow(sA, fA['dir'], eps_f_per_side=_epsps,
                              eps_side_override=_ov_A_e))
        _mdB = (1.0 if fB['dir'] % 2 == 0 else -1.0) * abs(
            _simple_mass_flow(sB, fB['dir'], eps_f_per_side=_epsps,
                              eps_side_override=_ov_B_e))
        _dPA = float(SIMPLESolver3D.extract_dP_face_extrap(sA))
        _P_A_local = _pressure_real_3d(sA, axis_map, P_inA - _dPA)
        _dPB = float(SIMPLESolver3D.extract_dP_face_extrap(sB))
        _P_B_local = _pressure_real_3d(sB, axis_map_B, P_inB - _dPB)

        _rho_A_real = _rho_real(sA, axis_map)
        _rho_B_real = _rho_real(sB, axis_map_B)
        _faces_A = [ufA.copy(), vfA.copy(), wfA.copy()]
        _faces_B = [ufB.copy(), vfB.copy(), wfB.copy()]
        _balance_stream_outflow(
            _faces_A, axis_map, eps_fA_arr * _rho_A_real, dx, dy, dz)
        _balance_stream_outflow(
            _faces_B, axis_map_B, eps_fB_arr * _rho_B_real, dx, dy, dz)
        _faces_A = _project_faces_div_free(
            *_faces_A, eps_fA_arr, _rho_A_real, dx, dy, dz)
        _faces_B = _project_faces_div_free(
            *_faces_B, eps_fB_arr, _rho_B_real, dx, dy, dz)
        _mass_faces_A = face_mass_fluxes(
            *_faces_A, _rho_A_real, eps_fA_arr, dx, dy, dz)
        _mass_faces_B = face_mass_fluxes(
            *_faces_B, _rho_B_real, eps_fB_arr, dx, dy, dz)
        state.Ta, state.Tb, state.Ts, _ltne_info_d = solve_ltne_enthalpy_3d_pipeline(
            Nx, Ny, Nz, dx, dy, dz, eps_arr, K_ss,
            state.h_vA_field, state.h_vB_field, _mdA, _mdB,
            T_inA, T_inB, P_inA, P_inB, fA['dir'], fB['dir'],
            fluid_A=fluid_type_A, fluid_B=fluid_type_B,
            pressure_A_field=_P_A_local,
            pressure_B_field=_P_B_local,
            mass_flux_A=_mass_faces_A,
            mass_flux_B=_mass_faces_B,
            eps_A_field=(eps_fA_arr if float(cfg.get('delta_levelset', 0.0)) != 0.0 else None),
            eps_B_field=(eps_fB_arr if float(cfg.get('delta_levelset', 0.0)) != 0.0 else None),
            Ta_init=state.Ta, Tb_init=state.Tb, Ts_init=state.Ts,
            n_sweep=int(cfg.get('ltne_enthalpy_nsweep', 25)),
            omega=float(cfg.get('ltne_enthalpy_omega', 0.6)),
            n_outer=int(cfg.get('ltne_enthalpy_outer', 1500)),
            tol=float(cfg.get('ltne_enthalpy_tol', 1e-3)),
            cancel_check=_cancel_check, coupled_energy_tol=0.001,
            equation_energy_tol=0.001)
        fluid_props.check_water_state(fluid_type_A, state.Ta, _P_A_local,
                                      where='3D enthalpy return A')
        fluid_props.check_water_state(fluid_type_B, state.Tb, _P_B_local,
                                      where='3D enthalpy return B')
        fluid_props.check_finite_temperatures(
            state.Ta, state.Tb, state.Ts, where='3D enthalpy return')

        return (_ltne_info_d, _mass_faces_A, _mass_faces_B,
                _P_A_local, _P_B_local, _dPA, _dPB)

    def _record_thermal_diagnostics(outer, _ltne_info_d, mode, *,
                                    _P_A_local, _P_B_local, _dPA, _dPB,
                                    _prof_t_ltne):
        """Record the existing certificates after native evidence is detached."""
        # B2 strict-conservation certificate (last outer iter holds final).
        state._eps_A_strict = _ltne_info_d.get('eps_A_strict')
        state._eps_B_strict = _ltne_info_d.get('eps_B_strict')
        state._eps_A_strict_cellmax = _ltne_info_d.get('eps_A_strict_cellmax')
        state._eps_B_strict_cellmax = _ltne_info_d.get('eps_B_strict_cellmax')
        if _cancel_check is not None and _cancel_check():
            raise CancelledError("compute cancelled by user")
        _ltne_info.append(dict(outer=outer, iters=_ltne_info_d.get('iterations',0),
                               converged=_ltne_info_d.get('converged',False),
                               residual=_ltne_info_d.get('residual',0.0)))
        if 'model_h_balance' in _ltne_info_d:
            _ltne_info[-1]['model_h_balance'] = dict(
                _ltne_info_d['model_h_balance'], outer_index=outer,
                converged=bool(_ltne_info_d['converged']),
                iterations=int(_ltne_info_d['iterations']))
        if mode == 'true_h':
            _ltne_info[-1]['true_h_balance'] = dict(
                Q_A=float(_ltne_info_d['Q_A']), Q_B=float(_ltne_info_d['Q_B']),
                units='W', outer_index=int(outer),
                converged=bool(_ltne_info_d['converged']),
                iterations=int(_ltne_info_d['iterations']),
                residual=float(_ltne_info_d['residual']),
                pressure_source='P_in - face-extrapolated dP + SIMPLE gauge',
                P_in_A_Pa=float(P_inA), P_in_B_Pa=float(P_inB),
                P_A_offset_Pa=float(P_inA - _dPA), P_B_offset_Pa=float(P_inB - _dPB),
                P_A_range_Pa=[float(_P_A_local.min()), float(_P_A_local.max())],
                P_B_range_Pa=[float(_P_B_local.min()), float(_P_B_local.max())])
            _ltne_info[-1]['true_h_balance'].update({key: _ltne_info_d[key] for key in (
                'exit_reason', 'enthalpy_clip_counts', 'effective_settings',
                'coupled_energy_balance', 'equation_energy_balance') if key in _ltne_info_d})
        if _prof_t_ltne is not None:
            _dt = _time.perf_counter() - _prof_t_ltne
            _log.info(f"[PROF] outer {outer}: LTNE {_dt:7.2f}s  "
                      f"iters={_ltne_info_d.get('iterations',0)}  "
                      f"conv={_ltne_info_d.get('converged',False)}  "
                      f"res={_ltne_info_d.get('residual',0.0):.2e}  "
                      f"(cap={_ltne_max_iter})")

    def _check_outer_convergence():
        _converged, _outer_deltas = _outer_conv.check(
            {'Ta': state.Ta, 'Tb': state.Tb, 'Ts': state.Ts})
        pressure_states = (inlet_pressure_state(sA, P_inA),
                           inlet_pressure_state(sB, P_inB))
        _converged = _converged and all(
            state is None or state['passed'] for state in pressure_states)
        state._outer_dT_hist.append(_outer_deltas)
        return _converged

    def _outer_step_3d(outer):
        # Cancel before each thermal stage. SIMPLE and thermal solvers also
        # check between iterations/chunks; an active JIT sweep finishes first.
        if _cancel_check is not None and _cancel_check():
            raise CancelledError("compute cancelled by user")
        if control.iteration is not None:
            control.iteration(f'outer {outer + 1}/{_max_outer}')
        if control.outer_iteration is not None:
            control.outer_iteration(outer + 1, _max_outer)
        control.report_progress(10 + int(80 * outer / _max_outer))
        inputs = _prepare_thermal_inputs(outer)
        _prof_t_ltne = _time.perf_counter() if _prof_3d_enabled() else None
        info = _solve_temperature(inputs)
        mass_A = inputs.model_kwargs.get('model_mass_A')
        mass_B = inputs.model_kwargs.get('model_mass_B')
        pressure_A = pressure_B = dP_A = dP_B = None
        if inputs.mode == 'true_h':
            info, mass_A, mass_B, pressure_A, pressure_B, dP_A, dP_B = _solve_true_enthalpy(inputs)
        if capture_native:
            state.native_evidence = _snapshot_thermal(
                outer, info, inputs.mode, mass_A, mass_B,
                pressure_A, pressure_B, inputs.faces_A, inputs.faces_B)
        _record_thermal_diagnostics(
            outer, info, inputs.mode, _P_A_local=pressure_A, _P_B_local=pressure_B,
            _dPA=dP_A, _dPB=dP_B, _prof_t_ltne=_prof_t_ltne)
        return _check_outer_convergence(), None

    def _refresh_flow_A(outer, _pressure_A):
        """A updates its temperature before density/viscosity and SIMPLE."""
        # Non-iso coupling: Ta real → solver coords via self-inverse perm
        Ta_sA = np.ascontiguousarray(state.Ta.transpose(solver_to_real_perm))
        # Invert the velocity/density spatial reflection for every fluid.
        # After transpose, the real stream axis maps to SIMPLE's stream axis.
        if axis_map['is_reverse']:
            _ssax_A = solver_to_real_perm[int(axis_map['stream_real_axis'])]
            Ta_sA = np.ascontiguousarray(np.flip(Ta_sA, axis=_ssax_A))
        # Critical: propagate Ta to T_field so SIMPLE inner _update_density()
        # uses local cell T, not stale T_in. (Mirror sB.update_T_field below.)
        with range_context(side='A', stage='property-refresh', layout='solver-cell(cross1,stream,cross2)'):
            sA.update_T_field(Ta_sA)
            P_abs = sA.P_ref_abs + sA.P
            if _mA.compressible:
                rho_new = P_abs / (R_AIR * Ta_sA)            # ideal gas
                mu_new_A = air_viscosity(Ta_sA)
            elif (fluid_type_A == 'sco2'
                  and run_environment(cfg, 'TPMSHX_SCO2_COMPRESSIBLE', '').lower()
                  in ('1', 'true', 'yes')):
                # A-side only (opt-in, EXPERIMENTAL): sco2 ρ/μ at the LOCAL absolute-P
                # field (ρ tracks local P, not frozen inlet P). ⚠ PROPERTY SIDE ONLY —
                # the full compressible continuity (∂ρ/∂P in the pressure correction,
                # Karki-Patankar ψ) is NOT implemented, so high-dP convergence is
                # unverified by this property switch.
                rho_new = sco2_props.sco2_prop("D", Ta_sA, P_abs)
                mu_new_A = sco2_props.sco2_prop("V", Ta_sA, P_abs)
            else:
                # Incompressible registry path. Water ignores P; default sCO2
                # evaluates ρ(T,P_in) and μ(T,P_in) with pressure frozen.
                rho_new = _mA.rho(Ta_sA, P_inA)
                mu_new_A = _mA.mu(Ta_sA, P_inA)
        if outer > 0:
            # Damped-Picard property update — the outer coupling's relaxation.
            # `_and_A` (opt-in, cfg['outer_anderson'], default OFF) replaces the
            # fixed _ALPHA_T with an Anderson least-squares mix over the last m
            # (x, G(x)) pairs; it falls back to EXACTLY this blend whenever the
            # candidate is inadmissible or history is short, so the disabled
            # path — and the golden gates — are bit-identical.
            if state._and_A is not None:
                (sA.rho_field, sA.mu_field), _ok_A = state._and_A.step(
                    [sA.rho_field, sA.mu_field], [rho_new, mu_new_A],
                    _ALPHA_T)
            else:
                sA.rho_field = np.ascontiguousarray(
                    _ALPHA_T * rho_new + (1.0 - _ALPHA_T) * sA.rho_field,
                    dtype=np.float64)
                sA.mu_field = np.ascontiguousarray(
                    _ALPHA_T * mu_new_A
                    + (1.0 - _ALPHA_T) * sA.mu_field, dtype=np.float64)
        else:
            sA.rho_field = np.ascontiguousarray(rho_new, dtype=np.float64)
            sA.mu_field = np.ascontiguousarray(mu_new_A, dtype=np.float64)
        eps_eff_A = sA.eps_field if hasattr(sA, 'eps_field') else sA.eps
        sA._mu_eff_field = np.ascontiguousarray(
            sA.mu_field / eps_eff_A, dtype=np.float64)
        if fluid_type_A in ('sco2', 'water'):
            sA._apply_massflux_inlet()

        T_avg = cell_average(state.Ta, dx, dy, dz)
        if _mA.compressible:
            if _p_shoot:
                sA.P_ref_abs = pressure_shooting_reference(_pressure_A)
            else:
                with range_context(side='A', stage='property-refresh', layout='mean'):
                    mu_avg = float(air_viscosity(T_avg))
                C_avg = (mu_avg * G_A / max(K_pred, 1e-16)
                         + cF_pred * G_A * G_A)
                P_out_sq_new = (P_inA ** 2
                                - 2.0 * R_AIR * T_avg * C_avg * L_stream)
                sA.P_ref_abs = pressure_initial_reference(
                    P_out_sq_new, P_inA, history=sA.pressure_iterations)
        else:
            # Incompressible reseed: D-F coefficients stay constant while the
            # registry supplies the fluid viscosity at the mean temperature.
            fluid_props.check_water_state(fluid_type_A, T_avg, P_inA,
                                          where='3D mean viscosity refresh A')
            with range_context(side='A', stage='property-refresh', layout='mean'):
                mu_avg = float(_mA.mu(T_avg, P_inA))
            C_avg = mu_avg * G_A / max(K_pred, 1e-16) + cF_pred * G_A * G_A
            _sco2_compress = (
                fluid_type_A == 'sco2'
                and run_environment(cfg, 'TPMSHX_SCO2_COMPRESSIBLE', '').lower()
                in ('1', 'true', 'yes'))
            if _sco2_compress:
                # Guard the A-side pressure seed with linear D-F at mean local
                # density. Failure of this approximation does not diagnose
                # physical choking. Report/raise before applying the floor.
                _rho_mean = max(cell_average(sA.rho_field, sA.dx, sA.dy, sA.dz), 1.0e-9)
                _dP_1d = C_avg * L_stream / _rho_mean
                _P_out_1d = float(P_inA - _dP_1d)
                if _P_out_1d <= PRESSURE_FLOOR_PA:
                    _ck = (f"Off-envelope sCO2: A-side local-pressure property "
                           f"experiment has an inadmissible 1D D-F pressure seed. "
                           f"Estimated drop {_dP_1d:.3e} Pa at inlet absolute P "
                           f"{float(P_inA):.0f} Pa gives outlet {_P_out_1d:.3e} Pa "
                           f"<= floor {PRESSURE_FLOOR_PA:.3e} Pa. "
                           f"This approximation does not establish physical choking "
                           f"or the absence of a steady multidimensional solution. "
                           f"Check flow and pressure inputs. [fluid A sCO2 reseed]")
                    if _env_mode == 'raise':
                        raise ChokedFlowError(_ck)
                    if _env_mode == 'warn':
                        _env_warnings.append(_ck)
                sA.P_ref_abs = max(_P_out_1d, PRESSURE_FLOOR_PA)
            else:
                # Default linear D-F seed uses the inlet-reference density.
                sA.P_ref_abs = max(float(P_inA - C_avg * L_stream / rho_A), 1.0e4)

        # Warm restart from current SIMPLE fields, using the effective iteration
        # budget and the same F2 convergence checks as the initial solve.
        _prof_t_sa = _time.perf_counter() if _prof_3d_enabled() else None
        with range_context(side='A', stage='main', layout='solver-cell(cross1,stream,cross2)'):
            _sa_conv, _sa_it = sA.solve(max_iter=_simple_max_iter(cfg, 600),
                                        tol=_simple_tol_default(cfg),
                                        verbose=False, cancel_check=_cancel_check)
        if not _sa_conv:
            _simple_nonconv.append(
                f"A@outer{outer}[{getattr(sA, 'exit_reason', '?')}]")
        if _prof_t_sa is not None:
            _log.info(f"[PROF] outer {outer}: SIMPLE_A {_time.perf_counter()-_prof_t_sa:7.2f}s  "
                      f"iters={_sa_it}  conv={_sa_conv}  "
                      f"(cap={_simple_max_iter(cfg, 600)})")

    def _refresh_thermal_properties():
        """Refresh conductivity/capacity between the A and B SIMPLE solves."""
        # Refresh fluid-property fields using the *local* T field, keeping
        # the spatial structure built by the zoned-geometry pass up-front
        # (#1). The previous implementation used `eps_f` (undefined in
        # this scope) and a scalar mean T, which both crashed for zoned
        # runs and flattened any non-uniform K_ff / h_v / rho_cp back to
        # a uniform field.
        # FIX (2026-06-24 audit): rebuild K_ffA from the per-side asymmetric void
        # fraction (eps_fA_arr), NOT the symmetric eps_f_arr — otherwise the δ≠0
        # offset-isosurface path reverts to the eps/2 split after outer iter 0.
        # Also re-add the optional thermal-dispersion term that the old in-place
        # refresh silently dropped. δ=0 ⇒ eps_fA_arr IS eps_f_arr (bit-identical);
        # disp_C_A=0 ⇒ no-op.
        with range_context(side='A', stage='property-refresh', layout='real-cell(x,y,z)'):
            if _mA.compressible:
                K_ffA[:] = eps_fA_arr * air_conductivity(state.Ta)
                _cpA_fld = air_cp(state.Ta)
            else:
                K_ffA[:] = eps_fA_arr * _mA.k(state.Ta, P_inA)
                _cpA_fld = _mA.cp(state.Ta, P_inA)
            if disp_C_A > 0.0:
                K_ffA[:] += K_disp_A
            if (_var_rhocp and sA is not None
                    and not (fluid_type_A == 'air' and _mA.compressible)):
                # SIMPLE's local ρ(P_local,T) → real coords (transpose + reverse flip)
                _rhoA_real = sA.rho_field.transpose(axis_map['solver_to_real_perm'])
                if axis_map['is_reverse']:
                    _rhoA_real = np.flip(_rhoA_real, axis=axis_map['stream_real_axis'])
                state.rho_cp_fA[:] = np.ascontiguousarray(_rhoA_real) * _cpA_fld
            elif not (_var_rhocp and fluid_type_A == 'air' and _mA.compressible):
                _rhoA_fld = (air_density(state.Ta, P_inA) if _mA.compressible
                             else _mA.rho(state.Ta, P_inA))
                state.rho_cp_fA[:] = _rhoA_fld * _cpA_fld
        # h_v rebuilt at top of next outer iter using LOCAL Re (#B fix).

        if state.Tb is not None:
            # B1 1.1: per-fluid primitives via registry; the local-P
            # rho·cp path is compressible-only physics (water keeps ρ(T)).
            with range_context(side='B', stage='property-refresh', layout='real-cell(x,y,z)'):
                state.K_ffB[:] = eps_fB_arr * _mB.k(state.Tb, P_inB)  # FIX (2026-06-24 audit): asym per-side eps + re-add dispersion (see fluid-A note above); P for sco2
                if disp_C_B > 0.0:
                    state.K_ffB[:] += K_disp_B
                if (_mB.compressible and _var_rhocp and sB is not None
                        and fluid_type_B != 'air'):
                    _rhoB_real = sB.rho_field.transpose(perm_B)
                    if axis_map_B['is_reverse']:
                        _rhoB_real = np.flip(
                            _rhoB_real, axis=axis_map_B['stream_real_axis'])
                    state.rho_cp_fB[:] = np.ascontiguousarray(_rhoB_real) * _mB.cp(state.Tb, P_inB)
                elif not (_var_rhocp and fluid_type_B == 'air' and _mB.compressible
                          and sB is not None):
                    state.rho_cp_fB[:] = _mB.rho(state.Tb, P_inB) * _mB.cp(state.Tb, P_inB)
            # h_vB rebuilt at top of next outer iter using LOCAL Re (#B fix).

    def _refresh_flow_B(outer, _pressure_B):
        """B updates its temperature after density/viscosity and pressure."""
        Tb_sB = np.ascontiguousarray(state.Tb.transpose(perm_B))
        # Match B's velocity/density frame, as for A above.
        if axis_map_B['is_reverse']:
            _ssax_B = perm_B[int(axis_map_B['stream_real_axis'])]
            Tb_sB = np.ascontiguousarray(np.flip(Tb_sB, axis=_ssax_B))
        with range_context(side='B', stage='property-refresh', layout='solver-cell(cross1,stream,cross2)'):
            if _mB.compressible:
                P_abs_B = sB.P_ref_abs + sB.P
                rho_new_B = P_abs_B / (R_AIR * Tb_sB)
            else:
                rho_new_B = _mB.rho(Tb_sB, P_inB)   # water ignores P; sco2 (T,P_in)
            mu_new_B = _mB.mu(Tb_sB, P_inB)          # air/water ignore P; sco2 needs P
        if outer > 0:
            # Mirror of the fluid-A property update above (see comment
            # there). Separate Anderson instance per side: A's blend is
            # applied BEFORE the SIMPLE-A re-solve and B's before SIMPLE-B,
            # so the two are sequential, not simultaneous — block-wise
            # acceleration respects that structure.
            if state._and_B is not None:
                (sB.rho_field, sB.mu_field), _ok_B = state._and_B.step(
                    [sB.rho_field, sB.mu_field], [rho_new_B, mu_new_B],
                    _ALPHA_T)
            else:
                sB.rho_field = np.ascontiguousarray(
                    _ALPHA_T * rho_new_B + (1.0 - _ALPHA_T) * sB.rho_field,
                    dtype=np.float64)
                sB.mu_field = np.ascontiguousarray(
                    _ALPHA_T * mu_new_B + (1.0 - _ALPHA_T) * sB.mu_field,
                    dtype=np.float64)
        else:
            sB.rho_field = np.ascontiguousarray(rho_new_B, dtype=np.float64)
            sB.mu_field = np.ascontiguousarray(mu_new_B, dtype=np.float64)
        eps_eff_B = sB.eps_field if hasattr(sB, 'eps_field') else sB.eps
        sB._mu_eff_field = np.ascontiguousarray(
            sB.mu_field / eps_eff_B, dtype=np.float64)
        if fluid_type_B in ('sco2', 'water'):
            sB._apply_massflux_inlet()

        if _mB.compressible:   # P_ref recompute is compressible-only
            Tb_avg = cell_average(state.Tb, dx, dy, dz)
            if _p_shoot:
                sB.P_ref_abs = pressure_shooting_reference(_pressure_B)
            else:
                with range_context(side='B', stage='property-refresh', layout='mean'):
                    mu_avg_B = float(_mB.mu(Tb_avg))
                # Use the B-side permeability / Forchheimer coeff (audit
                # 2026-06-28): the outer-loop reseed previously used fluid
                # A's K_pred / cF_pred, inconsistent with the initial B
                # seed (L1829, K_pred_B / cF_pred_B). Identical for
                # same-geometry same-fluid A/B; differs for asymmetric ε
                # (δ≠0) or differing per-side cF.
                C_avg_B = (mu_avg_B * G_B / max(K_pred_B, 1e-16)
                           + cF_pred_B * G_B * G_B)
                P_out_sq_B_new = (P_inB ** 2
                                  - 2.0 * R_AIR * Tb_avg * C_avg_B
                                  * L_stream_B)
                sB.P_ref_abs = pressure_initial_reference(
                    P_out_sq_B_new, P_inB, history=sB.pressure_iterations)

        with range_context(side='B', stage='property-refresh', layout='solver-cell(cross1,stream,cross2)'):
            sB.update_T_field(Tb_sB)
        _prof_t_sb = _time.perf_counter() if _prof_3d_enabled() else None
        with range_context(side='B', stage='main', layout='solver-cell(cross1,stream,cross2)'):
            _sb_conv, _sb_it = sB.solve(max_iter=_simple_max_iter(cfg, 600),
                                        tol=_simple_tol_default(cfg),
                                        verbose=False, cancel_check=_cancel_check)
        if not _sb_conv:
            _simple_nonconv.append(
                f"B@outer{outer}[{getattr(sB, 'exit_reason', '?')}]")
        if _prof_t_sb is not None:
            _log.info(f"[PROF] outer {outer}: SIMPLE_B {_time.perf_counter()-_prof_t_sb:7.2f}s  "
                      f"iters={_sb_it}  conv={_sb_conv}  "
                      f"(cap={_simple_max_iter(cfg, 600)})")
            _prof_res_trace(f"outer {outer} SIMPLE_B", sB)

        # Other routes refreshed rho_cp_fB above; variable-density air
        # refreshes it before the next thermal call, after this SIMPLE solve.

        # Re-extract the full B vector for the next LTNE pass.
        ucB2, vcB2, wcB2 = _solver_velocity_to_real(
            sB, axis_map_B, (Nx, Ny, Nz))
        ucB[:] = ucB2
        vcB[:] = vcB2
        wcB[:] = wcB2

    def _outer_post_3d(outer, _carry):
        # Measure both completed flows before either temperature refresh.
        pressure_A = inlet_pressure_state(sA, P_inA)
        pressure_B = inlet_pressure_state(sB, P_inB)
        _check_property_water('3D property refresh')
        _refresh_flow_A(outer, pressure_A)
        _refresh_thermal_properties()
        if sB is not None and state.Tb is not None:
            _refresh_flow_B(outer, pressure_B)

    # The skeleton returns (last_iter, converged). 3D used to DISCARD both, so
    # the outer-coupling verdict never reached `solver_converged` (2D captures
    # it — solve_2d.py:1173). A run that burned every outer iteration with ΔT
    # still bouncing could therefore report success as long as the final LTNE
    # inner pass and the SIMPLE solves converged. (Audit 2026-07-12.)
    state._outer_last_iter, state._outer_converged = run_outer_coupling(
        max_iter=_max_outer, step=_outer_step_3d, post=_outer_post_3d)
    # Metrics use P_ref_abs + gauge, independently of the true-h kernel offset.
    for fluid, temperature, solver, amap, side in (
            (fluid_type_A, state.Ta, sA, axis_map, 'A'),
            (fluid_type_B, state.Tb, sB, axis_map_B, 'B')):
        if fluid == 'water' and solver is not None:
            fluid_props.check_water_state(
                fluid, temperature, _pressure_real_3d(solver, amap, solver.P_ref_abs),
                where=f'3D final report state {side}')
        elif fluid == 'sco2' and solver is not None:
            sco2_props._validate_state(
                temperature, _pressure_real_3d(solver, amap, solver.P_ref_abs),
                where=f'3D final report state {side}')

    if not (sB is not None and 'sco2' in (fluid_type_A, fluid_type_B)):
        _record_temperature_state('final', 'real-cell(x,y,z)')

    return state
