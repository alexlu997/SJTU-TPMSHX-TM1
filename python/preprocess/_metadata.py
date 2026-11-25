"""Collect provenance and warning records for a prepared case."""
from contextlib import ExitStack
from dataclasses import replace

from sjtu_tpmshx.data_types.case_data import CaseData
from sjtu_tpmshx.run_control.provenance import source_context
from sjtu_tpmshx.run_control.run_warnings import warning_scope, warning_messages, range_observations


def _finish_metadata(case, provenance, records) -> CaseData:
    warnings = tuple(dict.fromkeys((*case.metadata.get('warnings', ()),
                                    *warning_messages(records))))
    inlets = {side: case.config_snapshot.get('fluid_' + side, {}) for side in 'AB'}
    if any(fluid.get('mass_flow_kg_s') is not None for fluid in inlets.values()):
        case = replace(case, parameters={**case.parameters, 'inlet_inputs': {
            side: {name: fluid[name] for name in ('u_mps', 'mass_flow_kg_s')}
            for side, fluid in inlets.items()}})
    return replace(case, metadata={**case.metadata, 'provenance': provenance,
                                   'warnings': warnings, 'applicability_inputs': range_observations(records)})


def prepare_with_metadata(prepare, *args, **kwargs) -> CaseData:
    provenance = source_context()
    with warning_scope({}) as records:
        return _finish_metadata(prepare(*args, **kwargs), provenance, records)


def prepare_fixed_flow_with_metadata(prepare, config, targets, *, case_id) -> CaseData:
    with ExitStack() as scopes:
        provenance: dict
        records: dict

        # Start collection when the native stage checks its inputs.
        def start_observations() -> None:
            nonlocal provenance, records
            provenance = source_context()
            records = scopes.enter_context(warning_scope({}))

        case = prepare(config, targets, case_id=case_id, start_observations=start_observations)
        return _finish_metadata(case, provenance, records)
