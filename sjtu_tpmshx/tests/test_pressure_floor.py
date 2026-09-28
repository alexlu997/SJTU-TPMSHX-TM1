"""The pressure clip must also floor the STORED gauge field, not only the
temporary copy used for rho.

Audit (2026-06-25): `_update_density` computed `P_abs = P_ref_abs + P`, clipped
that *copy* to [1 kPa, 10 MPa] for the ideal-gas rho, but left `self.P`
unbounded. In a choked solve (P_ref_abs collapses to ~100 Pa) the stored gauge
field then carried a negative *absolute* pressure into the momentum
pressure-gradient source. Flooring the stored gauge where the clip engages
removes that; an in-envelope solve never clips, so `self.P` is untouched
(bit-identical).
"""
from types import SimpleNamespace

import numpy as np

from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver


def _pressure_state(P, P_ref_abs):
    P = np.asarray(P, dtype=np.float64)
    return SimpleNamespace(
        fluid_type='ideal_gas', massflux_inlet=False,
        P_ref_abs=float(P_ref_abs), R_gas=287.05, alpha_rho=1.0,
        P=P, T_field=np.full(P.shape, 800.0),
        rho_field=np.ones(P.shape),
        _apply_massflux_inlet=lambda: None,   # disabled; no-op for this test
    )


# ── 3D ─────────────────────────────────────────────────────────────────────
def test_3d_floors_stored_gauge_when_clip_engages():
    # cell0 abs = 100 + (-5000) = -4900 Pa (< 1 kPa) -> must be floored.
    m = _pressure_state([[[-5000.0, 50000.0]]], P_ref_abs=100.0)
    SIMPLESolver3D._update_density(m)
    P_abs = m.P_ref_abs + m.P
    assert P_abs.min() >= 1.0e3 - 1e-6, \
        f"stored gauge still carries sub-1kPa abs pressure: {P_abs.min()}"


def test_3d_in_envelope_leaves_gauge_bit_identical():
    # All abs pressures well inside [1 kPa, 10 MPa] -> clip no-op -> P unchanged.
    P0 = np.array([[[40000.0, 50000.0, 60000.0]]], dtype=np.float64)
    m = _pressure_state(P0.copy(), P_ref_abs=101325.0)
    SIMPLESolver3D._update_density(m)
    assert np.array_equal(m.P, P0), "in-envelope solve must not touch self.P"


# ── 2D ─────────────────────────────────────────────────────────────────────
def test_2d_floors_stored_gauge_when_clip_engages():
    m = _pressure_state([[-5000.0, 50000.0]], P_ref_abs=100.0)
    SIMPLESolver._update_density(m)
    P_abs = m.P_ref_abs + m.P
    assert P_abs.min() >= 1.0e3 - 1e-6, \
        f"2D stored gauge still carries sub-1kPa abs pressure: {P_abs.min()}"


def test_2d_in_envelope_leaves_gauge_bit_identical():
    P0 = np.array([[40000.0, 50000.0, 60000.0]], dtype=np.float64)
    m = _pressure_state(P0.copy(), P_ref_abs=101325.0)
    SIMPLESolver._update_density(m)
    assert np.array_equal(m.P, P0), "in-envelope solve must not touch self.P"
