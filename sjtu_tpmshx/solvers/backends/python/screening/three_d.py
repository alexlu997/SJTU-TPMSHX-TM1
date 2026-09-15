"""Execute prepared 3D screening with the original frozen-B outer loop."""
import time
import numpy as np
from sjtu_tpmshx.domain.run_environment import require_f2_mode

from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.persistence_validation import validate_case
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.models.catalog import resolve_model
from sjtu_tpmshx.models.screening import SCREENING_FIELDS
from sjtu_tpmshx.models.tpms_calc import air_cp, air_viscosity
from sjtu_tpmshx.models.fluid_props import check_finite_temperatures
from sjtu_tpmshx.models.envelope import R_AIR_DEFAULT, assess_solution_validity, mach_field_max, predict_outlet_p_sq
from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D
from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d
from sjtu_tpmshx.solvers.ltne_enthalpy_3d import face_mass_fluxes
from sjtu_tpmshx.logutil import get_logger
from .result_capture import capture

R_AIR = R_AIR_DEFAULT
_log = get_logger(__name__)


def _post_solve_gate_3d(sA, sB, Ta, Tb):
    """Post-solve physical-validity check (P1.3-B, openspec D3).

    Same criteria as the production gate (run_stack_3d.py:2151-2164): minimum
    absolute pressure vs the clip floor + per-cell Mach against the LOCAL
    temperature, both ideal-gas sides. Assess-only — never raises; callers map
    ``(False, reasons)`` onto their existing invalid/penalty channels.

    Velocity magnitude is frame-invariant, so each side is evaluated in its
    OWN solver frame; the real-frame T fields are mapped in with the same
    self-inverse transforms the rho/LTNE plumbing uses (A: transpose(1,0,2),
    B: mirror along axis 1).
    """
    reasons = []
    for tag, s, T_solver in (('A', sA, Ta.transpose(1, 0, 2)),
                             ('B', sB, Tb[:, ::-1, :])):
        u_cc = 0.5 * (s.u[:-1, :, :] + s.u[1:, :, :])
        v_cc = 0.5 * (s.v[:, :-1, :] + s.v[:, 1:, :])
        w_cc = 0.5 * (s.w[:, :, :-1] + s.w[:, :, 1:])
        vmag = np.sqrt(u_cc ** 2 + v_cc ** 2 + w_cc ** 2)
        ok, why = assess_solution_validity(
            float((s.P_ref_abs + s.P).min()), float(vmag.max()),
            float(T_solver.mean()),
            ma_max=mach_field_max(vmag, T_solver))
        if not ok:
            reasons += [f"[{tag}] {r}" for r in why]
    return (not reasons), reasons


def run_case(case, control=RunControl()):
    control.check_cancelled()
    validate_case(case)
    if set(case.design_fields) != set(SCREENING_FIELDS):
        raise ValueError('unsupported screening design field')
    for key in SCREENING_FIELDS:
        values = np.asarray(case.design_fields[key])
        if not np.all(np.isfinite(values)) or np.any(values < 0):
            raise ValueError(f'invalid prepared screening coefficient: {key}')
        if key == 'eps_arr' and np.any((values <= 0) | (values >= 1)):
            raise ValueError('invalid prepared screening porosity')
    if case.metadata.get('energy_formulation') != 'conservative_air_model_h':
        raise ValueError('unsupported prepared screening energy formulation')
    if case.grid['dimension'] != 3 or case.metadata['model'] != 'air_air_frozen_b_volume_ltne_v1':
        raise ValueError('unsupported screening physical model')
    if len(case.model_refs) != 2 or case.model_refs[0].name != 'screening' or case.model_refs[1].name != 'fluid' or dict(case.model_refs[1].parameters) != {'fluid': 'air'}:
        raise ValueError('screening requires the recorded air model resources')
    for ref in case.model_refs:
        resolve_model(ref)
    if case.parameters['rejection']:
        return capture(case, dict(execution='rejected', converged=False, screening=True,
                                  rejection_stage='pre_solve', reason=case.parameters['rejection'],
                                  physical_validation='unestablished'))
    cfg = mutable_data(case.parameters['compute'])
    arrays = mutable_data(case.design_fields)
    dx_arr, dy_arr, dz_arr = (np.asarray(case.grid['d' + axis]) for axis in 'xyz')
    Nx, Ny, Nz = len(dx_arr), len(dy_arr), len(dz_arr)
    L_dom, H_dom, Lz = cfg['L_domain'], cfg['H_domain'], cfg['Lz']
    T_inA, T_inB, P_inA = cfg['T_inA'], cfg['T_inB'], cfg['P_inA']
    rho_A0, rho_B0 = cfg['rho_A0'], cfg['rho_B0']
    G_A, K_mean_A, cF_mean_A = cfg['G_A'], cfg['K_mean_A'], cfg['cF_mean_A']
    max_outer, outer_tol_K, alpha_outer = cfg['max_outer'], cfg['outer_tol_K'], cfg['alpha_outer']
    max_iter_simple, tol_simple = cfg['max_iter_simple'], cfg['tol_simple']
    max_iter_energy, tol_energy = cfg['max_iter_energy'], cfg['tol_energy']
    verbose = cfg['verbose']
    if max_outer < 1:
        raise ValueError('invalid prepared screening iteration controls')
    require_f2_mode(cfg['convergence_mode'])
    if (cfg['dir_A'], cfg['dir_B']) != (0, 3):
        raise ValueError('unsupported screening flow orientation')
    solvers = []
    for side, widths, eps in (('A', (dy_arr, dx_arr, dz_arr), arrays['eps_arr'].transpose(1, 0, 2)),
                              ('B', (dx_arr, dy_arr, dz_arr), arrays['eps_arr'][:, ::-1, :])):
        flow = mutable_data(case.parameters['flow'][side])
        p = flow['initial']
        if (p['Nx'], p['Ny'], p['Nz']) != eps.shape:
            raise ValueError('prepared screening flow shape disagrees with physical grid')
        for axis, w in zip('xyz', widths):
            if not np.array_equal(p['d' + axis + '_arr'], w) or not np.isclose(p['L' + axis], w.sum(), rtol=1e-12, atol=1e-15):
                raise ValueError('prepared screening flow grid disagrees with physical grid')
        if not np.array_equal(flow['eps_field'], eps) or not np.all(np.isfinite(eps) & (eps > 0) & (eps < 1)):
            raise ValueError('invalid prepared screening porosity')
        for key, positive in (('K_arr', True), ('cF_arr', False)):
            value = np.asarray(p[key])
            if value.shape != (p['Ny'], p['Nz']) or not np.all(np.isfinite(value)) or np.any(value <= 0 if positive else value < 0):
                raise ValueError('invalid prepared screening drag coefficients')
        solver = SIMPLESolver3D(**p)
        solver.eps_field = np.ascontiguousarray(flow['eps_field'])
        solver._mu_eff_field = np.ascontiguousarray(solver.mu_field / solver.eps_field)
        solver.convergence_mode = str(cfg['convergence_mode'])
        solvers.append(solver)
    sA, sB = solvers

    def solve_flow(s, side):
        control.check_cancelled()
        if control.iteration is not None:
            control.iteration('SIMPLE ' + side)
        answer = s.solve(max_iter=max_iter_simple, tol=tol_simple, verbose=False,
                         cancel_check=control.cancel_check)
        control.check_cancelled()
        return answer

    # 4. Initial SIMPLE solves.
    # Convergence TRUTH TABLE (2026-07-13, codex review P0): these verdicts
    # used to be DISCARDED — three solve() calls dropped (converged, iters),
    # the LTNE call never asked for return_info, and hitting max_outer set no
    # failure state, so an unconverged run returned Q/dP indistinguishable
    # from a converged one and `verify_pareto_3d` exited 0 on it. Every
    # verdict is now collected and returned; reporting callers must gate on
    # them (screening callers may ignore them — rankings-only, ledger O2).
    if verbose:
        _log.info("[3D] Solving SIMPLE A (cold) … ")
    t0 = time.perf_counter()
    simple_A_ok, _itA = solve_flow(sA, 'A')
    if verbose:
        _log.info(f"{time.perf_counter()-t0:.0f}s")
        _log.info("[3D] Solving SIMPLE B (cold) … ")
    t0 = time.perf_counter()
    simple_B_ok, _itB = solve_flow(sB, 'B')
    if verbose:
        _log.info(f"{time.perf_counter()-t0:.0f}s")
    # Last LTNE inner pass's verdict (the returned fields ARE that pass's) and
    # the outer dT loop's own verdict. `outer_converged` stays False when the
    # loop exits via the max_outer cap — including max_outer == 1/2 where the
    # dT check never fires: "unverified" counts as NOT converged, by design.
    ltne_inner_ok = False
    outer_ok = False

    # 5. Outer LTNE coupling with variable density on fluid A.
    rcp_A_field = np.full((Nx, Ny, Nz), rho_A0 * air_cp(T_inA), dtype=np.float64)
    rcp_B_field = np.full((Nx, Ny, Nz), rho_B0 * air_cp(T_inB), dtype=np.float64)
    # Robustness (2026-06-25): a non-positive max_outer skips the loop below,
    # leaving Ta/Tb/Ts = None and crashing the post-loop reductions with an
    # opaque `None - None` TypeError. Fail loud on the invalid input instead.
    if max_outer < 1:
        raise ValueError(
            f"max_outer must be >= 1 (got {max_outer}); the LTNE outer loop "
            "would not run and the temperature fields would stay None.")
    Ta = Tb = Ts = None
    Ta_prev = None

    for outer_it in range(max_outer):
        control.check_cancelled()
        if control.outer_iteration is not None:
            control.outer_iteration(outer_it + 1, max_outer)
        # Cell-centred velocities
        vA_cc = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])    # (Ny, Nx, Nz)
        ucA_real = vA_cc.transpose(1, 0, 2).copy()           # (Nx, Ny, Nz)
        vcA_real = np.zeros_like(ucA_real)
        wcA_real = np.zeros_like(ucA_real)
        vB_cc = 0.5 * (sB.v[:, :-1, :] + sB.v[:, 1:, :])    # (Nx, Ny, Nz)
        vcB_real = -vB_cc[:, ::-1, :].copy()
        ucB_real = np.zeros_like(vcB_real)
        wcB_real = np.zeros_like(vcB_real)

        # Full SIMPLE staggered faces → real coords, to drive the conservative
        # kernel (B-plan; matches the production run_stack_3d path so the
        # optimizer/Pareto evaluator uses the SAME strict-conservation solver
        # as the UI). sA maps solver→real via transpose(1,0,2) (A streamwise
        # +x); sB is reverse-y, so its faces mirror along y (axis 1) with the
        # streamwise (v) component negated — the divergence-preserving
        # transform, leaving the faces discretely solenoidal.
        ufA = np.ascontiguousarray(sA.v.transpose(1, 0, 2))   # (Nx+1,Ny,Nz)
        vfA = np.ascontiguousarray(sA.u.transpose(1, 0, 2))   # (Nx,Ny+1,Nz)
        wfA = np.ascontiguousarray(sA.w.transpose(1, 0, 2))   # (Nx,Ny,Nz+1)
        ufB = np.ascontiguousarray(sB.u[:, ::-1, :])          # (Nx+1,Ny,Nz)
        vfB = np.ascontiguousarray(-sB.v[:, ::-1, :])         # (Nx,Ny+1,Nz)
        wfB = np.ascontiguousarray(sB.w[:, ::-1, :])          # (Nx,Ny,Nz+1)
        mass_A = face_mass_fluxes(ufA, vfA, wfA, sA.rho_field.transpose(1, 0, 2),
                                 .5 * arrays['eps_arr'], dx_arr, dy_arr, dz_arr)
        mass_B = face_mass_fluxes(ufB, vfB, wfB, sB.rho_field[:, ::-1, :],
                                 .5 * arrays['eps_arr'], dx_arr, dy_arr, dz_arr)

        if verbose:
            _log.info(f"[3D] outer {outer_it+1}/{max_outer} … ")
        t0 = time.perf_counter()
        # 2026-05-19 ε contract (Option A): pass FULL porosity. Kernel does
        # the single halving (eps_f = 0.5*epsilon → ε_A). Pre-halving here
        # double-halved to ε_full/4. K_ff arrays already use ε_A — untouched.
        Ta, Tb, Ts, _ltne_info = solve_full_domain_3d(
            L_dom, H_dom, Lz, Nx, Ny, Nz, T_inA, T_inB,
            arrays['K_ffA_arr'], arrays['K_ffB_arr'], arrays['K_ss_arr'],
            arrays['h_vA_arr'], arrays['h_vB_arr'],
            rcp_A_field, rcp_B_field, arrays['eps_arr'],
            ucA_real, vcA_real, wcA_real,
            ucB_real, vcB_real, wcB_real,
            cfg.get('dir_A', 0), cfg.get('dir_B', 3),
            dx_arr=dx_arr, dy_arr=dy_arr, dz_arr=dz_arr,
            max_iter=max_iter_energy, tol=tol_energy,  # FIX (2026-06-24 audit): use the advertised inner tol_energy, not outer_tol_K (the outer dT break below still uses outer_tol_K). Both default 0.5 → production unchanged.
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
            alpha_T=0.7,
            ufA=ufA, vfA=vfA, wfA=wfA, ufB=ufB, vfB=vfB, wfB=wfB,
            conservative_ltne=True,
            model_mass_A=mass_A, model_mass_B=mass_B, model_fluids=('air', 'air'),
            return_info=True, cancel_check=control.cancel_check,
            progress_cb=lambda done, budget: control.report_progress(int(100 * (outer_it + done / budget) / max_outer)),
        )
        control.check_cancelled()
        check_finite_temperatures(Ta, Tb, Ts, where='3D evaluator temperature return')
        ltne_inner_ok = bool(_ltne_info.get('converged', False))
        if verbose:
            _log.info(f"{time.perf_counter()-t0:.0f}s")

        if Ta_prev is not None:
            dT_max = float(np.max(np.abs(Ta - Ta_prev)))
            if dT_max < outer_tol_K:
                if verbose:
                    _log.info(f"[3D] outer converged at iter {outer_it+1} "
                              f"(dT_max={dT_max:.2f} < {outer_tol_K} K)")
                outer_ok = True
                break
        Ta_prev = Ta.copy()

        if outer_it == max_outer - 1:
            break

        # Var-density update on fluid A (matches retired evaluate_3d).
        # 2026-05-14 fix: also propagate Ta into SIMPLE.T_field so that
        # `_update_density` inside the next sA.solve() uses real local T
        # instead of stale T_in scalar. Without this, the manual
        # rho_field/mu_field assignment below is silently overwritten on
        # the first inner iter, breaking compressible T-ρ coupling.
        # validate_shanghai_3d_real.py and pipelines/run_stack_3d.py have
        # this propagation already; the BO evaluator was missing it.
        Ta_sA = Ta.transpose(1, 0, 2).copy()  # to SIMPLE A's internal layout
        sA.update_T_field(Ta_sA)
        P_abs_sA = sA.P_ref_abs + sA.P
        rho_A_new = P_abs_sA / (R_AIR * Ta_sA)
        mu_A_new = air_viscosity(Ta_sA)
        sA.rho_field = np.ascontiguousarray(
            alpha_outer * rho_A_new + (1 - alpha_outer) * sA.rho_field,
            dtype=np.float64)
        sA.mu_field = np.ascontiguousarray(
            alpha_outer * mu_A_new + (1 - alpha_outer) * sA.mu_field,
            dtype=np.float64)
        # C10: divide by the PER-CELL eps_field, not the scalar (this line used
        # to re-break the per-cell μ/ε install on every outer iteration;
        # uniform designs are value-identical either way).
        sA._mu_eff_field = np.ascontiguousarray(
            sA.mu_field / sA.eps_field, dtype=np.float64)
        T_avg = float(Ta_sA.mean())
        mu_avg = float(air_viscosity(T_avg))
        C_avg = mu_avg * G_A / max(K_mean_A, 1e-16) + cF_mean_A * G_A * G_A
        P_out_sq_new = predict_outlet_p_sq(P_inA, T_avg, C_avg, L_dom)
        if P_out_sq_new <= 0.0:
            # Hot-state choke (2026-07-13 audit): the COLD seed above passed,
            # but the heated T_avg raised 2RT·C·L past P_in². This used to be
            # `sqrt(max(..., 1e4))` — a silent 100 Pa outlet anchor that let
            # the run continue in a region with NO steady solution and return
            # numbers (the exact failure mode the envelope invariant exists to
            # stop, and `verify_pareto_3d` REPORTS these numbers). Same strict
            # contract as the cold seed: NaN + invalid, never a floored anchor.
            if verbose:
                _log.warning(f"[3D verify] INFEASIBLE at outer {outer_it+1} -- "
                             f"P_out^2={P_out_sq_new:.3e} Pa^2 after var-rho "
                             "reseed (hot-state choke). Returning NaN per "
                             "strict validation contract.")
            reason = ('P_out² ≤ 0 on the var-ρ outer reseed — operating point chokes once heated '
                      f'(outer {outer_it+1}, T_avg={T_avg:.1f} K, P_out²={P_out_sq_new:.3e}).')
            return capture(case, dict(execution='rejected', converged=False, screening=True,
                                      rejection_stage='hot_reseed', reason=reason,
                                      simple_A_converged=bool(simple_A_ok), simple_B_converged=bool(simple_B_ok),
                                      ltne_inner_converged=bool(ltne_inner_ok), outer_iterations=outer_it + 1,
                                      physical_validation='unestablished'), (sA, sB), (Ta, Tb, Ts),
                           dict(rho_cp_A=rcp_A_field, rho_cp_B=rcp_B_field,
                                model_fluids=('air', 'air'), mass_flux_A=mass_A, mass_flux_B=mass_B,
                                ufA=ufA, vfA=vfA, wfA=wfA, ufB=ufB, vfB=vfB, wfB=wfB))
        sA.P_ref_abs = float(np.sqrt(P_out_sq_new))

        if verbose:
            _log.info("[3D] re-solving SIMPLE A with var-ρ … ")
        t0 = time.perf_counter()
        # Last re-solve's verdict overwrites the cold one (the fields returned
        # are the last solve's).
        simple_A_ok, _itA = solve_flow(sA, 'A')
        if verbose:
            _log.info(f"{time.perf_counter()-t0:.0f}s")

        # ── LTNE convective ρcp from SIMPLE's LOCAL ρ (ledger C10 fix) ────
        # This used to be `air_density(Ta/Tb, P_in)` — density at the INLET
        # pressure over the WHOLE domain, the pre-2026-06-09 behaviour the
        # production pipeline already fixed (`run_stack_3d` variable_rho_cp:
        # "rho_cp = ρ_local·cp matches SIMPLE's conserved mass flux").
        # SIMPLE's u accelerates as ρ falls downstream (G = ρ·u conserved);
        # multiplying that u by an inlet-pressure ρ inflates the convective
        # flux by P_in/P_local — a spurious enthalpy source growing with
        # Δp/P_in, i.e. a ranking distortion for high-Δp designs (C8-family).
        #   A: sA was just re-solved with the updated T_field, so rho_field is
        #      ρ(P_local, Ta) — use it directly (production pattern). SIMPLE-A
        #      layout (real-y, real-x, z) → real via transpose(1, 0, 2).
        #   B: sB is solved ONCE (cold, isothermal T_inB) with frozen
        #      velocities — use its ρ AS-IS (local P, T_inB) rather than
        #      re-warming with Tb: ρ·u then remains the flux SIMPLE-B actually
        #      conserved, so the convective operator sees no spurious
        #      divergence. The stale-T bias in B's ρ is part of the frozen-B
        #      approximation, same tier as the frozen velocities themselves.
        #      sB is reverse-y (see face transform above): mirror axis 1.
        rho_A_ltne = sA.rho_field.transpose(1, 0, 2)
        rho_B_ltne = sB.rho_field[:, ::-1, :]
        rcp_A_field = np.ascontiguousarray(
            alpha_outer * rho_A_ltne * air_cp(Ta)
            + (1 - alpha_outer) * rcp_A_field, dtype=np.float64)
        rcp_B_field = np.ascontiguousarray(
            alpha_outer * rho_B_ltne * air_cp(Tb)
            + (1 - alpha_outer) * rcp_B_field, dtype=np.float64)

    env_ok, env_reasons = _post_solve_gate_3d(sA, sB, Ta, Tb)
    status = dict(execution='completed' if env_ok else 'rejected', screening=True,
                  converged=bool(simple_A_ok and simple_B_ok and ltne_inner_ok and outer_ok and env_ok),
                  simple_A_converged=bool(simple_A_ok), simple_B_converged=bool(simple_B_ok),
                  ltne_inner_converged=bool(ltne_inner_ok), outer_converged=bool(outer_ok),
                  simple_A_iterations=int(_itA), simple_B_iterations=int(_itB),
                  outer_iterations=outer_it + 1, thermal_info=_ltne_info,
                  envelope_valid=bool(env_ok), physical_validation='unestablished')
    if not env_ok:
        status.update(rejection_stage='post_solve_envelope', reason='post-solve envelope gate: ' + '; '.join(env_reasons))
    result = capture(case, status, (sA, sB), (Ta, Tb, Ts),
                     dict(rho_cp_A=rcp_A_field, rho_cp_B=rcp_B_field,
                          model_fluids=('air', 'air'), mass_flux_A=mass_A, mass_flux_B=mass_B,
                          ufA=ufA, vfA=vfA, wfA=wfA, ufB=ufB, vfB=vfB, wfB=wfB))
    control.report_progress(100)
    return result
