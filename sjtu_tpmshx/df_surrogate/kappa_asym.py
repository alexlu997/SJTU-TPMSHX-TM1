"""df_surrogate/kappa_asym.py — per-side asymmetric-porosity κ correction.

Relative-ratio closure for the offset-isosurface (ε_A ≠ ε_B) work:

    X_asym(ε_side) = κ_X(r) · X_sym,   r = ε_side / ε_sym,   X ∈ {K, c_F}

where ``X_sym`` is the existing symmetric Darcy-Forchheimer prediction
(``predict.predict_K_cF`` at ε_sym = ε_total/2) and ``κ_X(r)`` is fitted from
the EXTERNAL ANSYS Fluent per-side runs (populated by
``ingest_cfd_kappa.ingest``). The relative ratio cancels the shared provenance
(turbulence model, mesh, AM-roughness factor) between the asymmetric and
symmetric CFD, so only the *geometry-induced* per-side shift survives.

Three identity guards keep δ=0 (and the uncalibrated state) bit-identical:
  1. env ``TPMSHX_ASYM_KAPPA`` off (default)  → (1.0, 1.0)
  2. no κ table for this tpms_type             → (1.0, 1.0)
  3. r ≈ 1 (ε_side == ε_sym, i.e. δ=0)         → (1.0, 1.0)

κ multiplies the output of ``predict_K_cF``. The fixed geometry baseline
is unchanged at δ=0; production preparation does not apply this research hook.
"""
from __future__ import annotations

import os

# {tpms_type: {'K': callable r->κ_K, 'cF': callable r->κ_cF}}. Filled by
# ingest_cfd_kappa.ingest() once Fluent data is available; empty → identity.
_KAPPA: dict = {}


def _enabled(flag) -> bool:
    """Resolve the on/off gate: explicit arg wins, else env (default off)."""
    if flag is not None:
        return bool(flag)
    return os.environ.get('TPMSHX_ASYM_KAPPA', '0') not in ('', '0', 'false', 'False')


def kappa_KcF(tpms_type: str, eps_side: float, eps_sym: float,
              *, enabled: bool | None = None) -> tuple[float, float]:
    """Return ``(κ_K, κ_cF)`` for one fluid side.

    Returns ``(1.0, 1.0)`` (identity) when disabled, when ε_side == ε_sym
    (δ=0), when ε_sym is non-positive, or when no κ table exists yet for
    ``tpms_type``.
    """
    if (not _enabled(enabled)) or eps_sym <= 0.0 or abs(eps_side - eps_sym) < 1e-12:
        return 1.0, 1.0
    tbl = _KAPPA.get(tpms_type)
    if tbl is None:
        return 1.0, 1.0
    r = eps_side / eps_sym
    return float(tbl['K'](r)), float(tbl['cF'](r))


def set_kappa_table(tpms_type: str, kK_callable, kcF_callable) -> None:
    """Register fitted κ_K(r), κ_cF(r) maps for a tpms_type (called by ingest)."""
    _KAPPA[tpms_type] = {'K': kK_callable, 'cF': kcF_callable}


def has_table(tpms_type: str) -> bool:
    return tpms_type in _KAPPA


def clear() -> None:
    """Drop all κ tables (test isolation)."""
    _KAPPA.clear()
