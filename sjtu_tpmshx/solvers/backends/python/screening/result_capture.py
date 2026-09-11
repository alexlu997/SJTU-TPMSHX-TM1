"""Capture native screening state; no objective values or postprocessing callbacks."""
from uuid import uuid4
from sjtu_tpmshx.domain.field_result import FieldResult


def capture(case, status, solvers=(), thermal=None, transport=None):
    dimension = case.grid['dimension']
    axes = tuple(case.grid['axis_order'])
    flow_state = ('hot property update after last thermal return; not re-solved'
                  if status.get('rejection_stage') == 'hot_reseed' else 'raw last SIMPLE return')
    arrays = case.design_fields
    fields = {k: arrays[k] for k in ('eps_arr', 'h_vA_arr', 'h_vB_arr', 'K_ss_arr', 'K_ffA_arr', 'K_ffB_arr')}
    units = dict(eps_arr='1', h_vA_arr='W/(m^3 K)', h_vB_arr='W/(m^3 K)', K_ss_arr='W/(m K)', K_ffA_arr='W/(m K)', K_ffB_arr='W/(m K)')
    metadata = {k: dict(unit=units[k], axes=axes, location='cell', state='prepared thermal coefficient') for k in fields}
    if thermal is not None:
        for key, value in zip(('Ta', 'Tb', 'Ts'), thermal):
            fields[key] = value
            metadata[key] = dict(unit='K', axes=axes, location='cell', state='raw last thermal return')
    pressure, faces, coefficients = {}, {}, {}
    for side, s in zip(('A', 'B'), solvers):
        pressure[side] = dict(P_gauge_Pa=s.P, reference_absolute_Pa=s.P_ref_abs,
                              inlet_fraction=s.inlet_frac, outlet_fraction=s.outlet_frac,
                              dx_m=s.dx_arr if dimension == 2 else s.dx,
                              dy_m=s.dy_arr if dimension == 2 else s.dy,
                              axes=(('y', 'x') if side == 'A' else ('x', '-y')) + (('z',) if dimension == 3 else ()),
                              state='raw last SIMPLE return')
        faces[side] = dict(u=s.u, v=s.v, density_kg_m3=s.rho_field,
                           inlet_geom_frac=s.inlet_geom_frac if dimension == 2 else s.inlet_frac,
                           outlet_geom_frac=s.outlet_geom_frac if dimension == 2 else s.outlet_frac,
                           velocity_unit='m/s', state=flow_state)
        coefficients[side] = dict(K_m2=s._K_arr if dimension == 2 else s.K_arr,
                                  cF_per_m=s._cF_arr if dimension == 2 else s.cF_arr,
                                  eps=s.eps_field, viscosity_Pa_s=s.mu_field, state=flow_state)
        if dimension == 2:
            coefficients[side].update(K_field_m2=s._K_field2d, cF_field_per_m=s._cF_field2d, cf_aniso=s.cf_aniso)
        if dimension == 3:
            pressure[side]['dz_m'] = s.dz
            faces[side]['w'] = s.w
    return FieldResult(str(uuid4()), case.case_id, 'python', backend_version='three_module_v1',
                       grid=case.grid, fields=fields, field_metadata=metadata,
                       pressure_evidence=pressure, boundary_fluxes=faces, run_status=status,
                       model_refs=case.model_refs,
                       metadata=dict(dimension=dimension, mode=case.metadata['mode'], model=case.metadata['model'],
                                     solid_density_kg_m3=case.parameters['compute']['rho_s'],
                                     parameters=case.parameters['compute'], model_configuration=case.metadata,
                                     flow_coefficients=coefficients, thermal_transport=transport,
                                     applicability=case.metadata['applicability']))


