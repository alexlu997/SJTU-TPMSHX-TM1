"""Prepare the existing plug-flow design mode without calling an LTNE kernel."""
from dataclasses import asdict

import numpy as np

from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.model_refs import ModelRef
from sjtu_tpmshx.models.catalog import MODEL_VERSIONS
from sjtu_tpmshx.models.fluid_props import check_finite_temperatures
from sjtu_tpmshx.models.quick_design import K_STEEL, GEOM_N, NX, LTNE_TOL, _ARR, _dp_fractions
from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry
from sjtu_tpmshx.df_surrogate.predict import (
    _resolve_method, _overrides_enabled, _residual_correction_enabled,
)


def prepare_quick_design(case, topo, l, t, s, Lx, arrangement='cross', *,
                         case_id, init=None, k_s=K_STEEL, prop_model='const',
                         tol=LTNE_TOL, height=None):
    if init is not None:
        check_finite_temperatures(*init, where='design external warm start')
    if arrangement not in _ARR or prop_model not in ('const', 'mean'):
        raise ValueError('unsupported quick-design arrangement or property model')
    sz = s if height is None else height
    for name, value in dict(l=l, t=t, s=s, Lx=Lx, height=sz, k_s=k_s, tol=tol,
                            mdot_h=case.mdot_h, mdot_c=case.mdot_c,
                            T_in_h=case.T_in_h, T_in_c=case.T_in_c,
                            P_in_h=case.P_in_h, P_in_c=case.P_in_c).items():
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f'quick-design {name} must be finite and positive')
    arr = _ARR[arrangement]
    shape = (NX, arr['ny'], arr['nz'])
    if init is not None and (len(init) != 3 or any(np.shape(a) != shape for a in init)):
        raise ValueError('quick-design warm start must match the prepared grid')
    geo = tpms_geometry(topo, l, t, k_s, N=GEOM_N)
    grid = dict(dimension=3, length_unit='m', axis_order=('x', 'y', 'z'))
    for axis, count, length in zip('xyz', shape, (Lx, s, sz)):
        widths = np.full(count, length / count)
        grid['d' + axis] = widths
        grid[axis + '_edges'] = np.r_[0., np.cumsum(widths)]
    inputs = {name: getattr(case, name) for name in
              ('hot_fluid', 'cold_fluid', 'T_in_h', 'T_in_c', 'P_in_h', 'P_in_c', 'mdot_h', 'mdot_c')}
    df_options = dict(method=_resolve_method(), overrides=_overrides_enabled(),
                      residual_correction=_residual_correction_enabled())
    fractions = _dp_fractions(case, topo, l, t, geo['epsilon_A'], s, Lx,
                              arrangement, sz, df_options=df_options)
    return CaseData(
        case_id=case_id, config_snapshot=asdict(case), grid=grid,
        design_fields=dict(eps=np.full(shape, geo['epsilon']),
                           eps_A=np.full(shape, geo['epsilon_A']),
                           K_ss=np.full(shape, (1. - geo['epsilon']) * k_s)),
        parameters=dict(operating_point=inputs, topology=topo, L_cell_m=l / 1000.,
                        t_wall_m=t / 1000., Lx=Lx, s=s, height=sz,
                        k_s=k_s, A_0=geo['A_0'], D_h=geo['D_h'],
                        arrangement=arrangement, prop_model=prop_model, tol=tol,
                        controls={key: value for key, value in arr.items() if key not in ('ny', 'nz')}, initial_fields=init,
                        df_options=df_options,
                        inlet_pressure_fractions=dict(zip(('A', 'B'), fractions))),
        model_refs=(ModelRef('quick_design', MODEL_VERSIONS['quick_design']),
                    ModelRef('fluid', MODEL_VERSIONS['fluid'], {'fluid': case.hot_fluid}),
                    ModelRef('fluid', MODEL_VERSIONS['fluid'], {'fluid': case.cold_fluid})),
        metadata=dict(mode='quick_design', model='plug_ltne_analytic_dp_v1',
                      quantity_basis='total', geometry_resolution=GEOM_N,
                      thermal_kernel=('2d_delegation' if shape[2] == 1 else '3d'),
                      applicability='Sizing approximation; prescribed velocity, analytical inlet-state dP; not full SIMPLE or experimental validation.'))
