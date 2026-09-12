"""Shared CFD geometry columns; raw schemas and flow checks stay with readers."""
import numpy as np
import pandas as pd
from sjtu_tpmshx.models.tpms_props import geometry as tpms_geometry


def attach_geometry(df: pd.DataFrame, lattice: str) -> pd.DataFrame:
    """Real t_mm + repo-convention eps / Dh (tpms_calc); raw Dh -> Dh_cfd_m."""
    out = df.copy()
    out["L_mm"] = out["cell_size_mm"].astype(float)
    # Older rows store t-codes 3..6, newer rows store real 0.3..0.6 mm.
    t_raw = out["wall_thickness_mm"].astype(float)
    out["t_mm"] = np.where(t_raw.to_numpy() > 1.0, t_raw / 10.0, t_raw)
    cache: dict[tuple[float, float], tuple[float, float]] = {}
    eps = np.empty(len(out))
    dh = np.empty(len(out))
    for i, (L, t) in enumerate(zip(out["L_mm"].to_numpy(),
                                   out["t_mm"].to_numpy())):
        key = (round(L, 3), round(t, 3))
        if key not in cache:
            g = tpms_geometry(lattice, key[0], key[1], 16.0)
            cache[key] = (float(g["epsilon"]), float(g["D_h"]))
        eps[i], dh[i] = cache[key]
    out["eps"] = eps
    out["eps_f"] = eps / 2.0
    out["Dh_cfd_m"] = out["Dh_m"]
    out["Dh_m"] = dh
    return out
