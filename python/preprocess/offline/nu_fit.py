"""Existing sCO2 log-space calibration; no production coefficient mutation."""
import numpy as np
import pandas as pd


def _design_matrix(d: pd.DataFrame, terms: list[str]) -> np.ndarray:
    cols = {
        "re": np.log(d["Re_b"].values),
        "pr": np.log(d["Pr_b"].values),
        "dhl": np.log(d["Dh_m"].values / (d["L_mm"].values * 1e-3)),
        "rho": np.log(d["rho_w"].values / d["rho_b"].values),
        "cp": np.log(d["cp_bar"].values / d["cp_b"].values),
        "mu": np.log(d["mu_w"].values / d["mu_b"].values),
    }
    return np.column_stack([np.ones(len(d))] + [cols[t] for t in terms])


def fit_nu_sco2(d: pd.DataFrame, terms: list[str],
         fixed: dict[str, float] | None = None) -> dict[str, float]:
    """OLS in log space; ``fixed`` pins exponents (moved to the LHS)."""
    fixed = fixed or {}
    free = [t for t in terms if t not in fixed]
    y = np.log(d["Nu_b"].values)
    X_all = _design_matrix(d, terms)
    for i, t in enumerate(terms):
        if t in fixed:
            y = y - fixed[t] * X_all[:, 1 + i]
    X = _design_matrix(d, free)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    out = {"c": float(np.exp(beta[0]))}
    names = {"re": "a", "pr": "b", "dhl": "d", "rho": "p", "cp": "q",
             "mu": "e"}
    for t in terms:
        out[names[t]] = float(fixed[t]) if t in fixed \
            else float(beta[1 + free.index(t)])
    return out


