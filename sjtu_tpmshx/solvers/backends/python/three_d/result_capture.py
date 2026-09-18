"""Detach native 3D thermal and final-flow evidence from backend instances."""
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.domain.field_result import FieldResult
from .runtime import _pressure_real_3d


def capture_result(case, prob, outer, raw):
    native = outer.native_evidence
    fields = {key: native[key] for key in ('Ta', 'Tb', 'Ts', 'h_vA', 'h_vB', 'K_ss',
                                          'P_thermal_A', 'P_thermal_B') if native[key] is not None}
    display_units = {}
    for name, source, unit in (
        ('Ta_display', 'Ta', 'K'), ('Tb_display', 'Tb', 'K'), ('Ts_display', 'Ts', 'K'),
        ('P_fA_display', 'P_Pa', 'Pa'), ('P_fB_display', 'P_Pa_B', 'Pa'),
        ('ucA', 'uc_real', 'm/s'), ('vcA', 'vc_real', 'm/s'), ('wcA', 'wc_real', 'm/s'),
        ('ucB', 'uc_real_B', 'm/s'), ('vcB', 'vc_real_B', 'm/s'), ('wcB', 'wc_real_B', 'm/s'),
        ('vmag_A', 'vmag', 'm/s'), ('vmag_B', 'vmag_B', 'm/s'), ('chi_B', 'chi_B', '1')):
        if raw[source] is not None:
            fields[name] = raw[source]
            display_units[name] = unit
    pressure, report = {}, {}
    for side, solver, port in zip(('A', 'B'), (prob.sA, prob.sB), (prob.fA, prob.fB)):
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
        # Reductions consume the native thermal faces below. Persist only
        # the port direction, without a second flow/enthalpy reconstruction.
        report[side] = dict(direction=port['dir'])
    metadata = {key: dict(unit='K' if key in ('Ta', 'Tb', 'Ts') else
                          'Pa' if key.startswith('P_') else
                          'W/(m3 K)' if key.startswith('h_v') else 'W/(m K)',
                         axes=('x', 'y', 'z'), location='cell',
                         state='final SIMPLE flow' if key.startswith(('P_report', 'P_gauge')) else 'last thermal solve')
                for key in fields}
    for name, unit in display_units.items():
        metadata[name] = dict(unit=unit, axes=('x', 'y', 'z'), location='cell',
                              state='display' if name.endswith('_display') else 'final flow/report')
    diagnostics = {key: value for key, value in raw.items()
                   if not isinstance(value, np.ndarray)}
    model_metadata = dict(case.metadata['model_metadata'])
    if native['true_h'] and 'sco2_enthalpy_eos' in native['true_h']:
        model_metadata['sco2_enthalpy_eos'] = native['true_h']['sco2_enthalpy_eos']
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
            design_mode=case.metadata['design_mode'],
            model_metadata=model_metadata, notices=case.metadata['notices'],
            application=dict(
                coeffs={key: raw.get('_audit_' + key) for key in ('K_ffA', 'K_ffB', 'K_ss')},
                props={key: raw.get(source) for key, source in (
                    ('rho_cp_A', '_audit_rho_cp_fA'), ('rho_cp_B', '_audit_rho_cp_fB'),
                    ('u_A_in_mps', 'u_A'), ('T_in_A_K', 'T_in'))}),
            diagnostics=diagnostics, df_metadata=raw['df_metadata'],
            model_roles=case.metadata['model_roles'],
            reporting_reference={key: raw[key] for key in ('Q', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B')}))
