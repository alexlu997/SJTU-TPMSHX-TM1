"""Native SIMPLE mass times original constant inlet cp, on retained fields.

Run with runpy from the repository root. This is an offline diagnostic;
no corrected thermal solve or new physical model is implied.
"""

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from sjtu_tpmshx.solvers.backends.python.two_d.coupling import _face_mass_fluxes_2d
from sjtu_tpmshx.models.tpms_props import air_cp

parser = argparse.ArgumentParser()
parser.add_argument("directories", nargs="*", type=Path)
args = parser.parse_args()
directories = args.directories or [
    Path("/private/tmp/sjtu-tm1-b40-post-wall/.cache/b40-2d-" + case)
    for case in ("uniform", "nonuniform")
]
assert len(directories) == 2, "supply uniform and nonuniform captures"
out = {}
for case, p in zip(("uniform", "nonuniform"), directories):
    raw = np.load(p / "native.npz")
    meta = json.loads((p / "capture.json").read_text())
    pre = "thermal/return/"
    a = {k[len(pre) :]: raw[k] for k in raw.files if k.startswith(pre)}
    row = {}
    for side, Tn in [("A", "Ta"), ("B", "Tb")]:
        pref = "flow/s" + side + "/"
        s = SimpleNamespace(**{k: raw[pref + k] for k in ("u", "v", "rho_field")})
        direction = meta[pre + "dir_" + side]
        cp = float(air_cp(meta[pre + "T_in" + side]))
        mass = _face_mass_fluxes_2d(
            s, direction, a["eps_f" + side + "_arr"], a["dx_arr"], a["dy_arr"]
        )
        faces = [-mass[0][0], mass[0][-1], -mass[1][:, 0], mass[1][:, -1]]
        T = a[Tn]
        temps = [T[0], T[-1], T[:, 0], T[:, -1]]
        temps[direction] = a["T_in" + side + "_arr"]
        boundary = [float((f * cp * t).sum()) for f, t in zip(faces, temps)]
        div = np.diff(mass[0], axis=0) + np.diff(mass[1], axis=1)
        axis = direction // 2
        end = 0 if direction % 2 == 0 else -1
        inlet = (end, slice(None)) if axis == 0 else (slice(None), end)
        widths = (a["dx_arr"], a["dy_arr"])
        conduction = float(
            (
                2
                * a["K_ff" + side + "_arr"][inlet]
                * widths[1 - axis]
                * a["ifrac_" + side]
                / widths[axis][end]
                * (T[inlet] - a["T_in" + side + "_arr"])
            ).sum()
        )
        source = float(
            (
                a["h_v" + side + "_arr"]
                * (a["Ts"] - T)
                * widths[0][:, None]
                * widths[1][None, :]
            ).sum()
        )
        gap = sum(boundary) + conduction - source
        row[side] = dict(
            native_boundary_minus_exchange_W_per_m=gap,
            relative_boundary_gap=abs(gap) / max(abs(source), 1.),
            native_boundary_capacity_energy_W_per_m=boundary,
            native_T_div_mass_cp_W_per_m=float((T * cp * div).sum()),
            native_mass_div_l1=float(abs(div).sum()),
            cp_J_kg_K=cp,
            source_W_per_m=source,
            conduction_W_per_m=conduction,
            f2={
                key: meta.get(pref + key)
                for key in (
                    "final_res_mom",
                    "final_res_mass_local",
                    "final_res_mass_global",
                )
            },
        )
    row["source_sha"] = meta["source_sha"]
    row["capture"] = str(p)
    row["q_relative_change"] = meta[pre + "rel_chg"]
    row["temperature_chunk_change_K"] = {
        key: meta[pre + key] for key in ("dTa_max", "dTb_max", "dTs_max")
    }
    row["outputs"] = [meta["outputs/" + str(i)] for i in range(3)]
    out[case] = row
print(json.dumps(out, indent=2))
