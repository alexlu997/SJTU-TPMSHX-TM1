"""Capture native 2D evidence, separate from engineering metric evaluation."""
from uuid import uuid4
import numpy as np

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.result_display import describe_fields


def capture_result(case, display_fields, native, application, diagnostics, *,
                   backend_id='cpp', backend_version='full_2d_v1'):
    fields = {key: native[key] for key in (
        'Ta', 'Tb', 'Ts', 'P_thermal_A', 'P_thermal_B', 'P_report_A', 'P_report_B',
        'h_vA', 'h_vB', 'K_ss')}
    fields.update(display_fields)
    for key in ('h_vA', 'h_vB', 'K_ss'):
        fields[key] = np.broadcast_to(fields[key], np.shape(fields['Ta']))
    field_metadata = describe_fields(fields, 2)
    ledger = native.get('physical_ledger')
    if ledger is not None and ledger['physical_boundary_complete'] is None:
        from sjtu_tpmshx.solvers.physical_ledger import ports_complete
        parameters = case.parameters
        ledger = dict(ledger, physical_boundary_complete=all(ports_complete(
            native['mass_flux_' + side], parameters['dir_' + side],
            parameters['boundary_openings'][side]['in_geom_frac'],
            parameters['boundary_openings'][side]['out_geom_frac']) for side in ('A', 'B')))
    model_metadata = dict(case.metadata['model_metadata'])
    for key in ('enthalpy_eos', 'sco2_enthalpy_eos'):
        if native['true_h'] and key in native['true_h']:
            model_metadata[key] = native['true_h'][key]
    return FieldResult(
        result_id=str(uuid4()), case_id=case.case_id,
        backend_id=backend_id, backend_version=backend_version, grid=case.grid,
        fields=fields, field_metadata=field_metadata, model_refs=case.model_refs,
        boundary_fluxes=dict(
            energy=ledger,
            mass_A=native['mass_flux_A'], mass_B=native['mass_flux_B'],
            mass_unit='kg/(s m)', mass_axes=('x-face', 'y-face'),
            mass_sign='positive along physical coordinate axis',
            state='last main thermal input', model_h=native['model_h_balance'],
            true_h=native['true_h'], fine=native['fine'],
            **({'temperature': native['temperature']} if 'temperature' in native else {})),
        pressure_evidence=native['pressure'],
        run_status=dict(execution='completed', converged=bool(diagnostics['solver_converged']),
                        envelope_valid=bool(diagnostics['envelope_valid']),
                        final_flow_after_last_thermal=native['final_after_thermal'],
                        outer_index=native['outer_index']),
        metadata=dict(dimension=2, quantity_basis='per_unit_depth',
                      thermal_mode=native['mode'], split_A=native['split_A'],
                      **({'temperature_transport': native['temperature']['definition']}
                         if 'temperature' in native else {}),
                      rho_cp_A=native['rho_cp_A'], rho_cp_B=native['rho_cp_B'],
                      parameters=case.parameters, design_fields=case.design_fields,
                      design_mode=case.metadata['design_mode'], application=application,
                      model_metadata=model_metadata, notices=case.metadata['notices'],
                      diagnostics=diagnostics, df_metadata=diagnostics['df_metadata'],
                      model_roles=case.metadata['model_roles'],
                      **{key: native[key] for key in ('input_resolution', 'property_sampling') if key in native},
                      reporting_reference={key: diagnostics[key] for key in (
                          'Q_total', 'dP_A', 'dP_B', 'T_out_A_K', 'T_out_B_K')}))
