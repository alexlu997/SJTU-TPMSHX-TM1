"""load_water_cfd.py — water-side unit-cell CFD loader for Nu / DF refits.

Mirrors ``load_sco2_cfd`` conventions so water and sCO2 correlations are fit
in ONE Dh basis (the solver's ``tpms_calc`` Dh), which is what makes them
interchangeable in the homogenised solver.

Source: ``data/raw_data/Water-CFD/水数值模拟数据.xlsx`` (2026-07-23 upload;
single sheet, 40 geometries D+G, L∈[4,8]×t∈[0.3,0.6] mm, ~46 Re each,
Re 93–50000). One row per case; the three streamwise cells are reported as
``Core1_Nu`` / ``Core2_Nu`` / ``Core3_Nu`` plus the core aggregate
``Nu_core`` / ``Darcy_f_core``. This describes the 2026-07-23 source record;
that revised workbook is currently missing. The older water-cfd-raw source is
retained as ``cfd/water/water_DG_cfd_results_legacy.xlsx`` for its separate
validation route, never as an automatic substitute. See docs/data-catalog.md.

Conventions (repo, NOT the sheet's own) — identical to load_sco2_cfd:
    t_mm       real wall thickness; auto-detected (t-code 3..6 ÷10 vs real
               0.3..0.6 as-is), decided per row by whether the value exceeds 1.
    Dh_m       from ``tpms_calc.geometry``; the sheet's mesh Dh kept as
               ``Dh_cfd_m``. Every solver / correlation consumer uses the
               tpms_calc value, so the fit must share it.
    Re / Nu / f  recomputed from raw (Um, h, dp) with the repo Dh; the
               sheet's own Re kept as ``Re_nominal`` (case-matrix label).
    Nu_dev     ENTRANCE-DROPPED Nu = mean(Core2, Core3) rescaled to repo Dh
               (Nu ∝ Dh at fixed h, k). Core1 is entrance-affected (~10% low,
               same as sCO2 period-1); Nu_dev is the developed value and the
               recommended fit target. Nu (full-core, repo Dh) also provided.

⚠ FLOW-DATA CAVEAT — Diamond D_7_3 / D_7_4 / D_7_5 carry the SAME mdot/Um
mass-balance inconsistency as the sCO2 export (mdot/(ρ·Um·L²) exceeds the true
geometry porosity by +3.9/+5.4/+7.3%; geometry itself is correct — verified by
the wetted-area A_0 check). Nu is velocity-free so it is UNAFFECTED on these;
Re-position and f depend on Um and may be off by ~5%/~10% there. They are
flagged via the ``flow_suspect`` column. See load_sco2_cfd module doc.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent  # .../sjtu_tpmshx
from sjtu_tpmshx.df_surrogate.cfd_geometry import attach_geometry
from sjtu_tpmshx.logutil import get_logger  # noqa: E402

_log = get_logger(__name__)

WATER_XLSX = (_PROJECT_ROOT.parent / "data" / "raw_data" / "Water-CFD"
              / "水数值模拟数据.xlsx")
LATTICES = ("Diamond", "Gyroid")
_CODE = {"Diamond": "D", "Gyroid": "G"}

# geometries whose reported Um/mdot don't close continuity with the true
# geometry (see module doc); velocity-derived quantities suspect there.
FLOW_SUSPECT = {"D_7_3", "D_7_4", "D_7_5"}


def load_water(lattice: str = "Diamond", *, source=None) -> pd.DataFrame:
    """Per-case water CFD with repo-convention Re / Nu / Nu_dev / f.

    Adds (repo Dh throughout):
        Re         rho·Um·Dh/mu
        Pr         mu·cp/k
        Nu         full-core  h·Dh/k
        Nu_dev     entrance-dropped mean(Core2,Core3)·(Dh_repo/Dh_cfd)
        f          Darcy  (dp/L)·Dh/(0.5·rho·Um²)
        Re_nominal sheet's own Re label
        flow_suspect  True on FLOW_SUSPECT geometries
    """
    if lattice not in LATTICES:
        raise ValueError(f"lattice must be one of {LATTICES}, got {lattice!r}")
    source = WATER_XLSX if source is None else Path(source)
    xl = pd.read_excel(source)
    code = _CODE[lattice]
    df = xl[xl["geometry_id"].str.startswith(code)].copy()
    if df.empty:
        raise ValueError(f"no {lattice} ({code}_*) rows in {source.name}")
    df = attach_geometry(df, lattice)
    df = df.rename(columns={"Re": "Re_nominal"})
    df["tpms"] = lattice

    rho, mu, k = df["rho_kg_m3"], df["mu_Pa_s"], df["k_W_mK"]
    u, dh = df["Um_m_s"], df["Dh_m"]
    dh_ratio = df["Dh_m"] / df["Dh_cfd_m"]        # Nu, Re ∝ Dh at fixed h/u
    df["dpdl_Pa_m"] = df["dp_core_Pa"] / df["core_length_m"]
    df["Re"] = rho * u * dh / mu
    df["Pr"] = mu * df["cp_J_kgK"] / k
    df["Nu"] = df["h_core_W_m2K"] * dh / k
    df["Nu_dev"] = 0.5 * (df["Core2_Nu"] + df["Core3_Nu"]) * dh_ratio
    df["f"] = df["dpdl_Pa_m"] * dh / (0.5 * rho * u ** 2)
    df["flow_suspect"] = df["geometry_id"].isin(FLOW_SUSPECT)

    if (df["dp_core_Pa"] <= 0).any():
        n = int((df["dp_core_Pa"] <= 0).sum())
        raise ValueError(f"{n} water rows with non-positive dp — inspect.")
    _log.info(f"load_water[{lattice}]: {len(df)} cases, "
              f"{df['geometry_id'].nunique()} geometries, "
              f"Re {df['Re'].min():.0f}-{df['Re'].max():.0f}, "
              f"Pr {df['Pr'].min():.2f}-{df['Pr'].max():.2f}"
              + (f", {int(df['flow_suspect'].sum())} flow-suspect rows"
                 if df["flow_suspect"].any() else ""))
    return df


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    for lat in LATTICES:
        d = load_water(lat)
        print(f"\n{lat}: {len(d)} cases / {d['geometry_id'].nunique()} geoms")
        print(d.groupby("geometry_id")[["Re", "Nu", "Nu_dev", "f"]]
              .median().round(3).to_string())
