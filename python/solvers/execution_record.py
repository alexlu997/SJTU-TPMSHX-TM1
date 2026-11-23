"""Recover execution facts from full results without a native execution view."""
from sjtu_tpmshx.data_types.field_result import execution_record


def full_execution_record(case, result, *, sides=None, thermal=None):
    """Use returned evidence; requested settings do not prove execution."""
    metadata = result.metadata
    if thermal is None or sides is None:
        mode = thermal['thermal_mode'] if thermal is not None else metadata['thermal_mode']
        if mode not in ('true_h', 'conservative_energy', 'model_h', 'temperature', 'legacy_temperature'):
            raise ValueError(f'unsupported executed thermal mode: {mode}')
        eos = mode in ('true_h', 'conservative_energy')
        temperature = result.boundary_fluxes.get('temperature') or {}
        integral = mode == 'model_h' or temperature.get('definition') == 'model_enthalpy_temperature_v1'
        if thermal is None:
            balance = metadata['diagnostics'].get('true_h_balance') or {}
            settings = balance.get('effective_settings', {})
            model_h_iterations = metadata.get('model_h_iterations')
            if integral and model_h_iterations:
                main_calls = [row for row in model_h_iterations['records'] if row['stage'] == 'outer_thermal']
                if main_calls:
                    settings = main_calls[-1]['settings']
            thermal = dict(thermal_mode=mode, unknown='h' if mode == 'true_h' else 'T',
                           temperature_transport=metadata.get('temperature_transport'), effective_settings=settings)
        if sides is None:
            models = metadata.get('model_metadata', {})
            table = models.get('enthalpy_eos', models.get('sco2_enthalpy_eos', {}))
            sides = _execution_sides(case, result, mode, eos, integral, table, temperature)
    states = dict(thermal_state=result.field_metadata['Ta']['state'], mass_state=result.boundary_fluxes['state'],
                  pressure_report_states={label: None if value is None else result.field_metadata['P_report_' + label]['state']
                                          for label, value in result.pressure_evidence.items()},
                  outer_index=result.run_status['outer_index'])
    return execution_record(result.backend_id, result.backend_version, metadata, version='full_execution_v1',
                            dimension=case.grid['dimension'], roles=case.metadata['model_roles'],
                            sides=sides, thermal=thermal, evidence=states)


def _execution_sides(case, result, mode, eos, integral, table, temperature):
    metadata = result.metadata
    roles = case.metadata['model_roles']
    energy_samples = {}
    for sample in metadata.get('property_sampling', ()):
        if sample['quantity'] == 'energy_relation' and sample['stage'] == 'thermal':
            label = sample['side']
            if label not in energy_samples or sample['outer_index'] >= energy_samples[label]['outer_index']:
                energy_samples[label] = sample
    sides = {}
    for label, field in (('A', 'Ta'), ('B', 'Tb')):
        index = roles['fluid_' + label]
        fluid = case.model_refs[index].parameters['fluid']
        flow_solved = result.pressure_evidence.get(label) is not None
        solved = temperature.get('solved', {}).get(label, flow_solved)
        relation = ('eos_h_TP' if eos else 'integral_cp_T' if integral else 'capacity_temperature')
        if solved and label in energy_samples:
            sample = energy_samples[label]
            if sample['provider'] == 'HEOS' and sample['operation'] == 'local_evaluation':
                relation = 'eos_h_TP'
            elif sample['operation'] == 'integral_cp_T':
                relation = 'integral_cp_T'
            elif sample['operation'] == 'frozen_capacity_temperature':
                relation = 'capacity_temperature'
            else:
                raise ValueError(f'unsupported executed energy sampling: {sample}')
        side_eos = relation == 'eos_h_TP'
        energy = dict(relation=relation if solved else 'prescribed_temperature',
                      property_provider=('HEOS' if side_eos else 'model_resource') if solved else None,
                      model_ref=index if solved and not side_eos else None, temperature_field=field)
        if side_eos and solved:
            pressure_field = 'P_thermal_' + label
            energy.update(fluid={'air': 'Air', 'water': 'Water', 'co2': 'CO2', 'sco2': 'CO2'}[fluid],
                          pressure_field=pressure_field,
                          pressure_state=result.field_metadata[pressure_field]['state'])
        if side_eos:
            state_update = 'HEOS_PT' if mode == 'conservative_energy' else 'T(h,P)'
        elif relation == 'integral_cp_T':
            state_update = 'T(h)' if mode == 'true_h' else 'h(T)'
        else:
            state_update = 'model_relation'
        evaluation = dict(state_update=state_update if solved else None)
        if side_eos and solved:
            evaluation['final_property_backend'] = 'HEOS'
            if mode == 'true_h':
                evaluation['iteration_inverse_backend'] = 'HEOS'
                if label in table.get('sides', ()):
                    evaluation.update(iteration_inverse_backend=table['iteration_backend'],
                                      inverse_algorithm=table['algorithm'],
                                      heos_polish=table['heos_polish'],
                                      coolprop_version=table['coolprop_version'])
        sides[label] = dict(fluid=fluid, solved=solved, flow_and_exchange_model_ref=index,
                            energy=energy, property_evaluation=evaluation)
    return sides
