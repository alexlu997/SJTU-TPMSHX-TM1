"""Project-wide configuration loaders.

The ``configs`` package centralises parameter dicts that were previously
hardcoded across multiple production scripts. Per audit Item 3 / AR8
(vault/reports/engineering/2026-05-28-sjtu-tpmshx-4-perspective-audit-CN.html).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_THIS_DIR = Path(__file__).resolve().parent


def load_shanghai_baseline() -> dict[str, Any]:
    """Return the canonical Shanghai 16-case baseline parameters.

    Shared by Shanghai validation tools. Individual diagnostic tools may
    declare their own geometry and pressure conventions; this resource
    does not override those inputs.

    Returns
    -------
    dict with keys:
        '_meta'      — provenance and canonical date
        'geometry'   — tpms / L_cell_mm / t_wall_mm / k_s_W_mK
        'domain'     — L_dom_m / H_dom_m / Lz_m / n_units / a_flow_per_unit_m2

    Examples
    --------
    >>> cfg = load_shanghai_baseline()
    >>> cfg['geometry']['L_cell_mm']
    7.0
    >>> cfg['domain']['L_dom_m']
    0.182
    """
    path = _THIS_DIR / "shanghai_baseline.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


__all__ = ["load_shanghai_baseline"]
