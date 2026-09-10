"""
surrogate_v3.py — Production surrogate for Darcy-Forchheimer coefficients.

Model:
    1D compressible isothermal D-F equation:
        P_out² = P_in² − 2·R·T·(μG/K + c_F·G²)·L

    Geometry → (K, c_F) regressor — method="rbf" (opt-in via
        TPMSHX_DF_METHOD=rbf; gamma_df is the default since 2026-06-12):
        RBF cubic s=0.1 on (L_mm, t_mm, eps_f) + K clamp 1e-8.
        Validated end-to-end: Shanghai 3D Nz=3 dP RMSRE 7.19% / Q 3.22%.

    method="plhub_gp" (opt-in, 2026-06-10): Huber-robust power-law trend
        log10 y = a + b·log10(L) + c·t  + GP Matern(ν=2.5) residual on
        (L, t) + log-clip ±0.1 dex; no K clamp. Wins the training-domain
        metrics by a wide margin (LOO dP MAPE G 17.5/D 11.5 vs RBF
        24.7/32.1; leave-one-L-out bounded ~240% vs RBF 2000-5800%
        divergence) — measured in the historical model-selection study.
        ⚠ REJECTED as production default by end-to-end evidence: its
        robust trend discounts the L6 c_F hump, but the Shanghai 3D
        pipeline measurement (2026-06-10, Nz=3) gives dP RMSRE 62.79%
        (systematic −27..−69% under-prediction, 16/16 cases; CSV
        validation/shanghai_3d_baselineplhub_switch.csv) vs 7.19% with
        the RBF — i.e. the Shanghai experiment sides with the high-c_F
        branch (L6 hump physics extends toward L=7), not the smooth
        trend. Keep for training-domain studies and as the L6-question
        counter-hypothesis.

Velocity / mass-flux convention:
    G = m_dot / A_void (interstitial mass flux), i.e. A_void already absorbs
    the eps_f factor. Consequently the fitted K and c_F are *effective
    interstitial* coefficients — not canonical Darcy/Forchheimer values.
    Downstream consumers (simple_solver.py) use the same convention; do not
    mix with superficial-form equations from textbooks.
    (Verified against the raw Excel columns 2026-06-10: col6 A = eps_f·L²
    per cell, col13 v = m/(ρ·20·A6) = interstitial velocity of the 20-cell
    frontal specimen, col3 Re = ρ·v13·D_h/μ. See the G note in _build.)

Calibration:
    1. Compressible WLS on raw Pressureloss_TPMS (col 43) + G (col 48):
       (P_in² - P_out²) / (2·R·T·L_ch) = μG/K + c_F·G²
    2. Multiply by boundary effect coefficient alpha:
       c_F_final = alpha × c_F_raw
       K_final = K_raw / alpha
    3. L=8 geometries: Re < 1600 excluded (transition regime)

Usage:
    >>> from sjtu_tpmshx.df_surrogate.surrogate_v3 import SurrogateV3
    >>> model = SurrogateV3()
    >>> K, c_F = model.predict(L_mm=7.0, t_mm=0.6)
    >>> dP = model.predict_dP(K, c_F, G=63.05, T=370.7, P_in=304746, mu=2.16e-5, L=0.182)
"""
from __future__ import annotations

import sys
import warnings
from math import isfinite, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent

# Make sjtu_tpmshx/ importable as a search root so `from solvers.tpms_calc`
# below resolves regardless of how the app was launched (python main.py from
# sjtu_tpmshx/, python -m sjtu_tpmshx.main from parent, or packaged entry).
from scipy.interpolate import RBFInterpolator
from sjtu_tpmshx.models.tpms_props import geometry as tpms_geometry, air_viscosity, P_atm
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

R_AIR = 287.05
K_S_CELLS = 10
P_ATM = P_atm
_KS = 16.0
K_MIN = 1e-8  # TEMPORARY: lowered from 1e-7 to let L>=5 use real K. Revisit later.

XLSX = _PROJECT / "data" / "raw_data" / "试验记录表_整理版.xlsx"

# Pre-built calibrated coefficients (derived, NOT raw experiment data). The
# raw training Excel is gitignored (data/ + *.xlsx). To let CI and any clone
# without the proprietary data run the surrogate-dependent paths, the per-
# geometry calibrated (K, c_F) — the model output, ~10-15 rows — is committed
# as CSV here and the RBF is rebuilt from it when the Excel is absent. The
# Excel path stays authoritative when the data is present; regenerate the CSVs
# with `python -m df_surrogate.build_prebuilt_surrogate` if the surrogate
# changes.
_PREBUILT_DIR = _PROJECT_ROOT / "df_surrogate" / "_prebuilt"


def _prebuilt_csv(tpms: str) -> Path:
    return _PREBUILT_DIR / f"{tpms}_surrogate_ref.csv"


_FEATURES_ALL = ("L_mm", "t_mm", "eps_f")
_METHODS = ("plhub_gp", "rbf")


class SurrogateV3:
    """Production surrogate for the geometry → (K, c_F) map.

    method="rbf" (default): RBF cubic s=0.1 + K clamp 1e-8 — production
        model, bit-identical to the historical behavior with default
        kwargs; Shanghai 3D end-to-end 7.19% dP / 3.22% Q.
    method="plhub_gp" (opt-in): Huber power-law trend + GP Matern
        residual + log-clip; no K clamp (K_min resolves to 1e-12).
        Training-domain winner (LOO/LOLO) but rejected as default —
        Shanghai 3D dP RMSRE 62.79% (see module docstring).

    RBF-only experiment kwargs retained from the feature-ablation study:

    standardize : z-score the RBF features before interpolation (tested
        2026-06-10: degrades LOO badly — the unscaled L_mm-dominated
        metric is an effective prior; keep False).
    features : which canonical features feed the RBF. Queries always
        pass the canonical 3-column (L_mm, t_mm, eps_f) layout.
    """

    def __init__(self, tpms: str = "Gyroid", K_min: float | None = None, *,
                 method: str = "rbf",
                 clip_margin: float = 0.1,
                 standardize: bool = False,
                 features: tuple[str, ...] = _FEATURES_ALL,
                 training_workbook: Path | None = None,
                 calibration_csv: Path | None = None):
        if training_workbook is not None and calibration_csv is not None:
            raise ValueError('choose training_workbook or calibration_csv, not both')
        self._training_workbook = XLSX if training_workbook is None else Path(training_workbook)
        if training_workbook is not None and not self._training_workbook.is_file():
            raise FileNotFoundError(self._training_workbook)
        if method not in _METHODS:
            raise ValueError(f"unknown method {method!r}; valid: {_METHODS}")
        self.tpms = tpms
        self.method = method
        self.clip_margin = float(clip_margin)
        # Legacy RBF keeps the historical 1e-8 clamp; plhub_gp removes it
        # (the clamp floored the true K ≈ 1e-9 of L4/L5 geometries and was
        # the largest single LOO error source).
        self.K_min = K_min if K_min is not None else (
            K_MIN if method == "rbf" else 1e-12)
        self.standardize = bool(standardize)
        self.features = tuple(features)
        unknown = set(self.features) - set(_FEATURES_ALL)
        if unknown:
            raise ValueError(f"unknown RBF features: {sorted(unknown)}; "
                             f"valid: {_FEATURES_ALL}")
        # W6 (2026-07-07): the source choice is LOGGED — the two paths can
        # silently diverge if the local Excel is edited without regenerating
        # the committed CSV, and the production GammaDF anchor derives from
        # this instance. test_df_source_parity pins their equivalence.
        # NOTE: keep these log lines ASCII-only. The Excel path contains
        # Chinese characters; on a GBK-console Windows a subprocess writes
        # them as GBK bytes while pytest reads its capture stream as UTF-8 —
        # one such line poisons the capture and EVERY later test teardown
        # dies with UnicodeDecodeError (found the hard way, 2026-07-07).
        if calibration_csv is not None:
            self._source = 'prebuilt_csv'
            _log.info('[SurrogateV3 %s/%s] using explicit calibrated CSV', self.tpms, self.method)
            self._build_from_prebuilt(Path(calibration_csv))
        elif self._training_workbook.exists():
            self._source = 'xlsx'
            _log.info("[SurrogateV3 %s/%s] calibrating from local experiment"
                      " Excel (data/raw_data)", self.tpms, self.method)
            self._build()                 # authoritative: calibrate from Excel
        else:
            self._source = 'prebuilt_csv'
            _log.warning(
                "[SurrogateV3 %s/%s]\n"
                "=============== CALIBRATION SOURCE FALLBACK ===============\n"
                "local experiment Excel NOT FOUND (data/raw_data/) - using\n"
                "the committed prebuilt CSV calibration instead. Numbers can\n"
                "differ from the authoritative Excel-calibrated ones with no\n"
                "further notice (the production GammaDF anchor derives from\n"
                "this instance). Fix: copy raw_data/ from the SJTU-TPMSHX-data\n"
                "repo at the commit recorded in data-revision.txt (repo root).\n"
                "===========================================================",
                self.tpms, self.method)
            self._build_from_prebuilt()   # fallback: committed calibrated CSV

    def _build(self) -> None:
        """Load data, calibrate, build RBF interpolators."""
        # Load boundary effect coefficients
        alpha_df = pd.read_excel(
            str(self._training_workbook), engine="openpyxl",
            sheet_name="边界效应系数", header=None)
        alpha_map = {str(r.iloc[0]): float(r.iloc[1])
                     for _, r in alpha_df.iterrows()}

        # Load training data
        prefix = self.tpms[0]  # 'G' for Gyroid, 'D' for Diamond
        sheet = f"{self.tpms}_汇总"
        raw = pd.read_excel(
            str(self._training_workbook), engine="openpyxl",
            sheet_name=sheet, header=None, skiprows=1)

        L_col = pd.to_numeric(raw.iloc[:, 1], errors="coerce")
        mask = L_col.notna()
        L_mm = L_col[mask].astype(float).values
        t_mm = pd.to_numeric(raw.iloc[:, 2], errors="coerce")[mask].astype(float).values
        T_C = pd.to_numeric(raw.iloc[:, 7], errors="coerce")[mask].astype(float).values
        # 2026-05-28 G convention fix: previous code read col 48 ("G
        # 千克每平方米每秒") which is exactly 20× ρ·v — the total m_dot over
        # a SINGLE cell's void area (specimen frontal = 20 cells), i.e. a
        # bookkeeping artifact, not a physical flux. Reconstruct G from
        # col 12 (density) × col 13 (velocity); the resulting fit ranges
        # match the documented c_F = 186–2140 for trained geometries.
        # 2026-06-10 provenance audit: col6 A = eps_f·L² (one cell's void
        # area), col13 v = m/(ρ·20·A6) → interstitial velocity, col3
        # Re = ρ·v13·D_h/μ. So G = ρ·v13 is the INTERSTITIAL mass flux —
        # consistent with the module-docstring convention and with
        # simple_solver's interstitial velocities. (An earlier version of
        # this comment claimed "superficial m/A_total" — wrong label,
        # right fix. Caveat: L=4 rows show v13 vs m/(ρ·20·A6) drift up to
        # ~16%; all other geometries agree to <0.5%.)
        rho_col = pd.to_numeric(raw.iloc[:, 12], errors="coerce")[mask].astype(float).values
        v_col = pd.to_numeric(raw.iloc[:, 13], errors="coerce")[mask].astype(float).values
        G = rho_col * v_col
        dP_raw = pd.to_numeric(raw.iloc[:, 43], errors="coerce")[mask].astype(float).values
        Re = pd.to_numeric(raw.iloc[:, 3], errors="coerce")[mask].astype(float).values

        valid = ~(np.isnan(G) | np.isnan(dP_raw) | np.isnan(T_C) | np.isnan(Re))
        L_mm, t_mm, T_C, G, dP_raw, Re = (
            a[valid] for a in (L_mm, t_mm, T_C, G, dP_raw, Re))
        T_K = T_C + 273.15
        mu = np.array([air_viscosity(T) for T in T_K])

        # L=8: exclude Re < 1600
        keep = ~((L_mm == 8) & (Re < 1600))
        L_mm, t_mm, G, dP_raw, T_K, mu = (
            a[keep] for a in (L_mm, t_mm, G, dP_raw, T_K, mu))

        # Per-geometry calibration: fit on raw dP, then × alpha
        ref_list = []
        self._rows_list = []
        self._geom_cache = {}

        for L_val in sorted(np.unique(L_mm)):
            for t_val in sorted(np.unique(t_mm[L_mm == L_val])):
                sel = (L_mm == L_val) & (t_mm == t_val)
                if sel.sum() < 3:
                    continue

                key = f"{prefix}_{int(L_val)}_{int(t_val * 10):02d}"
                alpha = alpha_map.get(key, 1.0)
                g = tpms_geometry(self.tpms, float(L_val), float(t_val), _KS)
                self._geom_cache[(float(L_val), float(t_val))] = g
                L_ch = K_S_CELLS * L_val * 1e-3

                gs = G[sel]; mu_s = mu[sel]; T_s = T_K[sel]; dp_s = dP_raw[sel]
                P_in = P_ATM + dp_s
                lhs = (P_in ** 2 - P_ATM ** 2) / (2 * R_AIR * T_s * L_ch)
                X = np.column_stack([mu_s * gs, gs ** 2])
                w = 1.0 / lhs
                coef, *_ = np.linalg.lstsq(X * w[:, None], lhs * w, rcond=None)
                inv_K_raw, cF_raw = coef

                cF_corr = alpha * cF_raw
                K_corr = ((1.0 / inv_K_raw) / alpha
                          if inv_K_raw > 0 else None)

                ref_list.append(dict(
                    L_mm=float(L_val), t_mm=float(t_val),
                    eps_f=g["epsilon"] / 2, r_h_m=g["D_h"] / 2,
                    K=K_corr, c_F=max(cF_corr, 1.0)))

                # Store corrected training rows
                for i in np.where(sel)[0]:
                    dp_corr = dP_raw[i] * alpha
                    self._rows_list.append(dict(
                        L_mm=L_mm[i], t_mm=t_mm[i],
                        eps_f=g["epsilon"] / 2,
                        G=G[i], mu=mu[i], T=T_K[i],
                        P_in=P_ATM + dp_corr, dP=dp_corr,
                        L_ch=K_S_CELLS * L_mm[i] * 1e-3))

        self.ref = pd.DataFrame(ref_list)
        self.rows_df = pd.DataFrame(self._rows_list)

        # Handle K=None (unconstrained) via power-law extrapolation
        K_arr = self.ref["K"].to_numpy(dtype=float)
        D_h_arr = np.array([2 * r.r_h_m for _, r in self.ref.iterrows()])
        has_K = ~np.isnan(K_arr)
        if not has_K.all():
            Xpw = np.column_stack([np.ones(has_K.sum()),
                                    np.log10(D_h_arr[has_K])])
            ypw = np.log10(K_arr[has_K])
            cpw, *_ = np.linalg.lstsq(Xpw, ypw, rcond=None)
            for i in range(len(self.ref)):
                if not has_K[i]:
                    K_arr[i] = 10.0 ** (cpw[0] + cpw[1] * np.log10(D_h_arr[i]))

        # Build RBF interpolators from the final calibrated fit points.
        X_feat = self.ref[["L_mm", "t_mm", "eps_f"]].to_numpy(dtype=float)
        cF_arr = self.ref["c_F"].to_numpy(dtype=float)
        self._fit_rbf(X_feat, K_arr, cF_arr)

    def _fit_rbf(self, X_feat: np.ndarray, K_arr: np.ndarray,
                 cF_arr: np.ndarray) -> None:
        """Build the (K, c_F) RBF interpolators from calibrated fit points.

        Shared by the Excel-calibration path and the pre-built CSV path so the
        two produce a bit-identical model from identical inputs. `_fit_*` are
        retained so the calibrated points can be serialized via dump_prebuilt.
        """
        self._fit_X = np.ascontiguousarray(X_feat, dtype=float)
        self._fit_K = np.ascontiguousarray(K_arr, dtype=float)
        self._fit_cF = np.ascontiguousarray(cF_arr, dtype=float)
        self._rbf_K, self._rbf_cF = self._make_predictors(
            self._fit_X, np.log10(self._fit_K), np.log10(self._fit_cF))

    def _make_predictors(self, X3, logK, logcF):
        """Build (fK, fC): callables mapping canonical (N,3) [L_mm, t_mm,
        eps_f] queries to log10(K) / log10(c_F), honoring self.method.
        Single construction point shared by the full-data fit and the
        per-fold refits in eval_loo. (Attribute names _rbf_K/_rbf_cF are
        kept for the predict_K_cF_vec batch path regardless of method.)
        """
        if self.method == "rbf":
            return (self._make_rbf(X3, logK), self._make_rbf(X3, logcF))
        return (self._fit_plhub_one(X3, logK),
                self._fit_plhub_one(X3, logcF))

    def _fit_plhub_one(self, X3, y):
        """Huber power-law trend + GP Matern residual, one target.

        Trend: log10 y = a + b*log10(L) + c*t, Huber loss (eps=1.35) so
        the L6 c_F hump cannot bend the extrapolation trend. Residual:
        GP Matern(nu=2.5) on (L, t), anisotropic ML-II length scales +
        WhiteKernel — restores per-geometry detail near data, decays to
        zero away from it (prediction reverts to the robust trend).
        Output log-clipped to the training range ± clip_margin dex.
        Selected by LOO + leave-one-L-out comparison.
        """
        from sklearn.gaussian_process import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import (
            ConstantKernel, Matern, WhiteKernel)
        from sklearn.linear_model import HuberRegressor

        X3 = np.asarray(X3, dtype=float)
        L, t = X3[:, 0], X3[:, 1]
        A = np.column_stack([np.ones(len(L)), np.log10(L), t])
        hub = HuberRegressor(epsilon=1.35, alpha=0.0,
                             fit_intercept=False, max_iter=500)
        hub.fit(A, y)
        coef = hub.coef_.copy()
        resid = y - A @ coef
        kern = (ConstantKernel(0.1, (1e-4, 1e2))
                * Matern(length_scale=[2.0, 0.2],
                         length_scale_bounds=(1e-2, 1e2), nu=2.5)
                + WhiteKernel(1e-4, (1e-8, 1e-1)))
        gp = GaussianProcessRegressor(kernel=kern, normalize_y=False,
                                      n_restarts_optimizer=5,
                                      random_state=0)
        gp.fit(np.column_stack([L, t]), resid)
        lo = float(y.min()) - self.clip_margin
        hi = float(y.max()) + self.clip_margin

        def predict_log10(X):
            X = np.atleast_2d(np.asarray(X, dtype=float))
            Lq, tq = X[:, 0], X[:, 1]
            Aq = np.column_stack([np.ones(len(Lq)), np.log10(Lq), tq])
            out = Aq @ coef + gp.predict(np.column_stack([Lq, tq]))
            return np.clip(out, lo, hi)

        return predict_log10

    def _make_rbf(self, X3: np.ndarray, y: np.ndarray):
        """RBF over canonical (N,3) [L_mm, t_mm, eps_f] feature rows.

        Honors the experiment-only variant config (feature subset and/or
        z-score standardization). Default config returns a bare
        RBFInterpolator on the raw 3-column array — bit-identical to the
        historical model. The variant path wraps the interpolator so every
        caller (predict, predict_K_cF_vec, eval_loo) keeps passing the
        canonical 3-column query layout.
        """
        if not self.standardize and self.features == _FEATURES_ALL:
            return RBFInterpolator(X3, y, kernel="cubic", smoothing=0.1)
        idx = [_FEATURES_ALL.index(f) for f in self.features]
        Xs = np.asarray(X3, dtype=float)[:, idx]
        if self.standardize:
            mu, sd = Xs.mean(axis=0), Xs.std(axis=0)
            sd[sd == 0.0] = 1.0
        else:
            mu = np.zeros(len(idx))
            sd = np.ones(len(idx))
        rbf = RBFInterpolator((Xs - mu) / sd, y,
                              kernel="cubic", smoothing=0.1)
        return lambda X: rbf((np.asarray(X, dtype=float)[:, idx] - mu) / sd)

    def _build_from_prebuilt(self, path: Path | None = None) -> None:
        """Build from the committed calibrated CSV (no raw Excel needed).

        Used when the gitignored training Excel is absent (CI, fresh clones).
        Loads the per-geometry calibrated (K, c_F) and rebuilds the same RBF.
        `rows_df` is left empty — the residual-correction path (opt-in,
        TPMSHX_DF_RESIDUAL_CORR) needs the raw Excel and is unavailable here.
        """
        path = _prebuilt_csv(self.tpms) if path is None else path
        if not path.exists():
            raise FileNotFoundError(
                f"SurrogateV3: no training Excel ({XLSX}) and no pre-built "
                f"calibrated CSV ({path}). Run "
                f"`python -m df_surrogate.build_prebuilt_surrogate` where the "
                f"Excel is available to generate it.")
        df = pd.read_csv(path)
        self.ref = df
        self.rows_df = pd.DataFrame()
        self._geom_cache = {}
        self._fit_rbf(df[["L_mm", "t_mm", "eps_f"]].to_numpy(dtype=float),
                      df["K"].to_numpy(dtype=float),
                      df["c_F"].to_numpy(dtype=float))

    def dump_prebuilt(self, path: Path | None = None) -> Path:
        """Serialize the calibrated fit points (L, t, eps_f, K, c_F) to CSV.

        Full float precision so the CSV-rebuilt RBF is bit-identical to the
        Excel-built one. Writes derived coefficients only, never raw data.
        """
        path = Path(path) if path is not None else _prebuilt_csv(self.tpms)
        path.parent.mkdir(parents=True, exist_ok=True)
        out = pd.DataFrame({
            "L_mm": self._fit_X[:, 0], "t_mm": self._fit_X[:, 1],
            "eps_f": self._fit_X[:, 2], "K": self._fit_K, "c_F": self._fit_cF})
        out.to_csv(path, index=False, float_format="%.17g")
        return path

    def predict(self, L_mm: float, t_mm: float,
                eps_f: float | None = None) -> tuple[float, float]:
        """Predict (K, c_F) for a geometry.

        Parameters
        ----------
        L_mm, t_mm : unit cell size and wall thickness [mm]
        eps_f : single-channel porosity. If None, computed from geometry.

        Returns
        -------
        K : Darcy permeability [m²], clamped to K_min
        c_F : Forchheimer coefficient [1/m]
        """
        if eps_f is None:
            g = tpms_geometry(self.tpms, L_mm, t_mm, _KS)
            eps_f = g["epsilon"] / 2.0

        x = np.array([[L_mm, t_mm, eps_f]])
        K = max(10.0 ** float(self._rbf_K(x)[0]), self.K_min)
        c_F = 10.0 ** float(self._rbf_cF(x)[0])
        return K, c_F

    @staticmethod
    def predict_dP(K: float, c_F: float, G: float, T: float,
                   P_in: float, mu: float, L: float,
                   strict: bool = False) -> float:
        """1D compressible isothermal D-F pressure drop.

        Parameters
        ----------
        K : permeability [m²]
        c_F : Forchheimer coefficient [1/m]
        G : mass flux [kg/(m²·s)]
        T : temperature [K]
        P_in : inlet absolute pressure [Pa]
        mu : dynamic viscosity [Pa·s]
        L : channel length [m]

        Returns
        -------
        dP : pressure drop [Pa]
        """
        C = mu * G / K + c_F * G ** 2
        P_out_sq = P_in ** 2 - 2.0 * R_AIR * T * C * L
        if P_out_sq <= 0:
            # Physically infeasible (choked / over-driven): no real P_out.
            # Codex #6: strict → NaN so callers can detect+exclude+count;
            # default → legacy P_in rescue (optimizer value-path untouched).
            return float('nan') if strict else P_in
        return P_in - sqrt(P_out_sq)

    def summary(self) -> None:
        """Print model summary."""
        _log.info(f"SurrogateV3 ({self.tpms})")
        _log.info(f"  Geometries: {len(self.ref)}")
        _log.info(f"  Training rows: {len(self.rows_df)}")
        _log.info(f"  K_min: {self.K_min:.0e}")
        _log.info("\n  Per-geometry (K, c_F):")
        _log.info(f"  {'L':>3} {'t':>4} {'K':>10} {'c_F':>8}")
        for _, r in self.ref.iterrows():
            K_str = f"{r.K:.3e}" if r.K is not None and not np.isnan(r.K) else "N/A"
            _log.info(f"  {r.L_mm:3.0f} {r.t_mm:4.1f} {K_str:>10} {r.c_F:8.1f}")


# ==================================================================
# Evaluation helpers
# ==================================================================

def eval_shanghai(model: SurrogateV3, L: float = 7.0, t: float = 0.6):
    """Evaluate on Shanghai 16 cases."""
    sh_xlsx = _PROJECT / "data" / "raw_data" / \
              "20260401-上海电气天然气加热器实验工况.xlsx"
    sh = pd.read_excel(str(sh_xlsx), engine="openpyxl",
                       sheet_name="Sheet1", header=None, skiprows=2)
    # Canonical Shanghai params: see configs/shanghai_baseline.json
    # (n_units=36, a_flow_per_unit_m2=1.80565e-5, L_dom_m=0.182). Not loaded
    # here to keep eval_shanghai a zero-dependency standalone helper; if
    # the JSON drifts, this constant must follow.
    A_FLOW = 36 * 18.0565e-6
    # 18.0565 mm² = eps_f(Gyroid,7,0.6)·(7 mm)² — per-unit VOID area, so
    # G = m/A_FLOW below is the interstitial mass flux, matching the
    # training-G convention (verified 2026-06-10).
    L_DOM = 0.182  # Shanghai HX streamwise A length [m]. Was 0.231 (stale —
                   # 182+42+7 historical "total" guess); corrected 2026-05-28.

    K, c_F = model.predict(L, t)
    _log.info(f"K = {K:.4e}, c_F = {c_F:.2f}")

    err_sq = 0.0
    n_valid = 0
    n_invalid = 0
    results = []
    for ci in range(16):
        m = float(sh.iloc[ci, 5])
        T = float(sh.iloc[ci, 28]) + 273.15
        P_in = P_ATM + float(sh.iloc[ci, 30])
        dP_exp = float(sh.iloc[ci, 30]) - float(sh.iloc[ci, 31])
        G = m / A_FLOW
        mu = air_viscosity(T)

        # Codex #6: strict → NaN on infeasible; exclude+count, never
        # fold a rescued P_in into RMSRE.
        dP_pred = model.predict_dP(K, c_F, G, T, P_in, mu, L_DOM,
                                   strict=True)
        if not isfinite(dP_pred):
            n_invalid += 1
            results.append(dict(case=ci + 1, dP_exp=dP_exp,
                                dP_pred=float('nan'), err_pct=float('nan'),
                                pressure_state_valid=False))
            continue
        err = (dP_pred - dP_exp) / dP_exp
        err_sq += err ** 2
        n_valid += 1
        results.append(dict(case=ci + 1, dP_exp=dP_exp,
                            dP_pred=dP_pred, err_pct=err * 100,
                            pressure_state_valid=True))

    rmsre = (sqrt(err_sq / n_valid) * 100) if n_valid else float('nan')
    if n_invalid:
        _log.warning(f"  ⚠ {n_invalid}/16 cases infeasible (P_out²≤0) — "
                     f"excluded from RMSRE (computed over {n_valid} valid)")
    return rmsre, results


def eval_loo(model: SurrogateV3):
    """Leave-one-geometry-out evaluation."""
    ref = model.ref
    rows_df = model.rows_df
    X_feat = ref[["L_mm", "t_mm", "eps_f"]].to_numpy(dtype=float)

    # Rebuild K array for LOO
    K_arr = ref["K"].to_numpy(dtype=float)
    D_h_arr = np.array([2 * r.r_h_m for _, r in ref.iterrows()])
    has_K = ~np.isnan(K_arr)
    if not has_K.all():
        Xpw = np.column_stack([np.ones(has_K.sum()),
                                np.log10(D_h_arr[has_K])])
        ypw = np.log10(K_arr[has_K])
        cpw, *_ = np.linalg.lstsq(Xpw, ypw, rcond=None)
        for i in range(len(ref)):
            if not has_K[i]:
                K_arr[i] = 10.0 ** (cpw[0] + cpw[1] * np.log10(D_h_arr[i]))

    log_K = np.log10(K_arr)
    log_cF = np.log10(ref["c_F"].to_numpy())

    mapes = []
    for idx in range(len(ref)):
        r = ref.iloc[idx]
        mask = np.ones(len(ref), dtype=bool)
        mask[idx] = False

        # Refit through model._make_predictors so per-fold models honor
        # the method (plhub_gp/rbf) and any variant config; the legacy
        # rbf default path is the same direct RBFInterpolator as before.
        rbf_K_i, rbf_cF_i = model._make_predictors(
            X_feat[mask], log_K[mask], log_cF[mask])

        K_p = max(10.0 ** rbf_K_i(X_feat[idx:idx + 1])[0], model.K_min)
        cF_p = 10.0 ** rbf_cF_i(X_feat[idx:idx + 1])[0]

        grp = rows_df[(rows_df["L_mm"] == r.L_mm) &
                       (rows_df["t_mm"] == r.t_mm)]
        Gt = grp["G"].to_numpy()
        Tt = grp["T"].to_numpy()
        mut = grp["mu"].to_numpy()
        Pit = grp["P_in"].to_numpy()
        dPt = grp["dP"].to_numpy()
        Lct = grp["L_ch"].to_numpy()

        C = mut * Gt / K_p + cF_p * Gt ** 2
        Psq = Pit ** 2 - 2 * R_AIR * Tt * C * Lct
        # Codex #6: rows with Psq≤0 are infeasible — exclude them from the
        # LOO MAPE instead of np.maximum(Psq,0)-rescuing into a fake dP.
        _ok = Psq > 0
        if not _ok.any():
            mape = float('nan')
        else:
            dPp = Pit[_ok] - np.sqrt(Psq[_ok])
            mape = float(np.mean(np.abs(dPp - dPt[_ok]) / dPt[_ok]) * 100)
        if not _ok.all():
            _log.warning(f"  ⚠ L={r.L_mm:.0f} t={r.t_mm:.1f}: "
                         f"{int((~_ok).sum())}/{_ok.size} pts infeasible — excluded")
        mapes.append(mape)
        _log.info(f"  L={r.L_mm:.0f} t={r.t_mm:.1f}: "
                  f"K={K_p:.3e} cF={cF_p:.0f} MAPE={mape:.1f}%")

    return float(np.nanmean(mapes))  # Codex #6: skip fully-infeasible geoms


# ==================================================================
# CLI
# ==================================================================

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    warnings.filterwarnings("ignore")

    model = SurrogateV3()
    model.summary()

    # Shanghai
    print("\n=== Shanghai ===")
    K, c_F = model.predict(7.0, 0.6)
    print(f"Prediction: K={K:.4e}, c_F={c_F:.2f}")
    rmsre, results = eval_shanghai(model)
    print(f"\n{'C':>2} {'dP_exp':>9} {'dP_pred':>9} {'err%':>8}")
    print("-" * 35)
    for r in results:
        print(f"{r['case']:2d} {r['dP_exp']:9.0f} {r['dP_pred']:9.0f} "
              f"{r['err_pct']:+8.1f}%")
    print(f"\n  Shanghai RMSRE = {rmsre:.2f}%")

    # LOO
    print("\n=== LOO ===")
    loo_mape = eval_loo(model)
    print(f"\n  Mean LOO MAPE = {loo_mape:.2f}%")

    print("\n=== Final ===")
    print(f"  Shanghai RMSRE = {rmsre:.2f}%")
    print(f"  LOO MAPE = {loo_mape:.2f}%")


if __name__ == "__main__":
    main()
