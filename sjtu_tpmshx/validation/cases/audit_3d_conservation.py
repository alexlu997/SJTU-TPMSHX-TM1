"""3D LTNE conservation audit of the current model on synthetic T1–T6 cases.

Checks the existing strict discrete certificate and retains the other audit
diagnostics. Historical reports keep their original conservation definitions.

Conservation diagnostic blocks:

  Phase 2a — current full-control-volume discrete energy certificate
      Reuses the solver's global and maximum-cell residuals, including
      physical inlet face advection and half-cell Dirichlet diffusion.
      Both residuals must be < 1 % per active fluid, as in the retained
      strict-conservation tests. The full-volume LTNE source balance keeps
      its < 1 % gate. Missing/nonfinite certificates fail.
      The former 5 % interior-layer heuristic and guessed-temperature-mask
      surface budget are retired; old reports retain their original meaning.
      This is a numerical certificate, not independent experimental validation.

  Phase 2c — per-cell mass-imbalance audit (H3 test)
      Computes per-cell NET_OUT_α = Σ_face F_face_advective_α and the
      associated spurious enthalpy Σ_cells T_cell · NET_OUT_cell, to locate
      imbalance in the current run and assess its energy-budget impact.

The H2 outlet-conduction and H6/H8 B-participation experiments are retired.
Their historical implementations and results remain indexed in docs/history;
they are not alternate physical settings of this current audit.

Test cases (synthetic, no Shanghai data):
  T1 — full-face cubic, parallel flow (A and B both dir=0)
  T2 — full-face cross-flow (A=+x, B=-y)               [current production]
  T3 — partial-B aligned (B_frac=0.5, in/out at same x)
  T4 — partial-B Shanghai-like (B_frac=0.20, offset patches)
  T5 — B-isolated null (B_frac=0)
  T6 — A=B equi-temperature (T_inA == T_inB)

Use --out to choose the report path; historical reports are separate evidence.
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

from sjtu_tpmshx.preprocess.api import prepare_research_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.conservation import compute_phase2a
from sjtu_tpmshx.validation.harness._provenance import output_directory, output_path


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
        fluid_B_cfg=dict(dir=0, in_ctr=H_DOM/2, in_w=H_DOM,
                          out_ctr=H_DOM/2, out_w=H_DOM,
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


CASES = {
    'T1': make_T1, 'T2': make_T2, 'T3': make_T3,
    'T4': make_T4, 'T5': make_T5, 'T6': make_T6,
}


# ──────────────────────────────────────────────────────────────────────────
# Phase 2c — H3 per-cell mass-imbalance audit
# ──────────────────────────────────────────────────────────────────────────

def _audit_scalar_to_solver(field, face):
    """Undo the real-coordinate map before combining with raw SIMPLE faces.

    Exported solver arrays always enter at j=0. Negative real flow directions
    reflect scalar fields along the stream axis as well as permuting axes.
    Scalars change location under that reflection, never sign.
    """
    inverse = tuple(np.argsort(face['solver_to_real_perm']))
    mapped = np.transpose(field, inverse)
    if face['dir_real'] in (1, 3, 5):
        mapped = np.flip(mapped, axis=1)
    return np.ascontiguousarray(mapped)


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
    diag = res.metadata['diagnostics']
    sA = diag['_audit_sA_face']
    sB = diag.get('_audit_sB_face')
    eps_arr = res.metadata['design_fields']['eps_arr']
    Ta = res.fields['Ta_display']; Tb = res.fields['Tb_display']

    def _per_cell_net_out(face):
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
    net_A = _per_cell_net_out(sA)
    Ta_solver = _audit_scalar_to_solver(Ta, sA)

    # NET_OUT already includes rho; T * cp * NET_OUT * eps_per_phase is W.
    eps_per_phase_solver = 0.5 * _audit_scalar_to_solver(eps_arr, sA)
    cp_A = diag['_audit_cp_A']
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
        net_B = _per_cell_net_out(sB)
        Tb_solver = _audit_scalar_to_solver(Tb, sB)
        eps_per_phase_solver_B = 0.5 * _audit_scalar_to_solver(eps_arr, sB)
        cp_B = diag['_audit_cp_B']
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

def _thermal_entropy(T, coefficients):
    """Integral cp(T)/T for the thermal model; no pressure/viscous entropy."""
    a, b, c, origin, reference = coefficients
    T = np.asarray(T)
    delta = T - reference
    return ((a - b*origin + c*origin**2) * np.log1p(delta/reference)
            + (b - 2*c*origin)*delta + .5*c*delta*(T + reference))


def _conductive_entropy(T, conductivity, widths):
    """Internal face heat times its reciprocal-temperature drop, W/K per cell."""
    K = np.broadcast_to(conductivity, T.shape)
    production = np.zeros_like(T)
    for axis, width in enumerate(widths):
        lo = [slice(None)]*3; hi = lo.copy()
        lo[axis] = slice(None, -1); hi[axis] = slice(1, None)
        lo, hi = tuple(lo), tuple(hi)
        shape = [1]*3; shape[axis] = -1
        kl, kr = K[lo], K[hi]
        resistance = .5*width[:-1].reshape(shape)*kr + .5*width[1:].reshape(shape)*kl
        conductance = np.zeros_like(kl)
        np.divide(kl*kr, resistance, out=conductance, where=(kl > 0.) & (kr > 0.))
        for transverse, transverse_width in enumerate(widths):
            if transverse != axis:
                shape = [1]*3; shape[transverse] = -1
                conductance *= transverse_width.reshape(shape)
        pair = conductance*(T[hi] - T[lo])**2/(T[hi]*T[lo])
        production[lo] += .5*pair
        production[hi] += .5*pair
    return production


def _boundary_thermal_entropy(T, mass, coefficients, direction, Tin, inlet_mask):
    """Signed thermal mass faces carry local s(T), before outlet mixing."""
    total = 0.
    for axis, flux in enumerate(mass):
        for end, sign in ((0, -1), (-1, 1)):
            outward = sign*np.take(flux, end, axis=axis)
            face_T = np.take(T, end, axis=axis)
            inlet = axis == direction//2 and end == (0 if direction % 2 == 0 else -1)
            known_inlet = inlet_mask > 0. if inlet else np.zeros_like(outward, dtype=bool)
            if np.any((outward < 0.) & ~known_inlet):
                raise ValueError('thermal entropy requires prescribed state at every inflow face')
            upstream = np.where(outward < 0., Tin, face_T) if inlet else face_T
            total += float(np.sum(outward*_thermal_entropy(upstream, coefficients)))
    return total


def compute_phase3(res):
    """Phase 3 — second law and Carnot bound checks.

    Five sub-blocks per spec §4:
      3.1 Thermal entropy from local cp(T)/T on native boundary mass faces
      3.2 Physical cell/face entropy production; numerical advection stays in the gap
      3.3 Carnot/NTU upper bound (cross-flow Incropera ε_max)
      3.4 Monotonicity: T_min ≤ Tα ≤ T_max ∀ cell (max principle)
      3.5 T_B_out < T_A_out (cold ≯ hot)
    """
    diag = res.metadata['diagnostics']
    Ta = res.fields['Ta']; Tb = res.fields['Tb']; Ts = res.fields['Ts']
    h_vA = res.fields['h_vA']; h_vB = res.fields['h_vB']
    K_ffA = res.fields['K_ffA']; K_ffB = res.fields['K_ffB']
    K_ss = res.fields['K_ss']
    dx = res.grid['dx']; dy = res.grid['dy']; dz = res.grid['dz']
    cp_A = diag['_audit_cp_A']
    cp_B = diag.get('_audit_cp_B')
    T_inA = diag['_audit_T_inA']; T_inB = diag.get('_audit_T_inB')
    m_A = float(diag['_audit_m_dot_A_simple'])
    m_B = (float(diag.get('_audit_m_dot_B_simple', 0.0))
           if diag.get('_audit_m_dot_B_simple') is not None else 0.0)
    # A B-isolated run leaves diag['T_B_out'] PRESENT but None; dict.get returns
    # the stored None (not the fallback), so float(None) would crash Phase 3.
    # Coerce present-but-None symmetrically for both fluids. Audit: r2-val-01.
    _ta = diag.get('T_A_out')
    T_A_out = float(_ta if _ta is not None else T_inA)
    _tb = diag.get('T_B_out')
    T_B_out = float(_tb if _tb is not None
                    else (T_inB if T_inB is not None else T_inA))

    Nx, Ny, Nz = Ta.shape
    cell_vol = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]

    # Thermal entropy uses the same raw state, cp model and physical faces as energy.
    widths = (dx, dy, dz)
    for field in (Ta, Tb, Ts, h_vA, h_vB, K_ffA, K_ffB, K_ss):
        if not np.isfinite(field).all():
            raise ValueError('thermal entropy requires finite temperatures and coefficients')
    if any(np.any(np.asarray(field) < 0.) for field in (h_vA, h_vB, K_ffA, K_ffB, K_ss)):
        raise ValueError('thermal entropy requires nonnegative exchange and conductivity')
    if min(float(Ta.min()), float(Tb.min()), float(Ts.min())) <= 0.:
        raise ValueError('thermal entropy requires positive absolute temperatures')
    entropy_power = _conductive_entropy(Ts, K_ss, widths)
    boundary_diffusion = 0.
    boundary_production = 0.
    side_entropy = {'A': 0., 'B': 0.}
    for side, T, K, hv, cp, Tin in (
            ('A', Ta, K_ffA, h_vA, cp_A, T_inA),
            ('B', Tb, K_ffB, h_vB, cp_B, T_inB)):
        if cp is None:
            continue
        entropy_power += hv*(Ts-T)**2/(Ts*T)*cell_vol
        entropy_power += _conductive_entropy(T, K, widths)
        port = res.metadata['parameters']['fluid_'+side+'_cfg']
        direction = port['dir']; axis = direction//2
        end = 0 if direction % 2 == 0 else -1
        mask = res.metadata['audit']['masks'][side]['inlet']
        face_T = np.take(T, end, axis=axis)
        K_face = np.take(np.broadcast_to(K, T.shape), end, axis=axis)
        conductance = 2*K_face*mask/widths[axis][end]
        for transverse, width in enumerate(widths):
            if transverse != axis:
                shape = [1, 1]; shape[transverse - (transverse > axis)] = -1
                conductance = conductance*width.reshape(shape)
        heat_out = conductance*(face_T - Tin)
        boundary_diffusion += float(np.sum(heat_out/Tin))
        generation = conductance*(face_T-Tin)**2/(face_T*Tin)
        boundary_production += float(np.sum(generation))
        np.moveaxis(entropy_power, axis, 0)[end] += generation
        if res.metadata['thermal_mode'] == 'model_h':
            coefficient = diag['model_h_balance']['sides'][side]['model_cp_coefficients']
            side_entropy[side] = _boundary_thermal_entropy(
                T, res.boundary_fluxes['mass_'+side], coefficient, direction, Tin, mask)
        elif cp_B is None:
            # T5 retains its capacity-temperature null check, not a model-h certificate.
            side_entropy[side] = m_A*cp_A*np.log1p((T_A_out-T_inA)/T_inA)
        else:
            raise ValueError('thermal entropy audit supports model-h or the single-fluid null case')
    S_gen_A, S_gen_B = side_entropy['A'], side_entropy['B']
    S_gen_global = S_gen_A + S_gen_B + boundary_diffusion
    S_gen_volumetric = float(entropy_power.sum())
    sigma_dot = entropy_power/cell_vol
    sigma_neg_cells = int(np.sum(sigma_dot < -1e-12))
    sigma_neg_pct = sigma_neg_cells/sigma_dot.size*100
    # Convert the existing 1 W zero-duty energy scale into entropy-flow units.
    entropy_floor = 1.0/min(T_inA, T_inB if cp_B is not None else T_inA)
    entropy_scale = max(abs(S_gen_global), abs(S_gen_volumetric), entropy_floor)


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
        Q_volumetric_phys = abs(float(diag.get('Q_sB_interior', 0.0)))
        Q_primary = 0.5 * (Q_LTNE_A + Q_LTNE_B) if Q_LTNE_B > 0 else Q_LTNE_A
        eps_obs = Q_primary / max(Q_NTU_max, 1e-30)
        # NTU estimate from the current unscaled interphase coupling.
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
                                       / entropy_scale),
        entropy_residual_W_K=abs(S_gen_global-S_gen_volumetric),
        entropy_normalization_W_K=entropy_scale,
        entropy_zero_duty_floor_W_K=entropy_floor,
        S_boundary_conduction=boundary_diffusion,
        S_inlet_half_cell=boundary_production,
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
# Phase 4 — mass conservation and thermal variation
# ──────────────────────────────────────────────────────────────────────────

def compute_phase4(res):
    """Integrate steady mass conservation across all six outer faces.

    Density variation changes velocity; it never excuses a net mass source.
    Relative temperature change is reported separately, not subtracted.
    """
    diag = res.metadata['diagnostics']
    sA = diag['_audit_sA_face']
    sB = diag.get('_audit_sB_face')
    T_inA = diag['_audit_T_inA']
    T_inB = diag.get('_audit_T_inB')

    def _per_fluid(face, T_in, T_out):
        u = face['u']; v = face['v']; w = face['w']
        rho = face['rho']
        dx = face['dx']; dy = face['dy']; dz = face['dz']

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

        # Runtime exports raw solver arrays: every physical direction enters
        # at solver j=0 with positive v. dir_real affects real-space mapping,
        # not these face arrays, so reverse physical streams need no swap.
        m_in_face = m_south
        m_out_face = m_north
        imbal = -net_out_solver / max(abs(m_in_face), abs(m_out_face), 1e-30)

        # Thermal variation is informational and independent of continuity.
        if T_in is not None and T_in > 0 and T_out is not None:
            dT_rel = abs(T_out - T_in) / T_in
        else:
            dT_rel = 0.0

        return dict(
            m_in=m_in_face, m_out=m_out_face,
            net_out_total=net_out_solver,
            imbal_rel=float(imbal),
            temperature_change_rel=float(dT_rel),
        )

    out = dict(A=None, B=None)
    if sA is not None:
        T_A_out = float(diag.get('T_A_out', T_inA))
        out['A'] = _per_fluid(sA, T_inA, T_A_out)
    if sB is not None and T_inB is not None:
        T_B_out = float(diag.get('T_B_out', T_inB))
        out['B'] = _per_fluid(sB, T_inB, T_B_out)
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
    diag = res.metadata['diagnostics']
    sA = diag['_audit_sA_face']
    sB = diag.get('_audit_sB_face')
    Ta = res.fields['Ta_display']; Tb = res.fields['Tb_display']
    rho_cp_A = res.metadata['application']['props']['rho_cp_A']
    rho_cp_B = res.metadata['application']['props']['rho_cp_B']
    eps_arr = res.metadata['design_fields']['eps_arr']
    eps_per_phase = 0.5 * eps_arr
    fA = diag['_audit_fA']
    fB = diag.get('_audit_fB')

    def _per_fluid(face, T_field, rho_cp_field, fcfg):
        if face is None or fcfg is None:
            return None
        # Compute advective enthalpy flux ∮F·n dA on each of 6 SOLVER faces.
        u = face['u']; v = face['v']; w = face['w']
        rho = face['rho']
        dx = face['dx']; dy = face['dy']; dz = face['dz']
        Nx_s, Ny_s, Nz_s = rho.shape

        T_solver = _audit_scalar_to_solver(T_field, face)
        rho_cp_solver = _audit_scalar_to_solver(rho_cp_field, face)
        eps_solver = _audit_scalar_to_solver(eps_per_phase, face)

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
    diag = res.metadata['diagnostics']
    lines = []
    all_gates = []
    lines.append(f'\n## Case: {label}\n')
    lines.append(f'- grid: {res.fields["Ta_display"].shape}')
    lines.append(f'- Q_enthalpy_A = {_fmt(diag.get("Q_enthalpy_A", float("nan")), 2)} W')
    lines.append(f'- Q_enthalpy_B = {_fmt(diag.get("Q_enthalpy_B", float("nan")), 2)} W')
    lines.append(f'- Q_solid_A (∫h_vA(Ts−Ta)dV) = {_fmt(diag.get("Q_sA", float("nan")), 2)} W')
    lines.append(f'- Q_solid_B (∫h_vB(Ts−Tb)dV) = {_fmt(diag.get("Q_sB", float("nan")), 2)} W')
    lines.append('### Phase 2a — full-CV discrete energy certificate\n')
    lines.append('All actual control volumes are included. The existing thermal '
                 'operator supplies physical-face advection and half-cell inlet '
                 'diffusion; no temperature-based port mask is inferred.')
    if p2a is None:
        lines.append('- Current energy certificate unavailable: **FAIL**')
        all_gates.append(('current energy certificate available', False))
    else:
        lines.append('| fluid | strict global | strict cell-max | boundary inward W | inlet diffusion inward W |')
        lines.append('|-------|---------------|-----------------|-------------------|---------------------------|')
        for side, phase in p2a['sides'].items():
            if phase is None:
                lines.append(f'| {side} | N/A (disabled) | N/A | N/A | N/A |')
                continue
            boundary = phase['boundary']
            external = boundary['physical_external_inward_W'] if boundary else 'N/A'
            diffusion = boundary['inlet_diffusion_inward_W'] if boundary else 'N/A'
            lines.append(f'| {side} | {_fmt(phase["global"]*100, 3)} % | '
                         f'{_fmt(phase["cellmax"]*100, 3)} % | '
                         f'{_fmt(external, 2)} | {_fmt(diffusion, 2)} |')
        if p2a['boundary'] is None:
            lines.append('T5 capacity-temperature path: model-h face ledger N/A; '
                         'the active-fluid full-CV strict certificate is still required.')
        lines.append(f'- Full-volume LTNE source balance: {_fmt(p2a["eps_LTNE"]*100, 3)} %')
        lines.append(f'- Source residual: {_fmt(p2a["source_residual_W"])} W; '
                     f'normalization: {_fmt(p2a["source_normalization_W"])} W (1 W zero-duty floor).')
        for name, ok in p2a['gates']:
            lines.append(f'- {name}: **{"PASS" if ok else "FAIL"}**')
        all_gates.extend(p2a['gates'])
    lines.append('Definition update: the old 5 % BC-excluded heuristic and '
                 'guessed-mask surface budget are retired. The global/cell-max '
                 '1 % limits reuse the strict-conservation regression contract; '
                 'historical reports and failures are unchanged. This is not '
                 'an independent experiment or a new physical validation.')
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
        lines.append('**3.1 Boundary thermal entropy** (local cp(T)/T and physical boundary heat):\n')
        lines.append('Thermal model only; pressure/viscous entropy is outside this audit. '
                     'The single-fluid T5 capacity-temperature null check keeps its own transport definition.')
        lines.append(f'- S_gen_A = {_fmt(p3["S_gen_A"], 4)} W/K')
        lines.append(f'- S_gen_B = {_fmt(p3["S_gen_B"], 4)} W/K')
        lines.append(f'- Boundary conductive entropy flux = {_fmt(p3["S_boundary_conduction"], 6)} W/K')
        lines.append(f'- **S_gen_global = {_fmt(p3["S_gen_global"], 6)} W/K**\n')
        lines.append('**3.2 Physical entropy production** (exchange and shared conductive faces):\n')
        lines.append(f'- S_gen_volumetric = ∫_Ω σ̇ dV = {_fmt(p3["S_gen_volumetric"], 4)} W/K')
        lines.append(f'- |global − volumetric| / scale = {_fmt(p3["sigma_global_vs_volumetric_rel"]*100, 4)} %')
        lines.append(f'- Absolute gap = {_fmt(p3["entropy_residual_W_K"], 6)} W/K; '
                     f'scale = {_fmt(p3["entropy_normalization_W_K"], 6)} W/K; '
                     f'zero-duty floor (1 W / coldest inlet K) = {_fmt(p3["entropy_zero_duty_floor_W_K"], 6)} W/K.')
        lines.append('Numerical advection dissipation is not counted as physical production. '
                     'The unchanged 5% agreement gate still tests grid resolution.')
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
        lines.append(f'| \\|Q_sB_interior\\| (historical subvolume, not physical duty) | {_fmt(p3["Q_volumetric_phys"], 1)} W |')
        lines.append(f'| NTU_int = ∫h_vB·dV / C_min | {_fmt(p3["NTU_int"], 3)} |')
        lines.append(f'| ε_max(C_r, NTU) cross-flow | {_fmt(p3["eps_max_NTU"], 4)} |')
        lines.append(f'| ε_obs = Q_LTNE / Q_NTU_max | {_fmt(p3["eps_obs"], 4)} |')
        lines.append('')
        lines.append('**3.4 Maximum principle** (T_min ≤ Tα ≤ T_max ∀ cell, tol=0.5 K):\n')
        lines.append(f'- T_min_in = {p3["T_min_in"]:.2f} K, T_max_in = {p3["T_max_in"]:.2f} K')
        lines.append(f'- A violations: {p3["max_principle_violations_A"]}')
        lines.append(f'- B violations: {p3["max_principle_violations_B"]}')
        lines.append(f'- s violations: {p3["max_principle_violations_s"]}\n')
        lines.append('**3.5 Outlet temperature ordering**:\n')
        lines.append(f'- T_A_out = {p3["T_A_out"]:.2f} K, T_B_out = {p3["T_B_out"]:.2f} K')
        lines.append(f'- Cold outlet below hot outlet: {p3["cold_lt_hot"]} (observation).\n')

        gates3 = []
        gates3.append(('S_gen_global ≥ −1e-3', p3['S_gen_global'] >= -1e-3))
        gates3.append(('σ̇ < 0 cells < 0.1 %', p3['sigma_neg_pct'] < 0.1))
        gates3.append(('|global − volumetric| / scale < 5 %',
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
            lines.append('- Outlet crossover: **allowed** (ε > 1/(1+C_r)); not a failed gate.')
        else:
            gates3.append(('cold ≯ hot', p3['cold_lt_hot']))
        for name, ok in gates3:
            lines.append(f'- {name}: **{"PASS" if ok else "FAIL"}**')
        all_gates.extend(gates3)
        lines.append('')

    if p4 is not None:
        lines.append('### Phase 4 — steady mass conservation\n')
        lines.append('| fluid | m_in (kg/s) | m_out (kg/s) | six-face imbal % | temperature change % (informational) |')
        lines.append('|-------|-------------|--------------|------------------|--------------------------------------|')
        for tag in ('A', 'B'):
            d = p4.get(tag)
            if d is None:
                continue
            lines.append(
                f'| {tag} | {_fmt(d["m_in"], 6)} | {_fmt(d["m_out"], 6)} | '
                f'{_fmt(d["imbal_rel"]*100, 3)} | {_fmt(d["temperature_change_rel"]*100, 3)} |')
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
        all_gates.extend(gates4)
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
        all_gates.extend(gates5)
        lines.append('')
    return '\n'.join(lines), all(ok for _, ok in all_gates)


def write_report(out_path, sections, header_meta):
    out_path = output_path(out_path)
    lines = []
    lines.append('# 3D LTNE Energy and Thermal-Entropy Audit\n')
    lines.append(f'- Date: {header_meta["date"]}')
    lines.append('- Discrete gate: existing full-CV strict-conservation global/cell-max < 1 %; historical surface specification is not inferred.')
    lines.append('- Audit script: `sjtu_tpmshx/validation/cases/audit_3d_conservation.py`\n')
    lines.append('## Scope\n')
    lines.append('- Phase 2a current full-CV strict certificate + Phase 2c per-cell mass-imbalance audit (H3).')
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

    try:
        out_path = (output_path(args.out) if args.out else
                    output_directory('conservation') / 'report.md')
    except ValueError as exc:
        ap.error(str(exc))
    if args.grid < 1:
        ap.error('--grid must be positive')

    selected = [c.strip() for c in args.cases.split(',') if c.strip()]
    unsupported = sorted(set(selected) - CASES.keys())
    if unsupported or not selected:
        ap.error(f'unsupported cases {unsupported}; use T1..T6. '
                 'H2/H6/H8 B-participation experiments are retired.')

    # ── Phase 6: grid convergence sweep ──
    if args.phase6_grid_convergence:
        print('\n══════ PHASE 6 — Grid convergence ══════')
        grids = [12, 20, 30]
        gc_rows = []
        failed = False
        for cid in selected:
            print(f'\n  case {cid}:')
            row = {'case': cid}
            for g in grids:
                cfg = CASES[cid](g)
                cfg['_emit_audit'] = True   # Retain final SIMPLE evidence for the offline audit
                t0 = time.time()
                Q_enth = eps_strict = float('nan')
                try:
                    res = run_case(prepare_research_case(cfg, case_id=cfg['_case_label']))
                    failed = failed or not res.run_status['converged']
                    Q_enth = float(res.metadata['diagnostics'].get('Q_enthalpy_B', float('nan')))
                    certificate = compute_phase2a(res)
                    passed = all(ok for _, ok in certificate['gates'])
                    row[f'certificate_pass_g{g}'] = passed
                    failed = failed or not passed
                    phase_b = certificate['sides']['B']
                    eps_strict = phase_b['global'] if phase_b else float('nan')
                except Exception as exc:
                    failed = True
                    row[f'certificate_pass_g{g}'] = False
                    row[f'error_g{g}'] = f'{type(exc).__name__}: {exc}'
                dt = time.time() - t0
                row[f'Q_g{g}'] = Q_enth
                row[f'eps_B_strict_g{g}'] = eps_strict * 100
                print(f'    grid={g}: Q={Q_enth:.1f}W ε_B_strict={eps_strict*100:.2f}% [{dt:.0f}s]')
            from sjtu_tpmshx.validation.cases.phase_c_gci import _richardson_triplet
            Qs = [row[f'Q_g{g}'] for g in grids]
            order, extrapolate = _richardson_triplet(grids, Qs)
            rel_med_fine = abs(Qs[-2] - Qs[-1]) / max(abs(Qs[-1]), 1e-30)
            row.update(rel_med_fine=rel_med_fine * 100, order_obs=order,
                       Q_extrapolated=extrapolate)
            print(f'    |med−fine|/fine = {rel_med_fine*100:.2f}%; '
                  f'Richardson order = {order:.2f} (NaN means undetermined)')
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
        write_report(out_path, [str(row) for row in gc_rows],
                     dict(date=time.strftime('%Y-%m-%d')))
        return 0 if not failed and all(np.isfinite(row['order_obs']) for row in gc_rows) else 1

    sections = []
    summary_rows = []
    failed = False
    for cid in selected:
        print(f'\n══════ Phase 2 case: {cid} ══════')
        cfg = CASES[cid](args.grid)
        cfg['_emit_audit'] = True   # Retain final SIMPLE evidence for the offline audit
        t0 = time.time()
        try:
            res = run_case(prepare_research_case(cfg, case_id=cfg['_case_label']))
        except Exception as exc:
            failed = True
            sections.append(f'\n## Case: {cid}\n\n**FAIL**: {type(exc).__name__}: {exc}')
            continue
        failed = failed or not res.run_status['converged']
        dt = time.time() - t0
        print(f'  solved in {dt:.1f}s')
        try:
            p2a = compute_phase2a(res)
        except Exception as e:
            failed = True
            print(f'  Phase 2a failed: {e}')
            p2a = None
        try:
            p2c = compute_phase2c_h3(res)
        except Exception as e:
            failed = True
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
            failed = True
            print(f'  Phase 3 failed: {e}')
            p3 = None
        try:
            p4 = compute_phase4(res)
        except Exception as e:
            failed = True
            print(f'  Phase 4 failed: {e}')
            p4 = None
        try:
            p5 = compute_phase5(res)
        except Exception as e:
            failed = True
            print(f'  Phase 5 failed: {e}')
            p5 = None
        sec, passed = render_case(cid, res, p2a, p2c, p3, p4, p5)
        if not res.run_status['converged']:
            sec += '\n- Solver convergence: **FAIL**\n'
        failed = failed or not passed
        sections.append(sec)
        summary_rows.append((cid, p2a, p2c, p3, p4, p5))

    write_report(out_path, sections, dict(date=time.strftime('%Y-%m-%d')))
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
              f'{(p2a["sides"]["A"]["global"]*100 if p2a else float("nan")):>6.2f} '
              f'{(p2a["sides"]["B"]["global"]*100 if p2a and p2a["sides"]["B"] else float("nan")):>6.2f} '
              f'{(p2a["eps_LTNE"]*100 if p2a else float("nan")):>7.2f} '
              f'{s_gen:>+8.4f} '
              f'{eo:>7.4f} '
              f'{mA:>+7.3f} '
              f'{mB:>+7.3f} '
              f'{latA:>6.2f} '
              f'{latB:>6.2f}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
