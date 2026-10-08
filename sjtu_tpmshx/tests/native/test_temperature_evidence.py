"""Full CC evidence detaches owner views and rejects incompatible records."""
import ctypes as ct
import os
from pathlib import Path

import numpy as np
import pytest

from sjtu_tpmshx.solvers.backends.cpp.model_h import _Array
from sjtu_tpmshx.solvers.backends.cpp.temperature_evidence import (
    TemperatureEvidence, TemperatureEvidence2D, copy_temperature_evidence,
)


def evidence(dimension, *, solve_b=True):
    shape = (2, 3, 1 if dimension == 2 else 4)
    value = TemperatureEvidence()
    value.available = 1
    value.physical_dimension = dimension
    value.boundary_complete = 1
    value.solved[:] = (1, int(solve_b), 1)
    value.algorithm = b'shared_fv_fullcc_model_enthalpy_test_v1'
    value.cp_coefficients[0][:] = (1004.5, .172, -7.56e-5, 273.15, 300.)
    value.cp_coefficients[1][:] = (4182., 0., 0., 273.15, 300.) if solve_b else (np.nan,) * 5
    owners = []

    def array(count):
        data = np.arange(count, dtype=np.float64) + 100 * (len(owners) + 1)
        owners.append(data)
        return _Array(data.ctypes.data_as(ct.POINTER(ct.c_double)), data.size)

    count = int(np.prod(shape))
    for phase in range(3):
        if not value.solved[phase]:
            continue
        value.residual[phase] = array(count)
        for face in range(6):
            value.advective_out[phase][face] = array(count // shape[face // 2])
            value.diffusive_out[phase][face] = array(count // shape[face // 2])
    value.source_integral[:] = (1., 2., -3.)
    value.prescribed_b_power = 17.
    return value, shape, owners


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('solve_b', [False, True])
def test_temperature_evidence_detaches_arrays_and_preserves_unsolved_phase(dimension, solve_b):
    value, shape, owners = evidence(dimension, solve_b=solve_b)
    copied = copy_temperature_evidence(value, shape, dimension)
    assert copied['physical_dimension'] == dimension
    assert copied['power_units'] == ('W/m' if dimension == 2 else 'W')
    assert copied['algorithm'] == 'shared_fv_fullcc_model_enthalpy_test_v1'
    assert copied['solved'] == dict(A=True, B=solve_b, solid=True)
    assert copied['source_integral'] == dict(A=1., B=2. if solve_b else None, solid=-3.)
    assert copied['prescribed_b_power'] == 17.
    np.testing.assert_array_equal(copied['cp_coefficients']['A'], value.cp_coefficients[0])
    assert (copied['cp_coefficients']['B'] is not None) == solve_b
    assert copied['advective_out']['A']['x-'].shape == (3, shape[2])
    assert copied['advective_out']['A']['z+'].shape == (2, 3)
    assert (copied['residual']['B'] is not None) == solve_b
    assert (copied['advective_out']['B'] is not None) == solve_b
    assert (copied['diffusive_out']['B'] is not None) == solve_b

    def arrays(record):
        if isinstance(record, np.ndarray):
            yield record
        elif isinstance(record, dict):
            for entry in record.values():
                yield from arrays(entry)
        elif isinstance(record, tuple):
            for entry in record:
                yield from arrays(entry)

    detached = list(arrays(copied))
    assert len(detached) == len(owners) + 1 + solve_b
    saved = [entry.copy() for entry in detached]
    for owner in owners:
        owner[:] = -999.
    value.cp_coefficients[0][:] = (-999.,) * 5
    value.cp_coefficients[1][:] = (-999.,) * 5
    for actual, expected in zip(detached, saved):
        np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize('defect', [
    'unavailable', 'dimension', 'complete_flag', 'solved_flag', 'shape',
    'algorithm', 'coefficients', 'residual_extent', 'advective_extent',
    'diffusive_extent', 'null_pointer',
])
def test_temperature_evidence_rejects_malformed_record(defect):
    value, shape, owners = evidence(2)
    if defect == 'unavailable':
        value.available = 0
    elif defect == 'dimension':
        value.physical_dimension = 3
    elif defect == 'complete_flag':
        value.boundary_complete = 2
    elif defect == 'solved_flag':
        value.solved[0] = 2
    elif defect == 'shape':
        shape = (2, 3, 2)
    elif defect == 'algorithm':
        value.algorithm = None
    elif defect == 'coefficients':
        value.cp_coefficients[1][2] = np.nan
    elif defect == 'residual_extent':
        value.residual[2].size -= 1
    elif defect == 'advective_extent':
        value.advective_out[1][3].size -= 1
    elif defect == 'diffusive_extent':
        value.diffusive_out[2][5].size -= 1
    else:
        value.residual[0].data = ct.POINTER(ct.c_double)()
    with pytest.raises(RuntimeError, match='native temperature evidence'):
        copy_temperature_evidence(value, shape, 2)
    assert owners  # Keep the native-view buffers alive for the attempted copy.


@pytest.mark.parametrize('dimension', [2, 3])
def test_query_rejects_null_and_unowned_results_without_writing_output(dimension):
    path = os.environ.get('TPMSHX_NATIVE_SOLVER_LIBRARY')
    if path is None:
        pytest.skip('explicit native library required')
    assert Path(path).is_absolute() and Path(path).is_file()
    if dimension == 2:
        from sjtu_tpmshx.solvers.backends.cpp.full_2d import _Result
        output_type = TemperatureEvidence2D
    else:
        from sjtu_tpmshx.solvers.backends.cpp.full_3d import _Result
        output_type = TemperatureEvidence
    library = ct.CDLL(path)
    query = getattr(library, f'tpmshx_full_{dimension}d_get_model_enthalpy_evidence_v1')
    query.argtypes = [ct.POINTER(_Result), ct.POINTER(output_type)]
    query.restype = ct.c_int
    native, output = _Result(), output_type()
    ct.memset(ct.byref(output), 0xA5, ct.sizeof(output))
    original = bytes(output)
    assert query(None, ct.byref(output)) == 1
    assert bytes(output) == original
    assert query(ct.byref(native), ct.byref(output)) == 1
    assert bytes(output) == original
    assert query(ct.byref(native), None) == 1


def test_full_3d_cc_captured_powers_survive_owner_release_and_portable_replay(monkeypatch, tmp_path):
    from sjtu_tpmshx.io.result_io import save_result, load_result
    from sjtu_tpmshx.postprocess.metrics import evaluate
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver, run_case
    from sjtu_tpmshx.tests.native.test_cpp_full_3d import case, control

    path = os.environ.get('TPMSHX_NATIVE_SOLVER_LIBRARY')
    if path is None:
        pytest.skip('explicit native library required')
    original = NativeFull3DDriver._run_prepared
    returned = []

    def bounded(self, cfg, prepared, runtime_control, **kwargs):
        cfg = dict(cfg, max_iter_simple=1, variable_rho_cp=False,
                   conservative_ltne=False, force_cc_ltne=True)
        cfg['_environment'] = dict(cfg.get('_environment', {}),
                                   TPMSHX_P_IN_SHOOT='0', TPMSHX_VAR_RHOCP=None)
        prepared = dict(prepared, max_outer=1, ltne_max_iter=1)
        raw = original(self, cfg, prepared, runtime_control, **kwargs)
        returned.append(raw)
        return raw

    monkeypatch.setattr(NativeFull3DDriver, '_run_prepared', bounded)
    result = run_case(case('air-air', cap=2), control(Path(path)))
    raw, = returned
    assert raw['mode'] == 'temperature'
    assert result.metadata['temperature_transport'] == 'model_enthalpy_temperature_v1'
    assert result.metadata['native']['algorithm'] == 'model_h_tface_sou_sou_strict_v3'
    archive = save_result(result, tmp_path / 'full-cc3d.h5')
    before = evaluate(result).metrics
    for source in (result, load_result(archive)):
        ledger = source.boundary_fluxes['temperature']
        assert ledger['physical_dimension'] == 3 and ledger['power_units'] == 'W'
        assert source.run_status['converged'] is False
        actual = evaluate(source).metrics
        for phase in ('A', 'B', 'solid'):
            np.testing.assert_array_equal(ledger['residual'][phase], raw['temperature_evidence']['residual'][phase])
            for kind in ('advective_out', 'diffusive_out'):
                for face, values in ledger[kind][phase].items():
                    np.testing.assert_array_equal(values, raw['temperature_evidence'][kind][phase][face])
        for key in ('Q', 'Q_A', 'Q_B', 'T_out_A', 'T_out_B', 'mass_flow_A', 'mass_flow_B'):
            assert actual[key] == before[key]
        for index, side in enumerate('AB'):
            if ledger['physical_boundary_complete']:
                assert actual['Q_' + side].status == 'available'
                assert abs(actual['Q_' + side].value) == pytest.approx(raw['duty'][index], rel=1e-12, abs=1e-10)
            else:
                assert actual['Q_' + side].status == 'invalid'
                assert not np.isfinite(raw['duty'][index])
