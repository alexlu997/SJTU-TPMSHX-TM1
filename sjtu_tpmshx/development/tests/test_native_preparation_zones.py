"""Compare raw native zoned preparation with the independent Python route."""
import ctypes as ct
from copy import deepcopy
from dataclasses import asdict, replace
from itertools import product
import os

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import test_native_preparation_case as v1
from sjtu_tpmshx.development.tests import test_native_preparation_fluids as v2
from sjtu_tpmshx.development.tests import test_native_preparation_mass_flow as v3
from sjtu_tpmshx.development.tests.test_native_preparation_continuous import _host_events
from sjtu_tpmshx.development.tests.solver_tm1.test_prepared_zoned_thermal_2d import _config
from sjtu_tpmshx.shared.models.zone_config import Zone

_U, _S, _D, _struct = v1._U, v1._S, v1._D, v1._structure
_GridScalar = _struct('ZoneScalar', [('value', _D), ('precision', _U), ('strong', _U)])
_Geometry = _struct('ZoneGeometry', v1._doubles(
    'epsilon epsilon_a epsilon_b area_density_per_m hydraulic_diameter_m'))
_Region = _struct('ZoneRegion', [('name', v1._Text), ('bounds', _GridScalar * 4),
    ('cell_length_mm', _D), ('wall_thickness_mm', _D), ('cell_kind', v2._Kind), ('wall_kind', v2._Kind)])
_Input = _struct('ZonedInput', [('abi_version', _U), ('struct_size', _S), ('values', v2._Input),
    ('kind', _U), ('axis', _U), ('regions', ct.POINTER(_Region)), ('region_count', _S)])
_RegionValues = _struct('ZoneValues', [('region', _Region), ('geometry', _Geometry),
    ('property_geometry', _Geometry * 2), ('solid_conductivity', _D), ('properties', v1._Properties * 2),
    ('property_kinds', (v2._Kind * 13) * 2)])
_Result = _struct('ZonedResult', [('abi_version', _U), ('struct_size', _S), ('prepared', v2._Result),
    ('kind', _U), ('axis', _U), ('regions', ct.POINTER(_RegionValues)), ('region_count', _S),
    ('zone_id', ct.POINTER(ct.c_int32)), ('cell_count', _S),
    *[(name, v1._Array) for name in ('thermal_porosity', 'area_density_per_m', 'hydraulic_diameter_m',
                                   'design_area_density_per_m')],
    ('fluid_conductivity', v1._Array * 2), ('volumetric_transfer', v1._Array * 2), ('owner', ct.c_void_p)])


@pytest.fixture(scope='module')
def native():
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY', v1._library_path()))
    library.tpmshx_prepare_zoned_case_2d_v5.argtypes = [ct.POINTER(_Input), ct.POINTER(v1._Options),
        ct.POINTER(v1._Callbacks), ct.POINTER(_Result), ct.POINTER(v2._Failure), ct.POINTER(ct.c_char), _S]
    library.tpmshx_prepare_zoned_case_2d_v5.restype = ct.c_int
    library.tpmshx_preparation_zoned_case_2d_release_v5.argtypes = [ct.POINTER(_Result)]
    library.tpmshx_preparation_zoned_case_2d_release_v5.restype = None
    return library


@pytest.fixture(autouse=True)
def clear_reference_caches():
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    compute.cache_clear();compute_geometry.cache_clear()
    yield
    compute.cache_clear();compute_geometry.cache_clear()


def _kind(value):
    if isinstance(value, np.integer):
        return v2._Kind(64, 1, 1)
    return v2._kind(value)


def _regions(config):
    if config.zones.axis == 'grid':
        return [('', [cell[key] for key in ('x0', 'x1', 'y0', 'y1')], cell['L'], cell['t'])
                for cell in config.zones.grid['cells']]
    config_value = config.zones.config
    rows = config_value['zones'] if isinstance(config_value, dict) else [asdict(zone) for zone in config_value.zones]
    return [(row['name'], [row['y_frac_start'], row['y_frac_end'], 0., 0.], row['L_mm'], row['t_mm']) for row in rows]


def _input(config):
    base = v2._input(config);base.values.geometry_mode = 2
    descriptors, buffers = [], []
    for name, bounds, cell, wall in _regions(config):
        buffer = ct.create_string_buffer(name.encode());buffers.append(buffer)
        values = []
        for value in bounds:
            kind = v3._kind(value)
            values.append(_GridScalar(value, kind.precision, kind.strong))
        descriptors.append(_Region(v1._Text(ct.cast(buffer, ct.POINTER(ct.c_char)), len(name.encode())),
            (_GridScalar * 4)(*values), cell, wall, _kind(cell), _kind(wall)))
    regions = (_Region * len(descriptors))(*descriptors)
    source = _Input(5, ct.sizeof(_Input), base, config.zones.axis == 'grid', config.zones.axis != 'x',
                    regions, len(regions))
    source._base, source._regions, source._buffers = base, regions, buffers
    return source


def _call(native, config, *, chi=None, source=None):
    source = _input(config) if source is None else source
    result, failure = _Result(5, ct.sizeof(_Result)), v2._Failure(2, ct.sizeof(v2._Failure))
    options = v1._Options(1, ct.sizeof(v1._Options), chi is not None, config.extrap.allow, chi or 0.)
    events, error = [], ct.create_string_buffer(4096)
    def event(_context, pointer):
        item = pointer.contents
        events.append((item.kind, v1._text(item.logger), v1._text(item.message), item.floating_event))
        return 0
    callback = v1._EventFunction(event)
    callbacks = v1._Callbacks(1, ct.sizeof(v1._Callbacks), callback, None)
    before, rows = bytes(source), bytes(source._regions)
    status = native.tpmshx_prepare_zoned_case_2d_v5(ct.byref(source), ct.byref(options), ct.byref(callbacks),
        ct.byref(result), ct.byref(failure), error, len(error))
    assert bytes(source) == before and bytes(source._regions) == rows
    return status, result, failure, error.value.decode(), events, source


def _release(native, result):
    native.tpmshx_preparation_zoned_case_2d_release_v5(ct.byref(result))



def _check_region_values(result, config):
    from sjtu_tpmshx.shared.domain.run_warnings import warning_scope
    from sjtu_tpmshx.shared.models.tpms_calc import compute, geometry
    regions = _regions(config)
    if config.zones.axis != 'grid':
        regions.sort(key=lambda region: region[1][0])
    geometry_names = [('epsilon', 'epsilon'), ('epsilon_a', 'epsilon_A'), ('epsilon_b', 'epsilon_B'),
                      ('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h')]
    property_names = [('rho', 'rho'), ('mu', 'mu'), ('k_f', 'k_f'), ('re', 'Re'), ('nu', 'Nu'),
        ('permeability_m2', 'K_df'), ('forchheimer_per_m', 'cF_df'), ('pressure_gradient_Pa_m', 'dP_per_L'),
        ('surface_transfer_W_m2K', 'H_sf'), ('fluid_conductivity_W_mK', 'K_ff'), ('solid_conductivity_W_mK', 'K_ss')]
    with warning_scope({}):
        for index, (_, _, cell, wall) in enumerate(regions):
            actual = result.regions[index]
            expected = geometry(config.geometry.tpms, cell, wall, config.geometry.k_s_W_mK)
            for name, key in geometry_names:
                v1._same(getattr(actual.geometry, name), expected[key], 'region geometry ' + key)
            v1._same(actual.solid_conductivity, expected['K_ss'], 'region solid conductivity')
            for side, tag in enumerate('AB'):
                fluid = getattr(config, 'fluid_' + tag)
                props = compute(config.geometry.tpms, cell, wall, fluid.u_mps, fluid.T_in_K,
                                fluid.P_in_Pa, config.geometry.k_s_W_mK)
                for name, key in geometry_names:
                    v1._same(getattr(actual.property_geometry[side], name), props[key], 'region property ' + key)
                for name, key in property_names:
                    v1._same(getattr(actual.properties[side], name), props[key], 'region inlet ' + key)
                    position = [item[0] for item in v1._Properties._fields_].index(name)
                    assert v1._struct_values(actual.property_kinds[side][position]) == v1._struct_values(_kind(props[key])), key


def _full(native, monkeypatch, config, *, chi=None):
    before = deepcopy(asdict(config))
    expected, state = v3._reference(monkeypatch, 'prepare_flow_case', config, chi=chi)
    status, result, failure, error, live, source = _call(native, config, chi=chi)
    assert status == 0, error
    try:
        assert result.owner and not result.prepared.values.owner and not failure.kind
        with monkeypatch.context() as patch:
            if chi is not None:
                patch.setenv('TPMSHX_CHI_S', str(chi))
            v2._check_values(result.prepared, expected, config)
            _check_region_values(result, config)
        v2._check_evidence(result.prepared, expected, state['records']['final'], state['events']['final'],
                           live, config, event_converter=_host_events)
        shape = expected.design_fields['L_field_m'].shape
        v1._same(np.ctypeslib.as_array(result.zone_id, shape=(result.cell_count,)).reshape(shape),
                 expected.design_fields['zone_id'], 'zone assignment')
        for name, key in [('thermal_porosity', 'epsilon'), ('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h')]:
            v1._same(v1._array(getattr(result, name)).reshape(shape), expected.parameters['thermal_geometry']['fields'][key], key)
        v1._same(v1._array(result.design_area_density_per_m).reshape(shape), expected.design_fields['A_0_arr'], 'design area density')
        for index, side in enumerate('AB'):
            v1._same(v1._array(result.fluid_conductivity[index]).reshape(shape), expected.design_fields['K_ff' + side + '_arr'], side + ' Kff')
            v1._same(v1._array(result.volumetric_transfer[index]).reshape(shape), expected.design_fields['h_v' + side + '_arr'], side + ' transfer')
        regions = _regions(config)
        if config.zones.axis != 'grid':
            regions.sort(key=lambda region: region[1][0])
        assert result.region_count == len(regions)
        for index, (name, bounds, cell, wall) in enumerate(regions):
            saved = result.regions[index].region
            assert v1._text(saved.name) == name
            v1._same([value.value for value in saved.bounds], bounds, 'zone bounds')
            v1._same([saved.cell_length_mm, saved.wall_thickness_mm], [cell, wall], 'zone dimensions')
            assert v1._struct_values(saved.cell_kind) == v1._struct_values(_kind(cell))
            assert v1._struct_values(saved.wall_kind) == v1._struct_values(_kind(wall))
        for buffer in source._buffers:
            ct.memset(buffer, ord('X'), len(buffer) - 1)
        source._regions[0].cell_length_mm = -1.
        assert v1._text(result.regions[0].region.name) == regions[0][0]
        assert result.regions[0].region.cell_length_mm == float(regions[0][2])
    finally:
        _release(native, result)
    assert asdict(config) == before
    return expected


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('mode', ['x', 'y', 'grid'])
def test_native_zoned_complete_preparation(native, monkeypatch, topology, mode):
    config = _config(mode);config.geometry.tpms = topology
    config.zones.config.tpms_type = topology;config.zones.grid['tpms_type'] = topology
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('directions', list(product(range(4), repeat=2)))
@pytest.mark.parametrize('mode', ['x', 'y', 'grid'])
@pytest.mark.parametrize('refine', [False, True])
def test_native_zoned_ports_rows_and_physical_grid(native, monkeypatch, directions, mode, refine):
    config = _config(mode);config.flags.port_wall_refine = refine
    config.solver.Nx = config.solver.Ny = 64 if refine else 12
    for side, direction in zip('AB', directions):
        cross = config.geometry.H_dom_m if direction < 2 else config.geometry.L_dom_m
        setattr(config, 'bc_' + side, replace(getattr(config, 'bc_' + side), dir=direction,
            in_ctr=.4*cross, in_w=.4*cross, out_ctr=.6*cross, out_w=.4*cross, uniform_inlet_2d=side == 'A'))
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('mode', ['x', 'y', 'grid'])
def test_native_zoned_full_faces_do_not_select_uniform_master_grid(native, monkeypatch, mode):
    config = _config(mode)
    for side in 'AB':
        port = getattr(config, 'bc_' + side);port.in_w = port.out_w = 0.
    expected = _full(native, monkeypatch, config)
    assert (len(expected.grid['dx']), len(expected.grid['dy'])) == (config.solver.Nx, config.solver.Ny)


@pytest.mark.parametrize('mode', ['x', 'y', 'grid'])
@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64, np.int16])
@pytest.mark.parametrize('first_typed', [False, True])
def test_native_zoned_first_equal_key_keeps_scalar_types(native, monkeypatch, mode, dtype, first_typed):
    config = _config(mode)
    values = [(dtype(6), np.float16(.375)), (6., .375)]
    if not first_typed:
        values.reverse()
    if mode == 'grid':
        config.zones.grid['cells'] = [dict(x0=0., x1=1., y0=index/3., y1=(index+1)/3., L=cell, t=wall)
            for index, (cell, wall) in enumerate([*values, (7., .5)])]
    else:
        config.zones.config.zones = [Zone(str(index), index/3., (index+1)/3., cell, wall)
            for index, (cell, wall) in enumerate([*values, (7., .5)])]
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('selection', ['gap', 'overlap', 'repeat', 'partial'])
def test_native_rectangles_keep_order_and_first_region_fallback(native, monkeypatch, selection):
    config = _config('grid')
    cells = config.zones.grid['cells']
    if selection == 'gap':
        cells[0]['y1'], cells[1]['y0'] = .25, .75
    elif selection == 'overlap':
        cells[0]['y1'], cells[1]['y0'] = .8, .2
    elif selection == 'repeat':
        cells.append(dict(cells[0], x0=.4, x1=.6))
    else:
        cells[:] = [dict(cells[1], x0=.3, x1=.7, y0=.3, y1=.7)]
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('gap', [-5e-10, 0., 5e-10])
def test_native_stripes_sort_without_changing_tolerated_bounds(native, monkeypatch, gap):
    config = _config('y')
    config.zones.config.zones[1].y_frac_start += gap
    config.zones.config.zones.reverse()
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('mode', ['x', 'y', 'grid'])
@pytest.mark.parametrize('chi', [.25, .75])
def test_native_zoned_material_override(native, monkeypatch, mode, chi):
    _full(native, monkeypatch, _config(mode), chi=chi)


@pytest.mark.parametrize('change,text', [
    ('mass', 'prescribed inlet velocity'), ('delta', 'symmetric delta_levelset=0'),
    ('experiment', "df_mode='cfd_smooth'"), ('water', 'air/air only'),
    ('mode', 'geometry_mode=2'), ('kind', 'stripe/rectangle'), ('axis', 'x/y axis')])
def test_native_zoned_declared_scope_preserves_failed_result(native, change, text):
    config = _config('y');source = _input(config)
    if change == 'mass':
        source.values.values.sides[0].have_mass_flow = 1
        source.values.values.sides[0].mass_flow_kg_s = .01
    elif change == 'delta': source.values.values.delta_levelset = .1
    elif change == 'experiment': source.values.values.df_mode = 1
    elif change == 'water': source.values.values.sides[1].fluid = 1
    elif change == 'mode': source.values.values.geometry_mode = 1
    elif change == 'kind': source.kind = 2
    elif change == 'axis': source.axis = 2
    status, result, failure, error, _, _ = _call(native, config, source=source)
    assert status == 1 and failure.kind == 1 and text in error
    assert bytes(result) == bytes(_Result(5, ct.sizeof(_Result)))


@pytest.mark.parametrize('mode,change,text', [
    ('y', 'first', 'First zone must start'), ('y', 'last', 'Last zone must end'),
    ('y', 'gap', 'Gap/overlap'), ('y', 'finite', 'endpoints must be finite'),
    ('y', 'length', 'outside [1, 20]'), ('y', 'wall', 'outside [0.1, 2.0]'),
    ('grid', 'bounds', 'x coordinates'), ('grid', 'pore', 'no pore space'),
    ('grid', 'df', 'outside')])
def test_native_zoned_first_physical_failure_matches_reference(native, monkeypatch, mode, change, text):
    config = _config(mode)
    if mode == 'y':
        first, last = config.zones.config.zones
        if change == 'first': first.y_frac_start = .1
        elif change == 'last': last.y_frac_end = .9
        elif change == 'gap': first.y_frac_end = .2
        elif change == 'finite': first.y_frac_start = float('nan')
        elif change == 'length': first.L_mm = 21.
        elif change == 'wall': first.t_mm = 3.
    else:
        first = config.zones.grid['cells'][0]
        if change == 'bounds': first['x0'] = -.1
        elif change == 'pore': first['t'] = 4.
        else: first['L'] = 9.
    with pytest.raises(ValueError) as reference:
        v3._reference(monkeypatch, 'prepare_flow_case', config)
    status, result, failure, error, _, _ = _call(native, config)
    assert status == 1 and failure.kind == 1 and text in error
    assert error == str(reference.value)
    assert bytes(result) == bytes(_Result(5, ct.sizeof(_Result)))


@pytest.mark.parametrize('mode', ['x', 'y', 'grid'])
@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
def test_native_zoned_typed_nominal_and_material_values(native, monkeypatch, mode, dtype):
    config = _config(mode)
    config.geometry.L_cell_mm = dtype(config.geometry.L_cell_mm)
    config.geometry.t_wall_mm = dtype(.375)
    config.geometry.k_s_W_mK = dtype(config.geometry.k_s_W_mK)
    config.zones.config.k_s = config.geometry.k_s_W_mK
    config.zones.grid['k_s'] = config.geometry.k_s_W_mK
    for side in 'AB':
        fluid = getattr(config, 'fluid_' + side)
        fluid.u_mps, fluid.T_in_K = dtype(fluid.u_mps), dtype(fluid.T_in_K)
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('earlier', ['temperature', 'reynolds'])
def test_native_empty_stripes_keep_earlier_physical_failure(native, monkeypatch, earlier):
    config = _config('y');config.zones.config.zones = []
    if earlier == 'temperature':
        config.fluid_A.T_in_K = -1.
    else:
        config.fluid_A.u_mps = 1e-9;config.extrap.allow = False
    with pytest.raises(ValueError) as reference:
        v3._reference(monkeypatch, 'prepare_flow_case', config)
    status, result, failure, error, _, _ = _call(native, config)
    assert status == 1 and failure.kind == 1
    assert error == str(reference.value)
    assert bytes(result) == bytes(_Result(5, ct.sizeof(_Result)))


@pytest.mark.parametrize('borrowed', ['regions', 'name'])
@pytest.mark.parametrize('destination', ['result', 'failure', 'error'])
def test_native_zoned_borrowed_storage_cannot_overlap_outputs(native, borrowed, destination):
    source = _input(_config('y'))
    result, failure = _Result(5, ct.sizeof(_Result)), v2._Failure(2, ct.sizeof(v2._Failure))
    error = ct.create_string_buffer(b'unchanged', 4096)
    target = {'result': result, 'failure': failure, 'error': error}[destination]
    if borrowed == 'regions':
        source.regions = ct.cast(ct.byref(target), ct.POINTER(_Region));source.region_count = 1
    else:
        source._regions[0].name = v1._Text(ct.cast(ct.byref(target), ct.POINTER(ct.c_char)), ct.sizeof(target))
    before = [bytes(value) for value in (source, result, failure, error)]
    status = native.tpmshx_prepare_zoned_case_2d_v5(ct.byref(source), None, None, ct.byref(result),
        ct.byref(failure), error, len(error))
    assert status == 1
    assert [bytes(value) for value in (source, result, failure, error)] == before


@pytest.mark.parametrize('mode', ['x', 'y'])
@pytest.mark.parametrize('dtype', [np.float16, np.float32])
@pytest.mark.parametrize('strong_end', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_native_zoned_mixed_bound_gap_preserves_scalar_types(native, monkeypatch, mode, dtype, strong_end, reverse):
    config = _config(mode)
    first, last = config.zones.config.zones
    first.y_frac_end, last.y_frac_start = ((dtype(.5), .500000005) if strong_end
                                          else (.500000005, dtype(.5)))
    if reverse:
        config.zones.config.zones.reverse()
    _full(native, monkeypatch, config)


@pytest.mark.parametrize('mode', ['x', 'y'])
@pytest.mark.parametrize('dtype', [np.float16, np.float32])
@pytest.mark.parametrize('change', ['sort-tie', 'narrow', 'strong-gap', 'wall-limit', 'nan-cell', 'nan-wall'])
def test_native_zoned_typed_stripe_failure_matches_reference(native, monkeypatch, mode, dtype, change):
    config = _config(mode)
    if change == 'sort-tie':
        config.zones.config.zones = [Zone('first', 0., dtype(.5), 7., .4),
            Zone('weak', .500000005, 1., 6., .5), Zone('strong', dtype(.5), 1., 6., .5)]
    elif change == 'narrow':
        config.zones.config.zones = [Zone('first', 0., dtype(.5), 7., .4),
            Zone('narrow', dtype(.5), .500000005, 6., .5), Zone('last', .500000005, 1., 6., .5)]
    elif change == 'strong-gap':
        first, last = config.zones.config.zones
        first.y_frac_end, last.y_frac_start = dtype(.5), np.float64(.500000005)
    elif change == 'wall-limit':
        config.zones.config.zones[0].t_mm = dtype(.1)
    elif change == 'nan-cell':
        config.zones.config.zones[0].L_mm = dtype(np.nan)
    else:
        config.zones.config.zones[0].t_mm = dtype(np.nan)
    with pytest.raises(ValueError) as reference:
        v3._reference(monkeypatch, 'prepare_flow_case', config)
    status, result, failure, error, _, _ = _call(native, config)
    assert status == 1 and failure.kind == 1
    assert error == str(reference.value)
    assert bytes(result) == bytes(_Result(5, ct.sizeof(_Result)))


@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('dtype', [np.float16, np.float32])
@pytest.mark.parametrize('strong_end', [False, True])
def test_native_zoned_typed_rectangle_order_matches_reference(native, monkeypatch, axis, dtype, strong_end):
    config = _config('grid')
    first = config.zones.grid['cells'][0]
    first[axis + '0'], first[axis + '1'] = ((.499999995, dtype(.5)) if strong_end
                                          else (dtype(.5), .500000005))
    with pytest.raises(ValueError) as reference:
        v3._reference(monkeypatch, 'prepare_flow_case', config)
    status, result, failure, error, _, _ = _call(native, config)
    assert status == 1 and failure.kind == 1
    assert error == str(reference.value)
    assert bytes(result) == bytes(_Result(5, ct.sizeof(_Result)))
