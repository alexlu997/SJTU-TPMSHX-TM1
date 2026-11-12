"""Compare continuous native execution with the unchanged Python workflow."""
import ctypes as ct
from itertools import product
import json

import numpy as np
import pytest

from sjtu_tpmshx.compute import compute
from sjtu_tpmshx.development.tests import test_native_preparation_continuous as preparation
from sjtu_tpmshx.development.tests import test_native_stage_uniform as uniform
from sjtu_tpmshx.shared.domain.module_ports import RunControl
from sjtu_tpmshx.shared.io.result_io import save_result

preparation_library = preparation.native


@pytest.fixture(scope='module')
def stage_library():
    library = ct.CDLL(str(uniform.library_path()))
    library.tpmshx_run_case_2d_v3.argtypes = [ct.POINTER(preparation._Result), ct.POINTER(uniform._RequestV2),
        ct.POINTER(uniform._Control), ct.POINTER(uniform._Result), ct.POINTER(ct.c_char), ct.c_size_t]
    library.tpmshx_run_case_2d_v3.restype = ct.c_int
    library.tpmshx_stage_run_2d_release_v1.argtypes = [ct.POINTER(uniform._Result)]
    library.tpmshx_stage_run_2d_release_v1.restype = None
    return library


def _configuration(pair):
    config = preparation._configuration(pair=pair)
    config.flags.port_wall_refine = False
    config.fluid_A.T_in_K += 10.
    return config


def _assert_exact(preparation_library, stage_library, config, tmp_path, request=None, *, frozen=None, targets=None):
    (tmp_path / 'input.json').write_text(json.dumps(config.to_dict(), indent=2))
    (tmp_path / 'control.json').write_text(json.dumps({'cpu_threads': 2,
        'native_library': str(uniform.library_path()), 'default_request': request is None,
        'result_id': 'continuous-stage', 'frozen_reference': frozen is not None,
        'explicit_mass_flow_kg_s': targets}, indent=2))
    status, prepared, _, error, _, source = preparation._call(preparation_library, 'prepare_flow_case', config, targets)
    assert status == 0, error
    result = uniform._Result(1, ct.sizeof(uniform._Result))
    progress, residuals = [], []
    callback = uniform.abi._Progress(lambda _, current, total: progress.append((current, total)))
    residual = uniform.abi._Residual(lambda *values: residuals.append(values[1:]))
    control = uniform._Control(b'continuous-stage', None, 2,
        uniform.abi._Callbacks(uniform.abi._Cancel(), callback, residual, None))
    error = ct.create_string_buffer(4096)
    try:
        status = stage_library.tpmshx_run_case_2d_v3(ct.byref(prepared),
            ct.byref(request) if request is not None else None, ct.byref(control),
            ct.byref(result), error, len(error))
        assert status == 0, error.value.decode()
    finally:
        preparation._release(preparation_library, prepared)
    try:
        actual = uniform._evaluate(result.evidence)
        expected_progress, expected_residuals = [], []
        if frozen is None:
            _, expected, _ = compute(config, control=RunControl(cpu_threads=2,
                native_library=str(uniform.library_path()),
                outer_iteration=lambda *values: expected_progress.append(values),
                residual=lambda side, iteration, value: expected_residuals.append(('AB'.index(side), iteration, value))))
        else:
            expected, expected_progress, expected_residuals = frozen
        wanted = uniform.report.python_report(expected)
        wanted['source_result_id'] = actual['source_result_id']
        wanted['qualification']['source_result_id'] = actual['source_result_id']
        (tmp_path / 'native-report.json').write_text(json.dumps(actual, indent=2))
        (tmp_path / 'reference-report.json').write_text(json.dumps(wanted, indent=2))
        (tmp_path / 'events.json').write_text(json.dumps({'native_progress': progress,
            'reference_progress': expected_progress, 'native_residuals': residuals,
            'reference_residuals': expected_residuals}))
        save_result(expected, tmp_path / 'reference.h5')
        assert result.resolved.spatial_geometry == 1
        assert result.evidence.field_count == len(expected.fields)
        for index in range(result.evidence.field_count):
            field = result.evidence.fields[index]
            name, value = field.name.decode(), field.value
            assert value.rank == 2
            data = np.ctypeslib.as_array(ct.cast(value.data, ct.POINTER(ct.c_double)),
                shape=(value.shape[0] * value.shape[1],)).reshape(value.shape[0], value.shape[1])
            np.testing.assert_array_equal(data.view(np.uint64), expected.fields[name].view(np.uint64), err_msg=name)
        assert actual == wanted
        assert progress == expected_progress
        for side in (0, 1):
            assert [row for row in residuals if row[0] == side] == [row for row in expected_residuals if row[0] == side]
        (tmp_path / 'verdict.json').write_text(json.dumps({'passed': True,
            'bitwise_fields': len(expected.fields), 'metrics_and_qualification_exact': True,
            'progress_and_side_residuals_exact': True}))
    finally:
        stage_library.tpmshx_stage_run_2d_release_v1(ct.byref(result))


@pytest.mark.slow
@pytest.mark.parametrize('pair', list(product(preparation.v2._FLUIDS, repeat=2)))
def test_continuous_stage_exact(preparation_library, stage_library, pair, tmp_path):
    _assert_exact(preparation_library, stage_library, _configuration(pair), tmp_path)


@pytest.mark.slow
@pytest.mark.parametrize('selection', ['negative-partial', 'refined', 'fixed-mass', 'mixed-mass', 'experimental'])
def test_continuous_stage_selected(preparation_library, stage_library, selection, tmp_path):
    config = _configuration(('air', 'water'))
    if selection in ('negative-partial', 'refined'):
        config.solver.Nx = config.solver.Ny = 64 if selection == 'refined' else 20
        config.flags.port_wall_refine = selection == 'refined'
        config.bc_A.dir, config.bc_B.dir = 1, 2
        config.bc_A.in_ctr, config.bc_A.in_w = .012, .012
        config.bc_A.out_ctr, config.bc_A.out_w = .028, .016
        config.bc_B.in_ctr, config.bc_B.in_w = .08, .09
        config.bc_B.out_ctr, config.bc_B.out_w = .10, .07
        if selection == 'refined':
            for side in 'AB':
                port = getattr(config, 'bc_' + side)
                cross = config.geometry.H_dom_m if port.dir < 2 else config.geometry.L_dom_m
                port.in_ctr, port.in_w = cross * .4, cross * .4
                port.out_ctr, port.out_w = cross * .6, cross * .4
    elif selection in ('fixed-mass', 'mixed-mass'):
        from sjtu_tpmshx.preprocess.api import prepare_inlet_mass_capacities
        capacities = prepare_inlet_mass_capacities(config)
        for side in ('AB' if selection == 'fixed-mass' else 'A'):
            fluid = getattr(config, 'fluid_' + side)
            fluid.mass_flow_kg_s = capacities[side] * fluid.u_mps
            fluid.u_mps = -99.
    else:
        config = preparation._configuration(mode='experimental')
        config.flags.port_wall_refine = False
        config.fluid_A.T_in_K += 10.
    _assert_exact(preparation_library, stage_library, config, tmp_path)


def test_continuous_stage_storage_and_cancel(preparation_library, stage_library):
    status, prepared, _, error, _, source = preparation._call(preparation_library, 'prepare_flow_case',
        _configuration(('air', 'water')))
    assert status == 0, error
    result = uniform._Result(1, ct.sizeof(uniform._Result))
    original = bytes(result)
    cancel = uniform.abi._Cancel(lambda _: 1)
    control = uniform._Control(b'continuous-boundary', None, 2,
        uniform.abi._Callbacks(cancel, uniform.abi._Progress(), uniform.abi._Residual(), None))
    error = ct.create_string_buffer(4096)
    call = stage_library.tpmshx_run_case_2d_v3
    try:
        assert call(ct.byref(prepared), None, ct.byref(control), ct.byref(result), error, len(error)) == 6
        assert bytes(result) == original and b'cancelled' in error.value
        array = prepared.fluid_conductivity[1]
        count, pointer = array.size, array.data
        snapshot = ct.string_at(pointer, count * 8)
        array.size -= 1
        assert call(ct.byref(prepared), None, ct.byref(control), ct.byref(result), error, len(error)) == 1
        assert bytes(result) == original and b'extent' in error.value
        # A late borrowed field must not become error storage after an earlier failure.
        array.data, array.size = pointer, count
        length = prepared.prepared.values.cell_length
        saved = length.data
        length.data = ct.POINTER(ct.c_double)()
        assert call(ct.byref(prepared), None, ct.byref(control), ct.byref(result),
            ct.cast(pointer, ct.POINTER(ct.c_char)), count * 8) == 1
        assert bytes(result) == original and ct.string_at(pointer, count * 8) == snapshot
        length.data = saved
    finally:
        preparation._release(preparation_library, prepared)
