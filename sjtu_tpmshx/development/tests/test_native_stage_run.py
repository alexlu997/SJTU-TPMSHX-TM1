"""Compare the independent native stage caller with the existing workflow."""
from dataclasses import asdict
import json
import os
from pathlib import Path

import numpy as np
import pytest

from sjtu_tpmshx.compute import compute
from sjtu_tpmshx.shared.domain.compute_config import ComputeConfig
from sjtu_tpmshx.shared.domain.module_ports import RunControl
from sjtu_tpmshx.shared.domain.portable_data import mutable_data
from sjtu_tpmshx.development.tests.native.shared_library import library_path


@pytest.mark.slow
def test_independent_stage_fields_metrics_and_qualification():
    root = Path(__file__).resolve().parents[3]
    evidence = Path(os.environ.get('TPMSHX_STAGE_RESULT_DIR', root / '.cache/native-deps/build/stage-result'))
    if not (evidence / 'fields.tsv').is_file():
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS'):
            pytest.fail('Run build_native_dependencies.py check-stages before this test')
        pytest.skip('the installed stage caller has not run')
    config = ComputeConfig.from_dict(json.loads((root / 'examples/three_module/air_2d.json').read_text()))
    _, result, performance = compute(config, control=RunControl(cpu_threads=2, native_library=str(library_path())))
    records = [line.split('\t') for line in (evidence / 'fields.tsv').read_text().splitlines()]
    assert len(records) == len(result.fields)
    assert {name for name, _, _ in records} == set(result.fields)
    for name, nx, ny in records:
        actual = np.fromfile(evidence / (name + '.bin')).reshape(int(nx), int(ny))
        expected = np.asarray(result.fields[name])
        np.testing.assert_array_equal(actual.view(np.uint64), expected.view(np.uint64), err_msg=name)
    report = json.loads((evidence / 'metrics.json').read_text())
    assert report['metrics'] == {name: asdict(value) for name, value in performance.metrics.items()}
    qualification = mutable_data(performance.qualification)
    assert qualification['source_result_id'] == result.result_id
    assert report['qualification']['source_result_id'] == report['source_result_id']
    qualification['source_result_id'] = report['source_result_id']
    assert report['qualification'] == qualification


@pytest.mark.slow
@pytest.mark.parametrize('sample', ['cross-const', 'cross-mean', 'counter-const',
                                    'cross-warm', 'counter-mean', 'water-air', 'sco2-sco2'])
def test_independent_quick_design_stage(sample):
    from dataclasses import replace
    from sjtu_tpmshx.applications.design.cases import DesignCase
    from sjtu_tpmshx.preprocess.api import prepare_quick_design
    from sjtu_tpmshx.postprocess.api import evaluate
    from sjtu_tpmshx.solvers.api import run_case

    root = Path(__file__).resolve().parents[3]
    directory = Path(os.environ.get('TPMSHX_QUICK_STAGE_RESULT_DIR',
        root / '.cache/native-deps/build/quick-design-stage-result')) / sample
    if not (directory / 'fields.tsv').is_file():
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS'):
            pytest.fail('Run build_native_dependencies.py check-stages before this test')
        pytest.skip('the installed Quick Design stage caller has not run')
    point = DesignCase(**json.loads((root / 'examples/three_module/design_case.json').read_text()))
    arrangement = 'counter' if sample.startswith('counter') else 'cross'
    mode = 'mean' if sample.endswith('mean') else 'const'
    topology, length, height = 'Diamond', .05, .07 if arrangement == 'cross' else None
    if sample == 'water-air':
        point = replace(point, hot_fluid='water', cold_fluid='air', T_in_h=355., T_in_c=300.,
                        P_in_h=2e5, P_in_c=2e5, mdot_h=.2, mdot_c=.04)
        topology, length, height = 'Gyroid', .025, .06
    elif sample == 'sco2-sco2':
        point = replace(point, hot_fluid='sco2', cold_fluid='sco2', T_in_h=500., T_in_c=350.,
                        P_in_h=9e6, P_in_c=8e6, mdot_h=.2, mdot_c=.2)
        length, height = .025, .06
    initial = None
    if sample == 'cross-warm':
        initial = tuple(np.full((60, 40, 1), value) for value in
                        (point.T_in_h, point.T_in_c, (point.T_in_h + point.T_in_c) / 2.))
    case = prepare_quick_design(point, topology, 7., .5, .084, length, arrangement,
                               case_id=sample, prop_model=mode, height=height, init=initial)

    def exact(actual, expected, name):
        first, second = np.asarray(actual), np.asarray(expected)
        assert first.dtype == second.dtype == np.dtype('float64'), name
        assert first.shape == second.shape, name
        np.testing.assert_array_equal(first.view(np.uint64), second.view(np.uint64), err_msg=name)

    records = [line.split('\t') for line in (directory / 'prepared.tsv').read_text().splitlines()]
    expected_prepared = {key: value for key, value in case.grid.items()
                         if key in ('dx', 'dy', 'dz', 'x_edges', 'y_edges', 'z_edges')}
    expected_prepared.update(case.design_fields)
    if initial is not None:
        expected_prepared.update({f'initial_{i}': value for i, value in enumerate(initial)})
    assert {name for name, _ in records} == set(expected_prepared)
    for name, size in records:
        actual = np.fromfile(directory / (name + '.bin'))
        assert actual.size == int(size)
        exact(actual, np.asarray(expected_prepared[name]).ravel(), name)

    def scalars(filename):
        return {name: float(value) for name, value in
                (line.split('\t') for line in (directory / filename).read_text().splitlines())}

    p = case.parameters
    expected = {key: p[key] for key in ('Lx', 's', 'height', 'L_cell_m', 't_wall_m', 'A_0', 'D_h', 'k_s', 'tol')}
    expected['geometry_resolution'] = case.metadata['geometry_resolution']
    expected.update({key: p['controls'][key] for key in ('maxit', 'chunk', 'qtol', 'alpha')})
    if arrangement == 'counter':
        expected['chunk'], expected['qtol'] = 250, max(p['tol'] * 10, 1e-4)
    expected.update({f'pressure_fraction_{side}': value for side, value in p['inlet_pressure_fractions'].items()})
    actual = scalars('prepared-scalars.tsv')
    assert actual.keys() == expected.keys()
    for name, value in expected.items():
        exact(np.float64(actual[name]), np.float64(value), name)

    events = []
    result = run_case(case, RunControl(cpu_threads=2, progress=events.append,
                                       native_library=str(library_path())))
    performance = evaluate(result)
    assert events == [int(value) for value in (directory / 'progress.tsv').read_text().splitlines()]
    records = [line.split('\t') for line in (directory / 'fields.tsv').read_text().splitlines()]
    assert {name for name, *_ in records} == set(result.fields)
    for name, *shape in records:
        actual = np.fromfile(directory / ('field_' + name + '.bin')).reshape(tuple(map(int, shape)))
        exact(actual, result.fields[name], name)
    for name, unit, state in (line.split('\t') for line in (directory / 'metadata.tsv').read_text().splitlines()):
        assert result.field_metadata[name] == dict(unit=unit, state=state, axes=('x', 'y', 'z'), location='cell')
    expected = dict(converged=result.run_status['converged'], completed_passes=len(result.run_status['passes']))
    for index, item in enumerate(result.run_status['passes']):
        expected.update({f'pass_{index}_{key}': item[key] for key in ('converged', 'iterations', 'residual')})
    for side in ('A', 'B'):
        pressure = result.pressure_evidence[side]
        expected.update({f'pressure_in_{side}': pressure['inlet_absolute_Pa'],
                         f'pressure_out_{side}': pressure['outlet_absolute_Pa'],
                         f'pressure_choked_{side}': pressure['choked']})
        expected.update({f'{key}_{side}': value for key, value in result.metadata['properties'][side].items()})
        expected[f'speed_{side}'] = result.boundary_fluxes[side]['velocity_m_s']
    actual = scalars('run-scalars.tsv')
    assert actual.keys() == expected.keys()
    for name, value in expected.items():
        exact(np.float64(actual[name]), np.float64(value), name)
    report = json.loads((directory / 'metrics.json').read_text())
    assert report['metrics'] == {name: asdict(value) for name, value in performance.metrics.items()}
    qualification = mutable_data(performance.qualification)
    qualification['source_result_id'] = report['source_result_id']
    assert report['qualification'] == qualification
