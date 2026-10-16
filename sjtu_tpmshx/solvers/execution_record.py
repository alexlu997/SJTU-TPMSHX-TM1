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
    model_h_iterations = metadata.get('model_h_iterations')
    if integral and model_h_iterations:
        main_calls = [row for row in model_h_iterations['records'] if row['stage'] == 'outer_thermal']
        if main_calls:
            settings = main_calls[-1]['settings']
    native = metadata.get('native', {})
    algorithm = settings.get('energy_algorithm', native.get('algorithm'))
    models = metadata.get('model_metadata', {})
    table = models.get('enthalpy_eos', models.get('sco2_enthalpy_eos', {}))
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
    return dict(version='full_execution_v1', backend=result.backend_id,
                backend_version=result.backend_version, dimension=case.grid['dimension'],
                **({'input_resolution': metadata['input_resolution']} if 'input_resolution' in metadata else {}),
                **({'property_sampling': dict(version='full_sampling_v1', records=metadata['property_sampling'])}
                   if 'property_sampling' in metadata else {}),
                sides=sides, closure_model_refs={key: roles[key] for key in ('geometry', 'darcy_forchheimer')},
                numerics=dict(thermal_mode=mode, unknown='h' if mode == 'true_h' else 'T',
                              algorithm=algorithm, algorithm_version=settings.get('energy_algorithm_version'),
                              face_reconstruction=settings.get('enthalpy_face_reconstruction'),
                              temperature_transport=metadata.get('temperature_transport'),
                              effective_settings=settings, native=native,
                              **({'enthalpy_update_normalization': metadata['enthalpy_update_normalization']}
                                 if metadata.get('enthalpy_update_normalization') else {}),
                              **({'simple_velocity_relaxation': metadata['simple_velocity_relaxation']}
                                 if 'simple_velocity_relaxation' in metadata else {}),
                              **({'simple_flow': metadata['simple_flow']} if 'simple_flow' in metadata else {}),
                              **({'model_h_iterations': model_h_iterations} if model_h_iterations else {})),
                evidence=dict(thermal_state=result.field_metadata['Ta']['state'],
                              mass_state=result.boundary_fluxes['state'],
                              pressure_report_states={label: None if value is None else
                                                      result.field_metadata['P_report_' + label]['state']
                                                      for label, value in result.pressure_evidence.items()},
                              outer_index=result.run_status['outer_index']))


def resolved_input_record(case, providers, shape, directions):
    """Record resources only after the execution builder has validated them."""
    roles = case.metadata['model_roles']
    return dict(version='prepared_input_v1', source='CaseData.parameters',
                grid_source='CaseData.grid', design_source='CaseData.design_fields',
                grid_shape=tuple(shape), active_sides=tuple(directions), directions=directions,
                grid_length_unit='m', cell_length_unit_in_file='m', cell_length_unit_after_resolution='mm',
                resources={role: dict(model_ref=index, name=case.model_refs[index].name,
                                      version=case.model_refs[index].version)
                           for role, index in roles.items()},
                fluids={side: providers['fluid_' + side].name for side in ('A', 'B')})


def record_property_samples(records, side, outer_index, stage, provider,
                            temperature, pressure, operation, *quantities):
    """Describe a sampling operation at its numerical owner."""
    records.extend(dict(side=side, outer_index=outer_index, stage=stage, quantity=quantity,
                        provider=provider, temperature=temperature, pressure=pressure,
                        operation=operation) for quantity in quantities)
