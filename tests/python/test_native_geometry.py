"""Native geometry binding contracts, separate from kernel accuracy studies."""
import gc
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
import weakref

import numpy as np
import pytest

from tests.python import geometry_reference as reference
from sjtu_tpmshx.cpp_interface import _native_geometry as native


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def geometry():
    try:
        native._library_path()
    except (FileNotFoundError, RuntimeError) as error:
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(str(error))
        pytest.skip(str(error))
    native._library()
    return native


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_signed_wall_grid_samples_physical_faces_and_cell_centers(geometry, topology):
    from sjtu_tpmshx.physical_models.tpms_geometry import signed_wall_grid

    cell = 8.
    box, shape = (10., 9., 7.5), (11, 19, 31)
    walls = np.linspace(.3, .7, np.prod(shape)).reshape(shape, order='F')
    delta = np.linspace(-.2, .15, np.prod(shape)).reshape(shape)[..., ::-1]
    samples, reason = signed_wall_grid(topology, np.full((3, 2), cell), box, shape, walls, delta)
    assert reason is None
    angles = [2. * np.pi * np.linspace(0., size, n) / cell for size, n in zip(box, shape)]
    expected_phi = reference._PHI_FUNCS[topology](*np.meshgrid(*angles, indexing='ij', sparse=True))
    np.testing.assert_allclose(samples['phi'], expected_phi, atol=5e-15, rtol=0.)
    # The one-period grid has centers at 1, 3, 5 and 7 mm on each axis.
    np.testing.assert_allclose(samples['phi'][1:8:2, 2:15:4, 4:29:8],
                               geometry.phi_grid(topology, 4), atol=5e-15, rtol=0.)
    C = reference._C_from_tL(topology, walls / cell)
    np.testing.assert_array_equal(samples['lower'], delta - C)
    np.testing.assert_array_equal(samples['upper'], delta + C)
    assert all(field.flags.owndata and field.flags.c_contiguous for field in samples.values())


def test_graded_cell_length_reports_the_missing_phase_rule(tmp_path, monkeypatch):
    from sjtu_tpmshx.physical_models.tpms_geometry import lattice_cell_size, signed_wall_grid

    monkeypatch.setenv('TPMSHX_GEOMETRY_LIBRARY', str(tmp_path / 'missing-library'))
    cells = np.array([[7., 7.], [7., 7.01]])
    cell, reason = lattice_cell_size(cells)
    assert cell is None and 'phase rule for graded L' in reason
    assert signed_wall_grid('Gyroid', cells, (8., 6., 4.), (5, 4, 3), .5) == (None, reason)


def test_signed_wall_grid_requires_sample_fields_on_the_same_axes(geometry):
    shape = (2, 3, 4)
    with pytest.raises(ValueError, match='sample shape'):
        geometry.signed_wall_grid('Gyroid', 7., (8., 6., 4.), shape, .5, np.zeros(shape[::-1]))
    with pytest.raises(ValueError, match='two samples per axis'):
        geometry.signed_wall_grid('Gyroid', 7., (8., 6., 4.), (1, 3, 4), .5, 0.)


@pytest.fixture
def lattice_request(geometry):
    pytest.importorskip('pyvista')
    pytest.importorskip('PySide6')
    from sjtu_tpmshx.applications.gui.ui.vis3d_lattice_worker import LatticeRequest

    widths = (np.array([.001, .003, .0064]), np.array([.002, .0051]), np.array([.0015, .0035, .005]))
    centers = [1000. * (np.cumsum(w) - w / 2) for w in widths]
    x, y, z = np.meshgrid(*centers, indexing='ij')
    return LatticeRequest(result_id='run1', field_name='Ta', topology='Gyroid', phase='A',
                          dx=widths[0], dy=widths[1], dz=widths[2], field=300. + 2*x - y + 3*z,
                          L_mm=7., t_mm=.32 + .04*x + .01*z, delta=-.3 + .05*x + .01*y)


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_lattice_domains_close_on_all_six_faces_and_sample_recorded_fields(lattice_request, topology):
    from sjtu_tpmshx.applications.gui.ui.vis3d_lattice_worker import LatticeCache
    from sjtu_tpmshx.physical_models.tpms_geometry import signed_wall_grid

    r = replace(lattice_request, topology=topology)
    widths = (r.dx, r.dy, r.dz)
    centers = [np.cumsum(w * 1000.) - w * 500. for w in widths]
    box = [sum(w * 1000.) for w in widths]
    x = np.linspace(0., box[0], round(box[0] * 8 / 7.) + 1)
    # On the x edge the two other coordinates take their first cell values.
    shape = (len(x), 2, 2)
    t, delta = [np.broadcast_to(np.interp(x, centers[0], f[:, 0, 0])[:, None, None], shape)
                for f in (r.t_mm, r.delta)]
    samples, _ = signed_wall_grid(topology, 7., box, shape, t, delta)
    volume = 0.
    cache = LatticeCache()
    for phase in ('A', 'B', 'S'):
        stages = []
        mesh, kept = cache.build(replace(r, phase=phase), threading.Event(),
                                 lambda number, label: stages.append(number))
        assert stages == [1, 2, 3, 4, 5] and kept
        assert mesh.is_all_triangles and mesh.n_open_edges == 0
        assert mesh.point_data['Normals'].shape == (mesh.n_points, 3)
        volume += mesh.volume
        triangles = mesh.points[mesh.regular_faces]
        for axis, span in enumerate(box):
            for face in (0., span):
                cap = triangles[np.isclose(triangles[:, :, axis], face).all(axis=1)]
                normals = np.cross(cap[:, 1] - cap[:, 0], cap[:, 2] - cap[:, 0])
                outward = normals[:, axis] * (-1 if face == 0. else 1)
                assert outward.size and np.any(outward > 0.) and np.all(outward >= 0.)
        edge_x = mesh.points[(mesh.points[:, 1] == 0.) & (mesh.points[:, 2] == 0.), 0]
        for limit in {'A': ('lower',), 'B': ('upper',), 'S': ('lower', 'upper')}[phase]:
            wall = (samples['phi'] - samples[limit])[:, 0, 0]
            i = np.flatnonzero(wall[:-1] * wall[1:] < 0.)
            crossings = x[i] - wall[i] * (x[i+1] - x[i]) / (wall[i+1] - wall[i])
            assert crossings.size
            for crossing in crossings:
                assert np.min(abs(edge_x - crossing)) < 2e-6
        px, py, pz = [np.clip(p, c[0], c[-1]) for p, c in zip(mesh.points.astype(float).T, centers)]
        np.testing.assert_allclose(mesh['Ta'], 300. + 2*px - py + 3*pz, rtol=0., atol=1e-10)
    assert volume == pytest.approx(np.prod(box), rel=2e-6)


def test_lattice_exact_wall_vertices_empty_domain_and_detail(lattice_request):
    from sjtu_tpmshx.applications.gui.ui.vis3d_lattice_worker import LatticeCache
    from sjtu_tpmshx.physical_models.tpms_geometry import _C_from_tL

    r = replace(lattice_request, dx=[.007], dy=[.007], dz=[.007], field=[[[310.]]], phase='S',
                t_mm=.4, delta=_C_from_tL('Gyroid', .4/7.))
    cache = LatticeCache()
    counts = []
    for detail in ('low', 'medium', 'high'):
        mesh, _ = cache.build(replace(r, detail=detail), threading.Event(), lambda *_: None)
        counts.append(mesh.n_cells)
        assert mesh.n_open_edges == 0
    assert 0 < counts[0] < counts[1] < counts[2]
    empty, _ = cache.build(replace(r, delta=10.), threading.Event(), lambda *_: None)
    assert empty.n_cells == empty['Ta'].size == 0


def test_lattice_solid_normals_face_into_enclosed_fluid_pockets(lattice_request):
    from sjtu_tpmshx.applications.gui.ui.vis3d_lattice_worker import LatticeCache

    cache = LatticeCache()
    volume = 0.
    for phase in ('A', 'B', 'S'):
        r = replace(lattice_request, topology='Diamond', phase=phase, detail='low',
                    dx=[.007], dy=[.007], dz=[.007], field=[[[300.]]], t_mm=.25, delta=0.)
        mesh, _ = cache.build(r, threading.Event(), lambda *_: None)
        assert mesh.n_open_edges == 0
        volume += mesh.volume
    assert volume == pytest.approx(7.**3, rel=2e-6)


def test_lattice_cache_reuses_geometry_and_evicts_the_oldest_color(lattice_request, monkeypatch):
    from sjtu_tpmshx.applications.gui.ui import vis3d_lattice_worker as lattice
    from sjtu_tpmshx.applications.gui.ui.vis3d_lattice_worker import LatticeCache

    for ram, limit in ((8 * 1024**3, 256_000_000), (16 * 1024**3, 512_000_000)):
        monkeypatch.setattr(lattice, '_physical_memory_bytes', lambda: ram)
        assert LatticeCache().limit_bytes == limit

    stop = threading.Event()
    def build(cache, request):
        return cache.build(request, stop, lambda *_: None)[0]

    first = lattice_request
    second = replace(first, result_id='run2', field=first.field + 7.)
    third = replace(first, field_name='pressure', field=first.field * 20.)
    sizing = LatticeCache()
    colors_size = build(sizing, first)['Ta'].nbytes
    cache = LatticeCache(limit_bytes=sizing.size_bytes + colors_size)
    a, b = build(cache, first), build(cache, second)
    assert np.shares_memory(a.points, b.points)
    np.testing.assert_allclose(b['Ta'], a['Ta'] + 7.)
    assert np.shares_memory(a['Ta'], build(cache, first)['Ta'])
    c = build(cache, third)
    assert np.shares_memory(a.points, c.points)
    assert cache.size_bytes == cache.limit_bytes
    assert np.shares_memory(a['Ta'], build(cache, first)['Ta'])
    assert not np.shares_memory(b['Ta'], build(cache, second)['Ta'])
    assert not np.shares_memory(a.points, build(cache, replace(first, t_mm=.33)).points)
    tiny = LatticeCache(limit_bytes=1)
    _, retained = tiny.build(first, stop, lambda *_: None)
    assert not retained and tiny.size_bytes == 0


def test_lattice_worker_cancels_superseded_requests_and_releases_cache(lattice_request, monkeypatch):
    from PySide6.QtCore import QCoreApplication
    from sjtu_tpmshx.applications.gui.ui import vis3d_lattice_worker as lattice

    builder = lattice.LatticeBuilder()
    entered, proceed = threading.Event(), threading.Event()
    main_thread = threading.get_ident()
    sampler = lattice.signed_wall_grid
    def sample(*args):
        assert threading.get_ident() != main_thread
        entered.set()
        assert proceed.wait(5)
        return sampler(*args)

    monkeypatch.setattr(lattice, 'signed_wall_grid', sample)
    delivered, cancelled, failures = [], [], []
    builder.ready.connect(lambda generation, mesh, retained: delivered.append((generation, mesh)))
    builder.cancelled.connect(cancelled.append)
    builder.failed.connect(lambda generation, message: failures.append(message))
    try:
        old = builder.submit(lattice_request)
        assert entered.wait(5)
        current = builder.submit(replace(lattice_request, phase='B'))
        proceed.set()
        assert builder._pool.waitForDone(10000)
        QCoreApplication.processEvents()
        assert not failures and cancelled == [old]
        assert [generation for generation, mesh in delivered] == [current]
        assert delivered[0][1].n_open_edges == 0
    finally:
        proceed.set()
        builder.close()
    assert builder.cache.size_bytes == 0


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_standard_binding_matches_independent_scan_and_copies_columns(geometry, topology):
    cells = np.array([[4., 7.], [5., 8.]], order='F')
    walls = np.array([[.3, .6], [.4, .3]], order='F')
    actual = geometry.standard_fields(topology, cells, walls, 16., chi_s=.7, N=13)
    expected = {key: np.empty(cells.shape) for key in actual}
    phi = reference._phi_grid(topology, 13)
    for index in np.ndindex(cells.shape):
        length, wall = float(cells[index]), float(walls[index])
        C = reference._C_from_tL(topology, wall / length)
        epsilon = reference._eps_from_C(phi, C)
        area = reference._A0_from_C(phi, C, length / 1000., 13)
        values = dict(epsilon=epsilon, epsilon_A=.5 * epsilon, epsilon_B=.5 * epsilon,
                      A_0=area, D_h=4. * (.5 * epsilon) / area,
                      K_ss=.7 * (1. - epsilon) * 16.)
        for key in expected:
            expected[key][index] = values[key]
    for key, value in actual.items():
        np.testing.assert_array_equal(value, expected[key])
        assert value.dtype == np.float64 and value.flags.c_contiguous and value.flags.writeable
        assert not np.shares_memory(value, cells) and not np.shares_memory(value, walls)
        assert all(not np.shares_memory(value, other)
                   for other_key, other in actual.items() if other_key != key)
    actual['epsilon_A'].fill(-1.)
    np.testing.assert_array_equal(actual['epsilon_B'], expected['epsilon_B'])
    again = geometry.standard_fields(topology, cells, walls, 16., chi_s=.7, N=13)
    for key in expected:
        np.testing.assert_array_equal(again[key], expected[key])


def test_raw_binding_keeps_degenerate_lut_nodes(geometry):
    raw = geometry.raw_fields('Diamond', [7.], [.4], N=1)
    np.testing.assert_array_equal(raw['epsilon'], [0.])
    np.testing.assert_array_equal(raw['A_0'], [0.])
    with pytest.raises(ValueError, match='Degenerate TPMS geometry'):
        geometry.standard_fields('Diamond', [7.], [.4], 16., N=1)
    empty = geometry.raw_fields('Diamond', np.empty((2, 0)), np.empty((2, 0)), N=1)
    assert all(value.shape == (2, 0) and value.flags.writeable for value in empty.values())


def test_lut_binding_keeps_its_distinct_denominator_and_material_order(geometry):
    epsilon, area = np.array([.8, .2]), np.array([0., 1e-30])
    actual = geometry.lut_fields('Gyroid', epsilon, area, 16., chi_s=.25)
    diameter = 2. * epsilon / (area + 1e-30)
    expected = dict(epsilon=epsilon, epsilon_A=epsilon / 2., epsilon_B=epsilon / 2.,
                    A_0=area, D_h=diameter, K_ss=.25 * (1. - epsilon) * 16., r_h=diameter / 2.)
    for key, value in expected.items():
        np.testing.assert_array_equal(actual[key], value)
        assert actual[key].flags.writeable and actual[key].flags.c_contiguous
        assert not np.shares_memory(actual[key], epsilon) and not np.shares_memory(actual[key], area)
    assert actual['D_h'][1] != 2. * epsilon[1] / area[1]
    material = geometry.material_fields('Gyroid', epsilon, 16., chi_s=.25)
    np.testing.assert_array_equal(material['K_ss'], expected['K_ss'])
    np.testing.assert_array_equal(material['chi_s'], [.25, .25])
    np.testing.assert_array_equal(geometry.chi_fields('Gyroid', epsilon, chi_s=.25), [.25, .25])


@pytest.mark.parametrize('diameter', [
    .003,
    np.float64(.007),
    np.array([[.002, np.nan], [.003, 0.]], order='F'),
    np.empty((2, 0)),
], ids=['scalar', 'numpy-scalar', 'array-nan', 'empty'])
def test_hydraulic_radius_preserves_values_and_owns_its_output(geometry, diameter):
    expected = np.asarray(diameter, dtype=np.float64) / 2.
    actual = geometry.hydraulic_radius(diameter)
    np.testing.assert_array_equal(actual, expected)
    assert actual.shape == expected.shape and actual.dtype == np.float64
    assert actual.flags.c_contiguous and actual.flags.writeable
    assert not np.shares_memory(actual, np.asarray(diameter))
    again = geometry.hydraulic_radius(diameter)
    assert not np.shares_memory(actual, again)
    actual.fill(-7.)
    np.testing.assert_array_equal(again, expected)
    np.testing.assert_array_equal(geometry.hydraulic_radius(diameter), expected)


def test_public_quick_design_replays_without_geometry_calls(geometry, tmp_path, monkeypatch):
    from sjtu_tpmshx.applications.design.cases import DesignCase
    from tests.python.native.shared_library import library_path
    from sjtu_tpmshx.postprocess.api import evaluate
    from sjtu_tpmshx.preprocess.api import prepare_quick_design
    from sjtu_tpmshx.run_control.module_ports import RunControl
    from sjtu_tpmshx.file_io.case_io import load_case, save_case
    from sjtu_tpmshx.solvers.api import run_case

    control = RunControl(native_library=str(library_path()), cpu_threads=1)
    condition = DesignCase(1, 'air', 688.23, 1088700., .2855,
                           'water', 320., 200000., .5, 30000., .075, .05)
    case = prepare_quick_design(condition, 'Diamond', 7., .5, .084, .025,
                                case_id='geometry-free-quick-design-replay')
    archive = tmp_path / 'case.yaml'
    save_case(case, archive)
    restored = load_case(archive)

    def forbidden(*args, **kwargs):
        pytest.fail('prepared Quick Design execution queried native geometry')

    monkeypatch.setattr(geometry, '_call', forbidden)
    result = run_case(restored, control)
    assert result.case_id == restored.case_id and result.backend_id == 'cpp'
    assert result.run_status['converged'] is True
    assert result.fields and all(np.isfinite(value).all() for value in result.fields.values())
    metric = evaluate(result).metrics['Q']
    assert metric.status == 'available' and metric.spec.unit == 'W'
    assert metric.value is not None and metric.value > 0.


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_co2_binding_normalizes_nodes_before_interpolation(geometry, topology):
    from sjtu_tpmshx.model_configs.model_parameters import load_co2_coefficients

    nodes = load_co2_coefficients()['topologies'][topology]['geometry_nodes']
    lookup = {(node['L_mm'], node['t_mm']): node for node in nodes}
    def normalized(length, wall):
        node = lookup[length, wall]
        cell = length * 1e-3
        return np.array([node['epsilon_single'], node['Dh_m'] / cell,
                         node['A0_single_per_m'] * cell])
    length, wall = 5.25, .42
    wl, wt = (length - 5.) / (6. - 5.), (wall - .4) / (.5 - .4)
    values = ((1. - wt) * ((1. - wl) * normalized(5., .4) + wl * normalized(6., .4))
              + wt * ((1. - wl) * normalized(5., .5) + wl * normalized(6., .5)))
    cell = length * 1e-3
    epsilon = 2. * values[0]
    expected = dict(epsilon=epsilon, epsilon_A=values[0], epsilon_B=values[0],
                    A_0=values[2] / cell, D_h=values[1] * cell,
                    K_ss=.5 * (1. - epsilon) * 16.)
    actual = geometry.co2_fields(topology, [length], [wall], 16., chi_s=.5)
    for key, value in expected.items():
        np.testing.assert_array_equal(actual[key], [value])
    with pytest.raises(ValueError, match='no extrapolation'):
        geometry.co2_fields(topology, [8.01], [.4], 16.)


def _side_reference(phi, C, delta, length_m, n):
    from skimage import measure

    solid = (phi >= delta - C) & (phi <= delta + C)
    masks = (phi < delta - C, phi > delta + C)
    results = []
    for mask, level in zip(masks, (delta - C, delta + C)):
        epsilon = float(np.mean(mask))
        count = 0
        for axis in range(3):
            first, second = [slice(None)] * 3, [slice(None)] * 3
            first[axis], second[axis] = slice(None, -1), slice(1, None)
            first, second = tuple(first), tuple(second)
            count += int(np.count_nonzero(solid[first] & mask[second]))
            count += int(np.count_nonzero(mask[first] & solid[second]))
        area = count * (length_m / n)**2 / (length_m**3 * reference._AREA_CORRECTION)
        verts, faces, _, _ = measure.marching_cubes(phi, level=level, spacing=(length_m / n,) * 3)
        mc_area = float(measure.mesh_surface_area(verts, faces)) / length_m**3
        results.append((epsilon, area, 4. * epsilon / mc_area))
    return results


def test_split_and_prepared_side_binding_preserve_four_surfaces(geometry, monkeypatch):
    phi = reference._phi_grid('Gyroid', 128)
    C = reference._C_from_tL('Gyroid', .6 / 7.)
    sides = _side_reference(phi, C, .12, .007, 128)
    baseline = _side_reference(phi, C, 0., .007, 128)
    fraction = sides[0][0] / (sides[0][0] + sides[1][0])
    assert geometry.split_from_index('Gyroid', 7., .6, .12) == fraction
    prepared = geometry.prepare_sides('Gyroid', 7., .6, .12)
    assert prepared['split_A'] == fraction
    for index, side in enumerate(('A', 'B')):
        np.testing.assert_array_equal(prepared['side_geometry'][side],
            [sides[index][1], sides[index][2], baseline[index][1], baseline[index][2]])
    epsilon = np.array([.7, .4])
    fields = geometry.split_fields(epsilon, fraction)
    np.testing.assert_array_equal(fields['epsilon_A'], epsilon * fraction)
    np.testing.assert_array_equal(fields['epsilon_B'], epsilon * (1. - fraction))
    def forbidden(*args, **kwargs):
        pytest.fail('zero-offset preparation created a phi index')
    monkeypatch.setattr(native, '_index', forbidden)
    assert geometry.prepare_sides('Gyroid', 7., .6, 0.) == {'split_A': .5, 'side_geometry': None}


def test_index_eviction_retains_library_until_the_owner_is_released(geometry, monkeypatch):
    native._cached_index.cache_clear()
    native._load_library.cache_clear()
    released = []
    release = native._release_index
    def observed(destroy, library, handle):
        released.append(handle.value)
        release(destroy, library, handle)
    monkeypatch.setattr(native, '_release_index', observed)
    try:
        index, _ = native._index('Diamond', 8)
        handle = index.handle.value
        index_ref, library_ref = weakref.ref(index), weakref.ref(index.library)
        assert native._index('Diamond', 8)[0] is index
        native._load_library.cache_clear()
        native._index('Gyroid', 8)
        native._index('Diamond', 13)
        gc.collect()
        assert native._cached_index.cache_info().currsize == 2
        assert library_ref() is index.library and index._finalizer.alive
        assert handle not in released
        del index
        gc.collect()
        assert index_ref() is None and library_ref() is None
        assert released.count(handle) == 1
    finally:
        native._cached_index.cache_clear()
        native._load_library.cache_clear()
        gc.collect()


def test_phi_cache_is_read_only_and_does_not_build_an_index(geometry, monkeypatch):
    native._cached_phi.cache_clear()
    def forbidden(*args, **kwargs):
        pytest.fail('phi export created a sorted count index')
    monkeypatch.setattr(native, '_index', forbidden)
    try:
        phi = geometry.phi_grid('Diamond', 13)
        assert geometry.phi_grid('Diamond', 13) is phi
        assert phi.flags.owndata and phi.flags.c_contiguous and not phi.flags.writeable
        np.testing.assert_array_equal(phi, reference._phi_grid('Diamond', 13))
        with pytest.raises(ValueError):
            phi[0, 0, 0] = 999.
        for n in (4, 8, 16, 17):
            geometry.phi_grid('Diamond', n)
        assert native._cached_phi.cache_info().currsize == 4
        rebuilt = geometry.phi_grid('Diamond', 13)
        assert rebuilt is not phi and not rebuilt.flags.writeable
        np.testing.assert_array_equal(rebuilt, phi)
    finally:
        native._cached_phi.cache_clear()


def test_public_scalar_cache_does_not_cache_the_current_material_setting(geometry, monkeypatch):
    from sjtu_tpmshx.physical_models import tpms_geometry, tpms_props

    tpms_geometry.compute_geometry.cache_clear()
    monkeypatch.delenv('TPMSHX_CHI_S', raising=False)
    try:
        first = tpms_props.geometry('Gyroid', 7., .6, 16., N=32)
        assert type(first['epsilon']) is float and type(first['K_ss']) is float
        assert isinstance(first['A_0'], np.float64) and isinstance(first['D_h'], np.float64)
        original_diameter, epsilon = first['D_h'], first['epsilon']
        first['D_h'] = -1.
        monkeypatch.setenv('TPMSHX_CHI_S', '.5')
        second = tpms_props.geometry('Gyroid', 7., .6, 16., N=32)
        assert second['D_h'] == original_diameter and second['K_ss'] == .5 * (1. - epsilon) * 16.
        monkeypatch.setenv('TPMSHX_CHI_S', 'invalid')
        explicit = tpms_props.geometry('Gyroid', 7., .6, 16., chi_s=.25, N=32)
        assert explicit['K_ss'] == .25 * (1. - epsilon) * 16.
        with pytest.raises(ValueError):
            tpms_props.geometry('Gyroid', 7., .6, 16., N=32)
        assert tpms_geometry.compute_geometry.cache_info().misses == 1
        assert tpms_geometry.compute_geometry.cache_info().maxsize == 32768
    finally:
        tpms_geometry.compute_geometry.cache_clear()


@pytest.mark.parametrize('system,machine,host,name', [
    ('darwin', 'arm64', 'macos-arm64', 'libtpmshx_geometry_shared.dylib'),
    ('win32', 'AMD64', 'windows-x64', 'tpmshx_geometry_shared.dll'),
])
@pytest.mark.parametrize('frozen', [False, True])
def test_loader_uses_the_selected_platform_and_package_layout(
        tmp_path, monkeypatch, system, machine, host, name, frozen):
    package, bundle = tmp_path / 'package', tmp_path / 'bundle'
    path = bundle / 'native' / name if frozen else package / 'solvers/native/lib' / host / name
    path.parent.mkdir(parents=True)
    path.touch()
    monkeypatch.delenv('TPMSHX_GEOMETRY_LIBRARY', raising=False)
    monkeypatch.setattr(native, 'sys', SimpleNamespace(platform=system, frozen=frozen, _MEIPASS=str(bundle)))
    monkeypatch.setattr(native, 'platform', SimpleNamespace(machine=lambda: machine))
    monkeypatch.setattr(native, 'PUBLISHED_LIBRARY_DIR', package / 'solvers/native/lib')
    assert native._library_path() == str(path.resolve())


def test_explicit_library_path_wins_and_missing_files_do_not_fall_back(tmp_path, monkeypatch):
    selected = tmp_path / 'chosen-library'
    selected.touch()
    monkeypatch.setattr(native, 'sys', SimpleNamespace(platform='unsupported'))
    monkeypatch.setattr(native, 'platform', SimpleNamespace(machine=lambda: 'unsupported'))
    monkeypatch.setenv('TPMSHX_GEOMETRY_LIBRARY', str(selected))
    assert native._library_path() == str(selected.resolve())
    monkeypatch.setenv('TPMSHX_GEOMETRY_LIBRARY', str(tmp_path / 'missing'))
    with pytest.raises(FileNotFoundError, match='prebuilt native geometry library is missing'):
        native._library_path()
    monkeypatch.setenv('TPMSHX_GEOMETRY_LIBRARY', '')
    with pytest.raises(ValueError, match='must name a prebuilt geometry library'):
        native._library_path()


@pytest.mark.parametrize('abi,missing,message', [
    (3, None, 'unsupported native geometry ABI 3'),
    (2, 'lut_batch', 'lacks tpmshx_geometry_lut_batch_v1'),
])
def test_prebuilt_library_rejects_unsupported_abi_or_missing_symbols(monkeypatch, abi, missing, message):
    def version():
        return abi
    def unused(*args):
        return 0
    symbols = {'tpmshx_geometry_abi_version_v1': version,
               'tpmshx_geometry_index_destroy_v1': unused}
    symbols.update({f'tpmshx_geometry_{name}_v1': unused
                    for name in native._SIGNATURES if name != missing})
    monkeypatch.setattr(native.ct, 'CDLL', lambda path: SimpleNamespace(**symbols))
    with pytest.raises(ValueError, match=message):
        native._NativeLibrary('prebuilt-test-library')


@pytest.mark.parametrize('status,exception', [(1, ValueError), (2, ZeroDivisionError), (3, RuntimeError)])
def test_c_error_status_preserves_its_python_exception_class(status, exception):
    def failed(error, capacity):
        error.value = b'geometry boundary failure'
        return status
    with pytest.raises(exception, match='geometry boundary failure'):
        native._call(failed)


def test_import_and_archived_result_read_need_no_geometry_library(tmp_path):
    from sjtu_tpmshx.data_types.field_result import FieldResult
    from sjtu_tpmshx.file_io.result_io import save_result

    grid = dict(dimension=2, length_unit='m', axis_order=('x', 'y'),
                dx=np.array([.1]), dy=np.array([.2]),
                x_edges=np.array([0., .1]), y_edges=np.array([0., .2]))
    result = FieldResult('archived-geometry', 'case', 'cpp', grid=grid,
        fields={'Ta': np.array([[310.]])},
        field_metadata={'Ta': dict(unit='K', axes=('x', 'y'), location='cell', state='raw last return')},
        run_status={'execution': 'completed', 'converged': False}, metadata={'dimension': 2})
    path = save_result(result, tmp_path / 'archived.h5')
    environment = dict(os.environ, TPMSHX_GEOMETRY_LIBRARY=str(tmp_path / 'missing-geometry'))
    child = subprocess.run([sys.executable, '-c', r'''
import ctypes
import sys
import h5py
import numpy

def forbidden(*args, **kwargs):
    raise AssertionError('an offline import or read attempted CDLL loading')
ctypes.CDLL = forbidden
from sjtu_tpmshx.cpp_interface import _native_geometry as native
from sjtu_tpmshx.file_io.result_io import load_result
from sjtu_tpmshx.postprocess.api import evaluate
result = load_result(sys.argv[1])
assert result.result_id == 'archived-geometry' and result.fields['Ta'][0, 0] == 310.
assert result.run_status['converged'] is False
assert native._load_library.cache_info().currsize == 0
assert native._cached_index.cache_info().currsize == 0
assert native._cached_phi.cache_info().currsize == 0
for prefix in ('sjtu_tpmshx.solvers', 'sjtu_tpmshx.preprocess', 'CoolProp', 'PySide6'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
try:
    native.phi_grid('Gyroid', 8)
except FileNotFoundError as error:
    assert 'missing-geometry' in str(error)
else:
    raise AssertionError('a geometry call ignored its missing selected library')
''', str(path)], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stderr
