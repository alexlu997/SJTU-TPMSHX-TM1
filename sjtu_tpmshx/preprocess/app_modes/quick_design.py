"""Map owned native Quick preparation to the existing CaseData contract."""
from sjtu_tpmshx.shared.domain.case_data import CaseData
from sjtu_tpmshx.shared.configs.model_parameters import load_quick_design_parameters
from sjtu_tpmshx.shared.models._native_quick_prepare import prepare_values

_DEFAULTS = load_quick_design_parameters()


def prepare_quick_design(case, topo, l, t, s, Lx, arrangement='cross', *,
                         case_id, init=None, k_s=_DEFAULTS['k_s'], prop_model='const',
                         tol=_DEFAULTS['tol'], height=None):
    state, grid, fields, controls, fractions = prepare_values(
        case, topo, l, t, s, Lx, arrangement, init=init, k_s=k_s,
        prop_model=prop_model, tol=tol, height=height)
    return CaseData(
        case_id=case_id, config_snapshot=state.config, grid=grid, design_fields=fields,
        parameters=dict(operating_point=state.operating, topology=topo,
                        L_cell_m=state.units[0], t_wall_m=state.units[1], Lx=Lx,
                        s=s, height=state.height, k_s=k_s,
                        A_0=state.geometry['A_0'], D_h=state.geometry['D_h'],
                        arrangement=arrangement, prop_model=prop_model, tol=tol,
                        controls=controls, initial_fields=init, df_options=state.df_options,
                        _environment=state.environment,
                        inlet_pressure_fractions=dict(zip(('A', 'B'), fractions))),
        model_refs=state.model_refs,
        metadata=dict(mode='quick_design', model='plug_ltne_analytic_dp_v1',
                      quantity_basis='total', geometry_resolution=_DEFAULTS['geometry_resolution'],
                      thermal_kernel=('2d_delegation' if fields['eps'].shape[2] == 1 else '3d'),
                      applicability='Sizing approximation; prescribed velocity, analytical inlet-state dP; not full SIMPLE or experimental validation.'))
