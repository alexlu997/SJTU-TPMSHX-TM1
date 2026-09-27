"""Public physical preparation entry point; no numerical backend import."""
from dataclasses import replace
from copy import deepcopy

from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.run_warnings import warning_scope, warning_messages
from sjtu_tpmshx.domain.provenance import source_context


def _prepare_with_metadata(prepare, *args, **kwargs) -> CaseData:
    provenance = source_context()
    with warning_scope({}) as records:
        case = prepare(*args, **kwargs)
    warnings = tuple(dict.fromkeys((*case.metadata.get('warnings', ()),
                                    *warning_messages(records))))
    return replace(case, metadata={**case.metadata, 'provenance': provenance,
                                   'warnings': warnings})


def prepare_case(config: ComputeConfig, *, case_id: str) -> CaseData:
    if config.is_3d:
        from .three_d.preparation import prepare_case as prepare
    else:
        from .two_d.preparation import prepare_case as prepare
    return _prepare_with_metadata(prepare, config, case_id=case_id)


def prepare_inlet_mass_capacities(config: ComputeConfig) -> dict[str, float]:
    """Resolve mass per inlet speed without evaluating an obsolete velocity.

    Geometry, ports and static inputs are validated before constructing fields.
    The caller must still prepare the final case after prescribing its speeds.
    """
    from .inlet_flow import total_inlet_mass_capacity

    config = deepcopy(config).validate_static_inputs()
    if config.is_3d:
        from .three_d.preparation import _parse_geometry_inputs_3d_cfg, _prepare_geometry_data
        prepared = _prepare_geometry_data(_parse_geometry_inputs_3d_cfg(config))
        design, parameters, grid = prepared['design'], {'prepared': prepared}, {'dimension': 3}
    else:
        from .two_d.preparation import _prepare_inlet_data
        design, parameters, grid = _prepare_inlet_data(config)
    return {side: total_inlet_mass_capacity(design, parameters, grid, side) for side in ('A', 'B')}


def prepare_quick_design(*args, **kwargs) -> CaseData:
    """Explicit prescribed-velocity design mode; no SIMPLE substitution."""
    from .app_modes.quick_design import prepare_quick_design as prepare
    return _prepare_with_metadata(prepare, *args, **kwargs)


def prepare_screening_2d(*args, **kwargs) -> CaseData:
    """Prepare the existing air/air continuous-field optimization model."""
    from .app_modes.screening_2d import prepare_screening_2d as prepare
    return _prepare_with_metadata(prepare, *args, **kwargs)


def prepare_screening_3d(*args, **kwargs) -> CaseData:
    """Prepare the existing frozen-B 3D screening model."""
    from .app_modes.screening_3d import prepare_screening_3d as prepare
    return _prepare_with_metadata(prepare, *args, **kwargs)
