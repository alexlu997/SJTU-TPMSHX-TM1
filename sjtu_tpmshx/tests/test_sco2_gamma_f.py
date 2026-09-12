"""D-2sc-2 — sCO2 γ_f production wiring contract (openspec: candidate D, D6).

Pins: (1) the frozen hot-free constants behave (center value, mild slope);
(2) window discipline — off-window means SMOOTH-WALL FALLBACK with a loud
one-shot warning, never slope extrapolation, never silent clamping;
(3) the kill switch restores pre-anchor behaviour; (4) the cf_scale
chokepoint multiplies exactly γ_f through; (5) the frozen constants match a
live refit against the CURRENT smooth base — the BASE-SWAP TRIPWIRE:
γ_f ≡ f_exp / f_cfd(base), so anyone refitting/replacing sco2_df or the
CFD-refit K face invalidates these constants and THIS test must go red.
"""
import warnings
from pathlib import Path

import numpy as np
import pytest

from sjtu_tpmshx.df_surrogate.sco2_gamma_f import (
    GAMMA_F_HOT, gamma_f_sco2, reset_warn_registry,
)

_REPO = Path(__file__).resolve().parents[2]
_SCO2_XLSX = _REPO / "data" / "raw_data" / 'experiments/sco2/sco2_DG7-t0p6_hx_experiment_summary.xlsx'


@pytest.fixture(autouse=True)
def _fresh_registry():
    reset_warn_registry()
    yield
    reset_warn_registry()


@pytest.mark.parametrize("topo", ["Diamond", "Gyroid"])
def test_gamma_at_center_is_G0(topo):
    p = GAMMA_F_HOT[topo]
    assert gamma_f_sco2(topo, p["Re_c"]) == pytest.approx(p["G0"], rel=1e-12)


@pytest.mark.parametrize("topo", ["Diamond", "Gyroid"])
def test_gamma_mild_monotone_in_window(topo):
    """The hot-free slope is MILD (transition-to-fully-rough trend): the
    window-edge ratio must stay well under 1.5× — a runaway exponent here
    means someone swapped in a cold-side-style artifact fit."""
    p = GAMMA_F_HOT[topo]
    g_lo = gamma_f_sco2(topo, p["re_lo"] * 1.001)
    g_hi = gamma_f_sco2(topo, p["re_hi"] * 0.999)
    assert g_hi > g_lo > 1.0
    assert g_hi / g_lo < 1.5


@pytest.mark.parametrize("probe", ["below", "above"])
def test_off_window_smooth_fallback_with_one_shot_warning(probe):
    p = GAMMA_F_HOT["Diamond"]
    Re = p["re_lo"] * 0.5 if probe == "below" else p["re_hi"] * 2.0
    with pytest.warns(UserWarning, match="SMOOTH-WALL"):
        assert gamma_f_sco2("Diamond", Re) == 1.0
    # one-shot: second call must stay silent (registry) and still return 1.0
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert gamma_f_sco2("Diamond", Re) == 1.0


def test_unknown_topology_falls_back_smooth():
    with pytest.warns(UserWarning, match="no experimental anchor"):
        assert gamma_f_sco2("Primitive", 2.0e4) == 1.0


def test_kill_switch_restores_smooth_wall(monkeypatch):
    monkeypatch.setenv("TPMSHX_SCO2_GAMMA_F", "0")
    p = GAMMA_F_HOT["Diamond"]
    assert gamma_f_sco2("Diamond", p["Re_c"]) == 1.0


def test_cf_scale_chokepoint_multiplies_exactly_gamma(monkeypatch):
    """ON/OFF ratio of the production chokepoint == γ_f(Re_in) bit-exactly
    (proves the wiring is a pure multiplier — zoned/κ layering untouched)."""
    from sjtu_tpmshx.df_surrogate.predict import sco2_cf_scale
    from sjtu_tpmshx.df_surrogate.smooth_df import _geom

    tpms, L, t, eps_f = "Diamond", 7.0, 0.6, 0.4
    rho, mu, u = 300.0, 2.6e-5, 1.0       # Re_in lands mid-window
    _, D_h = _geom(tpms, L, t)
    Re_in = rho * u * D_h / mu
    p = GAMMA_F_HOT[tpms]
    assert p["re_lo"] < Re_in < p["re_hi"], "probe must sit in-window"

    monkeypatch.setenv("TPMSHX_SCO2_GAMMA_F", "0")
    s_off = sco2_cf_scale(tpms, L, t, eps_f, rho, mu, u)
    monkeypatch.setenv("TPMSHX_SCO2_GAMMA_F", "1")
    s_on = sco2_cf_scale(tpms, L, t, eps_f, rho, mu, u)
    assert s_on / s_off == pytest.approx(gamma_f_sco2(tpms, Re_in), rel=1e-12)


@pytest.mark.skipif(not _SCO2_XLSX.exists(),
                    reason="sCO2 experiment Excel not on this machine")
@pytest.mark.parametrize("topo", ["Diamond", "Gyroid"])
def test_frozen_constants_match_live_refit(topo):
    """BASE-SWAP TRIPWIRE: refit hot-free γ_f from the raw experiment Excel
    against the LIVE smooth base and compare to the frozen constants.
    γ_f is base-relative (γ ≡ f_exp/f_cfd) — if sco2_df's prebuilt table,
    the CFD-refit K face, or the loader's reduction convention moves, this
    goes red and the constants must be re-derived (do NOT loosen the tol)."""
    from sjtu_tpmshx.validation.sco2_exp.compare_exp_vs_cfd import analyse
    from sjtu_tpmshx.validation.sco2_exp.gamma_f_variants import fit_gamma

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # known extrapolation notices
        r = analyse(topo)
    g = r["f_set"][r["f_set"].side == "hot"]
    Re = g["Re"].to_numpy(float)
    post = fit_gamma(Re, g["gamma_f"].to_numpy(float), slope_free=True)

    p = GAMMA_F_HOT[topo]
    assert post.G0 == pytest.approx(p["G0"], rel=1e-9)
    assert post.b1 == pytest.approx(p["dexp"], rel=1e-9)
    assert post.Re_c == pytest.approx(p["Re_c"], rel=1e-9)
    assert float(np.sqrt(post.s2)) == pytest.approx(p["sig_ln"], rel=1e-9)
    assert post.n == p["n"]
    assert float(Re.min()) == pytest.approx(p["re_lo"], rel=1e-12)
    assert float(Re.max()) == pytest.approx(p["re_hi"], rel=1e-12)
