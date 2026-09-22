"""Construct runtime SIMPLE instances on an already prepared physical grid."""
from __future__ import annotations
from typing import Any
from sjtu_tpmshx.domain.run_environment import run_environment
import numpy as np
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.solvers._solve_common import (
    configure_convergence, pressure_initial_reference, pressure_shooting_reference,
)
from sjtu_tpmshx.models.grid import cell_average
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

def build_runtime(cfg: dict[str, Any], prepared: dict[str, Any], *,
                  residual_cb=None) -> dict[str, Any]:
    """Construct SIMPLE helpers on the prepared grid; report via RunControl."""
    L = cfg['L']; H = cfg['H']
    N_x = cfg['N_x']; N_y = cfg['N_y']
    tpms_type = cfg['tpms_type']
    Lcell = cfg['Lcell']; t_wall = cfg['t_wall']
    eps = cfg['eps']; r_h = cfg['r_h']
    za = cfg['za']

    energy_dx, energy_dy = prepared['energy_dx'], prepared['energy_dy']
    _x_breaks, _y_breaks = set(prepared['_x_breaks']), set(prepared['_y_breaks'])
    N_x, N_y = cfg['N_x'], cfg['N_y']

    # Build the _run_simple closure here so it captures all needed locals.
    # It is returned in fields and called by Phase 3.
    simple_warnings = {}

    def _run_simple(cfg_fluid, rho_f, mu_f, T_in_f, u_f, label, P_in_abs=101325.0,
                    T_field_real=None, fluid_type='ideal_gas',
                    p_shoot_prev=None,
                    rho_inlet_ref=None, cancel_check=None):
        """Build + solve SIMPLE for one fluid.

        T_field_real : optional 2D array (Nx, Ny) of cell-centered T. When
        supplied (after first outer iter, from LTNE Ta/Tb), propagated to
        SIMPLE.T_field via update_T_field so inner _update_density() uses
        local T (not stale scalar T_in_f). Required for compressible coupling
        consistency across outer iters.

        fluid_type : 'ideal_gas' (default, air) or 'incompressible' (water).
        Controls whether SIMPLE's _update_density runs ρ = P / (R·T) per
        iter or treats ρ as fixed (water). Option B 2026-05-09.

        p_shoot_prev : physical port-pressure state from the previous SIMPLE
        solve. The pressure iteration is enabled by default for ideal gas.
        """
        d = cfg_fluid['dir']
        is_x = d in (0, 1)  # x-flow = dirs {+x, -x}
        pipe_lo = cfg_fluid['in_ctr'] - cfg_fluid['in_w'] / 2
        pipe_hi = cfg_fluid['in_ctr'] + cfg_fluid['in_w'] / 2
        out_lo = cfg_fluid.get('out_ctr', cfg_fluid['in_ctr']) - cfg_fluid.get('out_w', cfg_fluid['in_w']) / 2
        out_hi = cfg_fluid.get('out_ctr', cfg_fluid['in_ctr']) + cfg_fluid.get('out_w', cfg_fluid['in_w']) / 2

        flow = cfg['flow_inputs'][label[-1]]
        # Transform rho_f / mu_f (either or both may be 2D) to SIMPLE coords.
        def _to_simple_coords(fld):
            if np.ndim(fld) != 2:
                return fld
            if is_x:
                out = fld.T.copy()
                if d == 1:
                    out = out[:, ::-1].copy()
            else:
                out = fld.copy()
                if d == 3:
                    out = out[:, ::-1].copy()
            return out
        rho_simple = _to_simple_coords(rho_f)
        mu_simple = _to_simple_coords(mu_f)

        # Mass-flux inlet reference density ρ(T_in, P_in): the physical inlet
        # density the pipeline used to convert ṁ → u_f. Passed explicitly so the
        # pin holds the PHYSICAL throughput even though this pipeline recreates
        # the solver every outer iter with an already-compressed rho_f (a
        # field-based capture would ratchet here). The production pipeline
        # supplies the registered inlet density for every fluid. The branch
        # below retains the convention for direct ideal-gas callers.
        if rho_inlet_ref is None and fluid_type == 'ideal_gas':
            rho_inlet_ref = float(P_in_abs) / (287.05 * float(T_in_f))

        # P_ref_abs anchors outlet cells. The initial 1D estimate and later
        # physical-face corrections use the same policy as 3D.
        shooting = (fluid_type == 'ideal_gas' and p_shoot_prev is not None
                    and cfg.get('p_in_shooting',
                                run_environment(cfg, 'TPMSHX_P_IN_SHOOT', '1') == '1'))
        pressure_history = p_shoot_prev['iterations'] if shooting else []
        L_stream = float(L if is_x else H)
        if fluid_type == 'ideal_gas':
            from sjtu_tpmshx.models.envelope import predict_outlet_p_sq
            _K0, _cF0 = flow['seed_K_m2'], flow['seed_cF_per_m']
            _rho_in = float(P_in_abs) / (287.05 * float(T_in_f))
            _G = _rho_in * abs(float(u_f))                   # mass flux ρ·u
            _mu_in = cell_average(mu_f, energy_dx, energy_dy)
            _C = _mu_in * _G / max(_K0, 1e-16) + _cF0 * _G * _G
            _P_out_sq = predict_outlet_p_sq(float(P_in_abs), float(T_in_f),
                                            _C, L_stream)
            P_ref_out = (pressure_shooting_reference(p_shoot_prev) if shooting else
                         pressure_initial_reference(_P_out_sq, P_in_abs,
                                                    history=pressure_history))
        else:
            # Incompressible (water, sCO2 Phase-A): ρ is frozen, so the gauge
            # LEVEL does not feed back into the physics at all — only gradients
            # matter. Keep the inlet value (bit-identical to the old behaviour on
            # every water/incompressible solve).
            P_ref_out = float(P_in_abs)

        width, length, nx, ny = (H, L, N_y, N_x) if is_x else (L, H, N_x, N_y)
        s = SIMPLESolver(width, length, nx, ny, tpms_type, Lcell, t_wall,
                         eps, r_h, rho_simple, mu_simple, T_in_f,
                         pipe_lo, pipe_hi, u_f,
                         outlet_lo=out_lo, outlet_hi=out_hi,
                         wall_refine=False, P_ref_abs=P_ref_out,
                         rho_inlet_ref=rho_inlet_ref, fluid_type=fluid_type,
                         uniform_inlet=cfg_fluid.get('uniform_inlet_2d', False),
                         dx_arr=flow['dx'], dy_arr=flow['dy'],
                         K_arr=flow['K_m2'], cF_arr=flow['cF_per_m'])
        if 'boundary_openings' in cfg:
            openings = cfg['boundary_openings'][label[-1]]
            for key, actual in (('in_geom_frac', s.inlet_geom_frac),
                                ('out_geom_frac', s.outlet_geom_frac),
                                ('in_profile_frac', s.inlet_frac),
                                ('out_profile_frac', s.outlet_frac)):
                supplied = np.asarray(openings[key])
                if supplied.shape != actual.shape or not np.allclose(supplied, actual, rtol=1e-12, atol=1e-15):
                    raise ValueError(f'prepared {label} {key} disagrees with its grid and port geometry')
        # Zoned ε push (#2 fix): if zone config gives spatial eps_arr, push to
        # SIMPLE so its continuity uses ∇·(ε·ρ·u)=0 instead of ∇·(ρ·u)=0.
        # Uniform ε leaves default (eps_field=eps everywhere) unchanged.
        if za is not None and za.get('eps_arr') is not None:
            eps_real = np.asarray(za['eps_arr'], dtype=np.float64)
            eps_sol = _to_simple_coords(eps_real)
            if eps_sol.shape == s.eps_field.shape:
                s.eps_field = np.ascontiguousarray(eps_sol, dtype=np.float64)
                # 2026-07-13 audit: refresh the Brinkman μ/ε to the zoned ε.
                # `_mu_eff_field` is built from the SCALAR ε at construction
                # and its only refresh path (`update_T_field`) fires on the
                # first outer T-update, ideal_gas only — so without this the
                # air side's first solve and the water side's WHOLE solve run
                # Brinkman on the uniform ε while continuity runs the zoned ε.
                s._mu_eff_field = np.ascontiguousarray(
                    s.mu_field / s.eps_field, dtype=np.float64)
        s._df_metadata = flow['metadata']
        s.pressure_iterations = pressure_history
        # Graded drag affects the initial estimate only. Later iterations use
        # the pressure measured from the actual graded flow.
        if fluid_type == 'ideal_gas' and not shooting:
            _K_rows = np.asarray(s._K_arr, dtype=np.float64)
            _cF_rows = np.asarray(s._cF_arr, dtype=np.float64)
            if (float(_K_rows.max()) != float(_K_rows.min())
                    or float(_cF_rows.max()) != float(_cF_rows.min())):
                _C_rows = (_mu_in * _G / np.maximum(_K_rows, 1e-16)
                           + _cF_rows * _G * _G)
                _P_out_sq_g = predict_outlet_p_sq(
                    float(P_in_abs), float(T_in_f),
                    float(np.mean(_C_rows)), L_stream)
                pressure_history.clear()
                s.P_ref_abs = pressure_initial_reference(
                    _P_out_sq_g, P_in_abs, history=pressure_history)
        _max_it = 10000
        _sol_knobs = getattr(cfg.get('compute_cfg'), 'solver', None)
        if _sol_knobs is not None and _sol_knobs.max_iter_simple is not None:
            _max_it = int(_sol_knobs.max_iter_simple)
        # Propagate Ta/Tb to SIMPLE.T_field if available (compressible coupling
        # fix; without this _update_density uses stale scalar T_in inside SIMPLE)
        if T_field_real is not None:
            T_simple = _to_simple_coords(T_field_real)
            if T_simple.shape == s.T_field.shape:
                s.update_T_field(np.ascontiguousarray(T_simple))
        # Forward the pressure residual through the caller's RunControl hook.
        _side = 'A' if 'A' in label else 'B'
        def _progress_cb(it, res, _s=_side):
            if residual_cb is not None:
                residual_cb(_s, int(it), float(res))
        # 2026-05-07: 2D SIMPLE max_iter 5000 → 10000. Crossflow with
        # partial-B inlet (e.g. user's pipeB w=0.068m of L=0.182) +
        # high-u Forchheimer-branch needs more iters to drive residual
        # below tol. 5000 left B at res~3e-3 with target 1e-3.
        configure_convergence(s, cfg, _sol_knobs)

        conv, n_it = s.solve(max_iter=_max_it, verbose=False,
                               progress_cb=_progress_cb, cancel_check=cancel_check)
        if not conv:
            simple_warnings[label] = (
                f"SIMPLE ({label}): not converged after {n_it} iters "
                f"(exit={getattr(s, 'exit_reason', '?')}, "
                f"mom={getattr(s, 'final_res_mom', None)}, "
                f"mass_local={getattr(s, 'final_res_mass_local', None)}, "
                f"mass_global={getattr(s, 'final_res_mass_global', None)})")
        else:
            # A converged re-solve SUPERSEDES an earlier failure on the same
            # side (2026-07-12). This dict is keyed by label and was only ever
            # WRITTEN on failure, never cleared — so one stalled warm-up solve
            # stuck for the whole run and forced solver_converged=False even
            # though every field the run reported came from a converged solve.
            # The outer loop re-solves SIMPLE on every iteration, so the early
            # ones are transient warm-starts, not the answer. Mirrors the 3D
            # fix (judge the FINAL solve per side).
            simple_warnings.pop(label, None)

        # Use the solved field: wall fluxes already impose no-slip at the housing.
        main_cc = 0.5 * (s.v[:, :-1] + s.v[:, 1:])    # main flow (v in SIMPLE)
        cross_cc = 0.5 * (s.u[:-1, :] + s.u[1:, :])   # cross flow (u in SIMPLE)
        if is_x:
            # SIMPLE (perp=Ny, flow=Nx) → real (Nx, Ny)
            uc_real = main_cc.T     # main flow → x
            vc_real = cross_cc.T    # cross flow → y
            if d == 1:  # -x: flip
                uc_real = -uc_real[::-1, :]
                vc_real = vc_real[::-1, :]
        else:
            vc_real = main_cc       # main flow → y
            uc_real = cross_cc      # cross flow → x
            if d == 3:  # -y: flip
                vc_real = -vc_real[:, ::-1]
                uc_real = uc_real[:, ::-1]

        return uc_real, vc_real, s

    fields = {
        'energy_dx': energy_dx, 'energy_dy': energy_dy,
        '_x_breaks': _x_breaks, '_y_breaks': _y_breaks,
        '_run_simple': _run_simple,
        'simple_warnings': simple_warnings,
    }
    return fields
