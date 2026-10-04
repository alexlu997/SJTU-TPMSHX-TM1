"""Portable conservative energy uses captured powers, including SOU outlets."""
from dataclasses import replace
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.postprocess.metrics import evaluate

FACES = ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')


def result_fixture(dimension, algorithm='temperature_sou'):
    shape = (2, 3, 1 if dimension == 2 else 2)
    axes = tuple('xyz'[:dimension])
    grid = dict(dimension=dimension, length_unit='m', axis_order=axes)
    for axis, size in zip(axes, shape):
        grid['d' + axis] = np.arange(1, size + 1, dtype=float) / 10
        grid[axis + '_edges'] = np.r_[0., np.cumsum(grid['d' + axis])]
    mx = np.broadcast_to(np.arange(1., shape[1]*shape[2] + 1).reshape(shape[1:]),
                         (shape[0] + 1, *shape[1:])).copy()
    mx[-1, 0, 0] = -9.  # Reverse outlet flow must not weight outlet temperature.
    masses = (mx, np.zeros((shape[0], shape[1] + 1, shape[2])),
              np.zeros((shape[0], shape[1], shape[2] + 1)))
    common_mass = tuple(face[..., 0] for face in masses[:2]) if dimension == 2 else masses
    ta = np.arange(np.prod(shape), dtype=float).reshape(shape) + 300.
    tb = np.full(shape, 310.)
    plane_shapes = (shape[1:], shape[1:], (shape[0], shape[2]),
                    (shape[0], shape[2]), shape[:2], shape[:2])
    # Hand-specified outward powers, not reconstructed from the cell h below.
    totals_a = (-31., 17., 4., -5., 0., 0.) if dimension == 2 else (-31., 17., 4., -6., 2., -1.)
    totals_b = (10., -1., -8., 14., 0., 0.) if dimension == 2 else (10., -1., -8., 11., 3., 0.)
    powers = {side: {name: np.full(size, total / np.prod(size))
                     for name, size, total in zip(FACES, plane_shapes, totals)}
              for side, totals in (('A', totals_a), ('B', totals_b))}
    native = dict(h_A=np.full(shape, 100.), h_B=np.full(shape, 200.),
        h_in_A=300., h_in_B=100., mass_flux_A=masses, mass_flux_B=masses,
        energy_algorithm=algorithm, energy_algorithm_version=1, boundary_power=powers,
        boundary_power_units='W/m' if dimension == 2 else 'W', physical_boundary_complete=True,
        actual_conductivity_A=np.full(shape, .1), actual_conductivity_B=np.full(shape, .2))
    return FieldResult('conservative', 'case', 'fixture', grid=grid,
        fields={'Ta': ta[..., 0] if dimension == 2 else ta,
                'Tb': tb[..., 0] if dimension == 2 else tb},
        field_metadata={side: dict(unit='K', axes=axes, location='cell', state='last thermal return')
                        for side in ('Ta', 'Tb')},
        boundary_fluxes=dict(true_h=native, mass_A=common_mass, mass_B=common_mass,
            mass_unit='kg/(s m)' if dimension == 2 else 'kg/s',
            report={side: {'direction': 0} for side in ('A', 'B')}),
        pressure_evidence={side: {'outlet_geom_frac': np.ones(shape[1])} for side in ('A', 'B')},
        run_status=dict(execution='completed', converged=False),
        metadata=dict(dimension=dimension, mode='full', thermal_mode='conservative_energy',
            quantity_basis='per_unit_depth' if dimension == 2 else 'total',
            parameters=dict(dir_A=0, dir_B=0),
            diagnostics=dict(richardson_info=dict(extrapolated=True)),
            reporting_reference=dict(Q=-999., Q_A=-999., Q_B=-999.)))


def sources(result, tmp_path):
    return result, load_result(save_result(result, tmp_path / 'result.h5'))


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('algorithm', ['temperature_fou', 'temperature_sou'])
def test_captured_power_and_transport_survive_save_replay(tmp_path, monkeypatch, dimension, algorithm):
    from sjtu_tpmshx.postprocess import metrics, three_d

    def forbidden(*args, **kwargs):
        pytest.fail('candidate duty must never reconstruct the legacy FOU boundary')
    monkeypatch.setattr(metrics, '_boundary_enthalpy_duty', forbidden)
    monkeypatch.setattr(three_d, '_boundary_enthalpy_duty', forbidden)
    result = result_fixture(dimension, algorithm)
    for source in sources(result, tmp_path):
        actual = evaluate(source).metrics
        assert actual['Q'].value == pytest.approx(15.)
        assert actual['Q_A'].value == pytest.approx(15.)
        assert actual['Q_B'].value == pytest.approx(-15.)
        assert actual['Q'].spec.unit == ('W/m' if dimension == 2 else 'W')
        assert actual['energy_imbalance_rel'].value == pytest.approx(0., abs=1e-15)
        assert actual['T_out_A'].value == pytest.approx(304.6 if dimension == 2 else 309.5)
        assert actual['T_out_B'].value == pytest.approx(310.)
        assert actual['mass_flow_A'].value == (15. if dimension == 2 else 30.)
        assert actual['mass_imbalance_rel_A'].value == pytest.approx(2/3 if dimension == 2 else 1/3)
        assert source.run_status['converged'] is False  # Metric availability cannot promote the solve.
        np.testing.assert_array_equal(source.boundary_fluxes['true_h']['actual_conductivity_A'],
                                      result.boundary_fluxes['true_h']['actual_conductivity_A'])
        if dimension == 2:
            assert actual['Q_richardson_A'].status == actual['Q_richardson_B'].status == 'unsupported'


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('defect', ['missing_algorithm', 'algorithm', 'missing_version', 'version',
    'float_version', 'bool_version', 'missing_units', 'units', 'missing_complete', 'incomplete',
    'truthy_complete', 'missing_power', 'missing_native'])
def test_candidate_header_does_not_fall_back_to_legacy_h(tmp_path, dimension, defect):
    result = result_fixture(dimension)
    flux = mutable_data(result.boundary_fluxes)
    native = flux['true_h']
    if defect == 'missing_native':
        del flux['true_h']
    elif defect.startswith('missing_'):
        key = {'algorithm': 'energy_algorithm', 'version': 'energy_algorithm_version',
               'units': 'boundary_power_units', 'complete': 'physical_boundary_complete',
               'power': 'boundary_power'}[defect.removeprefix('missing_')]
        del native[key]
    else:
        key, value = {'algorithm': ('energy_algorithm', 'legacy_h_fou'),
            'version': ('energy_algorithm_version', 2), 'float_version': ('energy_algorithm_version', 1.),
            'bool_version': ('energy_algorithm_version', True),
            'units': ('boundary_power_units', 'W' if dimension == 2 else 'W/m'),
            'incomplete': ('physical_boundary_complete', False),
            'truthy_complete': ('physical_boundary_complete', 1)}[defect]
        native[key] = value
    for source in sources(replace(result, boundary_fluxes=flux), tmp_path):
        actual = evaluate(source).metrics
        for name in ('Q', 'Q_A', 'Q_B', 'energy_imbalance_rel'):
            assert actual[name].status == ('insufficient_data' if defect.startswith('missing_') else 'invalid')
            assert actual[name].value is None
        assert actual['T_out_A'].status == actual['mass_flow_A'].status == 'available'


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('defect', ['missing_side', 'missing_face', 'extra', 'rank', 'empty',
                                   'pair_shape', 'grid_shape', 'z_extent', 'nan', 'inf'])
def test_power_plane_errors_are_side_specific_after_archival(tmp_path, dimension, defect):
    result = result_fixture(dimension)
    flux = mutable_data(result.boundary_fluxes)
    powers = flux['true_h']['boundary_power']
    side = powers['A']
    if defect == 'missing_side':
        del powers['A']
    elif defect == 'missing_face':
        del side['z+']
    elif defect == 'extra':
        side['other'] = np.zeros((2, 3))
    elif defect == 'rank':
        side['x-'] = side['x-'].ravel()
    elif defect == 'empty':
        side['x-'] = side['x-'][:0]
    elif defect == 'pair_shape':
        side['x+'] = np.zeros((4, side['x+'].shape[1]))
    elif defect in ('grid_shape', 'z_extent'):
        shape = (4, 3, 1 if dimension == 2 else 2) if defect == 'grid_shape' else (2, 3, 3)
        for axis in range(3):
            plane = tuple(n for index, n in enumerate(shape) if index != axis)
            for name in FACES[2*axis:2*axis+2]:
                side[name] = np.zeros(plane)
    else:
        side['z+'][0, 0] = np.nan if defect == 'nan' else np.inf
    for source in sources(replace(result, boundary_fluxes=flux), tmp_path):
        actual = evaluate(source).metrics
        for name in ('Q', 'Q_A', 'energy_imbalance_rel'):
            assert actual[name].status == ('insufficient_data' if defect == 'missing_side' else 'invalid')
            assert actual[name].value is None
        assert actual['Q_B'].value == pytest.approx(-15.)
        assert actual['T_out_A'].status == actual['mass_flow_A'].status == 'available'


@pytest.mark.parametrize('dimension', [2, 3])
def test_zero_and_sequence_planes_need_no_h_or_conductivity_reconstruction(tmp_path, dimension):
    result = result_fixture(dimension)
    flux = mutable_data(result.boundary_fluxes)
    native = flux['true_h']
    for side in ('A', 'B'):
        native['boundary_power'][side] = {key: np.zeros_like(face).tolist()
                                        for key, face in native['boundary_power'][side].items()}
        native['h_' + side][:] = np.nan
        native['actual_conductivity_' + side][:] = np.nan
    for source in sources(replace(result, boundary_fluxes=flux), tmp_path):
        actual = evaluate(source).metrics
        assert actual['Q'].value == actual['Q_A'].value == actual['Q_B'].value == 0.
        assert actual['energy_imbalance_rel'].value == 0.


def test_saved_candidate_replays_in_fresh_process_without_solver_import(tmp_path):
    path = save_result(result_fixture(3), tmp_path / 'candidate.h5')
    process = subprocess.run([sys.executable, '-c', '''
import sys
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.postprocess.api import evaluate
result = load_result(sys.argv[1])
metrics = evaluate(result).metrics
assert result.metadata['thermal_mode'] == 'conservative_energy'
assert abs(metrics['Q_A'].value - 15.) < 1e-12
assert abs(metrics['Q_B'].value + 15.) < 1e-12
assert metrics['T_out_A'].value == 309.5
for prefix in ('sjtu_tpmshx.solvers', 'sjtu_tpmshx.preprocess', 'numba', 'PySide6', 'CoolProp'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
''', str(path)], capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
