"""Execute prepared plug-flow design passes; no preprocessing or grid creation."""
from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.persistence_validation import validate_grid
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.domain.run_warnings import range_context
from sjtu_tpmshx.models.catalog import resolve_model
from sjtu_tpmshx.models.fluid_props import check_finite_temperatures
from sjtu_tpmshx.result_math import _cold_outlet
from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d


def run_case(case, control=RunControl()):
    control.check_cancelled()
    shape = validate_grid(case.grid)
    if len(shape) != 3 or case.metadata['model'] != 'plug_ltne_analytic_dp_v1':
        raise ValueError('unsupported quick-design physical model')
    p = mutable_data(case.parameters)
    fractions = p.get('inlet_pressure_fractions')
    if (not isinstance(fractions, dict) or set(fractions) != {'A', 'B'}
            or any(not np.isscalar(value) or not np.isfinite(value) or value < 0
                   for value in fractions.values())):
        raise ValueError('quick-design requires prepared nonnegative inlet pressure fractions')
    op = SimpleNamespace(**p['operating_point'])
    if len(case.model_refs) != 3 or case.model_refs[0].name != 'quick_design':
        raise ValueError('quick-design model resources are incomplete')
    model = resolve_model(case.model_refs[0])
    for ref, fluid in zip(case.model_refs[1:], (op.hot_fluid, op.cold_fluid)):
        if ref.name != 'fluid' or dict(ref.parameters) != {'fluid': fluid}:
            raise ValueError('quick-design fluid resource disagrees with operating point')
        resolve_model(ref)
    if p['arrangement'] not in ('cross', 'counter') or p['prop_model'] not in ('const', 'mean'):
        raise ValueError('unsupported quick-design arrangement or property model')
    if p['controls']['dirB'] != (2 if p['arrangement'] == 'cross' else 1):
        raise ValueError('quick-design flow direction disagrees with arrangement')
    widths = tuple(np.asarray(case.grid['d' + axis]) for axis in 'xyz')
    for axis, width, length in zip('xyz', widths, (p['Lx'], p['s'], p['height'])):
        if not np.isclose(width.sum(), length, rtol=1e-12, atol=0.):
            raise ValueError(f'prepared {axis} grid disagrees with physical extent')
    fixed = mutable_data(case.design_fields)
    if set(fixed) != {'eps', 'eps_A', 'K_ss'}:
        raise ValueError('unsupported quick-design fields')
    for name, value in fixed.items():
        if np.shape(value) != shape or not np.all(np.isfinite(value)) or not np.all(value == value.flat[0]):
            raise ValueError(f'quick-design requires a finite uniform {name} field on its prepared grid')
    eps = float(fixed['eps'].flat[0]); eps_a = float(fixed['eps_A'].flat[0])
    if not 0 < eps < 1 or not np.isclose(eps_a, eps / 2, rtol=1e-12, atol=0.) or np.any(fixed['K_ss'] <= 0):
        raise ValueError('quick-design requires positive symmetric porosity and solid conduction')
    for name in ('tol', 'A_0', 'D_h'):
        if not np.isfinite(p[name]) or p[name] <= 0:
            raise ValueError(f'quick-design {name} must be finite and positive')
    arr = p['controls']
    if (not isinstance(arr['maxit'], int) or arr['maxit'] <= 0
            or not 0 < arr['alpha'] <= 1
            or (arr['qtol'] is not None and (not np.isfinite(arr['qtol']) or arr['qtol'] <= 0))
            or (arr['chunk'] is not None and (not isinstance(arr['chunk'], int) or arr['chunk'] <= 0))):
        raise ValueError('invalid quick-design numerical controls')
    seed = p['initial_fields']
    if seed is not None:
        check_finite_temperatures(*seed, where='design external warm start')
        if len(seed) != 3 or any(np.shape(v) != shape for v in seed):
            raise ValueError('quick-design warm start disagrees with prepared grid')
    n_passes = 2 if p['prop_model'] == 'mean' else 1
    evaluation = (op.T_in_h, op.T_in_c)
    pass_info = []
    zero = np.zeros(shape)
    for index in range(n_passes):
        control.check_cancelled()
        stage = 'design-inlet-pass' if index == 0 else 'design-mean-pass'
        with range_context(side='A', stage=stage, layout='scalar'):
            hv_a, re_a, u_a, props_a = model._hvol(
                op.hot_fluid, p['topology'], p['L_cell_m'] * 1e3, p['t_wall_m'] * 1e3,
                p['A_0'], p['D_h'], eps_a, op.mdot_h, p['s'], p['height'], evaluation[0], op.P_in_h)
        with range_context(side='B', stage=stage, layout='scalar'):
            hv_b, re_b, u_b, props_b = model._hvol(
                op.cold_fluid, p['topology'], p['L_cell_m'] * 1e3, p['t_wall_m'] * 1e3,
                p['A_0'], p['D_h'], eps_a, op.mdot_c,
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
        pass_info.append(info)
        seed = (ta, tb, ts)
        evaluation = (0.5 * (op.T_in_h + float(np.asarray(ta)[-1, :, :].mean())),
                      0.5 * (op.T_in_c + _cold_outlet(tb, p['arrangement'])))
    control.check_cancelled()
    dph, dpc = fractions['A'], fractions['B']
    fields = dict(Ta=ta, Tb=tb, Ts=ts, ucA=uc_a, vcA=zero, wcA=zero,
                  ucB=uc_b, vcB=vc_b, wcB=zero, K_ffA=k_a, K_ffB=k_b,
                  K_ss=fixed['K_ss'], h_vA=hv_a, h_vB=hv_b, eps=fixed['eps'])
    units = {**{k: 'K' for k in ('Ta', 'Tb', 'Ts')},
             **{k: 'm/s' for k in ('ucA', 'vcA', 'wcA', 'ucB', 'vcB', 'wcB')},
             **{k: 'W/(m K)' for k in ('K_ffA', 'K_ffB', 'K_ss')},
             'h_vA': 'W/(m3 K)', 'h_vB': 'W/(m3 K)', 'eps': '1'}
    pressure = {side: dict(inlet_absolute_Pa=pin, outlet_absolute_Pa=pin * (1. - fraction),
                           model='inlet_state_analytic_df', choked=bool(fraction >= 1.))
                for side, pin, fraction in (('A', op.P_in_h, dph), ('B', op.P_in_c, dpc))}
    converged = bool(pass_info[-1]['converged'])
    control.report_progress(100)
    control.check_cancelled()
    return FieldResult(
        result_id=str(uuid4()), case_id=case.case_id, backend_id='python',
        backend_version='quick_design_v1', grid=case.grid, fields=fields,
        field_metadata={key: dict(unit=units[key], axes=('x', 'y', 'z'), location='cell',
                                  state='last quick-design thermal pass') for key in fields},
        pressure_evidence=pressure,
        boundary_fluxes={side: dict(mass_flow_kg_s=mdot, inlet_temperature_K=tin,
                                    cp_J_kgK=props.cp, velocity_m_s=speed, density_kg_m3=props.rho)
                         for side, mdot, tin, props, speed in
                         (('A', op.mdot_h, op.T_in_h, props_a, u_a), ('B', op.mdot_c, op.T_in_c, props_b, u_b))},
        model_refs=case.model_refs,
        run_status=dict(execution='completed', converged=converged, screening=True,
                        physical_validation='not_established', passes=pass_info),
        metadata=dict(mode='quick_design', dimension=3, quantity_basis='total',
                      model=case.metadata['model'], parameters=case.parameters,
                      properties={'A': asdict(props_a), 'B': asdict(props_b)},
                      diagnostics={'warnings_list': ([] if converged else ['Quick-design thermal solve did not converge.'])},
                      applicability=case.metadata['applicability']))
