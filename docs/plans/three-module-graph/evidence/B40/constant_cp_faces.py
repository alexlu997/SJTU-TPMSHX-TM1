"""Independent constant-cp thermal experiment on fixed F2 native mass faces.
Run through runpy from the repository root; preserves original captures.
"""

import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from sjtu_tpmshx.solvers.backends.python.two_d.coupling import _face_mass_fluxes_2d
from sjtu_tpmshx.models.tpms_props import air_cp
from sjtu_tpmshx.solvers.ltne_energy import _gs_full_chunk, _model_h_balance

out = {}
for case, suffix in [("uniform", "-v2"), ("nonuniform", "")]:
    p = Path(".cache/b40-trace/current-2d-" + case + "-engineering" + suffix)
    raw = np.load(p / "native.npz")
    meta = json.loads((p / "capture.json").read_text())
    pre = "thermal/return/"
    a = {k[len(pre) :]: raw[k] for k in raw.files if k.startswith(pre)}
    Ta, Tb, Ts = (a[k].copy() for k in ("Ta", "Tb", "Ts"))
    dx, dy = a["dx_arr"], a["dy_arr"]
    area = dx[:, None] * dy[None, :]
    mass = []
    coeff = []
    for side in ("A", "B"):
        pref = "flow/s" + side + "/"
        s = SimpleNamespace(**{k: raw[pref + k] for k in ("u", "v", "rho_field")})
        mass.append(
            _face_mass_fluxes_2d(
                s, meta[pre + "dir_" + side], a["eps_f" + side + "_arr"], dx, dy
            )
        )
        coeff.append((float(air_cp(meta[pre + "T_in" + side])), 0.0, 0.0, 0.0, 0.0))
    lastA, lastB = Ta.copy(), Tb.copy()
    trace = []
    qprev = float((a["h_vB_arr"] * (Ts - Tb) * area).sum())
    converged = False
    for done in range(500, 2001, 500):
        prev = [v.copy() for v in (Ta, Tb, Ts)]
        residual = _gs_full_chunk(
            Ta,
            Tb,
            Ts,
            *Ta.shape,
            dx,
            dy,
            a["K_ffA_arr"],
            a["K_ffB_arr"],
            a["K_ss_arr"],
            a["h_vA_arr"],
            a["h_vB_arr"],
            a["eps_fA_arr"],
            a["eps_fB_arr"],
            a["rho_cp_fA_arr"],
            a["rho_cp_fB_arr"],
            a["ucA"],
            a["vcA"],
            a["ucB"],
            a["vcB"],
            0,
            3,
            a["T_inA_arr"],
            a["T_inB_arr"],
            a["ifrac_A"],
            a["ifrac_B"],
            500,
            0,
            0,
            a["inlet_flux_A"],
            a["inlet_flux_B"],
            *mass,
            *coeff,
            lastA,
            lastB,
        )
        q = float((a["h_vB_arr"] * (Ts - Tb) * area).sum())
        delta = abs(q - qprev) / abs(q)
        dt = max(float(abs(v - old).max()) for v, old in zip((Ta, Tb, Ts), prev))
        trace.append(
            dict(
                iterations=done,
                Q_W_per_m=q,
                relative_delta_Q=delta,
                max_chunk_delta_T_K=dt,
                sweep_delta_T_K=float(residual),
            )
        )
        if delta < 1e-4 and dt < 0.01:
            converged = True
            break
        qprev = q
    bal = _model_h_balance(
        Ta,
        Tb,
        Ts,
        a["K_ffA_arr"],
        a["K_ffB_arr"],
        a["K_ss_arr"],
        a["h_vA_arr"],
        a["h_vB_arr"],
        dx,
        dy,
        *mass,
        *coeff,
        0,
        3,
        a["T_inA_arr"],
        a["T_inB_arr"],
        a["ifrac_A"],
        a["ifrac_B"],
        False,
        lastA,
        lastB,
    )
    out[case] = dict(
        converged=converged,
        trace=trace,
        balance=bal,
        source_capture=str(p),
        cp_model="original per-side constant inlet cp; h=cp*T",
        initialization="saved engineering temperatures",
        scope="independent thermal experiment on fixed native flow; no production or reference update",
    )
    np.savez(".cache/b40-constant-cp-" + case + ".npz", Ta=Ta, Tb=Tb, Ts=Ts)
    print(case, converged, q, flush=True)
Path(".cache/b40-constant-cp-faces.json").write_text(json.dumps(out, indent=2) + "\n")
