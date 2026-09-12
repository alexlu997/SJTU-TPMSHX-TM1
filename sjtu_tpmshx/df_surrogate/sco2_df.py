"""sCO2 smooth-wall Forchheimer closure from the 2026-07 unit-cell CFD campaign.

    cF_sco2(tp, L, t, Re) = B(tp, L, t) · (Re/1000)^(−m_tp)     [SMOOTH WALL]
    K                     = production CFD-refit K face (predict_K_cF) —
                            UNCHANGED: the sCO2 data (Re ≳ 2600, Darcy share
                            ≤ 4 %) cannot identify K; low-Re behaviour stays
                            anchored to the water CFD.

Data: Diamond 5399 + Gyroid 5400 cases, ``data/raw_data/cfd/sco2/`` (smooth
wall RANS, no gravity; P ∈ {8,10,12,15} MPa on the pseudocritical line).
REBUILT 2026-07-26 (iter 85) on the Gyroid L=8 completion: **20 D / 20 G**
geometries, 10799 cases. That upload is PURELY ADDITIVE — the prior 4400
Gyroid rows survive bit-identically (max rel dev 3e-16); the 1000 new rows are
all L=8 (G_8_3 80→270 cases, G_8_4/5/6 0→270, previously ABSENT). Diamond is
untouched and its table rebuilt bit-identically, which is the control.
Prior: REBUILT 2026-07-25 (iter 78) on the corrected 2026-07-23 export,
20 D / 17 G geometries (was 15 / 12), 9799 cases — ledger SCO2-F-REFIT-0725.
Fit: per-geometry B (K fixed from SmoothDF), per-lattice pooled Re-slope m —
identical math to ``validation/sco2_cfd/compare_smooth_df.py`` (which imports
the fit helpers from HERE; keep single-sourced). Point-level refit RMSRE
8.86 % (Diamond, unchanged) / 8.01 % (Gyroid; was 7.80 % on 17 geometries —
3 more geometries widen the fit, not a regression. The Nu LOGO metric moved
the OTHER way, 8.4 %→7.9 %, i.e. the L=8 column was genuinely the weak spot).
Gyroid pooled m 0.11784→0.11244 and its per-geometry B fell ~1.5 %, but the
two changes cancel: cF = B·(Re/1000)^−m moves ≤0.64 % across the whole fit
window for every geometry except G_8_3 (+4.2…+5.1 %, the one that gained
3.4× more samples). Cross-fluid back-test vs water CFD in
``reports/sco2_cfd/`` (ledger SCO2-CFD).

⚠ SEMANTICS: this module stays the SMOOTH-WALL cF — SLM roughness is
deliberately NOT modelled HERE and must never be (double-count guard).
Since 2026-07-22 the experimental anchor lands ONE LAYER UP:
``predict.sco2_cf_scale`` multiplies this smooth value by the HX-level
correction ``sco2_gamma_f.gamma_f_sco2`` (D6 hot-free, D-7-6/G-7-6
experiments, in-window only — off-window the solver falls back to this
smooth estimate with a loud warning). Validation baselines (γ ≡ f_exp/f_cfd,
``validation/sco2_exp``) keep calling ``predict_cF_sco2`` directly so the
correction never feeds back into its own definition. Baking roughness into
THIS file would double-count with γ_f — don't.

Geometry domain (2026-07-25 rebuild): Diamond the FULL 5×4 grid
L ∈ {4,5,6,7,8} × t ∈ {0.3,0.4,0.5,0.6}; Gyroid the same minus
(8, 0.4/0.5/0.6) — 17 nodes. **(7, 0.6) — the D-7-6 / G-7-6 prototype
geometry — is now an interpolation NODE for both lattices** (it used to sit
outside the hull: the old domain was D L ∈ [4,7] with no 7/0.6 and
G L ∈ [4,6], so the prototype prediction rode an RBF extrapolation and
tripped the warning below). Off-grid
(L, t) interpolate via log-space RBF; outside the hull extrapolates with a
one-shot warning. Re outside [~2600, ~66000] extrapolates the (Re/1000)^−m
slope (below ~1000 it overshoots — water back-test measured +21 % medAPE at
Re<1000; sCO2 runs live well above that).

Rebuild the prebuilt table (needs the raw sCO2 CFD csvs on disk):
    python -m df_surrogate.sco2_df
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
from sjtu_tpmshx.logutil import get_logger  # noqa: E402

_log = get_logger(__name__)

PREBUILT_CSV = _THIS.parent / "_prebuilt" / "sco2_df_coeffs.csv"


# ── fit helpers (single source; validation/sco2_cfd imports these) ────────

def fit_B(d: pd.DataFrame, K: float, m: float) -> float:
    """Fixed-K, fixed-m relative least squares for B on raw dpdl rows.

    ``d`` needs columns Um_m_s / rho_kg_m3 / mu_Pa_s / Re / dpdl_Pa_m
    (the ``load_sco2_cfd.load_core`` schema).
    """
    u, rho, mu = d["Um_m_s"].values, d["rho_kg_m3"].values, d["mu_Pa_s"].values
    Re, y = d["Re"].values, d["dpdl_Pa_m"].values
    resid = y - mu * u / K                       # Forchheimer part of dpdl
    basis = rho * (Re / 1000.0) ** (-m) * u ** 2
    w = 1.0 / y                                  # relative weighting
    return float(np.sum(w * w * basis * resid)
                 / np.sum(w * w * basis * basis))


def fit_pooled_m(core: pd.DataFrame, sm, tpms: str) -> float:
    """Pooled sCO2 Re-slope m: grid search, per-geometry B refit inside."""
    from scipy.optimize import minimize_scalar

    groups = [(gid, d, sm.predict_K_B(tpms, d["L_mm"].iloc[0],
                                      d["t_mm"].iloc[0])[0])
              for gid, d in core.groupby("geometry_id")]

    def cost(m):
        errs = []
        for _, d, K in groups:
            B = fit_B(d, K, m)
            u, rho, mu = (d["Um_m_s"].values, d["rho_kg_m3"].values,
                          d["mu_Pa_s"].values)
            pred = mu * u / K + rho * B * (d["Re"].values / 1000.0) ** (-m) \
                * u ** 2
            errs.append((pred - d["dpdl_Pa_m"].values) / d["dpdl_Pa_m"].values)
        e = np.concatenate(errs)
        return float(np.sqrt(np.mean(e * e)))

    r = minimize_scalar(cost, bounds=(0.0, 0.5), method="bounded",
                        options={"xatol": 1e-4})
    return float(r.x)


# ── builder ────────────────────────────────────────────────────────────────

def build_table() -> pd.DataFrame:
    """Fit per-geometry B + per-lattice m from the raw sCO2 CFD; write CSV."""
    from sjtu_tpmshx.df_surrogate.load_sco2_cfd import LATTICES, load_core
    from sjtu_tpmshx.df_surrogate.smooth_df import SmoothDF

    sm = SmoothDF()
    rows = []
    for tpms in LATTICES:
        core = load_core(tpms)
        m = fit_pooled_m(core, sm, tpms)
        for gid, d in core.groupby("geometry_id"):
            L, t = float(d["L_mm"].iloc[0]), float(d["t_mm"].iloc[0])
            K, _ = sm.predict_K_B(tpms, L, t)
            rows.append(dict(tp=tpms, L=L, t=t,
                             eps_f=float(d["eps_f"].iloc[0]),
                             Dh=float(d["Dh_m"].iloc[0]),
                             K=K, B=fit_B(d, K, m), m=m, n=len(d)))
        _log.info(f"[{tpms}] pooled m = {m:.4f}, "
                  f"{core['geometry_id'].nunique()} geometries")
    table = pd.DataFrame(rows)
    PREBUILT_CSV.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(PREBUILT_CSV, index=False)
    _log.info(f"wrote {PREBUILT_CSV} ({len(table)} rows)")
    return table


# ── predictor ──────────────────────────────────────────────────────────────

class _Sco2CF:
    """log-space RBF of B over (L, t) per lattice + pooled m. Prebuilt-backed."""

    def __init__(self, table: pd.DataFrame | None = None):
        if table is None:
            if not PREBUILT_CSV.exists():
                raise FileNotFoundError(
                    f"prebuilt table missing: {PREBUILT_CSV} — run "
                    f"`python -m df_surrogate.sco2_df` (needs the raw sCO2 "
                    f"CFD csvs under data/raw_data/cfd/sco2/)")
            table = pd.read_csv(PREBUILT_CSV)
        self.table = table
        from scipy.interpolate import RBFInterpolator
        self._lat = {}
        for tp, d in table.groupby("tp"):
            X = d[["L", "t"]].to_numpy(float)
            rbf = RBFInterpolator(X, np.log10(d["B"].values), kernel="cubic",
                                  smoothing=0.0)
            box = (X[:, 0].min(), X[:, 0].max(),
                   X[:, 1].min(), X[:, 1].max())
            self._lat[tp] = dict(m=float(d["m"].iloc[0]), rbf=rbf, box=box)

    _warned: set = set()

    def cF(self, tpms: str, L_mm: float, t_mm: float, Re) -> float:
        if tpms not in self._lat:
            raise NotImplementedError(
                f"sCO2 D-F fit only available for {sorted(self._lat)}; "
                f"{tpms!r} unsupported.")
        p = self._lat[tpms]
        lo_L, hi_L, lo_t, hi_t = p["box"]
        if not (lo_L <= L_mm <= hi_L and lo_t <= t_mm <= hi_t):
            key = (tpms, round(L_mm, 2), round(t_mm, 2))
            if key not in self._warned:
                self._warned.add(key)
                warnings.warn(
                    f"[sCO2 cF extrap] {tpms} (L={L_mm:g}, t={t_mm:g}) mm "
                    f"outside the sCO2 CFD hull L[{lo_L:g},{hi_L:g}] × "
                    f"t[{lo_t:g},{hi_t:g}] — RBF extrapolation.",
                    stacklevel=3)
        B = 10.0 ** float(p["rbf"](np.array([[L_mm, t_mm]]))[0])
        return B * (np.maximum(np.asarray(Re, dtype=float), 1.0)
                    / 1000.0) ** (-p["m"])


_SINGLETON: _Sco2CF | None = None


def predict_cF_sco2(tpms: str, L_mm: float, t_mm: float, Re) -> float:
    """Smooth-wall sCO2 Forchheimer cF(Re) [1/m]. See module docstring."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = _Sco2CF()
    return _SINGLETON.cF(tpms, L_mm, t_mm, Re)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    t = build_table()
    print(t.round(4).to_string(index=False))
