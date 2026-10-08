"""Physical inlet pressure must reach thermal EOS, guards and saved results."""
import numpy as np
import pytest

from sjtu_tpmshx.io.case_io import load_case, save_case
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.solvers.backends.python.two_d import coupling
from sjtu_tpmshx.tests.native.test_native_execution import _config


@pytest.mark.parametrize('pin', [12_000_000., 7_900_100.], ids=['nominal', 'local-below-floor'])
def test_frozen_physical_inlet_survives_public_case_handoff(monkeypatch, tmp_path, pin):
    cfg = _config(2, air_sco2=True)
    cfg.fluid_B.P_in_Pa = pin
    monkeypatch.setenv('TPMSHX_TRUE_H_KERNEL', 'numba')
    case = prepare_case(cfg, case_id='frozen-physical-inlet')
    save_case(case, tmp_path / 'case.h5')
    pressure_calls, thermal_calls = [], []
    original_pressure = coupling._simple_pressure_abs_2d

    def pressure(solver, direction, inlet):
        absolute = original_pressure(solver, direction, inlet)
        if solver.fluid_type == 'incompressible':
            # Independently extrapolate the real absolute field back to its
            # physical inlet; the test case has B flowing along negative y.
            assert direction == 3
            local = absolute[:, ::-1]
            widths = solver.dy_arr
            face = local[:, 0] - (local[:, 1] - local[:, 0]) * widths[0] / (widths[0] + widths[1])
            area = solver.dx_arr * solver.inlet_geom_frac
            assert np.sum(face * area) / area.sum() == pytest.approx(inlet, abs=1e-8, rel=0.)
            assert solver.final_res_mom < 1e-4
            assert max(solver.final_res_mass_local, solver.final_res_mass_global) < 1e-6
            pressure_calls.append(absolute.copy())
        return absolute

    from sjtu_tpmshx.solvers import ltne_enthalpy_2d
    original_thermal = ltne_enthalpy_2d.solve_enthalpy_2d

    def thermal(*args, **kwargs):
        thermal_calls.append(args[3].copy())
        np.testing.assert_array_equal(thermal_calls[-1], pressure_calls[-1])
        return original_thermal(*args, **kwargs)

    monkeypatch.setattr(coupling, '_simple_pressure_abs_2d', pressure)
    monkeypatch.setattr(ltne_enthalpy_2d, 'solve_enthalpy_2d', thermal)
    if pin < 8e6:
        with pytest.raises(ValueError, match='sCO2 pressure must be within 7.9..16 MPa'):
            run_case(load_case(tmp_path / 'case.h5'))
        assert pressure_calls and thermal_calls
        assert thermal_calls[-1].min() < 7.9e6
        return

    result = run_case(load_case(tmp_path / 'case.h5'))
    assert result.run_status['converged'] and result.run_status['envelope_valid']
    assert not result.run_status['final_flow_after_last_thermal']
    save_result(result, tmp_path / 'result.h5')
    saved = load_result(tmp_path / 'result.h5')
    for key in ('P_thermal_B', 'P_report_B'):
        np.testing.assert_array_equal(saved.fields[key], thermal_calls[-1])
    assert saved.field_metadata['P_thermal_B']['state'] == 'last thermal input'
    assert saved.field_metadata['P_report_B']['state'] == 'final flow/report'
    balance = saved.metadata['diagnostics']['true_h_balance']
    assert balance['converged'] and balance['equation_energy_balance']['ratio'] <= .001
