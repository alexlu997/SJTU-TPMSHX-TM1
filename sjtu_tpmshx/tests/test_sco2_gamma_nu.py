"""D-2sc-3 — sCO2 γ_Nu production wiring contract (candidate D, 2026-07-22).

Mirror of test_sco2_gamma_f.py for the heat-transfer side. Pins: (1) the
frozen pooled amplitudes (amplitude-ONLY — measured Re-slopes ±0.02, flat);
(2) element-wise window mixing (in-window cells ×γ, off-window cells keep
the smooth value — an anchor never extrapolates) with a one-shot warning;
(3) kill switch; (4) both production chokepoints (fluid_props._nu_sco2
registry dispatch + flux_3d._sco2_hv_local_field) multiply exactly γ;
(5) frozen-vs-live tripwire against the raw experiment Excel — γ_Nu is
base-relative (γ ≡ Nu_exp/Nu_cfd(SCO2_NU_COEFFS)): refitting the smooth Nu
coefficients invalidates these constants and this test must go red.
"""
import warnings
from pathlib import Path

import numpy as np
import pytest

from sjtu_tpmshx.models.nu_correlations import (
    GAMMA_NU_SCO2, SCO2_NU_COEFFS, gamma_nu_sco2,
    reset_gamma_nu_warn_registry,
)

_REPO = Path(__file__).resolve().parents[2]
_SCO2_XLSX = _REPO / "data" / "raw_data" / 'experiments/sco2/sco2_DG7-t0p6_hx_experiment_summary.xlsx'


@pytest.fixture(autouse=True)
def _fresh_registry():
    reset_gamma_nu_warn_registry()
    yield
    reset_gamma_nu_warn_registry()


@pytest.mark.parametrize("topo", ["Diamond", "Gyroid"])
def test_scalar_in_window_is_gamma(topo):
    p = GAMMA_NU_SCO2[topo]
    Re_mid = 0.5 * (p["re_lo"] + p["re_hi"])
    assert gamma_nu_sco2(topo, Re_mid) == pytest.approx(p["gamma"], rel=1e-12)


def test_elementwise_window_mixing_with_one_shot_warning():
    """A Re field straddling the window: inside ×γ, outside ×1 — per cell."""
    p = GAMMA_NU_SCO2["Diamond"]
    Re = np.array([p["re_lo"] * 0.5,          # below
                   0.5 * (p["re_lo"] + p["re_hi"]),   # inside
                   p["re_hi"] * 2.0])         # above
    with pytest.warns(UserWarning, match="SMOOTH-WALL"):
        g = gamma_nu_sco2("Diamond", Re)
    assert g[0] == 1.0 and g[2] == 1.0
    assert g[1] == pytest.approx(p["gamma"], rel=1e-12)
    with warnings.catch_warnings():          # one-shot: second call silent
        warnings.simplefilter("error")
        gamma_nu_sco2("Diamond", Re)


def test_unknown_topology_smooth():
    with pytest.warns(UserWarning, match="no experimental anchor"):
        assert gamma_nu_sco2("Primitive", 2.0e4) == 1.0


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("TPMSHX_SCO2_GAMMA_NU", "0")
    p = GAMMA_NU_SCO2["Diamond"]
    assert gamma_nu_sco2("Diamond", 0.5 * (p["re_lo"] + p["re_hi"])) == 1.0


def test_registry_chokepoint_stays_smooth(monkeypatch):
    """V1 runtime ignores the retained experimental correction helper."""
    from sjtu_tpmshx.models import fluid_props

    m = fluid_props.get("sco2")
    p = GAMMA_NU_SCO2["Diamond"]
    Re_mid = 0.5 * (p["re_lo"] + p["re_hi"])
    args = ("Diamond", Re_mid, 0.4, 7.0, 2.6, 0.9)   # (tp, Re, eps_f, L, Dh, Pr)
    monkeypatch.setenv("TPMSHX_SCO2_GAMMA_NU", "0")
    nu_off = float(m.nu(*args))
    monkeypatch.setenv("TPMSHX_SCO2_GAMMA_NU", "1")
    nu_on = float(m.nu(*args))
    assert nu_on == nu_off


def test_hv_local_field_chokepoint_stays_smooth(monkeypatch):
    """The shared 2D/3D local-property path stays on smooth-wall CFD Nu."""
    from sjtu_tpmshx.models.local_heat_transfer import _sco2_hv_local_field
    from sjtu_tpmshx.models import sco2_props as _s2

    P = 10.0e6
    T = np.full((2, 2, 2), 320.0)
    kw = dict(A_0=500.0, D_h_m=2.6e-3, tpms_type="Diamond", L_cell_mm=7.0)
    p = GAMMA_NU_SCO2["Diamond"]

    # pick velocities that land Re mid-window / above-window at this state
    rho = float(_s2.sco2_density(320.0, P))
    mu = float(_s2.sco2_viscosity(320.0, P))
    Re_of = lambda u: rho * u * kw["D_h_m"] / mu          # noqa: E731
    u_in = 0.5 * (p["re_lo"] + p["re_hi"]) * mu / (rho * kw["D_h_m"])
    u_out = p["re_hi"] * 2.0 * mu / (rho * kw["D_h_m"])
    assert p["re_lo"] < Re_of(u_in) < p["re_hi"]
    assert Re_of(u_out) > p["re_hi"]

    for u_val in (u_in, u_out):
        u = np.full((2, 2, 2), u_val)
        monkeypatch.setenv("TPMSHX_SCO2_GAMMA_NU", "0")
        hv_off = _sco2_hv_local_field(T, P, u, **kw)
        monkeypatch.setenv("TPMSHX_SCO2_GAMMA_NU", "1")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")   # off-window one-shot notice
            hv_on = _sco2_hv_local_field(T, P, u, **kw)
        assert np.array_equal(hv_on, hv_off)


def test_hv_local_field_uses_each_cells_temperature():
    """Uniform velocity must not freeze sCO2 transport properties at inlet T."""
    from sjtu_tpmshx.models.local_heat_transfer import _sco2_hv_local_field

    T = np.array([[320.0, 360.0], [400.0, 440.0]])
    hv = _sco2_hv_local_field(
        T, 12.0e6, np.full_like(T, 0.5),
        A_0=500.0, D_h_m=2.6e-3,
        tpms_type="Diamond", L_cell_mm=7.0)

    assert hv.shape == T.shape
    assert np.ptp(hv) > 0.0


def test_smooth_base_function_untouched():
    """nu_sco2_topo stays SMOOTH (validation-baseline contract): its value
    must equal the raw coefficient formula, γ-free."""
    from sjtu_tpmshx.models.nu_correlations import nu_sco2_topo
    co = SCO2_NU_COEFFS["Diamond"]
    Re, Pr, L, Dh = 2.0e4, 0.9, 7.0, 2.6
    expect = co["c"] * Re ** co["a"] * Pr ** (1 / 3) * (Dh / L) ** co["d"]
    assert nu_sco2_topo("Diamond", Re, Pr, L, Dh) \
        == pytest.approx(expect, rel=1e-12)


@pytest.mark.skipif(not _SCO2_XLSX.exists(),
                    reason="sCO2 experiment Excel not on this machine")
@pytest.mark.parametrize("topo", ["Diamond", "Gyroid"])
def test_frozen_constants_match_live_refit(topo):
    """BASE-SWAP TRIPWIRE: γ_Nu is the anchored-fit ratio against the LIVE
    smooth coefficients — recompute from the raw Excel and compare."""
    from sjtu_tpmshx.validation.sco2_exp.fit_nu_correction import analyse

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = analyse(topo)
    p = GAMMA_NU_SCO2[topo]
    assert r["gamma_nu_fit"] == pytest.approx(p["gamma"], rel=1e-9)
    ns = r["nu_set"]
    Re = ns["Re"].to_numpy(float)
    assert float(Re.min()) == pytest.approx(p["re_lo"], rel=1e-12)
    assert float(Re.max()) == pytest.approx(p["re_hi"], rel=1e-12)
    assert len(ns) == p["n"]
    sig = float(np.std(np.log(ns["gamma_Nu"].to_numpy(float)), ddof=1))
    assert sig == pytest.approx(p["sig_ln"], rel=1e-9)
