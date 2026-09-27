"""Offline screening uses native inputs and keeps unsupported/rejected metrics."""
from dataclasses import replace
import numpy as np
import pytest
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.postprocess.api import evaluate


def _native_result(dimension):
    shape = (2,) * dimension
    pressure = np.full(shape, 10.)
    pressure[:, 0] = 20.
    face_shape = (2,) if dimension == 2 else (2, 2)
    evidence = dict(P_gauge_Pa=pressure, inlet_fraction=np.ones(face_shape),
                    outlet_fraction=np.ones(face_shape), dx_m=np.full(2, .1), dz_m=np.full(2, .15))
    axes = tuple('xyz'[:dimension])
    grid = dict(dimension=dimension, length_unit='m', axis_order=axes,
                dx=np.full(2, .1), dy=np.full(2, .2), dz=np.full(2, .15))
    for axis in axes:
        grid[axis + '_edges'] = np.r_[0., np.cumsum(grid['d' + axis])]
    values = dict(Tb=np.full(shape, 300.), Ts=np.full(shape, 320.),
                  h_vB_arr=np.full(shape, 10.), eps_arr=np.full(shape, .5))
    units = dict(Tb='K', Ts='K', h_vB_arr='W/(m3 K)', eps_arr='1')
    return FieldResult('native', 'case', 'fixture', grid=grid, fields=values,
        field_metadata={key: dict(unit=units[key], axes=axes, location='cell', state='native')
                        for key in values},
        pressure_evidence=dict(A=evidence, B=evidence),
        run_status=dict(execution='completed', converged=False),
        metadata=dict(dimension=dimension, mode=f'screening_{dimension}d',
                      solid_density_kg_m3=2700., cached_Q=99999.))


@pytest.mark.parametrize('dimension,q', [(2, 16.), (3, 4.8)])
def test_native_screening_reductions(dimension, q):
    result = _native_result(dimension)
    shape = (2,) * dimension
    metrics = evaluate(result).metrics
    assert metrics['Q'].value == pytest.approx(q)
    assert metrics['dP_A'].value == 10.
    assert metrics['mass'].value == pytest.approx(108. if dimension == 2 else 32.4)
    assert metrics['T_out_A'].status == 'unsupported'
    changed = replace(result, fields={**result.fields, 'Ts': np.full(shape, 310.)})
    assert evaluate(changed).metrics['Q'].value == pytest.approx(q / 2.)
    rejected = replace(result, run_status=dict(execution='rejected', converged=False, reason='choked'))
    assert evaluate(rejected).metrics['Q'].status == 'invalid'
    assert evaluate(rejected).metrics['mass'].value == metrics['mass'].value


@pytest.mark.parametrize('dimension,port,fraction', [
    (2, 'inlet', 0.), (2, 'outlet', 0.),
    (3, 'inlet', 0.), (3, 'outlet', 0.),
    (2, 'inlet', .01), (2, 'outlet', .5),
])
def test_empty_pressure_faces_remain_invalid_through_hdf5_and_cli(
        tmp_path, dimension, port, fraction):
    from sjtu_tpmshx.io.metrics_io import load_metrics
    from sjtu_tpmshx.io.result_io import load_result, save_result
    from sjtu_tpmshx.workflows.cli import main

    result = _native_result(dimension)
    baseline = evaluate(result).metrics
    pressure = dict(result.pressure_evidence['A'])
    key = port + '_fraction'
    pressure[key] = np.full_like(pressure[key], fraction)
    result = replace(result, pressure_evidence={**result.pressure_evidence, 'A': pressure})
    path = save_result(result, tmp_path / 'native.h5')
    loaded = load_result(path)
    metrics = evaluate(loaded).metrics
    output = tmp_path / 'metrics.json'
    exit_code = main(['postprocess', str(path), str(output)])
    archived = load_metrics(output)

    assert exit_code == 2
    assert archived.source_result_id == loaded.result_id
    assert loaded.run_status == result.run_status
    for current in (metrics, archived.metrics):
        assert current['dP_A'].status == 'invalid'
        assert current['dP_A'].value is None
        assert 'pressure faces' in current['dP_A'].reason
        for name in ('Q', 'mass', 'dP_B', 'T_out_A'):
            assert current[name] == baseline[name]
