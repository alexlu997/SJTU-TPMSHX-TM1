"""
Load the air experiment reference used for experimental correction.

Output DataFrame schema:
    tpms    : 'Diamond' | 'Gyroid'
    L_mm    : unit cell size [mm]
    t_mm    : wall thickness [mm]
    eps     : full porosity ε (from tpms_calc.geometry)
    eps_f   : single-channel porosity ε/2
    r_h_m   : hydraulic radius D_h/2 [m]
    Re      : Reynolds number (Excel column "Re", kept for reference/filtering)
    u_mps   : velocity [m/s] (Excel column 13, 速度 — 工况速度)
    dP_Pa   : 摩擦压损 friction ΔP [Pa] (Excel column 47). **实验侧** —
              = col43 Pressureloss_TPMS (实验总 ΔP 去入口效应) × (转折f/f)
              friction 隔离因子. 表为实验台架 (电加热 I/V/功率 + 实测流量/
              温度/压损); CFD (col27-35, col44 P_Exp/P_CFD) 仅并列对照, 非 fit 基.
              旧注误称 "修正压损 / CFD corrected" (2026-06-05 核实纠正).
    rho     : fluid density [kg/m³] (Excel column 12)
    mu      : fluid dynamic viscosity [Pa·s] (Excel column 9)

Friction factor is intentionally NOT computed — downstream D-F extraction
fits the momentum equation ``dP = (μ/K · u + ρ·c_F · u²) · L_channel``
directly on these raw columns. The 修正压损 column is the single source
of truth for pressure loss.

Only the training Excel is used; Shanghai data is deliberately excluded.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# Locate sjtu_tpmshx root for data paths and solvers package
_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent  # .../sjtu_tpmshx
from sjtu_tpmshx.models.tpms_props import geometry as tpms_geometry  # noqa: E402
from sjtu_tpmshx.logutil import get_logger  # noqa: E402

_log = get_logger(__name__)

DATA_XLSX = _PROJECT_ROOT.parent / "data" / "raw_data" / 'experiments/air/air_DG_specimen_experiment_summary.xlsx'

# Sheet names (GBK 汇总)
_SHEETS = {"Diamond": "Diamond_汇总", "Gyroid": "Gyroid_汇总"}

# Column indices in the sheet (0-based, confirmed from header inspection)
_COL_LABEL = 0   # e.g. 'D_8_03'
_COL_L = 1       # L/mm
_COL_T = 2       # t/mm
_COL_RE = 3      # Re
_COL_MU = 9      # 动力粘度 Pa·s
_COL_RHO = 12    # 密度 kg/m³
_COL_U = 13      # 速度 m/s
_COL_DP_CORR = 47  # 摩擦压损 friction ΔP (入口已除; 旧注误称"修正压损/CFD") — single source of truth

# Re filter: for L=8 mm geometries only, drop rows with Re < _L8_RE_MIN.
# Rationale: in the L=8 region the low-Re samples live in the transition
# regime where the 2-parameter D-F form f = A/Re + B is systematically off,
# and the report's unconstrained fit for Diamond 8/0.3 + Gyroid 8×{0.3,0.4,0.5}
# gave A < 0. Focusing on Re >= 1600 concentrates the fit on the Forchheimer
# branch where both A and B are well-conditioned.
_L8_RE_MIN = 1600.0

# Default k_s used when calling tpms_calc.geometry() — only affects K_ss, not
# ε or D_h which are the only fields we consume here.
_K_S_DEFAULT = 16.0


def _load_sheet(tpms: str, *, source=None) -> pd.DataFrame:
    """Load one TPMS type sheet from the training Excel and return a tidy frame.

    Header rows (row 0 = labels, row 1 = first group divider) and all group
    divider rows (L column is None) are stripped.
    """
    sheet = _SHEETS[tpms]
    raw = pd.read_excel(
        DATA_XLSX if source is None else source,
        sheet_name=sheet,
        engine="openpyxl",
        header=None,
        skiprows=1,  # skip header row 0
    )

    # Keep only rows with numeric L (filters out group divider rows)
    L_col = pd.to_numeric(raw.iloc[:, _COL_L], errors="coerce")
    mask = L_col.notna()

    df = pd.DataFrame(
        {
            "tpms": tpms,
            "label": raw.iloc[:, _COL_LABEL][mask].astype(str).values,
            "L_mm": L_col[mask].astype(float).values,
            "t_mm": pd.to_numeric(raw.iloc[:, _COL_T], errors="coerce")[mask]
            .astype(float)
            .values,
            "Re": pd.to_numeric(raw.iloc[:, _COL_RE], errors="coerce")[mask]
            .astype(float)
            .values,
            "u_mps": pd.to_numeric(raw.iloc[:, _COL_U], errors="coerce")[mask]
            .astype(float)
            .values,
            "dP_Pa": pd.to_numeric(raw.iloc[:, _COL_DP_CORR], errors="coerce")[mask]
            .astype(float)
            .values,
            "rho": pd.to_numeric(raw.iloc[:, _COL_RHO], errors="coerce")[mask]
            .astype(float)
            .values,
            "mu": pd.to_numeric(raw.iloc[:, _COL_MU], errors="coerce")[mask]
            .astype(float)
            .values,
        }
    )

    # Drop any rows where critical columns failed to parse
    df = df.dropna(subset=["Re", "u_mps", "dP_Pa", "rho", "mu"]).reset_index(drop=True)

    # L=8 mm: drop low-Re rows (see _L8_RE_MIN rationale above)
    n_before = len(df)
    l8_mask = (df["L_mm"] == 8.0) & (df["Re"] < _L8_RE_MIN)
    if l8_mask.any():
        df = df[~l8_mask].reset_index(drop=True)
        _log.info(f"  [{tpms}] dropped {n_before - len(df)} L=8 rows with Re < {_L8_RE_MIN:g}")

    return df


def _attach_geometry(df: pd.DataFrame) -> pd.DataFrame:
    """Add eps, eps_f, r_h_m columns computed from tpms_calc.geometry.

    Geometry is cached per (tpms, L, t) triple so we only pay the voxel
    integration cost once per geometry.
    """
    cache: dict[tuple[str, float, float], tuple[float, float]] = {}

    eps = np.empty(len(df))
    rh = np.empty(len(df))
    for i, row in df.iterrows():
        key = (row["tpms"], float(row["L_mm"]), float(row["t_mm"]))
        if key not in cache:
            g = tpms_geometry(key[0], key[1], key[2], _K_S_DEFAULT)
            cache[key] = (float(g["epsilon"]), float(g["D_h"]) / 2.0)
        e, r = cache[key]
        eps[i] = e
        rh[i] = r

    out = df.copy()
    out["eps"] = eps
    out["eps_f"] = eps / 2.0   # ε_A: per-stream void fraction (sheet HX)
    out["r_h_m"] = rh
    return out[[
        "tpms", "L_mm", "t_mm", "eps", "eps_f", "r_h_m",
        "Re", "u_mps", "dP_Pa", "rho", "mu", "label",
    ]]


# Shanghai geometry — never appears in training. Used by
# _assert_no_shanghai_leakage to fail loudly if anyone accidentally points
# DATA_XLSX at a validation file or a future merge contaminates the
# training sheets. See vault/reports/shanghai-validation/ for context.
_SHANGHAI_GEOMETRY = (7.0, 0.6)   # (L_mm, t_mm)
_SHANGHAI_PATH_KEYWORDS = ('shanghai', '上海')


def _assert_no_shanghai_leakage(df: pd.DataFrame, *, source=None) -> None:
    """Raise ValueError if the loaded training set contains Shanghai data.

    Three independent checks (any one tripping is a hard failure):

    1. ``DATA_XLSX`` filename — no ``shanghai`` / ``上海`` substring.
    2. No row with ``t_mm == 0.6`` (Shanghai's unique wall thickness;
       training uses {0.3, 0.4, 0.5} only).
    3. No row with ``L_mm == 7.0`` (Shanghai's unique cell size;
       training uses {4, 5, 6, 8} only).

    Keep the air specimen training set independent of Shanghai HX validation.
    Leakage would turn the comparison into an in-sample fit; historical
    validation scores are not acceptance evidence for the current model.
    """
    source = DATA_XLSX if source is None else source
    src = str(source).lower()
    for kw in _SHANGHAI_PATH_KEYWORDS:
        if kw.lower() in src:
            raise ValueError(
                f"DATA_XLSX path contains Shanghai keyword {kw!r}: "
                f"{source!s} — training set must come from "
                f"air_DG_specimen_experiment_summary.xlsx, never a Shanghai workbook.")
    L_sh, t_sh = _SHANGHAI_GEOMETRY
    if (df['t_mm'] == t_sh).any():
        rows = df[df['t_mm'] == t_sh]
        raise ValueError(
            f"Training set contains {len(rows)} rows with t_mm={t_sh} mm "
            f"— this matches the Shanghai validation thickness. "
            f"Likely leakage from a Shanghai workbook. "
            f"Affected geometries: "
            f"{sorted(set(zip(rows['tpms'], rows['L_mm'])))}")
    if (df['L_mm'] == L_sh).any():
        rows = df[df['L_mm'] == L_sh]
        raise ValueError(
            f"Training set contains {len(rows)} rows with L_mm={L_sh} mm "
            f"— this matches the Shanghai cell size. Likely leakage. "
            f"Affected geometries: "
            f"{sorted(set(zip(rows['tpms'], rows['t_mm'])))}")


def load_all(*, source=None) -> pd.DataFrame:
    """Load and combine Diamond + Gyroid training data with geometry attached.

    Preserve the independent Shanghai holdout boundary when deriving air
    experimental corrections from these records. The production base D-F
    model uses the separate fixed water+sCO2 CFD table.
    """
    frames = [_attach_geometry(_load_sheet(tpms, source=source)) for tpms in _SHEETS]
    df = pd.concat(frames, ignore_index=True)
    _assert_no_shanghai_leakage(df, source=source)
    return df
