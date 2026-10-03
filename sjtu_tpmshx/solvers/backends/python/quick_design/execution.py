"""Execute prepared plug-flow design passes; no preprocessing or grid creation."""
import numpy as np

from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.run_warnings import range_context
from sjtu_tpmshx.models.fluid_props import (
    QuickDesignWaterFieldError, WaterStateError,
    check_finite_temperatures, check_water_state,
)
from sjtu_tpmshx.result_math import _cold_outlet
from sjtu_tpmshx.solvers.backends.quick_design import prepared_input, field_result
from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d


def run_case(case, control=RunControl()):
    control.check_cancelled()
    shape, p, op, model, widths, fixed = prepared_input(case)
    eps_a = float(fixed['eps_A'].flat[0])
    seed = p['initial_fields']
    # Validate inlet states independently of a warm field so input errors keep
    # their original meaning when a persisted CaseData reaches this backend.
    check_water_state(op.hot_fluid, op.T_in_h, op.P_in_h, where='design inlet A')
    check_water_state(op.cold_fluid, op.T_in_c, op.P_in_c, where='design inlet B')
    def check_water_fields(ta, tb, where):
        # Prescribed-flow quick design has no local pressure solution. Keep
        # the same side inlet pressure used by its property evaluations.
        try:
            check_water_state(op.hot_fluid, ta, op.P_in_h, where=f'{where} A')
            check_water_state(op.cold_fluid, tb, op.P_in_c, where=f'{where} B')
        except WaterStateError as exc:
            raise QuickDesignWaterFieldError(str(exc)) from exc
    if seed is not None:
        check_finite_temperatures(*seed, where='design external warm start')
        if len(seed) != 3 or any(np.shape(v) != shape for v in seed):
            raise ValueError('quick-design warm start disagrees with prepared grid')
        check_water_fields(*seed[:2], 'design external warm start')
    n_passes = 2 if p['prop_model'] == 'mean' else 1
    evaluation = (op.T_in_h, op.T_in_c)
    pass_info = []
    zero = np.zeros(shape)
    for index in range(n_passes):
        control.check_cancelled()
        stage = 'design-inlet-pass' if index == 0 else 'design-mean-pass'
        with range_context(side='A', stage=stage, layout='scalar'):
            hv_a, re_a, u_a, props_a = model._hvol(
                op.hot_fluid, p['topology'], p['L_cell_m'] * 1e3, p['A_0'], p['D_h'], eps_a, op.mdot_h, p['s'], p['height'], evaluation[0], op.P_in_h)
        with range_context(side='B', stage=stage, layout='scalar'):
            hv_b, re_b, u_b, props_b = model._hvol(
                op.cold_fluid, p['topology'], p['L_cell_m'] * 1e3, p['A_0'], p['D_h'], eps_a, op.mdot_c,
                p['Lx'] if p['arrangement'] == 'cross' else p['s'], p['height'], evaluation[1], op.P_in_c)
        uc_a = np.full(shape, u_a)
        uc_b, vc_b = ((zero, np.full(shape, u_b)) if p['arrangement'] == 'cross'
                      else (np.full(shape, -u_b), zero))
        k_a = np.full(shape, eps_a * props_a.k); k_b = np.full(shape, eps_a * props_b.k)
        hv_a = np.full(shape, hv_a); hv_b = np.full(shape, hv_b)
        arr = p['controls']
        ta, tb, ts, info = solve_full_domain_3d(
            p['Lx'], p['s'], p['height'], *shape, op.T_in_h, op.T_in_c,
            k_a, k_b, fixed['K_ss'], hv_a, hv_b,
            props_a.rho * props_a.cp, props_b.rho * props_b.cp, fixed['eps'],
            uc_a, zero, zero, uc_b, vc_b, zero, dir_A=0, dir_B=arr['dirB'],
            dx_arr=widths[0], dy_arr=widths[1], dz_arr=widths[2],
            Ta_init=None if seed is None else seed[0],
            Tb_init=None if seed is None else seed[1], Ts_init=None if seed is None else seed[2],
            max_iter=arr['maxit'], tol=p['tol'], alpha_T=arr['alpha'],
            q_rel_tol=arr['qtol'], conv_chunk=arr['chunk'], return_info=True,
            cancel_check=control.cancel_check,
            progress_cb=(None if control.progress is None else lambda done, budget:
                         control.report_progress(int((index + done / budget) * 100 / n_passes))))
        check_finite_temperatures(ta, tb, ts, where='design thermal return')
        check_water_fields(ta, tb, f'{stage} thermal return')
        pass_info.append(info)
        seed = (ta, tb, ts)
        evaluation = (0.5 * (op.T_in_h + float(np.asarray(ta)[-1, :, :].mean())),
                      0.5 * (op.T_in_c + _cold_outlet(tb, p['arrangement'])))
    control.check_cancelled()
    fields = dict(Ta=ta, Tb=tb, Ts=ts, ucA=uc_a, vcA=zero, wcA=zero,
                  ucB=uc_b, vcB=vc_b, wcB=zero, K_ffA=k_a, K_ffB=k_b,
                  K_ss=fixed['K_ss'], h_vA=hv_a, h_vB=hv_b, eps=fixed['eps'])
    control.report_progress(100)
    control.check_cancelled()
    return field_result(case, fields, props_a, props_b, u_a, u_b, pass_info, backend_id='python')
