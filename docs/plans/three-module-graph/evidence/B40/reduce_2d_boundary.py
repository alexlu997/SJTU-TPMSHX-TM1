"""Offline four-face 2D diagnostic of retained post-wall captures; no PDE runs.

The defect is the equivalent temperature-form T div(capacity flux) term.
The inlet-temperature substitution is limited to these forward-inlet cases.
A small equation residual does not make the uncorrected boundary gap pass.
Native SIMPLE mass uses its total-porosity convention (physical side is half).
"""

import json
from pathlib import Path
import numpy as np
from reduce_history import solid_residual

results = {}
for case in ("uniform", "nonuniform"):
    p = Path("/private/tmp/sjtu-tm1-b40-post-wall/.cache/b40-2d-" + case)
    raw = np.load(p / "native.npz")
    meta = json.loads((p / "capture.json").read_text())
    pre = "thermal/return/"
    a = {k[len(pre) :]: raw[k] for k in raw.files if k.startswith(pre)}
    dx, dy = a["dx_arr"], a["dy_arr"]
    vol = dx[:, None] * dy[None, :]
    out = {}
    for side, Tn in [("A", "Ta"), ("B", "Tb")]:
        T = a[Tn]
        cap = a["eps_f" + side + "_arr"] * a["rho_cp_f" + side + "_arr"]
        fx = cap * a["uc" + side] * dy
        fy = cap * a["vc" + side] * dx[:, None]
        x = np.concatenate((fx[:1], 0.5 * (fx[:-1] + fx[1:]), fx[-1:]), axis=0)
        y = np.concatenate(
            (fy[:, :1], 0.5 * (fy[:, :-1] + fy[:, 1:]), fy[:, -1:]), axis=1
        )
        direction = meta[pre + "dir_" + side]
        axis = direction // 2
        end = 0 if direction % 2 == 0 else -1
        sign = -1 if end == 0 else 1
        face = [slice(None), slice(None)]
        face[axis] = end
        face = tuple(face)
        faces = (x, y)
        faces[axis][face] = -sign * a["inlet_flux_" + side]
        temps = [T[0], T[-1], T[:, 0], T[:, -1]]
        temps[direction] = a["T_in" + side + "_arr"]
        fluxes = [-x[0], x[-1], -y[:, 0], y[:, -1]]
        boundary = [float((f * t).sum()) for f, t in zip(fluxes, temps)]
        width = (dx, dy)[axis][end]
        cross = (dy, dx)[axis]
        conduction = float(
            (
                2
                * a["K_ff" + side + "_arr"][face]
                * cross
                * a["ifrac_" + side]
                / width
                * (T[face] - temps[direction])
            ).sum()
        )
        source = float((a["h_v" + side + "_arr"] * (a["Ts"] - T) * vol).sum())
        defect = float((T * (np.diff(x, axis=0) + np.diff(y, axis=1))).sum())
        out[side] = dict(
            boundary=boundary,
            conduction=conduction,
            source=source,
            defect=defect,
            residual=sum(boundary) + conduction - source - defect,
        )
        pref = "flow/s" + side + "/"
        rhoeps = raw[pref + "rho_field"] * raw[pref + "eps_field"]
        u = raw[pref + "u"]
        v = raw[pref + "v"]
        wx = raw[pref + "dx_arr"]
        wy = raw[pref + "dy_arr"]
        mass = [
            float((-rhoeps[0] * u[0] * wy).sum()),
            float((rhoeps[-1] * u[-1] * wy).sum()),
            float((-rhoeps[:, 0] * v[:, 0] * wx).sum()),
            float((rhoeps[:, -1] * v[:, -1] * wx).sum()),
        ]
        out[side]["mass"] = mass
        out[side]["mass_relative"] = abs(sum(mass)) / max(abs(z) for z in mass)
    solid = sum(
        a["h_v" + s + "_arr"] * (a[t] - a["Ts"]) * vol
        for s, t in [("A", "Ta"), ("B", "Tb")]
    )
    res = solid_residual(
        a["Ts"][:, :, None],
        a["K_ss_arr"][:, :, None],
        solid[:, :, None],
        [dx, dy, np.ones(1)],
    )
    out["solid"] = {"sum": float(res.sum()), "l1": float(abs(res).sum())}
    out["q_delta"] = meta[pre + "rel_chg"]
    out["source_sha"] = meta["source_sha"]
    out["units"] = {"energy": "W/m", "mass_flow": "kg/(s m)"}
    out["status"] = "diagnostic; boundary conservation not passed"
    results[case] = out
print(json.dumps(results, indent=2))
