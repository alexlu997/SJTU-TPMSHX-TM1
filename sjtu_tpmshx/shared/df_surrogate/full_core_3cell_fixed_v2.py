"""Geometry-only Darcy--Forchheimer data from the native fixed CFD table."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from sjtu_tpmshx.shared.models import _native_df

METHOD = "cfd_full_core_3cell_fixed_v2"
TABLE_PATH = Path(__file__).parent / "_prebuilt" / f"{METHOD}.csv"


class FullCore3CellFixedDFV2:
    """Keep the fixed model interface and use the native table owner."""

    def __init__(self, tpms: str):
        if tpms not in ('Diamond', 'Gyroid'):
            raise ValueError('fixed sCO2 CFD coefficients support Diamond/Gyroid only')
        self.tpms = tpms

    def predict(self, L_mm: float, t_mm: float, eps_f: float | None = None) -> tuple[float, float]:
        del eps_f
        try:
            length, wall = float(L_mm), float(t_mm)
        except ValueError as failure:
            raise ValueError('geometry is outside the fixed sCO2 CFD grid: '
                             '4 <= L <= 8 mm and 0.3 <= t <= 0.6 mm') from failure
        k, f = _native_df.fixed(self.tpms, length, wall)
        return float(k), float(f)

    def predict_batch(self, L_mm, t_mm):
        """Evaluate matching arrays through the native interpolation owner."""
        lengths, walls = np.broadcast_arrays(np.asarray(L_mm, dtype=float), np.asarray(t_mm, dtype=float))
        return _native_df.fixed(self.tpms, lengths, walls)


__all__ = ['FullCore3CellFixedDFV2', 'METHOD', 'TABLE_PATH']
