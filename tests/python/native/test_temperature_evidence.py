"""Full CC evidence queries reject unowned results and survive owner release."""
import ctypes as ct
import os
from pathlib import Path

import numpy as np
import pytest

from sjtu_tpmshx.cpp_interface.solver_library._stage_capture_abi import TemperatureEvidence


class TemperatureEvidence2D(ct.Structure):
    _fields_ = [('main', TemperatureEvidence), ('fine', TemperatureEvidence)]


@pytest.mark.parametrize('dimension', [2, 3])
def test_query_rejects_null_and_unowned_results_without_writing_output(dimension):
    path = os.environ.get('TPMSHX_NATIVE_SOLVER_LIBRARY')
    if path is None:
        pytest.skip('explicit native library required')
    assert Path(path).is_absolute() and Path(path).is_file()
    if dimension == 2:
        from sjtu_tpmshx.cpp_interface.solver_library._full_2d_abi import _Result
        output_type = TemperatureEvidence2D
    else:
        from sjtu_tpmshx.cpp_interface.solver_library._full_3d_abi import _Result
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
    from sjtu_tpmshx.file_io.result_io import save_result, load_result
    from sjtu_tpmshx.postprocess.api import evaluate
    from sjtu_tpmshx.solvers import full_3d
    from sjtu_tpmshx.solvers.full_3d import run_case
    from dataclasses import replace
    from tests.python.native.test_cpp_full_3d import case, control

    path = os.environ.get('TPMSHX_NATIVE_SOLVER_LIBRARY')
    if path is None:
        pytest.skip('explicit native library required')
    capture = full_3d.capture_result
    returned = []

    def observe(case, cfg, prepared, raw, abi):
        returned.append(raw)
        return capture(case, cfg, prepared, raw, abi)

    monkeypatch.setattr(full_3d, 'capture_result', observe)
    prepared = case('air-air', cap=2)
    params = prepared.parameters
    prepared = replace(prepared, parameters=dict(params, max_iter_simple=1, variable_rho_cp=False,
        conservative_ltne=False, force_cc_ltne=True,
        _environment=dict(params['_environment'], TPMSHX_P_IN_SHOOT='0', TPMSHX_VAR_RHOCP=None),
        prepared=dict(params['prepared'], max_outer=1, ltne_max_iter=1)))
    result = run_case(prepared, control(Path(path)))
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
