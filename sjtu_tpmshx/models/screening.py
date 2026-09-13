"""Existing air/air optimization screening settings; no execution or objectives."""
import numpy as np
from sjtu_tpmshx.models.continuous_field import (
    from_decision_vector, DEFAULT_N_CTRL_X, DEFAULT_N_CTRL_Y,
    DEFAULT_SYMMETRIC_Y, DEFAULT_L_BOUNDS, DEFAULT_T_BOUNDS,
)


FIELD_CONFIG_KEYS = ('tpms_type', 'k_s', 'L_domain', 'H_domain', 'n_ctrl_x',
                     'n_ctrl_y', 'symmetric_y', 'spline_order', 'L_bounds', 't_bounds')


SCREENING_FIELDS = ('eps_arr', 'K_ffA_arr', 'K_ffB_arr', 'K_ss_arr', 'h_vA_arr', 'h_vB_arr')

DEFAULT_CONFIG: dict = {
    # Domain
    'L_domain':   0.10,    # m  (real x, fluid A streamwise)
    'H_domain':   0.05,    # m  (real y, fluid B streamwise)
    'Nx':         None,    # None → adaptive_grid from D_h(L_avg, t_avg)
    'Ny':         None,
    'grid_alpha': 0.8,     # adaptive_grid density factor (0.8 = baseline)

    # TPMS + solid
    'tpms_type':  'Diamond',
    'k_s':        17.0,    # solid conductivity [W/(m K)]
    'rho_s':      2700.0,  # solid density [kg/m^3]

    # Fluid operating point
    'u_A':        10.0,    # m/s
    'u_B':        10.0,
    'T_inA':      350.0,   # K
    'T_inB':      300.0,
    'P_inA':      101325.0,
    'P_inB':      101325.0,
    'fluid_type_A': 'air',
    'fluid_type_B': 'air',

    # Flow direction codes
    #   0 = +x, 1 = -x, 2 = +y, 3 = -y
    'dir_A':      0,       # fluid A flows +x  → streamwise = real x
    'dir_B':      3,       # fluid B flows -y  → streamwise = real y reversed

    # Boundary openings — port-type partial BC (2026-07-10, IDEA-PORT-DIM).
    #   None → FULL-FACE inlet/outlet. This is the M0–M3 experiment condition
    #   and the scope of the ADJOINT gate-2 verdict; it reproduces the
    #   pre-port evaluator bit-identically. A tuple
    #   (in_lo, in_hi, out_lo, out_hi) [m] opens only that span of the face:
    #   fluid A spans real y ∈ [0, H_domain]; fluid B spans real x ∈
    #   [0, L_domain]. Partial-BC absolute numbers are NOT experimentally
    #   benchmarked (ledger IDEA-PORT-VALID) — relative rankings only.
    'ports_A':    None,
    'ports_B':    None,
    # Per-cell K/cF in the momentum drag (lateral-K, 2026-07-10). False →
    # legacy per-row streamwise projection (laterally averaged — what M0–M3
    # ran). True → per-cell prediction from the local (L, t) field; REQUIRED
    # for port-BC routing studies: lateral resistance contrast is the
    # routing lever, and the per-row projection erases it.
    'per_cell_K': False,
    # Oblique-flow Forchheimer direction factor (cf-aniso, 2026-07-10):
    # cF_eff = cF·(1 + cf_aniso·4nx²ny²), the lowest cubic-symmetry
    # invariant (0 on-axis — the calibration-anchored value — max at 45°).
    # 0.0 = isotropic (bit-identical legacy). The closure was calibrated on
    # axis-aligned flow only; port-BC runs turn the flow in-domain, so a
    # non-zero value bounds that direction error. Its VALUE must come from
    # direction-resolved unit-cell CFD (validation/cf_aniso/ worklist) —
    # do not quote absolute numbers from a hand-picked setting; use ± sweeps
    # for verdict-robustness checks only.
    'cf_aniso': 0.0,

    # Solver knobs
    'max_iter_simple': 5000,
    'tol_simple':      1e-3,        # SIMPLE mass residual tolerance. The
                                    # cross-flow geometry (no manifold,
                                    # axis-swap on side B) leaves side B's
                                    # residual stagnating at O(1e-3) on
                                    # heterogeneous fields even though dP
                                    # has fully stabilized; tightening past
                                    # 1e-3 produces 100% rejection during
                                    # Sobol exploration without changing
                                    # Q / dP. V&V Standard-Tier paths can
                                    # override to 1e-5 explicitly.
    'max_iter_energy': 5000,
    'tol_energy':      0.5,        # K
    'n_rho_loops':     3,          # 1 = isothermal-ρ fast path; >1 enables
                                   # outer SIMPLE↔energy variable-density
                                   # iteration. 3 is the ConstDF-v1 baseline
                                   # used in validate_shanghai_3d_real and
                                   # the retired patch-zoning evaluator;
                                   # honors feedback_compressible_required.md.
    'drho_tol':        0.01,       # converge outer loop when |Δρ|/ρ̄ < 1 %
    'rho_relax':       0.7,        # under-relaxation on ρ updates (Picard)

    # Continuous-field parametrization
    'n_ctrl_x':    DEFAULT_N_CTRL_X,
    'n_ctrl_y':    DEFAULT_N_CTRL_Y,
    'symmetric_y': DEFAULT_SYMMETRIC_Y,
    'L_bounds':    DEFAULT_L_BOUNDS,
    't_bounds':    DEFAULT_T_BOUNDS,
    'spline_order': 3,

    # Manufacturability penalty added to dP objective
    'penalty_enabled':  True,
    'penalty_weight':   1.0,        # scales the raw penalty before adding to dP

    # Pathological-design rejection (production hardening; v2)
    'dp_cap_pa':            1.0e6,  # hard upper bound on dP. Designs that
                                    # blow past this — usually unconverged
                                    # SIMPLE residuals masquerading as dP —
                                    # are tagged bad and returned at the cap
                                    # so the BO surrogate sees a bounded
                                    # input distribution (no 17-MPa outliers
                                    # destroying GP lengthscale estimates).
    'reject_unconverged':   False,  # When True, a SIMPLE solve that exits at
                                    # max_iter without hitting tol returns at
                                    # the cap with Q ≈ 0. Default off because
                                    # the dp_cap_pa final guard already
                                    # catches the failure mode we care about
                                    # (residual-dominated dP > 1 MPa); strict
                                    # convergence-flag rejection just discards
                                    # designs where dP is already stable but
                                    # mass residual happens to plateau above
                                    # tol_simple. Set True for diagnostics
                                    # that demand machine-precision SIMPLE.
}



def validate_screening_config(cfg, *, dimension=2):
    """Reject unsupported physical requests before they become air defaults."""
    if (cfg.get('dir_A', 0), cfg.get('dir_B', 3)) != (0, 3):
        raise ValueError(f'{dimension}D screening flow mapping supports only +x A and -y B')
    for key in ('fluid_type_A', 'fluid_type_B'):
        if str(cfg.get(key, 'air')).lower() != 'air':
            raise ValueError(f'screening supports air only: {key}={cfg[key]!r}')
    for key in ('L_domain', 'H_domain', 'T_inA', 'T_inB', 'P_inA', 'P_inB', 'k_s', 'rho_s'):
        if not np.isfinite(cfg[key]) or cfg[key] <= 0.:
            raise ValueError(f'screening {key} must be finite and positive')
    if dimension == 3 and any(cfg.get(key) is not None for key in ('ports_A', 'ports_B')):
        raise ValueError('3D screening supports full-face ports only')


def build_field(x, cfg):
    return from_decision_vector(
        x, tpms_type=cfg['tpms_type'], k_s=cfg['k_s'],
        L_domain=cfg['L_domain'], H_domain=cfg['H_domain'],
        n_ctrl_x=cfg['n_ctrl_x'], n_ctrl_y=cfg['n_ctrl_y'],
        symmetric_y=cfg['symmetric_y'], spline_order=cfg['spline_order'],
        L_bounds=cfg['L_bounds'], t_bounds=cfg['t_bounds'])


def _build_3d_arrays(fc, Nx: int, Ny: int, Nz: int,
                     u_A: float, u_B: float,
                     T_inA: float, T_inB: float,
                     P_inA: float, k_s: float,
                     tpms_type: str,
                     quant_L: float = 0.05,
                     quant_t: float = 0.01, *, P_inB: float | None = None) -> dict:
    """Per-voxel arrays (eps, K_ffA/B, K_ss, h_vA/B, A_0, eps_A) of shape
    (Nx, Ny, Nz). 2D field extruded uniformly along z.
    """
    L_field_2D, t_field_2D = fc.evaluate_grid(Nx, Ny)

    # Quantized (L, t) → unique-pair scatter, shared with the 2D builder
    # (B3 C7: solvers.continuous_field.props_from_Lt_fields). Replaces the
    # former per-cell dict-cache loop; the quantization key moved from
    # Python round() to np.round (round-half-even, agrees on the
    # 0.05/0.01-quantized grid). Result is z-broadcast below.
    from sjtu_tpmshx.models.continuous_field import props_from_Lt_fields
    p = props_from_Lt_fields(L_field_2D, t_field_2D, tpms_type, k_s,
                             u_A, u_B, T_inA, T_inB, P_inA,
                             P_inB=P_inB, quant_L=quant_L, quant_t=quant_t)

    L_field_3D = np.broadcast_to(L_field_2D[:, :, None], (Nx, Ny, Nz)).copy()
    t_field_3D = np.broadcast_to(t_field_2D[:, :, None], (Nx, Ny, Nz)).copy()

    def _z(a2d):
        """Extrude a (Nx, Ny) array uniformly to (Nx, Ny, Nz)."""
        return np.broadcast_to(a2d[:, :, None], (Nx, Ny, Nz)).copy()

    return {
        'eps_arr':   _z(p['eps_arr']),
        'eps_f_arr': _z(p['eps_f_arr']),
        'K_ffA_arr': _z(p['K_ffA_arr']),
        'K_ffB_arr': _z(p['K_ffB_arr']),
        'K_ss_arr':  _z(p['K_ss_arr']),
        'h_vA_arr':  _z(p['h_vA_arr']),
        'h_vB_arr':  _z(p['h_vB_arr']),
        'A_0_arr':   _z(p['A_0_arr']),
        'L_field':   L_field_3D,
        't_field':   t_field_3D,
        'cache_size': p['n_unique'],
    }

