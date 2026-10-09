"""Map detached full native 3D evidence to the portable result contract."""
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.model_refs import freeze_value


def capture_result(case, cfg, p, r, abi):
    fields=dict(zip(('Ta','Tb','Ts'), map(freeze_value, r['temperature'])))
    fields.update(h_vA=r['hv'][0],h_vB=r['hv'][1],K_ss=np.asarray(p['design']['K_ss']))
    for s,label in enumerate('AB'):
        if r['thermal_pressure'][s] is not None:
            fields['P_thermal_'+label]=r['thermal_pressure'][s]
    display_units={}
    for name in ('Ta','Tb','Ts'):
        fields[name+'_display']=fields[name];display_units[name+'_display']='K'
    pressure,report={},{}
    for s,label in enumerate('AB'):
        f=r['flow'][s]
        if f is None:
            continue
        axis=case.parameters['prepared']['axes'][label]
        # Shape/axis restoration only. All values have already been solved.
        gauge=f['pressure'].transpose(axis['solver_to_real_perm'])
        if axis['is_reverse']:
            gauge=np.flip(gauge,axis=axis['stream_real_axis'])
        fields['P_gauge_'+label]=np.ascontiguousarray(gauge)
        fields['P_report_'+label]=freeze_value(f['pressure_real'])
        fields['P_f'+label+'_display']=fields['P_report_'+label];display_units['P_f'+label+'_display']='Pa'
        for name,value in zip(('uc','vc','wc'),f['velocity_real']):
            fields[name+label]=value;display_units[name+label]='m/s'
        fields['vmag_'+label]=f['speed_real'];display_units['vmag_'+label]='m/s'
        pressure[label]=dict(P=f['pressure'],dx=f['widths'][0],dy=f['widths'][1],dz=f['widths'][2],
            inlet_frac=f['inlet_opening'],outlet_frac=f['outlet_opening'],P_ref_abs=f['pressure_reference'],axis_map=axis,
            unit='Pa',axes=('solver_x','solver_y','solver_z'),stream_axis=1,state='final SIMPLE flow',method='face_extrapolation_v1')
        report[label]=dict(direction=cfg['fluid_'+label+'_cfg']['dir'])
    field_metadata={key:dict(unit='K' if key in ('Ta','Tb','Ts') else 'Pa' if key.startswith('P_') else
        'W/(m3 K)' if key.startswith('h_v') else 'W/(m K)',axes=('x','y','z'),location='cell',
        state='final SIMPLE flow' if key.startswith(('P_report','P_gauge')) else 'last thermal solve') for key in fields}
    for name,unit in display_units.items():
        field_metadata[name]=dict(unit=unit,axes=('x','y','z'),location='cell',state='display' if name.endswith('_display') else 'final flow/report')
    from sjtu_tpmshx.df_surrogate.experimental_correction import cfd_metadata
    df_metadata=dict(mode=cfg.get('df_mode','cfd_smooth'))
    for label,f in zip('AB',r['flow']):
        if f is None:
            df_metadata[label]=None
        else:
            base=cfd_metadata(p['design']['K_m2'],p['design']['cF_per_m'])
            applied=cfd_metadata(f['permeability'],f['forchheimer'])
            df_metadata[label]=dict((cfg.get('df_application') or {}).get(label,{}) if df_metadata['mode']=='experimental' else base,
                base_K=base['base_K'],base_cF=base['base_cF'],applied_K=applied['applied_K'],applied_cF=applied['applied_cF'])
    ltne=[]
    for h in r['outer']:
        row={key:h[key] for key in ('outer','iters','converged','residual')}
        for key in ('coupling_startup','energy_finishing_checks','model_h_balance'):
            if key in h:
                row[key]=h[key]
        if 'true_h_info' in h:
            info=h['true_h_info']
            row['true_h_balance']=dict(Q_A=info['Q_A'],Q_B=info['Q_B'],units='W',outer_index=h['outer'],
                converged=h['converged'],iterations=h['iters'],residual=h['residual'],
                pressure_source='completed SIMPLE P_ref_abs + gauge',P_in_A_Pa=cfg['P_inA'],P_in_B_Pa=cfg['P_inB'],
                P_A_offset_Pa=h['pressure_reference'][0],P_B_offset_Pa=h['pressure_reference'][1],
                P_A_range_Pa=h['pressure_range'][0],P_B_range_Pa=h['pressure_range'][1])
            row['true_h_balance'].update({key:info[key] for key in ('exit_reason','enthalpy_clip_counts','effective_settings',
                'coupled_energy_balance','equation_energy_balance','energy_algorithm',
                'energy_algorithm_version','temperature_update_K') if key in info})
        ltne.append(row)
    final_info=ltne[-1]
    strict={}
    for s,label in enumerate('AB'):
        for suffix in ('','_cellmax'):
            value=None
            if r['model_h'] is not None:
                value=r['model_h']['eps_'+label+'_strict'+suffix]
            elif r['mode']=='temperature' and r['staggered'][s] is not None and r['staggered'][s]['residual_available']:
                value=r['staggered'][s]['cell_ratio' if suffix else 'global_ratio']
            strict['eps_'+label+'_strict'+suffix]=value
    diagnostics=dict(dP=r['pressure_drop'][0],dP_A=r['pressure_drop'][0],dP_B=r['pressure_drop'][1],
        Lx=cfg['L'],Ly=cfg['H'],Lz=cfg['Lz'],Q=r['duty'][0],Q_total=r['duty'][0],
        Q_enthalpy_A=r['duty'][0],Q_enthalpy_B=r['duty'][1],Q_solid_B=r['solid_exchange'][1],
        mass_flow_A_kg_s=r['inlet_mass'][0],mass_flow_B_kg_s=r['inlet_mass'][1] if r['flow'][1] else None,
        u_A=cfg['u_A'],T_in=cfg['T_inA'],T_A_out=r['outlet_temperature'][0],T_B_out=r['outlet_temperature'][1] if r['flow'][1] else None,
        T_out_A=r['outlet_temperature'][0],T_out_B=r['outlet_temperature'][1] if r['flow'][1] else None,
        dir_A=cfg['fluid_A_cfg']['dir'],dir_B=cfg['fluid_B_cfg']['dir'] if r['flow'][1] else None,
        Q_sA=r['solid_exchange'][0],Q_sB=r['solid_exchange'][1],Q_net=sum(r['solid_exchange']),
        energy_imbalance_rel=r['energy_imbalance'],mass_imbalance_rel_A=r['mass_imbalance'][0],mass_imbalance_rel_B=r['mass_imbalance'][1],
        Q_AB_imbalance_rel=r['enthalpy_imbalance'],Q_sA_interior=r['interior_exchange'][0],Q_sB_interior=r['interior_exchange'][1],
        Q_interior=r['interior_duty'],AB_interior=r['interior_imbalance'],**strict,_ltne_info=ltne,
        _max_outer=p['max_outer'] if p['max_outer'] is not None else 12,_ltne_max_iter=p['ltne_max_iter'],
        _needs_full_validate=bool(p.get('compact',False) and not all(h['converged'] for h in ltne)),
        sco2_nu_observations=r['nu_observations'],df_metadata=df_metadata,
        solver_converged=r['converged'],envelope_valid=r['envelope_ok'],envelope_reasons=r['envelope_reasons'],
        envelope_warnings=list(r['warnings']),p_clip_hits=sum(f['last']['pressure_clip_hits'] for f in r['flow'] if f is not None))
    pressure_states={label:None if f is None else f['inlet_pressure'] for label,f in zip('AB',r['flow'])}
    for label in 'AB':
        state=pressure_states[label]
        diagnostics['P_in_realized_'+label]=np.nan if state is None else state['realized_Pa']
        diagnostics['P_in_shoot_resid_'+label]=np.nan if state is None else state['relative_error']
    def simple_detail(f):
        if f is None:
            return None
        last=f['last']
        return dict(**{key:last[key] for key in ('exit_reason','final_res','res_norm_ref','final_res_mom',
            'final_res_mass_local','final_res_mass_global','outlet_backflow_frac')},convergence_mode='f2',iterations=len(f['legacy']))
    transient=[name for name in r['simple_failures'] if name.startswith(('A@init','B@init'))]
    final=[name for name in r['simple_failures'] if name not in transient]
    if not r['simple_ok']:
        diagnostics['envelope_warnings'].append('SIMPLE momentum solve did not converge in the FINAL solve: '
            + ', '.join(final or r['simple_failures'])
            + ' — the reported velocity/pressure field is not converged (inspect the F2 residuals and iteration budget).')
    elif transient:
        diagnostics['envelope_warnings'].append('SIMPLE momentum solve stalled in a TRANSIENT (superseded) solve: '
            + ', '.join(transient) + ' — the cold-start field was re-solved by the outer loop and the '
            'reported field DID converge, so this is informational. It does flag a hard cold start (typically high u).')
    if not r['finite_fields']:
        diagnostics['envelope_warnings'].append('Non-finite (NaN/inf) cells in the converged temperature or '
            'velocity field — the result is not physical; solver_converged is forced False.')
    diagnostics['envelope_warnings']=list(dict.fromkeys(diagnostics['envelope_warnings']))
    diagnostics['convergence_detail']=dict(inlet_pressure=pressure_states,
        simple_A=simple_detail(r['flow'][0]),simple_B=simple_detail(r['flow'][1]),simple_nonconv=r['simple_failures'],
        outer_dT=[h['temperature_change'] for h in r['outer']],outer_converged=r['outer_ok'],outer_iters=len(r['outer']),
        outer_hit_cap=not r['outer_ok'],simple_ok=r['simple_ok'],simple_nonconv_final=final,simple_nonconv_transient=transient,
        simple_exit_A=r['flow'][0]['last']['exit_reason'],simple_exit_B=None if r['flow'][1] is None else r['flow'][1]['last']['exit_reason'],
        ltne_ok=r['thermal_ok'],fields_finite=r['finite_fields'],envelope_ok=r['envelope_ok'],
        outer_anderson=None if not cfg.get('outer_anderson',False) else {label:None if f is None else f['anderson'] for label,f in zip('AB',r['flow'])})
    for mode in ('true_h','model_h'):
        key=mode+'_balance'
        diagnostics[key]=dict(final_info[key],outer_converged=r['outer_ok'],post_after_last_thermal=r['post_after_last_thermal'],
            state='last true-h solve, before any final post update' if mode=='true_h' else 'last model-h thermal solve, before any final post update') if key in final_info else None
    diagnostics['native_full_3d']=dict(abi=abi,entry_version=r['entry_version'],numerical_driver='cpp',
        coarse_bootstrap={label:None if f is None else f['bootstrap'] for label,f in zip('AB',r['flow'])},
        pressure={label:None if f is None else f['last']['pressure'] for label,f in zip('AB',r['flow'])})
    diagnostics['coarse_bootstrap_trace'] = r['bootstrap_trace']
    model_metadata=dict(case.metadata['model_metadata'])
    mass=freeze_value(r['mass'])
    true_h=None if r['true_h'] is None else dict(r['true_h']['_native_state'],
        mass_flux_A=mass[0], mass_flux_B=mass[1])
    if true_h and 'sco2_enthalpy_eos' in true_h:
        model_metadata['sco2_enthalpy_eos']=true_h['sco2_enthalpy_eos']
    emit_audit=bool(cfg.get('_emit_audit',False))
    if emit_audit:
        from sjtu_tpmshx.solvers.simple_solver_3d import _build_outlet_frac_taper
        for s,label in enumerate('AB'):
            f=r['flow'][s];bc=cfg['fluid_'+label+'_cfg'];axes=p['axes'][label]
            outlet_coeff=None if f is None else f['outlet_opening']
            if f is not None and cfg['fluid_type_'+label] not in ('sco2', 'co2'):
                # Legacy audit-only display weight; raw opening owns every solved face.
                outlet_coeff=outlet_coeff*_build_outlet_frac_taper(*outlet_coeff.shape)
            diagnostics['_audit_s'+label+'_face']=None if f is None else dict(
                u=f['u'],v=f['v'],w=f['w'],rho=f['density'],outlet_coeff=outlet_coeff,
                inlet_frac=f['inlet_opening'],outlet_frac=f['outlet_opening'],eps=f['epsilon'],
                dx=f['widths'][0],dy=f['widths'][1],dz=f['widths'][2],dir_real=bc['dir'],solver_to_real_perm=axes['solver_to_real_perm'])
            for key,value in (('m_dot_'+label+'_simple',r['inlet_mass'][s]),('cp_'+label,r['inlet_cp'][s]),
                ('T_in'+label,cfg['T_in'+label]),('u_'+label,cfg['u_'+label]),('f'+label,bc)):
                diagnostics['_audit_'+key]=value if f is not None else None
            diagnostics['_audit_P_in'+label]=cfg['P_in'+label]
        diagnostics['_audit_eps']=float(cfg['eps'])
        diagnostics['_audit_m_dot_B_phys_in']=r['physical_mass_in'][1] if r['flow'][1] else None
        diagnostics['_audit_m_dot_B_phys_out']=r['physical_mass_out'][1] if r['flow'][1] else None
    temperature_transport = (r['temperature_evidence']['definition'] if 'temperature_evidence' in r
                             else r.get('temperature_transport'))
    return FieldResult(result_id=str(uuid4()),case_id=case.case_id,backend_id='cpp',backend_version=f"full_3d_v{r['entry_version']}",grid=case.grid,
        fields=fields,field_metadata=field_metadata,model_refs=case.model_refs,
        boundary_fluxes=dict(mass_A=None if mass[0][0] is None else mass[0],mass_B=None if mass[1][0] is None else mass[1],
            mass_unit='kg/s',mass_axes=('x-face','y-face','z-face'),mass_sign='positive along physical coordinate axis',state='last thermal input',
            model_h=None if r['model_h'] is None else r['model_h']['_native_model_h'],true_h=true_h,report=report,
            face_velocity_A=r['face_velocity'][0],face_velocity_B=r['face_velocity'][1] if r['flow'][1] else None,
            **({'temperature':r['temperature_evidence']} if 'temperature_evidence' in r else {})),
        pressure_evidence=pressure,run_status=dict(execution='completed',converged=r['converged'],outer_index=r['outer_index']),
        metadata=dict(dimension=3,quantity_basis='total',thermal_mode=r['mode'],parameters=case.parameters,design_fields=case.design_fields,
            **({'temperature_transport':temperature_transport} if temperature_transport is not None else {}),
            design_mode=case.metadata['design_mode'],model_metadata=model_metadata,notices=case.metadata['notices'],
            application=dict(coeffs=dict(K_ffA=r['final_conductivity'][0],K_ffB=r['final_conductivity'][1],
                K_ss=np.asarray(p['design']['K_ss']) if emit_audit else None),
                props=dict(rho_cp_A=r['final_rho_cp'][0],rho_cp_B=r['final_rho_cp'][1],u_A_in_mps=cfg['u_A'],T_in_A_K=cfg['T_inA'])),
            **({'native':r['native_metadata']} if 'native_metadata' in r else {}),
            diagnostics=diagnostics,df_metadata=df_metadata,model_roles=case.metadata['model_roles'],
            reporting_reference={key:diagnostics[key] for key in ('Q','dP_A','dP_B','T_out_A','T_out_B')}))
