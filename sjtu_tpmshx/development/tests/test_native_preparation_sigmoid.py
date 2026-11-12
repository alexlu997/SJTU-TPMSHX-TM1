"""Compare raw sigmoid preparation with the retained Python stage and voxel scans."""
import ctypes as ct
from copy import deepcopy
from dataclasses import asdict, replace
from itertools import product
import os
from types import SimpleNamespace
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import geometry_reference, sigmoid_reference
from sjtu_tpmshx.development.tests import test_native_preparation_case as v1
from sjtu_tpmshx.development.tests import test_native_preparation_fluids as v2
from sjtu_tpmshx.development.tests import test_native_preparation_mass_flow as v3
from sjtu_tpmshx.development.tests import test_native_preparation_zones as v5
from sjtu_tpmshx.development.tests.test_native_preparation_continuous import _host_events

_U, _S, _D, _struct = v1._U, v1._S, v1._D, v1._structure
_LUTView = _struct('SigmoidLUTView', [(name, v1._Array) for name in
    ('cell_mm', 'wall_mm', 'porosity', 'area_density_per_m')] +
    [('porosity_fast', _U), ('area_fast', _U)])
_LUT = _struct('SigmoidLUT', [('abi_version', _U), ('struct_size', _S),
    ('values', _LUTView), ('owner', ct.c_void_p)])
_Controls = _struct('SigmoidControls', [('decision_mm', v1._Array),
    ('inlet_transition', v5._GridScalar), ('outlet_transition', v5._GridScalar)])
_Input = _struct('SigmoidInput', [('abi_version', _U), ('struct_size', _S),
    ('values', v5._Input), ('controls', _Controls), ('lut', _LUTView)])
_Result = _struct('SigmoidResult', [('abi_version', _U), ('struct_size', _S),
    ('values', v5._Result), ('controls', _Controls), ('owner', ct.c_void_p)])


@pytest.fixture(scope='module')
def native():
    path = os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY') or v1._library_path()
    library = ct.CDLL(path)
    library.tpmshx_prepare_sigmoid_case_2d_v6.argtypes = [ct.POINTER(_Input),
        ct.POINTER(v1._Options), ct.POINTER(v1._Callbacks), ct.POINTER(_Result),
        ct.POINTER(v2._Failure), ct.POINTER(ct.c_char), _S]
    library.tpmshx_prepare_sigmoid_case_2d_v6.restype = ct.c_int
    library.tpmshx_preparation_sigmoid_lut_create_v6.argtypes = [_U, _S, _S, _S,
        ct.POINTER(_LUT), ct.POINTER(ct.c_char), _S]
    library.tpmshx_preparation_sigmoid_lut_create_v6.restype = ct.c_int
    for name, value in [('lut', _LUT), ('case_2d', _Result)]:
        function = getattr(library, 'tpmshx_preparation_sigmoid_' + name + '_release_v6')
        function.argtypes = [ct.POINTER(value)]
        function.restype = None
    library.tpmshx_preparation_case_abi_version_v6.restype = _U
    assert library.tpmshx_preparation_case_abi_version_v6() == 6
    return library


@pytest.fixture(autouse=True)
def clear_reference_caches():
    from sjtu_tpmshx.development.tests.property_reference import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    compute.cache_clear()
    compute_geometry.cache_clear()
    yield
    compute.cache_clear()
    compute_geometry.cache_clear()
    geometry_reference._phi_grid.cache_clear()


def _configuration(topology='Gyroid', *, constant=False):
    config = v5._config('grid')
    config.geometry.tpms = topology
    config.zones.config.tpms_type = topology
    config.zones.grid['tpms_type'] = topology
    lengths = np.full(18, 7.) if constant else np.linspace(5., 7.8, 18)
    walls = np.full(18, .4) if constant else np.linspace(.32, .58, 18)
    config.zones.pareto_x_decision = np.column_stack((lengths, walls)).ravel().tolist()
    return config


def _raw_tables(topology, cells, walls, resolution):
    """Scan the frozen voxel field; no production geometry supplies these values."""
    phi = geometry_reference._phi_grid(topology, resolution)
    epsilon, area = (np.empty((len(cells), len(walls))) for _ in range(2))
    for i, cell in enumerate(cells):
        for j, wall in enumerate(walls):
            threshold = geometry_reference._C_from_tL(topology, wall / cell)
            epsilon[i, j] = geometry_reference._eps_from_C(phi, threshold)
            area[i, j] = geometry_reference._A0_from_C(phi, threshold, cell / 1000., resolution)
    return epsilon, area


def _array(values):
    return v1._Array(values.ctypes.data_as(ct.POINTER(_D)), values.size)


def _table(topology='Gyroid', *, shape=(2, 2), styles=('double', 'double')):
    cells, walls = np.linspace(4., 8., shape[0]), np.linspace(.3, .6, shape[1])
    epsilon, area = _raw_tables(topology, cells, walls, 16)
    tables = []
    for values, style in zip((epsilon, area), styles):
        if style == 'narrow':
            values = values.astype(np.float32)
        elif style == 'byteorder':
            values = values.astype('>f8')
        elif style == 'readonly':
            values.flags.writeable = False
        tables.append(values)
    oracle = sigmoid_reference.GeometryLUT(cells, walls, *tables)
    return _table_from_oracle(oracle)


def _table_from_oracle(oracle):
    """Capture normalized references and each RGI arithmetic mode before packing."""
    from sjtu_tpmshx.shared.models import _native_lut
    cells, walls = oracle.epsilon.grid
    values = [cells, walls, oracle.epsilon.values, oracle.area.values]
    packed = [np.array(value, dtype=np.float64, order='C', copy=True) for value in values]
    view = _LUTView(*(_array(value) for value in packed), *oracle.modes())
    runtime = _native_lut.LUT(*values)
    def query(length, wall):
        actual = tuple(value.reshape(length.shape) for value in runtime.query(length, wall))
        for value, expected in zip(actual, oracle.query(length, wall)):
            # Keep the existing independent LUT tolerance and exact stage comparison.
            np.testing.assert_allclose(value, expected, rtol=3e-14, atol=3e-14, equal_nan=True)
        return actual
    return SimpleNamespace(oracle=oracle, reference=SimpleNamespace(query=query), arrays=packed, view=view)


def _scalar(value):
    kind = v3._kind(value)
    return v5._GridScalar(float(value), kind.precision, kind.strong)


def _input(config, table):
    base = v5._input(config)
    decision = np.asarray(config.zones.pareto_x_decision, dtype=np.float64).copy()
    controls = _Controls(_array(decision), _scalar(config.zones.pareto_y_trans_inlet),
                         _scalar(config.zones.pareto_y_trans_outlet))
    source = _Input(6, ct.sizeof(_Input), base, controls, table.view)
    source._base, source._decision, source._table = base, decision, table
    return source


def _call(native, config, table, *, chi=None, source=None, result=None, stop_event=None):
    source = _input(config, table) if source is None else source
    result = _Result(6, ct.sizeof(_Result)) if result is None else result
    failure, error = v2._Failure(2, ct.sizeof(v2._Failure)), ct.create_string_buffer(4096)
    options = v1._Options(1, ct.sizeof(v1._Options), chi is not None, config.extrap.allow,
                          chi if chi is not None else 0.)
    events = []
    def event(_context, pointer):
        item = pointer.contents
        events.append((item.kind, v1._text(item.logger), v1._text(item.message), item.floating_event))
        return int(stop_event is not None and len(events) == stop_event)
    callback = v1._EventFunction(event)
    callbacks = v1._Callbacks(1, ct.sizeof(v1._Callbacks), callback, None)
    borrowed = [source, source._base._regions, source._decision, *source._table.arrays,
                *source._base._buffers, *source._base._base._buffers]
    before = [bytes(value) for value in borrowed]
    status = native.tpmshx_prepare_sigmoid_case_2d_v6(ct.byref(source), ct.byref(options),
        ct.byref(callbacks), ct.byref(result), ct.byref(failure), error, len(error))
    assert [bytes(value) for value in borrowed] == before
    return status, result, failure, error.value.decode(), events, source


def _release(native, value):
    name = 'lut' if isinstance(value, _LUT) else 'case_2d'
    getattr(native, 'tpmshx_preparation_sigmoid_' + name + '_release_v6')(ct.byref(value))


def _reference(monkeypatch, config, table, *, chi=None):
    from sjtu_tpmshx.shared.models import sigmoid_field
    with monkeypatch.context() as patch:
        patch.setattr(sigmoid_field, 'get_geometry_lut', lambda *args, **kwargs: table.reference)
        return v3._reference(patch, 'prepare_flow_case', config, chi=chi)


def _snapshot_controls(actual, config):
    v1._same(v1._array(actual.decision_mm), config.zones.pareto_x_decision, 'saved controls')
    for name, key in [('inlet_transition', 'pareto_y_trans_inlet'),
                      ('outlet_transition', 'pareto_y_trans_outlet')]:
        value = getattr(config.zones, key)
        v3._scalar(getattr(actual, name), value)


def _check_values(result, expected, state, live, config, monkeypatch, *, chi=None):
    values = result.values
    assert result.owner and not values.owner and not values.prepared.values.owner
    assert (values.kind, values.axis, values.region_count) == (2, 1, 0)
    with monkeypatch.context() as patch:
        if chi is not None:
            patch.setenv('TPMSHX_CHI_S', str(chi))
        v2._check_values(values.prepared, expected, config)
    v2._check_evidence(values.prepared, expected, state['records']['final'],
        state['events']['final'], live, config, event_converter=_host_events)
    _snapshot_controls(result.controls, config)
    shape = expected.design_fields['L_field_m'].shape
    assert values.cell_count == int(np.prod(shape))
    v1._same(np.ctypeslib.as_array(values.zone_id, shape=(values.cell_count,)).reshape(shape),
             expected.design_fields['zone_id'], 'zone assignment')
    assert not np.any(expected.design_fields['zone_id'])
    for name, key in [('thermal_porosity', 'epsilon'), ('area_density_per_m', 'A_0'),
                      ('hydraulic_diameter_m', 'D_h')]:
        v1._same(v1._array(getattr(values, name)).reshape(shape),
                 expected.parameters['thermal_geometry']['fields'][key], 'thermal ' + key)
    v1._same(v1._array(values.design_area_density_per_m).reshape(shape),
             expected.design_fields['A_0_arr'], 'design area')
    for i, side in enumerate('AB'):
        v1._same(v1._array(values.fluid_conductivity[i]).reshape(shape),
                 expected.design_fields['K_ff' + side + '_arr'], side + ' fluid conductivity')
        v1._same(v1._array(values.volumetric_transfer[i]).reshape(shape),
                 expected.design_fields['h_v' + side + '_arr'], side + ' volumetric transfer')
    logs = [event for event in live if event[0] == 0 and 'Continuous Sigmoid field' in event[2]]
    assert len(logs) == 2
    assert logs[0][2].endswith(f'({config.solver.Nx}x{config.solver.Ny})')
    assert logs[1][2].endswith(f'({shape[0]}x{shape[1]})')
    assert expected.design_fields['axis'] == 'continuous'


def _check_independent_fields(expected, config):
    dx, dy = expected.grid['dx'], expected.grid['dy']
    xf = (np.cumsum(dx) - dx / 2.) / config.geometry.L_dom_m
    yf = (np.cumsum(dy) - dy / 2.) / config.geometry.H_dom_m
    XF, YF = np.meshgrid(xf, yf, indexing='ij')
    controls = np.asarray(config.zones.pareto_x_decision[:36]).reshape(2, 3, 3, 2)
    for i, (key, nominal, bounds) in enumerate([
            ('L_field_m', config.geometry.L_cell_mm, (4., 8.)),
            ('t_field_m', config.geometry.t_wall_mm, (.3, .6))]):
        field = sigmoid_reference.sigmoid_field_2d(XF, YF, controls[0, :, :, i],
            controls[1, :, :, i], nominal, config.zones.pareto_y_trans_inlet,
            config.zones.pareto_y_trans_outlet)
        if not config.extrap.allow:
            field = np.clip(field, *bounds)
        np.testing.assert_allclose(expected.design_fields[key], field * 1e-3,
                                   rtol=3e-15, atol=1e-18)


def _full(native, monkeypatch, config, table=None, *, chi=None):
    table = _table(config.geometry.tpms) if table is None else table
    before = deepcopy(asdict(config))
    expected, state = _reference(monkeypatch, config, table, chi=chi)
    status, result, failure, error, live, source = _call(native, config, table, chi=chi)
    assert status == 0, error
    try:
        assert not failure.kind
        _check_values(result, expected, state, live, config, monkeypatch, chi=chi)
        _check_independent_fields(expected, config)
        source._decision.fill(-99.)
        for value in source._table.arrays:
            value.fill(-99.)
        source._base._regions[0].cell_length_mm = -99.
        _check_values(result, expected, state, live, config, monkeypatch, chi=chi)
    finally:
        _release(native, result)
    assert asdict(config) == before
    return expected


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('constant', [False, True])
def test_sigmoid_complete_fields_and_evidence(native, monkeypatch, topology, constant):
    _full(native, monkeypatch, _configuration(topology, constant=constant))


@pytest.mark.parametrize('directions', list(product(range(4), repeat=2)))
@pytest.mark.parametrize('refine', [False, True])
def test_sigmoid_rows_ports_and_physical_centres(native, monkeypatch, directions, refine):
    config = _configuration()
    config.flags.port_wall_refine = refine
    config.solver.Nx = config.solver.Ny = 64 if refine else 12
    for side, direction in zip('AB', directions):
        cross = config.geometry.H_dom_m if direction < 2 else config.geometry.L_dom_m
        setattr(config, 'bc_' + side, replace(getattr(config, 'bc_' + side), dir=direction,
            in_ctr=.4 * cross, in_w=.4 * cross, out_ctr=.6 * cross, out_w=.4 * cross,
            uniform_inlet_2d=side == 'A'))
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('count', [1, 7])
def test_sigmoid_full_faces_and_small_grids(native, monkeypatch, count):
    config = _configuration()
    config.solver.Nx = config.solver.Ny = count
    for side in 'AB':
        getattr(config, 'bc_' + side).in_w = getattr(config, 'bc_' + side).out_w = 0.
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('dtype', [float, int, np.float16, np.float32, np.float64,
                                  np.int8, np.int16, np.int32, np.int64, np.uint32])
@pytest.mark.parametrize('array', [False, True])
def test_sigmoid_typed_transition_bounds(native, monkeypatch, dtype, array):
    config = _configuration()
    values = (1, 0) if np.issubdtype(np.dtype(dtype), np.integer) else (.231, .371)
    values = [dtype(value) for value in values]
    if array:
        values = [np.asarray(value) for value in values]
    config.zones.pareto_y_trans_inlet, config.zones.pareto_y_trans_outlet = values
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('transitions', [(-.2, .3), (0., 0.), (.8, .7), (1.2, -.3)])
def test_sigmoid_keeps_finite_transition_order(native, monkeypatch, transitions):
    config = _configuration()
    config.zones.pareto_y_trans_inlet, config.zones.pareto_y_trans_outlet = transitions
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
def test_sigmoid_typed_air_properties_and_material(native, monkeypatch, dtype):
    config = _configuration()
    config.geometry.L_cell_mm = dtype(6.375)
    config.geometry.t_wall_mm = dtype(.4375)
    config.geometry.k_s_W_mK = dtype(16.125)
    config.zones.grid['k_s'] = config.geometry.k_s_W_mK
    config.zones.config.k_s = config.geometry.k_s_W_mK
    for i, side in enumerate('AB'):
        fluid = getattr(config, 'fluid_' + side)
        fluid.u_mps, fluid.T_in_K = dtype(8.123 + i), dtype(350.125 + 75 * i)
        fluid.P_in_Pa = dtype(60000. + 1000 * i)
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('styles', list(product(('double', 'readonly'), repeat=2)) +
    [('narrow', 'double'), ('double', 'narrow'), ('byteorder', 'double'), ('double', 'byteorder')])
def test_sigmoid_retains_independent_lut_modes(native, monkeypatch, styles):
    table = _table(styles=styles)
    assert (table.view.porosity_fast, table.view.area_fast) == tuple(int(style == 'double') for style in styles)
    _full(native, monkeypatch, _configuration(), table)


@pytest.mark.parametrize('shape', [(1, 1), (1, 3), (3, 1)])
@pytest.mark.parametrize('styles', list(product(('double', 'readonly'), repeat=2)))
def test_sigmoid_singleton_lut_extrapolation(native, monkeypatch, shape, styles):
    _full(native, monkeypatch, _configuration(), _table(shape=shape, styles=styles))


def test_sigmoid_normalized_lut_retains_captured_values(native, monkeypatch):
    original = _table(shape=(3, 3))
    x, y = original.oracle.epsilon.grid
    oracle = sigmoid_reference.GeometryLUT(x[::-1], y[::-1],
        original.oracle.epsilon.values[::-1, ::-1], original.oracle.area.values[::-1, ::-1])
    # Rebinding facade attributes cannot replace the captured interpolation tables.
    facade = SimpleNamespace(query=oracle.query, eps_table=oracle.epsilon.values,
                             A0_table=oracle.area.values)
    facade.eps_table, facade.A0_table = np.zeros((3, 3)), np.ones((3, 3))
    table = _table_from_oracle(oracle)
    table.oracle = facade
    _full(native, monkeypatch, _configuration(), table)


def test_sigmoid_keeps_mutated_nan_lut_values(native, monkeypatch):
    table = _table()
    table.oracle.epsilon.values[0, 0] = np.nan
    _full(native, monkeypatch, _configuration(), _table_from_oracle(table.oracle))


@pytest.mark.parametrize('chi', [.25, .75])
def test_sigmoid_warm_lut_uses_current_material(native, monkeypatch, chi):
    config = _configuration()
    _full(native, monkeypatch, config, chi=chi)


@pytest.mark.parametrize('allow', [False, True])
def test_sigmoid_clipping_and_geometry_notices(native, monkeypatch, allow):
    config = _configuration()
    config.extrap.allow = allow
    config.zones.pareto_x_decision[0::2] = [3.99, 8.01] * 9
    config.zones.pareto_x_decision[1::2] = [.2999, .6001] * 9
    _full(native, monkeypatch, config)


def test_sigmoid_ignores_extra_controls_and_facade_geometry(native, monkeypatch):
    config = _configuration()
    config.zones.pareto_x_decision.extend([float('inf'), -99.])
    config.zones.grid['cells'][0].update(L=-1., t=99.)
    _full(native, monkeypatch, config)


def _failure_reference(monkeypatch, config, table):
    from sjtu_tpmshx.development.tests import preparation_api_reference as api
    from sjtu_tpmshx.development.tests import preparation_case_reference as preparation
    from sjtu_tpmshx.shared.models import sigmoid_field
    events = []
    with monkeypatch.context() as patch:
        patch.delenv('TPMSHX_CHI_S', raising=False)
        patch.delenv('TPMSHX_ALLOW_EXTRAP', raising=False)
        patch.setattr(sigmoid_field, 'get_geometry_lut', lambda *args, **kwargs: table.reference)
        patch.setattr(preparation._log, 'info', lambda message:
            events.append((0, preparation._log.name, message, 0)))
        with warnings.catch_warnings():
            warnings.simplefilter('always')
            patch.setattr(warnings, 'showwarning', lambda message, *args, **kwargs:
                events.append((1, '', str(message), 0)))
            with pytest.raises(Exception) as caught:
                api.prepare_case(config, case_id='sigmoid-first-failure')
    return caught.value, events


@pytest.mark.parametrize('selection', ['bounds-before-nominal', 'bounds-before-speed',
    'temperature-before-controls', 'nu-before-controls', 'nan-control', 'nan-transition',
    'infinite-transition', 'row-geometry'])
def test_sigmoid_physical_failure_order(native, monkeypatch, selection):
    config, table = _configuration(), _table()
    if selection.startswith('bounds-before'):
        config.zones.grid['cells'][0]['x1'] = -1.
        if selection == 'bounds-before-nominal':
            config.geometry.L_cell_mm = -1.
        else:
            config.fluid_A.u_mps = -1.
    elif selection == 'temperature-before-controls':
        config.fluid_A.T_in_K = -1.
        config.zones.pareto_x_decision = []
    elif selection == 'nu-before-controls':
        config.fluid_A.u_mps = 1e-9
        config.extrap.allow = False
        config.zones.pareto_x_decision = []
    elif selection == 'nan-control':
        config.zones.pareto_x_decision[0] = float('nan')
    elif selection == 'nan-transition':
        config.zones.pareto_y_trans_inlet = float('nan')
    elif selection == 'infinite-transition':
        config.zones.pareto_y_trans_outlet = np.float32(np.inf)
    elif selection == 'row-geometry':
        config.zones.pareto_x_decision[0::2] = [12.] * 18
    expected, events = _failure_reference(monkeypatch, config, table)
    status, result, failure, error, live, _ = _call(native, config, table)
    assert status == 1 and failure.kind == 1
    assert error == str(expected)
    assert _host_events(live) == events
    assert bytes(result) == bytes(_Result(6, ct.sizeof(_Result)))


@pytest.mark.parametrize('selection', ['short-controls', 'flags-epsilon', 'flags-area',
    'table-count', 'different-table-counts', 'empty-axis'])
def test_sigmoid_structural_lut_and_control_errors(native, selection):
    config, table = _configuration(), _table()
    source = _input(config, table)
    if selection == 'short-controls':
        source.controls.decision_mm.size = 35
    elif selection == 'flags-epsilon':
        source.lut.porosity_fast = 2
    elif selection == 'flags-area':
        source.lut.area_fast = 2
    elif selection == 'table-count':
        source.lut.porosity.size = source.lut.area_density_per_m.size = 3
    elif selection == 'different-table-counts':
        source.lut.porosity.size = 3
    else:
        source.lut.cell_mm = v1._Array(None, 0)
        source.lut.porosity.size = source.lut.area_density_per_m.size = 0
    status, result, failure, error, _, _ = _call(native, config, table, source=source)
    assert status == 1 and failure.kind == 1 and error
    assert bytes(result) == bytes(_Result(6, ct.sizeof(_Result)))


@pytest.mark.parametrize('selection', ['mass-flow', 'delta', 'non-air', 'experimental'])
def test_sigmoid_raw_scope_rejects_unsupported_inputs(native, selection):
    config, table = _configuration(), _table()
    if selection == 'mass-flow':
        config.fluid_A.mass_flow_kg_s = .01
    elif selection == 'delta':
        config.geometry.delta_levelset = .01
    elif selection == 'non-air':
        config.fluid_B.type = 'water'
    else:
        config.df_mode = 'experimental'
    status, result, failure, error, _, _ = _call(native, config, table)
    assert status == 1 and failure.kind == 1 and error
    assert bytes(result) == bytes(_Result(6, ct.sizeof(_Result)))


@pytest.mark.parametrize('stop_event', [1, 2])
def test_sigmoid_callback_failure_preserves_prior_events(native, stop_event):
    config, table = _configuration(), _table()
    status, success, _, error, expected, _ = _call(native, config, table)
    assert status == 0, error
    _release(native, success)
    assert len(expected) >= stop_event
    status, result, failure, error, live, _ = _call(native, config, table, stop_event=stop_event)
    assert status != 0 and failure.kind and error
    assert live == expected[:stop_event]
    assert bytes(result) == bytes(_Result(6, ct.sizeof(_Result)))


@pytest.mark.parametrize('borrowed', ['source', 'controls', 'cell_mm', 'wall_mm',
    'porosity', 'area_density_per_m', 'regions', 'name'])
@pytest.mark.parametrize('destination', ['result', 'failure', 'error'])
def test_sigmoid_borrowed_storage_cannot_overlap_outputs(native, borrowed, destination):
    source = _input(_configuration(), _table())
    result, failure = _Result(6, ct.sizeof(_Result)), v2._Failure(2, ct.sizeof(v2._Failure))
    error = ct.create_string_buffer(b'unchanged', 4096)
    target = {'result': result, 'failure': failure, 'error': error}[destination]
    if borrowed == 'source':
        # Use a real input allocation and point the destination into it.
        storage = ct.create_string_buffer(max(ct.sizeof(source), ct.sizeof(target)))
        ct.memmove(storage, ct.byref(source), ct.sizeof(source))
        source_pointer = ct.cast(storage, ct.POINTER(_Input))
        if destination == 'result':
            result = _Result.from_buffer(storage)
        elif destination == 'failure':
            failure = v2._Failure.from_buffer(storage)
        else:
            error = storage
        keep = [storage]
    else:
        source_pointer = ct.byref(source)
        if borrowed == 'controls':
            source.controls.decision_mm = v1._Array(ct.cast(ct.byref(target), ct.POINTER(_D)), 1)
        elif borrowed == 'regions':
            source.values.regions = ct.cast(ct.byref(target), ct.POINTER(v5._Region))
            source.values.region_count = 1
        elif borrowed == 'name':
            source._base._regions[0].name = v1._Text(ct.cast(ct.byref(target), ct.POINTER(ct.c_char)), ct.sizeof(target))
        else:
            setattr(source.lut, borrowed, v1._Array(ct.cast(ct.byref(target), ct.POINTER(_D)), 1))
        keep = [source]
    # An independent error buffer can report a top-level descriptor conflict.
    watched = [*keep, result] if borrowed == 'source' else [*keep, result, failure, error]
    before = [bytes(value) for value in watched]
    status = native.tpmshx_prepare_sigmoid_case_2d_v6(source_pointer, None, None,
        ct.byref(result), ct.byref(failure), error, len(error))
    assert status == 1
    assert [bytes(value) for value in watched] == before


@pytest.mark.parametrize('which', ['source', 'nested-v5', 'nested-v2', 'nested-v1', 'result'])
@pytest.mark.parametrize('field', ['abi_version', 'struct_size'])
def test_sigmoid_versioned_storage_preserves_result(native, which, field):
    config, table = _configuration(), _table()
    source, result = _input(config, table), _Result(6, ct.sizeof(_Result))
    target = {'source': source, 'nested-v5': source.values, 'nested-v2': source.values.values,
              'nested-v1': source.values.values.values, 'result': result}[which]
    setattr(target, field, 0)
    before = bytes(result)
    status, result, _, error, _, _ = _call(native, config, table, source=source, result=result)
    assert status == 1 and error and bytes(result) == before


def test_sigmoid_owned_result_requires_release(native):
    config, table = _configuration(), _table()
    status, result, _, error, _, _ = _call(native, config, table)
    assert status == 0, error
    before, decision = bytes(result), v1._array(result.controls.decision_mm)
    try:
        status, result, failure, error, live, _ = _call(native, config, table, result=result)
        assert status == 1 and failure.kind == 1 and 'release' in error and not live
        assert bytes(result) == before
        v1._same(v1._array(result.controls.decision_mm), decision, 'retained result')
    finally:
        _release(native, result)
    assert bytes(result) == bytes(_Result())
    _release(native, result)
    native.tpmshx_preparation_sigmoid_case_2d_release_v6(None)


def _cold(native, topology, *, shape=(2, 2), resolution=16):
    result, error = _LUT(6, ct.sizeof(_LUT)), ct.create_string_buffer(4096)
    status = native.tpmshx_preparation_sigmoid_lut_create_v6(
        int(topology == 'Gyroid'), *shape, resolution, ct.byref(result), error, len(error))
    assert status == 0, error.value.decode()
    assert result.owner and (result.values.porosity_fast, result.values.area_fast) == (1, 1)
    return result


def _check_cold(result, topology, shape, resolution):
    cells, walls = np.linspace(4., 8., shape[0]), np.linspace(.3, .6, shape[1])
    v1._same(v1._array(result.values.cell_mm), cells, 'cold cell axis')
    v1._same(v1._array(result.values.wall_mm), walls, 'cold wall axis')
    epsilon, area = _raw_tables(topology, cells, walls, resolution)
    v1._same(v1._array(result.values.porosity).reshape(shape), epsilon, 'cold porosity')
    v1._same(v1._array(result.values.area_density_per_m).reshape(shape), area, 'cold area')
    return sigmoid_reference.GeometryLUT(cells, walls, epsilon, area)


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('shape,resolution', [((2, 2), 16), ((1, 1), 1), ((0, 3), 1), ((3, 1), 13)])
def test_sigmoid_cold_lut_matches_raw_voxel_nodes(native, topology, shape, resolution):
    result = _cold(native, topology, shape=shape, resolution=resolution)
    try:
        if 0 in shape:
            v1._same(v1._array(result.values.cell_mm), np.linspace(4., 8., shape[0]), 'empty axis')
            assert result.values.porosity.size == result.values.area_density_per_m.size == 0
        else:
            _check_cold(result, topology, shape, resolution)
        if topology == 'Diamond' and resolution == 1 and shape == (1, 1):
            v1._same(v1._array(result.values.porosity), [0.], 'raw degenerate porosity')
            v1._same(v1._array(result.values.area_density_per_m), [0.], 'raw degenerate area')
    finally:
        _release(native, result)
    assert bytes(result) == bytes(_LUT())
    _release(native, result)
    native.tpmshx_preparation_sigmoid_lut_release_v6(None)


def test_sigmoid_cold_lut_and_prepared_result_have_separate_owners(native, monkeypatch):
    resource = _cold(native, 'Gyroid')
    oracle = _check_cold(resource, 'Gyroid', (2, 2), 16)
    table = _table_from_oracle(oracle)
    table.arrays, table.view = [], resource.values
    config = _configuration()
    expected, state = _reference(monkeypatch, config, table)
    status, result, _, error, live, _ = _call(native, config, table)
    assert status == 0, error
    _release(native, resource)
    try:
        _check_values(result, expected, state, live, config, monkeypatch)
    finally:
        _release(native, result)


@pytest.mark.parametrize('selection', ['zero-resolution', 'extent-overflow', 'voxel-overflow',
    'topology', 'version', 'size'])
def test_sigmoid_cold_lut_failure_preserves_result(native, selection):
    result, error = _LUT(6, ct.sizeof(_LUT)), ct.create_string_buffer(4096)
    topology, cells, walls, resolution = 1, 2, 2, 16
    if selection == 'zero-resolution':
        resolution = 0
    elif selection == 'extent-overflow':
        cells = _S(-1).value
    elif selection == 'voxel-overflow':
        resolution = _S(-1).value
    elif selection == 'topology':
        topology = 2
    elif selection == 'version':
        result.abi_version = 0
    else:
        result.struct_size = 0
    before = bytes(result)
    status = native.tpmshx_preparation_sigmoid_lut_create_v6(topology, cells, walls,
        resolution, ct.byref(result), error, len(error))
    assert status == 1 and error.value and bytes(result) == before


def test_sigmoid_cold_lut_reuse_and_error_overlap(native):
    resource = _cold(native, 'Gyroid')
    before, error = bytes(resource), ct.create_string_buffer(4096)
    try:
        status = native.tpmshx_preparation_sigmoid_lut_create_v6(1, 2, 2, 16,
            ct.byref(resource), error, len(error))
        assert status == 1 and b'release' in error.value and bytes(resource) == before
        status = native.tpmshx_preparation_sigmoid_lut_create_v6(1, 2, 2, 16,
            ct.byref(resource), ct.cast(ct.byref(resource), ct.POINTER(ct.c_char)), ct.sizeof(resource))
        assert status == 1 and bytes(resource) == before
    finally:
        _release(native, resource)


@pytest.mark.slow
@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_sigmoid_production_cold_nodes_and_repeated_warm_preparation(native, monkeypatch, topology):
    """Check all 1,271 N=256 nodes; small transport fixtures cannot replace this check."""
    resource = _cold(native, topology, shape=(41, 31), resolution=256)
    results = []
    try:
        oracle = _check_cold(resource, topology, (41, 31), 256)
        table = _table_from_oracle(oracle)
        table.arrays, table.view = [], resource.values
        evidence = []
        for chi, conductivity in ((.25, 16.), (.75, 24.)):
            config = _configuration(topology)
            config.geometry.k_s_W_mK = conductivity
            config.zones.grid['k_s'] = config.zones.config.k_s = conductivity
            expected, state = _reference(monkeypatch, config, table, chi=chi)
            status, result, _, error, live, _ = _call(native, config, table, chi=chi)
            assert status == 0, error
            results.append(result)
            evidence.append((expected, state, live, config, chi))
        _release(native, resource)
        for result, (expected, state, live, config, chi) in zip(results, evidence):
            _check_values(result, expected, state, live, config, monkeypatch, chi=chi)
            _check_independent_fields(expected, config)
    finally:
        _release(native, resource)
        for result in results:
            _release(native, result)
