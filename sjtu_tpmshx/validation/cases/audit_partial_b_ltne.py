"""audit_partial_b_ltne.py — partial-B LTNE conservation audit (P1-P7).

⚠ ARCHIVAL: this is a post-mortem audit snapshot from 2026-05-04.
   Designed as a one-shot read-only diagnostic; **not for routine CI runs**.
   Per memory `feedback_partial_b_audit`, the issues it diagnosed have since
   been resolved (closure default 'none' from 2026-05-14; ε double-halving
   fixed at commit 02f091c). Keep for historical reference.

Read-only diagnostic. Runs Shanghai case 1 (B_area_frac = 0.20) twice — closure
"none" and closure "m4_effective_area" (p=0.67, mode=sqrt) — and emits the
P1-P7 markdown report demanded by the task spec.

No solver, M4, M3, K/cF, momentum, or closure formula is modified anywhere.
The audit reaches the SIMPLE solver internals via additive read-only exports
in run_calculation_3d's result dict (keys prefixed with "_audit_").

Goal: classify the residual partial-B fluid enthalpy imbalance / negative S_gen
into one of:
  (a) diagnostic m_dot / face-flux mismatch
  (b) boundary source pinning (BC layer-dominant Q_s)
  (c) outlet flux misweighting (mask vs actual outflow)
  (d) genuine LTNE discretisation non-conservation
  (e) sign convention / multi-cause (manual review)

Output: vault/reports/3d-solver/2026-05-04-partial-b-ltne-audit-CN.md.

Usage:
    python -u sjtu_tpmshx\\validation\\audit_partial_b_ltne.py
    python -u sjtu_tpmshx\\validation\\audit_partial_b_ltne.py --grid 15
"""
from __future__ import annotations
import argparse, sys, time, warnings
from pathlib import Path
from typing import Any
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
warnings.filterwarnings('ignore')

from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack
from sjtu_tpmshx.models.tpms_calc import air_density


# ── Shanghai case 1 partial-B baseline (mirror sweep_m4_baseline.py C1) ──
CASE1 = dict(
    label='shanghai_case1',
    L=0.182, H=0.042, Lz=0.042,
    u_A=2.0, u_B=4.0,
    T_inA=422.0, T_inB=322.0,
    P_inA=102325.0, P_inB=101325.0,
    partial=True,    # B_area_frac ≈ 0.20 (0.042 × 0.042 patch on 0.182 × 0.042)
)


def make_cfg(case: dict, closure: str, grid: int = 20) -> dict:
    """Build cfg matching sweep_m4_baseline geometry and properties.

    `closure` accepts:
        'none'                       — no correction
        'm4_effective_area'          — legacy 0D scalar (p=0.67, sqrt)
        'per_cell_chi_b_velocity'    — Phase 1 per-cell, velocity-threshold
        'per_cell_chi_b_extrude'     — Phase 1 per-cell, union-extrude
    """
    L, H, Lz = case['L'], case['H'], case['Lz']
    partial = case['partial']
    fB = dict(
        dir=3,
        in_ctr=0.154 if partial else 0.091,
        in_w=0.042 if partial else L,
        out_ctr=0.028 if partial else 0.091,
        out_w=0.042 if partial else L,
        in_z_ctr=0.021, in_z_w=0.042,
        out_z_ctr=0.021, out_z_w=0.042,
    )
    # ── parse closure tag → solver cfg keys ──
    closure_kw = dict()
    if closure == 'm4_effective_area':
        closure_kw = dict(partial_B_closure='m4_effective_area',
                           m4_eff_mode='sqrt', m4_exponent=0.67)
    elif closure == 'per_cell_chi_b_velocity':
        closure_kw = dict(partial_B_closure='per_cell_chi_b',
                           chi_B_method='velocity_threshold',
                           chi_B_threshold_frac=0.01,
                           chi_B_n_dilate=3, chi_B_n_smooth=2,
                           chi_B_floor=1e-3)
    elif closure == 'per_cell_chi_b_extrude':
        closure_kw = dict(partial_B_closure='per_cell_chi_b',
                           chi_B_method='union_extrude',
                           chi_B_n_taper=3, chi_B_floor=1e-3)
    elif closure == 'none':
        closure_kw = dict(partial_B_closure='none')
    else:
        # Pass-through: caller knows what they're doing.
        closure_kw = dict(partial_B_closure=closure)
    cfg = dict(
        L=L, H=H, Lz=Lz,
        Nx=grid, Ny=grid, Nz=grid,
        u_A=case['u_A'], u_B=case['u_B'],
        T_inA=case['T_inA'], T_inB=case['T_inB'],
        P_inA=case['P_inA'], P_inB=case['P_inB'],
        tpms_type='Gyroid', Lcell=7.0, t_wall=0.6, k_s=16.0, eps=0.85,
        fluid_A_cfg=dict(
            dir=0, in_ctr=0.021, in_w=0.042,
            out_ctr=0.021, out_w=0.042,
            in_z_ctr=0.021, in_z_w=0.042,
            out_z_ctr=0.021, out_z_w=0.042,
        ),
        fluid_B_cfg=fB,
        fluid_type_A='air', fluid_type_B='air',
        wall_refine_3d=False,
        _case_label=f"{case['label']}_{closure}",
        **closure_kw,
    )
    return cfg


# ──────────────────────────────────────────────────────────────────────────
# Geometry helpers
# ──────────────────────────────────────────────────────────────────────────

def _real_inlet_index(dir_code: int, shape: tuple) -> tuple:
    """Indexer for real-coord 1-cell inlet face (cells, not faces)."""
    Nx, Ny, Nz = shape
    return {
        0: (slice(0, 1), slice(None), slice(None)),
        1: (slice(Nx-1, Nx), slice(None), slice(None)),
        2: (slice(None), slice(0, 1), slice(None)),
        3: (slice(None), slice(Ny-1, Ny), slice(None)),
        4: (slice(None), slice(None), slice(0, 1)),
        5: (slice(None), slice(None), slice(Nz-1, Nz)),
    }[dir_code]


def _real_outlet_index(dir_code: int, shape: tuple) -> tuple:
    Nx, Ny, Nz = shape
    return {
        0: (slice(Nx-1, Nx), slice(None), slice(None)),
        1: (slice(0, 1), slice(None), slice(None)),
        2: (slice(None), slice(Ny-1, Ny), slice(None)),
        3: (slice(None), slice(0, 1), slice(None)),
        4: (slice(None), slice(None), slice(Nz-1, Nz)),
        5: (slice(None), slice(None), slice(0, 1)),
    }[dir_code]


def _bc_layer_mask(dir_code: int, shape: tuple) -> np.ndarray:
    Nx, Ny, Nz = shape
    m = np.zeros(shape, dtype=bool)
    m[_real_inlet_index(dir_code, shape)] = True
    return m


def _outlet_layer_mask(dir_code: int, shape: tuple) -> np.ndarray:
    Nx, Ny, Nz = shape
    m = np.zeros(shape, dtype=bool)
    m[_real_outlet_index(dir_code, shape)] = True
    return m


def _streamwise_axis_real(dir_code: int) -> int:
    return {0: 0, 1: 0, 2: 1, 3: 1, 4: 2, 5: 2}[dir_code]


def _extrude_face_to_volume(face_mask_2d: np.ndarray, dir_code: int,
                             shape: tuple) -> np.ndarray:
    """Broadcast a 2D inlet/outlet face mask over the streamwise axis to 3D.

    Real-coord face shapes:
      dir 0/1 → face is (Ny, Nz), extrude along Nx (axis 0)
      dir 2/3 → face is (Nx, Nz), extrude along Ny (axis 1)
      dir 4/5 → face is (Nx, Ny), extrude along Nz (axis 2)
    """
    Nx, Ny, Nz = shape
    axis = _streamwise_axis_real(dir_code)
    if axis == 0:
        return np.broadcast_to(face_mask_2d[None, :, :], shape).copy()
    if axis == 1:
        return np.broadcast_to(face_mask_2d[:, None, :], shape).copy()
    return np.broadcast_to(face_mask_2d[:, :, None], shape).copy()


# ──────────────────────────────────────────────────────────────────────────
# Solver-coord face flux helpers (mirror _face_flux_weights semantics)
# ──────────────────────────────────────────────────────────────────────────

def _solver_face_flux_2d(face: dict, which: str, eps_mode: str = 'physical',
                          chi_face: np.ndarray | None = None,
                          mask_face: np.ndarray | None = None) -> np.ndarray:
    """Compute face-cell mass flux array in solver coords.

    Solver convention: streamwise is solver y-axis. is_reverse swaps outlet ↔
    inlet (solver y=0 ↔ y=-1).

    Parameters
    ----------
    face : dict (one of result['_audit_sA_face'] / result['_audit_sB_face'])
    which : 'inlet' or 'outlet'  — REAL face semantics (auto-swapped per dir)
    eps_mode : 'physical' (no eps_f) or 'ltne' (× 0.5·eps[face])
    chi_face : optional 2D χ at this face
    mask_face : optional 2D weighting (e.g. inlet_frac/outlet_frac)

    Returns
    -------
    w : 2D ndarray of effective ρ·v·A (× eps × mask × chi as requested) [kg/s].
        Sum over w gives the same number `_face_flux_weights` returns.
    """
    dir_real = face['dir_real']
    is_reverse = dir_real in (1, 3, 5)
    v = face['v']  # solver staggered v: shape (Nx_sol, Ny_sol+1, Nz_sol)
    rho = face['rho']  # cell-centered: (Nx_sol, Ny_sol, Nz_sol)
    if which == 'outlet':
        if is_reverse:
            # real outlet ↔ solver y=0
            v_face = v[:, 0, :]
            rho_face = rho[:, 0, :]
            face_idx = 0
            mask_default = face.get('inlet_frac')
        else:
            v_face = v[:, -1, :]
            rho_face = rho[:, -1, :]
            face_idx = -1
            mask_default = face.get('outlet_frac')
    else:  # inlet
        if is_reverse:
            v_face = v[:, -1, :]
            rho_face = rho[:, -1, :]
            face_idx = -1
            mask_default = face.get('outlet_frac')
        else:
            v_face = v[:, 0, :]
            rho_face = rho[:, 0, :]
            face_idx = 0
            mask_default = face.get('inlet_frac')
    dx = face['dx'][:, None]
    dz = face['dz'][None, :]
    w = rho_face * np.abs(v_face) * dx * dz
    if eps_mode == 'ltne':
        eps = face.get('eps')
        if eps is not None:
            w = w * (0.5 * np.asarray(eps[:, face_idx, :], dtype=np.float64))
    used_mask = mask_face if mask_face is not None else mask_default
    if used_mask is not None:
        w = w * np.asarray(used_mask, dtype=np.float64)
    if chi_face is not None:
        w = w * np.asarray(chi_face, dtype=np.float64)
    return w


def _solver_signed_outflow_2d(face: dict) -> tuple[np.ndarray, np.ndarray]:
    """Mass flux magnitude through the REAL outlet face (per cell, kg/s).

    Returns (flux_mag_2d, area_2d). `flux_mag_2d` is `|ρ · v · A|` at every
    outlet-face cell — same sign convention as `_face_flux_weights` (which
    also uses `np.abs(v_face)`). For a converged SIMPLE solve there is no
    flow reversal at the outlet, so |·| is the correct outflow magnitude
    regardless of the solver-coord sign induced by `is_reverse`.
    """
    dir_real = face['dir_real']
    is_reverse = dir_real in (1, 3, 5)
    v = face['v']
    rho = face['rho']
    dx = face['dx'][:, None]; dz = face['dz'][None, :]
    if is_reverse:
        v_face = v[:, 0, :]
        rho_face = rho[:, 0, :]
    else:
        v_face = v[:, -1, :]
        rho_face = rho[:, -1, :]
    flux_mag = rho_face * np.abs(v_face) * dx * dz
    area = (np.ones_like(v_face) * dx * dz)
    return flux_mag.astype(np.float64), area.astype(np.float64)


def _outlet_T_in_solver_coords(face: dict, T_real: np.ndarray) -> np.ndarray:
    """Slice T at the real-outlet face and reshape into solver-face coords.

    T_real is in real (Nx, Ny, Nz). The face arrays are in solver coords with
    `solver_to_real_perm` mapping solver→real. We need the 2D face slice in
    solver-(cross1, cross2) order so element-wise products with v_face work.
    """
    perm = face['solver_to_real_perm']
    T_solver = np.ascontiguousarray(np.transpose(T_real, _inverse_perm(perm)))
    # T_solver shape == (Nx_sol, Ny_sol, Nz_sol). Real outlet ⇔ solver y=0
    # if is_reverse else y=-1.
    is_reverse = face['dir_real'] in (1, 3, 5)
    return T_solver[:, 0, :] if is_reverse else T_solver[:, -1, :]


def _inverse_perm(perm: tuple) -> tuple:
    """Inverse of a 3-axis permutation."""
    inv = [0, 0, 0]
    for i, p in enumerate(perm):
        inv[p] = i
    return tuple(inv)


# ──────────────────────────────────────────────────────────────────────────
# Audit blocks
# ──────────────────────────────────────────────────────────────────────────

def p1_signs(res: dict) -> dict:
    Q_A_enth = float(res.get('Q_enthalpy_A', float('nan')))
    Q_B_enth = float(res.get('Q_enthalpy_B', float('nan')))
    Q_sA = float(res.get('Q_sA', float('nan')))
    Q_sB = float(res.get('Q_sB', float('nan')))
    return dict(
        Q_A_enthalpy_pos_lost=Q_A_enth,    # |m·cp·ΔT|
        Q_B_enthalpy_pos_gained=Q_B_enth,  # |m·cp·ΔT|
        Q_sA_code_solid_to_A=Q_sA,        # ∫ h_vA(Ts−Ta) dV  (Ts<Ta ⇒ Q_sA<0)
        Q_sB_code_solid_to_B=Q_sB,        # ∫ h_vB(Ts−Tb) dV  (Ts>Tb ⇒ Q_sB>0)
        Q_A_to_solid=-Q_sA,                # derived sign-flip
        Q_solid_to_B=Q_sB,                 # identity
        closure_check_AtoSolid_minus_AEnth=(-Q_sA) - Q_A_enth,
        closure_check_solidToB_minus_BEnth=Q_sB - Q_B_enth,
        closure_check_AtoSolid_minus_solidToB=(-Q_sA) - Q_sB,
    )


def p2_face_flux_enthalpy(res: dict, case: dict) -> dict:
    """Compare Excel-m_dot enthalpy vs face-flux enthalpy for both fluids.

    Excel-m_dot:
       m_dot_excel = ρ_in · u_excel · A_active_face   (geometric area; same as
                                                       Excel harness target)
       T_out_unweighted = mean over geometric outlet face cells (mask>0.5)
       Q_excel = |m_dot_excel · cp · (T_in − T_out_unweighted)|

    Face-flux (already in result):
       m_dot_face   = `_audit_m_dot_*_simple` (LTNE-effective ε·ρ·v·A)
       T_out_face   = `T_A_out` / `T_B_out` (mass-flux-weighted)
       Q_face       = `Q_enthalpy_A` / `Q_enthalpy_B`
    """
    Ta = res['Ta']; Tb = res['Tb']
    fA = res['_audit_fA']; fB = res.get('_audit_fB')
    eps = res['_audit_eps']
    cp_A = res['_audit_cp_A']; cp_B = res.get('_audit_cp_B')
    T_inA = res['_audit_T_inA']; T_inB = res.get('_audit_T_inB')
    u_A_excel = res['_audit_u_A']; u_B_excel = res.get('_audit_u_B')
    P_inA = case['P_inA']; P_inB = case['P_inB']
    rho_A_in = float(air_density(T_inA, P_inA))
    rho_B_in = float(air_density(T_inB, P_inB)) if T_inB is not None else None

    sB_face = res.get('_audit_sB_face')

    # ── A side ──
    out_idx_A = _real_outlet_index(fA['dir'], Ta.shape)
    T_A_out_slab = Ta[out_idx_A]  # one of (1, Ny, Nz) etc.
    # Geometric mask in real coords for outlet of A (full-face for A).
    A_active_A = float(case['H'] * case['Lz'])  # H × Lz for fA dir=0
    m_dot_A_excel = rho_A_in * u_A_excel * A_active_A * 0.5 * eps  # LTNE ε/2
    T_A_out_unweighted = float(np.mean(T_A_out_slab))
    Q_A_excel = abs(m_dot_A_excel * cp_A * (T_inA - T_A_out_unweighted))
    Q_A_face = float(res.get('Q_enthalpy_A', float('nan')))
    rel_A = abs(Q_A_excel - Q_A_face) / max(Q_A_face, 1e-30)

    # ── B side ──
    out_B = dict(Q_excel=float('nan'), Q_face=float('nan'),
                 m_dot_excel=float('nan'), m_dot_face=float('nan'),
                 T_out_unweighted=float('nan'), T_out_weighted=float('nan'),
                 rel=float('nan'))
    if sB_face is not None and rho_B_in is not None:
        out_idx_B = _real_outlet_index(fB['dir'], Tb.shape)
        T_B_out_slab = Tb[out_idx_B]
        # B active area on inlet face (geometric Excel target):
        A_active_B = float(fB['in_w'] * fB['in_z_w'])
        m_dot_B_excel = rho_B_in * u_B_excel * A_active_B * 0.5 * eps
        T_B_out_unweighted = float(np.mean(T_B_out_slab))
        Q_B_excel = abs(m_dot_B_excel * cp_B * (T_inB - T_B_out_unweighted))
        Q_B_face = float(res.get('Q_enthalpy_B', float('nan')))
        out_B = dict(
            Q_excel=Q_B_excel,
            Q_face=Q_B_face,
            m_dot_excel=m_dot_B_excel,
            m_dot_face=float(res['_audit_m_dot_B_simple']),
            T_out_unweighted=T_B_out_unweighted,
            T_out_weighted=float(res['T_B_out']),
            rel=abs(Q_B_excel - Q_B_face) / max(Q_B_face, 1e-30),
        )

    return dict(
        A=dict(Q_excel=Q_A_excel, Q_face=Q_A_face,
               m_dot_excel=m_dot_A_excel,
               m_dot_face=float(res['_audit_m_dot_A_simple']),
               T_out_unweighted=T_A_out_unweighted,
               T_out_weighted=float(res['T_A_out']),
               rel=rel_A),
        B=out_B,
    )


def p3_source_partition(res: dict) -> dict:
    Ta = res['Ta']; Tb = res['Tb']; Ts = res['Ts']
    h_vA = res['h_vA_field']; h_vB = res['h_vB_field']
    dx = res['dx']; dy = res['dy']; dz = res['dz']
    fA = res['_audit_fA']; fB = res.get('_audit_fB')
    Nx, Ny, Nz = Ta.shape
    cell_vol = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]
    integ_A = h_vA * (Ts - Ta) * cell_vol
    integ_B = h_vB * (Ts - Tb) * cell_vol if fB is not None else np.zeros_like(integ_A)

    bc_in_A = _bc_layer_mask(fA['dir'], Ta.shape)
    bc_out_A = _outlet_layer_mask(fA['dir'], Ta.shape)
    interior_A = ~(bc_in_A | bc_out_A)

    Q_sA_all = float(np.sum(integ_A))
    Q_sA_interior = float(np.sum(integ_A[interior_A]))
    Q_sA_inlet = float(np.sum(integ_A[bc_in_A]))
    Q_sA_outlet = float(np.sum(integ_A[bc_out_A]))

    out = dict(
        A=dict(all=Q_sA_all, interior=Q_sA_interior,
               inlet_layer=Q_sA_inlet, outlet_layer=Q_sA_outlet,
               partition_residual=Q_sA_all - (Q_sA_interior + Q_sA_inlet + Q_sA_outlet)),
    )
    if fB is not None:
        bc_in_B = _bc_layer_mask(fB['dir'], Ta.shape)
        bc_out_B = _outlet_layer_mask(fB['dir'], Ta.shape)
        interior_B = ~(bc_in_B | bc_out_B)
        Q_sB_all = float(np.sum(integ_B))
        Q_sB_interior = float(np.sum(integ_B[interior_B]))
        Q_sB_inlet = float(np.sum(integ_B[bc_in_B]))
        Q_sB_outlet = float(np.sum(integ_B[bc_out_B]))

        # Partial-B regions (extruded along streamwise axis)
        ltne_mask_B = res.get('_audit_ltne_mask_B')
        in_mask_B = res.get('_audit_in_mask_B')
        out_mask_B = res.get('_audit_out_mask_B')
        Q_sB_part = Q_sB_ghost = Q_sB_proj = float('nan')
        if ltne_mask_B is not None:
            mask_3d = _extrude_face_to_volume(
                (ltne_mask_B > 0.5).astype(np.float64),
                fB['dir'], Ta.shape)
            participating = mask_3d > 0.5
            Q_sB_part = float(np.sum(integ_B[participating]))
            Q_sB_ghost = float(np.sum(integ_B[~participating]))
            # mask projected = union of inlet ∪ outlet (geometric envelope)
            if in_mask_B is not None and out_mask_B is not None:
                proj_face_2d = ((in_mask_B > 0.5) | (out_mask_B > 0.5)).astype(np.float64)
                proj_3d = _extrude_face_to_volume(proj_face_2d, fB['dir'], Ta.shape)
                Q_sB_proj = float(np.sum(integ_B[proj_3d > 0.5]))

        out['B'] = dict(
            all=Q_sB_all, interior=Q_sB_interior,
            inlet_layer=Q_sB_inlet, outlet_layer=Q_sB_outlet,
            partition_residual=Q_sB_all - (Q_sB_interior + Q_sB_inlet + Q_sB_outlet),
            participating=Q_sB_part, ghost=Q_sB_ghost, mask_projected=Q_sB_proj,
        )
    else:
        out['B'] = None
    return out


def p4_interior_closure(p2: dict, p3: dict) -> dict:
    return dict(
        A=dict(all=p3['A']['all'], interior=p3['A']['interior'],
               face_flux_Q=p2['A']['Q_face']),
        B=(dict(all=p3['B']['all'], interior=p3['B']['interior'],
                face_flux_Q=p2['B']['Q_face']) if p3['B'] is not None else None),
    )


def p5_outlet_distribution(res: dict) -> dict:
    sB_face = res.get('_audit_sB_face')
    if sB_face is None:
        return None
    Tb = res['Tb']
    fB = res['_audit_fB']
    # ── pick the correct real-outlet patch mask in solver coords ──
    # `_build_partial_masks` swaps caller's in_mask ↔ out_mask when
    # is_reverse=True (run_calculation_3d.py:744-746). So:
    #   - non-reverse: caller's out_mask_B = real-outlet patch
    #   - reverse:     caller's in_mask_B  = real-outlet patch
    # This mirrors `_face_flux_weights`, which uses solver.inlet_frac
    # for real_outlet when is_reverse (= caller's in_mask_B).
    is_reverse = fB['dir'] in (1, 3, 5)
    if is_reverse:
        out_mask_B = res.get('_audit_in_mask_B')
    else:
        out_mask_B = res.get('_audit_out_mask_B')

    # Geometric mask fraction (solver coords)
    if out_mask_B is None:
        return None
    dx = sB_face['dx'][:, None]; dz = sB_face['dz'][None, :]
    area_2d = (np.ones_like(out_mask_B) * dx * dz)
    A_total = float(np.sum(area_2d))
    A_mask = float(np.sum(area_2d * (out_mask_B > 0.5)))
    mask_fraction = A_mask / max(A_total, 1e-30)

    # T_B_out — the existing weighted (chi) value plus an unweighted full-face
    # mean computed inline.
    T_B_out_weighted = float(res['T_B_out'])
    # Full-face T_out: just unweighted mean across full real outlet face slice
    out_idx_B = _real_outlet_index(fB['dir'], Tb.shape)
    T_B_out_face = Tb[out_idx_B]
    T_B_out_full_face = float(np.mean(T_B_out_face))
    # Masked (chi-free) — already exposed indirectly via _face_flux_weights;
    # recompute inline via solver-coord T at outlet face.
    T_B_out_solver_face = _outlet_T_in_solver_coords(sB_face, Tb)
    w_masked = _solver_face_flux_2d(sB_face, 'outlet', eps_mode='ltne')
    tot_m = float(np.sum(w_masked))
    T_B_out_masked = (float(np.sum(T_B_out_solver_face * w_masked) / tot_m)
                      if tot_m > 1e-30 else float('nan'))

    # m_dot variants
    m_dot_B_out_masked = float(np.sum(_solver_face_flux_2d(
        sB_face, 'outlet', eps_mode='physical')))  # uses default mask
    m_dot_B_out_fullface = float(np.sum(_solver_face_flux_2d(
        sB_face, 'outlet', eps_mode='physical', mask_face=np.ones_like(out_mask_B))))

    # Actual outflow distribution (mass flux magnitude per cell)
    flux_mag_2d, area_outlet_2d = _solver_signed_outflow_2d(sB_face)
    pos_total = float(np.sum(flux_mag_2d))
    pos_inside = float(np.sum(flux_mag_2d * (out_mask_B > 0.5)))
    inside_frac = pos_inside / max(pos_total, 1e-30)
    outside_frac = 1.0 - inside_frac if pos_total > 1e-30 else 0.0

    return dict(
        B_out_mask_fraction=mask_fraction,
        T_B_out_masked=T_B_out_masked,
        T_B_out_full_face=T_B_out_full_face,
        T_B_out_weighted_chi=T_B_out_weighted,
        m_dot_B_out_masked=m_dot_B_out_masked,
        m_dot_B_out_fullface=m_dot_B_out_fullface,
        outflow_inside_mask_fraction=inside_frac,
        outflow_outside_mask_fraction=outside_frac,
    )


def p6_mass_flux(res: dict, case: dict) -> dict:
    sA_face = res['_audit_sA_face']
    sB_face = res.get('_audit_sB_face')
    eps = res['_audit_eps']

    # A target Excel m_dot (LTNE-effective so it matches sum)
    rho_A_in = float(air_density(res['_audit_T_inA'], case['P_inA']))
    A_face_A = case['H'] * case['Lz']  # full face for A (dir=0)
    m_dot_A_target = rho_A_in * res['_audit_u_A'] * A_face_A * 0.5 * eps

    m_dot_A_in = float(np.sum(_solver_face_flux_2d(
        sA_face, 'inlet', eps_mode='ltne')))
    m_dot_A_out = float(np.sum(_solver_face_flux_2d(
        sA_face, 'outlet', eps_mode='ltne')))
    imbal_A = (m_dot_A_in - m_dot_A_out) / max(abs(m_dot_A_in), 1e-30)

    out = dict(A=dict(target=m_dot_A_target, in_face=m_dot_A_in,
                       out_face=m_dot_A_out, imbalance=imbal_A))
    if sB_face is not None:
        rho_B_in = float(air_density(res['_audit_T_inB'], case['P_inB']))
        fB = res['_audit_fB']
        A_face_B = fB['in_w'] * fB['in_z_w']
        m_dot_B_target = rho_B_in * res['_audit_u_B'] * A_face_B * 0.5 * eps
        m_dot_B_in = float(np.sum(_solver_face_flux_2d(
            sB_face, 'inlet', eps_mode='ltne')))
        m_dot_B_out = float(np.sum(_solver_face_flux_2d(
            sB_face, 'outlet', eps_mode='ltne')))
        imbal_B = (m_dot_B_in - m_dot_B_out) / max(abs(m_dot_B_in), 1e-30)
        out['B'] = dict(target=m_dot_B_target, in_face=m_dot_B_in,
                        out_face=m_dot_B_out, imbalance=imbal_B)
    else:
        out['B'] = None
    return out


# ──────────────────────────────────────────────────────────────────────────
# Diagnosis heuristic
# ──────────────────────────────────────────────────────────────────────────

def diagnose(p1: dict, p2: dict, p3: dict, p4: dict,
             p5: dict | None, p6: dict) -> tuple[str, str]:
    """Return (category, recommendation).

    Cause hierarchy (checked in this order; first match wins):

      (e1) ghost-B LTNE diffusion contamination
           — Q_sB_ghost / |Q_sB_all| > 0.20 AND T_B_out_full_face is more than
             a few K above T_B_out_masked, OR Q_enth_B exceeds Q_solid_to_B
             by >30 % even when |Q_sA_int + Q_sB_int| closes < 5 %.
           Symptom: stagnant cells outside the B participating region heat
           up via h_vB·(Ts − Tb), then leak into the active flow channel
           through the ε_f·k_f·∇²Tb diffusion term, raising T_B_out beyond
           what the actual h_vB·(Ts − Tb) source budget can supply.
      (a)  diagnostic Excel-m_dot vs face-flux mismatch (informational only)
      (b)  boundary source pinning (BC-layer Q_s dominant)
      (c)  outlet flux misweighting (geometric mask vs actual outflow)
      (d)  true LTNE discretisation non-conservation
      (e)  sign / multi-cause manual review fallback
    """
    excel_face_A = p2['A']['rel']
    excel_face_B = p2['B']['rel'] if p2['B']['Q_face'] == p2['B']['Q_face'] else float('nan')

    # internal LTNE closure (interior only)
    Q_sA_int = p3['A']['interior']
    Q_sB_int = p3['B']['interior'] if p3['B'] is not None else 0.0
    Q_sA_all = p3['A']['all']
    Q_sB_all = p3['B']['all'] if p3['B'] is not None else 0.0

    interior_closure = abs(Q_sA_int + Q_sB_int) / max(abs(Q_sA_int), abs(Q_sB_int), 1e-30)
    all_closure = abs(Q_sA_all + Q_sB_all) / max(abs(Q_sA_all), abs(Q_sB_all), 1e-30)

    # ── ghost-B fraction
    Q_sB_ghost = (p3['B']['ghost'] if p3['B'] is not None else 0.0)
    ghost_frac = (abs(Q_sB_ghost) / max(abs(Q_sB_all), 1e-30)
                  if p3['B'] is not None else 0.0)

    # ── Q_enth_B vs Q_solid_to_B closure (the headline imbalance)
    Q_solid_to_B = p1.get('Q_solid_to_B', 0.0)
    Q_B_enth = p1.get('Q_B_enthalpy_pos_gained', 0.0)
    enth_solid_gap = abs(Q_B_enth - Q_solid_to_B) / max(abs(Q_B_enth), abs(Q_solid_to_B), 1e-30)

    rules = []

    # (e1) ghost-B contamination — most informative for partial-B
    if (ghost_frac > 0.20 and enth_solid_gap > 0.30):
        cat = 'ghost-B LTNE diffusion contamination'
        rec = (
            f"{ghost_frac*100:.0f}% of |Q_sB| comes from cells outside the B "
            f"participating region (ghost cells), and Q_enth_B exceeds "
            f"Q_solid_to_B by {enth_solid_gap*100:.0f}%. Stagnant ghost-B "
            f"cells equilibrate with hot solid via h_vB·(Ts − Tb), then leak "
            f"that heat into the active flow channel through the ε_f·k_f·∇²Tb "
            f"diffusion term, inflating T_B_out beyond what the local source "
            f"budget can sustain. Mitigations to investigate (NOT applied "
            f"here): (i) zero h_vB outside the B participating region; "
            f"(ii) zero ε_f·k_f for fluid-B in ghost cells (no diffusion path "
            f"from stagnant zone into flow channel); (iii) report "
            f"Q_solid_to_B as the primary B-side metric instead of Q_enth_B.")
        rules.append(f'rule (e1): ghost_frac={ghost_frac:.3f} '
                     f'enth_solid_gap={enth_solid_gap:.3f}')
        return cat, '\n'.join(rules + [rec])

    if (excel_face_A > 0.05) or (excel_face_B == excel_face_B and excel_face_B > 0.05):
        cat = 'diagnostic m_dot/face-flux mismatch'
        rec = ('Excel-m_dot diagnostic disagrees with the face-flux Q by >5%. '
               'The historical imbalance complaint is a diagnostic-convention '
               'artefact. Recommend reporting Q_face as the authoritative '
               'enthalpy metric and treating Excel-m_dot as a sanity reference.')
        rules.append(f'rule (a): excel/face rel A={excel_face_A:.3f} B={excel_face_B:.3f}')
    elif (interior_closure < 0.05) and (all_closure > 0.10):
        cat = 'boundary source pinning'
        rec = ('Q_s interior closes to <5% but all-cells closes >10% — Dirichlet '
               'inlet/outlet T pinning creates artificial h_v·(Ts−T_pin) '
               'contributions. Recommend reporting Q_s_interior as primary; '
               'consider zero-flux outlet T or removing inlet-layer h_v from '
               'the source integral diagnostic.')
        rules.append(f'rule (b): interior_close={interior_closure:.3f} '
                     f'all_close={all_closure:.3f}')
    elif (p5 is not None and p5['outflow_outside_mask_fraction'] > 0.05
          and abs(p5['T_B_out_full_face'] - p5['T_B_out_masked']) > 1.0):
        cat = 'outlet flux misweighting'
        rec = ('A non-trivial fraction of outflow leaves outside the geometric '
               'B_out mask, and the full-face vs masked T_B_out differ by >1K. '
               'Recommend replacing the geometric mask in T_B_out with an '
               'actual-outflow weighting (positive ρ·v at outlet, no mask).')
        rules.append(f"rule (c): outside_frac={p5['outflow_outside_mask_fraction']:.3f}")
    elif interior_closure > 0.01:
        cat = 'true LTNE discretisation non-conservation'
        rec = ('Even after BC layer exclusion, |Q_sA_int + Q_sB_int| / max > 1%. '
               'This points to a real discretisation defect (face-flux '
               'inconsistency, advection-diffusion balance, or per-cell h_v '
               'asymmetry). Inspect the kernel residual on participating cells; '
               'consider a NET_OUT-corrected variant on a coarse grid.')
        rules.append(f'rule (d): interior_close={interior_closure:.3f}')
    else:
        cat = 'sign convention / multi-cause (manual review)'
        rec = ('No single rule fired. Inspect P1 sign-closure values and the '
               'P3 partition table; the residual may be a combination of '
               'small effects (e.g. mass imbalance + slight χ_B leakage). '
               'Re-run the audit on a normal-Re full-face case as a control.')
        rules.append('no rule fired')

    return cat, '\n'.join(rules + [rec])


# ──────────────────────────────────────────────────────────────────────────
# Markdown report
# ──────────────────────────────────────────────────────────────────────────

def _fmt(x: Any, prec: int = 4) -> str:
    if isinstance(x, float):
        if x != x:  # NaN
            return 'nan'
        if abs(x) >= 1e6 or (abs(x) < 1e-3 and x != 0.0):
            return f'{x:.{prec}e}'
        return f'{x:.{prec}f}'
    return str(x)


def render_variant(label: str, case: dict, res: dict) -> str:
    p1 = p1_signs(res)
    p2 = p2_face_flux_enthalpy(res, case)
    p3 = p3_source_partition(res)
    p4 = p4_interior_closure(p2, p3)
    p5 = p5_outlet_distribution(res)
    p6 = p6_mass_flux(res, case)
    cat, rec = diagnose(p1, p2, p3, p4, p5, p6)

    lines = []
    lines.append(f'\n## Variant: {label}\n')
    lines.append(f'- closure = `{case.get("_closure_used", "?")}`')
    lines.append(f'- Shanghai case 1, B_area_frac ≈ 0.20, grid = '
                 f'{res["Ta"].shape}\n')

    # ── P1 ──
    lines.append('### P1 sign convention\n')
    lines.append(f"- Q_A_enthalpy (positive heat lost by hot fluid A): "
                 f"`{_fmt(p1['Q_A_enthalpy_pos_lost'], 2)} W`")
    lines.append(f"- Q_B_enthalpy (positive heat gained by cold fluid B): "
                 f"`{_fmt(p1['Q_B_enthalpy_pos_gained'], 2)} W`")
    lines.append(f"- Q_sA_code = ∫ h_vA(Ts−Ta) dV (solid → A): "
                 f"`{_fmt(p1['Q_sA_code_solid_to_A'], 2)} W`  "
                 f"(expect < 0 because Ts < Ta on hot side)")
    lines.append(f"- Q_sB_code = ∫ h_vB(Ts−Tb) dV (solid → B): "
                 f"`{_fmt(p1['Q_sB_code_solid_to_B'], 2)} W`  "
                 f"(expect > 0 because Ts > Tb on cold side)")
    lines.append(f"- Q_A_to_solid = −Q_sA_code = `{_fmt(p1['Q_A_to_solid'], 2)} W`")
    lines.append(f"- Q_solid_to_B = +Q_sB_code = `{_fmt(p1['Q_solid_to_B'], 2)} W`")
    lines.append('- Expected closures:')
    lines.append('    - `Q_A_enthalpy ≈ Q_A_to_solid`')
    lines.append('    - `Q_B_enthalpy ≈ Q_solid_to_B`')
    lines.append('    - `Q_A_to_solid ≈ Q_solid_to_B`')
    lines.append('- Closure residuals:')
    lines.append(f"    - `Q_A_to_solid − Q_A_enthalpy = {_fmt(p1['closure_check_AtoSolid_minus_AEnth'], 2)} W`")
    lines.append(f"    - `Q_solid_to_B − Q_B_enthalpy = {_fmt(p1['closure_check_solidToB_minus_BEnth'], 2)} W`")
    lines.append(f"    - `Q_A_to_solid − Q_solid_to_B = {_fmt(p1['closure_check_AtoSolid_minus_solidToB'], 2)} W`\n")

    # ── P2 ──
    lines.append('### P2 face-flux enthalpy\n')
    lines.append('| quantity | Excel-m_dot version | face-flux version | rel diff |')
    lines.append('|----------|---------------------|-------------------|----------|')
    a = p2['A']
    lines.append(f"| Q_A | {_fmt(a['Q_excel'], 2)} W | {_fmt(a['Q_face'], 2)} W | "
                 f"{_fmt(a['rel']*100, 2)} % |")
    b = p2['B']
    lines.append(f"| Q_B | {_fmt(b['Q_excel'], 2)} W | {_fmt(b['Q_face'], 2)} W | "
                 f"{_fmt(b['rel']*100, 2) if b['rel']==b['rel'] else 'n/a'} % |")
    lines.append('')
    lines.append('| side | m_dot_excel | m_dot_face | T_out_unweighted | T_out_weighted |')
    lines.append('|------|------------|-----------|------------------|----------------|')
    lines.append(f"| A | {_fmt(a['m_dot_excel'], 5)} | {_fmt(a['m_dot_face'], 5)} | "
                 f"{_fmt(a['T_out_unweighted'], 2)} K | {_fmt(a['T_out_weighted'], 2)} K |")
    lines.append(f"| B | {_fmt(b['m_dot_excel'], 5)} | {_fmt(b['m_dot_face'], 5)} | "
                 f"{_fmt(b['T_out_unweighted'], 2)} K | {_fmt(b['T_out_weighted'], 2)} K |")
    lines.append('')

    # ── P3 ──
    lines.append('### P3 boundary/source audit\n')
    lines.append('| region | Q_source W | fraction of |all| |')
    lines.append('|--------|------------|---------------------|')
    for tag, val in [('A all cells', p3['A']['all']),
                     ('A interior only', p3['A']['interior']),
                     ('A inlet layer', p3['A']['inlet_layer']),
                     ('A outlet layer', p3['A']['outlet_layer'])]:
        frac = val / max(abs(p3['A']['all']), 1e-30)
        lines.append(f"| {tag} | {_fmt(val, 2)} | {_fmt(frac, 4)} |")
    if p3['B'] is not None:
        denomB = max(abs(p3['B']['all']), 1e-30)
        for tag, val in [('B all cells', p3['B']['all']),
                         ('B interior only', p3['B']['interior']),
                         ('B inlet layer', p3['B']['inlet_layer']),
                         ('B outlet layer', p3['B']['outlet_layer']),
                         ('B participating region', p3['B']['participating']),
                         ('B ghost region', p3['B']['ghost']),
                         ('B mask projected region', p3['B']['mask_projected'])]:
            frac = (val / denomB) if val == val else float('nan')
            lines.append(f"| {tag} | {_fmt(val, 2)} | {_fmt(frac, 4)} |")
    lines.append(f"\n- Partition residual A = "
                 f"`{_fmt(p3['A']['partition_residual'], 4)} W` "
                 f"(should be ≈ 0)")
    if p3['B'] is not None:
        lines.append(f"- Partition residual B = "
                     f"`{_fmt(p3['B']['partition_residual'], 4)} W`\n")

    # ── P4 ──
    lines.append('### P4 interior source closure\n')
    lines.append('| quantity | all cells | interior only | face-flux Q |')
    lines.append('|----------|-----------|---------------|-------------|')
    a4 = p4['A']
    lines.append(f"| Q_sA | {_fmt(a4['all'], 2)} | {_fmt(a4['interior'], 2)} | "
                 f"{_fmt(a4['face_flux_Q'], 2)} |")
    if p4['B'] is not None:
        b4 = p4['B']
        lines.append(f"| Q_sB | {_fmt(b4['all'], 2)} | {_fmt(b4['interior'], 2)} | "
                     f"{_fmt(b4['face_flux_Q'], 2)} |")
    lines.append('')

    # ── P5 ──
    lines.append('### P5 outlet flux distribution\n')
    if p5 is not None:
        lines.append('| quantity | value |')
        lines.append('|----------|-------|')
        lines.append(f"| B_out_mask_fraction | {_fmt(p5['B_out_mask_fraction'], 4)} |")
        lines.append(f"| T_B_out_masked (chi-free) | {_fmt(p5['T_B_out_masked'], 2)} K |")
        lines.append(f"| T_B_out_weighted_chi (production) | {_fmt(p5['T_B_out_weighted_chi'], 2)} K |")
        lines.append(f"| T_B_out_full_face (no mask) | {_fmt(p5['T_B_out_full_face'], 2)} K |")
        lines.append(f"| m_dot_B_out_masked | {_fmt(p5['m_dot_B_out_masked'], 5)} kg/s |")
        lines.append(f"| m_dot_B_out_fullface | {_fmt(p5['m_dot_B_out_fullface'], 5)} kg/s |")
        lines.append(f"| outflow_inside_mask_fraction | {_fmt(p5['outflow_inside_mask_fraction'], 4)} |")
        lines.append(f"| outflow_outside_mask_fraction | {_fmt(p5['outflow_outside_mask_fraction'], 4)} |")
    else:
        lines.append('_no Fluid B in this run._')
    lines.append('')

    # ── P6 ──
    lines.append('### P6 mass/flux consistency\n')
    lines.append('| fluid | target | face_in | face_out | imbalance |')
    lines.append('|-------|--------|---------|----------|-----------|')
    a6 = p6['A']
    lines.append(f"| A | {_fmt(a6['target'], 5)} | {_fmt(a6['in_face'], 5)} | "
                 f"{_fmt(a6['out_face'], 5)} | {_fmt(a6['imbalance']*100, 3)} % |")
    if p6['B'] is not None:
        b6 = p6['B']
        lines.append(f"| B | {_fmt(b6['target'], 5)} | {_fmt(b6['in_face'], 5)} | "
                     f"{_fmt(b6['out_face'], 5)} | {_fmt(b6['imbalance']*100, 3)} % |")
    lines.append('')

    # ── Diagnosis ──
    lines.append('### Diagnosis\n')
    lines.append(f"- **Main cause of apparent LTNE imbalance:** {cat}")
    lines.append('- **Recommended fix / interpretation:**')
    for ln in rec.splitlines():
        lines.append(f'  > {ln}')
    lines.append('')

    return '\n'.join(lines), dict(p1=p1, p2=p2, p3=p3, p4=p4, p5=p5, p6=p6,
                                   diagnosis=cat, recommendation=rec)


def write_report(out_path: Path, sections: list, header_meta: dict) -> None:
    lines = []
    lines.append('# Partial-B LTNE Conservation Audit (P1–P7)\n')
    lines.append(f"- Date: {header_meta['date']}")
    lines.append("- Case: Shanghai case 1, B_area_frac ≈ 0.20")
    lines.append(f"- Grid: Nx=Ny=Nz={header_meta['grid']}")
    lines.append("- Audit script: `sjtu_tpmshx/validation/cases/audit_partial_b_ltne.py`")
    lines.append("- Result-dict additive exports: keys prefixed `_audit_*` "
                 "in `sjtu_tpmshx/solvers/backends/python/three_d/runtime.py`\n")
    lines.append('## Scope\n')
    lines.append('- Read-only audit. No solver, M4, M3, K/cF, momentum, or '
                 'closure formula was modified.')
    lines.append('- Two variants run: closure=`none` and '
                 'closure=`m4_effective_area` (p=0.67, mode=sqrt).')
    lines.append('- Goal: classify the residual partial-B fluid enthalpy '
                 'imbalance. No fix is applied.\n')
    lines.append('## Sign convention recap\n')
    lines.append('- Q_A_enthalpy = `|m_dot_A · cp_A · (T_inA − T_A_out)|` — '
                 'positive heat **lost** by hot fluid A.')
    lines.append('- Q_B_enthalpy = `|m_dot_B · cp_B · (T_inB − T_B_out)|` — '
                 'positive heat **gained** by cold fluid B.')
    lines.append('- Q_sA_code   = `∫ h_vA · (Ts − Ta) · dV` — current code '
                 'convention (solid → A).')
    lines.append('- Q_sB_code   = `∫ h_vB · (Ts − Tb) · dV` — current code '
                 'convention (solid → B).')
    lines.append('- Therefore `Q_A_to_solid := −Q_sA_code`, '
                 '`Q_solid_to_B := +Q_sB_code`.')
    lines.append('- Expected steady-state closure: '
                 '`Q_A_enthalpy ≈ Q_A_to_solid ≈ Q_solid_to_B ≈ Q_B_enthalpy`.\n')

    for sec in sections:
        lines.append(sec)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text('\n'.join(lines), encoding='utf-8')


# ──────────────────────────────────────────────────────────────────────────
# Self-consistency assertions
# ──────────────────────────────────────────────────────────────────────────

def _assert_self_consistency(payload: dict) -> None:
    p3 = payload['p3']
    res_A = abs(p3['A']['partition_residual'])
    denom_A = abs(p3['A']['all']) + 1e-30
    assert res_A / denom_A < 1e-6, (
        f"A source partition incomplete: residual={res_A} ({res_A/denom_A:.2e})")
    if p3['B'] is not None:
        res_B = abs(p3['B']['partition_residual'])
        denom_B = abs(p3['B']['all']) + 1e-30
        assert res_B / denom_B < 1e-6, (
            f"B source partition incomplete: residual={res_B} "
            f"({res_B/denom_B:.2e})")
    p5 = payload.get('p5')
    if p5 is not None:
        s = p5['outflow_inside_mask_fraction'] + p5['outflow_outside_mask_fraction']
        # only enforce when outflow is non-trivial
        if (p5['outflow_inside_mask_fraction'] + p5['outflow_outside_mask_fraction']) > 1e-6:
            assert abs(s - 1.0) < 1e-6 or s == 0.0, (
                f"outflow inside+outside fractions ≠ 1: {s}")


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--grid', type=int, default=20,
                    help='Nx=Ny=Nz cubic grid (default 20)')
    ap.add_argument('--out', type=str, default=None,
                    help='Output markdown path. Default = '
                         'vault/reports/3d-solver/2026-05-04-partial-b-ltne-audit-CN.md')
    ap.add_argument('--variants', type=str, default='none,m4_effective_area',
                    help='Comma-separated closure variants to run.')
    args = ap.parse_args()

    if args.out is None:
        # ROOT = …/Postgraduate/Homogenize/SJTU-TPMSHX/sjtu_tpmshx
        # parents[0]=SJTU-TPMSHX, parents[1]=Homogenize, parents[2]=Postgraduate
        proj_root = ROOT.parents[2]
        out_path = proj_root / 'vault' / 'reports' / '3d-solver' \
                            / '2026-05-04-partial-b-ltne-audit-CN.md'
    else:
        out_path = Path(args.out).resolve()

    sections = []
    payload_all = []
    for closure in [v.strip() for v in args.variants.split(',') if v.strip()]:
        print(f"\n══════ AUDIT VARIANT: closure={closure} ══════")
        cfg = make_cfg(CASE1, closure, grid=args.grid)
        cfg['_closure_used'] = closure
        case_with_closure = dict(CASE1)
        case_with_closure['_closure_used'] = closure
        cfg['_emit_audit'] = True   # C1: this audit reads r['_audit_*'] keys
        t0 = time.time()
        res = _run_3d_stack(cfg)
        dt = time.time() - t0
        print(f"  solved in {dt:.1f}s")

        sec, payload = render_variant(closure, case_with_closure, res)
        sections.append(sec)
        payload_all.append((closure, payload))
        try:
            _assert_self_consistency(payload)
            print("  self-consistency OK")
        except AssertionError as e:
            print(f"  ⚠ self-consistency FAILED: {e}")

    write_report(out_path, sections, dict(
        date='2026-05-04', grid=args.grid))
    print(f"\nReport written: {out_path}")

    print('\n══════ DIAGNOSIS SUMMARY ══════')
    for closure, payload in payload_all:
        print(f"  closure={closure:<22s} → {payload['diagnosis']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
