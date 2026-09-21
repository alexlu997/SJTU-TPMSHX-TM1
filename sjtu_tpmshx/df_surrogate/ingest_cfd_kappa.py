"""ingest_cfd_kappa.py — turn external ANSYS Fluent per-side runs into κ tables.

Reads a Fluent results CSV (one row per design point per side) with columns:

    tpms, L_mm, t_mm, eps_side, eps_sym, K_cfd, cF_cfd

computes the **relative-ratio** correction against the existing symmetric
Darcy-Forchheimer baseline:

    κ_K(r)  = K_cfd  / K_sym ,    κ_cF(r) = cF_cfd / cF_sym ,    r = ε_side/ε_sym

where (K_sym, cF_sym) = ``predict.predict_K_cF(tpms, L, t, ε_sym)``. This
denominator is the current symmetric model prediction, not a paired CFD run;
the ratio can therefore include differences in CFD recipe and model baseline.
For the separate same-recipe CFD self-ratio workflow, use
``sjtu_tpmshx.runs.cfd_asym.asym_postproc_kappa`` instead.

Tables use piecewise linear interpolation on sorted r with flat ends; κ is not
constrained to be monotone. A (1, 1) point is added only when r≈1 is absent;
supplied r≈1 values are retained. The outer ``kappa_asym.kappa_KcF`` caller has
its own symmetric-r identity guard.

``ingest`` registers tables in the calling Python process only. Research code
can then explicitly call ``kappa_asym.kappa_KcF(..., enabled=True)`` in that
process. The tables are not connected to production preparation; neither this
CLI nor ``TPMSHX_ASYM_KAPPA=1`` installs or enables them in a full 3D/GUI solve.

Usage:  python -m sjtu_tpmshx.df_surrogate.ingest_cfd_kappa results.csv
        (or import ingest(path) programmatically)
"""
from __future__ import annotations

import csv
import argparse

import numpy as np

from sjtu_tpmshx.df_surrogate.predict import predict_K_cF
from sjtu_tpmshx.df_surrogate import kappa_asym
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)


def _linear_interp(r_pts, k_pts):
    """Interpolate sorted (r, κ), with flat ends and no monotonicity constraint.

    Add (1, 1) only if r≈1 is absent; retain a supplied near-symmetric value.
    """
    r = list(r_pts)
    k = list(k_pts)
    if not any(abs(rv - 1.0) < 1e-9 for rv in r):
        r.append(1.0)
        k.append(1.0)
    order = np.argsort(r)
    r_s = np.asarray(r, dtype=np.float64)[order]
    k_s = np.asarray(k, dtype=np.float64)[order]
    # de-duplicate identical r (np.interp needs strictly increasing x)
    keep = np.concatenate(([True], np.diff(r_s) > 1e-12))
    r_s, k_s = r_s[keep], k_s[keep]
    return lambda rq: float(np.interp(rq, r_s, k_s))   # flat beyond ends


def ingest(path: str) -> dict:
    """Divide fitted CFD coefficients by the symmetric predictor and register
    interpolation tables in this process. Return {tpms: n_points}."""
    by_tpms: dict = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tpms = row["tpms"].strip()
            L = float(row["L_mm"]); t = float(row["t_mm"])
            eps_side = float(row["eps_side"]); eps_sym = float(row["eps_sym"])
            K_cfd = float(row["K_cfd"]); cF_cfd = float(row["cF_cfd"])
            K_sym, cF_sym = predict_K_cF(tpms, L, t, eps_sym)
            r = eps_side / eps_sym if eps_sym > 0 else 1.0
            kK = K_cfd / K_sym if K_sym > 0 else 1.0
            kcF = cF_cfd / cF_sym if cF_sym > 0 else 1.0
            by_tpms.setdefault(tpms, {"r": [], "kK": [], "kcF": []})
            by_tpms[tpms]["r"].append(r)
            by_tpms[tpms]["kK"].append(kK)
            by_tpms[tpms]["kcF"].append(kcF)

    summary = {}
    for tpms, d in by_tpms.items():
        kK_fn = _linear_interp(d["r"], d["kK"])
        kcF_fn = _linear_interp(d["r"], d["kcF"])
        kappa_asym.set_kappa_table(tpms, kK_fn, kcF_fn)
        summary[tpms] = len(d["r"])
        print(f"[kappa] {tpms}: {len(d['r'])} points, "
              f"r∈[{min(d['r']):.3f},{max(d['r']):.3f}], "
              f"κ_K∈[{min(d['kK']):.3f},{max(d['kK']):.3f}], "
              f"κ_cF∈[{min(d['kcF']):.3f},{max(d['kcF']):.3f}]")
    print(f"[kappa] registered {len(summary)} tpms tables in this process only. "
          "Research callers can explicitly evaluate kappa_KcF(..., enabled=True). "
          "Production preparation does not consume these tables; no calibration was installed.")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results_csv', help='Per-side fitted CFD coefficients (7-column CSV).')
    ingest(parser.parse_args().results_csv)
