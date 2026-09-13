"""Execute the inherited 2D screening loop on prepared arrays only."""
import numpy as np

from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.persistence_validation import validate_case
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.models.catalog import resolve_model
from sjtu_tpmshx.models.screening import SCREENING_FIELDS
from sjtu_tpmshx.models.tpms_calc import air_density, air_cp
from sjtu_tpmshx.models.fluid_props import check_finite_temperatures
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.solvers.ltne_energy import solve_full_domain
from .result_capture import capture
from ..two_d.coupling import _face_mass_fluxes_2d, _simple_staggered_to_real_2d


def build_flow(prepared):
    p = mutable_data(prepared)
    initial = p['initial']
    initial['L_cell_mm'] = initial.pop('L_cell_m') * 1000.
    initial['t_mm'] = initial.pop('t_wall_m') * 1000.
    s = SIMPLESolver(**initial)
    eps = np.asarray(p['eps_field'], dtype=np.float64)
    if eps.shape != (s.Nx, s.Ny) or not np.all(np.isfinite(eps) & (eps > 0) & (eps < 1)):
        raise ValueError('invalid prepared screening porosity')
    s.eps_field = np.ascontiguousarray(eps)
    s._mu_eff_field = np.ascontiguousarray(s.mu_field / s.eps_field)
    if (p['K_field'] is None) != (p['cF_field'] is None):
        raise ValueError('prepared per-cell drag requires both K and cF')
    if p['K_field'] is not None:
        for key, positive in (('K_field', True), ('cF_field', False)):
            value = np.asarray(p[key])
            if not np.all(np.isfinite(value)) or np.any(value <= 0 if positive else value < 0):
                raise ValueError('invalid prepared screening per-cell drag')
        s.set_K_cF_field(p['K_field'], p['cF_field'])
    s.cf_aniso = float(p['cf_aniso'])
    s.convergence_mode = str(p['convergence_mode'])
    return s


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
    if case.grid['dimension'] != 2 or case.metadata['model'] != 'air_air_volume_ltne_v1':
        raise ValueError('unsupported screening physical model')
    if len(case.model_refs) != 2 or case.model_refs[0].name != 'screening' or case.model_refs[1].name != 'fluid' or dict(case.model_refs[1].parameters) != {'fluid': 'air'}:
        raise ValueError('screening requires the recorded air model resources')
    for ref in case.model_refs:
        resolve_model(ref)
    cfg_full = mutable_data(case.parameters['compute'])
    if (cfg_full['dir_A'], cfg_full['dir_B']) != (0, 3):
        raise ValueError('unsupported screening flow orientation')
    if case.parameters['rejection']:
        return capture(case, dict(execution='rejected', converged=False, screening=True,
                                  rejection_stage='pre_solve', reason=case.parameters['rejection'],
                                  physical_validation='unestablished'))
    arrays = mutable_data(case.design_fields)
    dx_arr, dy_arr = np.asarray(case.grid['dx']), np.asarray(case.grid['dy'])
    Nx, Ny = len(dx_arr), len(dy_arr)
    L_dom, H_dom = float(cfg_full['L_domain']), float(cfg_full['H_domain'])
    flow = case.parameters['flow']
    for side, shape, lengths in (('A', (Ny, Nx), (H_dom, L_dom)), ('B', (Nx, Ny), (L_dom, H_dom))):
        p = flow[side]['initial']
        if (p['Nx'], p['Ny']) != shape or (p['W'], p['H']) != lengths:
            raise ValueError('prepared screening flow grid disagrees with its physical grid')
        widths = (dy_arr, dx_arr) if side == 'A' else (dx_arr, dy_arr[::-1])
        if not all(np.array_equal(p[key], width) for key, width in
                   zip(('dx_arr', 'dy_arr'), widths)):
            raise ValueError('prepared screening flow cell widths disagree with its physical grid')
        eps = arrays['eps_arr'].T if side == 'A' else arrays['eps_arr'][:, ::-1]
        if not np.array_equal(flow[side]['eps_field'], eps):
            raise ValueError('prepared flow porosity disagrees with physical design')
    sA, sB = (build_flow(flow[side]) for side in ('A', 'B'))
    verbose = bool(cfg_full.get('verbose', False))

    def solve_flow(s, side):
        control.check_cancelled()
        callback = None if control.residual is None else lambda i, r: control.residual(side, i, r)
        answer = s.solve(max_iter=cfg_full['max_iter_simple'], tol=cfg_full['tol_simple'],
                         verbose=verbose, cancel_check=control.cancel_check, progress_cb=callback)
        control.check_cancelled()
        return answer

    sA_converged, sA_iters = solve_flow(sA, 'A')
    sB_converged, sB_iters = solve_flow(sB, 'B')
    if cfg_full.get('reject_unconverged', False) and not (sA_converged and sB_converged):
        return capture(case, dict(execution='rejected', converged=False, screening=True,
                                  rejection_stage='initial_flow', reason='initial SIMPLE did not converge',
                                  simple_A_converged=bool(sA_converged), simple_B_converged=bool(sB_converged),
                                  physical_validation='unestablished'), (sA, sB))
    n_rho_loops = max(1, int(cfg_full.get('n_rho_loops', 1)))
    drho_tol = float(cfg_full.get('drho_tol', .01))
    rho_relax = float(cfg_full.get('rho_relax', .7))
    P_inA, P_inB = float(cfg_full['P_inA']), float(cfg_full['P_inB'])
    T_inA, T_inB = float(cfg_full['T_inA']), float(cfg_full['T_inB'])
    rho_A_field = np.full((Nx, Ny), air_density(T_inA, P_inA), dtype=np.float64)
    rho_B_field = np.full((Nx, Ny), air_density(T_inB, P_inB), dtype=np.float64)
    rcp_A, rcp_B = rho_A_field * air_cp(T_inA), rho_B_field * air_cp(T_inB)
    Ta = Tb = Ts = None
    outer_converged = False
    for outer_it in range(n_rho_loops):
        control.check_cancelled()
        if control.outer_iteration is not None:
            control.outer_iteration(outer_it + 1, n_rho_loops)
        uxA, uyA = _simple_staggered_to_real_2d(sA, cfg_full['dir_A'])
        uxB, uyB = _simple_staggered_to_real_2d(sB, cfg_full['dir_B'])
        ucA, vcA = .5 * (uxA[:-1] + uxA[1:]), .5 * (uyA[:, :-1] + uyA[:, 1:])
        ucB, vcB = .5 * (uxB[:-1] + uxB[1:]), .5 * (uyB[:, :-1] + uyB[:, 1:])
        mass_A = _face_mass_fluxes_2d(sA, cfg_full['dir_A'], .5 * arrays['eps_arr'], dx_arr, dy_arr)
        mass_B = _face_mass_fluxes_2d(sB, cfg_full['dir_B'], .5 * arrays['eps_arr'], dx_arr, dy_arr)
        inlet_A = .5 * arrays['eps_arr'][0, :] * sA.rho_field[:, 0] * sA.v[:, 0] * dy_arr * air_cp(T_inA)
        inlet_B = .5 * arrays['eps_arr'][:, -1] * sB.rho_field[:, 0] * sB.v[:, 0] * dx_arr * air_cp(T_inB)
        Ta, Tb, Ts, info = solve_full_domain(
            L_dom, H_dom, Nx, Ny, T_inA, T_inB,
            arrays['K_ffA_arr'], arrays['K_ffB_arr'], arrays['K_ss_arr'],
            arrays['h_vA_arr'], arrays['h_vB_arr'], rcp_A, rcp_B, arrays['eps_arr'],
            ucA, vcA, ucB, vcB, cfg_full['dir_A'], cfg_full['dir_B'],
            tol=cfg_full['tol_energy'], max_iter=cfg_full['max_iter_energy'],
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts, dx_arr=dx_arr, dy_arr=dy_arr,
            inlet_mask_A=flow['A']['inlet_mask'], inlet_mask_B=flow['B']['inlet_mask'],
            inlet_flux_A=inlet_A, inlet_flux_B=inlet_B,
            model_fluids=('air', 'air'), mass_flux_A=mass_A, mass_flux_B=mass_B,
            return_info=True, cancel_check=control.cancel_check,
            progress_cb=lambda done, budget: control.report_progress(int(100 * (outer_it + done / budget) / n_rho_loops)))
        control.check_cancelled()
        check_finite_temperatures(Ta, Tb, Ts, where='optimizer temperature return')
        if n_rho_loops == 1:
            break
        rho_A_new, rho_B_new = air_density(Ta, P_inA), air_density(Tb, P_inB)
        drho_max = max(float(np.max(np.abs(rho_A_new - rho_A_field)) / max(rho_A_field.mean(), 1e-12)),
                       float(np.max(np.abs(rho_B_new - rho_B_field)) / max(rho_B_field.mean(), 1e-12)))
        if drho_max < drho_tol:
            outer_converged = True
            break
        if outer_it == n_rho_loops - 1:
            break
        rho_A_field = rho_relax * rho_A_new + (1. - rho_relax) * rho_A_field
        rho_B_field = rho_relax * rho_B_new + (1. - rho_relax) * rho_B_field
        sA.rho_field = np.ascontiguousarray(rho_A_field.T, dtype=np.float64)
        sB.rho_field = np.ascontiguousarray(rho_B_field[:, ::-1], dtype=np.float64)
        sA.update_T_field(np.ascontiguousarray(Ta.T, dtype=np.float64))
        sB.update_T_field(np.ascontiguousarray(Tb[:, ::-1], dtype=np.float64))
        sA_converged, sA_iters = solve_flow(sA, 'A')
        sB_converged, sB_iters = solve_flow(sB, 'B')
        rcp_A = rho_relax * np.ascontiguousarray(sA.rho_field.T) * air_cp(Ta) + (1. - rho_relax) * rcp_A
        rcp_B = rho_relax * np.ascontiguousarray(sB.rho_field[:, ::-1]) * air_cp(Tb) + (1. - rho_relax) * rcp_B
    thermal_ok = bool(info['converged'])
    status = dict(execution='completed', screening=True,
                  converged=bool(sA_converged and sB_converged and thermal_ok and (n_rho_loops == 1 or outer_converged)),
                  simple_A_converged=bool(sA_converged), simple_B_converged=bool(sB_converged),
                  simple_A_iterations=int(sA_iters), simple_B_iterations=int(sB_iters),
                  thermal_converged=thermal_ok, thermal_info=info, outer_converged=outer_converged,
                  outer_convergence_required=n_rho_loops > 1, outer_iterations=outer_it + 1,
                  physical_validation='unestablished')
    result = capture(case, status, (sA, sB), (Ta, Tb, Ts),
                     dict(rho_cp_A=rcp_A, rho_cp_B=rcp_B, ucA=ucA, vcA=vcA, ucB=ucB, vcB=vcB,
                          inlet_flux_A=inlet_A, inlet_flux_B=inlet_B,
                          model_fluids=('air', 'air'), mass_flux_A=mass_A, mass_flux_B=mass_B))
    control.report_progress(100)
    return result
