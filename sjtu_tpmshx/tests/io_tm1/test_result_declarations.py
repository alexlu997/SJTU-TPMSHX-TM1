"""Declarations retain their meaning across memory and native HDF5 handoffs."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.io.hdf5_data import write_record
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.tests.postprocess_tm1.test_reduction_reuse import native_result


def archived_native_result(dimension):
    result = native_result(dimension)
    axes = tuple('xyz'[:dimension])
    widths = (np.array([.1, .2]), np.array([.3, .4]), np.array([.5]))[:dimension]
    shape = tuple(len(values) for values in widths)
    grid = dict(dimension=dimension, length_unit='m', axis_order=axes)
    for axis, values in zip(axes, widths):
        grid['d' + axis] = values
        grid[axis + '_edges'] = np.r_[0., np.cumsum(values)]
    return replace(result, grid=grid,
        fields={'Ta': np.arange(np.prod(shape)).reshape(shape) + 300.},
        field_metadata={'Ta': dict(unit='K', axes=axes, location='cell', state='main')},
        run_status=dict(execution='completed', converged=False))


@pytest.mark.parametrize('dimension,basis', [(2, 'total'), (3, 'per_unit_depth')])
@pytest.mark.parametrize('boundary', ['memory', 'save', 'load'])
def test_conflicting_quantity_basis_rejected(tmp_path, dimension, basis, boundary):
    result = archived_native_result(dimension)
    result = replace(result, metadata={**result.metadata, 'quantity_basis': basis})
    path = tmp_path / 'contradictory.h5'
    if boundary == 'load':
        # An external producer bypasses the public writer's validation.
        write_record(path, result, 'FieldResult')
    with pytest.raises(ValueError, match='quantity_basis'):
        if boundary == 'memory':
            evaluate(result)
        elif boundary == 'save':
            save_result(result, path)
        else:
            load_result(path)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('mode', ['unexpected_new_mode', None, ''])
def test_unknown_explicit_mode_can_archive_but_not_evaluate(tmp_path, dimension, mode):
    result = archived_native_result(dimension)
    result = replace(result, metadata={**result.metadata, 'mode': mode})
    path = tmp_path / 'unsupported.h5'
    save_result(result, path)
    loaded = load_result(path)
    assert loaded.metadata['mode'] == mode
    np.testing.assert_array_equal(loaded.fields['Ta'], result.fields['Ta'])
    for source in (result, loaded):
        with pytest.raises(ValueError, match='unsupported postprocessing mode'):
            evaluate(source)


@pytest.mark.parametrize('dimension', [2, 3])
def test_grid_dimension_is_authoritative_when_metadata_omits_it(tmp_path, dimension):
    result = archived_native_result(dimension)
    expected = evaluate(result).metrics
    result = replace(result, metadata={key: value for key, value in result.metadata.items()
                                      if key != 'dimension'})
    path = tmp_path / 'grid-dimension.h5'
    save_result(result, path)
    loaded = load_result(path)
    assert 'dimension' not in loaded.metadata
    assert loaded.run_status['converged'] is False
    np.testing.assert_array_equal(loaded.fields['Ta'], result.fields['Ta'])
    for source in (result, loaded):
        actual = evaluate(source).metrics
        assert actual == expected
        assert actual['Q'].value == 10.
        assert actual['Q'].spec.unit == ('W/m' if dimension == 2 else 'W')
        assert actual['mass_flow_A'].value == 2.
        assert actual['mass_flow_A'].spec.unit == ('kg/(s m)' if dimension == 2 else 'kg/s')


@pytest.mark.parametrize('dimension', [2, 3])
def test_omitted_declarations_and_partial_evidence_remain_supported(tmp_path, dimension):
    # Metadata-only dimension remains usable for small in-memory evidence.
    result = native_result(dimension)
    expected = evaluate(result).metrics
    declared = replace(result, metadata={**result.metadata, 'mode': 'full',
        'quantity_basis': 'per_unit_depth' if dimension == 2 else 'total'})
    assert evaluate(declared).metrics == expected
    assert expected['Q'].value == 10.
    assert expected['T_out_A'].status == 'insufficient_data'
    result = archived_native_result(dimension)
    path = tmp_path / 'partial.h5'
    save_result(result, path)
    loaded = load_result(path)
    assert 'mode' not in loaded.metadata and 'quantity_basis' not in loaded.metadata
    assert evaluate(loaded).metrics == evaluate(result).metrics


def test_missing_dimension_is_not_inferred_from_a_container():
    result = FieldResult('result', 'case', 'fixture')
    with pytest.raises(ValueError, match='physical dimension'):
        evaluate(result)
