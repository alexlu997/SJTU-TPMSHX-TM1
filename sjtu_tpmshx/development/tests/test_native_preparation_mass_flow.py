"""Compare independent native inlet-flow operations with the public APIs."""
import ctypes as ct
from contextlib import contextmanager
from dataclasses import asdict, replace
from itertools import product
import os
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import test_native_preparation_case as v1
from sjtu_tpmshx.development.tests import test_native_preparation_fluids as v2
from sjtu_tpmshx.preprocess import api
from sjtu_tpmshx.shared.domain.run_warnings import (
    range_observations, warning_messages, warning_scope,
)
from sjtu_tpmshx.shared.models import _native_flow

_U, _S, _D, _struct = v1._U, v1._S, v1._D, v1._structure
_Input = _struct('FlowInput', [('abi_version', _U), ('struct_size', _S),
    ('values', v2._Input), ('physical_depth_kind', v2._Kind), ('target_kinds', v2._Kind * 2),
    ('have_explicit_targets', _U), ('explicit_targets_kg_s', _D * 2)])
_Evidence = _struct('FlowEvidence', [('ranges', ct.POINTER(v1._Range)), ('range_count', _S),
    ('range_bounds_list', ct.POINTER(_U)), ('warnings', ct.POINTER(v1._Text)), ('warning_count', _S),
    ('events', ct.POINTER(v1._Event)), ('event_count', _S)])
_Flow = _struct('FlowResult', [('abi_version', _U), ('struct_size', _S), ('input', v2._Input),
    ('have_capacities', _U), ('capacities', _native_flow._Scalar * 2), ('speeds', _native_flow._Scalar * 2),
    ('evidence', _Evidence), ('owner', ct.c_void_p)])
_Result = _struct('FlowCase', [('abi_version', _U), ('struct_size', _S),
    ('prepared', v2._Result), ('flow', _Flow), ('owner', ct.c_void_p)])


@pytest.fixture(scope='module')
def native():
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY', v1._library_path()))
    for name, result in [('prepare_inlet_mass_capacities', _Flow), ('resolve_inlet_flow', _Flow),
                         ('prepare_flow_case', _Result)]:
        function = getattr(library, 'tpmshx_' + name + '_2d_v3')
        function.argtypes = [ct.POINTER(_Input), ct.POINTER(v1._Options), ct.POINTER(v1._Callbacks),
            ct.POINTER(result), ct.POINTER(v2._Failure), ct.POINTER(ct.c_char), _S]
        function.restype = ct.c_int
    library.tpmshx_preparation_flow_2d_release_v3.argtypes = [ct.POINTER(_Flow)]
    library.tpmshx_preparation_flow_case_2d_release_v3.argtypes = [ct.POINTER(_Result)]
    return library


def _kind(value):
    scalar = _native_flow._scalar(value)
    return v2._Kind(scalar.precision, scalar.strong, int(bool(scalar.strong)))


def _input(config, targets=None):
    source = v2._input(config)
    result = _Input(3, ct.sizeof(_Input), source)
    result._source = source
    result.physical_depth_kind = _kind(config.geometry.Lz_m if config.geometry.Lz_m is not None else 0.)
    result.have_explicit_targets = targets is not None
    for i, side in enumerate('AB'):
        value = targets[i] if targets is not None else getattr(config, 'fluid_' + side).mass_flow_kg_s
        result.target_kinds[i] = _kind(value if value is not None else 0.)
        if targets is not None:
            result.explicit_targets_kg_s[i] = value
    return result


def _call(native, operation, config, targets=None):
    source = _input(config, targets)
    result_type = _Result if operation == 'prepare_flow_case' else _Flow
    result, failure = result_type(3, ct.sizeof(result_type)), v2._Failure(2, ct.sizeof(v2._Failure))
    options = v1._Options(1, ct.sizeof(v1._Options), 0, config.extrap.allow, 0.)
    events, error = [], ct.create_string_buffer(4096)
    def event(_context, pointer):
        item = pointer.contents
        events.append((item.kind, v1._text(item.logger), v1._text(item.message), item.floating_event))
        return 0
    callback = v1._EventFunction(event)
    callbacks = v1._Callbacks(1, ct.sizeof(v1._Callbacks), callback, None)
    before = bytes(source)
    status = getattr(native, 'tpmshx_' + operation + '_2d_v3')(
        ct.byref(source), ct.byref(options), ct.byref(callbacks), ct.byref(result),
        ct.byref(failure), error, len(error))
    assert bytes(source) == before
    return status, result, failure, error.value.decode(), events, source


def _release(native, result):
    name = 'tpmshx_preparation_flow_case_2d_release_v3' if isinstance(result, _Result) else 'tpmshx_preparation_flow_2d_release_v3'
    getattr(native, name)(ct.byref(result))


def _reference(monkeypatch, operation, config, targets=None):
    from sjtu_tpmshx.preprocess.two_d import preparation
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    compute.cache_clear(); compute_geometry.cache_clear()
    state = {'records': {'preliminary': {}, 'final': {}}, 'events': {'preliminary': [], 'final': []},
             'phase': 'preliminary', 'resolved': config}
    @contextmanager
    def final_scope(initial):
        state['phase'] = 'final'
        try:
            with warning_scope(initial) as records:
                yield records
        finally:
            state['records']['final'].update(records)
            state['phase'] = 'preliminary'
    original = preparation._prepare_case
    def final_prepare(resolved, *args, **kwargs):
        state['resolved'] = resolved
        return original(resolved, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.delenv('TPMSHX_CHI_S', raising=False)
        patch.delenv('TPMSHX_ALLOW_EXTRAP', raising=False)
        patch.setattr(api, 'warning_scope', final_scope)
        patch.setattr(preparation, '_prepare_case', final_prepare)
        patch.setattr(preparation._log, 'info', lambda message: state['events'][state['phase']].append(
            (0, preparation._log.name, message, 0)))
        with warnings.catch_warnings():
            warnings.simplefilter('always')
            patch.setattr(warnings, 'showwarning', lambda message, *args, **kwargs:
                state['events'][state['phase']].append((1, '', str(message), 0)))
            with warning_scope({}) as preliminary:
                if operation == 'prepare_inlet_mass_capacities':
                    expected = api.prepare_inlet_mass_capacities(config)
                elif operation == 'resolve_inlet_flow':
                    expected = (api.resolve_inlet_flow_config(config) if targets is None else
                        api.resolve_fixed_mass_flow_config(config, mass_flow_A_kg_s=targets[0], mass_flow_B_kg_s=targets[1]))
                    state['resolved'] = expected
                else:
                    expected = (api.prepare_case(config, case_id='native-mass-reference') if targets is None else
                        api.prepare_fixed_mass_flow_case(config, mass_flow_A_kg_s=targets[0], mass_flow_B_kg_s=targets[1],
                                                        case_id='native-mass-reference'))
            state['records']['preliminary'].update(preliminary)
    return expected, state


def _events(evidence):
    return [(item.kind, v1._text(item.logger), v1._text(item.message), item.floating_event)
            for item in evidence.events[:evidence.event_count]]


def _flow_evidence(actual, state):
    records = state['records']['preliminary']
    for last in (False, True):
        rows = []
        for i in range(actual.range_count):
            row = v1._range(actual.ranges[i], last=last)
            if actual.range_bounds_list[i]:
                row['bounds'] = list(row['bounds'])
            rows.append(row)
        assert rows == range_observations(records, last=last)
    assert [v1._text(item) for item in actual.warnings[:actual.warning_count]] == list(warning_messages(records))
    assert _events(actual) == state['events']['preliminary']


def _scalar(actual, expected):
    v1._same(actual.value, expected, 'typed scalar')
    kind = _native_flow._scalar(expected)
    assert (actual.precision, actual.strong) == (kind.precision, kind.strong)


def _resolved(actual, expected):
    for i, side in enumerate('AB'):
        fluid = getattr(expected, 'fluid_' + side)
        inlet = actual.input.values.sides[i]
        v1._same(inlet.velocity_m_s, fluid.u_mps, side + ' resolved speed')
        assert bool(inlet.have_mass_flow) == (fluid.mass_flow_kg_s is not None)
        if inlet.have_mass_flow:
            v1._same(inlet.mass_flow_kg_s, fluid.mass_flow_kg_s, side + ' stored target')
        assert v1._struct_values(actual.input.kinds.sides[i].velocity) == v1._struct_values(v2._kind(fluid.u_mps))


def _configuration(topology='Gyroid', pair=('air', 'water'), mode='cfd_smooth'):
    config = v2._configuration(topology, pair, mode)
    config.geometry.Lz_m = .042
    return config


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('pair', list(product(v2._FLUIDS, repeat=2)))
@pytest.mark.parametrize('mode', ['cfd_smooth', 'experimental'])
def test_native_explicit_mass_preparation(native, monkeypatch, topology, pair, mode):
    config = _configuration(topology, pair, mode)
    capacities, capacity_state = _reference(monkeypatch, 'prepare_inlet_mass_capacities', config)
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    before = asdict(config)
    status, query, failure, error, live, _ = _call(native, 'prepare_inlet_mass_capacities', config)
    assert status == 0, error
    try:
        for i, side in enumerate('AB'):
            _scalar(query.capacities[i], capacities[side])
        _flow_evidence(query.evidence, capacity_state)
        assert live == capacity_state['events']['preliminary']
    finally:
        _release(native, query)
    stale = replace(config, fluid_A=replace(config.fluid_A, u_mps=-99., mass_flow_kg_s=.9),
                    fluid_B=replace(config.fluid_B, u_mps=-88., mass_flow_kg_s=.8))
    resolved, resolve_state = _reference(monkeypatch, 'resolve_inlet_flow', stale, targets)
    status, query, failure, error, live, _ = _call(native, 'resolve_inlet_flow', stale, targets)
    assert status == 0, error
    try:
        assert query.have_capacities
        _resolved(query, resolved); _flow_evidence(query.evidence, resolve_state)
        assert live == resolve_state['events']['preliminary']
    finally:
        _release(native, query)
    expected, state = _reference(monkeypatch, 'prepare_flow_case', stale, targets)
    status, result, failure, error, live, _ = _call(native, 'prepare_flow_case', stale, targets)
    assert status == 0, error
    try:
        assert not failure.kind and result.owner and not result.prepared.values.owner and not result.flow.owner
        _resolved(result.flow, state['resolved']); _flow_evidence(result.flow.evidence, state)
        v2._check_values(result.prepared, expected, state['resolved'])
        final_events = state['events']['final']
        v2._check_evidence(result.prepared, expected, state['records']['final'], final_events,
                           _events(result.prepared.values), state['resolved'])
        assert live == state['events']['preliminary'] + final_events
        assert 'inlet_inputs' not in expected.parameters
    finally:
        _release(native, result)
    assert asdict(config) == before


@pytest.mark.parametrize('sides', [('A',), ('B',), ('A', 'B')])
@pytest.mark.parametrize('directions', [(0, 2), (1, 3), (2, 1), (3, 0)])
def test_native_configured_targets_and_partial_ports(native, monkeypatch, sides, directions):
    from sjtu_tpmshx.shared.domain.compute_config import PartialBCConfig
    config = _configuration()
    config.solver.Nx = config.solver.Ny = 12
    config.bc_A = PartialBCConfig(dir=directions[0], in_ctr=.021 if directions[0] < 2 else .091,
        in_w=.021 if directions[0] < 2 else .091, out_ctr=.021 if directions[0] < 2 else .091,
        out_w=.03 if directions[0] < 2 else .12)
    config.bc_B = PartialBCConfig(dir=directions[1], in_ctr=.021 if directions[1] < 2 else .091,
        in_w=.03 if directions[1] < 2 else .12, out_ctr=.021 if directions[1] < 2 else .091,
        out_w=.021 if directions[1] < 2 else .091, uniform_inlet_2d=True)
    capacities, _ = _reference(monkeypatch, 'prepare_inlet_mass_capacities', config)
    for side in sides:
        fluid = getattr(config, 'fluid_' + side)
        setattr(config, 'fluid_' + side, replace(fluid, u_mps=-99., mass_flow_kg_s=float(capacities[side] * fluid.u_mps)))
    expected, state = _reference(monkeypatch, 'prepare_flow_case', config)
    status, result, failure, error, live, _ = _call(native, 'prepare_flow_case', config)
    assert status == 0, error
    try:
        _resolved(result.flow, state['resolved']); _flow_evidence(result.flow.evidence, state)
        v2._check_values(result.prepared, expected, state['resolved'])
        v2._check_evidence(result.prepared, expected, state['records']['final'], state['events']['final'],
                           _events(result.prepared.values), state['resolved'])
        assert live == state['events']['preliminary'] + state['events']['final']
        assert set(expected.parameters['inlet_inputs']) == {'A', 'B'}
    finally:
        _release(native, result)


@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64, np.int16])
@pytest.mark.parametrize('array', [False, True])
def test_native_typed_depth_and_explicit_targets(native, monkeypatch, dtype, array):
    config = _configuration()
    depth = dtype(1) if dtype is np.int16 else dtype(.042)
    config.geometry.Lz_m = np.asarray(depth) if array else depth
    targets = tuple((np.asarray(dtype(value)) if array else dtype(value))
                    for value in ((1, 2) if dtype is np.int16 else (.003, .03)))
    expected, state = _reference(monkeypatch, 'resolve_inlet_flow', config, targets)
    status, result, failure, error, live, _ = _call(native, 'resolve_inlet_flow', config, targets)
    assert status == 0, error
    try:
        _resolved(result, expected); _flow_evidence(result.evidence, state)
        capacities, _ = _reference(monkeypatch, 'prepare_inlet_mass_capacities', config)
        for i, side in enumerate('AB'):
            _scalar(result.capacities[i], capacities[side])
            _scalar(result.speeds[i], getattr(expected, 'fluid_' + side).u_mps)
        assert live == state['events']['preliminary']
    finally:
        _release(native, result)


def test_native_capacity_ignores_obsolete_speed_and_nu(native, monkeypatch):
    config = _configuration()
    config.fluid_A.u_mps, config.fluid_B.u_mps = -99., float('nan')
    config.extrap.allow = False
    expected, state = _reference(monkeypatch, 'prepare_inlet_mass_capacities', config)
    status, result, failure, error, live, _ = _call(native, 'prepare_inlet_mass_capacities', config)
    assert status == 0, error
    try:
        for i, side in enumerate('AB'):
            _scalar(result.capacities[i], expected[side])
        assert all(v1._text(result.evidence.ranges[i].source[0]) != 'nu' for i in range(result.evidence.range_count))
        _flow_evidence(result.evidence, state)
    finally:
        _release(native, result)


def test_native_resolve_without_targets_preserves_unvalidated_input(native, monkeypatch):
    config = _configuration()
    config.fluid_A.T_in_K = -1.
    expected, state = _reference(monkeypatch, 'resolve_inlet_flow', config)
    assert expected is config
    status, result, failure, error, live, source = _call(native, 'resolve_inlet_flow', config)
    assert status == 0, error
    try:
        assert not result.have_capacities and not live
        assert v1._struct_values(result.input.values) == v1._struct_values(source.values.values)
        _flow_evidence(result.evidence, state)
    finally:
        _release(native, result)


@pytest.mark.parametrize('case', ['depth-target', 'target-a', 'target-b', 'configured-target-geometry',
    'static-temperature', 'delta', 'water-before-depth', 'resolved-experiment', 'co2-phase'])
@pytest.mark.parametrize('operation', ['resolve_inlet_flow', 'prepare_flow_case'])
def test_native_mass_first_error(native, monkeypatch, case, operation):
    config, targets = _configuration(), (.003, .03)
    if case == 'depth-target':
        config.geometry.Lz_m, targets = None, (-1., -2.)
    elif case == 'target-a':
        targets = (float('nan'), 0.)
    elif case == 'target-b':
        targets = (.003, -1.)
    elif case == 'configured-target-geometry':
        targets = None
        config.fluid_A.mass_flow_kg_s = -1.
        config.geometry.L_cell_mm = -1.
    elif case == 'static-temperature':
        config.fluid_B.T_in_K = float('nan')
    elif case == 'delta':
        config.geometry.delta_levelset = .1
    elif case == 'water-before-depth':
        config.geometry.Lz_m = None
        config.fluid_B.T_in_K = 500.
        operation = 'prepare_inlet_mass_capacities'
        targets = None
    elif case == 'resolved-experiment':
        config.df_mode, targets = 'experimental', (1e-12, .03)
    elif case == 'co2-phase':
        config.fluid_A.type = 'co2'
        config.fluid_A.T_in_K, config.fluid_A.P_in_Pa = 304.1282, 7377298.373
    with pytest.raises(Exception) as reference:
        _reference(monkeypatch, operation, config, targets)
    status, result, failure, error, live, _ = _call(native, operation, config, targets)
    assert status != 0
    assert error == str(reference.value)
    assert not result.owner
    _release(native, result)
