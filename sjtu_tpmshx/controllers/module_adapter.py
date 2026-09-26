"""Map archived module results to the existing application display contract."""
from dataclasses import asdict

from sjtu_tpmshx.domain.compute_result import ComputeResult
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.models.zone_units import _legacy_zone_units


def to_compute_result(result, performance):
    """No solve, preparation or metric reduction; use this run's archived data."""
    if performance.source_result_id != result.result_id:
        raise ValueError('performance belongs to another result')
    if result.run_status.get('execution') != 'completed':
        raise ValueError('application display requires a completed result')
    dimension = result.grid['dimension']
    unit = 'W/m' if dimension == 2 else 'W'
    if performance.metrics['Q'].spec.unit != unit:
        raise ValueError('heat-duty unit disagrees with the result dimension')
    if performance.metrics['Q'].spec.definition_version != 'native_boundary_v1':
        raise ValueError('re-evaluate native results before displaying the current heat-duty definition')
    if any(performance.metrics[name].spec.definition_version != 'pressure_face_v1'
           for name in ('dP_A', 'dP_B')):
        raise ValueError('re-evaluate native results before displaying the current pressure-drop definition')
    f = result.fields
    parameters = result.metadata['parameters']
    diagnostics = mutable_data(result.metadata['diagnostics'])
    application = mutable_data(result.metadata['application'])
    fields = {name: mutable_data(f[name + '_display']) for name in ('Ta', 'Tb', 'Ts')}
    fields.update({name: mutable_data(f.get(name + '_display')) for name in ('P_fA', 'P_fB')})
    fields.update({name: mutable_data(f.get(name)) for name in ('ucA', 'vcA', 'ucB', 'vcB')})
    if dimension == 2:
        geometry = parameters['static_properties']['geometry']
        fields.update({name + '_disp': mutable_data(f.get(name + '_display'))
                       for name in ('ucA', 'vcA', 'ucB', 'vcB')})
        zone = _legacy_zone_units(mutable_data(parameters['zone_config']))
        if isinstance(zone, dict):
            from sjtu_tpmshx.models.zone_config import Zone, ZoneConfig
            zone['zones'] = [Zone(**item) for item in zone['zones']]
            zone = ZoneConfig(**zone)
        fields.update(dx_arr=result.grid['dx'], dy_arr=result.grid['dy'],
                      N_x=len(result.grid['dx']), N_y=len(result.grid['dy']),
                      L=parameters['L'], H=parameters['H'],
                      dir_A=parameters['dir_A'], dir_B=parameters['dir_B'], zone_config=zone,
                      za=(_legacy_zone_units(mutable_data(result.metadata['design_fields']))
                          if result.metadata['design_mode'] != 'uniform' else None))
        residuals = {name: diagnostics[name] for name in
                     ('mass_imbalance_rel_A', 'mass_imbalance_rel_B', 'Q_A', 'Q_B', 'energy_imbalance_rel')}
        residuals.update(r_dP_A=float('nan'), r_dP_B=float('nan'),
                         r_Q=float(bool(diagnostics['Q_richardson_warn'])),
                         simple_A=diagnostics['residuals_A'], simple_B=diagnostics['residuals_B'])
        zones = application['zones']
    elif dimension == 3:
        geometry = parameters['prepared']['geometry']
        fields.update({name: mutable_data(f.get(name)) for name in ('wcA', 'wcB', 'vmag_A', 'vmag_B')})
        fields.update({axis: result.grid[axis] for axis in ('dx', 'dy', 'dz')})
        fields.update(Lx=parameters['L'], Ly=parameters['H'], Lz=parameters['Lz'],
                      L_mm=result.metadata['design_fields']['L_field_m'] * 1e3,
                      t_mm=result.metadata['design_fields']['t_field_m'] * 1e3,
                      dir_A=diagnostics['dir_A'], dir_B=diagnostics['dir_B'],
                      h_vA_field=mutable_data(f['h_vA']), h_vB_field=mutable_data(f['h_vB']))
        residuals = {name: diagnostics.get(name) for name in (
            'Q_enthalpy_A', 'Q_enthalpy_B', 'Q_solid_B', 'Q_sA', 'Q_sB', 'Q_interior',
            'energy_imbalance_rel', 'mass_imbalance_rel_A', 'mass_imbalance_rel_B')}
        zones = None
    else:
        raise ValueError(f'unsupported result dimension: {dimension}')
    props = application['props']
    props.update(eps_A=geometry['epsilon'], D_h_m=geometry['D_h'], A_0_m2=geometry['A_0'])
    diagnostics['mode'] = f'{dimension}d'
    metadata = mutable_data(result.metadata['model_metadata'])
    metadata.update(darcy_forchheimer=mutable_data(result.metadata['df_metadata']),
                    quantity_basis=result.metadata['quantity_basis'], units={'Q': unit},
                    source_result_id=result.result_id, case_id=result.case_id,
                    backend_id=result.backend_id, backend_version=result.backend_version,
                    model_refs=[dict(name=ref.name, version=ref.version,
                                     parameters=mutable_data(ref.parameters), applicability=ref.applicability)
                                for ref in result.model_refs])
    warnings = list(dict.fromkeys((*diagnostics.get('warnings_list', ()),
                                  *diagnostics.get('envelope_warnings', ()), *result.metadata['notices'])))
    values = {}
    for name in ('Q', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B'):
        metric = performance.metrics[name]
        values[name] = metric.value if metric.status == 'available' else float('nan')
        if metric.status != 'available':
            warnings.append(f'{name}: {metric.status}: {metric.reason}')
    metadata['metric_status'] = {name: performance.metrics[name].status for name in values}
    metadata['metric_reasons'] = {name: performance.metrics[name].reason for name in values
                                  if performance.metrics[name].status != 'available'}
    metadata['metric_definitions'] = {name: asdict(metric.spec)
                                      for name, metric in performance.metrics.items()}
    for name in ('Q_A', 'Q_B', 'energy_imbalance_rel', 'mass_imbalance_rel_A', 'mass_imbalance_rel_B',
                 'Q_richardson_A', 'Q_richardson_B'):
        if name in performance.metrics:
            metric = performance.metrics[name]
            residuals[name] = metric.value if metric.status == 'available' else float('nan')
    residuals['Q_net'] = residuals['Q_A'] + residuals['Q_B']
    residuals['enthalpy_imbalance_rel'] = residuals['energy_imbalance_rel']
    return ComputeResult(
        Q_W=values['Q'], dP_A_Pa=values['dP_A'], dP_B_Pa=values['dP_B'],
        T_out_A_K=values['T_out_A'], T_out_B_K=values['T_out_B'],
        converged=bool(result.run_status['converged']), fields=fields,
        coeffs=application['coeffs'], props=props, residuals=residuals, zones=zones,
        warnings=warnings, extrap_reasons=list(parameters['extrap_reasons']),
        diagnostics=diagnostics, metadata=metadata)
