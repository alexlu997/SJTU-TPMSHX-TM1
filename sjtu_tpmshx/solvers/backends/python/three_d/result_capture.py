"""Detach native 3D thermal and final-flow evidence from backend instances."""
from uuid import uuid4

from sjtu_tpmshx.domain.field_result import FieldResult
from .runtime import _pressure_real_3d


def capture_result(case, prob, outer, metrics, diagnostics):
    native = outer.native_evidence
    emit_audit = prob.cfg.get('_emit_audit', False)
    fields = {key: native[key] for key in ('Ta', 'Tb', 'Ts', 'h_vA', 'h_vB', 'K_ss',
                                          'P_thermal_A', 'P_thermal_B') if native[key] is not None}
    display_units = {}
    for name, value, unit in (
        ('Ta_display', outer.Ta, 'K'), ('Tb_display', outer.Tb, 'K'), ('Ts_display', outer.Ts, 'K'),
        ('P_fA_display', metrics.P_real, 'Pa'), ('P_fB_display', metrics.P_real_B, 'Pa'),
        ('ucA', metrics.uc_real, 'm/s'), ('vcA', metrics.vc_real, 'm/s'), ('wcA', metrics.wc_real, 'm/s'),
        ('ucB', prob.ucB, 'm/s'), ('vcB', prob.vcB, 'm/s'), ('wcB', prob.wcB, 'm/s'),
        ('vmag_A', metrics.vmag, 'm/s'), ('vmag_B', metrics.vmag_B, 'm/s')):
        if value is not None:
            fields[name] = value
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
    audit = {}
    if emit_audit:
        for side in ('A', 'B'):
            name = 'K_ff' + side
            fields[name] = native[name]
            metadata[name] = dict(unit='W/(m K)', axes=('x', 'y', 'z'),
                                  location='cell', state='last thermal input')
        for side in ('A', 'B'):
            name = 'h_v' + side + '_report'
            fields[name] = getattr(outer, 'h_v' + side + '_field')
            metadata[name] = dict(unit='W/(m3 K)', axes=('x', 'y', 'z'),
                                  location='cell', state='final report coupling')
        masks = {}
        for side in case.parameters['prepared']['axes']:
            axis = case.parameters['prepared']['axes'][side]
            masks[side] = dict(
                thermal=getattr(outer, '_ltne_mask_' + side),
                inlet=prob.in_mask_2d if side == 'A' else prob.in_mask_B,
                outlet=prob.out_mask_2d if side == 'A' else prob.out_mask_B,
                axes=tuple('xyz'[axis[key]] for key in ('cross1_real_axis', 'cross2_real_axis')),
                unit='1', state='final report opening masks')
        audit = dict(masks=masks, axes=('x', 'y', 'z'), state='final report/property refresh',
                     units=dict(K_ffA='W/(m K)', K_ffB='W/(m K)', K_ss='W/(m K)',
                                rho_cp_A='J/(m3 K)', rho_cp_B='J/(m3 K)'))
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
        run_status=dict(execution='completed', converged=bool(diagnostics['solver_converged']),
                        outer_index=native['outer_index']),
        metadata=dict(dimension=3, quantity_basis='total', thermal_mode=native['mode'],
            active_fluids=tuple(pressure),
            parameters=case.parameters, design_fields=case.design_fields,
            design_mode=case.metadata['design_mode'],
            model_metadata=model_metadata, notices=case.metadata['notices'],
            audit=audit,
            application=dict(
                coeffs={key: value if emit_audit else None for key, value in (
                    ('K_ffA', prob.K_ffA), ('K_ffB', outer.K_ffB), ('K_ss', prob.K_ss))},
                props=dict(rho_cp_A=outer.rho_cp_fA if emit_audit else None,
                           rho_cp_B=outer.rho_cp_fB if emit_audit else None,
                           u_A_in_mps=prob.u_A, T_in_A_K=prob.T_inA)),
            diagnostics=diagnostics, df_metadata=diagnostics['df_metadata'],
            model_roles=case.metadata['model_roles'],
            reporting_reference=dict(Q=metrics.Q, dP_A=metrics.dP, dP_B=metrics.dP_B,
                                     T_out_A=metrics.T_A_out, T_out_B=metrics.T_B_out)))
