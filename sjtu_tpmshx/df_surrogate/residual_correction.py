"""residual_correction.py — D-F closure residual learning correction.

Method:
    1. For each training CFD point (TPMS, L, t, Re, dP_actual), compute
       in-sample baseline prediction dP_pred via SurrogateV3 + 1D compressible
       D-F formula.
    2. Compute relative residual r = (dP_pred - dP_actual) / dP_actual.
    3. Fit smooth g(log_Re, eps_f) using RBF (regularised) per TPMS type.
    4. At inference: dP_corrected = dP_baseline * (1 + g(log_Re, eps_f))_clamped.

Rationale:
    `plot_residual_vs_re.png` shows clear U-shape in residuals: ConstDF-v1
    fits middle-Re band (1e3–3e3) optimally but under-fits low-Re tail
    (Re<1e3, +30~50% residual) and high-Re tail (Re>3e3, ±20%). A smooth
    correction layer captures this U-shape without modifying K, c_F.

Independence from prior dead-ends (`feedback_surrogate_exploration`):
    - 6 prior failures changed K, c_F formulas. This adds an orthogonal
      multiplicative correction to dP — the underlying (K, c_F) untouched.
    - Smoothing=>1 prevents overfitting to in-sample noise.

Public API:
    get_corrector(tpms_type) -> ResidualCorrector  (cached singleton)
    ResidualCorrector.correction(Re, eps_f) -> float in [-0.6, +0.6] clamp
    predict_dP_compressible_corrected(...) -> dP [Pa] with correction applied

Usage:
    >>> from sjtu_tpmshx.df_surrogate.residual_correction import (
    ...     predict_dP_compressible_corrected,
    ... )
    >>> dP = predict_dP_compressible_corrected(
    ...     'Gyroid', 7.0, 0.6, 0.368, G=63.05, T=370.7,
    ...     P_in=304746, mu=2.16e-5, L=0.231)
"""
from __future__ import annotations

import sys
from math import sqrt

import numpy as np

from scipy.interpolate import RBFInterpolator

from sjtu_tpmshx.models.tpms_props import geometry as tpms_geometry  # noqa: E402
from sjtu_tpmshx.logutil import get_logger  # noqa: E402

_log = get_logger(__name__)

R_AIR = 287.05
_KS = 16.0

# Clamp for safety: correction g in [-0.6, +0.6] → dP_corrected in [0.4, 1.6] × dP_baseline
# Empirically the in-sample residual U-shape is bounded by ±50%.
_G_CLAMP = 0.6

# Smoothing for RBF: trades fit quality vs over-fit. Higher = smoother.
# 1.0 picked empirically — yields visibly smooth fit without flattening U-shape.
_RBF_SMOOTHING = 1.0


# ============================================================
# Residual corrector
# ============================================================

class ResidualCorrector:
    """Smooth dP residual correction via RBF on (log_Re, eps_f).

    Parameters
    ----------
    tpms : 'Diamond' or 'Gyroid'
    smoothing : RBF smoothing parameter (default 1.0)
    g_clamp : maximum |g| (default 0.6)

    The corrector is built once at construction (loads SurrogateV3 + computes
    in-sample residuals + fits RBF). Use `get_corrector(tpms)` for cached
    access in solver loops.
    """

    def __init__(self, tpms: str = "Gyroid",
                 smoothing: float = _RBF_SMOOTHING,
                 g_clamp: float = _G_CLAMP):
        self.tpms = tpms
        self._smoothing = float(smoothing)
        self._g_clamp = float(g_clamp)
        self._build()

    def _build(self):
        """Build correction model from in-sample SurrogateV3 residuals."""
        from .surrogate_v3 import SurrogateV3

        sv3 = SurrogateV3(tpms=self.tpms)
        # Use SV3's internal corrected training rows
        rows = sv3.rows_df.copy()
        # rows columns: L_mm, t_mm, eps_f, G, mu, T, P_in, dP, L_ch

        # For each row: compute baseline dP_pred via SurrogateV3.predict + 1D compressible
        log_Re_list = []
        eps_f_list = []
        residual_list = []
        for _, row in rows.iterrows():
            L_mm = float(row["L_mm"])
            t_mm = float(row["t_mm"])
            eps_f = float(row["eps_f"])
            G = float(row["G"])
            T = float(row["T"])
            P_in = float(row["P_in"])
            mu = float(row["mu"])
            L_ch = float(row["L_ch"])
            dP_actual = float(row["dP"])

            # Geometry for D_h
            geom = tpms_geometry(self.tpms, L_mm, t_mm, _KS)
            D_h = float(geom["D_h"])
            rho_in = P_in / (R_AIR * T)
            u_in = G / rho_in
            Re = rho_in * u_in * D_h / mu

            # Baseline prediction
            K, c_F = sv3.predict(L_mm, t_mm, eps_f)
            C = mu * G / K + c_F * G * G
            P_out_sq = P_in ** 2 - 2.0 * R_AIR * T * C * L_ch
            if P_out_sq <= 0:
                continue  # numerical edge case, skip
            dP_pred = P_in - sqrt(P_out_sq)

            if dP_actual <= 0 or dP_pred <= 0:
                continue
            # Define correction g s.t. dP_corrected = dP_pred * (1 + g) ≈ dP_actual
            # → g = (dP_actual - dP_pred) / dP_pred
            g_target = (dP_actual - dP_pred) / dP_pred
            log_Re_list.append(np.log10(Re))
            eps_f_list.append(eps_f)
            residual_list.append(g_target)

        log_Re = np.asarray(log_Re_list, dtype=np.float64)
        eps_f = np.asarray(eps_f_list, dtype=np.float64)
        r = np.asarray(residual_list, dtype=np.float64)

        if len(r) < 10:
            raise RuntimeError(
                f"Too few residual points ({len(r)}) — refusing to fit. "
                "Check SurrogateV3 + load_data integrity.")

        # Fit RBF on (log_Re, eps_f) with smoothing for stability
        X = np.column_stack([log_Re, eps_f])
        self._rbf = RBFInterpolator(
            X, r,
            kernel="thin_plate_spline",
            smoothing=self._smoothing)
        # Stash diagnostics
        self._n_train = len(r)
        self._log_Re_min = float(log_Re.min())
        self._log_Re_max = float(log_Re.max())
        self._eps_f_min = float(eps_f.min())
        self._eps_f_max = float(eps_f.max())
        self._r_in_sample = r
        self._log_Re_in_sample = log_Re
        self._eps_f_in_sample = eps_f

    def correction(self, Re: float, eps_f: float) -> float:
        """Return multiplicative correction g s.t. dP_corrected = dP * (1 + g).

        Clamped to ±g_clamp. Outside training (Re, eps_f) range, g still
        evaluated but capped — extrapolation is bounded.
        """
        log_Re = float(np.log10(max(float(Re), 1.0)))
        x = np.atleast_2d([log_Re, float(eps_f)])
        g = float(self._rbf(x)[0])
        if not np.isfinite(g):
            return 0.0
        return float(np.clip(g, -self._g_clamp, self._g_clamp))

    def summary(self) -> dict:
        return dict(
            tpms=self.tpms,
            n_train=self._n_train,
            log_Re_range=(self._log_Re_min, self._log_Re_max),
            eps_f_range=(self._eps_f_min, self._eps_f_max),
            r_mean=float(self._r_in_sample.mean()),
            r_std=float(self._r_in_sample.std()),
            r_max_abs=float(np.max(np.abs(self._r_in_sample))),
            g_clamp=self._g_clamp,
        )


# ============================================================
# Module-level cache
# ============================================================

_CORRECTOR_CACHE: dict[str, ResidualCorrector] = {}


def get_corrector(tpms_type: str) -> ResidualCorrector:
    """Return cached ResidualCorrector for the given TPMS type."""
    if tpms_type not in _CORRECTOR_CACHE:
        _CORRECTOR_CACHE[tpms_type] = ResidualCorrector(tpms=tpms_type)
    return _CORRECTOR_CACHE[tpms_type]


def clear_cache() -> None:
    """Clear cached correctors (e.g., after parameter changes during testing)."""
    _CORRECTOR_CACHE.clear()


# ============================================================
# Public predict API with correction
# ============================================================

def predict_dP_compressible_corrected(tpms_type: str, L_mm: float, t_mm: float,
                                       eps_f: float, G: float, T: float,
                                       P_in: float, mu: float,
                                       L: float, strict: bool = False) -> float:
    """1D compressible D-F dP with residual correction.

    Same signature/contract as `predict.predict_dP_compressible`
    (incl. the Codex #6 `strict` flag). Returns dP [Pa].

    strict=False (default) → legacy P_in rescue on infeasible
        (P_out²≤0), keeps any existing caller untouched.
    strict=True → NaN on infeasible so callers can detect/exclude/count.
    """
    from .predict import predict_K_cF

    # FIX (2026-06-24 audit): build the baseline with the RBF backend to match
    # the corrector, which is fit as g=(actual-pred_rbf)/pred_rbf. Without method=
    # 'rbf' this defaulted to gamma_df (production default since 2026-06-12) and
    # multiplied an rbf-fit residual onto a gamma_df baseline — a backend mismatch
    # that corrupts rather than corrects. This function's whole purpose is the
    # rbf residual-learning prediction, so the baseline must be rbf.
    K, c_F = predict_K_cF(tpms_type, L_mm, t_mm, eps_f, method='rbf')
    C = mu * G / K + c_F * G * G
    P_out_sq = P_in ** 2 - 2.0 * R_AIR * T * C * L
    if P_out_sq <= 0:
        # Codex 3rd-pass P2a: was unconditional `return P_in` — symmetric
        # with predict_dP_compressible now.
        return float('nan') if strict else float(P_in)
    dP_baseline = float(P_in - sqrt(P_out_sq))

    # Compute Re for correction lookup
    geom = tpms_geometry(tpms_type, L_mm, t_mm, _KS)
    D_h = float(geom["D_h"])
    rho_in = P_in / (R_AIR * T)
    u_in = G / rho_in
    Re = rho_in * u_in * D_h / mu

    corr = get_corrector(tpms_type)
    g = corr.correction(Re, eps_f)
    dP_corrected = dP_baseline * (1.0 + g)
    return max(dP_corrected, 0.0)


# ============================================================
# Self-test
# ============================================================

def _self_test():
    print("=" * 70)
    print("ResidualCorrector self-test")
    print("=" * 70)

    for tpms in ("Diamond", "Gyroid"):
        print(f"\n--- {tpms} ---")
        try:
            corr = ResidualCorrector(tpms=tpms)
            s = corr.summary()
            for k, v in s.items():
                print(f"  {k}: {v}")

            # Sample queries
            print("\n  Sample corrections:")
            for Re in [500, 2000, 8000]:
                for eps_f in [0.30, 0.40]:
                    g = corr.correction(Re, eps_f)
                    print(f"    Re={Re:5d} eps_f={eps_f:.2f}: g={g:+.4f}")
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()

    # Test predict_dP_compressible_corrected
    print("\n--- predict_dP_compressible_corrected (Gyroid, 7×0.6, Shanghai-ish) ---")
    try:
        dP = predict_dP_compressible_corrected(
            "Gyroid", 7.0, 0.6, 0.368,
            G=63.05, T=370.7, P_in=304746, mu=2.16e-5, L=0.231)
        from .predict import predict_dP_compressible
        dP_baseline = predict_dP_compressible(
            "Gyroid", 7.0, 0.6, 0.368,
            G=63.05, T=370.7, P_in=304746, mu=2.16e-5, L=0.231)
        print(f"  baseline: {dP_baseline:.1f} Pa")
        print(f"  corrected: {dP:.1f} Pa")
        print(f"  ratio: {dP / max(dP_baseline, 1.0):.4f}")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    _self_test()
