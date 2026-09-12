"""Reproduce the existing sCO2 Nu correction without any friction surrogate.

Uses the same experiment membership, geometry and anchored log fit as the
archived compare_exp_vs_cfd report. It does not install new coefficients.
"""
import json

import numpy as np

from sjtu_tpmshx.models.nu_correlations import SCO2_NU_COEFFS
from sjtu_tpmshx.models.tpms_props import geometry
from .load_sco2_exp import load_exp


def analyse(topo: str) -> dict:
    df = load_exp(topo)
    nu_set = df[df.ok_dT & df.ok_hb & df.ok_done].copy()
    Dh_m = float(geometry(topo, 7.0, 0.6, 16.0)["D_h"])
    co = SCO2_NU_COEFFS[topo]
    nu_set["Nu_cfd"] = (co["c"] * np.asarray(nu_set["Re"]) ** co["a"]
                        * np.asarray(nu_set["Pr"]) ** (1 / 3)
                        * (Dh_m * 1e3 / 7.0) ** co["d"])
    nu_set["gamma_Nu"] = nu_set["Nu"] / nu_set["Nu_cfd"]
    lnRe = np.log(nu_set["Re"].to_numpy())
    lnNu = np.log(nu_set["Nu"].to_numpy()) - np.log(nu_set["Pr"].to_numpy()) / 3.0
    c_anch = float(np.exp(np.mean(lnNu - co["a"] * lnRe)))
    c_cfd_eff = co["c"] * (Dh_m * 1e3 / 7.0) ** co["d"]
    return dict(topo=topo, nu_set=nu_set, gamma_nu_fit=c_anch / c_cfd_eff)


if __name__ == "__main__":
    summary = {}
    for topo in ("Diamond", "Gyroid"):
        result = analyse(topo)
        ns = result["nu_set"]
        summary[topo] = dict(gamma=result["gamma_nu_fit"], n=len(ns),
                             re_lo=float(ns.Re.min()), re_hi=float(ns.Re.max()),
                             sig_ln=float(np.std(np.log(ns.gamma_Nu), ddof=1)))
    print(json.dumps(summary, indent=2))
