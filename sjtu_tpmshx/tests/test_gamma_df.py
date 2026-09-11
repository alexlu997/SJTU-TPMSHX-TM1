"""Tests for the GammaDF opt-in surrogate backend (2026-06-12).

Pins the v4 scoreboard values (see gamma_df.py module docstring and the
research scripts temp_df_gamma_mf*.py) and verifies that the production
default path (rbf) is untouched by the new routing.
"""
import numpy as np
import pytest

import sjtu_tpmshx.df_surrogate.predict as P
from sjtu_tpmshx.df_surrogate.gamma_df import GammaDF, GATE_CF_G7
from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry


def _ef(tp, L, t):
    return tpms_geometry(tp, L, t, 16.0)["epsilon"] / 2


@pytest.fixture(scope="module")
def gyroid():
    return GammaDF("Gyroid")


@pytest.fixture(scope="module")
def diamond(gyroid):
    return GammaDF("Diamond", smooth=gyroid.sm)


# ---------------- model values (v4 scoreboard pins) ----------------

def test_gate_point_identical_to_production(gyroid):
    """Shanghai calibration point: cF must equal production exactly."""
    _, cF = gyroid.predict(7.0, 0.6)
    assert cF == pytest.approx(GATE_CF_G7, rel=1e-9)


def test_d7_blind_value(diamond):
    """D7/t0.6 blind prediction — regression pin (ref ~454 bridged)."""
    _, cF = diamond.predict(7.0, 0.6)
    assert cF == pytest.approx(454.19, rel=2e-3)


def test_trusted_anchors_faithful(gyroid, diamond):
    """In-sample fit must track every trusted anchor within 5%
    (G8 anchors especially: the v3 floor forced +9..13% there)."""
    for model in (gyroid, diamond):
        for (L, t), cf_exp in model.anchors.items():
            if L not in (6, 8):
                continue
            _, cF = model.predict(float(L), float(t))
            assert abs(cF / cf_exp - 1) < 0.05, (model.tpms, L, t, cF, cf_exp)


def test_g8_not_floored(gyroid):
    """Anchor-faithful gamma < 1 at G_L8 (Re_ref-convention value)."""
    assert 0.85 < gyroid.gamma(8.0, 0.4) < 1.0
    _, cF = gyroid.predict(8.0, 0.4)
    assert cF == pytest.approx(187.6, rel=5e-3)   # exp anchor 188.6


def test_curvature_structural_rule(gyroid, diamond):
    """Diamond layers' curvatures agree in sign -> shared c; Gyroid not."""
    assert diamond.use_curvature is True
    assert gyroid.use_curvature is False
    assert diamond._c < 0


# ---------------- L4/L5 extrapolation region ----------------

def test_lowL_flat6_and_floor(gyroid, diamond):
    for model in (gyroid, diamond):
        for t in (0.3, 0.4, 0.5):
            g4 = model.gamma(4.0, t)
            g5 = model.gamma(5.0, t)
            assert g4 == pytest.approx(g5, rel=1e-12)      # flat
            assert g4 >= 1.0                                # floor (lowL only)
            assert g4 == pytest.approx(
                max(1.0, model._ev(6, t)), rel=1e-12)       # = gamma(L6, t)


def test_lowL_blend_continuity(diamond):
    """gamma continuous across the 5->6 blend and at the L=6 joint."""
    t = 0.4
    g55 = diamond.gamma(5.5, t)
    lo, hi = sorted((diamond.gamma(5.0, t), diamond.gamma(6.0, t)))
    assert lo - 1e-9 <= g55 <= hi + 1e-9
    assert diamond.gamma(5.999, t) == pytest.approx(
        diamond.gamma(6.0, t), rel=1e-2)


def test_lowL_band(gyroid, diamond):
    lo, hi = diamond.lowL_band(4.0, 0.4)
    assert lo == 1.0
    assert hi > diamond.gamma(4.0, 0.4)        # Colebrook above flat6 (D)
    lo_g, hi_g = gyroid.lowL_band(4.0, 0.4)
    assert hi_g == pytest.approx(gyroid.gamma(4.0, 0.4), rel=1e-9)  # fallback


# ---------------- semantics ----------------

def test_K_is_cfd_surface(diamond):
    """GammaDF K is the CFD-refit surface (2026-06-30), NOT the SmoothDF Dh²
    trend. At a grid geometry the log-space TPS returns ~the tabulated CFD K."""
    import csv
    from pathlib import Path
    K, _ = diamond.predict(6.0, 0.4)
    K_sm, _ = diamond.sm.predict_K_B("Diamond", 6.0, 0.4)
    assert K != pytest.approx(K_sm, rel=1e-3), "K should be the CFD surface, not SmoothDF"
    tbl = (Path(__file__).resolve().parents[1] / "df_surrogate"
           / "_prebuilt" / "df_cfd_coeffs.csv")
    ktab = {f"{r['tp']} {r['L']} {r['t']}": float(r['K'])
            for r in csv.DictReader(tbl.open())}
    assert K == pytest.approx(ktab["Diamond 6.0 0.4"], rel=0.02)


def test_unsupported_lattice_raises():
    with pytest.raises(ValueError):
        GammaDF("Primitive")


# ---------------- predict.py routing ----------------

def test_default_is_fixed_cfd(monkeypatch):
    monkeypatch.delenv("TPMSHX_DF_METHOD", raising=False)
    ef = _ef("Gyroid", 7.0, 0.6)
    K, cF = P.predict_K_cF("Gyroid", 7.0, 0.6, ef)
    K0, cF0 = P.predict_K_cF(
        "Gyroid", 7.0, 0.6, ef, method="cfd_full_core_3cell_fixed_v2")
    assert (K, cF) == (K0, cF0)


def test_rbf_restorable(monkeypatch):
    """Old default must stay reachable: env=rbf -> SurrogateV3 bit-identical."""
    monkeypatch.setenv("TPMSHX_DF_METHOD", "rbf")
    ef = _ef("Gyroid", 7.0, 0.6)
    K, cF = P.predict_K_cF("Gyroid", 7.0, 0.6, ef)
    K0, cF0 = P._get_model("Gyroid", "rbf").predict(7.0, 0.6, ef)
    assert (K, cF) == (K0, cF0)


def test_env_routing(monkeypatch, gyroid):
    monkeypatch.setenv("TPMSHX_DF_METHOD", "gamma_df")
    ef = _ef("Gyroid", 7.0, 0.6)
    K, cF = P.predict_K_cF("Gyroid", 7.0, 0.6, ef)
    Kg, cFg = gyroid.predict(7.0, 0.6)
    assert cF == pytest.approx(cFg, rel=1e-12)
    assert K == pytest.approx(Kg, rel=1e-12)


def test_method_kwarg_wins_over_env(monkeypatch, gyroid):
    monkeypatch.setenv("TPMSHX_DF_METHOD", "rbf")
    ef = _ef("Gyroid", 7.0, 0.6)
    _, cF = P.predict_K_cF("Gyroid", 7.0, 0.6, ef, method="gamma_df")
    assert cF == pytest.approx(gyroid.predict(7.0, 0.6)[1], rel=1e-12)


def test_invalid_method_raises():
    with pytest.raises(ValueError):
        P.predict_K_cF("Gyroid", 7.0, 0.6, 0.368, method="nope")


def test_vec_gamma_matches_scalar(monkeypatch, diamond):
    monkeypatch.delenv("TPMSHX_DF_METHOD", raising=False)
    L = np.array([4.0, 6.0, 7.0, 8.0])
    t = np.array([0.4, 0.4, 0.6, 0.5])
    ef = np.zeros(4)
    Kv, cv = P.predict_K_cF_vec("Diamond", L, t, ef, method="gamma_df")
    for i in range(4):
        Ks, cs = diamond.predict(L[i], t[i])
        assert Kv[i] == pytest.approx(Ks, rel=1e-12)
        assert cv[i] == pytest.approx(cs, rel=1e-12)


def test_vec_default_is_fixed_cfd(monkeypatch):
    monkeypatch.delenv("TPMSHX_DF_METHOD", raising=False)
    L = np.array([5.0, 7.0]); t = np.array([0.4, 0.6])
    ef = np.array([_ef("Gyroid", 5.0, 0.4), _ef("Gyroid", 7.0, 0.6)])
    Kv, cv = P.predict_K_cF_vec("Gyroid", L, t, ef)
    K0, cF0 = P.predict_K_cF_vec(
        "Gyroid", L, t, ef, method="cfd_full_core_3cell_fixed_v2")
    assert np.array_equal(Kv, K0)
    assert np.array_equal(cv, cF0)


def test_vec_rbf_batch_contract(monkeypatch):
    """method='rbf' vec path = pure RBF batched eval (legacy contract)."""
    monkeypatch.delenv("TPMSHX_DF_METHOD", raising=False)
    L = np.array([5.0, 7.0]); t = np.array([0.4, 0.6])
    ef = np.array([_ef("Gyroid", 5.0, 0.4), _ef("Gyroid", 7.0, 0.6)])
    Kv, cv = P.predict_K_cF_vec("Gyroid", L, t, ef, method="rbf")
    model = P._get_model("Gyroid", "rbf")
    X = np.column_stack([L, t, ef])
    assert np.allclose(Kv, np.maximum(10.0 ** model._rbf_K(X), model.K_min))
    assert np.allclose(cv, 10.0 ** model._rbf_cF(X))
