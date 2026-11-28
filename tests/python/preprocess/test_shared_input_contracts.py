"""Public config boundaries reject ambiguous inputs before physical preparation."""
from dataclasses import asdict

import pytest

from tm1.data_types.compute_config import (
    ComputeConfig, GeometryConfig, PartialBCConfig, SolverConfig, ZoneInputConfig, bc_to_dict,
)
from tm1.data_types.validator import validate_pipe_config
from tm1.physical_models.zone_config import Zone, ZoneConfig
from tm1.preprocess.api import prepare_case


def _zoned(mode, dimension, topology='Gyroid', conductivity=16.):
    if mode == 'grid':
        zones = ZoneInputConfig(enabled=True, axis=mode, grid=dict(
            cells=[dict(x0=0., x1=1., y0=0., y1=1., L=6., t=.4)],
            tpms_type=topology, k_s=conductivity))
    else:
        zones = ZoneInputConfig(enabled=True, axis=mode, config=ZoneConfig(
            [Zone('all', 0., 1., 6., .4)], topology, conductivity))
    return ComputeConfig(geometry=GeometryConfig(L_cell_mm=6., t_wall_mm=.4,
        Lz_m=.042 if dimension == 3 else None), zones=zones,
        solver=SolverConfig(Nx=4, Ny=4, Nz=2 if dimension == 3 else 1))


@pytest.mark.parametrize('mode,dimension', [('grid', 2), ('grid', 3), ('x', 2), ('y', 2)])
@pytest.mark.parametrize('change,field', [({'topology': 'Diamond'}, 'tpms_type'),
                                         ({'conductivity': 160.}, 'k_s')])
def test_conflicting_zone_copy_is_rejected_at_config_and_prepare(mode, dimension, change, field):
    config = _zoned(mode, dimension, **change)
    for action in (config.validate, lambda: ComputeConfig.from_dict(asdict(config)),
                   lambda: prepare_case(config, case_id='conflicting-zones')):
        with pytest.raises(ValueError, match=f'zones.*{field}.*geometry'):
            action()


@pytest.mark.parametrize('mode,dimension', [('grid', 2), ('grid', 3), ('x', 2), ('y', 2)])
def test_matching_zone_copy_keeps_json_and_preparation(mode, dimension):
    config = _zoned(mode, dimension)
    restored = ComputeConfig.from_dict(asdict(config))
    assert restored.geometry == config.geometry
    case = prepare_case(restored, case_id='matching-zones')
    assert case.grid['dimension'] == dimension


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('width', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_width_rejected_before_full_face_normalization(side, width):
    bc = PartialBCConfig(in_w=width, out_w=width)
    with pytest.raises(ValueError, match='width.*finite'):
        bc_to_dict(bc, .182, .042, side=side)
    config = ComputeConfig()
    setattr(config, f'bc_{side}', bc)
    with pytest.raises(ValueError, match='width.*finite'):
        config.validate()


@pytest.mark.parametrize('width', [0., -1.])
def test_finite_nonpositive_full_face_sentinel_is_preserved(width):
    bc = PartialBCConfig(in_ctr=.001, out_ctr=.002, in_w=width, out_w=width)
    config = ComputeConfig(bc_A=bc, bc_B=bc).validate()
    pipe = bc_to_dict(config.bc_A, .182, .042)
    assert (pipe['in_ctr'], pipe['out_ctr'], pipe['in_w'], pipe['out_w']) == (.021, .021, .042, .042)
    assert bc_to_dict(bc, .182, .042, side='B') is None


@pytest.mark.parametrize('direction', [2.5, 2., '2', True, None, float('nan')])
def test_original_direction_must_be_integer_enum(direction):
    pipe = dict(dir=direction, in_ctr=.021, out_ctr=.021, in_w=.042, out_w=.042)
    errors = validate_pipe_config(pipe, .182, .042)
    assert any(item.code == 'pipe_bad_dir' and item.severity == 'error' for item in errors)
    config = ComputeConfig(bc_A=PartialBCConfig(dir=direction))
    with pytest.raises(ValueError, match='pipe_bad_dir'):
        config.validate()


@pytest.mark.parametrize('dimension,directions', [(2, range(4)), (3, range(6))])
def test_supported_integer_directions_keep_full_face_ports(dimension, directions):
    for direction in directions:
        ComputeConfig(geometry=GeometryConfig(Lz_m=.042 if dimension == 3 else None),
            solver=SolverConfig(Nz=2 if dimension == 3 else 1),
            bc_A=PartialBCConfig(dir=direction)).validate()


@pytest.mark.parametrize('domain', [{'L_dom_mm': 80}, {'H_dom_mm': 40}, {'Lz_mm': 42}])
def test_legacy_unknown_domain_keys_do_not_select_default_geometry(domain):
    with pytest.raises(ValueError, match='legacy domain.*unknown'):
        ComputeConfig.from_dict({'domain': domain})


def test_legacy_supported_and_omitted_domain_fields_still_load():
    default = ComputeConfig.from_dict({'domain': {}})
    assert (default.geometry.L_dom_m, default.geometry.H_dom_m) == (.182, .042)
    actual = ComputeConfig.from_dict({'domain': {'L_dom_m': .08, 'H_dom_m': .04, 'Lz_m': .03}})
    assert (actual.geometry.L_dom_m, actual.geometry.H_dom_m, actual.geometry.Lz_m) == (.08, .04, .03)


def test_invalid_port_precedes_invalid_speed_at_public_entries():
    from tm1.compute import compute
    from tm1.data_types.compute_config import ComputeConfig
    from tm1.preprocess.api import prepare_case

    config = ComputeConfig()
    config.bc_A.in_w = config.bc_A.out_w = .01
    config.bc_A.in_ctr = 2.
    config.fluid_A.u_mps = -1.
    for entry in (compute, prepare_case):
        with pytest.raises(ValueError, match='pipe_in_out_of_domain'):
            entry(config, case_id='invalid-input')


def test_mass_flow_entries_preserve_static_port_error_order():
    from tm1.data_types.compute_config import ComputeConfig
    from tm1.preprocess import api

    config = ComputeConfig()
    config.geometry.Lz_m = .04
    config.fluid_A.mass_flow_kg_s = .01
    config.bc_A.in_w = config.bc_A.out_w = .01
    config.bc_A.in_ctr = 2.
    config.solver.mom_tol = -1.
    fixed = dict(mass_flow_A_kg_s=.01, mass_flow_B_kg_s=.02)
    for entry, kwargs in (
        (api.prepare_case, dict(case_id='invalid')),
        (api.prepare_inlet_mass_capacities, {}),
        (api.resolve_inlet_flow_config, {}),
        (api.prepare_fixed_mass_flow_case, dict(case_id='invalid', **fixed)),
        (api.resolve_fixed_mass_flow_config, fixed),
    ):
        with pytest.raises(ValueError, match='pipe_in_out_of_domain'):
            entry(config, **kwargs)


def test_invalid_configuration_precedes_second_cancel_poll():
    from tm1.compute import compute
    from tm1.data_types.compute_config import ComputeConfig
    from tm1.run_control.module_ports import RunControl

    config = ComputeConfig()
    config.bc_A.in_w = config.bc_A.out_w = .01
    config.bc_A.in_ctr = 2.
    polls = []

    def cancel():
        polls.append(True)
        return len(polls) == 2

    with pytest.raises(ValueError, match='pipe_in_out_of_domain'):
        compute(config, control=RunControl(cancel_check=cancel))
    assert len(polls) == 1
