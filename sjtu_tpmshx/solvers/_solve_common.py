"""Shared SIMPLE residuals, convergence and physical inlet-pressure checks."""
from __future__ import annotations

import numpy as np

from sjtu_tpmshx.domain.run_environment import require_f2_mode, run_environment
from sjtu_tpmshx.result_math import pressure_face_values


INLET_PRESSURE_REL_TOL = 1e-4


def inlet_pressure_state(solver, specified_Pa):
    """Actual ideal-gas port pressures, using geometric areas in either dimension.

    The pressure anchor pins outlet *cells*. The extrapolated outlet face
    can have nonzero gauge pressure, so anchor + dP is not the inlet pressure.
    """
    if solver is None or solver.fluid_type != 'ideal_gas':
        return None
    if solver.P.ndim == 2:
        area, stream_widths = solver.dx_arr, solver.dy_arr
        inlet, outlet = solver.inlet_geom_frac, solver.outlet_geom_frac
    else:
        area, stream_widths = solver.dx[:, None] * solver.dz[None, :], solver.dy
        inlet, outlet = solver.inlet_frac, solver.outlet_frac
    pin, pout = pressure_face_values(solver.P, stream_widths)
    def mean(values, weights):
        mask = weights > 0.
        return float(np.average(values[mask], weights=weights[mask]))
    inlet_gauge = mean(pin, inlet * area)
    outlet_gauge = mean(pout, outlet * area)
    realized = float(solver.P_ref_abs) + inlet_gauge
    outlet_abs = float(solver.P_ref_abs) + outlet_gauge
    residual = (realized - float(specified_Pa)) / float(specified_Pa)
    return dict(specified_Pa=float(specified_Pa), realized_Pa=realized,
                outlet_Pa=outlet_abs, outlet_gauge_Pa=outlet_gauge,
                relative_error=residual, relative_tolerance=INLET_PRESSURE_REL_TOL,
                passed=bool(np.isfinite(residual) and abs(residual) < INLET_PRESSURE_REL_TOL),
                definition='geometric open-area mean at physical port faces')


def pressure_shooting_target_sq(state):
    """P² iteration at physical faces; callers convert back to a cell anchor."""
    return (state['specified_Pa'] ** 2
            - (state['realized_Pa'] ** 2 - state['outlet_Pa'] ** 2))


def f2_state_is_finite(solver, velocities):
    """Numerical qualification of the actual F2 state, not a physical gate."""
    return all(np.isfinite(field).all() for field in
               (*velocities, solver.P, solver.rho_field, solver.T_field))


def f2_nonfinite_exit(solver, iterations):
    solver.exit_reason = 'nonfinite'
    solver.final_res = float('nan')
    # Finite diagnostics no longer certify this state. Retain any observed
    # NaN/Inf and the residual histories for diagnosis.
    for name in ('final_res_mom', 'final_res_mass_local', 'final_res_mass_global',
                 'outlet_backflow_frac', 'res_norm_ref'):
        value = getattr(solver, name, None)
        if value is None or np.isfinite(value):
            setattr(solver, name, float('nan'))
    if hasattr(solver, 'f2_cert_post_rescale_ok'):
        solver.f2_cert_post_rescale_ok = False
    return False, iterations


def momentum_component_residuals(nums, dens, floor_fraction):
    """Keep invalid raw observations out of finite-only normalization/max."""
    if not np.isfinite((*nums, *dens)).all():
        return (float('nan'),) * len(nums)
    floor = floor_fraction * max(dens)

    def ratio(n, d):
        den = max(d, floor)
        return n / den if den > 0.0 else 0.0

    return tuple(ratio(n, d) for n, d in zip(nums, dens))


def global_mass_residual(mdot_in, mdot_out):
    if not np.isfinite((mdot_in, mdot_out)).all():
        return float('nan')
    return abs(mdot_out - mdot_in) / abs(mdot_in) if abs(mdot_in) > 1e-14 else 0.0


def configure_convergence(solver, cfg, solver_config=None):
    """Apply captured environment > typed settings > cfg > shared defaults."""
    def knob(name, default):
        value = getattr(solver_config, name, None)
        if value is None:
            value = cfg.get(name)
        return default if value is None else value

    solver.convergence_mode = require_f2_mode(run_environment(
        cfg, 'TPMSHX_CONV_MODE', knob('convergence_mode', 'f2')))
    solver.mom_tol = float(knob('mom_tol', 1e-4))
    solver.mass_local_tol = float(knob('mass_local_tol', 1e-6))
    solver.mass_global_tol = float(knob('mass_global_tol', 1e-6))


class F2Monitor:
    """Shared 2D/3D gate: momentum, local/global mass and outlet backflow.

    A static velocity field triggers a residual check; it cannot certify
    convergence by itself. Require consecutive passing checks. A stationary
    momentum plateau that fails the gates returns failure, preserving its evidence.
    Momentum reassembly is scheduled sparsely until a confirmation starts.
    """

    def __init__(self, solver, vels, min_iter: int):
        g = lambda k, d: getattr(solver, k, d)  # noqa: E731
        self.mom_tol = float(g('mom_tol', 1e-4))
        self.mass_local_tol = float(g('mass_local_tol', 1e-6))
        self.mass_global_tol = float(g('mass_global_tol', 1e-6))
        # Fourth gate (2026-07-13, codex review): the GLOBAL mass residual is a
        # SIGNED scalar — positive and negative outlet fluxes can cancel inside
        # it, so a recirculating outlet can read as perfectly mass-balanced
        # (that is exactly why `outlet_backflow_frac` was reported separately,
        # ledger C7). Reporting alone lets a separated/recirculating "solution"
        # exit as converged; gate it. Every measured baseline has backflow == 0,
        # so the default is inert there (bit-identical).
        self.backflow_max = float(g('f2_backflow_max', 0.01))
        self.n_confirm = int(g('f2_n_confirm', 2))
        self.mom_every = max(1, int(g('f2_mom_every', 5)))
        self.vtol = float(g('f2_velocity_check_tol', 1e-4))
        self.stall_window = int(g('f2_stall_window', 60))
        self.stall_ratio = float(g('f2_stall_ratio', 1e-3))
        self.min_iter = int(min_iter)
        self._prev = [v.copy() for v in vels]
        self._streak = 0
        self._mom_at_window_start = None
        self._window_start_it = 0
        self.last_vd = float('inf')
        for name in ('mom_residuals', 'mass_local_residuals', 'mass_global_residuals'):
            if not hasattr(solver, name):
                setattr(solver, name, [])

    def velocity_delta(self, vels) -> float:
        """max|Δφ| / scale; refresh the snapshot after every observation."""
        deltas = [np.max(np.abs(v - p)) for v, p in zip(vels, self._prev)]
        scale = max(max(np.max(np.abs(v)) for v in vels), 1e-30)
        vd = max(deltas) / scale
        for p, v in zip(self._prev, vels):
            p[:] = v
        self.last_vd = vd
        return vd

    def should_eval_momentum(self, it: int, vd: float) -> bool:
        if it < self.min_iter:
            return False
        if self._streak > 0:
            return True                 # confirming — check every iteration
        if vd < self.vtol:
            return True                 # velocity static — check NOW
        return (it % self.mom_every) == 0

    def submit(self, it: int, R_mom: float, R_mass_local: float,
               R_mass_global: float, vd: float, backflow_frac: float = 0.0):
        """Call ONLY on iterations where R_mom was actually evaluated.

        `backflow_frac` is the outlet backflow fraction (|reverse flux| /
        |total outlet flux|) — the fourth gate; defaults to 0.0 so callers
        that cannot measure it degrade to the old three-gate behaviour.

        Returns None (keep iterating) | 'tol' (converged) | 'stall' (give up)
        | 'nonfinite' (invalid numerical observation). Both failures mean False.
        """
        if not np.isfinite((R_mom, R_mass_local, R_mass_global, vd, backflow_frac)).all():
            self._streak = 0
            return 'nonfinite'
        if it < self.min_iter:
            return None
        ok = (R_mom < self.mom_tol
              and R_mass_local < self.mass_local_tol
              and R_mass_global < self.mass_global_tol
              and backflow_frac <= self.backflow_max)
        if ok:
            self._streak += 1
            return 'tol' if self._streak >= self.n_confirm else None
        self._streak = 0

        # A near-static field with a stalled momentum residual is a failure.
        if (self._mom_at_window_start is None
                or (it - self._window_start_it) >= self.stall_window):
            if (self._mom_at_window_start is not None
                    and vd < 10.0 * self.vtol
                    and R_mom > self._mom_at_window_start
                        * (1.0 - self.stall_ratio)):
                return 'stall'
            self._mom_at_window_start = R_mom
            self._window_start_it = it
        return None
