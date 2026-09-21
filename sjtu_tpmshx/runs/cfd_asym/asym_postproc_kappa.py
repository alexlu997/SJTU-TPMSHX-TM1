"""asym_postproc_kappa.py — Phase-1 asym-porosity CFD post-processing.

Reads the PyFluent results CSV (one row per case × side × Re, with the measured
internal-plane pressures filled in), then in one pass:

  1. DF fit  — per (tpms, split, side) fit the Darcy-Forchheimer law over the Re
               sweep:   dp_core / L_core = (μ/K)·Um + c_F·ρ·Um²
               (linear in [Um, Um²] → least squares → K = μ/a, c_F = b/ρ).
  2. κ self-ratio — per tpms divide by the SYMMETRIC (split_r==1) anchor:
               κ_K(r)  = K(r)  / K(r=1) ,   κ_cF(r) = c_F(r) / c_F(r=1) ,
               r = ε_side / ε_sym (κ-table axis).
     The denominator is the mean of all split_r≈1 fitted rows for that tpms;
     individual symmetric rows need not equal their mean. Supply paired CFD
     from the same recipe and geometry scale to study the relative effect;
     common numerical/model biases are not guaranteed to cancel. This differs
     from ingest_cfd_kappa, whose denominator is the symmetric model predictor.

Input CSV columns (the contract PyFluent must emit — see asym_pyfluent_runner.py):
    tpms|lattice, split_r, side, Re, Um_m_s, rho, mu, Dh_m|Dh_mm,
    eps_side, eps_sym, dp_core_Pa, L_core_m|core_mm

Output:
    <results>_kappa.csv               κ table (tpms, r, kappa_K, kappa_cF, ...)
    <results>_dffit.csv               per-(tpms,split,side) (K, c_F, kr)
    optional: register in this Python process via kappa_asym.set_kappa_table.
    Research callers can evaluate kappa_KcF(..., enabled=True) in that process.
    Production preparation does not consume the table; no calibration is installed.

Usage:  python -m sjtu_tpmshx.runs.cfd_asym.asym_postproc_kappa results.csv [--register]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

_LAT = {"D": "Diamond", "G": "Gyroid", "Diamond": "Diamond", "Gyroid": "Gyroid"}


def _col(df, *names):
    """First matching column (case-insensitive) from a list of aliases."""
    low = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    raise KeyError(f"need one of {names}; have {list(df.columns)}")


def _load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    out = pd.DataFrame({
        "tpms": df[_col(df, "tpms", "lattice")].map(lambda x: _LAT.get(str(x).strip(), str(x).strip())),
        "split_r": df[_col(df, "split_r", "split")].astype(float),
        "side": df[_col(df, "side")].astype(str).str.strip().str.upper(),
        "Re": df[_col(df, "Re")].astype(float),
        "Um": df[_col(df, "Um_m_s", "v_in_m_s", "Um")].astype(float),
        "rho": df[_col(df, "rho", "rho_ref", "rho_kg_m3")].astype(float),
        "mu": df[_col(df, "mu", "mu_ref", "mu_Pa_s")].astype(float),
        "eps_side": df[_col(df, "eps_side")].astype(float),
        "eps_sym": df[_col(df, "eps_sym")].astype(float),
        "dp_core": df[_col(df, "dp_core_Pa", "dp_core")].astype(float),
    })
    # core length in metres (accept L_core_m or core_mm)
    try:
        out["L_core"] = df[_col(df, "L_core_m")].astype(float)
    except KeyError:
        out["L_core"] = df[_col(df, "core_mm", "core_len_mm", "L_TPMS_mm")].astype(float) / 1e3
    return out


def _fit_df(um, dpdz):
    """Fit dp/dz = a·Um + b·Um²  (a=μ/K, b=c_F·ρ). Returns (a, b, r2)."""
    um = np.asarray(um, float); dpdz = np.asarray(dpdz, float)
    A = np.column_stack([um, um ** 2])
    coef, *_ = np.linalg.lstsq(A, dpdz, rcond=None)
    a, b = coef
    pred = A @ coef
    ss_res = float(np.sum((dpdz - pred) ** 2))
    ss_tot = float(np.sum((dpdz - dpdz.mean()) ** 2)) or 1.0
    return a, b, 1.0 - ss_res / ss_tot


def df_fit(df: pd.DataFrame) -> pd.DataFrame:
    """Per (tpms, split, side): K, c_F from the DF fit over the Re sweep."""
    rows = []
    df = df.copy()
    df["dpdz"] = df["dp_core"] / df["L_core"]
    for (tpms, split, side), g in df.groupby(["tpms", "split_r", "side"]):
        g = g.sort_values("Re")
        rho, mu = float(g["rho"].mean()), float(g["mu"].mean())
        a, b, r2 = _fit_df(g["Um"].values, g["dpdz"].values)
        K = mu / a if a > 0 else float("nan")          # Darcy permeability [m²]
        cF = b / rho if b > 0 else float("nan")        # Forchheimer coef [1/m]
        kr = float(g["eps_side"].iloc[0] / g["eps_sym"].iloc[0])
        rows.append(dict(tpms=tpms, split_r=split, side=side, kr=round(kr, 4),
                         K_cfd=K, cF_cfd=cF, r2=round(r2, 4), n_Re=len(g)))
    return pd.DataFrame(rows).sort_values(["tpms", "split_r", "side"])


def kappa(fit: pd.DataFrame) -> pd.DataFrame:
    """κ(r)=X(r)/X(r=1) per tpms (denominator = symmetric split_r==1 anchor)."""
    out = []
    for tpms, g in fit.groupby("tpms"):
        sym = g[np.isclose(g["split_r"], 1.0)]
        if sym.empty:
            raise ValueError(f"{tpms}: no symmetric split_r=1 anchor — required as κ denominator")
        K1, cF1 = float(sym["K_cfd"].mean()), float(sym["cF_cfd"].mean())
        for _, r in g.iterrows():
            out.append(dict(tpms=tpms, r=r["kr"], split_r=r["split_r"], side=r["side"],
                            kappa_K=r["K_cfd"] / K1 if K1 else float("nan"),
                            kappa_cF=r["cF_cfd"] / cF1 if cF1 else float("nan"),
                            K_cfd=r["K_cfd"], cF_cfd=r["cF_cfd"], r2=r["r2"]))
    return pd.DataFrame(out).sort_values(["tpms", "r"])


def register(kap: pd.DataFrame):
    """Register piecewise linear tables in this process, with flat end values.

    Supplied r≈1 values are retained; the outer κ helper separately
    enforces symmetric identity. No monotonicity constraint is fitted here.
    """
    from sjtu_tpmshx.df_surrogate import kappa_asym
    for tpms, g in kap.groupby("tpms"):
        g = g.sort_values("r")
        r = g["r"].values
        kK, kcF = g["kappa_K"].values, g["kappa_cF"].values

        def _mk(rp, kp):
            rp = np.asarray(rp, float); kp = np.asarray(kp, float)
            if not np.any(np.isclose(rp, 1.0)):           # add a missing anchor
                rp = np.append(rp, 1.0); kp = np.append(kp, 1.0)
            o = np.argsort(rp); rp, kp = rp[o], kp[o]
            keep = np.concatenate(([True], np.diff(rp) > 1e-9))
            rp, kp = rp[keep], kp[keep]
            return lambda rq: float(np.interp(rq, rp, kp))

        kappa_asym.set_kappa_table(tpms, _mk(r, kK), _mk(r, kcF))
        print(f"[register] {tpms}: r∈[{r.min():.3f},{r.max():.3f}] "
              f"κ_K∈[{kK.min():.3f},{kK.max():.3f}] κ_cF∈[{kcF.min():.3f},{kcF.max():.3f}]")
    print("[register] tables are local to this process; research callers can evaluate "
          "kappa_KcF(..., enabled=True). Production preparation does not consume "
          "these tables; no calibration was installed.")


def main(results_csv: str, do_register: bool = False):
    df = _load(results_csv)
    fit = df_fit(df)
    kap = kappa(fit)
    base = Path(results_csv).with_suffix("")
    fit.to_csv(f"{base}_dffit.csv", index=False)
    kap.to_csv(f"{base}_kappa.csv", index=False)
    print(f"[dffit] {base}_dffit.csv  ({len(fit)} per-side fits)")
    print(fit.to_string(index=False))
    print(f"\n[kappa] {base}_kappa.csv")
    print(kap.to_string(index=False))
    if do_register:
        register(kap)
    return fit, kap


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results_csv', help='Per-side/Re CFD rows, including internal-plane pressure drop.')
    parser.add_argument('--register', action='store_true', help='Register only in this process; does not install a calibration.')
    args = parser.parse_args()
    main(args.results_csv, do_register=args.register)
