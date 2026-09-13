"""Geometry-only Darcy--Forchheimer coefficients from water+sCO2 CFD."""

from __future__ import annotations

import csv
from bisect import bisect_left
from math import isfinite
from pathlib import Path


METHOD = "cfd_full_core_3cell_fixed_v2"
TABLE_PATH = Path(__file__).parent / "_prebuilt" / f"{METHOD}.csv"
_TOPOLOGIES = ("Diamond", "Gyroid")
from ._domain import TRAIN_L_NODES as _L_NODES, TRAIN_T_NODES as _T_NODES


def _load_table() -> dict[str, dict[tuple[float, float], tuple[float, float]]]:
    tables = {topology: {} for topology in _TOPOLOGIES}
    with TABLE_PATH.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        required = {"tp", "L_mm", "t_mm", "K_m2", "cF_fixed_1_m"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("fixed sCO2 CFD coefficient schema mismatch")
        for row in reader:
            topology = row["tp"]
            if topology not in tables:
                raise ValueError(f"unsupported TPMS topology: {topology!r}")
            key = (float(row["L_mm"]), float(row["t_mm"]))
            values = (float(row["K_m2"]), float(row["cF_fixed_1_m"]))
            if key in tables[topology]:
                raise ValueError(f"duplicate fixed sCO2 CFD node: {topology} {key}")
            if key[0] not in _L_NODES or key[1] not in _T_NODES:
                raise ValueError(f"off-grid fixed sCO2 CFD node: {topology} {key}")
            if not all(isfinite(value) and value > 0.0 for value in values):
                raise ValueError(f"invalid fixed sCO2 CFD coefficients: {topology} {key}")
            tables[topology][key] = values

    expected = {(L_mm, t_mm) for L_mm in _L_NODES for t_mm in _T_NODES}
    if any(set(table) != expected for table in tables.values()):
        raise ValueError("fixed sCO2 CFD coefficient grid is incomplete")
    return tables


_TABLE = _load_table()


def _bracket(value: float, nodes: tuple[float, ...]) -> tuple[float, float, float]:
    value = float(value)
    tol = 1e-12 * max(1.0, abs(value))
    if value < nodes[0] - tol or value > nodes[-1] + tol:
        raise ValueError
    value = min(max(value, nodes[0]), nodes[-1])
    upper = bisect_left(nodes, value)
    if upper < len(nodes) and abs(value - nodes[upper]) <= tol:
        return nodes[upper], nodes[upper], 0.0
    lower = upper - 1
    lo, hi = nodes[lower], nodes[upper]
    return lo, hi, (value - lo) / (hi - lo)


class FullCore3CellFixedDFV2:
    """Return node values or bilinear ``(L, t)`` interpolation within the CFD grid."""

    def __init__(self, tpms: str):
        if tpms not in _TABLE:
            raise ValueError("fixed sCO2 CFD coefficients support Diamond/Gyroid only")
        self.tpms = tpms

    def predict(
        self, L_mm: float, t_mm: float, eps_f: float | None = None
    ) -> tuple[float, float]:
        del eps_f
        try:
            L0, L1, wL = _bracket(L_mm, _L_NODES)
            t0, t1, wt = _bracket(t_mm, _T_NODES)
        except ValueError as exc:
            raise ValueError(
                "geometry is outside the fixed sCO2 CFD grid: "
                "4 <= L <= 8 mm and 0.3 <= t <= 0.6 mm"
            ) from exc

        table = _TABLE[self.tpms]
        result = []
        for index in (0, 1):
            at_t0 = ((1.0 - wL) * table[L0, t0][index]
                     + wL * table[L1, t0][index])
            at_t1 = ((1.0 - wL) * table[L0, t1][index]
                     + wL * table[L1, t1][index])
            result.append((1.0 - wt) * at_t0 + wt * at_t1)
        return result[0], result[1]


__all__ = ["FullCore3CellFixedDFV2", "METHOD", "TABLE_PATH"]
