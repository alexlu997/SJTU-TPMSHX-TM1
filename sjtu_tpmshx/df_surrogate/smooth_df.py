"""Unified smooth-wall Darcy-Forchheimer model (water + air CFD).

    dp/L = mu*u/K  +  rho * B * (Re/1000)^(-m_lat) * u^2

Coefficients (validated 2026-06-11, see vault method doc
2026-06-11-df-water-cfd-c6-trust-hybrid-CN.html and the unified-model HTML):

    m_lat : per-lattice Re exponent, pooled water+air calibration
            (Diamond ~0.137, Gyroid ~0.106; read from the prebuilt CSV).
    K     : pure physical trend  K = 10^(2*log10(D_h) + b0_lattice).
            Per-geometry K from 3-param fits is weakly identified (correlated
            with m; 5x non-monotonic in-layer scatter) -> NO data residual.
            Permeability ~ D_h^2 dimensional law, robust intercept.
    B     : Forchheimer level at Re=1000.  Huber trend on log10(D_h)
            + cubic RBF residual over (L, t, eps_f), trust-region decay
            outside the data hull (C6 logic).

Validation battery (2620 CFD points, 40 geometries, Re 100-50000):
    interpolation  LOGO median 11.6% (p90 18.1%)
    geometry extrapolation LOLO all layers 11.7-15.6% (incl. edges)
    Re extrapolation: fit Re<=4000 -> predict above 9.3%; downward 13.8%
    cross-fluid (water-trained -> air) 19.3%

SCOPE — smooth-wall domain ONLY (CAD geometry, no SLM roughness):
C6 far-field base, optimizer exploration, low-Re design estimates,
baseline for future rough-wall CFD campaigns.  The production rough
surrogate (predict.predict_K_cF, Shanghai-validated dP RMSRE 7.19%)
is a DIFFERENT physical object (SLM roughness ~3x on c_F) and is NOT
replaced by this model — swapping it fails the Shanghai 3D gate.

Rebuild the prebuilt table:
    python -m df_surrogate.smooth_df  [--air-xlsx PATH]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.interpolate import RBFInterpolator

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent          # .../sjtu_tpmshx
from sjtu_tpmshx.models.tpms_props import geometry as tpms_geometry  # noqa: E402
from sjtu_tpmshx.logutil import get_logger  # noqa: E402

_log = get_logger(__name__)

PREBUILT_CSV = _THIS.parent / "_prebuilt" / "smooth_df_coeffs.csv"
WATER_XLSX = _PROJECT_ROOT.parent / "data" / "raw_data" / "water-cfd-raw.xlsx"
# Relocated+renamed ~2026-07 (was server-pyfluent\Data_All_1,0.xlsx); shape
# verified 2026-07-07: All_Cases_Combined, 840 data rows x 106 cols.
# REBUILD-ONLY asset, never migrated off the old dev box (it is NOT in the
# SJTU-TPMSHX-data repo): normal inference reads PREBUILT_CSV and never
# touches this. The dead default is kept as provenance; point
# TPMSHX_AIR_CFD_XLSX at the file if the asset ever lands (P1.7).
AIR_XLSX_DEFAULT = Path(os.environ.get(
    'TPMSHX_AIR_CFD_XLSX',
    r"D:\Postgraduate\server-pyfluent\Air\Cfd-air-raw-old-new.xlsx"))

_K_S_DEFAULT = 16.0


def _geom(tp: str, L: float, t: float, _cache={}) -> tuple[float, float]:
    """(eps_f, D_h[m]) for one geometry, quantized to 3 decimals and cached.

    The value MUST stay a pure function of the rounded key: geometry is
    evaluated AT the rounded (L, t), never at the caller's exact floats.
    Evaluating at exact floats under a rounded key (pre-2026-07-13 bug)
    made the cached value depend on which caller hit the key first, so
    cF drifted ~0.14% with call history. The 3-decimal quantization is
    intended — sub-µm L/t deltas are below geometry-model resolution.
    """
    k = (tp, round(float(L), 3), round(float(t), 3))
    if k not in _cache:
        g = tpms_geometry(tp, k[1], k[2], _K_S_DEFAULT)
        _cache[k] = (float(g["epsilon"]) / 2.0, float(g["D_h"]))
    return _cache[k]


class SmoothDF:
    """Smooth-wall D-F predictor built from the prebuilt coefficient table."""

    def __init__(self, table: pd.DataFrame | None = None,
                 tau_L: float = 1.0, tau_t: float = 0.1):
        if table is None:
            if not PREBUILT_CSV.exists():
                raise FileNotFoundError(
                    f"prebuilt table missing: {PREBUILT_CSV} — run "
                    f"`python -m df_surrogate.smooth_df` to build it")
            table = pd.read_csv(PREBUILT_CSV)
        self.table = table
        self.tau_L = float(tau_L)
        self.tau_t = float(tau_t)
        self._lat = {}
        from sklearn.linear_model import HuberRegressor
        for tp, d in table.groupby("tp"):
            lDh = np.log10(d.Dh.values).reshape(-1, 1)
            # K: pinned physical slope +2, robust intercept
            b0K = float(np.median(d.logK.values - 2.0 * lDh[:, 0]))
            # B: Huber trend + cubic RBF residual
            hub = HuberRegressor().fit(lDh, d.logB.values)
            res = d.logB.values - hub.predict(lDh)
            X = d[["L", "t", "ef"]].to_numpy(float)
            rbf = RBFInterpolator(X, res, kernel="cubic", smoothing=0.05)
            box = (X[:, 0].min(), X[:, 0].max(), X[:, 1].min(), X[:, 1].max())
            self._lat[tp] = dict(m=float(d.m_lat.iloc[0]), b0K=b0K,
                                 hub=hub, rbf=rbf, box=box)

    # ---------------- coefficient access ----------------
    def predict_K_B(self, tpms: str, L_mm: float, t_mm: float
                    ) -> tuple[float, float]:
        """(K [m^2], B [1/m]) — B is c_F anchored at Re=1000."""
        p = self._lat[tpms]
        ef, Dh = _geom(tpms, L_mm, t_mm)
        lDh = np.log10([[Dh]])
        logK = 2.0 * lDh[0][0] + p["b0K"]
        dL = max(0.0, p["box"][0] - L_mm, L_mm - p["box"][1]) / self.tau_L
        dt = max(0.0, p["box"][2] - t_mm, t_mm - p["box"][3]) / self.tau_t
        w = float(np.exp(-(dL * dL + dt * dt)))
        logB = (float(p["hub"].predict(lDh)[0])
                + w * float(p["rbf"](np.array([[L_mm, t_mm, ef]]))[0]))
        return 10.0 ** logK, 10.0 ** logB

    def predict_cF(self, tpms: str, L_mm: float, t_mm: float,
                   Re: float) -> float:
        """Re-dependent Forchheimer coefficient c_F(Re) [1/m]."""
        _, B = self.predict_K_B(tpms, L_mm, t_mm)
        return B * (float(Re) / 1000.0) ** (-self._lat[tpms]["m"])

    # ---------------- pressure drop ----------------
    def predict_dpdl(self, tpms: str, L_mm: float, t_mm: float,
                     u: float, rho: float, mu: float) -> float:
        """dp/L [Pa/m] at interstitial velocity u, fluid (rho, mu)."""
        K, B = self.predict_K_B(tpms, L_mm, t_mm)
        _, Dh = _geom(tpms, L_mm, t_mm)
        Re = rho * abs(u) * Dh / mu
        m = self._lat[tpms]["m"]
        cF = B * max(Re, 1.0e-6) ** 0.0 if Re <= 0 else B * (Re / 1000.0) ** (-m)
        return mu * u / K + rho * cF * u * abs(u)

    def predict_dP(self, tpms: str, L_mm: float, t_mm: float,
                   u: float, rho: float, mu: float,
                   L_channel_m: float) -> float:
        """Incompressible dP [Pa] over channel length."""
        return self.predict_dpdl(tpms, L_mm, t_mm, u, rho, mu) * L_channel_m


# =====================================================================
# Builder — regenerate the prebuilt coefficient table from raw CFD xlsx
# =====================================================================

def _load_points(air_xlsx: Path) -> pd.DataFrame:
    rows = []
    xl = pd.ExcelFile(WATER_XLSX, engine="openpyxl")
    for sh in xl.sheet_names:
        df = xl.parse(sh).dropna(subset=["p0_Pa", "p3_Pa", "Um_m_s"])
        for gid in sorted(df.geometry_id.unique()):
            s = df[df.geometry_id == gid]
            tp = "Diamond" if s.lattice.iloc[0] == "D" else "Gyroid"
            L = round(float(s.cell_size_mm.iloc[0]))
            t = round(float(s.wall_thickness_mm.iloc[0]) / 10.0, 1)
            for _, r in s.iterrows():
                rows.append((tp, L, t, "water", r.Um_m_s, r.rho_kg_m3,
                             r.mu_Pa_s, r.Re,
                             (r.p0_Pa - r.p3_Pa) / r.core_length_m))
    ac = pd.ExcelFile(air_xlsx, engine="openpyxl").parse("All_Cases_Combined")
    ac = ac[ac.excluded_from_fit == 0]
    for _, r in ac.iterrows():
        t = r.wall_param / 10.0 if r.wall_param >= 3 else r.wall_param
        rows.append((r.structure, round(r.L_cell_mm), round(t, 1), "air",
                     r.v_ref_excel_m_s, r.rho_ref, r.mu_ref, r.Re,
                     r.dP_core_Pa / (r.L_core_report_mm * 1e-3)))
    return pd.DataFrame(rows, columns=["tp", "L", "t", "fluid",
                                       "u", "rho", "mu", "Re", "dpdl"])


def _fit_geom(d: pd.DataFrame, m: float | None):
    """Relative-weighted D-F fit on point rows; m fixed or free."""
    from scipy.optimize import least_squares
    u, rho, mu, Re, y = (d.u.values, d.rho.values, d.mu.values,
                         d.Re.values, d.dpdl.values)
    A = np.column_stack([mu * u, rho * u ** 2])
    w = 1.0 / y
    c, *_ = np.linalg.lstsq(A * w[:, None], y * w, rcond=None)
    p0 = [np.log(1.0 / c[0]) if c[0] > 0 else np.log(1e-8),
          np.log(max(c[1], 1.0))]
    if m is None:
        def f(p):
            K, B, mm = np.exp(p[0]), np.exp(p[1]), p[2]
            return (mu * u / K + rho * B * (Re / 1000.) ** (-mm) * u**2 - y) / y
        r = least_squares(f, p0 + [0.1], method="lm", max_nfev=8000)
        return np.exp(r.x[0]), np.exp(r.x[1]), float(r.x[2])
    def f(p):
        K, B = np.exp(p)
        return (mu * u / K + rho * B * (Re / 1000.) ** (-m) * u**2 - y) / y
    r = least_squares(f, p0, method="lm", max_nfev=8000)
    return np.exp(r.x[0]), np.exp(r.x[1]), float(m)


def build_table(air_xlsx: Path = AIR_XLSX_DEFAULT) -> pd.DataFrame:
    """Full pipeline: pooled m per lattice -> per-geometry (K,B) -> fluid-avg."""
    if not Path(air_xlsx).exists():
        raise FileNotFoundError(
            f"air smooth-CFD source XLSX not found: {air_xlsx} — this "
            "REBUILD-ONLY asset was never migrated off the old dev box (not "
            "in the SJTU-TPMSHX-data repo), so the air smooth basis cannot "
            "be re-fit on this machine. Normal inference reads the committed "
            "_prebuilt/smooth_df_coeffs.csv and never hits this path. Set "
            "TPMSHX_AIR_CFD_XLSX when the asset lands.")
    D = _load_points(air_xlsx)
    mfits: dict[str, list] = {"Diamond": [], "Gyroid": []}
    for (tp, L, t, fl), d in D.groupby(["tp", "L", "t", "fluid"]):
        if len(d) >= 8:
            mfits[tp].append(_fit_geom(d, None)[2])
    m_lat = {tp: float(np.median(v)) for tp, v in mfits.items()}
    recs: dict[tuple, list] = {}
    for (tp, L, t, fl), d in D.groupby(["tp", "L", "t", "fluid"]):
        if len(d) < 6:
            continue
        K, B, _ = _fit_geom(d, m_lat[tp])
        recs.setdefault((tp, L, t), []).append((np.log10(K), np.log10(B)))
    out = []
    for (tp, L, t), v in recs.items():
        ef, Dh = _geom(tp, L, t)
        out.append((tp, L, t, ef, Dh,
                    float(np.mean([x[0] for x in v])),
                    float(np.mean([x[1] for x in v])),
                    m_lat[tp], len(v)))
    return pd.DataFrame(out, columns=["tp", "L", "t", "ef", "Dh",
                                      "logK", "logB", "m_lat", "n_fluids"])


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    air = AIR_XLSX_DEFAULT
    if "--air-xlsx" in sys.argv:
        air = Path(sys.argv[sys.argv.index("--air-xlsx") + 1])
    tab = build_table(air)
    PREBUILT_CSV.parent.mkdir(exist_ok=True)
    tab.to_csv(PREBUILT_CSV, index=False)
    print(f"wrote {PREBUILT_CSV}  ({len(tab)} geometries)")
    print(tab.groupby('tp').agg(n=('L', 'size'), m=('m_lat', 'first')))
    mdl = SmoothDF()
    K, B = mdl.predict_K_B("Gyroid", 7.0, 0.6)
    print(f"sanity G7/t0.6: K={K:.3e}  B={B:.1f}  cF(Re=2000)="
          f"{mdl.predict_cF('Gyroid', 7.0, 0.6, 2000):.1f}")
