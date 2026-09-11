"""Load sCO2 unit-cell CFD data (2026-07 campaign, smooth wall).

Dataset: ``data/raw_data/sCO2-CFD/{Diamond,Gyroid}/`` — see the README.md
there for the confirmed CFD setup (smooth wall, RANS, no gravity,
Twall = Tref + 50 K) and the case-matrix derivation. Same post-processing
pipeline / column schema as ``water-cfd-raw.xlsx``
(see ``smooth_df._load_points``).

Two loaders (``lattice`` = 'Diamond' | 'Gyroid'):

``load_core(lattice)``     — 1 row per case (core = 3 periods). D-F basis.
``load_segments(lattice)`` — 3 rows per case (per-period slices) with LOCAL
                      bulk properties re-evaluated by CoolProp at
                      (P, T_b_local). Basis for Nu-correlation work
                      (near-critical cases cross the cp spike WITHIN the
                      core, so core-averaged properties smear it;
                      per-segment is the resolution limit of this dataset).

Conventions (repo, NOT the CSV's own):
    t_mm       real wall thickness, auto-detected from
               ``wall_thickness_mm``: older exports store the t-code 3..6
               (÷10), the 2026-07-23 exports store real mm 0.3..0.6 as-is;
               ``_attach_geometry`` decides per-file on whether the max
               exceeds 1.0.
    Dh_m       from ``tpms_calc.geometry`` — every downstream consumer
               (solver, correlations) uses the tpms_calc value, so the fit
               MUST share it or the correlation misapplies in the solver.
               Raw CSV Dh kept as ``Dh_cfd_m``.
               2026-07-22 RETRO-VALIDATION: the corrected upload's
               mesh-measured Dh now agrees with tpms_calc to 0.43% on
               Gyroid (the OLD export ran +5.8% median / +10.2% max), and
               on Diamond to 0.12% median / 0.24% max at N=256 — i.e. the
               override was right and the old mesh Dh was the error.

               ⚠ FLOW-DATA INCONSISTENCY (NOT a geometry error) —
               Diamond D_7_3 / D_7_4 / D_7_5. Re-adjudicated 2026-07-23
               with the corrected upload; SUPERSEDES the earlier
               "bad mesh / thin walls" call, which was WRONG (it was
               misled by the old export's Dh being off in lock-step).
               The GEOMETRY is correct on all 20: the mesh's own wetted
               area A_wall gives A_0 matching tpms_calc to 0.4% for every
               geometry INCLUDING these three (Um-independent check), and
               the file Dh now matches to <0.3%. The single remaining
               anomaly is a MASS-BALANCE gap in the flow data:
               mdot/(rho·Um·L²) exceeds the true (geometric) porosity by
               +3.9 / +5.4 / +7.3% on these three, i.e. reported mdot and
               Um don't close continuity with the correct geometry.
               Whether Um is ~5% low or mdot is ~5% high can't be settled
               from the CSV alone (the Re and energy-balance cross-checks
               are circular — Re_nominal and Q_core are derived from Um and
               mdot respectively). CONSEQUENCE for fits:
                 Nu = h·Dh/k          — NO velocity term → SAFE on all 20.
                 Re = rho·Um·Dh/mu    — uses Um → these 3 shift ~±5% along
                 f  = dpdl·Dh/(ρU²/2)   the Re axis / f by ~10% IF Um (not
                                        mdot) is the wrong one.
               Fit Nu on all 20 freely; for f, flag D_7_3/4/5 as pending a
               provider answer on which of mdot/Um is authoritative.
    Re / Nu / f  recomputed from raw physical quantities (Um, h, dp) with
               the repo Dh. CSV's own Re kept as ``Re_nominal`` (case-matrix
               label) — do not fit against it.
    u          interstitial (in-pore) mean velocity = CSV ``Um_m_s``.
    f          Darcy: f = (dp/L) · Dh / (ρ·u²/2).

Pressure attachment: the CSVs do not store the operating pressure; it is
uniquely encoded in Tref's two decimals (campaign design anchors Tref to
the pseudocritical line T_pc(P); CoolProp max-cp check matches the grid
digit-for-digit). ``_P_BY_CENTS`` below. A CoolProp ρ(Tref, P) guard
verifies every unique property state on load and fails loudly on mismatch,
so a future upload with a new pressure level cannot be silently mis-tagged.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent  # .../sjtu_tpmshx
from sjtu_tpmshx.models.tpms_props import geometry as tpms_geometry  # noqa: E402
from sjtu_tpmshx.logutil import get_logger  # noqa: E402

_log = get_logger(__name__)

DATA_ROOT = _PROJECT_ROOT.parent / "data" / "raw_data" / "sCO2-CFD"
LATTICES = ("Diamond", "Gyroid")


def _resolve_csv(lattice: str, kind: str) -> Path:
    """Locate the core / segment CSV for a lattice by CONTENT, not filename.

    kind: 'core' (one row per case) or 'seg' (per-period rows).

    Filenames are NOT reliable across uploads: the 2026-07-22/23 exports
    (``{lat}三个胞元平均/独立数据*.csv``) and the 2026-07-15 exports
    (``tpms_core_summary.../tpms_period_segments...csv``) coexist, and worse,
    the new Diamond files have their 平均(avg)/独立(indep) labels SWAPPED
    vs their contents (平均数据 actually holds the per-segment rows) while
    Gyroid's do not. So classify by the tell-tale ``segment`` column: the
    per-period export has it, the core-summary export does not.
    """
    if lattice not in LATTICES:
        raise ValueError(f"lattice must be one of {LATTICES}, got {lattice!r}")
    d = DATA_ROOT / lattice
    core, seg, seen = None, None, []
    for p in sorted(d.glob("*.csv")):
        cols = set(pd.read_csv(p, nrows=0).columns)
        seen.append(p.name)
        if "segment" in cols:
            seg = p
        elif {"Nu_core", "Darcy_f_core"} & cols:
            core = p
    hit = core if kind == "core" else seg
    if hit is None:
        raise FileNotFoundError(
            f"{lattice} sCO2 {kind} CSV not found under {d} — saw {seen}. "
            f"(core = has Nu_core/Darcy_f_core; seg = has a `segment` column.)")
    return hit

# Tref cents -> operating pressure [MPa]. Confirmed by data provider
# (2026-07-15) + CoolProp rho-inversion; see dataset README.
_P_BY_CENTS = {82: 8.0, 16: 10.0, 12: 12.0, 48: 15.0}
# Pseudocritical temperature at each pressure [K] (CoolProp max-cp point;
# identical to the campaign's Tref anchor values).
_TPC_BY_P = {8.0: 307.82, 10.0: 318.16, 12.0: 327.12, 15.0: 337.48}

_RHO_GUARD_RTOL = 0.01   # CoolProp vs CSV reference density
_K_S_DEFAULT = 16.0      # only affects K_ss inside tpms_calc, not eps/Dh

# Nu-fit hygiene: period-1 slice is entrance-affected (Nu ~13% low vs
# periods 2/3 which agree to ~1%); drop it by default in load_segments.
ENTRANCE_SEGMENT = 1


def _attach_pressure(df: pd.DataFrame) -> pd.DataFrame:
    """Add P_MPa / P_Pa / Tpc_K / dT_pc from the Tref decimal encoding."""
    cents = (df["Tref"] * 100).round().astype(int) % 100
    unknown = sorted(set(cents.unique()) - set(_P_BY_CENTS))
    if unknown:
        raise ValueError(
            f"Tref decimal(s) {unknown} not in the pressure map "
            f"{_P_BY_CENTS} — new pressure level in an upload? Extend "
            f"_P_BY_CENTS/_TPC_BY_P after verifying with CoolProp.")
    out = df.copy()
    out["P_MPa"] = cents.map(_P_BY_CENTS)
    out["P_Pa"] = out["P_MPa"] * 1e6
    out["Tpc_K"] = out["P_MPa"].map(_TPC_BY_P)
    out["dT_pc"] = (out["Tref"] - out["Tpc_K"]).round(2)
    return out


def _verify_rho_guard(df: pd.DataFrame) -> None:
    """CoolProp rho(Tref, P) must reproduce the CSV reference density."""
    from CoolProp.CoolProp import PropsSI

    states = df[["Tref", "P_Pa", "rho_kg_m3"]].drop_duplicates(
        subset=["Tref", "P_Pa"])
    rho_cp = PropsSI("D", "T", states["Tref"].to_numpy(),
                     "P", states["P_Pa"].to_numpy(), "CO2")
    rel = np.abs(rho_cp - states["rho_kg_m3"].to_numpy()) \
        / states["rho_kg_m3"].to_numpy()
    if rel.max() > _RHO_GUARD_RTOL:
        bad = states.iloc[int(np.argmax(rel))]
        raise ValueError(
            f"Pressure-map guard tripped: CoolProp rho({bad.Tref} K, "
            f"{bad.P_Pa / 1e6:g} MPa) deviates {rel.max():.2%} from the CSV "
            f"reference density {bad.rho_kg_m3:g} — Tref->P mapping wrong "
            f"for this state?")
    _log.info(f"  pressure-map rho guard OK: {len(states)} states, "
              f"max dev {rel.max():.3%}")


def _attach_geometry(df: pd.DataFrame, lattice: str) -> pd.DataFrame:
    """Real t_mm plus repo-convention eps / eps_f / Dh (tpms_calc)."""
    out = df.copy()
    expected_code = {"Diamond": "D", "Gyroid": "G"}[lattice]
    codes = set(out["lattice"].unique())
    if codes != {expected_code}:
        raise ValueError(f"{lattice} loader got lattice codes {codes} — "
                         f"wrong folder contents?")
    out["L_mm"] = out["cell_size_mm"].astype(float)
    # Wall-thickness convention auto-detect (flipped between uploads):
    #   older exports store the t-CODE 3..6  (real t = code/10),
    #   2026-07-23 exports store REAL mm 0.3..0.6 directly.
    # Real walls are always < 1 mm and codes always ≥ 3, so the gap at 1.0
    # separates them unambiguously; decide per-file on the max.
    t_raw = out["wall_thickness_mm"].astype(float)
    out["t_mm"] = np.where(t_raw.to_numpy() > 1.0, t_raw / 10.0, t_raw)
    cache: dict[tuple[float, float], tuple[float, float]] = {}
    eps = np.empty(len(out))
    dh = np.empty(len(out))
    for i, (L, t) in enumerate(zip(out["L_mm"].to_numpy(),
                                   out["t_mm"].to_numpy())):
        key = (round(L, 3), round(t, 3))
        if key not in cache:
            g = tpms_geometry(lattice, key[0], key[1], _K_S_DEFAULT)
            cache[key] = (float(g["epsilon"]), float(g["D_h"]))
        eps[i], dh[i] = cache[key]
    out["eps"] = eps
    out["eps_f"] = eps / 2.0
    out["Dh_cfd_m"] = out["Dh_m"]
    out["Dh_m"] = dh
    return out


def load_core(lattice: str = "Diamond", *, source=None) -> pd.DataFrame:
    """Core-summary rows (1/case) with repo-convention Re / f / Nu.

    Adds:
        tpms       lattice name ('Diamond' / 'Gyroid')
        A_flow_m2  open flow area = mdot / (rho_ref · Um)
        G_kg_m2s   mass flux = mdot / A_flow
        dpdl_Pa_m  dp_core / core_length
        Re, f, Nu  repo-Dh conventions (reference properties at Tref)
        Re_nominal CSV case-matrix Re label
    """
    if lattice not in LATTICES:
        raise ValueError(f'lattice must be one of {LATTICES}, got {lattice!r}')
    df = pd.read_csv(_resolve_csv(lattice, "core") if source is None else source)
    df = _attach_pressure(df)
    _verify_rho_guard(df)
    df = _attach_geometry(df, lattice)
    df = df.rename(columns={"Re": "Re_nominal"})
    df["tpms"] = lattice

    rho, mu, k = df["rho_kg_m3"], df["mu_Pa_s"], df["k_W_mK"]
    u, dh = df["Um_m_s"], df["Dh_m"]
    df["A_flow_m2"] = df["mdot_in_kg_s"] / (rho * u)
    df["G_kg_m2s"] = rho * u
    df["dpdl_Pa_m"] = df["dp_core_Pa"] / df["core_length_m"]
    df["Re"] = rho * u * dh / mu
    df["f"] = df["dpdl_Pa_m"] * dh / (0.5 * rho * u**2)
    df["Nu"] = df["h_core_W_m2K"] * dh / k
    df["Pr"] = mu * df["cp_J_kgK"] / k

    if (df["dp_core_Pa"] <= 0).any() or (df["Q_core_W"] <= 0).any():
        n = int(((df["dp_core_Pa"] <= 0) | (df["Q_core_W"] <= 0)).sum())
        raise ValueError(f"{n} core rows with non-positive dp or Q — "
                         f"upstream extraction problem, inspect before use.")
    _log.info(f"load_core[{lattice}]: {len(df)} cases, "
              f"{df['geometry_id'].nunique()} geometries, "
              f"P {sorted(df['P_MPa'].unique())} MPa")
    return df


def load_segments(lattice: str = "Diamond",
                  drop_entrance: bool = True, *, source=None) -> pd.DataFrame:
    """Per-period rows with LOCAL bulk / wall properties (CoolProp).

    Local reduction (standard variable-property convention):
        T_b     = (Tin + Tout)/2         (segment ΔT is a few K; the
                  arithmetic mean vs enthalpy mean difference is below the
                  plane-averaging noise at this slice length)
        rho_b, mu_b, cp_b, k_b, Pr_b  at (T_b, P)
        Re_b    = G · Dh / mu_b          (G from the case's mdot/A_flow)
        Nu_b    = h_seg · Dh / k_b
        rho_w, mu_w, k_w  at (Twall, P)
        cp_bar  = (h(Twall) − h(T_b)) / (Twall − T_b)   [Jackson integrated cp]

    Identifiability caveat (fit scripts rely on this): Twall − Tref is 50 K
    for EVERY case, so wall/bulk property ratios are near-deterministic
    functions of the bulk state — log(k_w/k_b) and log(rho_w/rho_b)
    correlate −1.00 / −0.97 with log(Pr_b). Only mu_w/mu_b (corr −0.69)
    carries usable independent signal; any fitted wall-ratio exponent is
    conditional on ΔT ≈ 50 K until a ΔT sweep is uploaded.

    drop_entrance: drop period-1 slices (entrance-affected, see module doc).
    """
    from CoolProp.CoolProp import PropsSI

    if lattice not in LATTICES:
        raise ValueError(f'lattice must be one of {LATTICES}, got {lattice!r}')
    seg = pd.read_csv(_resolve_csv(lattice, "seg") if source is None else source)
    seg = _attach_pressure(seg)
    _verify_rho_guard(seg)
    seg = _attach_geometry(seg, lattice)
    seg = seg.rename(columns={"Re": "Re_nominal"})
    seg["tpms"] = lattice

    if drop_entrance:
        seg = seg[seg["segment"] != ENTRANCE_SEGMENT].reset_index(drop=True)

    # case-level mass flux with reference properties (G is x-independent)
    seg["A_flow_m2"] = seg["mdot_in_kg_s"] / (seg["rho_kg_m3"] * seg["Um_m_s"])
    seg["G_kg_m2s"] = seg["mdot_in_kg_s"] / seg["A_flow_m2"]

    T_b = 0.5 * (seg["Tin_K"] + seg["Tout_K"])
    P = seg["P_Pa"].to_numpy()
    seg["T_b_K"] = T_b
    tb = T_b.to_numpy()
    tw = seg["Twall_K"].to_numpy()
    seg["rho_b"] = PropsSI("D", "T", tb, "P", P, "CO2")
    seg["mu_b"] = PropsSI("V", "T", tb, "P", P, "CO2")
    seg["cp_b"] = PropsSI("C", "T", tb, "P", P, "CO2")
    seg["k_b"] = PropsSI("L", "T", tb, "P", P, "CO2")
    seg["Pr_b"] = seg["mu_b"] * seg["cp_b"] / seg["k_b"]
    seg["rho_w"] = PropsSI("D", "T", tw, "P", P, "CO2")
    seg["mu_w"] = PropsSI("V", "T", tw, "P", P, "CO2")
    seg["k_w"] = PropsSI("L", "T", tw, "P", P, "CO2")
    h_b = PropsSI("H", "T", tb, "P", P, "CO2")
    h_w = PropsSI("H", "T", tw, "P", P, "CO2")
    seg["cp_bar"] = (h_w - h_b) / (tw - tb)

    dh = seg["Dh_m"]
    seg["Re_b"] = seg["G_kg_m2s"] * dh / seg["mu_b"]
    seg["Nu_b"] = seg["h_W_m2K"] * dh / seg["k_b"]
    seg["dpdl_Pa_m"] = seg["dp_Pa"] / (seg["x_start_mm"]
                                       - seg["x_end_mm"]).abs() * 1e3

    _log.info(f"load_segments[{lattice}]: {len(seg)} rows "
              f"({'periods 2-3' if drop_entrance else 'all periods'}), "
              f"Re_b [{seg['Re_b'].min():.0f}, {seg['Re_b'].max():.0f}], "
              f"Pr_b [{seg['Pr_b'].min():.2f}, {seg['Pr_b'].max():.2f}]")
    return seg


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    for _lat in LATTICES:
        core = load_core(_lat)
        print(f"[{_lat}] core: {len(core)} cases")
        print(core.groupby("geometry_id")
              .agg(n=("Re", "size"), Re_min=("Re", "min"),
                   Re_max=("Re", "max"),
                   f_med=("f", "median"), Nu_med=("Nu", "median"),
                   eps=("eps", "first"),
                   Dh_mm=("Dh_m", lambda s: s.iloc[0] * 1e3))
              .round(3).to_string())
        segs = load_segments(_lat)
        print(f"[{_lat}] segments (periods 2-3): {len(segs)} rows")
        print()
