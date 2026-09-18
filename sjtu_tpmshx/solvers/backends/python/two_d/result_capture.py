"""Capture native 2D evidence, separate from engineering metric evaluation."""
from uuid import uuid4
import numpy as np

from sjtu_tpmshx.domain.field_result import FieldResult


def capture_result(case, raw, diagnostics):
    native = raw['_native_evidence']
    fields = {key: native[key] for key in (
        'Ta', 'Tb', 'Ts', 'P_thermal_A', 'P_thermal_B', 'P_report_A', 'P_report_B',
        'h_vA', 'h_vB', 'K_ss')}
    fields.update({key + '_display': raw[key] for key in ('Ta', 'Tb', 'Ts', 'P_fA', 'P_fB')})
    fields.update({key: raw[key] for key in ('ucA', 'vcA', 'ucB', 'vcB')})
    fields.update({key + '_display': raw[key + '_disp']
                   for key in ('ucA', 'vcA', 'ucB', 'vcB')
                   if raw.get(key + '_disp') is not None})
    for key in ('h_vA', 'h_vB', 'K_ss'):
        fields[key] = np.broadcast_to(fields[key], np.shape(fields['Ta']))
    field_metadata = {}
    for key in fields:
        unit = ('K' if key.startswith(('Ta', 'Tb', 'Ts')) else
                'Pa' if key.startswith('P_') else
                'W/(m3 K)' if key.startswith('h_v') else
                'W/(m K)' if key == 'K_ss' else 'm/s')
        state = ('display' if key.endswith('_display') else
                 'last thermal input' if key.startswith(('P_thermal', 'h_v')) or key == 'K_ss' else
                 'final flow/report' if key.startswith(('P_report', 'uc', 'vc')) else
                 'raw last main thermal return')
        field_metadata[key] = dict(unit=unit, axes=('x', 'y'), location='cell', state=state)
    model_metadata = dict(case.metadata['model_metadata'])
    if native['true_h'] and 'sco2_enthalpy_eos' in native['true_h']:
        model_metadata['sco2_enthalpy_eos'] = native['true_h']['sco2_enthalpy_eos']
    return FieldResult(
        result_id=str(uuid4()), case_id=case.case_id,
        backend_id='python', backend_version='two_d_v1', grid=case.grid,
        fields=fields, field_metadata=field_metadata, model_refs=case.model_refs,
        boundary_fluxes=dict(
            mass_A=native['mass_flux_A'], mass_B=native['mass_flux_B'],
            mass_unit='kg/(s m)', mass_axes=('x-face', 'y-face'),
            mass_sign='positive along physical coordinate axis',
            state='last main thermal input', model_h=native['model_h_balance'],
            true_h=native['true_h'], fine=native['fine']),
        pressure_evidence=native['pressure'],
        run_status=dict(execution='completed', converged=bool(raw['solver_converged']),
                        envelope_valid=bool(raw['envelope_valid']),
                        final_flow_after_last_thermal=native['final_after_thermal'],
                        outer_index=native['outer_index']),
        metadata=dict(dimension=2, quantity_basis='per_unit_depth',
                      thermal_mode=native['mode'], split_A=native['split_A'],
                      rho_cp_A=native['rho_cp_A'], rho_cp_B=native['rho_cp_B'],
                      parameters=case.parameters, design_fields=case.design_fields,
                      design_mode=case.metadata['design_mode'], application=raw['application'],
                      model_metadata=model_metadata, notices=case.metadata['notices'],
                      diagnostics=diagnostics, df_metadata=raw['df_metadata'],
                      model_roles=case.metadata['model_roles'],
                      reporting_reference={key: raw[key] for key in (
                          'Q_total', 'dP_A', 'dP_B', 'T_out_A_K', 'T_out_B_K')}))
