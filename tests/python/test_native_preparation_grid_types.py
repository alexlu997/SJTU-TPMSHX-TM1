"""Keep original scalar arithmetic across the complete typed 2D grid boundary."""

from copy import deepcopy
from dataclasses import asdict
import dis
import warnings
import numpy as np
import pytest
from tests.python import test_native_prepare_adapter as adapter

from sjtu_tpmshx.data_types.compute_config import (
    ComputeConfig, ExtrapPolicy, GeometryConfig, PartialBCConfig, SolverConfig,
)
from tests.python import native_preparation_abi
from tests.python.solver_tm1.test_prepared_zoned_thermal_2d import _config


@pytest.fixture(autouse=True)
def clear_reference_caches():
    from tests.python.property_reference import compute
    from sjtu_tpmshx.physical_models.tpms_geometry import compute_geometry
    compute.cache_clear()
    compute_geometry.cache_clear()
    yield
    compute.cache_clear()
    compute_geometry.cache_clear()


def _ci_config(integer=np.int8, floating=np.float16):
    return ComputeConfig(
        geometry=GeometryConfig(L_dom_m=integer(1), H_dom_m=np.int16(2)),
        solver=SolverConfig(Nx=12, Ny=12, Nz=1), extrap=ExtrapPolicy(allow=True),
        bc_A=PartialBCConfig(dir=0, in_ctr=integer(1), out_ctr=integer(1),
            in_w=floating(.2), out_w=floating(.2), uniform_inlet_2d=True),
        bc_B=PartialBCConfig(dir=3, in_ctr=.5, out_ctr=.5,
            in_w=1., out_w=1., uniform_inlet_2d=True))


def _configuration(scope):
    if scope == 'uniform':
        config = native_preparation_abi._configuration_mass_flow(pair=('air', 'air'))
    elif scope == 'continuous':
        config = native_preparation_abi._configuration_continuous(pair=('air', 'air'), nx=4, ny=3, mirror=False, order=2)
    elif scope == 'zones':
        config = _config('grid')
    else:
        config = native_preparation_abi._configuration_sigmoid()
    config.geometry.L_dom_m, config.geometry.H_dom_m = np.float16(.125), np.float32(.0625)
    config.geometry.Lz_m = .042
    config.solver.Nx = config.solver.Ny = 16
    for side, direction in zip('AB', (0, 1)):
        setattr(config, 'bc_' + side, PartialBCConfig(dir=direction,
            in_ctr=np.float16(.03125), in_w=np.float32(.03125),
            out_ctr=np.float32(.03125), out_w=np.float16(.03125),
            uniform_inlet_2d=side == 'A'))
    return config


def test_public_prepare_restores_original_integer_half_width_contract(monkeypatch):
    config = _ci_config()
    before = deepcopy(asdict(config))
    expected = adapter._capture(monkeypatch, adapter.reference, 'full', config)
    actual = adapter._capture(monkeypatch, adapter.api, 'full', config)
    adapter._same(actual, expected)
    adapter._same(asdict(config), before, 'unchanged input')
    assert actual[0].grid['dy'][0] == .179931640625


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('field', ['L_dom_m', 'in_ctr'])
@pytest.mark.parametrize('earlier', ['none', 'geometry-object', 'water-state', 'extrapolation'])
@pytest.mark.parametrize('fixed', [False, True])
def test_host_grid_object_error_keeps_original_order(monkeypatch, spatial, field, earlier, fixed):
    config = (native_preparation_abi._configuration_continuous if spatial else native_preparation_abi._configuration_mass_flow)(pair=('air', 'water'))
    if field == 'L_dom_m':
        config.geometry.L_dom_m = np.asarray(config.geometry.L_dom_m)
    else:
        config.bc_A.in_ctr = np.asarray(.02)
        config.bc_A.out_ctr = .02
        config.bc_A.in_w = config.bc_A.out_w = .02
    if earlier == 'geometry-object':
        config.geometry.L_cell_mm = np.asarray(7.)
    elif earlier == 'water-state':
        config.fluid_B.T_in_K = 450.
    elif earlier == 'extrapolation':
        config.fluid_A.u_mps = 500.
    targets = (.003, .03) if fixed else None
    expected = adapter._failure(monkeypatch, adapter.reference, config, targets)
    actual = adapter._failure(monkeypatch, adapter.api, config, targets)
    assert actual == expected


@pytest.mark.parametrize('spatial', [False, True])
def test_full_face_does_not_consume_replaced_port_objects(monkeypatch, spatial):
    config = (native_preparation_abi._configuration_continuous if spatial else native_preparation_abi._configuration_mass_flow)(pair=('air', 'water'))
    for side in 'AB':
        port = getattr(config, 'bc_' + side)
        port.in_ctr = port.out_ctr = np.asarray(0.)
        port.in_w = port.out_w = np.asarray(0.)
    adapter._same(adapter._capture(monkeypatch, adapter.api, 'full', config),
                  adapter._capture(monkeypatch, adapter.reference, 'full', config))


@pytest.mark.parametrize('scope,error', [
    ('integer', 'prepared y grid does not cover the physical domain'),
    ('uniform', None), ('continuous', None)])
def test_public_typed_case_keeps_saved_grid_and_ports(monkeypatch, tmp_path, scope, error):
    from sjtu_tpmshx.file_io.case_io import load_case, save_case
    from sjtu_tpmshx.solvers.backends.prepared_2d import build_execution_inputs

    config = _ci_config() if scope == 'integer' else _configuration(scope)
    case = adapter._capture(monkeypatch, adapter.api, 'full', config)[0]
    reference = adapter._capture(monkeypatch, adapter.reference, 'full', config)[0]
    adapter._same(case, reference)
    save_case(case, tmp_path / 'case.h5')
    save_case(reference, tmp_path / 'reference.h5')
    restored = load_case(tmp_path / 'case.h5')
    expected_case = load_case(tmp_path / 'reference.h5')
    adapter._same(restored.grid, case.grid)
    adapter._same(restored.design_fields, case.design_fields)
    adapter._same(restored, expected_case)
    if error is not None:
        for saved in (expected_case, restored):
            with pytest.raises(ValueError) as failure:
                build_execution_inputs(saved, copy_design=False)
            assert str(failure.value) == error
        return
    actual, _ = build_execution_inputs(restored, copy_design=False)
    expected, _ = build_execution_inputs(expected_case, copy_design=False)
    for name in ('cfgA', 'cfgB', 'boundary_openings', 'flow_inputs'):
        adapter._same(actual[name], expected[name])


def _axis_config(count, axis):
    config = native_preparation_abi._configuration_continuous(pair=('air', 'air'), nx=count if axis == 'x' else 1,
                               ny=count if axis == 'y' else 1, mirror=False, order=1)
    config.geometry.L_dom_m, config.geometry.H_dom_m = np.float16(.125), np.float16(.0625)
    config.zones.config['x_decision'] = [7.] * count + [.6] * count
    return config


def _axis_observation(monkeypatch, module, config, operation, *, filter_module=False):
    from sjtu_tpmshx.run_control.logutil import get_logger
    from tests.python.test_native_prepare_adapter import _property_compute
    compute = _property_compute(module)
    from sjtu_tpmshx.physical_models.tpms_geometry import compute_geometry
    compute.cache_clear()
    compute_geometry.cache_clear()
    events = []
    targets = (.003, .004)
    result, failure = None, None
    with monkeypatch.context() as patch, warnings.catch_warnings():
        warnings.simplefilter('always')
        if filter_module:
            warnings.filterwarnings('error', module=r'^numpy\._core\.function_base$')
        patch.setattr(warnings, 'showwarning', lambda message, category, filename, lineno, *args, **kwargs:
                      events.append((category.__name__, str(message), filename, lineno)))
        patch.setattr(get_logger('sjtu_tpmshx.preprocess.two_d.preparation'), 'info',
                      lambda message: events.append(('log', message)))
        try:
            if operation == 'capacity':
                result = module.prepare_inlet_mass_capacities(config)
            elif operation == 'resolve':
                result = module.resolve_fixed_mass_flow_config(config,
                    mass_flow_A_kg_s=targets[0], mass_flow_B_kg_s=targets[1])
            elif operation == 'fixed':
                result = module.prepare_fixed_mass_flow_case(config, case_id='axis-error',
                    mass_flow_A_kg_s=targets[0], mass_flow_B_kg_s=targets[1])
            else:
                result = module.prepare_case(config, case_id='axis-error')
        except Exception as caught:
            failure = type(caught), str(caught)
    return result, failure, events


def _axis_failure(monkeypatch, module, config, operation, *, filter_module=False):
    _result, failure, events = _axis_observation(
        monkeypatch, module, config, operation, filter_module=filter_module)
    assert failure is not None
    return *failure, events


@pytest.mark.parametrize('count', [4097, 65521])
@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('policy', ['warn', 'raise'])
@pytest.mark.parametrize('operation', ['full', 'capacity', 'resolve', 'fixed'])
def test_control_axis_failure_keeps_host_events(monkeypatch, count, axis, policy, operation):
    config = _axis_config(count, axis)
    with np.errstate(over=policy, invalid=policy):
        expected = _axis_failure(monkeypatch, adapter.reference, config, operation)
        actual = _axis_failure(monkeypatch, adapter.api, config, operation)
    assert actual == expected


@pytest.mark.parametrize('operation', ['full', 'capacity', 'resolve', 'fixed'])
def test_control_axis_keeps_original_warning_module_filter(monkeypatch, operation):
    config = _axis_config(65521, 'x')
    with np.errstate(over='warn', invalid='warn'):
        expected = _axis_failure(monkeypatch, adapter.reference, config, operation, filter_module=True)
        actual = _axis_failure(monkeypatch, adapter.api, config, operation, filter_module=True)
    assert expected[0] is RuntimeWarning
    assert actual == expected


@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('operation', ['full', 'capacity', 'resolve', 'fixed'])
def test_control_axis_error_precedes_only_later_host_grid_error(monkeypatch, axis, operation):
    config = _axis_config(4097, axis)
    name = 'H_dom_m' if axis == 'x' else 'L_dom_m'
    setattr(config.geometry, name, np.asarray(getattr(config.geometry, name)))
    assert _axis_failure(monkeypatch, adapter.api, config, operation) == _axis_failure(
        monkeypatch, adapter.reference, config, operation)


def _underflow_config(axis, sampling, *, one_cell=False):
    count = 1 if sampling else 2
    config = native_preparation_abi._configuration_continuous(pair=('air', 'air'), nx=count if axis == 'x' else 1,
                               ny=count if axis == 'y' else 1, mirror=False, order=1)
    config.geometry.L_dom_m, config.geometry.H_dom_m = np.float16(.125), np.float16(.0625)
    setattr(config.geometry, 'L_dom_m' if axis == 'x' else 'H_dom_m',
            np.float16(2. ** (-24 if sampling else -15)))
    config.solver.Nx = config.solver.Ny = 4
    setattr(config.solver, 'Nx' if axis == 'x' else 'Ny', 1 if one_cell else 4 if sampling else 3)
    config.flags.port_wall_refine = False
    config.bc_A = PartialBCConfig(dir=0 if axis == 'x' else 2)
    config.bc_B = PartialBCConfig(dir=0 if axis == 'x' else 2)
    return config


def _nominal_divide_sources():
    from tests.python import preparation_case_reference
    from sjtu_tpmshx.preprocess.two_d import preparation

    function = preparation_case_reference._parse_geometry_inputs_cfg
    original = [(function.__code__.co_filename, item.positions.lineno)
                for item in dis.get_instructions(function)
                if item.opname == 'BINARY_OP' and item.argrepr == '/']
    function = preparation._nominal_grid_warning
    current = [(function.__code__.co_filename, item.positions.lineno)
               for item in dis.get_instructions(function)
               if item.opname == 'LOAD_ATTR' and item.argval == 'warn']
    assert len(original) == len(current) == 2
    return dict(zip(original, current))


def _normalize_nominal_sources(events):
    sources = _nominal_divide_sources()
    return [(*event[:2], *sources.get(event[2:], event[2:])) if len(event) == 4 else event
            for event in events]


@pytest.mark.parametrize('sampling', [False, True], ids=['nominal-quotient', 'requested-sampling'])
@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('policy', ['warn', 'raise'])
@pytest.mark.parametrize('operation', ['full', 'capacity', 'resolve', 'fixed'])
def test_half_domain_underflow_keeps_host_failure_order(monkeypatch, sampling, axis, policy, operation):
    config = _underflow_config(axis, sampling)
    with np.errstate(under=policy):
        error, message, events = _axis_failure(monkeypatch, adapter.reference, config, operation)
        actual = _axis_failure(monkeypatch, adapter.api, config, operation)
    expected_events = _normalize_nominal_sources(events)
    assert actual == (error, message, expected_events)
    if policy == 'raise':
        assert error is FloatingPointError and message == 'underflow encountered in scalar divide'
    else:
        assert error is ValueError
        floating = [event for event in expected_events if event[0] == 'RuntimeWarning']
        assert floating[0] == ('RuntimeWarning', 'underflow encountered in scalar divide',
                              *tuple(_nominal_divide_sources().values())[axis == 'y'])
        if operation == 'full':
            assert len(floating) == (3 if sampling else 1)
            assert message == ('sampling axes must be finite, increasing and inside the field domain'
                               if sampling else 'cell widths must be finite, positive and cover the field domain')


@pytest.mark.parametrize('axis', ['x', 'y'])
def test_one_cell_half_domain_keeps_success_and_midpoint_sources(monkeypatch, axis):
    config = _underflow_config(axis, True, one_cell=True)
    with np.errstate(under='warn'):
        expected = _axis_observation(monkeypatch, adapter.reference, config, 'full')
        actual = _axis_observation(monkeypatch, adapter.api, config, 'full')
    assert expected[1] is None
    adapter._same(actual, expected)
    floating = [event for event in expected[2] if event[0] == 'RuntimeWarning']
    assert len(floating) == 4
    assert all(event[1] == 'underflow encountered in scalar divide' for event in floating)
    assert not any(event[2:] in _nominal_divide_sources() for event in floating)


@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('policy', ['warn', 'raise'])
def test_uniform_half_domain_keeps_one_nominal_event(monkeypatch, axis, policy):
    config = _underflow_config(axis, False)
    config.zones.enabled = False
    with np.errstate(under=policy):
        expected, failure, events = _axis_observation(monkeypatch, adapter.reference, config, 'full')
        actual = _axis_observation(monkeypatch, adapter.api, config, 'full')
    adapter._same(actual, (expected, failure, _normalize_nominal_sources(events)))
    if policy == 'warn':
        assert failure is None
        assert len([event for event in events if event[0] == 'RuntimeWarning']) == 1
    else:
        assert failure == (FloatingPointError, 'underflow encountered in scalar divide')


