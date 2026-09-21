"""asym_pyfluent_runner.py — Phase-1 asym-porosity CFD batch via PyFluent.

Drives ANSYS Fluent over the asym_cfd_worklist.xlsx matrix. For each geometry
(one nTop-exported mesh per (tpms, split, side)) it sweeps the per-side Re list,
runs steady pressure-based SIMPLE, and reads the FOUR internal-plane pressures
p0..p3 at the core-cell boundaries → dp_core = p0 − p3 (developed friction,
entrance/exit excluded). Emits one results CSV that asym_postproc_kappa.py
consumes (DF fit → κ).

Locked domain (see plan §6):
    [inlet_mm straight] + [n_core × period offset-TPMS core] + [outlet_mm straight]
    cross-section 1 cell L×L, lateral x,y = PERIODIC (set in the mesh),
    straight channels = void face extruded.
    BC: mass-flow inlet (worklist mdot_kg_s) + pressure outlet.
    planes p_i at z = inlet_mm + i·period  (i = 0..n_core), dp_core = p0 − p3.

NOTE: this is the orchestration skeleton — runs on the Fluent machine, not here.
Adjust MESH_DIR / mesh_path(), the periodic-zone names, and any version-specific
settings-tree paths to your PyFluent build (tested shape: 2024R1 / 2025R1 API).

Usage (on the CFD box):
    python -m sjtu_tpmshx.runs.cfd_asym.asym_pyfluent_runner --worklist asym_cfd_worklist.xlsx \
        --mesh-dir ./meshes  --out asym_cfd_results.csv  --procs 8
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import ansys.fluent.core as pyfluent

# ── geometry → mesh file convention (nTop exports one fluid domain per side) ──
def mesh_path(mesh_dir: Path, tpms: str, split_r: float, side: str) -> Path:
    # e.g. meshes/Diamond_r2_A.msh  (.msh, .cas, or .cas.h5 — adjust as needed)
    return mesh_dir / f"{tpms}_r{split_r:g}_{side}.msh"


# ── per-geometry Fluent setup ────────────────────────────────────
def setup_fluid(solver, fluid: str, rho: float, mu: float, cp: float, k: float):
    """Air = ideal-gas compressible (energy on); water = constant-prop incompressible."""
    setup = solver.settings.setup
    if fluid == "air":
        setup.models.energy.enabled = True
        m = setup.materials.fluid["air"]
        m.density.option = "ideal-gas"
        m.viscosity.value = mu            # or sutherland; const inlet-ref is fine for κ
        m.specific_heat.value = cp
        m.thermal_conductivity.value = k
    else:                                  # water (incompressible, const props)
        setup.models.energy.enabled = False     # dP-only; enable for Nu spot-check
        m = setup.materials.fluid["water-liquid"]
        m.density.option = "constant"; m.density.value = rho
        m.viscosity.value = mu
        m.specific_heat.value = cp
        m.thermal_conductivity.value = k


def make_planes(solver, inlet_mm: float, period_mm: float, n_core: int):
    """Iso-surfaces p0..p{n_core} at the core-cell boundaries (z in metres)."""
    names = []
    for i in range(n_core + 1):
        z = (inlet_mm + i * period_mm) / 1e3        # mm → m
        nm = f"p{i}"
        solver.settings.results.surfaces.iso_surface[nm] = {
            "field": "z-coordinate", "iso_values": [z]}
        names.append(nm)
    return names


def plane_pressure(solver, name: str) -> float:
    """Area-weighted-average static pressure on a plane surface [Pa]."""
    rep = solver.settings.results.report_definitions.surface
    rep["_pp"] = {"report_type": "surface-areaavg",
                  "field": "pressure", "surface_names": [name]}
    val = float(rep["_pp"].compute()[0])   # API name may vary by PyFluent version
    del rep["_pp"]
    return val


def run_case(solver, mdot: float, T_in: float, n_iter: int = 600):
    bc = solver.settings.setup.boundary_conditions
    bc.mass_flow_inlet["inlet"].momentum.mass_flow_rate.value = mdot
    bc.mass_flow_inlet["inlet"].thermal.temperature.value = T_in
    bc.pressure_outlet["outlet"].momentum.gauge_pressure.value = 0.0
    solver.settings.solution.run_calculation.iterate(iter_count=n_iter)


# ── batch driver ─────────────────────────────────────────────────
def main(worklist: str, mesh_dir: str, out_csv: str, procs: int):
    wl = pd.read_excel(worklist, sheet_name="cfd_worklist", engine="openpyxl")
    mesh_dir = Path(mesh_dir)
    results = []

    # one mesh per (tpms, split, side); inner loop = its Re sweep
    for (tpms, split_r, side), grp in wl.groupby(["lattice", "split_r", "side"]):
        mp = mesh_path(mesh_dir, tpms, split_r, side)
        if not mp.exists():
            print(f"[skip] mesh missing: {mp}")
            continue
        r0 = grp.iloc[0]
        solver = pyfluent.launch_fluent(precision="double", processor_count=procs,
                                        mode="solver", dimension=3)
        try:
            solver.settings.file.read_mesh(file_name=str(mp))
            # nTop usually exports in mm → scale to metres if needed:
            # solver.settings.mesh.scale(x_scale=1e-3, y_scale=1e-3, z_scale=1e-3)
            # TODO: make lateral x,y faces translational-periodic (mesh-dependent;
            #       create matched periodic zones in meshing, then make_periodic).
            setup_fluid(solver, r0["fluid"], r0["rho"], r0["mu"], r0["cp"], r0["k_cond"])
            solver.settings.setup.general.solver.type = "pressure-based"
            solver.settings.setup.general.solver.time = "steady"
            planes = make_planes(solver, r0["inlet_mm"], r0["period_mm"], int(r0["n_core"]))
            p_lo, p_hi = planes[0], planes[-1]              # p0, p_{n_core}

            for _, row in grp.sort_values("Re").iterrows():
                run_case(solver, float(row["mdot_kg_s"]), float(row["Tref_K"]))
                press = {nm: plane_pressure(solver, nm) for nm in planes}
                dp_core = press[p_lo] - press[p_hi]
                results.append({
                    "case_id": row["case_id"], "tpms": tpms, "split_r": split_r,
                    "side": side, "Re": row["Re"], "Um_m_s": row["Um_m_s"],
                    "rho": row["rho"], "mu": row["mu"],
                    "Dh_m": row["Dh_mm"] / 1e3, "eps_side": row["eps_side"],
                    "eps_sym": row["eps_sym"], "L_core_m": row["core_mm"] / 1e3,
                    **{f"{k}_Pa": v for k, v in press.items()},
                    "dp_core_Pa": dp_core,
                })
                print(f"[ok] {row['case_id']}  dp_core={dp_core:.3f} Pa")
        finally:
            solver.exit()

    pd.DataFrame(results).to_csv(out_csv, index=False)
    print(f"\n[csv] {out_csv}  ({len(results)} rows) "
          f"→ python -m sjtu_tpmshx.runs.cfd_asym.asym_postproc_kappa {out_csv}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--worklist", default="asym_cfd_worklist.xlsx")
    ap.add_argument("--mesh-dir", default="./meshes")
    ap.add_argument("--out", default="asym_cfd_results.csv")
    ap.add_argument("--procs", type=int, default=8)
    a = ap.parse_args()
    main(a.worklist, a.mesh_dir, a.out, a.procs)
