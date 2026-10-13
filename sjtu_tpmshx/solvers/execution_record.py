"""Describe the physical resources and methods of a completed full solve."""


def full_execution_record(case, result):
    """Use returned evidence; requested settings do not prove execution."""
    metadata = result.metadata
    mode = metadata['thermal_mode']
    if mode not in ('true_h', 'conservative_energy', 'model_h', 'temperature', 'legacy_temperature'):
        raise ValueError(f'unsupported executed thermal mode: {mode}')
    eos = mode in ('true_h', 'conservative_energy')
    temperature = result.boundary_fluxes.get('temperature') or {}
    integral = mode == 'model_h' or temperature.get('definition') == 'model_enthalpy_temperature_v1'
    balance = metadata['diagnostics'].get('true_h_balance') or {}
    settings = balance.get('effective_settings', {})
    native = metadata.get('native', {})
    algorithm = settings.get('energy_algorithm', native.get('algorithm'))
    table = metadata.get('model_metadata', {}).get('sco2_enthalpy_eos', {})
    roles = case.metadata['model_roles']
    sides = {}
    for label, field in (('A', 'Ta'), ('B', 'Tb')):
        index = roles['fluid_' + label]
        fluid = case.model_refs[index].parameters['fluid']
        flow_solved = result.pressure_evidence.get(label) is not None
        solved = temperature.get('solved', {}).get(label, flow_solved)
        relation = ('eos_h_TP' if eos else 'integral_cp_T' if integral else 'capacity_temperature')
        energy = dict(relation=relation if solved else 'prescribed_temperature',
                      property_provider=('HEOS' if eos else 'model_resource') if solved else None,
                      model_ref=index if solved and not eos else None, temperature_field=field)
        if eos:
            pressure_field = 'P_thermal_' + label
            energy.update(fluid={'air': 'Air', 'water': 'Water', 'co2': 'CO2', 'sco2': 'CO2'}[fluid],
                          pressure_field=pressure_field,
                          pressure_state=result.field_metadata[pressure_field]['state'])
        evaluation = dict(state_update=(settings.get('nonlinear_state_update',
                                                     'T(h,P)' if eos else 'model_relation')
                                        if solved else None))
        if eos:
            evaluation['final_property_backend'] = 'HEOS'
            if mode == 'true_h':
                evaluation['inverse_backend'] = 'HEOS'
                if label in table.get('sides', ()):
                    evaluation.update(inverse_backend=table['iteration_backend'],
                                      inverse_algorithm=table['algorithm'],
                                      heos_polish=table['heos_polish'],
                                      coolprop_version=table['coolprop_version'])
        sides[label] = dict(fluid=fluid, solved=solved, flow_and_exchange_model_ref=index,
                            energy=energy, property_evaluation=evaluation)
    return dict(version='full_execution_v1', backend=result.backend_id,
                backend_version=result.backend_version, dimension=case.grid['dimension'],
                sides=sides, closure_model_refs={key: roles[key] for key in ('geometry', 'darcy_forchheimer')},
                numerics=dict(thermal_mode=mode, unknown='h' if mode == 'true_h' else 'T',
                              algorithm=algorithm, algorithm_version=settings.get('energy_algorithm_version'),
                              face_reconstruction=settings.get('enthalpy_face_reconstruction'),
                              temperature_transport=metadata.get('temperature_transport'),
                              effective_settings=settings, native=native),
                evidence=dict(thermal_state=result.field_metadata['Ta']['state'],
                              mass_state=result.boundary_fluxes['state'],
                              pressure_report_states={label: None if value is None else
                                                      result.field_metadata['P_report_' + label]['state']
                                                      for label, value in result.pressure_evidence.items()},
                              outer_index=result.run_status['outer_index']))
