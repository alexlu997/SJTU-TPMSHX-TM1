import numpy as np

from sjtu_tpmshx.models import sco2_props
from sjtu_tpmshx.solvers.ltne_enthalpy_2d import solve_enthalpy_2d
from sjtu_tpmshx.tests.enthalpy_2d_reference import solve_sco2_enthalpy_2d


def test_fullface_counterflow_conserves_true_enthalpy():
    nx, ny = 24, 3
    dx = np.full(nx, 0.21 / nx)
    dy = np.full(ny, 0.03 / ny)
    PA = np.linspace(12.0e6, 11.99e6, nx)[:, None]
    PB = np.linspace(11.99e6, 12.0e6, nx)[:, None]
    rho_A = sco2_props.sco2_prop('D', 500.0, 12.0e6)
    rho_B = sco2_props.sco2_prop('D', 330.0, 12.0e6)
    mA = np.full(ny, 0.35 * rho_A * 0.8 * dy[0])
    mB = np.full(ny, 0.35 * rho_B * 0.5 * dy[0])
    Ta, Tb, Ts, info = solve_sco2_enthalpy_2d(
        500.0, 330.0, PA, PB, mA, mB, 8.0e5, 8.0e5, 5.0,
        dx, dy, max_iter=3000, tol=1e-3,
    )
    assert info["converged"]
    assert info["energy_imbalance_rel"] < 0.05
    assert np.all(np.isfinite(Ta)) and np.all(np.isfinite(Tb))
    assert Ta[-1].mean() < 500.0
    assert Tb[0].mean() > 330.0
    assert Tb.min() <= Ts.mean() <= Ta.max()


def test_mixed_fluid_custom_ports_use_face_mass_flow():
    nx, ny = 5, 6
    dx = np.full(nx, 0.01)
    dy = np.full(ny, 0.01)
    fx_a = np.zeros((nx + 1, ny))
    fy_a = np.zeros((nx, ny + 1))
    fy_a[1:4, :] = 0.01  # sCO2 +y, partial x-span
    fx_b = np.zeros((nx + 1, ny))
    fy_b = np.zeros((nx, ny + 1))
    fx_b[:, 2:5] = -0.01  # water -x, partial y-span
    shape = (nx, ny)
    Ta, Tb, _, info = solve_enthalpy_2d(
        500.0, 300.0, np.full(shape, 12e6), np.full(shape, 2e6),
        (fx_a, fy_a), (fx_b, fy_b), np.full(shape, 1e5),
        np.full(shape, 1e5), np.full(shape, 5.0), np.full(shape, 0.325),
        np.full(shape, 0.325), dx, dy, fluid_A='sco2', fluid_B='water',
        P_inA=12e6, P_inB=2e6,
        max_iter=1000, tol=0.1,
    )
    assert info['converged']
    assert info['energy_imbalance_rel'] < 0.05
    assert np.all(np.isfinite(Ta)) and np.all(np.isfinite(Tb))
    assert Ta[:, -1].mean() < 500.0
    assert Tb[0, :].mean() > 300.0


def test_adapter_preserves_inlet_pressures_and_local_fields(monkeypatch):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d

    shape = (2, 3)
    pressure_a = np.linspace(11.7e6, 11.9e6, 6).reshape(shape)
    pressure_b = np.linspace(8.6e6, 8.8e6, 6).reshape(shape)

    def capture(*args, **kwargs):
        assert args[12:14] == (12e6, 9e6)
        np.testing.assert_array_equal(
            kwargs['pressure_A_field'], pressure_a[..., None])
        np.testing.assert_array_equal(
            kwargs['pressure_B_field'], pressure_b[..., None])
        field = np.zeros((*shape, 1))
        return field, field, field, {}

    monkeypatch.setattr(
        ltne_enthalpy_3d, 'solve_ltne_enthalpy_3d_pipeline', capture)
    flux = (np.zeros((3, 3)), np.zeros((2, 4)))
    solve_enthalpy_2d(
        500.0, 330.0, pressure_a, pressure_b, flux, flux,
        1e5, 1e5, 5.0, 0.325, 0.325,
        np.array([0.01, 0.02]), np.array([0.01, 0.02, 0.03]),
        P_inA=12e6, P_inB=9e6,
    )
