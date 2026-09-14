"""Construct runtime SIMPLE instances on an already prepared physical grid."""
from __future__ import annotations
from typing import Any
from sjtu_tpmshx.domain.run_environment import run_environment
import numpy as np
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

def build_runtime(cfg: dict[str, Any], prepared: dict[str, Any], *,
                      live_residuals: dict | None = None, residual_cb=None) -> dict[str, Any]:
    """Phase 2 (Qt-free): construct aligned grid arrays and SIMPLE
    helper closures.

    Audit C4 (L-a-2): renamed from ``_build_fields(window, cfg)``. The
    two window touches were:

    1. ``window._is_x_dir(d)`` — inlined as ``d in (0, 1)`` per the
       original ``Main_Menu._is_x_dir`` body.
    2. ``window._live_residuals`` (UI sparkline buffer) — now passed
       explicitly via the ``live_residuals`` keyword.  Pipeline2D
       leaves it at ``None`` (no UI); the legacy UI adapter
       :func:`_build_fields` extracts it from the window.
    """
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
                    p_shoot_prev=None, df_method=None,
                    rho_inlet_ref=None, fluid_name='air', cancel_check=None):
        """Build + solve SIMPLE for one fluid.

        T_field_real : optional 2D array (Nx, Ny) of cell-centered T. When
        supplied (after first outer iter, from LTNE Ta/Tb), propagated to
        SIMPLE.T_field via update_T_field so inner _update_density() uses
        local T (not stale scalar T_in_f). Required for compressible coupling
        consistency across outer iters.

        fluid_type : 'ideal_gas' (default, air) or 'incompressible' (water).
        Controls whether SIMPLE's _update_density runs ρ = P / (R·T) per
        iter or treats ρ as fixed (water). Option B 2026-05-09.

        p_shoot_prev : optional (P_ref_abs_prev, dP_solved_prev) from the
        PREVIOUS outer iteration's converged SIMPLE (this pipeline recreates
        the solver each outer iter). Consumed only when the C8 shooting knob
        is ON and fluid_type is ideal_gas — see the shooting block below.
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

        # ── P_ref_abs is the OUTLET absolute pressure, not the inlet ────────
        # BUG FIX 2026-07-12 (ledger C8). This used to pass `P_ref_abs=P_in_abs`.
        #
        # `P_ref_abs` is the ABSOLUTE pressure the solver's GAUGE field is
        # measured from, and the gauge field's zero sits at the OUTLET: the pp
        # equation pins the outlet row `Pp = 0` (`_kernels_simple_2d.py:735`) and
        # `_correct_jit` never corrects those cells' P, so the outlet gauge stays
        # 0 for the entire solve. Hence
        #
        #       outlet absolute pressure  ==  P_ref_abs   (exactly)
        #       inlet  absolute pressure  ==  P_ref_abs + Δp
        #
        # Passing the INLET pressure therefore anchored the OUTLET at the inlet
        # and floated the whole field up by Δp. Measured on Shanghai case 16
        # (experiment: 304.7 kPa in -> 126.1 kPa out, Δp = 178.7 kPa):
        #
        #       before:  inlet 407.3 kPa -> outlet 304.7 kPa,  Δp =  102.6 kPa
        #                                          ^^^^^ the experiment's INLET
        #
        # The outlet density was ~2.4x too high, so the compressible physics was
        # wrong throughout and Δp came out 43 % low. The error scales with
        # Δp/P_in: negligible for low-Δp designs (case 1: ~1 %), catastrophic for
        # high-Δp ones. It was invisible because the 2D validation gate is
        # kernel-direct and seeds this correctly itself — the gate was validating
        # a path production does not run.
        #
        # (An older project guide described this as "2D is inlet-anchored ... rarely chokes".
        # That was a description of the SYMPTOM, not a design: it "rarely chokes"
        # because it never lets the outlet pressure fall.)
        #
        # 3D always did this right (`run_stack_3d._seed_p_ref`, ~line 620). Use
        # the same 1D compressible Forchheimer closed form, with the SAME (K, cF)
        # the solver itself will build (`simple_solver.py:409-412`), so the seed
        # can never drift from the drag it is seeding for.
        L_stream = float(L if is_x else H)
        if fluid_type == 'ideal_gas':
            from sjtu_tpmshx.solvers.envelope import predict_outlet_p_sq
            _K0, _cF0 = flow['seed_K_m2'], flow['seed_cF_per_m']
            _rho_in = float(P_in_abs) / (287.05 * float(T_in_f))
            _G = _rho_in * abs(float(u_f))                   # mass flux ρ·u
            _mu_in = float(np.mean(mu_f)) if np.ndim(mu_f) else float(mu_f)
            _C = _mu_in * _G / max(_K0, 1e-16) + _cF0 * _G * _G
            _P_out_sq = predict_outlet_p_sq(float(P_in_abs), float(T_in_f),
                                            _C, L_stream)
            # A non-positive P_out² means the 1D estimate says Δp >= P_in, i.e.
            # the outlet would go to vacuum — no steady solution exists there.
            # The 3D path raises ChokedFlowError; 2D has never had a choke guard
            # (ledger O1), so clip to the same 1e4 Pa floor 3D's `_seed_p_ref`
            # uses and leave the guard as a separate change, rather than silently
            # widening the envelope here.
            P_ref_out = float(np.sqrt(max(_P_out_sq, 1.0e4)))
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
        # ── Re-seed P_ref_abs from the solver's ACTUAL drag (2026-07-13) ────
        # The seed above used the uniform-geometry (K0, cF0); the zone_config /
        # zone_arrays paths then swap in per-row graded K/cF (constructor or
        # override_simple_K_cF). P_ref_abs is the PHYSICAL outlet absolute
        # pressure (ledger C8) — leaving the uniform seed on a graded design
        # anchors the outlet at the wrong pressure by (Δp_graded − Δp_uniform),
        # which feeds ρ = P_abs/(RT) everywhere: the C8 mechanism surviving on
        # the zoned branch. Per-row C averaged arithmetically (rows are drag in
        # SERIES along the stream). Guarded on genuine non-uniformity so the
        # uniform path never recomputes — bit-identical there (same reasoning
        # as the kernels' use_eps guard).
        if fluid_type == 'ideal_gas':
            _K_rows = np.asarray(s._K_arr, dtype=np.float64)
            _cF_rows = np.asarray(s._cF_arr, dtype=np.float64)
            if (float(_K_rows.max()) != float(_K_rows.min())
                    or float(_cF_rows.max()) != float(_cF_rows.min())):
                _C_rows = (_mu_in * _G / np.maximum(_K_rows, 1e-16)
                           + _cF_rows * _G * _G)
                _P_out_sq_g = predict_outlet_p_sq(
                    float(P_in_abs), float(T_in_f),
                    float(np.mean(_C_rows)), L_stream)
                s.P_ref_abs = float(np.sqrt(max(_P_out_sq_g, 1.0e4)))
        # ── C8 shooting: reseed from the PREVIOUS iteration's MEASURED drag
        # (openspec c8-p-in-shooting). The 1D seed above (and its graded
        # refinement) only ESTIMATE the drag, so the realized inlet absolute
        # pressure P_ref_abs + Δp_solved misses the specified P_in (ledger
        # C8: case 16 realized 288980 vs spec 304746, −5.2%). The P² update
        #     P_out²_new = P_in² − (realized_prev² − P_ref_prev²)
        # reuses the 1D compressible invariant (P_in²−P_out² = 2RT̄CL, level-
        # free) with the solver-measured drag integral, landing the realized
        # inlet on spec in 1–2 outer iterations. Overrides BOTH seeds above
        # (measured drag supersedes any estimate). Same clip posture as the
        # seeds: 1e4 Pa floor, no raise (2D has no choke guard — ledger O1,
        # deliberately a separate change).
        if (fluid_type == 'ideal_gas' and p_shoot_prev is not None
                and cfg.get('p_in_shooting',
                            run_environment(cfg, 'TPMSHX_P_IN_SHOOT', '0') == '1')):
            _pref_prev, _dp_prev = float(p_shoot_prev[0]), float(p_shoot_prev[1])
            _P_out_sq_shoot = (float(P_in_abs) ** 2
                               - _dp_prev * (_dp_prev + 2.0 * _pref_prev))
            s.P_ref_abs = float(np.sqrt(max(_P_out_sq_shoot, 1.0e4)))
        _has_partial = np.any(s.outlet_frac < 0.99) and np.any(s.outlet_frac > 0.5)
        # R3 (2026-07-07): production solver knobs, precedence
        # env > SolverConfig > dim-specific auto. The autos are the
        # long-standing hardcodes (partial 5e-4 / full 1e-5, cap 10000);
        # a None config keeps them bit-identically. TPMSHX_SIMPLE_TOL
        # used to be honoured by 3D only — the asymmetry is gone.
        _tol = 5e-4 if _has_partial else 1e-5
        _max_it = 10000
        _sol_knobs = getattr(cfg.get('compute_cfg'), 'solver', None)
        if _sol_knobs is not None:
            if _sol_knobs.tol_simple is not None:
                _tol = float(_sol_knobs.tol_simple)
            if _sol_knobs.max_iter_simple is not None:
                _max_it = int(_sol_knobs.max_iter_simple)
        _env_tol = run_environment(cfg, 'TPMSHX_SIMPLE_TOL')
        if _env_tol is not None:
            _tol = float(_env_tol)
        # Propagate Ta/Tb to SIMPLE.T_field if available (compressible coupling
        # fix; without this _update_density uses stale scalar T_in inside SIMPLE)
        if T_field_real is not None:
            T_simple = _to_simple_coords(T_field_real)
            if T_simple.shape == s.T_field.shape:
                s.update_T_field(np.ascontiguousarray(T_simple))
        # Live residual hook — push (iter, residual) onto the shared
        # buffer (captured from the enclosing _build_fields_cfg
        # ``live_residuals`` parameter) so the UI sparkline can render
        # during the solve instead of only after it returns. ``None``
        # disables the hook for headless pipeline runs.
        _buf = live_residuals
        _side = 'A' if 'A' in label else 'B'
        def _progress_cb(it, res, _s=_side):
            if _buf is not None:
                _buf.setdefault(_s, []).append((int(it), float(res)))
            if residual_cb is not None:
                residual_cb(_s, int(it), float(res))
        # 2026-05-07: 2D SIMPLE max_iter 5000 → 10000. Crossflow with
        # partial-B inlet (e.g. user's pipeB w=0.068m of L=0.182) +
        # high-u Forchheimer-branch needs more iters to drive residual
        # below tol. 5000 left B at res~3e-3 with target 1e-3.
        # ── Ledger C9 / F2 convergence gates ────────────────────────────
        # DEFAULT ON in the pipeline, mirroring 3D (ledger C7). The legacy `tol`
        # gates `_mass_res_jit`, a PLANE-INTEGRATED flux defect that the pp solve
        # makes TAUTOLOGICALLY ZERO on a full-face outlet (measured 1.6e-15), so
        # it fires at the min-iter floor (iteration 20) and stops the solve there
        # — under-converging dP_A by 3.3 %. F2 gates on the momentum residual +
        # solved-cell continuity + global boundary mass instead.
        #
        # NOT `tol_simple`: that name already means several different numbers
        # across the codebase and it still drives the legacy path. F2 gets its own
        # names so nothing forks silently (codex review P0-4).
        # precedence: env > SolverConfig > cfg > default (same shape as `_tol`)
        def _f2_knob(name, default):
            v = getattr(_sol_knobs, name, None) if _sol_knobs is not None else None
            if v is None:
                v = cfg.get(name)
            return default if v is None else v

        s.convergence_mode = str(run_environment(
            cfg, 'TPMSHX_CONV_MODE', _f2_knob('convergence_mode', 'f2')))
        s.mom_tol = float(_f2_knob('mom_tol', 1e-4))
        s.mass_local_tol = float(_f2_knob('mass_local_tol', 1e-6))
        s.mass_global_tol = float(_f2_knob('mass_global_tol', 1e-6))

        conv, n_it = s.solve(max_iter=_max_it, tol=_tol, verbose=False,
                               progress_cb=_progress_cb, cancel_check=cancel_check)
        if not conv:
            # Under f2 the legacy `residuals[-1]` is the C9 tautology (~1e-15
            # on a full-face outlet) — quoting it makes a FAILED solve look
            # converged. Report the gates that actually held the exit open.
            if str(getattr(s, 'convergence_mode', 'legacy')) == 'f2':
                simple_warnings[label] = (
                    f"SIMPLE ({label}): not converged after {n_it} iters "
                    f"(exit={getattr(s, 'exit_reason', '?')}, "
                    f"mom={getattr(s, 'final_res_mom', None)}, "
                    f"mass_local={getattr(s, 'final_res_mass_local', None)}, "
                    f"mass_global={getattr(s, 'final_res_mass_global', None)})")
            else:
                simple_warnings[label] = (
                    f"SIMPLE ({label}): not converged after {n_it} iters "
                    f"(res={s.residuals[-1]:.2e})")
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
