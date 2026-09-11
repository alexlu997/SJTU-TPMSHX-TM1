"""Canonical `_run_3d_stack` cfg template (B2 2.6, 2026-06-13).

Five runs/ scripts each hand-rolled the same cfg dict (demo_3d_air_air,
demo_3d_cube_air_air, demo_3d_cube_volume, diag_ab_imbal,
smoke_ui_3d_modes) — a changed default geometry never reached the demos.
This is the single template; scripts pass only their deltas.

NOT used by runs/_out/_golden_3d.py — the golden gate stays
self-contained on purpose (a gate must not share code with the code
under test).

Defaults mirror the demo/cube family: Gyroid 7.0/0.5, hot air A
(+x, 422 K, 192 362 Pa abs) vs cold air B (-y crossflow, 293.15 K,
atmospheric), full-face inlet/outlet on both sides, Shanghai domain
0.182 x 0.042 x 0.042 m.
"""
from __future__ import annotations

from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry


def build_cfg(*, tpms_type: str = 'Gyroid', Lcell: float = 7.0,
              t_wall: float = 0.5, k_s: float = 16.0,
              L: float = 0.182, H: float = 0.042, Lz: float = 0.042,
              Nx: int = 30, Ny: int = 20, Nz: int = 5,
              u_A: float = 20.0, T_inA: float = 422.0,
              P_inA: float = 192362.0,
              u_B: float = 10.0, T_inB: float = 293.15,
              P_inB: float = 101325.0,
              fluid_type_A: str = 'air', fluid_type_B: str = 'air',
              T_s_init: float | None = None,
              fluid_A_cfg: dict | None = None,
              fluid_B_cfg: dict | None = None,
              **overrides) -> dict:
    """One canonical cfg for ``pipelines.stages_3d._run_3d_stack``.

    ``fluid_A_cfg`` / ``fluid_B_cfg`` default to full-face +x / -y
    crossflow derived from (L, H); pass a dict to override (partial BC).
    Any extra keyword lands verbatim in the cfg (``sweep_profile``,
    ``partial_B_closure``, accel flags, …).
    """
    g = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
    cfg = dict(
        L=L, H=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        u_A=u_A, u_B=u_B,
        T_inA=T_inA, T_inB=T_inB,
        P_inA=P_inA, P_inB=P_inB,
        T_s_init=T_s_init,
        Lcell=Lcell, t_wall=t_wall, k_s=k_s,
        tpms_type=tpms_type,
        eps=g['epsilon'], D_h=g['D_h'],
        fluid_A_cfg=(fluid_A_cfg if fluid_A_cfg is not None else
                     dict(dir=0, in_ctr=H / 2, in_w=H,
                          out_ctr=H / 2, out_w=H)),
        fluid_B_cfg=(fluid_B_cfg if fluid_B_cfg is not None else
                     dict(dir=3, in_ctr=L / 2, in_w=L,
                          out_ctr=L / 2, out_w=L)),
        wall_refine_3d=False,
        zone_grid_cells=None,
        fluid_type_A=fluid_type_A, fluid_type_B=fluid_type_B,
    )
    cfg.update(overrides)
    return cfg
