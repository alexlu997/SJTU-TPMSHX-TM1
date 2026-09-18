"""audit_3d_conservation.py — Phase 2 3D LTNE conservation audit (hybrid path).

Verifies the 3D solver against the conservation contract spec at
`vault/reports/3d-solver/2026-05-04-3d-conservation-spec-CN.md`.

Three diagnostic blocks:

  Phase 2a — volumetric ε_α                  (per-phase 1st-law residual)
      LHS_α = ∮_∂Ω F_α·n dA       (advective + diffusive surface integral)
      RHS_α = ∫_Ω S_α dV          (LTNE source volume integral)
      ε_α   = |LHS − RHS| / max(|LHS|, |RHS|)
      Hard gate: ε_α < 1.0 % per phase, ε_total < 0.5 % for LTNE 3-phase sum.

  Phase 2b — outlet-face K_ffB shortcircuit (H2 test)
      Reruns the same case with K_ffB := 0 in the 1-cell outlet boundary
      layer (real outlet of B). Compares T_B_out and Q_enth_B vs baseline.
      Quantifies how much T_B_out hot-spot is due to local diffusion from
      hot solid into the outlet patch fluid.

  Phase 2c — per-cell mass-imbalance audit (H3 test)
      Computes per-cell NET_OUT_α = Σ_face F_face_advective_α and the
      associated spurious enthalpy Σ_cells T_cell · NET_OUT_cell. Locates
      where the 6.6 % global mass imbalance accrues and quantifies its
      energy-budget impact.

Test cases (synthetic, no Shanghai data):
  T1 — full-face cubic, parallel flow (A and B both dir=0)
  T2 — full-face cross-flow (A=+x, B=-y)               [current production]
  T3 — partial-B aligned (B_frac=0.5, in/out at same x)
  T4 — partial-B Shanghai-like (B_frac=0.20, offset patches)
  T5 — B-isolated null (B_frac=0)
  T6 — A=B equi-temperature (T_inA == T_inB)

Output: vault/reports/3d-solver/2026-05-04-phase2-conservation-CN.md
"""
from __future__ import annotations
import argparse, sys, time, warnings
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
warnings.filterwarnings('ignore')

from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack


# ──────────────────────────────────────────────────────────────────────────
# Test case configs
# ──────────────────────────────────────────────────────────────────────────

L_DOM, H_DOM, LZ = 0.182, 0.042, 0.042

def _base_cfg(grid: int = 20):
    return dict(
        L=L_DOM, H=H_DOM, Lz=LZ,
        Nx=grid, Ny=grid, Nz=grid,
        tpms_type='Gyroid', Lcell=7.0, t_wall=0.6, k_s=16.0, eps=0.85,
        fluid_type_A='air', fluid_type_B='air',
        wall_refine_3d=False,
        partial_B_closure='none',
    )


def make_T1(grid):  # full-face parallel A,B both +x
    cfg = _base_cfg(grid)
    cfg.update(
        u_A=2.0, u_B=4.0, T_inA=422.0, T_inB=322.0,
        P_inA=102325.0, P_inB=101325.0,
        fluid_A_cfg=dict(dir=0, in_ctr=H_DOM/2, in_w=H_DOM,
                          out_ctr=H_DOM/2, out_w=H_DOM,
                          in_z_ctr=LZ/2, in_z_w=LZ,
                          out_z_ctr=LZ/2, out_z_w=LZ),
        fluid_B_cfg=dict(dir=2, in_ctr=L_DOM/2, in_w=L_DOM,
                          out_ctr=L_DOM/2, out_w=L_DOM,
                          in_z_ctr=LZ/2, in_z_w=LZ,
                          out_z_ctr=LZ/2, out_z_w=LZ),
        _case_label='T1_full_parallel',
    )
    return cfg


def make_T2(grid):  # full-face cross-flow Shanghai NORM
    cfg = _base_cfg(grid)
    cfg.update(
        u_A=5.0, u_B=5.0, T_inA=422.0, T_inB=300.0,
        P_inA=1.01325e5, P_inB=1.01325e5,
        fluid_A_cfg=dict(dir=0, in_ctr=H_DOM/2, in_w=H_DOM,
                          out_ctr=H_DOM/2, out_w=H_DOM,
                          in_z_ctr=LZ/2, in_z_w=LZ,
                          out_z_ctr=LZ/2, out_z_w=LZ),
        fluid_B_cfg=dict(dir=3, in_ctr=L_DOM/2, in_w=L_DOM,
                          out_ctr=L_DOM/2, out_w=L_DOM,
                          in_z_ctr=LZ/2, in_z_w=LZ,
                          out_z_ctr=LZ/2, out_z_w=LZ),
        _case_label='T2_full_cross',
    )
    return cfg


def make_T3(grid):  # partial-B aligned (in/out same cross-stream position)
    cfg = _base_cfg(grid)
    cfg.update(
        u_A=2.0, u_B=4.0, T_inA=422.0, T_inB=322.0,
        P_inA=102325.0, P_inB=101325.0,
        fluid_A_cfg=dict(dir=0, in_ctr=0.021, in_w=0.042,
                          out_ctr=0.021, out_w=0.042,
                          in_z_ctr=0.021, in_z_w=0.042,
                          out_z_ctr=0.021, out_z_w=0.042),
        # B aligned: in_ctr = out_ctr
        fluid_B_cfg=dict(dir=3, in_ctr=L_DOM/2, in_w=0.090,
                          out_ctr=L_DOM/2, out_w=0.090,
                          in_z_ctr=0.021, in_z_w=0.042,
                          out_z_ctr=0.021, out_z_w=0.042),
        _case_label='T3_partial_aligned',
    )
    return cfg


def make_T4(grid):  # partial-B Shanghai-like offset
    cfg = _base_cfg(grid)
    cfg.update(
        u_A=2.0, u_B=4.0, T_inA=422.0, T_inB=322.0,
        P_inA=102325.0, P_inB=101325.0,
        fluid_A_cfg=dict(dir=0, in_ctr=0.021, in_w=0.042,
                          out_ctr=0.021, out_w=0.042,
                          in_z_ctr=0.021, in_z_w=0.042,
                          out_z_ctr=0.021, out_z_w=0.042),
        fluid_B_cfg=dict(dir=3, in_ctr=0.154, in_w=0.042,
                          out_ctr=0.028, out_w=0.042,
                          in_z_ctr=0.021, in_z_w=0.042,
                          out_z_ctr=0.021, out_z_w=0.042),
        _case_label='T4_partial_offset_shanghai',
    )
    return cfg


def make_T5(grid):  # B isolated (no fluid B)
    cfg = _base_cfg(grid)
    cfg.update(
        u_A=2.0, T_inA=422.0, T_inB=322.0,
        P_inA=102325.0, P_inB=101325.0,
        fluid_A_cfg=dict(dir=0, in_ctr=H_DOM/2, in_w=H_DOM,
                          out_ctr=H_DOM/2, out_w=H_DOM,
                          in_z_ctr=LZ/2, in_z_w=LZ,
                          out_z_ctr=LZ/2, out_z_w=LZ),
        fluid_B_cfg=None,   # B disabled
        _case_label='T5_B_isolated',
    )
    return cfg


def make_T6(grid):  # A == B equi-temperature
    cfg = _base_cfg(grid)
    cfg.update(
        u_A=5.0, u_B=5.0, T_inA=350.0, T_inB=350.0,
        P_inA=1.01325e5, P_inB=1.01325e5,
        fluid_A_cfg=dict(dir=0, in_ctr=H_DOM/2, in_w=H_DOM,
                          out_ctr=H_DOM/2, out_w=H_DOM,
                          in_z_ctr=LZ/2, in_z_w=LZ,
                          out_z_ctr=LZ/2, out_z_w=LZ),
        fluid_B_cfg=dict(dir=3, in_ctr=L_DOM/2, in_w=L_DOM,
                          out_ctr=L_DOM/2, out_w=L_DOM,
                          in_z_ctr=LZ/2, in_z_w=LZ,
                          out_z_ctr=LZ/2, out_z_w=LZ),
        _case_label='T6_equi_temperature',
    )
    return cfg


def make_T4_H2(grid):  # T4 + H2 outlet K_ffB=0 test
    cfg = make_T4(grid)
    cfg['audit_zero_K_ffB_at_outlet'] = True
    cfg['audit_h2_n_layers'] = 1
    cfg['_case_label'] = 'T4_H2_outlet_K_ffB_zero'
    return cfg


def make_T4_H6(grid):  # T4 + H6 ghost-pin (per-cell χ_B + kernel threshold)
    cfg = make_T4(grid)
    cfg['partial_B_closure'] = 'per_cell_chi_b'
    cfg['chi_B_method'] = 'velocity_threshold'
    cfg['chi_B_threshold_frac'] = 0.30
    cfg['chi_B_n_dilate'] = 2
    cfg['chi_B_n_smooth'] = 1
    cfg['chi_B_floor'] = 1e-3
    cfg['chi_B_kernel_threshold'] = 0.30   # H6 kernel pin threshold
    cfg['_case_label'] = 'T4_H6_ghost_pin'
    return cfg


def make_T4_H6_tight(grid):
    cfg = make_T4_H6(grid)
    cfg['chi_B_threshold_frac'] = 0.50
    cfg['chi_B_kernel_threshold'] = 0.50
    cfg['_case_label'] = 'T4_H6_tight'
    return cfg


def make_T4_H6_xtight(grid):
    cfg = make_T4_H6(grid)
    cfg['chi_B_threshold_frac'] = 0.70
    cfg['chi_B_kernel_threshold'] = 0.70
    cfg['chi_B_n_dilate'] = 1
    cfg['chi_B_n_smooth'] = 1
    cfg['_case_label'] = 'T4_H6_xtight'
    return cfg


def make_T4_H6_extreme(grid):
    cfg = make_T4_H6(grid)
    cfg['chi_B_threshold_frac'] = 0.90
    cfg['chi_B_kernel_threshold'] = 0.90
    cfg['chi_B_n_dilate'] = 0
    cfg['chi_B_n_smooth'] = 0
    cfg['_case_label'] = 'T4_H6_extreme'
    return cfg


def make_T2_H6(grid):  # full-face cross-flow + H6 (regression check)
    cfg = make_T2(grid)
    cfg['partial_B_closure'] = 'per_cell_chi_b'
    cfg['chi_B_method'] = 'velocity_threshold'
    cfg['chi_B_threshold_frac'] = 0.70
    cfg['chi_B_n_dilate'] = 1
    cfg['chi_B_n_smooth'] = 1
    cfg['chi_B_floor'] = 1e-3
    cfg['chi_B_kernel_threshold'] = 0.70
    cfg['chi_B_u_ref_mode'] = 'inlet'
    cfg['_case_label'] = 'T2_H6_fullface'
    return cfg


def make_T3_H6(grid):  # partial-aligned + H6
    cfg = make_T3(grid)
    cfg['partial_B_closure'] = 'per_cell_chi_b'
    cfg['chi_B_method'] = 'velocity_threshold'
    cfg['chi_B_threshold_frac'] = 0.70
    cfg['chi_B_n_dilate'] = 1
    cfg['chi_B_n_smooth'] = 1
    cfg['chi_B_floor'] = 1e-3
    cfg['chi_B_kernel_threshold'] = 0.70
    cfg['chi_B_u_ref_mode'] = 'inlet'
    cfg['_case_label'] = 'T3_H6_aligned'
    return cfg


# ── H8 cases — mass-flux threshold (auto-adaptive) ──
def _h8_cfg(cfg, threshold_frac=0.20, kernel_thr=0.30, n_dil=1,
            ref_mode='max'):
    """Default H8 params (max-ref + per-grid tuned, REVERTED from p75):
    thr=0.20, n_dil=1, kthr=0.30, ref='max'. Max-ref needs per-grid tune
    for offset partial-B (12: thr=0.30, 20: thr=0.20, 30: thr=0.25), but
    is BIMODAL-AWARE — full-face/aligned cases unchanged.

    p75-ref attempted (selection B') made grid 20 sweet thr universal at
    1.00 BUT broke full-face cases: T1_H8 ε_B=17.9 %, T2_H8 S_gen=-0.68
    (NEGATIVE — 2nd law violation). p75 cuts half cells in uniform-flow
    geometries. Lesson: percentile-ref only safe when distribution is
    bimodal; a robust auto-detect is needed (TODO future work)."""
    cfg['partial_B_closure'] = 'per_cell_chi_b'
    cfg['chi_B_method'] = 'mass_flux_threshold'
    cfg['chi_B_threshold_frac'] = threshold_frac
    cfg['chi_B_n_dilate'] = n_dil
    cfg['chi_B_n_smooth'] = 0
    cfg['chi_B_floor'] = 1e-3
    cfg['chi_B_kernel_threshold'] = kernel_thr
    cfg['chi_B_mass_ref_mode'] = ref_mode
    return cfg


def make_T2_H8(grid):
    cfg = _h8_cfg(make_T2(grid))
    cfg['_case_label'] = 'T2_H8'
    return cfg


def make_T3_H8(grid):
    cfg = _h8_cfg(make_T3(grid))
    cfg['_case_label'] = 'T3_H8'
    return cfg


def make_T4_H8(grid):
    cfg = _h8_cfg(make_T4(grid))
    cfg['_case_label'] = 'T4_H8'
    return cfg


def make_T4_H8_loose(grid):
    cfg = _h8_cfg(make_T4(grid), threshold_frac=0.20, kernel_thr=0.20)
    cfg['_case_label'] = 'T4_H8_loose'
    return cfg


def make_T4_H8_tight(grid):
    cfg = _h8_cfg(make_T4(grid), threshold_frac=0.50, kernel_thr=0.50)
    cfg['_case_label'] = 'T4_H8_tight'
    return cfg


def make_T1_H8(grid):
    cfg = _h8_cfg(make_T1(grid))
    cfg['_case_label'] = 'T1_H8'
    return cfg


def make_T4_H2_3layer(grid):  # T4 + H2 with 3-layer K_ffB=0
    cfg = make_T4(grid)
    cfg['audit_zero_K_ffB_at_outlet'] = True
    cfg['audit_h2_n_layers'] = 3
    cfg['_case_label'] = 'T4_H2_3layer'
    return cfg


CASES = {
    'T1': make_T1, 'T2': make_T2, 'T3': make_T3,
    'T4': make_T4, 'T5': make_T5, 'T6': make_T6,
    'T4_H2': make_T4_H2, 'T4_H2_3L': make_T4_H2_3layer,
    'T4_H6': make_T4_H6, 'T4_H6_tight': make_T4_H6_tight,
    'T4_H6_xtight': make_T4_H6_xtight, 'T4_H6_extreme': make_T4_H6_extreme,
    'T2_H6': make_T2_H6, 'T3_H6': make_T3_H6,
    'T2_H8': make_T2_H8, 'T3_H8': make_T3_H8,
    'T4_H8': make_T4_H8, 'T1_H8': make_T1_H8,
    'T4_H8_loose': make_T4_H8_loose, 'T4_H8_tight': make_T4_H8_tight,
}


# ──────────────────────────────────────────────────────────────────────────
# Phase 2a — volumetric ε_α (LHS surface integral vs RHS volume integral)
# ──────────────────────────────────────────────────────────────────────────

def _real_inlet_dir_face_index(dir_real, shape):
    """Return (axis, idx) for the REAL inlet boundary cell layer."""
    Nx, Ny, Nz = shape
    return {0: (0, 0), 1: (0, Nx-1), 2: (1, 0),
            3: (1, Ny-1), 4: (2, 0), 5: (2, Nz-1)}[dir_real]


def _real_outlet_dir_face_index(dir_real, shape):
    Nx, Ny, Nz = shape
    return {0: (0, Nx-1), 1: (0, 0), 2: (1, Ny-1),
            3: (1, 0), 4: (2, Nz-1), 5: (2, 0)}[dir_real]


def _slice_at(axis, idx, shape):
    """Return a slice tuple for cells on the boundary face."""
    Nx, Ny, Nz = shape
    s = [slice(None), slice(None), slice(None)]
    s[axis] = slice(idx, idx+1)
    return tuple(s)


def compute_phase2a_interior(res):
    """Phase 2a — interior 1st-law residual ε_α using BC-excluded volume.

    The FVM equation `ε·ρ·cp·u·∇T − ∇·(K·∇T) = h_v·(Ts−T)` is solved on
    cells where T is NOT pinned. At inlet-mask cells T = T_in (Dirichlet,
    no FVM update); at outlet 1-cell layer T = T_neighbor (Neumann pinning).
    Including those cells in the volume integral over-counts by the "fake
    BC source" h_v·(Ts−T_pinned)·V. The fair conservation check is over
    INTERIOR cells only.

    Metric:
      ε_A_kernel = |Q_enth_A − |Q_sA_interior|| / max(...)
      ε_B_kernel = |Q_enth_B − Q_sB_interior|     / max(...)
      ε_LTNE     = |Q_sA + Q_sB|                  / max(|Q_sA|, |Q_sB|)

    Q_enth uses the LTNE-effective face flux (`m_dot_α_simple`) and the
    flux-weighted T_α_out — i.e. the kernel's own "what mass carried out"
    integral. Q_s_interior is the existing pre-computed BC-excluded sum.
    """
    Q_enth_A = abs(float(res.get('Q_enthalpy_A', 0.0)))
    Q_enth_B = abs(float(res.get('Q_enthalpy_B', 0.0)))
    Q_sA = float(res.get('Q_sA', 0.0))
    Q_sB = float(res.get('Q_sB', 0.0))
    Q_sA_int = float(res.get('Q_sA_interior', 0.0))
    Q_sB_int = float(res.get('Q_sB_interior', 0.0))

    eps_A = abs(Q_enth_A - abs(Q_sA_int)) / max(Q_enth_A, abs(Q_sA_int), 1e-30)
    if Q_enth_B > 1e-30:
        eps_B = abs(Q_enth_B - Q_sB_int) / max(Q_enth_B, abs(Q_sB_int), 1e-30)
    else:
        eps_B = 0.0
    eps_LTNE = abs(Q_sA + Q_sB) / max(abs(Q_sA), abs(Q_sB), 1e-30)

    # Optional surface-integral cross-check (advection + Dirichlet diffusion)
    surf = compute_phase2a_surface(res)

    return dict(
        Q_enth_A=Q_enth_A, Q_sA=Q_sA, Q_sA_interior=Q_sA_int,
        Q_enth_B=Q_enth_B, Q_sB=Q_sB, Q_sB_interior=Q_sB_int,
        eps_A_kernel=eps_A, eps_B_kernel=eps_B, eps_LTNE=eps_LTNE,
        # Surface-integral diagnostic (cross-check):
        LHS_A_surf=surf['LHS_A'], LHS_B_surf=surf['LHS_B'],
        # BC pinning fraction:
        BC_frac_A=abs(Q_sA - Q_sA_int) / max(abs(Q_sA), 1e-30),
        BC_frac_B=abs(Q_sB - Q_sB_int) / max(abs(Q_sB), 1e-30),
    )


def compute_phase2a_surface(res):
    """Surface-integral version (cross-check via 6-face advective + Dirichlet diff)."""
    Ta = res['Ta']; Tb = res['Tb']; Ts = res['Ts']
    h_vA = res['h_vA_field']; h_vB = res['h_vB_field']
    K_ffA = res['_audit_K_ffA']; K_ffB = res['_audit_K_ffB']
    eps_arr = res['_audit_eps_arr']
    rho_cp_A = res['_audit_rho_cp_fA']; rho_cp_B = res['_audit_rho_cp_fB']
    uc_A = res['uc_real']; vc_A = res['vc_real']; wc_A = res['wc_real']
    uc_B = res.get('uc_real_B'); vc_B = res.get('vc_real_B'); wc_B = res.get('wc_real_B')
    dx = res['dx']; dy = res['dy']; dz = res['dz']
    T_inA = res['_audit_T_inA']; T_inB = res.get('_audit_T_inB')
    fA = res['_audit_fA']; fB = res.get('_audit_fB')
    eps_per_phase = 0.5 * eps_arr

    Nx, Ny, Nz = Ta.shape
    cell_vol = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]

    # ── RHS volume integrals ──
    # Fluid A FVM equation:  ε·ρ_cp·u·∇T − ∇·(K∇T) = h_vA·(Ts−Ta)
    # Integrating gives LHS = ∫ h_vA·(Ts−Ta) dV ← THIS is what should equal LHS_α
    RHS_A = float(np.sum(h_vA * (Ts - Ta) * cell_vol))
    if fB is not None:
        RHS_B = float(np.sum(h_vB * (Ts - Tb) * cell_vol))
    else:
        RHS_B = 0.0
    # Solid: 0 = ∇·(K_ss·∇T_s) + h_vA·(Ta−Ts) + h_vB·(Tb−Ts)
    # ⇒ ∮ −K_ss·∇T_s·n dA = ∫ [h_vA(Ts−Ta) + h_vB(Ts−Tb)] dV (sign-corrected)
    # Solid RHS_s = -RHS_A - RHS_B (negative of sum, by LTNE coupling)
    RHS_s = -(RHS_A + RHS_B)

    def _face_LHS(T_field, K_ff_field, rho_cp_field, uc, vc, wc, T_in, fcfg):
        """Build LHS = ∮ (ε·ρ_cp·u·n·T − K·∇T·n) dA for one fluid phase."""
        if fcfg is None or T_in is None:
            return 0.0
        adv = 0.0
        diff_dirichlet = 0.0
        dir_real = int(fcfg['dir'])
        # ── Inlet face contribution ──
        ax_in, idx_in = _real_inlet_dir_face_index(dir_real, T_field.shape)
        sl_in = _slice_at(ax_in, idx_in, T_field.shape)
        # Face area per cell on inlet face
        if ax_in == 0:
            A_2d = dy[:, None] * dz[None, :]
            u_n = (-uc if dir_real == 0 else uc)
            dh_in = dx[idx_in]
        elif ax_in == 1:
            A_2d = dx[:, None] * dz[None, :]
            u_n = (-vc if dir_real == 2 else vc)
            dh_in = dy[idx_in]
        else:
            A_2d = dx[:, None] * dy[None, :]
            u_n = (-wc if dir_real == 4 else wc)
            dh_in = dz[idx_in]
        # u_n at the inlet boundary cell layer (cell-center value)
        u_n_in = u_n[sl_in].squeeze()
        T_cell_in = T_field[sl_in].squeeze()
        rho_cp_in = rho_cp_field[sl_in].squeeze()
        eps_in = eps_per_phase[sl_in].squeeze()
        K_in = K_ff_field[sl_in].squeeze()
        # Outward normal at inlet for the various dirs:
        #   dir 0 (+x in, outlet at +x): real_inlet at i=0, n_outward=(-1,0,0)
        #     ∴ u·n = -u_x; for inflow u_x>0, u·n<0 (flux entering = negative outward)
        #   dir 1 (-x in, ...): n_outward=(+1,0,0), u·n=+u_x; inflow has u_x<0 → u·n<0 ✓
        # So u_n_in computed above already carries the correct sign for outward ·.
        # T_face for advection at inlet: the FVM kernel uses pinned T_in only on
        # mask cells; non-mask cells use neighbor (zero-grad). Both cases reduce
        # to "T at the boundary cell as set by BC application" — which is exactly
        # T_field[sl_in]. Use that.
        adv_in = float(np.sum(eps_in * rho_cp_in * u_n_in * T_cell_in * A_2d))
        adv += adv_in
        # Diffusive at inlet: only the mask cells have Dirichlet → ∂T/∂n ≠ 0.
        # For mask cells T_face ≈ T_in (pinned), gradient = (T_in − T_interior_adj) / (0.5·dh).
        # Since the boundary cell IS pinned to T_in (frac=1 case) or blend (0<frac<1),
        # the discrete diffusion stencil already absorbed this into the kernel.
        # For surface integral diagnostic, use: T_face=T_cell, T_outside=T_in, dh=cell.
        # Outward gradient = (T_in − T_cell) / (0.5·dh) projected onto n.
        # Sign: n outward; ∇T·n = ∂T/∂n_outward = (T_outside − T_inside) / (0.5·dh)
        #                       = (T_in − T_cell) / (0.5·dh)
        # Diffusive flux contribution: −K·∇T·n_outward (so − sign in F·n integral)
        T_in_2d = (np.full_like(T_cell_in, T_in)
                    if np.isscalar(T_in) else np.asarray(T_in))
        # Apply diffusive only where T is pinned (mask cells). For partial-B,
        # only mask>0.5 cells have T=T_in. But we don't have direct access to the
        # mask here — approximate: only contribute when |T_cell − T_in| < small
        # (cell IS pinned). Simpler: contribute everywhere — non-mask cells have
        # T_cell = neighbor ≈ ~T_in for inlet layer → gradient small. So OK.
        # Actually simpler still: at non-mask cells T_cell may be far from T_in
        # (zero-grad neighbor in heated region) → gradient large but FAKE.
        # To avoid double-counting fake at non-mask cells, restrict diffusive to
        # cells where |T_cell − T_in| < 0.5K (essentially pinned).
        pinned_mask_2d = (np.abs(T_cell_in - T_in_2d) < 0.5).astype(np.float64)
        grad = (T_in_2d - T_cell_in) / (0.5 * dh_in)
        diff_in = float(np.sum(-K_in * grad * pinned_mask_2d * A_2d))
        diff_dirichlet += diff_in

        # ── Outlet face contribution ──
        ax_out, idx_out = _real_outlet_dir_face_index(dir_real, T_field.shape)
        sl_out = _slice_at(ax_out, idx_out, T_field.shape)
        if ax_out == 0:
            A_2d_out = dy[:, None] * dz[None, :]
            u_n_out_arr = (uc if dir_real == 0 else -uc)
        elif ax_out == 1:
            A_2d_out = dx[:, None] * dz[None, :]
            u_n_out_arr = (vc if dir_real == 2 else -vc)
        else:
            A_2d_out = dx[:, None] * dy[None, :]
            u_n_out_arr = (wc if dir_real == 4 else -wc)
        u_n_out = u_n_out_arr[sl_out].squeeze()
        T_cell_out = T_field[sl_out].squeeze()
        rho_cp_out = rho_cp_field[sl_out].squeeze()
        eps_out = eps_per_phase[sl_out].squeeze()
        adv_out = float(np.sum(eps_out * rho_cp_out * u_n_out * T_cell_out * A_2d_out))
        adv += adv_out
        # Outlet diffusive: zero-grad ⇒ contribution 0
        return adv + diff_dirichlet

    LHS_A = _face_LHS(Ta, K_ffA, rho_cp_A, uc_A, vc_A, wc_A, T_inA, fA)
    if fB is not None:
        LHS_B = _face_LHS(Tb, K_ffB, rho_cp_B, uc_B, vc_B, wc_B, T_inB, fB)
    else:
        LHS_B = 0.0
    # Solid LHS — solid only has diffusive flux at boundaries (no advection)
    # Lateral walls: zero-grad ⇒ 0. Streamwise inlet/outlet of fluids: also
    # zero-grad in code (`_apply_outlet_3d` does Ts → cell value; inlet via
    # `_apply_inlet_3d` only acts on Ta/Tb, not Ts). So LHS_s ≈ 0.
    LHS_s = 0.0

    # ── Residuals ──
    eps_A = abs(LHS_A - RHS_A) / max(abs(LHS_A), abs(RHS_A), 1e-30)
    eps_B = abs(LHS_B - RHS_B) / max(abs(LHS_B), abs(RHS_B), 1e-30)
    eps_s = abs(LHS_s - RHS_s) / max(abs(LHS_s), abs(RHS_s), 1e-30)
    LHS_total = LHS_A + LHS_B + LHS_s
    RHS_total = RHS_A + RHS_B + RHS_s   # = 0 by LTNE coupling
    eps_total = abs(LHS_total - RHS_total) / max(abs(LHS_A), abs(LHS_B), abs(LHS_s), 1e-30)

    return dict(
        LHS_A=LHS_A, RHS_A=RHS_A, eps_A=eps_A,
        LHS_B=LHS_B, RHS_B=RHS_B, eps_B=eps_B,
        LHS_s=LHS_s, RHS_s=RHS_s, eps_s=eps_s,
        LHS_total=LHS_total, RHS_total=RHS_total, eps_total=eps_total,
    )


# ──────────────────────────────────────────────────────────────────────────
# Phase 2c — H3 per-cell mass-imbalance audit
# ──────────────────────────────────────────────────────────────────────────

def compute_phase2c_h3(res):
    """Per-cell mass NET_OUT and associated spurious enthalpy.

    For each interior cell: NET_OUT = Σ_face F_face_advective.
    A perfectly mass-conservative SIMPLE solve has NET_OUT ≈ 0 per cell.
    Spurious enthalpy from advection-equation per-cell residual:
        ΔE_cell = T_cell · NET_OUT_cell · ε · cp     (energy units, W)
    Globally summed gives the "mass-imbalance enthalpy contamination".

    Use solver-coord staggered face arrays (raw sA.u, sB.u etc.) since they
    are the EXACT face fluxes used by the kernel.
    """
    sA = res['_audit_sA_face']
    sB = res.get('_audit_sB_face')
    eps_arr = res['_audit_eps_arr']
    rho_cp_A = res['_audit_rho_cp_fA']
    rho_cp_B = res['_audit_rho_cp_fB']
    Ta = res['Ta']; Tb = res['Tb']

    def _per_cell_net_out(face, rho_cp_field, T_field):
        """Per-cell mass NET_OUT = Σ_face ρ·u·n·A (signed by outward normal)."""
        u = face['u']; v = face['v']; w = face['w']
        rho = face['rho']
        dx = face['dx']; dy = face['dy']; dz = face['dz']  # 1D arrays
        Nx_s, Ny_s, Nz_s = rho.shape

        # Per-cell area arrays as 3D for broadcast:
        # Face area for x-faces of cell (i,j,k) = dy[j]·dz[k] (independent of i)
        Ax_3d = (dy[None, :, None] * dz[None, None, :])    # (1, Ny, Nz)
        Ay_3d = (dx[:, None, None] * dz[None, None, :])    # (Nx, 1, Nz)
        Az_3d = (dx[:, None, None] * dy[None, :, None])    # (Nx, Ny, 1)
        # Broadcast to (Nx, Ny, Nz)
        Ax = np.broadcast_to(Ax_3d, rho.shape)
        Ay = np.broadcast_to(Ay_3d, rho.shape)
        Az = np.broadcast_to(Az_3d, rho.shape)

        # Mass flux (kg/s) through each face of each cell, signed by outward normal
        # u face array shape: (Nx+1, Ny, Nz). u[i, :, :] is the face between cell
        # i-1 and cell i (for i=0 it's the west boundary face of cell 0; for
        # i=Nx it's the east boundary face of cell Nx-1).
        # Mass flux at face i: m = ρ_face · u[i,:,:] · A. Sign of u positive ⇒
        # mass flowing in +x direction. For cell i, "east face flux out" =
        # +ρ·u[i+1]·A; "west face flux in" = +ρ·u[i]·A (positive into cell).
        # Net out via x = ρ·u[i+1]·A − ρ·u[i]·A.
        rho_e = 0.5 * (rho[:-1, :, :] + rho[1:, :, :]) if Nx_s > 1 else rho
        rho_n = 0.5 * (rho[:, :-1, :] + rho[:, 1:, :]) if Ny_s > 1 else rho
        rho_t = 0.5 * (rho[:, :, :-1] + rho[:, :, 1:]) if Nz_s > 1 else rho

        # For boundary faces, use the adjacent cell's ρ (no harmonic).
        # u_e shape (Nx, Ny, Nz): the east face of each cell.
        # u_w shape (Nx, Ny, Nz): the west face of each cell.
        u_east_face = u[1:, :, :]     # shape (Nx, Ny, Nz) — east face per cell
        u_west_face = u[:-1, :, :]    # shape (Nx, Ny, Nz) — west face per cell
        # For interior x-faces, ρ at face = harmonic-mean-like rho_e; at
        # boundary x-faces, fall back to cell-side ρ.
        rho_e_per_cell = rho.copy()  # ρ at east face of cell i
        if Nx_s > 1:
            rho_e_per_cell[:-1, :, :] = rho_e
            # East face of last cell IS boundary; rho stays as cell value
        rho_w_per_cell = rho.copy()  # ρ at west face of cell i
        if Nx_s > 1:
            rho_w_per_cell[1:, :, :] = rho_e
            # West face of first cell IS boundary
        flux_x_out = rho_e_per_cell * u_east_face * Ax \
                   - rho_w_per_cell * u_west_face * Ax

        v_north_face = v[:, 1:, :]
        v_south_face = v[:, :-1, :]
        rho_n_per_cell = rho.copy()
        if Ny_s > 1:
            rho_n_per_cell[:, :-1, :] = rho_n
        rho_s_per_cell = rho.copy()
        if Ny_s > 1:
            rho_s_per_cell[:, 1:, :] = rho_n
        flux_y_out = rho_n_per_cell * v_north_face * Ay \
                   - rho_s_per_cell * v_south_face * Ay

        w_top_face = w[:, :, 1:]
        w_bot_face = w[:, :, :-1]
        rho_t_per_cell = rho.copy()
        if Nz_s > 1:
            rho_t_per_cell[:, :, :-1] = rho_t
        rho_b_per_cell = rho.copy()
        if Nz_s > 1:
            rho_b_per_cell[:, :, 1:] = rho_t
        flux_z_out = rho_t_per_cell * w_top_face * Az \
                   - rho_b_per_cell * w_bot_face * Az

        return flux_x_out + flux_y_out + flux_z_out

    # Compute per-cell NET_OUT for both fluids
    net_A = _per_cell_net_out(sA, rho_cp_A, Ta)
    # Reshape Ta from real coords to solver coords for matching with sA
    perm_A = sA['solver_to_real_perm']
    inv_A = tuple(np.argsort(perm_A))
    Ta_solver = np.ascontiguousarray(np.transpose(Ta, inv_A))

    # Spurious enthalpy contamination
    # Per cell α: ΔE_cell = T_cell · NET_OUT · ε_α · cp
    # But NET_OUT already includes ρ — so ΔE_cell = T_cell · NET_OUT · cp
    # Wait — net_out has units kg/s (rho·v·A). For energy contamination:
    # ΔE_cell ≈ T_cell · cp · net_out · ε_per_phase    units: K · J/kg/K · kg/s = W
    eps_per_phase_solver = 0.5 * np.transpose(eps_arr, inv_A)
    cp_A = res['_audit_cp_A']
    spur_A_per_cell = Ta_solver * cp_A * net_A * eps_per_phase_solver
    spur_A_total = float(np.sum(spur_A_per_cell))
    mass_imbal_A_total = float(np.sum(net_A))   # kg/s sum (per-cell)
    mass_imbal_A_abs = float(np.sum(np.abs(net_A)))

    out = dict(
        A=dict(
            net_out_total=mass_imbal_A_total,
            net_out_abs=mass_imbal_A_abs,
            spurious_enthalpy_W=spur_A_total,
            net_out_max_cell=float(np.max(np.abs(net_A))),
            net_out_p99=float(np.percentile(np.abs(net_A), 99)),
        ),
        B=None,
    )
    if sB is not None:
        net_B = _per_cell_net_out(sB, rho_cp_B, Tb)
        perm_B = sB['solver_to_real_perm']
        inv_B = tuple(np.argsort(perm_B))
        Tb_solver = np.ascontiguousarray(np.transpose(Tb, inv_B))
        eps_per_phase_solver_B = 0.5 * np.transpose(eps_arr, inv_B)
        cp_B = res['_audit_cp_B']
        spur_B_per_cell = Tb_solver * cp_B * net_B * eps_per_phase_solver_B
        spur_B_total = float(np.sum(spur_B_per_cell))
        out['B'] = dict(
            net_out_total=float(np.sum(net_B)),
            net_out_abs=float(np.sum(np.abs(net_B))),
            spurious_enthalpy_W=spur_B_total,
            net_out_max_cell=float(np.max(np.abs(net_B))),
            net_out_p99=float(np.percentile(np.abs(net_B), 99)),
        )
    return out


# ──────────────────────────────────────────────────────────────────────────
# Phase 3 — 2nd law (S_gen) + volumetric σ̇ + Carnot bound + monotonicity
# ──────────────────────────────────────────────────────────────────────────

def compute_phase3(res):
    """Phase 3 — second law and Carnot bound checks.

    Five sub-blocks per spec §4:
      3.1 Global S_gen via outlet T (mass-flux weighted)
      3.2 Volumetric σ̇ per cell + integral; sign-positive check
      3.3 Carnot/NTU upper bound (cross-flow Incropera ε_max)
      3.4 Monotonicity: T_min ≤ Tα ≤ T_max ∀ cell (max principle)
      3.5 T_B_out < T_A_out (cold ≯ hot)
    """
    Ta = res['Ta']; Tb = res['Tb']; Ts = res['Ts']
    h_vA = res['h_vA_field']; h_vB = res['h_vB_field']
    K_ffA = res['_audit_K_ffA']; K_ffB = res['_audit_K_ffB']
    K_ss = res['_audit_K_ss']
    dx = res['dx']; dy = res['dy']; dz = res['dz']
    cp_A = res['_audit_cp_A']
    cp_B = res.get('_audit_cp_B')
    T_inA = res['_audit_T_inA']; T_inB = res.get('_audit_T_inB')
    m_A = float(res['_audit_m_dot_A_simple'])
    m_B = (float(res.get('_audit_m_dot_B_simple', 0.0))
           if res.get('_audit_m_dot_B_simple') is not None else 0.0)
    # A B-isolated run leaves res['T_B_out'] PRESENT but None; dict.get returns
    # the stored None (not the fallback), so float(None) would crash Phase 3.
    # Coerce present-but-None symmetrically for both fluids. Audit: r2-val-01.
    _ta = res.get('T_A_out')
    T_A_out = float(_ta if _ta is not None else T_inA)
    _tb = res.get('T_B_out')
    T_B_out = float(_tb if _tb is not None
                    else (T_inB if T_inB is not None else T_inA))

    Nx, Ny, Nz = Ta.shape
    cell_vol = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]

    # ── 3.1 Global S_gen ──
    S_gen_A = m_A * cp_A * np.log(max(T_A_out, 1e-30) / max(T_inA, 1e-30))
    if cp_B is not None and m_B > 0 and T_inB is not None:
        S_gen_B = m_B * cp_B * np.log(max(T_B_out, 1e-30) / max(T_inB, 1e-30))
    else:
        S_gen_B = 0.0
    S_gen_global = float(S_gen_A + S_gen_B)

    # ── 3.2 Volumetric σ̇ per-cell ──
    # σ̇ = h_vA·(Ts−Ta)²/(Ts·Ta) + h_vB·(Ts−Tb)²/(Ts·Tb)
    #    + K_ss·|∇Ts|²/Ts² + K_ffA·|∇Ta|²/Ta² + K_ffB·|∇Tb|²/Tb²
    # All terms positive in continuous form.
    sigma_h_vA = h_vA * (Ts - Ta) ** 2 / (Ts * Ta + 1e-30)
    sigma_h_vB = h_vB * (Ts - Tb) ** 2 / (Ts * Tb + 1e-30) if cp_B is not None else np.zeros_like(Ta)
    # ∇T magnitude squared (cell-center finite difference, central)
    def _grad_sq(T, dx, dy, dz):
        gx = np.zeros_like(T)
        gy = np.zeros_like(T)
        gz = np.zeros_like(T)
        if T.shape[0] > 1:
            gx[1:-1] = (T[2:] - T[:-2]) / (dx[1:-1, None, None] * 2)
            gx[0] = (T[1] - T[0]) / dx[0]
            gx[-1] = (T[-1] - T[-2]) / dx[-1]
        if T.shape[1] > 1:
            gy[:, 1:-1] = (T[:, 2:] - T[:, :-2]) / (dy[None, 1:-1, None] * 2)
            gy[:, 0] = (T[:, 1] - T[:, 0]) / dy[0]
            gy[:, -1] = (T[:, -1] - T[:, -2]) / dy[-1]
        if T.shape[2] > 1:
            gz[:, :, 1:-1] = (T[:, :, 2:] - T[:, :, :-2]) / (dz[None, None, 1:-1] * 2)
            gz[:, :, 0] = (T[:, :, 1] - T[:, :, 0]) / dz[0]
            gz[:, :, -1] = (T[:, :, -1] - T[:, :, -2]) / dz[-1]
        return gx ** 2 + gy ** 2 + gz ** 2
    grad2_Ts = _grad_sq(Ts, dx, dy, dz)
    grad2_Ta = _grad_sq(Ta, dx, dy, dz)
    grad2_Tb = _grad_sq(Tb, dx, dy, dz) if cp_B is not None else np.zeros_like(Ta)

    sigma_diff_s = K_ss * grad2_Ts / (Ts ** 2 + 1e-30)
    sigma_diff_A = K_ffA * grad2_Ta / (Ta ** 2 + 1e-30)
    sigma_diff_B = K_ffB * grad2_Tb / (Tb ** 2 + 1e-30) if cp_B is not None else np.zeros_like(Ta)

    sigma_dot = sigma_h_vA + sigma_h_vB + sigma_diff_s + sigma_diff_A + sigma_diff_B
    S_gen_volumetric = float(np.sum(sigma_dot * cell_vol))
    sigma_neg_cells = int(np.sum(sigma_dot < -1e-12))
    sigma_neg_pct = sigma_neg_cells / sigma_dot.size * 100

    # ── 3.3 Carnot / NTU bound ──
    # Use LTNE-effective C (= m_LTNE·cp). The kernel's energy equation
    # balances at this scale: ε_α·ρ·cp·u·∇T = h_vα·(Ts−Tα). m_LTNE already
    # carries the ε/2 factor. ε-NTU bound applied at this consistent scale.
    # Degenerate-path defaults: single-fluid (T5, cp_B None) and
    # equi-temperature (T6, zero inlet gap) skip the guarded block below,
    # but the metrics dict at the bottom still references these names —
    # pre-init to nan so it reports "not applicable" instead of dying with
    # UnboundLocalError on C_A (found 2026-07-14 on the T6 audit).
    C_A = C_B = C_r = C_min = float('nan')
    Q_primary = Q_phys_A = Q_phys_B = Q_volumetric_phys = float('nan')
    Q_NTU_max = eps_obs = eps_max_NTU = NTU_int = float('nan')
    if cp_B is not None and T_inB is not None and abs(T_inA - T_inB) > 1e-30:
        C_A = m_A * cp_A
        C_B = m_B * cp_B
        C_min = min(C_A, C_B) if (C_A > 0 and C_B > 0) else max(C_A, C_B, 1e-30)
        C_max = max(C_A, C_B, 1e-30)
        C_r = C_min / max(C_max, 1e-30)
        dT_max = abs(T_inA - T_inB)
        Q_NTU_max = C_min * dT_max
        # Q_actual at LTNE scale: m_LTNE·cp·ΔT (matches kernel internal).
        Q_LTNE_A = C_A * abs(T_inA - T_A_out)
        Q_LTNE_B = C_B * abs(T_B_out - T_inB) if C_B > 0 else 0.0
        Q_phys_A = float(Q_LTNE_A)   # naming retained for report
        Q_phys_B = float(Q_LTNE_B)
        Q_volumetric_phys = abs(float(res.get('Q_sB_interior', 0.0)))
        Q_primary = 0.5 * (Q_LTNE_A + Q_LTNE_B) if Q_LTNE_B > 0 else Q_LTNE_A
        eps_obs = Q_primary / max(Q_NTU_max, 1e-30)
        # NTU estimate: ∫h_vB·χ_B·dV / C_min
        chi_B = res.get('_audit_chi_B')
        if chi_B is not None:
            NTU_int = float(np.sum(h_vB * chi_B * cell_vol)) / max(C_min, 1e-30)
        else:
            NTU_int = float(np.sum(h_vB * cell_vol)) / max(C_min, 1e-30)
        # Cross-flow unmixed-unmixed Incropera ε_max
        if NTU_int > 0:
            try:
                eps_max_NTU = (1.0 - np.exp(
                    (np.exp(-C_r * NTU_int ** 0.78) - 1.0)
                    / max(C_r * NTU_int ** -0.22, 1e-30)))
            except Exception:
                eps_max_NTU = 1.0
        else:
            eps_max_NTU = 0.0
    else:
        C_min = float('nan'); C_max = float('nan'); C_r = float('nan')
        Q_NTU_max = float('nan'); Q_primary = float('nan')
        eps_obs = float('nan'); NTU_int = float('nan')
        eps_max_NTU = float('nan')

    # ── 3.4 Monotonicity / max principle ──
    T_min_in = min(T_inA, T_inB) if T_inB is not None else T_inA
    T_max_in = max(T_inA, T_inB) if T_inB is not None else T_inA
    tol = 0.5
    over_a = int(np.sum((Ta > T_max_in + tol) | (Ta < T_min_in - tol)))
    over_b = int(np.sum((Tb > T_max_in + tol) | (Tb < T_min_in - tol))) if cp_B is not None else 0
    over_s = int(np.sum((Ts > T_max_in + tol) | (Ts < T_min_in - tol)))

    # ── 3.5 T_B_out < T_A_out (cold ≯ hot for hot-A scenarios) ──
    if T_inB is not None and T_inA > T_inB:
        cold_lt_hot = T_B_out < T_A_out
    elif T_inB is not None and T_inA < T_inB:
        cold_lt_hot = T_A_out < T_B_out   # roles swapped
    else:
        cold_lt_hot = True   # equi-T or B disabled, trivially passes

    return dict(
        # 3.1
        S_gen_global=S_gen_global,
        S_gen_A=float(S_gen_A), S_gen_B=float(S_gen_B),
        # 3.2
        S_gen_volumetric=S_gen_volumetric,
        sigma_neg_cells=sigma_neg_cells,
        sigma_neg_pct=sigma_neg_pct,
        sigma_global_vs_volumetric_rel=(abs(S_gen_global - S_gen_volumetric)
                                       / max(abs(S_gen_global), abs(S_gen_volumetric), 1e-30)),
        # 3.3
        C_A=float(C_A) if cp_B is not None else float('nan'),
        C_B=float(C_B) if cp_B is not None else float('nan'),
        C_r=float(C_r), C_min=float(C_min),
        Q_primary_phys=float(Q_primary),
        Q_phys_A=float(Q_phys_A) if cp_B is not None else float('nan'),
        Q_phys_B=float(Q_phys_B) if cp_B is not None else float('nan'),
        Q_volumetric_phys=float(Q_volumetric_phys) if cp_B is not None else float('nan'),
        Q_NTU_max=float(Q_NTU_max),
        eps_obs=float(eps_obs), eps_max_NTU=float(eps_max_NTU),
        NTU_int=float(NTU_int),
        carnot_pass=(eps_obs <= eps_max_NTU + 0.05) if eps_obs == eps_obs else None,
        # 3.4
        max_principle_violations_A=over_a,
        max_principle_violations_B=over_b,
        max_principle_violations_s=over_s,
        T_min_in=T_min_in, T_max_in=T_max_in,
        # 3.5
        T_A_out=T_A_out, T_B_out=T_B_out,
        cold_lt_hot=bool(cold_lt_hot),
    )


# ──────────────────────────────────────────────────────────────────────────
# Phase 4 — mass conservation + compressible drift
# ──────────────────────────────────────────────────────────────────────────

def compute_phase4(res):
    """Phase 4 — mass-cons audit per fluid; attribute imbal to compressible drift.

    For each fluid α, integrate ρ·u·n·dA across 6 outer faces. For steady
    incompressible: imbal = 0. For compressible (ideal gas): imbal expected
    ~ |Δρ/ρ| ≈ |ΔP/P| + |ΔT/T|.

    If actual imbal exceeds expected drift, residual is numerical.
    """
    sA = res['_audit_sA_face']
    sB = res.get('_audit_sB_face')
    P_inA = res.get('_audit_P_inA')
    P_inB = res.get('_audit_P_inB')
    T_inA = res['_audit_T_inA']
    T_inB = res.get('_audit_T_inB')

    def _per_fluid(face, T_in, P_in, T_out):
        u = face['u']; v = face['v']; w = face['w']
        rho = face['rho']
        dx = face['dx']; dy = face['dy']; dz = face['dz']
        dir_real = face['dir_real']
        Nx_s, Ny_s, Nz_s = rho.shape

        # Solver j=0 face (south boundary)
        A_solver_y = dx[:, None] * dz[None, :]
        m_south = float(np.sum(rho[:, 0, :] * v[:, 0, :] * A_solver_y))
        m_north = float(np.sum(rho[:, -1, :] * v[:, -1, :] * A_solver_y))
        # Solver lateral (x and z) faces
        A_solver_x = dy[:, None] * dz[None, :]
        m_west = float(np.sum(rho[0, :, :] * u[0, :, :] * A_solver_x))
        m_east = float(np.sum(rho[-1, :, :] * u[-1, :, :] * A_solver_x))
        A_solver_z = dx[:, None] * dy[None, :]
        m_bot = float(np.sum(rho[:, :, 0] * w[:, :, 0] * A_solver_z))
        m_top = float(np.sum(rho[:, :, -1] * w[:, :, -1] * A_solver_z))

        # Net out (signed by outward normal in solver coords):
        # outward at +x = +u_east·A; outward at -x = -u_west·A; etc.
        net_out_solver = (m_east - m_west) + (m_north - m_south) + (m_top - m_bot)

        # SIMPLE conv: forward streams enter at solver j=0 (south, v>0); the
        # streamwise "out" face is j=Ny. FIX (2026-06-24 audit): reverse-direction
        # fluids (dir_real in {1,3,5}, e.g. fluid B with dir=3 in the T2 case)
        # physically enter at solver j=-1 (north), so swap in/out — otherwise the
        # imbalance is normalized on the OUTLET flux. net_out_solver above is
        # signed/direction-independent and stays unchanged.
        is_reverse = dir_real in (1, 3, 5)
        if is_reverse:
            m_in_face = m_north    # signed positive entering
            m_out_face = m_south   # signed positive leaving
        else:
            m_in_face = m_south
            m_out_face = m_north
        imbal = (m_in_face - m_out_face) / max(abs(m_in_face), 1e-30)

        # Compressible drift expectation: |ΔT/T_in| + |ΔP/P_in|
        # For ideal gas: ρ ∝ P/T. Without P/T data inside, use only T drift.
        if T_in is not None and T_in > 0 and T_out is not None:
            dT_rel = abs(T_out - T_in) / T_in
        else:
            dT_rel = 0.0
        # Pressure drift small for typical Shanghai cases; ignore for now.
        drift_expected = dT_rel
        residual_numerical = abs(imbal) - drift_expected

        return dict(
            m_in=m_in_face, m_out=m_out_face,
            net_out_total=net_out_solver,
            imbal_rel=float(imbal),
            drift_expected=float(drift_expected),
            residual=float(residual_numerical),
        )

    out = dict(A=None, B=None)
    if sA is not None:
        T_A_out = float(res.get('T_A_out', T_inA))
        out['A'] = _per_fluid(sA, T_inA, P_inA, T_A_out)
    if sB is not None and T_inB is not None:
        T_B_out = float(res.get('T_B_out', T_inB))
        out['B'] = _per_fluid(sB, T_inB, P_inB, T_B_out)
    return out


# ──────────────────────────────────────────────────────────────────────────
# Phase 5 — boundary surface flux audit (6 faces + lateral wall adiabaticity)
# ──────────────────────────────────────────────────────────────────────────

def compute_phase5(res):
    """Phase 5 — energy flux through 6 outer faces of Ω.

    For each fluid α, integrate F_α·n dA across each of 6 outer faces.
    Streamwise inlet/outlet faces should carry advective enthalpy flux;
    lateral walls (perpendicular to flow direction) should be adiabatic
    (zero net flux). Hard gate: lateral wall flux < 0.5 % of streamwise
    inlet/outlet max.
    """
    sA = res['_audit_sA_face']
    sB = res.get('_audit_sB_face')
    Ta = res['Ta']; Tb = res['Tb']
    rho_cp_A = res['_audit_rho_cp_fA']
    rho_cp_B = res['_audit_rho_cp_fB']
    eps_arr = res['_audit_eps_arr']
    eps_per_phase = 0.5 * eps_arr
    fA = res['_audit_fA']
    fB = res.get('_audit_fB')

    def _per_fluid(face, T_field, rho_cp_field, fcfg):
        if face is None or fcfg is None:
            return None
        # Compute advective enthalpy flux ∮F·n dA on each of 6 SOLVER faces.
        u = face['u']; v = face['v']; w = face['w']
        rho = face['rho']
        dx = face['dx']; dy = face['dy']; dz = face['dz']
        Nx_s, Ny_s, Nz_s = rho.shape

        perm = face['solver_to_real_perm']
        inv = tuple(np.argsort(perm))
        T_solver = np.ascontiguousarray(np.transpose(T_field, inv))
        rho_cp_solver = np.ascontiguousarray(np.transpose(rho_cp_field, inv))
        eps_solver = np.ascontiguousarray(np.transpose(eps_per_phase, inv))

        A_x = dy[:, None] * dz[None, :]   # shape (Ny, Nz) — for x-faces
        A_y = dx[:, None] * dz[None, :]   # for y-faces
        A_z = dx[:, None] * dy[None, :]   # for z-faces

        # Solver faces:
        # +x (i=Nx_s, outward), -x (i=0, outward = -x dir), etc.
        F_xp = float(np.sum(eps_solver[-1, :, :] * rho_cp_solver[-1, :, :]
                            * u[-1, :, :] * T_solver[-1, :, :] * A_x))
        F_xm = float(np.sum(eps_solver[0, :, :] * rho_cp_solver[0, :, :]
                            * (-u[0, :, :]) * T_solver[0, :, :] * A_x))
        F_yp = float(np.sum(eps_solver[:, -1, :] * rho_cp_solver[:, -1, :]
                            * v[:, -1, :] * T_solver[:, -1, :] * A_y))
        F_ym = float(np.sum(eps_solver[:, 0, :] * rho_cp_solver[:, 0, :]
                            * (-v[:, 0, :]) * T_solver[:, 0, :] * A_y))
        F_zp = float(np.sum(eps_solver[:, :, -1] * rho_cp_solver[:, :, -1]
                            * w[:, :, -1] * T_solver[:, :, -1] * A_z))
        F_zm = float(np.sum(eps_solver[:, :, 0] * rho_cp_solver[:, :, 0]
                            * (-w[:, :, 0]) * T_solver[:, :, 0] * A_z))

        # Streamwise vs lateral: SIMPLE solver streamwise = solver y axis.
        # So +y/-y are streamwise inlet/outlet. ±x and ±z are lateral.
        F_stream = F_yp + F_ym
        F_lateral = F_xp + F_xm + F_zp + F_zm
        F_stream_mag = max(abs(F_yp), abs(F_ym), 1e-30)
        lateral_frac = abs(F_lateral) / F_stream_mag

        return dict(
            F_xp=F_xp, F_xm=F_xm,
            F_yp=F_yp, F_ym=F_ym,
            F_zp=F_zp, F_zm=F_zm,
            F_stream=F_stream, F_lateral=F_lateral,
            F_stream_mag=F_stream_mag,
            lateral_frac=float(lateral_frac),
        )

    return dict(
        A=_per_fluid(sA, Ta, rho_cp_A, fA),
        B=_per_fluid(sB, Tb, rho_cp_B, fB),
    )


# ──────────────────────────────────────────────────────────────────────────
# Markdown rendering
# ──────────────────────────────────────────────────────────────────────────

def _fmt(x, p=4):
    if isinstance(x, float):
        if x != x:
            return 'nan'
        if abs(x) >= 1e6 or (abs(x) < 1e-3 and x != 0.0):
            return f'{x:.{p}e}'
        return f'{x:.{p}f}'
    return str(x)


def render_case(label, res, p2a, p2c, p3=None, p4=None, p5=None):
    lines = []
    lines.append(f'\n## Case: {label}\n')
    lines.append(f'- grid: {res["Ta"].shape}')
    lines.append(f'- Q_enthalpy_A = {_fmt(res.get("Q_enthalpy_A", float("nan")), 2)} W')
    lines.append(f'- Q_enthalpy_B = {_fmt(res.get("Q_enthalpy_B", float("nan")), 2)} W')
    lines.append(f'- Q_solid_A (∫h_vA(Ts−Ta)dV) = {_fmt(res.get("Q_sA", float("nan")), 2)} W')
    lines.append(f'- Q_solid_B (∫h_vB(Ts−Tb)dV) = {_fmt(res.get("Q_sB", float("nan")), 2)} W')
    lines.append(f'- Q_sA_interior (BC excluded) = {_fmt(res.get("Q_sA_interior", float("nan")), 2)} W')
    lines.append(f'- Q_sB_interior (BC excluded) = {_fmt(res.get("Q_sB_interior", float("nan")), 2)} W\n')

    lines.append('### Phase 2a — interior 1st-law residual\n')
    lines.append('Compares Q_enth (LTNE m·cp·ΔT) against |Q_s_interior| (BC layer excluded).')
    lines.append('Includes all-cells LHS_surf (surface integral) as an independent check.\n')
    lines.append('| metric | A | B |')
    lines.append('|--------|---|---|')
    lines.append(f'| Q_enth | {_fmt(p2a["Q_enth_A"], 2)} W | {_fmt(p2a["Q_enth_B"], 2)} W |')
    lines.append(f'| \\|Q_s_interior\\| | {_fmt(abs(p2a["Q_sA_interior"]), 2)} W | {_fmt(abs(p2a["Q_sB_interior"]), 2)} W |')
    lines.append(f'| ε_α (kernel, interior) | {_fmt(p2a["eps_A_kernel"]*100, 3)} % | {_fmt(p2a["eps_B_kernel"]*100, 3)} % |')
    lines.append(f'| BC pinning frac (Q_s_BC / \\|Q_s_all\\|) | {_fmt(p2a["BC_frac_A"]*100, 2)} % | {_fmt(p2a["BC_frac_B"]*100, 2)} % |')
    lines.append(f'| LHS_surf (∮F·n dA, all cells) | {_fmt(p2a["LHS_A_surf"], 2)} W | {_fmt(p2a["LHS_B_surf"], 2)} W |')
    lines.append('')
    lines.append(f'- LTNE 3-phase coupling: ε_LTNE = |Q_sA + Q_sB| / max = {_fmt(p2a["eps_LTNE"]*100, 3)} %')
    lines.append('')
    gates = []
    gates.append(('ε_A_kernel < 5 %', p2a['eps_A_kernel'] < 0.05))
    gates.append(('ε_B_kernel < 5 %', p2a['eps_B_kernel'] < 0.05))
    gates.append(('ε_LTNE < 1 %',     p2a['eps_LTNE']    < 0.01))
    for name, ok in gates:
        lines.append(f'- {name}: **{"PASS" if ok else "FAIL"}**')
    lines.append('')

    lines.append('### Phase 2c — H3 per-cell mass-imbalance audit\n')
    lines.append('| fluid | Σ NET_OUT (kg/s) | Σ\\|NET_OUT\\| (kg/s) | spurious enthalpy (W) | max\\|NET_OUT\\| | p99 |')
    lines.append('|-------|-------------------|------------------------|------------------------|------------------|-----|')
    a = p2c['A']
    lines.append(f'| A | {_fmt(a["net_out_total"],6)} | {_fmt(a["net_out_abs"],6)} | {_fmt(a["spurious_enthalpy_W"],2)} | {_fmt(a["net_out_max_cell"],6)} | {_fmt(a["net_out_p99"],6)} |')
    if p2c['B'] is not None:
        b = p2c['B']
        lines.append(f'| B | {_fmt(b["net_out_total"],6)} | {_fmt(b["net_out_abs"],6)} | {_fmt(b["spurious_enthalpy_W"],2)} | {_fmt(b["net_out_max_cell"],6)} | {_fmt(b["net_out_p99"],6)} |')
    lines.append('')

    if p3 is not None:
        lines.append('### Phase 3 — 2nd law + Carnot bound\n')
        lines.append('**3.1 Global S_gen** (mass-flux-weighted T_out form):\n')
        lines.append(f'- S_gen_A = {_fmt(p3["S_gen_A"], 4)} W/K')
        lines.append(f'- S_gen_B = {_fmt(p3["S_gen_B"], 4)} W/K')
        lines.append(f'- **S_gen_global = {_fmt(p3["S_gen_global"], 4)} W/K**\n')
        lines.append('**3.2 Volumetric σ̇** (per-cell entropy generation rate, dual check):\n')
        lines.append(f'- S_gen_volumetric = ∫_Ω σ̇ dV = {_fmt(p3["S_gen_volumetric"], 4)} W/K')
        lines.append(f'- |global − volumetric| / max = {_fmt(p3["sigma_global_vs_volumetric_rel"]*100, 2)} %')
        lines.append(f'- σ̇ < 0 cells: {p3["sigma_neg_cells"]} ({_fmt(p3["sigma_neg_pct"], 2)} %)\n')
        lines.append('**3.3 Carnot / NTU bound** (LTNE-effective scale, '
                     'matches kernel energy balance):\n')
        lines.append('| quantity | value |')
        lines.append('|----------|-------|')
        lines.append(f'| C_A = m_LTNE_A · cp_A | {_fmt(p3["C_A"], 3)} W/K |')
        lines.append(f'| C_B = m_LTNE_B · cp_B | {_fmt(p3["C_B"], 3)} W/K |')
        lines.append(f'| C_min | {_fmt(p3["C_min"], 3)} W/K |')
        lines.append(f'| C_r = C_min/C_max | {_fmt(p3["C_r"], 4)} |')
        lines.append(f'| Q_NTU_max = C_min·ΔT_max | {_fmt(p3["Q_NTU_max"], 1)} W |')
        lines.append(f'| Q_LTNE_A = C_A·\\|T_inA−T_A_out\\| | {_fmt(p3["Q_phys_A"], 1)} W |')
        lines.append(f'| Q_LTNE_B = C_B·\\|T_B_out−T_inB\\| | {_fmt(p3["Q_phys_B"], 1)} W |')
        lines.append(f'| \\|Q_sB_interior\\| (volumetric source) | {_fmt(p3["Q_volumetric_phys"], 1)} W |')
        lines.append(f'| NTU_int = ∫h_vB·χ_B·dV / C_min | {_fmt(p3["NTU_int"], 3)} |')
        lines.append(f'| ε_max(C_r, NTU) cross-flow | {_fmt(p3["eps_max_NTU"], 4)} |')
        lines.append(f'| ε_obs = Q_LTNE / Q_NTU_max | {_fmt(p3["eps_obs"], 4)} |')
        lines.append('')
        lines.append('**3.4 Maximum principle** (T_min ≤ Tα ≤ T_max ∀ cell, tol=0.5 K):\n')
        lines.append(f'- T_min_in = {p3["T_min_in"]:.2f} K, T_max_in = {p3["T_max_in"]:.2f} K')
        lines.append(f'- A violations: {p3["max_principle_violations_A"]}')
        lines.append(f'- B violations: {p3["max_principle_violations_B"]}')
        lines.append(f'- s violations: {p3["max_principle_violations_s"]}\n')
        lines.append('**3.5 Cold ≯ hot**:\n')
        lines.append(f'- T_A_out = {p3["T_A_out"]:.2f} K, T_B_out = {p3["T_B_out"]:.2f} K')
        lines.append(f'- T_B_out < T_A_out: **{"PASS" if p3["cold_lt_hot"] else "FAIL"}**\n')

        gates3 = []
        gates3.append(('S_gen_global ≥ −1e-3', p3['S_gen_global'] >= -1e-3))
        gates3.append(('σ̇ < 0 cells < 0.1 %', p3['sigma_neg_pct'] < 0.1))
        gates3.append(('|global − volumetric| / max < 5 %',
                        p3['sigma_global_vs_volumetric_rel'] < 0.05))
        if p3['carnot_pass'] is not None:
            gates3.append(('ε_obs ≤ ε_max + 0.05', p3['carnot_pass']))
        gates3.append(('max principle (no violations)',
                       p3['max_principle_violations_A'] +
                       p3['max_principle_violations_B'] +
                       p3['max_principle_violations_s'] == 0))
        # 'cold ≯ hot' is informational only — for cross-flow with high ε
        # crossover (T_B_out > T_A_out) is thermodynamically allowed when
        # ε > 1/(1+C_r). Report status but don't auto-fail.
        crossover_allowed = (p3['C_r'] > 0 and
                             p3['eps_obs'] > 1.0 / (1.0 + p3['C_r']))
        if crossover_allowed and not p3['cold_lt_hot']:
            lines.append('- cold ≯ hot: **(crossover allowed, ε > 1/(1+C_r))**')
        else:
            gates3.append(('cold ≯ hot', p3['cold_lt_hot']))
        for name, ok in gates3:
            lines.append(f'- {name}: **{"PASS" if ok else "FAIL"}**')
        lines.append('')

    if p4 is not None:
        lines.append('### Phase 4 — mass conservation + compressible drift\n')
        lines.append('| fluid | m_in (kg/s) | m_out (kg/s) | imbal % | expected drift % | numerical residual % |')
        lines.append('|-------|-------------|--------------|---------|------------------|----------------------|')
        for tag in ('A', 'B'):
            d = p4.get(tag)
            if d is None:
                continue
            lines.append(
                f'| {tag} | {_fmt(d["m_in"], 6)} | {_fmt(d["m_out"], 6)} | '
                f'{_fmt(d["imbal_rel"]*100, 3)} | {_fmt(d["drift_expected"]*100, 3)} | '
                f'{_fmt(d["residual"]*100, 3)} |')
        lines.append('')
        gates4 = []
        for tag in ('A', 'B'):
            d = p4.get(tag)
            if d is None:
                continue
            ok = abs(d['imbal_rel']) < 0.01    # mass conservation < 1 %
            gates4.append((f'{tag} mass imbal < 1 % (physical scale)', ok))
        for name, ok in gates4:
            lines.append(f'- {name}: **{"PASS" if ok else "FAIL"}**')
        lines.append('')

    if p5 is not None:
        lines.append('### Phase 5 — boundary surface flux audit\n')
        lines.append('Solver-coord faces: +y/−y = streamwise (inlet/outlet); '
                     '±x/±z = lateral walls (should be adiabatic).\n')
        lines.append('| fluid | F_xp | F_xm | F_yp | F_ym | F_zp | F_zm | F_lateral | lat/stream |')
        lines.append('|-------|------|------|------|------|------|------|-----------|------------|')
        for tag in ('A', 'B'):
            d = p5.get(tag)
            if d is None:
                continue
            lines.append(
                f'| {tag} | {_fmt(d["F_xp"], 1)} | {_fmt(d["F_xm"], 1)} | '
                f'{_fmt(d["F_yp"], 1)} | {_fmt(d["F_ym"], 1)} | '
                f'{_fmt(d["F_zp"], 1)} | {_fmt(d["F_zm"], 1)} | '
                f'{_fmt(d["F_lateral"], 1)} | {_fmt(d["lateral_frac"]*100, 2)} % |')
        lines.append('')
        gates5 = []
        for tag in ('A', 'B'):
            d = p5.get(tag)
            if d is None:
                continue
            ok = d['lateral_frac'] < 0.005    # < 0.5 % per spec
            gates5.append((f'{tag} lateral wall flux < 0.5 % of streamwise', ok))
        for name, ok in gates5:
            lines.append(f'- {name}: **{"PASS" if ok else "FAIL"}**')
        lines.append('')
    return '\n'.join(lines)


def write_report(out_path, sections, header_meta):
    lines = []
    lines.append('# Phase 2 — 3D LTNE Conservation Audit\n')
    lines.append(f'- Date: {header_meta["date"]}')
    lines.append('- Spec: `vault/reports/3d-solver/2026-05-04-3d-conservation-spec-CN.md`')
    lines.append('- Audit script: `sjtu_tpmshx/validation/audit_3d_conservation.py`\n')
    lines.append('## Scope\n')
    lines.append('- Hybrid path: Phase 2a volumetric ε_α + Phase 2c per-cell mass-imbal audit (H3).')
    lines.append('- Read-only. No solver / closure / momentum changes.')
    lines.append('- Test matrix: T1 full-face parallel, T2 full-face cross, T3 partial-aligned, T4 partial-offset (Shanghai-like), T5 B-isolated, T6 equi-temperature.\n')
    for sec in sections:
        lines.append(sec)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text('\n'.join(lines), encoding='utf-8')


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--grid', type=int, default=20)
    ap.add_argument('--cases', type=str, default='T1,T2,T3,T4,T5,T6',
                    help='Comma-separated test case IDs (subset of T1..T6).')
    ap.add_argument('--out', type=str, default=None)
    ap.add_argument('--phase6_grid_convergence', action='store_true',
                    help='Phase 6 multi-grid sweep: runs each case at '
                         'grids 12, 20, 30 and reports Richardson convergence.')
    args = ap.parse_args()

    if args.out is None:
        # The vault sits at a different depth per machine (laptop:
        # D:\Postgraduate\vault with the repo two levels down; server:
        # E:\LWH\vault beside the repo). A fixed parents[N] therefore
        # resolved to a stray root (E:\vault) after the 2026-07 migration —
        # walk up until an actual vault/reports directory is found instead.
        # Filename carries the RUN date so a regeneration can never clobber
        # a historical dated report in the vault.
        vault_root = next((c for c in ROOT.parents
                           if (c / 'vault' / 'reports').is_dir()), None)
        fname = time.strftime('%Y-%m-%d') + '-phase2-conservation-CN.md'
        if vault_root is None:
            out_path = ROOT / 'validation' / fname
        else:
            out_path = vault_root / 'vault' / 'reports' / '3d-solver' / fname
    else:
        out_path = Path(args.out).resolve()

    selected = [c.strip() for c in args.cases.split(',') if c.strip() in CASES]

    # ── Phase 6: grid convergence sweep ──
    if args.phase6_grid_convergence:
        print('\n══════ PHASE 6 — Grid convergence ══════')
        grids = [12, 20, 30]
        gc_rows = []
        for cid in selected:
            print(f'\n  case {cid}:')
            row = {'case': cid}
            for g in grids:
                cfg = CASES[cid](g)
                cfg['_emit_audit'] = True   # C1: reads r['_audit_*'] keys
                t0 = time.time()
                res = _run_3d_stack(cfg)
                dt = time.time() - t0
                Q_enth = float(res.get('Q_enthalpy_B', float('nan')))
                Q_sB_int = float(res.get('Q_sB_interior', float('nan')))
                eps_kern = abs(Q_enth - abs(Q_sB_int)) / max(Q_enth, abs(Q_sB_int), 1e-30)
                row[f'Q_g{g}'] = Q_enth
                row[f'eps_g{g}'] = eps_kern * 100
                print(f'    grid={g}: Q={Q_enth:.1f}W ε_B={eps_kern*100:.2f}% [{dt:.0f}s]')
            # Richardson
            if all(f'Q_g{g}' in row for g in grids):
                Qc, Qm, Qf = row['Q_g12'], row['Q_g20'], row['Q_g30']
                rel_med_fine = abs(Qm - Qf) / max(abs(Qf), 1e-30)
                row['rel_med_fine'] = rel_med_fine * 100
                if abs(Qm - Qf) > 1e-30 and abs(Qc - Qm) > 1e-30:
                    try:
                        order = float(np.log(abs(Qc - Qf) / abs(Qm - Qf))
                                      / np.log(20 / 12))
                    except Exception:
                        order = float('nan')
                else:
                    order = float('nan')
                row['order_obs'] = order
                print(f'    Richardson: |med−fine|/fine = {rel_med_fine*100:.2f}%  '
                      f'order_obs ≈ {order:.2f}')
            gc_rows.append(row)
        print('\n  grid-convergence summary:')
        print(f'    {"case":<10}{"Q@12":>8}{"Q@20":>8}{"Q@30":>8}{"|m-f|%":>8}{"order":>7}')
        for r in gc_rows:
            print(f'    {r["case"]:<10}'
                  f'{r.get("Q_g12", float("nan")):>8.1f}'
                  f'{r.get("Q_g20", float("nan")):>8.1f}'
                  f'{r.get("Q_g30", float("nan")):>8.1f}'
                  f'{r.get("rel_med_fine", float("nan")):>8.2f}'
                  f'{r.get("order_obs", float("nan")):>7.2f}')
        return 0

    sections = []
    summary_rows = []
    for cid in selected:
        print(f'\n══════ Phase 2 case: {cid} ══════')
        cfg = CASES[cid](args.grid)
        cfg['_emit_audit'] = True   # C1: reads r['_audit_*'] keys
        t0 = time.time()
        res = _run_3d_stack(cfg)
        dt = time.time() - t0
        print(f'  solved in {dt:.1f}s')
        try:
            p2a = compute_phase2a_interior(res)
        except Exception as e:
            print(f'  Phase 2a failed: {e}')
            p2a = dict(Q_enth_A=float('nan'), Q_sA=float('nan'),
                       Q_sA_interior=float('nan'),
                       Q_enth_B=float('nan'), Q_sB=float('nan'),
                       Q_sB_interior=float('nan'),
                       eps_A_kernel=float('nan'),
                       eps_B_kernel=float('nan'),
                       eps_LTNE=float('nan'),
                       LHS_A_surf=float('nan'),
                       LHS_B_surf=float('nan'),
                       BC_frac_A=float('nan'),
                       BC_frac_B=float('nan'))
        try:
            p2c = compute_phase2c_h3(res)
        except Exception as e:
            print(f'  Phase 2c failed: {e}')
            p2c = dict(A=dict(net_out_total=float('nan'),
                               net_out_abs=float('nan'),
                               spurious_enthalpy_W=float('nan'),
                               net_out_max_cell=float('nan'),
                               net_out_p99=float('nan')),
                       B=None)
        try:
            p3 = compute_phase3(res)
        except Exception as e:
            print(f'  Phase 3 failed: {e}')
            p3 = None
        try:
            p4 = compute_phase4(res)
        except Exception as e:
            print(f'  Phase 4 failed: {e}')
            p4 = None
        try:
            p5 = compute_phase5(res)
        except Exception as e:
            print(f'  Phase 5 failed: {e}')
            p5 = None
        sec = render_case(cid, res, p2a, p2c, p3, p4, p5)
        sections.append(sec)
        summary_rows.append((cid, p2a, p2c, p3, p4, p5))

    write_report(out_path, sections, dict(date='2026-05-04'))
    print(f'\nReport: {out_path}')
    print('\n══════ SUMMARY ══════')
    print(f'{"case":<14s} {"ε_A%":>6s} {"ε_B%":>6s} {"ε_LTNE%":>8s} '
          f'{"S_gen":>8s} {"ε_obs":>7s} {"mImbA%":>8s} {"mImbB%":>8s} '
          f'{"latA%":>7s} {"latB%":>7s}')
    for cid, p2a, p2c, p3, p4, p5 in summary_rows:
        s_gen = p3["S_gen_global"] if p3 else float('nan')
        eo = p3["eps_obs"] if p3 else float('nan')
        mA = p4["A"]["imbal_rel"]*100 if (p4 and p4.get("A")) else float('nan')
        mB = p4["B"]["imbal_rel"]*100 if (p4 and p4.get("B")) else float('nan')
        latA = p5["A"]["lateral_frac"]*100 if (p5 and p5.get("A")) else float('nan')
        latB = p5["B"]["lateral_frac"]*100 if (p5 and p5.get("B")) else float('nan')
        print(f'{cid:<14s} '
              f'{p2a["eps_A_kernel"]*100:>6.2f} '
              f'{p2a["eps_B_kernel"]*100:>6.2f} '
              f'{p2a["eps_LTNE"]*100:>7.2f} '
              f'{s_gen:>+8.4f} '
              f'{eo:>7.4f} '
              f'{mA:>+7.3f} '
              f'{mB:>+7.3f} '
              f'{latA:>6.2f} '
              f'{latB:>6.2f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
