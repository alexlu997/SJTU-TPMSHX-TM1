"""Audit scalars must meet raw SIMPLE face fluxes at the same physical cell."""
import numpy as np
import pytest

from sjtu_tpmshx.validation.cases import audit_3d_conservation as audit


@pytest.fixture(params=range(6))
def oriented_two_cell_result(request):
    direction = request.param
    stream_axis = direction // 2
    permutation = ((1, 0, 2), (0, 1, 2), (0, 2, 1))[stream_axis]

    def real_scalar(inlet, outlet):
        # Physical inlet/outlet positions are known independently of the audit:
        # negative-going streams enter at the high coordinate.
        values = [outlet, inlet] if direction % 2 else [inlet, outlet]
        shape = [1, 1, 1]
        shape[stream_axis] = 2
        return np.asarray(values, dtype=float).reshape(shape)

    face = dict(
        u=np.zeros((2, 2, 1)), v=np.array([[[1.], [.5], [.5]]]),
        w=np.zeros((1, 2, 2)), rho=np.ones((1, 2, 1)),
        dx=np.ones(1), dy=np.ones(2), dz=np.ones(1),
        dir_real=direction, solver_to_real_perm=permutation,
    )
    return dict(
        _audit_sA_face=face, _audit_sB_face=face,
        Ta=real_scalar(300., 400.), Tb=real_scalar(500., 600.),
        _audit_eps_arr=real_scalar(.8, .6),
        _audit_cp_A=2., _audit_cp_B=2.,
        _audit_rho_cp_fA=real_scalar(2., 3.),
        _audit_rho_cp_fB=real_scalar(4., 5.),
        _audit_fA={'dir': direction}, _audit_fB={'dir': direction},
    )


def test_per_cell_mass_defect_uses_temperature_at_the_same_solver_cell(
        oriented_two_cell_result):
    result = audit.compute_phase2c_h3(oriented_two_cell_result)
    # Only the inlet cell has a defect: dm = .5 - 1 = -.5 kg/s.
    # Spurious enthalpy is dm * T_in * cp * eps_in / 2.
    assert result['A']['spurious_enthalpy_W'] == pytest.approx(-120.)
    assert result['B']['spurious_enthalpy_W'] == pytest.approx(-200.)
    for fluid in result.values():
        assert fluid['net_out_total'] == pytest.approx(-.5)
        assert fluid['net_out_abs'] == pytest.approx(.5)


def test_six_face_enthalpy_uses_local_temperature_density_and_porosity(
        oriented_two_cell_result):
    result = audit.compute_phase5(oriented_two_cell_result)
    # SIMPLE always injects at its south face (+v), even for real -x/-y/-z.
    # Signed face enthalpy is +/- eps/2 * rho_cp * v * T * area.
    assert result['A']['F_ym'] == pytest.approx(-240.)
    assert result['A']['F_yp'] == pytest.approx(180.)
    assert result['B']['F_ym'] == pytest.approx(-800.)
    assert result['B']['F_yp'] == pytest.approx(450.)
    for fluid in result.values():
        assert fluid['F_lateral'] == 0.
        assert fluid['lateral_frac'] == 0.
