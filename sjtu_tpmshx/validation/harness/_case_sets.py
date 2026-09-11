"""Canonical validation case sets: specimen specs + truth-table locations.

Single source for "which specimen, which workbook, which cases" so validation
runners cannot drift apart on geometry or column conventions (refactor B1 1.3).
"""
from __future__ import annotations

from pathlib import Path

from sjtu_tpmshx.validation.harness._harness import SpecimenSpec

_PKG_ROOT = Path(__file__).resolve().parent.parent.parent     # sjtu_tpmshx/
_DATA = _PKG_ROOT.parent / 'data' / 'raw_data'

SHANGHAI_XLSX = _DATA / '20260401-上海电气天然气加热器实验工况.xlsx'
SHANGHAI_N_CASES = 16

D76_XLSX = _DATA / '20260609-水直空气侧-D_7_6.xlsx'
D76_N_CASES = 18
# Case index 11: duplicated sensor block (= case 10's T/P columns),
# verified 2026-06-11 — excluded from the dP gate.
D76_EXCLUDE = frozenset({11})


def shanghai_spec() -> SpecimenSpec:
    """Shanghai Electric gas-heater specimen, from the canonical baseline
    JSON (configs/shanghai_baseline.json, audit Item 3 / AR8)."""
    from sjtu_tpmshx.configs import load_shanghai_baseline
    from sjtu_tpmshx.domain.compute_config import ComputeConfig
    sh = load_shanghai_baseline()
    cc = ComputeConfig.from_dict(sh)
    return SpecimenSpec(
        name='shanghai',
        tpms=cc.geometry.tpms,
        L_cell_mm=cc.geometry.L_cell_mm,
        t_wall_mm=cc.geometry.t_wall_mm,
        k_s_W_mK=cc.geometry.k_s_W_mK,
        L_dom_m=cc.geometry.L_dom_m,
        H_dom_m=cc.geometry.H_dom_m,
        Lz_m=cc.geometry.Lz_m,
        a_flow_m2=(sh['domain']['n_units']
                   * sh['domain']['a_flow_per_unit_m2']),
    )


def d76_spec() -> SpecimenSpec:
    """D_7_6 specimen (Diamond L=7 t=0.6, SLM) — same domain architecture
    as Shanghai; frontal flow area = void fraction x 36 cells x (7 mm)^2.

    NOTE (B1 bug fix, 2026-06-12): the retired ``_patch_to_d76`` global
    patch never reached frozen helper defaults, so the d76 gate had been
    computing h_vA with SHANGHAI (Gyroid) eps/D_h/L_cell. With the spec
    passed explicitly the gate now uses true Diamond geometry — its
    reference numbers move accordingly (re-baselined in the B1 PR).
    """
    sh = shanghai_spec()        # domain dims are shared with Shanghai
    from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry
    g = tpms_geometry('Diamond', 7.0, 0.6, 16.0)
    return SpecimenSpec(
        name='d76',
        tpms='Diamond',
        L_cell_mm=7.0,
        t_wall_mm=0.6,
        k_s_W_mK=16.0,
        L_dom_m=sh.L_dom_m,
        H_dom_m=sh.H_dom_m,
        Lz_m=sh.Lz_m,
        a_flow_m2=g['epsilon_A'] * 36 * 49e-6,
    )
