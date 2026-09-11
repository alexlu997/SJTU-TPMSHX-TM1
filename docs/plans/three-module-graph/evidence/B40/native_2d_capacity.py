"""Native SIMPLE boundary energy on retained fields.

Run with runpy from the repository root. This is an offline diagnostic;
Default is original constant inlet cp; --enthalpy selects approved air h(T).
The T-div-mass-cp field remains a constant-cp auxiliary, not an h(T) defect.
"""

import argparse
import json
import runpy
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from sjtu_tpmshx.solvers.backends.python.two_d.coupling import _face_mass_fluxes_2d
from sjtu_tpmshx.models.tpms_props import air_cp, model_h_coefficients

parser = argparse.ArgumentParser()
parser.add_argument("directories", nargs="*", type=Path)
parser.add_argument("--enthalpy", action="store_true", help="reduce approved air cp(T) integral transport")
args = parser.parse_args()
directories = args.directories or [
    Path("/private/tmp/sjtu-tm1-b40-post-wall/.cache/b40-2d-" + case)
    for case in ("uniform", "nonuniform")
]
assert len(directories) == 2, "supply uniform and nonuniform captures"
out = {}
solid_residual = runpy.run_path(str(Path(__file__).with_name('reduce_history.py')))['solid_residual']
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
        def h(t):
            if not args.enthalpy:
                return cp * t
            ca, cb, cc, origin, reference = model_h_coefficients('air')
            x, r = t - origin, reference - origin
            return ca*(x-r) + cb/2*(x*x-r*r) + cc/3*(x*x*x-r*r*r)
        boundary = [float((f * h(t)).sum()) for f, t in zip(faces, temps)]
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
    volume = a['dx_arr'][:, None] * a['dy_arr'][None, :]
    source_s = sum(a['h_v'+side+'_arr']*(a[temp]-a['Ts'])*volume
                   for side, temp in [('A', 'Ta'), ('B', 'Tb')])
    residual_s = solid_residual(a['Ts'][:, :, None], a['K_ss_arr'][:, :, None],
                                source_s[:, :, None], [a['dx_arr'], a['dy_arr'], np.ones(1)])
    scale = max(abs(row['A']['source_W_per_m']), abs(row['B']['source_W_per_m']), 1.)
    row['solid'] = dict(signed_residual_W_per_m=float(residual_s.sum()),
                        l1_residual_W_per_m=float(abs(residual_s).sum()),
                        relative_l1=float(abs(residual_s).sum()) / scale)
    row["source_sha"] = meta["source_sha"]
    row["energy_formulation"] = "air_integral_enthalpy" if args.enthalpy else "constant_inlet_cp"
    row["capture"] = str(p)
    row["q_relative_change"] = meta[pre + "rel_chg"]
    row["temperature_chunk_change_K"] = {
        key: meta[pre + key] for key in ("dTa_max", "dTb_max", "dTs_max")
    }
    row["outputs"] = [meta["outputs/" + str(i)] for i in range(3)]
    out[case] = row
print(json.dumps(out, indent=2))
