"""Public physical preparation entry point; no numerical backend import."""
from dataclasses import replace
from copy import deepcopy
from math import isfinite

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


def prepare_fixed_mass_flow_case(
    config: ComputeConfig, *, mass_flow_A_kg_s: float,
    mass_flow_B_kg_s: float, case_id: str,
) -> CaseData:
    """Prepare a 2D or 3D candidate at prescribed total inlet mass flows.

    Integrate the actual inlet profile and pore fraction on the physical
    inlet slice, including reverse directions. The 2D tapered profile is
    normalized to the geometric open area by SIMPLE; its capacity includes
    that normalization, with the spatial pore fraction inside the integral.
    Prepared ``eps_A/B`` already represent each fluid's pore fraction in 3D.
    A 2D case requires an explicit physical depth ``geometry.Lz_m`` to convert
    total flow to the solver's per-unit-depth flow; its symmetric channel
    porosity is half the prepared total porosity.

    Resolve geometry and inlet density before checking inlet velocities, so
    the immutable snapshot and all speed-dependent preparation use the targets.
    The caller's configuration, geometry, inlet temperature/pressure and model
    choices stay intact.
    No numerical solve is performed.
    """
    config, targets = _fixed_mass_flow_inputs(config, mass_flow_A_kg_s, mass_flow_B_kg_s)
    if not config.is_3d:
        from .two_d.preparation import _prepare_inlet_data, _prepare_case
        from .inlet_flow import total_inlet_mass_capacity

        design, parameters, grid = _prepare_inlet_data(deepcopy(config).validate_static_inputs())
        capacities = {side: total_inlet_mass_capacity(design, parameters, grid, side) for side in 'AB'}
        resolved = _resolve_inlet_speeds(config, targets, capacities)
        spline_geometry = design if config.zones.enabled and config.zones.axis == 'continuous' else None
        del design, parameters
        return _prepare_with_metadata(_prepare_case, resolved, case_id=case_id,
                                      inlet_grid=grid, spline_geometry=spline_geometry)

    def prepare():
        from .three_d.preparation import (
            _parse_geometry_inputs_3d_cfg, _prepare_geometry_data, _finish_problem_data,
            _set_run_environment, _case_from_prepared,
        )
        from .inlet_flow import total_inlet_mass_capacity
        from sjtu_tpmshx.models.input_validation import surrogate_extrap_reasons

        config.validate_static_inputs()
        cfg = _parse_geometry_inputs_3d_cfg(config)
        _set_run_environment(cfg)
        prepared = _prepare_geometry_data(cfg)
        capacities = {side: total_inlet_mass_capacity(
            prepared['design'], {'prepared': prepared}, {'dimension': 3}, side) for side in 'AB'}
        resolved = _resolve_inlet_speeds(config, targets, capacities)
        prepared['cfg'].update(u_A=resolved.fluid_A.u_mps, u_B=resolved.fluid_B.u_mps,
            compute_cfg=resolved, extrap_reasons=surrogate_extrap_reasons(resolved, bool(resolved.extrap.allow)))
        return _case_from_prepared(resolved, _finish_problem_data(prepared), case_id=case_id)

    return _prepare_with_metadata(prepare)


def resolve_fixed_mass_flow_config(
    config: ComputeConfig, *, mass_flow_A_kg_s: float, mass_flow_B_kg_s: float,
) -> ComputeConfig:
    """Resolve inlet velocities from the actual geometry, then validate them."""
    config, targets = _fixed_mass_flow_inputs(config, mass_flow_A_kg_s, mass_flow_B_kg_s)
    return _resolve_inlet_speeds(config, targets, prepare_inlet_mass_capacities(config))


def _fixed_mass_flow_inputs(config, flow_a, flow_b):
    config = deepcopy(config)
    if config.fluid_A is None or config.fluid_B is None:
        raise ValueError('fixed mass flow requires a dual-fluid ComputeConfig')
    if not config.is_3d and (config.geometry.Lz_m is None or not isfinite(config.geometry.Lz_m)
                             or config.geometry.Lz_m <= 0):
        raise ValueError('2D total mass flow requires a positive physical Lz_m')
    targets = {'A': flow_a, 'B': flow_b}
    for side, target in targets.items():
        if not isfinite(target) or target <= 0:
            raise ValueError(f'mass_flow_{side}_kg_s must be finite and positive')
    return config, targets


def _resolve_inlet_speeds(config, targets, capacities):
    fluids = {'fluid_' + side: replace(getattr(config, 'fluid_' + side),
                                       u_mps=target / capacities[side])
              for side, target in targets.items()}
    return replace(config, **fluids).validate()


def prepare_quick_design(*args, **kwargs) -> CaseData:
    """Explicit prescribed-velocity design mode; no SIMPLE substitution."""
    from .app_modes.quick_design import prepare_quick_design as prepare
    return _prepare_with_metadata(prepare, *args, **kwargs)
