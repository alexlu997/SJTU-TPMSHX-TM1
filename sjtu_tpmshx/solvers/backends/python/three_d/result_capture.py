"""Detach native 3D thermal and final-flow evidence from backend instances."""
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.domain.field_result import FieldResult
from .flux import _face_flux_weights
from sjtu_tpmshx.models.field_coordinates_3d import _real_outlet_slice
from sjtu_tpmshx.models.asym_split import _per_side_eps_override
from .runtime import _pressure_real_3d


def capture_result(case, prob, outer, raw):
    native = prob.cfg['_native_evidence']
    fields = {key: native[key] for key in ('Ta', 'Tb', 'Ts', 'h_vA', 'h_vB', 'K_ss',
                                          'P_thermal_A', 'P_thermal_B') if native[key] is not None}
    pressure, report = {}, {}
    overrides = _per_side_eps_override(prob.cfg, prob.tpms_type, prob.Lcell, prob.t_wall, prob.eps)
    for side, solver, port, override in zip(('A', 'B'), (prob.sA, prob.sB), (prob.fA, prob.fB), overrides):
        if solver is None:
            continue
        axis = case.parameters['prepared']['axes'][side]
        fields['P_gauge_' + side] = _pressure_real_3d(solver, axis, 0.)
        fields['P_report_' + side] = _pressure_real_3d(solver, axis, solver.P_ref_abs)
        pressure[side] = dict(P=solver.P, dx=solver.dx, dy=solver.dy, dz=solver.dz,
                              inlet_frac=solver.inlet_frac, outlet_frac=solver.outlet_frac,
                              P_ref_abs=solver.P_ref_abs, axis_map=axis,
                              unit='Pa', axes=('solver_x', 'solver_y', 'solver_z'),
                              stream_axis=1, state='final SIMPLE flow', method='face_extrapolation_v1')
        chi = (_real_outlet_slice(outer.chi_B, port['dir'])
               if side == 'B' and outer.chi_B is not None else None)
        report[side] = dict(
            inlet_weights=_face_flux_weights(solver, port['dir'], face='real_inlet',
                eps_f_per_side=.5 * prob.eps, eps_side_override=override),
            outlet_weights=_face_flux_weights(solver, port['dir'], face='real_outlet',
                eps_f_per_side=.5 * prob.eps, eps_side_override=override, chi_face=chi),
            cp=prob.cp_A if side == 'A' else prob.cp_B,
            inlet_temperature=prob.T_inA if side == 'A' else prob.T_inB,
            inlet_pressure=prob.P_inA if side == 'A' else prob.P_inB,
            direction=port['dir'], weight_unit='kg/s',
            convention='rho * abs(normal velocity) * full face area * side porosity * optional chi',
            state='final SIMPLE flow/report')
        if 'sco2' in (prob.fluid_type_A, prob.fluid_type_B):
            from sjtu_tpmshx.solvers.ltne_enthalpy_3d import _prop_field, _h_scalar
            fluid = prob.fluid_type_A if side == 'A' else prob.fluid_type_B
            item = report[side]
            item['h_out_J_kg'] = _prop_field('H',
                _real_outlet_slice(fields['Ta' if side == 'A' else 'Tb'], port['dir']),
                _real_outlet_slice(fields['P_report_' + side], port['dir']), fluid)
            item['h_in_J_kg'] = _h_scalar(item['inlet_temperature'], item['inlet_pressure'], fluid)
    metadata = {key: dict(unit='K' if key in ('Ta', 'Tb', 'Ts') else
                          'Pa' if key.startswith('P_') else
                          'W/(m3 K)' if key.startswith('h_v') else 'W/(m K)',
                         axes=('x', 'y', 'z'), location='cell',
                         state='final SIMPLE flow' if key.startswith(('P_report', 'P_gauge')) else 'last thermal solve')
                for key in fields}
    diagnostics = {key: value for key, value in raw.items()
                   if not isinstance(value, np.ndarray) and key not in ('_native_evidence',)}
    return FieldResult(result_id=str(uuid4()), case_id=case.case_id,
        backend_id='python', backend_version='three_d_v1', grid=case.grid,
        fields=fields, field_metadata=metadata, model_refs=case.model_refs,
        boundary_fluxes=dict(mass_A=native['mass_A'], mass_B=native['mass_B'],
            mass_unit='kg/s', mass_axes=('x-face', 'y-face', 'z-face'),
            mass_sign='positive along physical coordinate axis', state='last thermal input',
            model_h=native['model_h'], true_h=native['true_h'], report=report,
            face_velocity_A=native['face_velocity_A'], face_velocity_B=native['face_velocity_B']),
        pressure_evidence=pressure,
        run_status=dict(execution='completed', converged=bool(raw['solver_converged']),
                        outer_index=native['outer_index']),
        metadata=dict(dimension=3, quantity_basis='total', thermal_mode=native['mode'],
            parameters=case.parameters, design_fields=case.design_fields,
            diagnostics=diagnostics, df_metadata=raw['df_metadata'],
            model_roles=case.metadata['model_roles'],
            reporting_reference={key: raw[key] for key in ('Q', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B')}))
