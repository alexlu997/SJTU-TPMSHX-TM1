"""Select captured inlet and final closure states for the range policy."""
from sjtu_tpmshx.domain.run_warnings import range_observations


_INLET_STAGES = {'inlet', 'inlet-preflight', 'prepared-df', 'df-application',
                 'asym-ratio', 'main-inlet', 'richardson-inlet', 'fallback-inlet'}
_FINAL_STAGES = {'main', 'main-hv', 'property-refresh', 'final', 'main-duty',
                 'richardson-duty', 'richardson-return'}


def capture_applicability(case, result, records):
    """Keep last source calls distinct from aggregate iteration warnings."""
    rows = (result.metadata.get('_last_closure_ranges', ()) if result.backend_id == 'cpp'
            else range_observations(records, last=True))
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
                scope_notes=tuple(dict.fromkeys((*case.metadata.get('notices', ()),
                    *(value for key, value in records.items() if key[0] == 'nu-evidence')))))
