"""Result state and unavailable metrics survive real persistent files."""
from dataclasses import replace
import json

import numpy as np
import pytest

from tm1.data_types.field_result import FieldResult
from tm1.data_types.metric_spec import MetricSpec
from tm1.data_types.performance_result import MetricValue, PerformanceResult
from tm1.file_io.metrics_io import load_metrics, save_metrics
from tm1.file_io.result_io import (
    load_result,
    load_result_design_field,
    load_result_field,
    load_result_header,
    save_result,
)
from tm1.file_io.hdf5_data import write_record
from tests.python.io_tm1.io_support import sample_case
from tests.python.io_tm1.test_result_declarations import archived_native_result
from tm1.postprocess.api import evaluate


@pytest.mark.parametrize('change', ['temperature_unit', 'dimension', 'mode'])
def test_result_file_rejects_conflicting_physical_declarations(tmp_path, change):
    result = FieldResult('result', 'case', 'fixture', grid=sample_case().grid,
        fields={'Ta': np.full((2, 2), 350.)},
        field_metadata={'Ta': dict(unit='K', axes=('x', 'y'), location='cell', state='raw')},
        run_status={'execution': 'completed', 'converged': True},
        metadata={'dimension': 2, 'mode': 'screening_2d'})
    if change == 'temperature_unit':
        result = replace(result, fields={'Ta': result.fields['Ta'] - 273.15},
                         field_metadata={'Ta': {**result.field_metadata['Ta'], 'unit': 'degC'}})
    else:
        result = replace(result, metadata={**result.metadata,
                         **({'dimension': 3} if change == 'dimension' else {'mode': 'screening_3d'})})
    path = tmp_path / 'results.h5'
    # Write as an external producer, bypassing the public writer's validation.
    write_record(path, result, 'FieldResult')
    with pytest.raises(ValueError, match='unit|dimension'):
        load_result(path)
    with pytest.raises(ValueError, match='unit|dimension'):
        load_result_field(path, 'Ta')
    with pytest.raises(ValueError, match='unit|dimension'):
        load_result_header(path)
    with pytest.raises(ValueError, match='unit|dimension'):
        save_result(result, tmp_path / 'invalid.h5')
    with pytest.raises(ValueError, match='unit|dimension'):
        evaluate(result)


def test_nonconverged_result_is_preserved_and_cancelled_archive_rejected(tmp_path):
    result = FieldResult('result', 'synthetic', 'fixture', grid=sample_case().grid,
        fields={'Ta': np.full((2, 2), 310.)},
        field_metadata={'Ta': dict(unit='K', axes=('x', 'y'), location='cell', state='raw last thermal return')},
        run_status={'execution': 'completed', 'converged': False},
        metadata={'diagnostic': float('nan'), 'warnings': ('not converged',)})
    path = tmp_path / 'results.h5'
    save_result(result, path)
    loaded = load_result(path)
    assert loaded.run_status['converged'] is False
    assert np.isnan(loaded.metadata['diagnostic'])
    np.testing.assert_array_equal(loaded.fields['Ta'], result.fields['Ta'])
    with pytest.raises(ValueError, match='completed'):
        save_result(replace(result, run_status={'execution': 'cancelled', 'converged': False}), path)
    assert load_result(path).run_status['execution'] == 'completed'


def test_metrics_strict_json_and_unknown_version(tmp_path):
    result = PerformanceResult('perf', 'result', {
        'Q': MetricValue(12., MetricSpec('Q', 'W/m')),
        'mass': MetricValue(None, MetricSpec('mass', 'kg/m'), 'insufficient_data', 'solid density absent')})
    path = tmp_path / 'metrics.json'
    save_metrics(result, path)
    assert load_metrics(path) == result
    data = json.loads(path.read_text())
    assert data['metrics']['mass']['value'] is None
    data['schema_version'] = 'future'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='schema'):
        load_metrics(path)


@pytest.mark.parametrize('dimension', [2, 3])
def test_selected_field_matches_full_reader_across_field_kinds_and_nonfinite(tmp_path, dimension):
    base = archived_native_result(dimension)
    axes = tuple(base.grid['axis_order'])
    shape = base.fields['Ta'].shape
    values = np.arange(np.prod(shape), dtype=np.float64).reshape(shape)
    nonfinite = values.copy()
    nonfinite.flat[0] = float('nan')
    nonfinite.flat[1] = float('inf')
    nonfinite.flat[2] = float('-inf')

    fields = {
        'Ta': values + 300.0,
        'Tb': nonfinite,
        'Ta_display': values + 300.5,
        'P_report_A': values * 100.0 + 101325.0,
        'ucA': values * 0.5 + 1.0,
        'h_vA': values * 10.0 + 500.0,
        'K_ss': values * 0.1 + 16.0,
        'eps_arr': np.full(shape, 0.72, dtype=np.float64),
    }
    expected_units = {
        'Ta': ('K', 'K', 'main'),
        'Tb': ('K', 'K', 'main'),
        'Ta_display': ('K', 'K', 'display'),
        'P_report_A': ('Pa', 'kPa', 'final SIMPLE flow'),
        'ucA': ('m/s', 'm/s', 'final flow/report'),
        'h_vA': ('W/(m3 K)', 'W/(m3 K)', 'last thermal solve'),
        'K_ss': ('W/(m K)', 'W/(m K)', 'last thermal solve'),
        'eps_arr': ('1', '1', 'design'),
    }
    field_metadata = {
        name: {'unit': raw_unit, 'axes': axes, 'location': 'cell', 'state': state}
        for name, (raw_unit, _disp, state) in expected_units.items()
    }
    design_fields = {
        'L_field_m': np.full(shape, 0.007, dtype=np.float64),
        't_field_m': np.full(shape, 0.0006, dtype=np.float64),
    }
    archived = replace(
        base,
        fields=fields,
        field_metadata=field_metadata,
        metadata={**base.metadata, 'design_fields': design_fields},
    )
    path = tmp_path / f'selected-{dimension}d.h5'
    save_result(archived, path)

    full = load_result(path)
    header = load_result_header(path)
    assert header.result_id == full.result_id
    assert header.available_fields == tuple(full.fields)
    assert set(header.available_design_fields) == {'L_field_m', 't_field_m'}
    for key, arr in full.grid.items():
        if isinstance(arr, np.ndarray):
            np.testing.assert_array_equal(header.grid[key], arr)
        else:
            assert header.grid[key] == arr

    for name, (raw_unit, display_unit, state) in expected_units.items():
        selected = load_result_field(path, name)
        expected = full.fields[name]
        assert selected.source_result_id == full.result_id
        assert selected.name == name
        assert selected.raw_unit == raw_unit
        assert selected.display_unit == display_unit
        assert selected.axes == axes
        assert selected.association == 'cell'
        assert selected.shape == expected.shape
        assert selected.dtype == expected.dtype
        assert selected.state == state
        assert not selected.values.flags.writeable
        with pytest.raises(ValueError):
            selected.values.setflags(write=True)
        assert np.array_equal(selected.values, expected, equal_nan=True)
        for key, arr in full.grid.items():
            if isinstance(arr, np.ndarray):
                np.testing.assert_array_equal(selected.grid[key], arr)
            else:
                assert selected.grid[key] == arr

    for design_name in ('L_field_m', 't_field_m'):
        selected_design = load_result_design_field(path, design_name)
        expected_design = full.metadata['design_fields'][design_name]
        assert selected_design.source_result_id == full.result_id
        assert selected_design.raw_unit == 'm'
        assert selected_design.display_unit == 'mm'
        assert selected_design.axes == axes
        assert selected_design.association == 'cell'
        assert selected_design.shape == expected_design.shape
        assert selected_design.dtype == expected_design.dtype
        assert not selected_design.values.flags.writeable
        np.testing.assert_array_equal(selected_design.values, expected_design)

    with pytest.raises(KeyError):
        load_result_field(path, 'missing_field')


def test_selected_field_reader_rejects_corrupt_unselected_array_link(tmp_path):
    import h5py

    base = archived_native_result(2)
    result = replace(
        base,
        fields={'Ta': base.fields['Ta'], 'Tb': base.fields['Ta'] + 5.0},
        field_metadata={
            'Ta': base.field_metadata['Ta'],
            'Tb': base.field_metadata['Ta'],
        },
    )
    path = tmp_path / 'tampered.h5'
    save_result(result, path)

    with h5py.File(path, 'r+') as source:
        descriptor = json.loads(source['descriptor'].asstr()[()])
        unselected_ref = descriptor['mapping']['fields']['mapping']['Tb']['array']
        leaf = unselected_ref.split('/', 1)[1]
        data = source[unselected_ref][...]
        del source['arrays'][leaf]
        source['arrays'].create_dataset('shadow', data=data)
        source['arrays'][leaf] = h5py.SoftLink('/arrays/shadow')

    with pytest.raises(ValueError, match='external or symbolic HDF5 resources'):
        load_result(path)
    with pytest.raises(ValueError, match='external or symbolic HDF5 resources'):
        load_result_field(path, 'Ta')
    with pytest.raises(ValueError, match='external or symbolic HDF5 resources'):
        load_result_header(path)
