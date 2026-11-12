"""Copy native applicability evidence and retain direct-runtime capture."""

_INLET_STAGES = {'inlet', 'inlet-preflight', 'prepared-df', 'df-application',
                 'asym-ratio', 'main-inlet', 'richardson-inlet', 'fallback-inlet'}
_FINAL_STAGES = {'main', 'main-hv', 'property-refresh', 'final', 'main-duty',
                 'richardson-duty', 'richardson-return'}


def capture_applicability(case, result, records):
    """Keep last source calls distinct from aggregate iteration warnings."""
    rows = result.metadata.get('_last_closure_ranges', ())
    inlet = list(case.metadata.get('applicability_inputs', ()))
    inlet.extend(row for row in rows if row['stage'] in _INLET_STAGES)
    inlet = [dict(row, constraint='hard_bounds') if row['source'][0] == 'geometry' else row
             for row in inlet]
    final = [row for row in rows if row['stage'] in _FINAL_STAGES and
             (row['source'][0] != 'property_state' or row['stage'] in ('final', 'richardson-return'))]
    roles = case.metadata.get('model_roles', {})
    required = [dict(group='inlet', side='shared', source=('geometry', field))
                for field in ('L_field_m', 't_field_m')]
    for side, pressure in result.pressure_evidence.items():
        if pressure is None or 'fluid_' + side not in roles:
            continue
        fluid = case.model_refs[roles['fluid_' + side]].parameters['fluid']
        topology = case.model_refs[roles['darcy_forchheimer']].parameters['topology']
        required.extend((dict(group='inlet', side=side, source=('nu', fluid, topology)),
                         dict(group='final', side=side, source=('nu_raw', fluid, topology))))
        if fluid == 'co2':
            required.append(dict(group='final', side=side, source=('nu_pr', fluid, topology)))
        if fluid in ('air', 'water') and result.metadata.get('thermal_mode') in (
                'model_h', 'temperature', 'legacy_temperature'):
            required.append(dict(group='final', side=side, source=('property_state', fluid + '_cp')))
    return dict(version='applicability_evidence_v1',
                inlet_recorded='applicability_inputs' in case.metadata,
                inlet=inlet, final=final, required=required,
                scope_notes=captured_scope_notes(case, records))


def captured_scope_notes(case, records):
    """Keep complete host notices and callback records in their original order."""
    return tuple(dict.fromkeys((*case.metadata.get('notices', ()),
        *(value for key, value in records.items() if key[0] == 'nu-evidence'))))


def copy_applicability(pointer, saved_inlet):
    """Copy selected evidence before the native result owner is released."""
    if not pointer or pointer.contents.version != b'applicability_evidence_v1':
        raise RuntimeError('native result lacks supported applicability evidence')
    value = pointer.contents
    if value.inlet_count < len(saved_inlet):
        raise RuntimeError('native applicability evidence lacks saved inlet rows')
    inlet = []
    for index in range(value.inlet_count):
        raw = value.inlet[index]
        # Saved rows retain host fields and scalar types absent from the C descriptor.
        row = dict(saved_inlet[index]) if index < len(saved_inlet) else _copy_range(raw)
        if raw.constraint is not None:
            row['constraint'] = raw.constraint.decode()
        inlet.append(row)
    return dict(version=value.version.decode(), inlet_recorded=bool(value.inlet_recorded),
        inlet=inlet, final=[_copy_range(value.final_state[index]) for index in range(value.final_count)],
        required=[dict(group=row.group.decode(), side=row.side.decode(),
            source=tuple(item.decode() for item in row.source[:row.source_count]))
            for row in value.required[:value.required_count]])


def _copy_range(value):
    row = {name: getattr(value, name).decode() for name in ('side', 'quantity', 'stage', 'layout', 'unit')}
    row.update(source=tuple(item.decode() for item in value.source[:value.source_count]),
        captured=bool(value.captured), shape=tuple(value.shape[:value.rank]), bounds=tuple(value.bounds))
    for name in ('constraint', 'reason'):
        if getattr(value, name) is not None:
            row[name] = getattr(value, name).decode()
    if value.captured:
        row.update({name: getattr(value, name) for name in ('size', 'low', 'high', 'nonfinite')})
        for name in ('minimum', 'maximum'):
            row[name] = ((getattr(value, name)[0], tuple(getattr(value, name + '_index')[:value.rank]))
                         if getattr(value, name) else None)
    return row
