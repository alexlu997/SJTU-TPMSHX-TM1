"""Attach portable model references and effective settings to solver reports."""


def link_execution(report, case, energy):
    """Attach portable model references to the completed solver report."""
    facts = report['facts']
    for side, record in facts['sides'].items():
        model = case.metadata['model_roles']['fluid_' + side]
        record['flow_and_exchange_model_ref'] = model
        record['energy']['model_ref'] = model if record['solved'] and 'fluid' not in record['energy'] else None
    index = report['last_main_model_h']
    rows = report['model_h_iterations']['records']
    facts['thermal']['effective_settings'] = (
        rows[index]['settings'] if index < len(rows) else
        energy['effective_settings'] if energy is not None else {})
    return facts
