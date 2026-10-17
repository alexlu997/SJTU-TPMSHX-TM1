"""The shared pressure face reduction keeps its original spatial order gates."""
import numpy as np
import pytest
from types import SimpleNamespace

from sjtu_tpmshx.result_math import pressure_face_values

LY = 0.042  # streamwise length (m), Shanghai-ish


def _Pfield(y):
    # smooth, with NONZERO, ASYMMETRIC gradient at both end faces so the
    # cell-centre half-cell offset is a genuine O(h) term (no symmetry
    # cancellation). A pressure-drop profile decays ~exponentially streamwise.
    return 1000.0 * np.exp(-3.0 * y / LY)


def _exact_dP():
    return float(_Pfield(0.0) - _Pfield(LY))


def _make_state(Ny):
    # streamwise = axis 1; Nx = Nz = 1. cell centres at (j+0.5)*h.
    h = LY / Ny
    yc = (np.arange(Ny) + 0.5) * h
    P = _Pfield(yc)[None, :, None]          # (1, Ny, 1)
    ones = np.ones((1, 1), dtype=np.float64)
    return SimpleNamespace(P=P, inlet_frac=ones, outlet_frac=ones,
                           dx=np.ones(1), dy=np.full(Ny, h), dz=np.ones(1))


@pytest.mark.parametrize('widths', [[.1, .9], [.1, .2, .4, .3], [.3, .4, .2, .1]])
def test_nonuniform_affine_pressure_reaches_physical_faces(widths):
    s = _make_state(len(widths))
    s.dy = np.array(widths) * LY
    yc = np.cumsum(s.dy) - .5 * s.dy
    s.P = (1234. - 700. * yc / LY)[None, :, None]
    assert float((pressure_face_values(s.P, s.dy)[0] - pressure_face_values(s.P, s.dy)[1]).item()) == pytest.approx(700., abs=1e-10)


def test_uniform_face_extrap_preserves_exact_result():
    s = _make_state(8)
    expected = float((1.5 * s.P[:, 0, :] - .5 * s.P[:, 1, :]).item()
                     - (1.5 * s.P[:, -1, :] - .5 * s.P[:, -2, :]).item())
    assert float((pressure_face_values(s.P, s.dy)[0] - pressure_face_values(s.P, s.dy)[1]).item()) == expected


def test_single_cell_pressure_has_zero_drop():
    s = _make_state(1)
    assert float((pressure_face_values(s.P, s.dy)[0] - pressure_face_values(s.P, s.dy)[1]).item()) == float((s.P[:, 0] - s.P[:, -1]).item())


def _orders():
    Nys = [8, 16, 32, 64, 128]
    exact = _exact_dP()
    e_cell, e_face = [], []
    for Ny in Nys:
        s = _make_state(Ny)
        e_cell.append(abs(float((s.P[:, 0] - s.P[:, -1]).item()) - exact))
        e_face.append(abs(float((pressure_face_values(s.P, s.dy)[0] - pressure_face_values(s.P, s.dy)[1]).item()) - exact))
    h = 1.0 / np.array(Nys, dtype=float)
    p_cell = np.polyfit(np.log(h), np.log(e_cell), 1)[0]
    p_face = np.polyfit(np.log(h), np.log(e_face), 1)[0]
    return p_cell, p_face, e_cell, e_face


def test_cell_centre_dp_is_first_order():
    p_cell, _, _, _ = _orders()
    assert 0.7 < p_cell < 1.4, f"cell-centre dP order {p_cell:.2f} (expected ~1)"


def test_face_extrap_dp_is_second_order():
    _, p_face, _, e_face = _orders()
    assert p_face > 1.8, f"face-extrapolated dP order {p_face:.2f} (expected ~2)"


def test_face_is_more_accurate_than_cell():
    _, _, e_cell, e_face = _orders()
    # on the finest grid the 2nd-order extractor must be strictly closer
    assert e_face[-1] < e_cell[-1]


if __name__ == "__main__":
    pc, pf, ec, ef = _orders()
    print(f"cell-centre dP order = {pc:.3f}")
    print(f"face-extrap  dP order = {pf:.3f}")
    print(f"finest-grid err: cell={ec[-1]:.4g}  face={ef[-1]:.4g}  ratio={ec[-1]/ef[-1]:.1f}x")
