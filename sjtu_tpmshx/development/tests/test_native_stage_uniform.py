"""Compare uniform native execution with the unchanged Python workflow."""
import ctypes as ct
from dataclasses import replace
from itertools import product
import json
from pathlib import Path

import numpy as np
import pytest

from sjtu_tpmshx.compute import compute
from sjtu_tpmshx.development.tests import result_stage_fixture as report
from sjtu_tpmshx.development.tests import test_native_preparation_fluids as preparation
from sjtu_tpmshx.development.tests.native.shared_library import library_path
from sjtu_tpmshx.shared import _native_result
from sjtu_tpmshx.shared.domain.module_ports import RunControl
from sjtu_tpmshx.solvers.backends.cpp import _full_2d_abi as abi
from sjtu_tpmshx.solvers.backends.cpp.enthalpy import _EnergyOptions, _EnergyOptionsV2
from sjtu_tpmshx.solvers.backends.cpp.model_h import _IterationOptions

_U, _Z, _D = ct.c_uint32, ct.c_size_t, ct.c_double
preparation_library = preparation.native
_Size = report.record('SizeOption', [('present', _U), ('value', _Z)])
_Double = report.record('DoubleOption', [('present', _U), ('value', _D)])
_Request = report.record('RunRequest', [('abi_version', _U), ('struct_size', _Z),
    ('max_iter_simple', _Size), ('max_outer_ltne', _Size),
    *((key, _Double) for key in ('outer_tol_K', 'simple_velocity_relaxation',
        'mom_tol', 'mass_local_tol', 'mass_global_tol', 'solid_seed_K')),
    ('have_pressure_shooting', _U), ('pressure_shooting', _U), ('convergence_mode', ct.c_char_p),
    ('model_h', _IterationOptions), ('energy', ct.POINTER(_EnergyOptions)),
    ('explicit_energy', ct.POINTER(abi._EnergyControl))])
_RequestV2 = report.record('RunRequestV2', [('abi_version', _U), ('struct_size', _Z),
    ('values', _Request), ('envelope_mode', ct.c_char_p)])
_Control = report.record('RunControl', [('result_id', ct.c_char_p), ('table_directory', ct.c_char_p),
    ('cpu_threads', _Z), ('callbacks', abi._Callbacks)])
_Result = report.record('StageRun', [('abi_version', _U), ('struct_size', _Z), ('owner', ct.c_void_p),
    ('raw', abi._Result), ('evidence', report.Evidence), ('resolved', abi._Config)])


@pytest.fixture(scope='module')
def stage_library():
    library = ct.CDLL(str(library_path()))
    library.tpmshx_run_case_2d_v2.argtypes = [ct.POINTER(preparation._Result), ct.POINTER(_RequestV2),
        ct.POINTER(_Control), ct.POINTER(_Result), ct.POINTER(ct.c_char), _Z]
    library.tpmshx_run_case_2d_v2.restype = ct.c_int
    library.tpmshx_stage_run_2d_release_v1.argtypes = [ct.POINTER(_Result)]
    library.tpmshx_stage_run_2d_release_v1.restype = None
    return library


def _configuration(pair):
    config = preparation._configuration('Gyroid', pair)
    config.fluid_A.T_in_K += 10.
    return config


def _request():
    return _RequestV2(2, ct.sizeof(_RequestV2), _Request(1, ct.sizeof(_Request)))


def _evaluate(evidence):
    library = _native_result._library().library
    function = library.tpmshx_result_stage_evaluate_v1
    function.argtypes = [ct.POINTER(report.Evidence), ct.POINTER(report.Spec),
        ct.POINTER(report.Output), ct.POINTER(ct.c_char), _Z]
    function.restype = ct.c_int
    output, error = report.Output(struct_size=ct.sizeof(report.Output)), ct.create_string_buffer(4096)
    status = function(ct.byref(evidence), None, ct.byref(output), error, len(error))
    assert status == 0, error.value.decode()
    try:
        return json.loads(output.json)
    finally:
        release = library.tpmshx_result_stage_release_v1
        release.argtypes = [ct.POINTER(report.Output)]
        release.restype = None
        release(ct.byref(output))


def _assert_exact(preparation_library, stage_library, config, request, tmp_path, *, water_rejection=False):
    table = str(Path(__file__).resolve().parents[3] / '.cache/native-deps/tables')
    (tmp_path / 'input.json').write_text(json.dumps(config.to_dict(), indent=2))
    (tmp_path / 'control.json').write_text(json.dumps({
        'cpu_threads': 2, 'result_id': 'uniform-stage', 'table_directory': table,
        'native_library': str(library_path()), 'default_request': request is None,
        'water_rejection': water_rejection}, indent=2))
    status, prepared, _, error, _, source = preparation._call(preparation_library, config)
    assert status == 0, error
    result = _Result(1, ct.sizeof(_Result))
    empty_result = bytes(result)
    progress, residuals = [], []
    callback = abi._Progress(lambda _, current, total: progress.append((current, total)))
    residual = abi._Residual(lambda *values: residuals.append(values[1:]))
    control = _Control(b'uniform-stage', table.encode(), 2,
        abi._Callbacks(abi._Cancel(), callback, residual, None))
    error = ct.create_string_buffer(4096)
    try:
        status = stage_library.tpmshx_run_case_2d_v2(ct.byref(prepared),
            None if request is None else ct.byref(request), ct.byref(control),
            ct.byref(result), error, len(error))
        if water_rejection:
            from sjtu_tpmshx.shared.models.fluid_props import WaterStateError
            assert status == 2 and bytes(result) == empty_result, error.value.decode()
            native_error = error.value.decode()
            (tmp_path / 'native-error.json').write_text(json.dumps({'status': status, 'message': native_error}))
            with pytest.raises(WaterStateError) as failure:
                compute(config, control=RunControl(cpu_threads=2,
                    native_library=str(library_path()), native_table_directory=table))
            (tmp_path / 'reference-error.json').write_text(json.dumps({'type': type(failure.value).__name__, 'message': str(failure.value)}))
            assert native_error == str(failure.value)
            (tmp_path / 'verdict.json').write_text(json.dumps({'passed': True,
                'status': status, 'exception': 'WaterStateError', 'output_unchanged': True}))
            return
        assert status == 0, error.value.decode()
    finally:
        preparation_library.tpmshx_preparation_case_2d_release_v2(ct.byref(prepared))
    try:
        # The run must own every retained view after preparation is released.
        actual = _evaluate(result.evidence)
        expected_progress, expected_residuals = [], []
        _, expected, _ = compute(config, control=RunControl(cpu_threads=2,
            native_library=str(library_path()), native_table_directory=table,
            outer_iteration=lambda *values: expected_progress.append(values),
            residual=lambda side, iteration, value: expected_residuals.append(('AB'.index(side), iteration, value))))
        assert result.evidence.thermal_mode.decode() == expected.metadata['thermal_mode']
        assert result.evidence.field_count == len(expected.fields)
        for index in range(result.evidence.field_count):
            field = result.evidence.fields[index]
            name, value = field.name.decode(), field.value
            assert value.rank == 2
            data = np.ctypeslib.as_array(ct.cast(value.data, ct.POINTER(_D)),
                shape=(value.shape[0] * value.shape[1],)).reshape(value.shape[0], value.shape[1])
            np.testing.assert_array_equal(data.view(np.uint64), expected.fields[name].view(np.uint64), err_msg=name)
        wanted = report.python_report(expected)
        wanted['source_result_id'] = actual['source_result_id']
        wanted['qualification']['source_result_id'] = actual['source_result_id']
        (tmp_path / 'native-report.json').write_text(json.dumps(actual, indent=2))
        (tmp_path / 'reference-report.json').write_text(json.dumps(wanted, indent=2))
        from sjtu_tpmshx.shared.io.result_io import save_result
        save_result(expected, tmp_path / 'reference.h5')
        assert actual == wanted
        assert progress == expected_progress
        for side in (0, 1):
            assert [row for row in residuals if row[0] == side] == [row for row in expected_residuals if row[0] == side]
        (tmp_path / 'events.json').write_text(json.dumps({
            'native_progress': progress, 'reference_progress': expected_progress,
            'native_residuals': residuals, 'reference_residuals': expected_residuals}))
        (tmp_path / 'verdict.json').write_text(json.dumps({'passed': True,
            'bitwise_fields': len(expected.fields), 'metrics_and_qualification_exact': True,
            'progress_and_side_residuals_exact': True}))
    finally:
        stage_library.tpmshx_stage_run_2d_release_v1(ct.byref(result))


@pytest.mark.slow
@pytest.mark.parametrize('pair', list(product(preparation._FLUIDS, repeat=2)))
def test_uniform_stage_exact(preparation_library, stage_library, pair, tmp_path):
    _assert_exact(preparation_library, stage_library, _configuration(pair), None, tmp_path)


@pytest.mark.slow
@pytest.mark.parametrize('selection', ['negative-partial', 'negative-partial-water-limit', 'experimental', 'model-controls', 'energy-controls'])
def test_uniform_stage_selected_controls(preparation_library, stage_library, selection, tmp_path):
    pair = ('water', 'air') if selection == 'model-controls' else ('sco2', 'water') if selection == 'experimental' else ('co2', 'water')
    config, request = _configuration(pair), _request()
    config.flags.port_wall_refine = False
    if selection.startswith('negative-partial'):
        config.solver.Nx, config.solver.Ny = 20, 40
        config.bc_A.dir, config.bc_B.dir = 1, 2
        config.bc_A.in_ctr, config.bc_A.in_w = .012, .012
        config.bc_A.out_ctr, config.bc_A.out_w = .028, .016
        config.bc_B.in_ctr, config.bc_B.in_w = .045, .04
        config.bc_B.out_ctr, config.bc_B.out_w = .13, .06
        if selection == 'negative-partial':
            config.fluid_A.T_in_K, config.fluid_A.u_mps = 340., .7
            config.fluid_B.T_in_K, config.fluid_B.u_mps = 325., .2
    elif selection == 'experimental':
        config = preparation._configuration('Diamond', pair, 'experimental')
        config.flags.port_wall_refine = False
        config.sco2_nu = replace(config.sco2_nu, mode='experimental', alpha_D=1.13, alpha_G=2.27,
            parameter_version='stage-comparison', source='existing experimental selection', applicability='uniform geometry')
    elif selection == 'model-controls':
        config.solver.max_outer_ltne = 2
        request.values.max_outer_ltne = _Size(1, 2)
        config.solver.model_h_max_iterations = 500
        config.solver.model_h_temperature_tol_K = .001
        config.solver.model_h_q_relative_tol = .001
        request.values.model_h = _IterationOptions(500, .001, .001)
    else:
        config.solver.max_outer_ltne = 2
        request.values.max_outer_ltne = _Size(1, 2)
        settings = (20, 3, .8, .002, .001, .001)
        for name, value in zip(('outer', 'nsweep', 'omega', 'tol', 'coupled_energy_tol', 'equation_energy_tol'), settings):
            setattr(config.solver, 'ltne_enthalpy_' + name, value)
        explicit = abi._EnergyControl(*settings[:4], _EnergyOptionsV2(2, 1e-8, *settings[4:], 0))
        request.values.explicit_energy = ct.pointer(explicit)
    _assert_exact(preparation_library, stage_library, config, request, tmp_path,
        water_rejection=selection == 'negative-partial-water-limit')


def test_uniform_stage_boundary_and_cancellation(preparation_library, stage_library):
    config = _configuration(('co2', 'water'))
    status, prepared, _, error, _, source = preparation._call(preparation_library, config)
    assert status == 0, error
    output = _Result(1, ct.sizeof(_Result))
    before = bytes(output)
    calls = []
    cancel = abi._Cancel(lambda _: calls.append('cancel') or 1)
    control = _Control(b'cancel-uniform', None, 2, abi._Callbacks(cancel, abi._Progress(), abi._Residual(), None))
    error = ct.create_string_buffer(4096)
    function = stage_library.tpmshx_run_case_2d_v2
    try:
        assert function(ct.byref(prepared), None, ct.cast(ct.byref(output), ct.POINTER(_Control)),
            ct.byref(output), error, len(error)) == 1
        assert not error.value and bytes(output) == before and not calls
        label = ct.create_string_buffer(b'preserve-label', 128)
        label_before = bytes(label)
        control.result_id = ct.cast(label, ct.c_char_p)
        malformed = preparation._Result.from_buffer_copy(prepared)
        malformed.values.dx.data = ct.POINTER(_D)()
        assert function(ct.byref(malformed), None, ct.byref(control),
            ct.byref(output), label, len(label)) == 1
        assert bytes(label) == label_before and bytes(output) == before and not calls
        control.result_id = b'cancel-uniform'
        request = _request()
        request.abi_version = 1
        assert function(ct.byref(prepared), ct.byref(request), ct.byref(control),
            ct.byref(output), error, len(error)) == 1
        assert bytes(output) == before and not calls
        assert function(ct.byref(prepared), None, ct.byref(control),
            ct.byref(output), error, len(error)) == 6
        assert bytes(output) == before and calls
    finally:
        preparation_library.tpmshx_preparation_case_2d_release_v2(ct.byref(prepared))
