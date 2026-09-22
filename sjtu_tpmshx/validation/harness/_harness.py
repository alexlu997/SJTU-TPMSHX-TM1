"""Shared experimental workbook loading and Shanghai specimen geometry.

The former D76 global-patching workaround is retired with the frozen-water
runner. Current callers use the canonical baseline specimen explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from sjtu_tpmshx.models.tpms_calc import geometry as _tpms_geometry


@dataclass(frozen=True)
class SpecimenSpec:
    """One physical HX specimen: input geometry + derived TPMS properties.

    Derived full and A-side porosities are computed once from
    ``tpms_calc.geometry`` at construction; they exist so validation
    runners never re-derive (or worse, freeze) them locally.
    """
    name: str
    tpms: str
    L_cell_mm: float
    t_wall_mm: float
    k_s_W_mK: float
    L_dom_m: float
    H_dom_m: float
    Lz_m: float
    a_flow_m2: float
    # ── derived (filled in __post_init__) ──
    eps: float = field(init=False)
    eps_A: float = field(init=False)

    def __post_init__(self):
        g = _tpms_geometry(self.tpms, self.L_cell_mm, self.t_wall_mm,
                           self.k_s_W_mK)
        object.__setattr__(self, 'eps', g['epsilon'])
        object.__setattr__(self, 'eps_A', g['epsilon_A'])


def load_cases_df(xlsx_path: Path) -> pd.DataFrame:
    """Load an experimental-case workbook in the project's canonical shape.

    All validation truth tables (Shanghai 16-case, D_7_6) share one layout:
    Sheet1, two header rows skipped, positional ``iloc`` column access.
    """
    from sjtu_tpmshx.validation.water_exp import (
        WATER_EXPERIMENT_BOOKS, with_water_absolute_pressures)
    d = pd.read_excel(xlsx_path, engine='openpyxl', sheet_name='Sheet1',
                      header=None, skiprows=2)
    if xlsx_path.name in WATER_EXPERIMENT_BOOKS - {'water-air_DG7-t0p6_hx_water-dp_with-air-temperature.xlsx'}:
        # Rows after the last case ID contain sensor corrections, not cases.
        # Keep interior gaps and incomplete cases for the existing validation.
        d = d.loc[:d[0].last_valid_index()].copy()
        d = with_water_absolute_pressures(
            d, source=xlsx_path, sheet='Sheet1', tin=24, tout=25, pin=26, pout=27)
    return d
