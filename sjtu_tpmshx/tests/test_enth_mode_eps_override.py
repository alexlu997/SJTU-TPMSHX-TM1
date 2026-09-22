"""N4 (full-debug audit 2026-06-28): under an offset-isosurface δ≠0 the
enthalpy-mode LTNE m_dot was built with the SYMMETRIC 0.5·ε per side (no
eps_side_override), while the kernel simultaneously received the asymmetric
eps_A/eps_B fields — an internally inconsistent ṁ·h duty (ṁ mis-scaled by
split_A/0.5, ~20% at split_A=0.6). The main extraction path already passes the
per-side override; the enthalpy block must use the SAME override.

These cover the shared override helper and the _simple_mass_flow scaling
mechanism it relies on. δ=0 (every production / 703 / golden config) -> None ->
symmetric 0.5·ε (bit-identical), so the fix is latent until an asymmetric-porosity
sCO2/water enthalpy-mode case is run.
"""
import numpy as np
import pytest

from sjtu_tpmshx.preprocess.thermal_geometry import prepare_thermal_geometry
from sjtu_tpmshx.solvers.backends.python.three_d.runtime import _prepared_eps_overrides
from sjtu_tpmshx.solvers.backends.python.three_d.flux import _simple_mass_flow


def test_per_side_eps_override_none_at_delta0():
    cfg = {'thermal_geometry': prepare_thermal_geometry('Diamond', 7., .6, 16.)}
    ovA, ovB = _prepared_eps_overrides(cfg, .7)
    assert ovA is None and ovB is None


def test_per_side_eps_override_splits_at_delta_nonzero():
    cfg = {'delta_levelset': .3, 'thermal_geometry':
           prepare_thermal_geometry('Diamond', 7., .6, 16., delta=.3)}
    eps = 0.7
    ovA, ovB = _prepared_eps_overrides(cfg, eps)
    assert ovA is not None and ovB is not None
    # the two single-channel voids sum to the total ε
    assert ovA + ovB == pytest.approx(eps)
    # genuinely asymmetric (δ≠0 → split_A ≠ 0.5 → ovA ≠ 0.5·ε)
    assert abs(ovA - 0.5 * eps) > 1e-6


def _stub_solver(Nx, Nz, eps, v_in=3.0, rho=1.2, d=0.01):
    class _S:
        pass
    s = _S()
    s.v = np.zeros((Nx, 3, Nz)); s.v[:, 0, :] = v_in
    s.rho_field = np.full((Nx, 3, Nz), rho)
    s.dx = np.full(Nx, d); s.dz = np.full(Nz, d)
    s.eps_field = np.full((Nx, 3, Nz), eps)
    return s


def test_simple_mass_flow_eps_side_override_scales_mdot():
    """ṁ ∝ per-side void: the override replaces the symmetric 0.5·ε with the
    asymmetric ε·split, so ṁ scales by split/0.5 — the mechanism the N4 fix
    relies on when it passes eps_side_override in the enthalpy block."""
    Nx, Nz, eps, split = 2, 2, 0.8, 0.6
    s = _stub_solver(Nx, Nz, eps)
    m_sym = _simple_mass_flow(s, eps_f_per_side=0.5 * eps)
    m_ov = _simple_mass_flow(s, eps_f_per_side=0.5 * eps,
                             eps_side_override=eps * split)
    assert m_sym > 0.0
    assert m_ov == pytest.approx(m_sym * (eps * split) / (0.5 * eps))
    assert m_ov == pytest.approx(m_sym * split / 0.5)
