"""validation/_order_fit.py — equivalence vs the four retired local fits.

The old implementations (mms_phase_a3/a4/b4, phase_c_gci) are embedded
verbatim below and compared against the unified fit on representative
grid-refinement data, so the B1 1.2 consolidation is provably
number-preserving without re-running the (hours-long) MMS sweeps:

  * a3/a4 (np.polyfit) — bit-identical demanded
  * b4 (np.linalg.lstsq) — same least-squares problem, last-ulp tolerance
  * phase_c (err_floor=1e-6 masking) — bit-identical demanded
"""
import numpy as np
import pytest

from sjtu_tpmshx.validation.harness._order_fit import OrderFitResult, fit_order_loglog


# ── retired implementations, verbatim ───────────────────────────────

def _old_a3_fit_order(h_arr, err_arr):
    h = np.asarray(h_arr, dtype=np.float64)
    e = np.asarray(err_arr, dtype=np.float64)
    mask = (e > 0) & np.isfinite(e)
    if mask.sum() < 2:
        return float('nan'), float('nan'), float('nan')
    lh = np.log(h[mask]); le = np.log(e[mask])
    p, c = np.polyfit(lh, le, 1)
    le_pred = p * lh + c
    ss_res = np.sum((le - le_pred) ** 2)
    ss_tot = np.sum((le - le.mean()) ** 2)
    r2 = 1.0 - ss_res / (ss_tot + 1e-30)
    return float(p), float(c), float(r2)


def _old_b4_fit(hs, errs):
    lh = np.log(np.asarray(hs)); le = np.log(np.asarray(errs))
    A = np.vstack([lh, np.ones_like(lh)]).T
    coef, *_ = np.linalg.lstsq(A, le, rcond=None)
    slope = float(coef[0])
    pred = A @ coef
    ss_res = float(np.sum((le - pred) ** 2))
    ss_tot = float(np.sum((le - le.mean()) ** 2))
    r2 = 1.0 - ss_res / (ss_tot + 1e-30)
    return slope, r2


def _old_phase_c(Ns, Qs):
    Qs = np.asarray(Qs, dtype=np.float64)
    Q_inf = Qs[-1]
    h = 1.0 / np.asarray(Ns, dtype=np.float64)
    e = np.abs(Qs - Q_inf)
    msk = (e > 1e-6) & np.isfinite(e)
    if msk.sum() < 2:
        return float('nan')
    lh = np.log(h[msk]); le = np.log(e[msk])
    p, _ = np.polyfit(lh, le, 1)
    return float(p)


# ── representative refinement data (2nd-order-ish with noise) ───────

_GRIDS = np.array([12.0, 16.0, 20.0, 30.0, 40.0])
_H = 1.0 / _GRIDS
_ERR_SETS = [
    0.5 * _H ** 2.07,                          # clean 2nd order
    0.5 * _H ** 2.07 * np.array([1.0, 1.1, 0.93, 1.05, 0.98]),  # noisy
    np.array([3e-3, 2e-3, 1.4e-3, 6e-4, np.nan]),               # one NaN
]


@pytest.mark.parametrize('err', _ERR_SETS)
def test_bit_identical_vs_a3(err):
    p0, c0, r20 = _old_a3_fit_order(_H, err)
    r = fit_order_loglog(_H, err)
    assert (r.p == p0 or (np.isnan(r.p) and np.isnan(p0)))
    assert (r.c == c0 or (np.isnan(r.c) and np.isnan(c0)))
    assert (r.r2 == r20 or (np.isnan(r.r2) and np.isnan(r20)))


def test_last_ulp_vs_b4_lstsq():
    err = _ERR_SETS[1]
    p0, r20 = _old_b4_fit(_H, err)
    r = fit_order_loglog(_H, err)
    assert r.p == pytest.approx(p0, rel=1e-12)
    assert r.r2 == pytest.approx(r20, rel=1e-12)


def test_bit_identical_vs_phase_c_floor():
    Ns = [10, 16, 24, 32]
    Qs = [101.2, 100.4, 100.05, 100.0]   # finest is Q_inf proxy → e[-1]=0 masked
    p0 = _old_phase_c(Ns, Qs)
    h = 1.0 / np.asarray(Ns, dtype=np.float64)
    e = np.abs(np.asarray(Qs) - Qs[-1])
    r = fit_order_loglog(h, e, err_floor=1e-6)
    assert r.p == p0
    assert r.n_used == 3   # the zero point dropped by the floor


def test_underdetermined_returns_nan():
    r = fit_order_loglog([0.1, 0.05], [np.nan, -1.0])
    assert np.isnan(r.p) and np.isnan(r.c) and np.isnan(r.r2)
    assert r.n_used == 0
    assert isinstance(r, OrderFitResult)
