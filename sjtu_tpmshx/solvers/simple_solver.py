"""
simple_solver.py — 2D SIMPLE solver for porous-media transition zone

Solves steady-state Navier-Stokes + Brinkman porous resistance,
then frozen-velocity temperature field (LTNE: fluid + solid).
Production default is COMPRESSIBLE ideal-gas rho=rho(P,T) with a mass-flux
inlet (`massflux_inlet=True`) — repo hard invariants.

All inner loops are Numba-compiled for speed (~50-100x vs pure Python).

Physics (velocity; header re-verified against kernels 2026-07-06 — the old
friction-factor resistance form and its kernel no longer exist, D-F is the
only closure):
  du/dx + dv/dy = 0                                         (continuity)
  rho(u du/dx + v du/dy) = -dP/dx + mu_eff nabla^2 u - Rx  (x-momentum)
  rho(u dv/dx + v dv/dy) = -dP/dy + mu_eff nabla^2 v - Ry  (y-momentum)
  Rx = (mu/K + rho c_F |U|) u,  Ry = (mu/K + rho c_F |U|) v
  (Darcy-Forchheimer ConstDF-v1, interstitial form; _porous_src_df)

Physics (temperature, frozen velocity):
  eps rho_cp (u dTf/dx + v dTf/dy) = K_ff nabla^2 Tf + h_v(Ts - Tf)
  0 = K_ss nabla^2 Ts + h_v(Tf - Ts) + h_v2(T_other - Ts)

Staggered grid:  P[i,j] cell centre (Nx,Ny)
                 u[i,j] x-face (Nx+1,Ny)    v[i,j] y-face (Nx,Ny+1)

Velocity convention (IMPORTANT — differs from textbook Brinkman-Forchheimer):
  u, v are *interstitial* (pore-average) velocities, not superficial. Inlet BC
  `v_inlet = m_dot / (rho * A_void)` where A_void = eps_f * A_total; training
  data (df_surrogate/) uses the same convention. Consequently K and c_F from the D-F
  surrogate are *effective interstitial* coefficients that already absorb the
  eps_f factor — they are not the canonical Darcy/Forchheimer values one would
  cite from a textbook. This is algebraically equivalent to the superficial
  form when eps_f is spatially uniform (e.g. Shanghai). For spatially varying
  eps_f (future zoned-TPMS work) the convection and Laplacian operators on
  interstitial u deviate from the homogenised BFNS derivation — flag before
  extending to non-uniform porosity (verdict + per-dimension detail: vault
  research ledger B5, code-verified 2026-07-06).
"""

import os

import numpy as np
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF, predict_K_cF_vec
from ._solve_common import (LowReExit, F2Monitor, f2_state_is_finite,
                            f2_nonfinite_exit, momentum_component_residuals,
                            global_mass_residual)
from sjtu_tpmshx.models.tpms_calc import (air_density, air_viscosity, P_atm)
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

# --- moved kernels (openspec split-solver-kernels, 2026-07-03) ----------
# All numba kernels + pressure-Poisson infra live in _kernels_simple_2d.py
# Re-exported here for existing kernel importers.
from ._kernels_simple_2d import (  # noqa: F401
    _sou_corr_u_x,
    _sou_corr_u_y,
    _sou_corr_v_x,
    _sou_corr_v_y,
    _porous_src_df,
    _umag_u,
    _umag_v,
    _sweep_u_jit_df,
    _sweep_v_jit_df,
    _build_pp_sparsity_pattern,
    _assemble_pp_data_jit,
    _solve_pp_sparse_fast,
    _correct_jit,
    _close_outlet_mass,
    _mass_res_jit,
    _solve_temp_jit,
    # F2 convergence gates (ledger C6 / C7 / C9)
    _u_coeffs_df_2d,
    _v_coeffs_df_2d,
    _mom_res_jit_2d,
    _mass_res_solved_jit_2d,
    _mass_global_jit_2d,
)


# ===================================================================
#  Adaptive grid generation
# ===================================================================

from sjtu_tpmshx.models.grid import _port_overlap_1d  # noqa: F401


from sjtu_tpmshx.models.grid import _port_fractions_1d  # noqa: F401


from sjtu_tpmshx.models.grid import _aligned_grid  # noqa: F401


def _prolong_mass_faces_2d(mass, dx, dy, fine_dx, fine_dy):
    """Integrate the coarse CV's linear-normal, constant-transverse flux.

    Works on nonnested partitions. Fine divergence is the overlap integral
    of coarse divergence; this transfers the flow and does not solve momentum.
    """
    edges = [np.r_[0., np.cumsum(w)] for w in (dx, dy, fine_dx, fine_dy)]
    x, y, xf, yf = edges
    if not (np.isclose(x[-1], xf[-1], rtol=1e-12, atol=1e-15)
            and np.isclose(y[-1], yf[-1], rtol=1e-12, atol=1e-15)):
        raise ValueError('mass prolongation requires the same physical domain')
    # These are the same physical boundary, despite cumsum roundoff.
    xf[-1], yf[-1] = x[-1], y[-1]
    overlap_x = np.maximum(0., np.minimum(xf[1:, None], x[None, 1:])
                            - np.maximum(xf[:-1, None], x[None, :-1]))
    overlap_y = np.maximum(0., np.minimum(yf[1:, None], y[None, 1:])
                            - np.maximum(yf[:-1, None], y[None, :-1]))
    jx = np.column_stack([np.interp(xf, x, mass[0][:, j]) for j in range(len(dy))])
    jy = np.vstack([np.interp(yf, y, mass[1][i]) for i in range(len(dx))])
    return (np.ascontiguousarray((jx / np.asarray(dy)[None, :]) @ overlap_y.T),
            np.ascontiguousarray(overlap_x @ (jy / np.asarray(dx)[:, None])))


from sjtu_tpmshx.models.grid import build_wall_refined_1d  # noqa: F401


def build_inlet_stretched_1d(L, N, first_cell, end='lo'):
    """One-sided geometric STREAMWISE grid: fine at the inlet end, coarsening
    smoothly downstream (no cell-size jump). ``cell[0]=first_cell``,
    ``cell[k]=first_cell·r**k``; the growth ratio ``r>1`` is solved so the N
    cells sum exactly to ``L``.

    Purpose: resolve a steep inlet thermal-entry without a globally fine grid.
    This is the OPT-IN streamwise counterpart of :func:`build_wall_refined_1d`
    (which refines the two CROSS-STREAM walls). It is NOT wired into the default
    solver path — ``_aligned_grid`` (uniform) remains the default. The per-cell
    ``dx_arr`` kernels (``ltne_energy._gs_full_chunk``, ``simple_solver``'s
    momentum sweep) already consume a non-uniform 1-D array, so a graded
    ``dx_arr`` from here plugs in with no kernel change.

    Parameters
    ----------
    L : float — domain length along this (streamwise) axis [m]
    N : int — number of cells
    first_cell : float — width of the cell at the inlet end [m]. Must be < L/N
        to actually refine; otherwise the function returns a uniform grid.
    end : {'lo', 'hi'} — 'lo' puts the fine cells at x=0 (dir 0/2 inlet),
        'hi' mirrors them to x=L (dir 1/3 inlet).

    Returns
    -------
    dx_arr : (N,) float64 array, ``sum == L`` (renormalised to machine
        precision), geometrically graded from ``first_cell``.

    Notes
    -----
    The growth ratio is whatever the (L, N, first_cell) triple implies; a very
    small ``first_cell`` forces a steep ratio. For low truncation error on the
    second-order-upwind convection term, keep the implied ratio modest
    (≈≤1.2–1.3 per cell) — i.e. choose ``first_cell`` not far below ``L/N``.
    """
    N = int(N)
    if N < 2 or first_cell <= 0 or first_cell * N >= L:
        # Cannot refine (first cell already ≥ the uniform width) → uniform.
        return np.full(N, L / float(N), dtype=np.float64)
    # Solve first_cell·(r**N − 1)/(r − 1) = L for r>1 by bisection. The
    # geometric-sum S(r)=(r**N−1)/(r−1) is monotonic increasing in r with
    # S(1+)=N < L/first_cell (guaranteed by the guard above), so a root r>1
    # exists; cap the bracket at a steep r=8 (renormalisation absorbs any
    # residual so the sum is always exact even if the root is clamped).
    target = L / first_cell
    lo, hi = 1.0 + 1e-12, 8.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        s = (mid ** N - 1.0) / (mid - 1.0)
        if s < target:
            lo = mid
        else:
            hi = mid
    r = 0.5 * (lo + hi)
    dx = first_cell * r ** np.arange(N, dtype=np.float64)
    dx *= L / dx.sum()                      # renormalise → exact sum == L
    return dx[::-1].copy() if end == 'hi' else dx


# ===================================================================
#  SIMPLESolver class
# ===================================================================

class SIMPLESolver:
    """2D steady SIMPLE on staggered grid for porous-media transition zone.

    Parameters of note
    ------------------
    wall_refine : bool (default True)
        If True, use geometric refinement near cross-stream walls to resolve
        the Brinkman boundary layer (δ_B ≈ 0.05 mm for typical TPMS). Adds
        2*n_wall_refine cells on top of Nx. Automatically disabled when any
        external 2D field (rho, T_field) is passed at init or when inlet/outlet
        is not full-width, because downstream consumers expect matched Nx.

        Production paths (optimizer, validate_shanghai, run_calculation) pass
        wall_refine=False because their outer coupling loops feed SIMPLE outputs
        back to solvers that expect the coarse (pre-refine) Nx. Standalone
        diagnostic / visualisation scripts benefit from the default (True) and
        can see the Brinkman BL directly.

    n_wall_refine : int (default 8)
        Refinement layers per wall.
    wall_first_cell : float (default 0.02e-3 m)
        First cell thickness at the wall (should be < δ_B for full resolution).
    """

    def __init__(self, W, H, Nx, Ny,
                 tpms_type, L_cell_mm, t_mm, eps, r_h,
                 rho, mu, T_in,
                 inlet_lo, inlet_hi, v_inlet,
                 outlet_lo=None, outlet_hi=None,
                 P_ref=0.0, zone_config=None, zone_arrays=None,
                 y_breakpoints=None,
                 fluid_type='ideal_gas',
                 R_gas=287.05,
                 T_field=None,
                 P_ref_abs=None,
                 alpha_rho=0.3,
                 rho_inlet_ref=None,
                 wall_refine=True,
                 n_wall_refine=8,
                 wall_first_cell=0.02e-3,
                 df_method=None,
                 dx_arr=None, dy_arr=None, K_arr=None, cF_arr=None,
                 **_legacy_kw):
        # Historical 'closure' kwarg is accepted but ignored; ConstDF-v1 D-F
        # is the only closure since 2026-04-19 f-Re cleanup.
        _legacy_kw.pop('closure', None)
        # Mass-flux inlet reference density (kg/m³): the physical inlet density
        # ρ(T_in, P_in) the caller used to convert ṁ → v_inlet. With the
        # mass-flux inlet on, the pinned inlet mass flux is G = v_inlet ·
        # rho_inlet_ref (grid- and convention-independent). None → fall back to
        # capturing G from rho_field[:,0] at the first solve(); that is correct
        # when the solver is reused across outer iters (3D) or when P_ref_abs is
        # an outlet datum (the rho_field inlet row then stays at the reference),
        # but NOT when the solver is recreated each outer iter with an
        # inlet-pressure datum (the inlet row inflates → target would ratchet),
        # so the 2D pipeline / validation pass this explicitly. See solve().
        self._rho_inlet_ref = (float(rho_inlet_ref)
                               if rho_inlet_ref is not None else None)

        # Wall refinement (cross-stream, x direction): geometric grid at both
        # side walls to resolve Brinkman boundary layer. Default ON since
        # 2026-04-17. Adds 2*n_wall_refine cells on top of Nx (interpreted as
        # bulk cell count). Disabled if inlet/outlet are not full-width
        # (x_breaks present) or if the user passes wall_refine=False.
        if (dx_arr is None) != (dy_arr is None):
            raise ValueError('prepared SIMPLE grid requires both dx_arr and dy_arr')
        if dx_arr is not None:
            for widths, count, length in ((dx_arr, Nx, W), (dy_arr, Ny, H)):
                values = np.asarray(widths, dtype=np.float64)
                if (values.shape != (count,) or not np.all(np.isfinite(values))
                        or np.any(values <= 0.0)
                        or not np.isclose(values.sum(), length, rtol=1e-12, atol=1e-15)):
                    raise ValueError('prepared SIMPLE grid does not match its domain')
            wall_refine = False
        if (K_arr is None) != (cF_arr is None):
            raise ValueError('prepared SIMPLE drag requires both K_arr and cF_arr')
        if K_arr is not None:
            for values, positive in ((K_arr, True), (cF_arr, False)):
                values = np.asarray(values, dtype=np.float64)
                if (values.shape != (Ny,) or not np.all(np.isfinite(values))
                        or np.any(values <= 0.0 if positive else values < 0.0)):
                    raise ValueError('invalid prepared SIMPLE row drag coefficients')

        x_breaks = []
        if inlet_lo > W * 0.001:
            x_breaks.append(inlet_lo)
        if inlet_hi < W * 0.999:
            x_breaks.append(inlet_hi)
        if outlet_lo is not None and outlet_lo > W * 0.001:
            x_breaks.append(outlet_lo)
        if outlet_hi is not None and outlet_hi < W * 0.999:
            x_breaks.append(outlet_hi)

        # Wall refinement is only safe when all external 2D fields (rho, T_field)
        # are scalars — otherwise the user's pre-built fields won't match the
        # refined Nx. Auto-disable if any 2D array is passed.
        external_2d = (np.ndim(rho) == 2) or (T_field is not None and np.ndim(T_field) == 2)
        self._wall_refined = False
        if (wall_refine and len(x_breaks) == 0 and n_wall_refine > 0
                and not external_2d):
            try:
                dx_refined = build_wall_refined_1d(
                    W, N_bulk=Nx, n_refine=n_wall_refine,
                    first_cell=wall_first_cell, growth=1.8)
                Nx = Nx + 2 * n_wall_refine   # actual cell count after refinement
                self._wall_refined = True
            except ValueError:
                dx_refined = None  # fall back to uniform
        else:
            dx_refined = None

        # Domain
        self.Nx, self.Ny = Nx, Ny
        self.dx, self.dy = W / Nx, H / Ny  # scalar for backward compat

        # Aligned grid: cell edges at inlet/outlet-wall junctions
        if dx_arr is not None:
            self.dx_arr = np.array(dx_arr, dtype=np.float64, copy=True)
        elif self._wall_refined and dx_refined is not None:
            self.dx_arr = dx_refined
        else:
            self.dx_arr = _aligned_grid(Nx, W, x_breaks)
        # y-direction: aligned if y_breakpoints provided, else uniform
        self.dy_arr = (_aligned_grid(Ny, H, y_breakpoints or []) if dy_arr is None
                       else np.array(dy_arr, dtype=np.float64, copy=True))

        # Porous medium (scalar, kept for temperature solver & backward compat)
        self.eps = eps
        self.r_h = r_h
        self.mu_eff = mu / eps
        # Per-cell porosity (2D #2 fix). Default uniform; caller sets
        # eps_field for zoned. Used in continuity: ∇·(ε·ρ·u) = 0 macroscopic
        # form. Without ε factor, zoned-ε cases miss ∇ε term and accumulate
        # 5-20% per-cell mass divergence.
        self.eps_field = np.full((Nx, Ny), float(eps), dtype=np.float64)

        # Fluid — rho can be scalar or 2D array (Nx, Ny)
        if np.ndim(rho) == 0:
            self.rho_field = np.full((Nx, Ny), float(rho), dtype=np.float64)
        else:
            self.rho_field = np.ascontiguousarray(rho, dtype=np.float64)
        self.rho = float(self.rho_field.mean())  # scalar mean for backwards-compat
        # mu can be scalar or 2D array (Nx, Ny) — 2D supports non-isothermal
        # coupling where viscosity tracks the temperature field.
        if np.ndim(mu) == 0:
            self.mu = float(mu)
        else:
            self.mu = float(np.asarray(mu, dtype=np.float64).mean())

        # Compressible flow: pressure-density coupling
        self.fluid_type = fluid_type
        self.R_gas = R_gas
        self.alpha_rho = alpha_rho
        if P_ref_abs is None:
            self.P_ref_abs = P_atm + P_ref
        else:
            self.P_ref_abs = float(P_ref_abs)
        if T_field is None:
            self.T_field = np.full((Nx, Ny), float(T_in), dtype=np.float64)
        elif np.ndim(T_field) == 0:
            self.T_field = np.full((Nx, Ny), float(T_field), dtype=np.float64)
        else:
            self.T_field = np.ascontiguousarray(T_field, dtype=np.float64)

        # Non-isothermal coupling: 2D viscosity fields that track T_field.
        # Authoritative arrays consumed by D-F sweeps; update via
        # _refresh_mu_from_T whenever T_field changes.
        if np.ndim(mu) == 0:
            self.mu_field = np.full((Nx, Ny), float(mu), dtype=np.float64)
        else:
            self.mu_field = np.ascontiguousarray(mu, dtype=np.float64)
        self._mu_eff_field = self.mu_field / float(eps)

        # ── ConstDF-v1 surrogate: precompute (K, c_F) per row ──
        # Broadcast for uniform geometry; per-row predictions for zone_config
        # graded designs. zone_arrays path doesn't carry L/t/eps metadata, so
        # it falls back to the uniform (scalar) prediction.

        if K_arr is not None:
            self._K_arr = np.array(K_arr, dtype=np.float64, copy=True)
            self._cF_arr = np.array(cF_arr, dtype=np.float64, copy=True)
        elif zone_config is not None:
            # Per-row (L, t, eps_f) → batched prediction
            L_row = np.empty(Ny, dtype=np.float64)
            t_row = np.empty(Ny, dtype=np.float64)
            eps_f_row = np.empty(Ny, dtype=np.float64)
            dy_val = H / Ny
            for j in range(Ny):
                yc_frac = (j + 0.5) * dy_val / H
                z = zone_config.zones[-1]
                for zz in zone_config.zones:
                    if zz.y_frac_start <= yc_frac < zz.y_frac_end:
                        z = zz; break
                L_row[j] = z.L_mm
                t_row[j] = z.t_mm
                z_eps = z.props_A['epsilon'] if z.props_A else eps
                eps_f_row[j] = 0.5 * z_eps  # ε_A: per-stream void fraction
            K_vec, cF_vec = predict_K_cF_vec(
                tpms_type, L_row, t_row, eps_f_row, method=df_method)
            self._K_arr = K_vec.astype(np.float64)
            self._cF_arr = cF_vec.astype(np.float64)
        else:
            # Uniform (or zone_arrays fallback): single (K, c_F), broadcast
            K_val, cF_val = predict_K_cF(
                tpms_type, float(L_cell_mm), float(t_mm), 0.5 * float(eps),
                method=df_method,
            )
            self._K_arr = np.full(Ny, K_val, dtype=np.float64)
            self._cF_arr = np.full(Ny, cF_val, dtype=np.float64)

        # 2026-07-10 lateral-K: optional per-cell (Nx, Ny) K/cF override in
        # SIMPLE coords. None → solve() tiles the per-row _K_arr laterally
        # (bit-identical: kernels average equal values / index the same row).
        # Set via set_K_cF_field() by callers whose design varies K across the
        # stream (port-BC routing studies). The 1D _K_arr stays authoritative
        # for every other consumer (seeds, diagnostics).
        self._K_field2d = None
        self._cF_field2d = None
        # 2026-07-10 cf-aniso: oblique-flow Forchheimer direction factor
        # cF_eff = cF·(1 + cf_aniso·4nx²ny²) (lowest cubic-symmetry
        # invariant; 0 on-axis, max at 45°). Default 0.0 = isotropic —
        # kernels skip the branch bit-identically. On-axis flow is unchanged
        # for ANY value (the calibration-anchored cF IS the on-axis value,
        # so this cannot double-count the γ roughness anchor). Calibrate
        # from direction-resolved unit-cell CFD (validation/cf_aniso/)
        # before quoting numbers from a non-zero setting.
        self.cf_aniso = 0.0

        # Inlet — use overlap fraction for exact mass conservation
        # v_inlet is the scalar reference inlet velocity (kept for the
        # mass-flux target capture + back-compat diagnostics). v_inlet_field is
        # the per-cross-stream-cell inlet velocity the kernels actually impose
        # (Option A, 2026-06-25): with the mass-flux inlet on it is rescaled
        # per cell by the local inlet density (see _apply_massflux_inlet), the
        # 2D analogue of SIMPLESolver3D.v_inlet_field. For a uniform full-face
        # inlet every cell shares the same density ⇒ v_inlet_field is uniform ⇒
        # bit-identical to the scalar path.
        self.v_inlet = v_inlet

        # Fields
        self.u  = np.zeros((Nx + 1, Ny))
        self.v  = np.zeros((Nx, Ny + 1))
        self.P  = np.full((Nx, Ny), P_ref)
        self.Pp = np.zeros((Nx, Ny))
        self.d_u = np.zeros((Nx + 1, Ny))
        self.d_v = np.zeros((Nx, Ny + 1))

        # Temperature (allocated on demand)
        self.Tf = None
        self.Ts = None

        self._pp_sparsity = None  # lazily built on first solve() call
        self._refresh_ports(inlet_lo, inlet_hi, outlet_lo, outlet_hi)
        self.residuals = []

        # If an explicit non-uniform T_field was passed (not the default T_in
        # broadcast), refresh mu_field / mu_eff_field to match. For the default
        # uniform T_in case the initial scalar-broadcast from L846-848 is
        # already consistent with Sutherland at T_in, but calling it is cheap
        # and guarantees mu_field is in sync with T_field at all times.
        if self.fluid_type == 'ideal_gas':
            self._refresh_mu_from_T()

    def _refresh_ports(self, inlet_lo, inlet_hi, outlet_lo, outlet_hi):
        """Initialize port profiles on the final grid before the first solve."""
        Nx = self.Nx
        self.v_inlet_field = np.full(Nx, float(self.v_inlet), dtype=np.float64)
        inf_raw, self.inlet_frac = _port_fractions_1d(self.dx_arr, inlet_lo, inlet_hi)
        self.inlet_geom_frac = inf_raw
        # N3 (2026-07-07): the taper smooths the imposed profile but must not
        # DELETE throughput — unrenormalised it under-delivered the imposed
        # inlet mass flux by ~0.914 cell-widths of open area per pipe edge, a
        # grid-dependent deficit (finer grid → smaller loss). Scale the
        # imposed velocity so the tapered profile carries exactly the
        # geometric open-area flux; the mass-flux-inlet target applies the
        # same factor at capture (see solve()). The guard keeps full-face
        # runs (taper never fires) bit-identical.
        self._inlet_taper_flux_scale = 1.0
        if np.any(self.inlet_frac != inf_raw):
            _geom_flux = float(np.sum(inf_raw * self.dx_arr))
            _eff_flux = float(np.sum(self.inlet_frac * self.dx_arr))
            if _eff_flux > 1e-30 and _geom_flux > 0.0:
                self._inlet_taper_flux_scale = _geom_flux / _eff_flux
                self.v_inlet_field *= self._inlet_taper_flux_scale
        self.inlet_mask = self.inlet_frac > 0.01     # boolean for temperature BC

        # Outlet — partial or full-width, with smooth lateral transition
        if outlet_lo is not None and outlet_hi is not None:
            self.outlet_geom_frac, self.outlet_frac = _port_fractions_1d(
                self.dx_arr, outlet_lo, outlet_hi)
            self.outlet_frac = self.outlet_frac.astype(np.float64)
        else:
            outlet_lo, outlet_hi = 0., float(np.sum(self.dx_arr))
            self.outlet_frac = np.ones(Nx, dtype=np.float64)
            self.outlet_geom_frac = self.outlet_frac.copy()
        self.outlet_u_frac = _port_overlap_1d(
            self.dx_arr, outlet_lo, outlet_hi, staggered=True)

        self.outlet_mask = self.outlet_geom_frac > 0.0
        self._pp_sparsity = None
        self._set_bc()

    def _set_bc(self):
        Nx, Ny = self.Nx, self.Ny
        self.u[0, :] = 0.0;  self.u[Nx, :] = 0.0
        for i in range(Nx):
            self.v[i, 0] = self.v_inlet_field[i] * self.inlet_frac[i]
            self.v[i, Ny] = self.v[i, Ny - 1] if self.outlet_mask[i] else 0.0

    def update_rho_field(self, rho_field):
        """Update density field for variable-density coupling iterations."""
        self.rho_field = np.ascontiguousarray(rho_field, dtype=np.float64)
        self.rho = float(self.rho_field.mean())

    def _update_density(self):
        """Update rho_field from pressure field (ideal gas: rho = P_abs / (R*T)).
        Under-relaxed to avoid oscillation. With the mass-flux inlet on (default),
        the inlet mass flux ρ·v is held constant and v_inlet is rescaled to track
        the (under-relaxed) inlet density — see _apply_massflux_inlet. No-op for
        incompressible.

        Clipping policy (2026-05-06 fix #1; envelope widened 2026-05-07):
            Clip the *physical inputs* (P_abs) to the HX operating envelope
            [1 kPa, 10 MPa] (originally [10 kPa, 1 MPa]; widened so high-u
            Forchheimer transients don't trip the clip — see below), then derive
            ρ from ρ = P/(R·T). Do NOT clip ρ directly — that would silently
            break the ideal-gas relation.
            Previous code clipped ρ ∈ [0.01, 100] kg/m³ which corresponds to
            P~770 Pa or P~78×STP, far outside any real HX state, and could
            decouple ρ from (P,T) during transient iterations.
        """
        if self.fluid_type != 'ideal_gas':
            return
        # Persistent scratch (R2, openspec solver-efficiency-r1-r4): P_abs and
        # rho_new were reallocated every outer iteration (7% of pipeline wall
        # on small grids); reuse buffers like solve()'s _rho_eps. Bit-identical
        # (commutative add/multiply, same operand values).
        if getattr(self, '_pabs_buf', None) is None or \
                self._pabs_buf.shape != self.P.shape:
            self._pabs_buf = np.empty_like(self.P)
            self._rho_new_buf = np.empty_like(self.P)
        P_abs = self._pabs_buf
        np.add(self.P, self.P_ref_abs, out=P_abs)
        # 2026-05-07: clip widened from [10 kPa, 1 MPa] to [1 kPa, 10 MPa]
        # so SIMPLE transients on high-u cases (u>10 m/s, Forchheimer
        # branch) don't trip the clip and stall outer convergence. See
        # simple_solver_3d.py:_update_density for the full rationale.
        _eng = (P_abs < 1.0e3) | (P_abs > 10.0e6)
        try:
            self._p_clip_hits = (
                getattr(self, '_p_clip_hits', 0) + int(np.count_nonzero(_eng)))
        except Exception:
            pass
        np.clip(P_abs, 1.0e3, 10.0e6, out=P_abs)  # 1 kPa .. 10 MPa
        # Robustness (2026-06-25): also floor the STORED gauge field where the
        # clip engaged, so the momentum pressure-gradient source can't carry a
        # negative absolute pressure into the next sweep. In-envelope solves
        # never clip (_eng all False) -> self.P untouched -> bit-identical.
        if _eng.any():
            self.P = np.where(_eng, P_abs - self.P_ref_abs, self.P)
        rho_new = self._rho_new_buf
        np.multiply(self.T_field, self.R_gas, out=rho_new)
        np.divide(P_abs, rho_new, out=rho_new)
        # No ρ clip: ρ derives from (P,T); clipping ρ violates ideal gas law.
        # Blend stays a rebind (not in-place): rho_field may alias the caller's
        # array from __init__ (ascontiguousarray no-copy) — never mutate it.
        self.rho_field = (self.alpha_rho * rho_new
                          + (1.0 - self.alpha_rho) * self.rho_field)
        # Compressible inlet: hold the inlet MASS FLUX (ρ·v) constant, not v.
        self._apply_massflux_inlet()

    def _apply_massflux_inlet(self):
        """Re-impose a mass-flux inlet: v_inlet_field = G_target / ρ_inlet (2D
        port of SIMPLESolver3D._apply_massflux_inlet, 2026-06-25).

        Velocity-inlet (fixed v) + compressible ρ=P/(RT) + Forchheimer
        (dP∝ρ·u² at fixed u) is a POSITIVE feedback (dP↑→P↑→ρ↑→dP↑): for
        high-resistance / strongly-compressible runs (Shanghai air side, P drops
        a third over the core) it lets the inlet mass flux ρ·u drift with the
        grid, so Δp never converges (p_obs≈0) and under-reports badly. Holding
        the mass flux G=ρ·v constant makes it NEGATIVE feedback (ρ↑→v=G/ρ↓→
        dP↓) → grid-convergent and physically correct. `_massflux_target` is
        the scalar reference throughput G captured once at solve start from
        (v_inlet, ρ_inlet,ref).

        Option A (per-cell): rescale EACH cross-stream inlet cell by its own
        (already α_rho-damped) inlet density rho_field[i,0] — the 2D analogue
        of the 3D v_inlet_field[:,k] = G/ρ[:,0,k]. No extra under-relaxation is
        needed (ρ is already damped). For a uniform full-face inlet ρ[:,0] is
        constant ⇒ v_inlet_field is uniform ⇒ identical to the scalar Option B.
        self.v_inlet is kept as the lateral mean for back-compat / diagnostics.
        For low-dP runs (water is incompressible and returns earlier; aligned
        low-u air) ρ≈ρ_ref so v≈v_specified — behaviour ≈ legacy velocity-inlet.

        No-op when disabled or before the target is captured (keeps the method
        self-safe for unit tests); the ideal_gas guard in _update_density makes
        it a no-op for incompressible fluids.
        """
        if not getattr(self, 'massflux_inlet', True):
            return
        if not hasattr(self, '_massflux_target'):
            return
        rho_in = np.maximum(self.rho_field[:, 0], 1e-9)        # per cell (Nx,)
        self.v_inlet_field = np.ascontiguousarray(
            self._massflux_target / rho_in, dtype=np.float64)
        self.v_inlet = float(self.v_inlet_field.mean())        # back-compat scalar

    def update_T_field(self, T_field):
        """Update temperature field. Also refreshes mu_field / mu_eff_field via
        Sutherland so that non-isothermal D-F coupling stays consistent.

        If wall refinement is on and the incoming T_field has the pre-refine
        shape, we linearly interpolate along the cross-stream axis so the user
        can keep passing fields at their original resolution (common in the
        non-isothermal coupling loop, e.g. validate_shanghai_aligned.py).
        """
        if np.ndim(T_field) == 0:
            self.T_field = np.full((self.Nx, self.Ny), float(T_field), dtype=np.float64)
        else:
            T_in = np.asarray(T_field, dtype=np.float64)
            if T_in.shape != (self.Nx, self.Ny) and self._wall_refined:
                # Interpolate cross-stream axis from pre-refine Nx to refined Nx
                T_in = self._interp_to_refined_cross(T_in)
            self.T_field = np.ascontiguousarray(T_in, dtype=np.float64)
        if self.fluid_type == 'ideal_gas':
            self._refresh_mu_from_T()

    def _interp_to_refined_cross(self, field_2d):
        """Interpolate a (Nx_coarse, Ny) field onto refined (Nx, Ny) grid along
        cross-stream axis (axis=0). Uses cell-center physical positions."""
        Nx_in, Ny_in = field_2d.shape
        if Ny_in != self.Ny:
            raise ValueError(
                f"field Ny mismatch: got {Ny_in}, expected {self.Ny}")
        # Cell-center positions (pre-refine uniform)
        W_total = self.dx_arr.sum()
        dx_coarse = W_total / Nx_in
        y_coarse = (np.arange(Nx_in) + 0.5) * dx_coarse
        # Refined cell centers
        y_edges = np.concatenate([[0.0], np.cumsum(self.dx_arr)])
        y_refined = 0.5 * (y_edges[:-1] + y_edges[1:])
        # Linear interp per y-column (streamwise index)
        out = np.empty((self.Nx, self.Ny), dtype=np.float64)
        for j in range(self.Ny):
            out[:, j] = np.interp(y_refined, y_coarse, field_2d[:, j])
        return out

    def _refresh_mu_from_T(self):
        """Recompute mu_field and mu_eff_field from self.T_field via Sutherland.
        Called after update_T_field (and once during __init__ for ideal gas)."""
        from sjtu_tpmshx.models.tpms_calc import air_viscosity
        mu_new = air_viscosity(self.T_field).astype(np.float64)
        self.mu_field = np.ascontiguousarray(mu_new)
        # Per-cell μ/ε (zoned ε support); falls back to uniform self.eps.
        eps_eff = self.eps_field if hasattr(self, 'eps_field') else self.eps
        self._mu_eff_field = np.ascontiguousarray(mu_new / eps_eff)

    # ──────────────── velocity solve ──────────────────────────────
    def set_K_cF_field(self, K2d, cF2d):
        """Per-cell Darcy-Forchheimer override (SIMPLE coords, shape (Nx, Ny)).

        2026-07-10 lateral-K: gives the momentum drag lateral (cross-stream)
        variation — the per-row 1D projection (`override_simple_K_cF`)
        averages laterally before predicting, which erases the resistance
        contrast that port-BC routing studies need. The 1D `_K_arr` stays
        authoritative for non-kernel consumers (seeds, diagnostics); when
        this override is set, the momentum kernels consume it instead.
        """
        K2d = np.ascontiguousarray(K2d, dtype=np.float64)
        cF2d = np.ascontiguousarray(cF2d, dtype=np.float64)
        want = (self.Nx, self.Ny)
        if K2d.shape != want or cF2d.shape != want:
            raise ValueError(
                f"K/cF field shape {K2d.shape}/{cF2d.shape} != {want}")
        self._K_field2d = K2d
        self._cF_field2d = cF2d

    def solve(self, max_iter=3000, tol=1e-6,
              alpha_u=0.7, alpha_p=0.3,
              n_inner=2,
              verbose=True, progress_cb=None, cancel_check=None):
        """
        Run SIMPLE iterations. PP equation solved by sparse direct solver.

        Returns (converged: bool, iterations: int).
        """
        Nx, Ny = self.Nx, self.Ny
        dx_a, dy_a = self.dx_arr, self.dy_arr

        # ── A+B early-exit (R1) — criteria single-sourced in
        # solvers/_solve_common.LowReExit since arch-b-c-e batch C (the 2D/3D
        # copies drifted for months before R1; see that module's docstring).
        _lowre = LowReExit(self, (self.u, self.v), min_iter=20)

        # ── Ledger C9 / F2 — convergence mode (mirrors the 3D solver, C7) ──
        # 'legacy' (default): `tol` on `_mass_res_jit` + LowReExit.
        #     That residual is a PLANE-INTEGRATED flux defect, and the pp solve
        #     drives the per-cell divergence to zero, so every plane's flux
        #     telescopes to the inlet's — on a FULL-FACE outlet it is a
        #     TAUTOLOGY (measured 1.6e-15). `tol` therefore fires at the
        #     min-iter floor (iteration 20) and the solve stops there.
        #     Measured cost on the production Pipeline2D: dP_A under-converged
        #     by -3.3 %. Kept as the default until F2 is priced and re-baselined.
        # 'f2'    : three independent gates — momentum residual + solved-cell
        #     continuity (fresh rho, cell_kind == 0) + global boundary mass —
        #     each with its own tolerance, confirmed over consecutive checks.
        #     A static velocity field TRIGGERS a check; it does NOT terminate.
        _mode = str(getattr(self, 'convergence_mode',
                            os.environ.get('TPMSHX_CONV_MODE', 'legacy')))
        if _mode not in ('legacy', 'f2'):
            raise ValueError(
                f"convergence_mode must be 'legacy' or 'f2', got {_mode!r}")
        _f2 = None
        if _mode == 'f2':
            _f2 = F2Monitor(self, (self.u, self.v), min_iter=20)
            for _h in ('mom_residuals', 'mass_local_residuals',
                       'mass_global_residuals'):
                if not hasattr(self, _h):
                    setattr(self, _h, [])
            self.final_res_mom = None
            self.final_res_mass_local = None
            self.final_res_mass_global = None
            self.outlet_backflow_frac = 0.0
            # Legacy attribute name: gates on the returned field after local
            # outlet closure; None until an F2 exit happens.
            self.f2_cert_post_rescale_ok = None
        # A2: exit bookkeeping — 'tol' | 'velocity' | 'stall' | 'max_iter' | 'nonfinite';
        # reset on every (re-)entry (the 2D pipeline rebuilds the solver per
        # outer iteration, but direct callers may reuse one instance).
        self.exit_reason = None
        self.final_res = None
        if _f2 is not None and not f2_state_is_finite(self, (self.u, self.v)):
            return f2_nonfinite_exit(self, 0)

        # Capture the mass-flux inlet target G = v · ρ_inlet,ref ONCE, before
        # any pressure build-up. The `not hasattr` guard keeps it fixed across
        # warm restarts. Prefer the explicit `rho_inlet_ref` (the physical
        # inlet density the caller used to define v_inlet) — that is grid- and
        # datum-independent, so it pins the *physical* throughput identically
        # on every grid and on every recreation of the solver. When it is not
        # supplied, fall back to the 3D-style capture from rho_field[:,0]. An
        # explicit reference also enables this invariant for a variable-density
        # fluid whose momentum model is otherwise labelled incompressible.
        if (getattr(self, 'massflux_inlet', True)
                and (self.fluid_type == 'ideal_gas'
                     or self._rho_inlet_ref is not None)
                and not hasattr(self, '_massflux_target')):
            if self._rho_inlet_ref is not None:
                _rho_ref_in = self._rho_inlet_ref
            else:
                _rho_ref_in = float(self.rho_field[:, 0].mean())
            # N3: the taper-renormalisation factor rides on the target too —
            # _apply_massflux_inlet rebuilds v_inlet_field from this target
            # every iteration, so an init-time field scaling alone would be
            # overwritten. Σ ρ·(G/ρ)·frac·dx then equals the geometric
            # open-area flux exactly. 1.0 unless the edge taper fired.
            self._massflux_target = (float(self.v_inlet) * _rho_ref_in
                                     * getattr(self, '_inlet_taper_flux_scale',
                                               1.0))
            if self.fluid_type != 'ideal_gas':
                self._apply_massflux_inlet()

        # 2026-07-10 lateral-K: kernels consume 2D (Nx, Ny) K/cF fields. An
        # explicit per-cell override (set_K_cF_field) wins; otherwise tile the
        # per-row arrays — the kernels then reproduce the historical per-row
        # drag bit-identically (equal-value averages are IEEE-exact).
        if self._K_field2d is not None:
            _K2d, _cF2d = self._K_field2d, self._cF_field2d
        else:
            _K2d = np.ascontiguousarray(
                np.repeat(self._K_arr[None, :], Nx, axis=0))
            _cF2d = np.ascontiguousarray(
                np.repeat(self._cF_arr[None, :], Nx, axis=0))

        for it in range(1, max_iter + 1):
            if cancel_check is not None and cancel_check():
                raise CancelledError("compute cancelled by user")
            # Effective density for continuity (#2 fix): ε·ρ. Uniform ε →
            # multiplicative constant (no functional change). Zoned ε →
            # captures macroscopic ∇·(ε·ρ·u)=0 form. Momentum unchanged
            # (uses interstitial u with ε encoded in K).
            # Reuse a persistent buffer instead of allocating ε·ρ every outer
            # iteration. Bit-identical to ascontiguousarray(rho*eps): same
            # float64 products, and rho_eps_field is only read (PP solve + mass
            # residual) within this iteration, never retained across iters.
            if getattr(self, '_rho_eps', None) is None or \
                    self._rho_eps.shape != self.rho_field.shape:
                self._rho_eps = np.empty_like(self.rho_field)
            np.multiply(self.rho_field, self.eps_field, out=self._rho_eps)
            rho_eps_field = self._rho_eps
            if self._pp_sparsity is None:
                self._pp_sparsity = _build_pp_sparsity_pattern(Nx, Ny, self.outlet_geom_frac)

            _sweep_u_jit_df(self.u, self.v, self.P, self.d_u,
                            self.outlet_u_frac,
                            Nx, Ny, dx_a, dy_a, self.rho_field, self._mu_eff_field,
                            _K2d, _cF2d, self.mu_field,
                            self.eps_field,
                            alpha_u, n_inner, self.cf_aniso)
            _sweep_v_jit_df(self.u, self.v, self.P, self.d_v,
                            self.inlet_frac, self.v_inlet_field, self.outlet_geom_frac,
                            Nx, Ny, dx_a, dy_a, self.rho_field, self._mu_eff_field,
                            _K2d, _cF2d, self.mu_field,
                            self.eps_field,
                            alpha_u, n_inner, self.cf_aniso)
            _solve_pp_sparse_fast(self.Pp, self.u, self.v, self.d_u, self.d_v,
                                  self.outlet_geom_frac,
                                  Nx, Ny, dx_a, dy_a, rho_eps_field,
                                  self._pp_sparsity)
            _correct_jit(self.u, self.v, self.P, self.Pp,
                         self.d_u, self.d_v,
                         self.inlet_frac, self.v_inlet_field, self.outlet_geom_frac,
                         Nx, Ny, dx_a, dy_a, alpha_p, self.rho_field, self.eps_field)
            if (_f2 is not None and self.fluid_type == 'ideal_gas'
                    and not f2_state_is_finite(self, (self.u, self.v))):
                return f2_nonfinite_exit(self, it)
            self._update_density()  # compressible: update rho from P
            if _f2 is not None and not f2_state_is_finite(self, (self.u, self.v)):
                return f2_nonfinite_exit(self, it)

            res = _mass_res_jit(self.u, self.v, Nx, Ny, dx_a, dy_a, rho_eps_field)
            self.residuals.append(res)

            # Live progress hook for UI sparklines — throttled to every
            # 20 iters so a compute with 5000 iters pushes 250 samples max.
            if progress_cb is not None and (it % 20 == 0 or it == 1):
                try:
                    progress_cb(it, float(res))
                except Exception:
                    pass

            if verbose and it % 200 == 0:
                _log.info(f"  iter {it:5d}  |R| = {res:.3e}")

            # ══ F2 path (ledger C9) — three honest gates ══════════════════
            if _f2 is not None:
                _vd = _f2.velocity_delta((self.u, self.v))

                _rho_eps_now = np.ascontiguousarray(
                    self.rho_field * self.eps_field, dtype=np.float64)
                _Rml, _n_solved = _mass_res_solved_jit_2d(
                    self.u, self.v, Nx, Ny, dx_a, dy_a,
                    _rho_eps_now, self._pp_sparsity['cell_kind'])
                _min, _mout, _bf = _mass_global_jit_2d(
                    self.v, Nx, Ny, dx_a, _rho_eps_now)
                _Rmg = global_mass_residual(_min, _mout)
                self.mass_local_residuals.append(_Rml)
                self.mass_global_residuals.append(_Rmg)
                self.outlet_backflow_frac = _bf
                self.final_res_mass_local = _Rml
                self.final_res_mass_global = _Rmg
                if not np.isfinite((res, _vd, _Rml, _Rmg, _bf)).all():
                    return f2_nonfinite_exit(self, it)

                if _f2.should_eval_momentum(it, _vd):
                    _Rmom, _rec = self._momentum_residual(Nx, Ny, dx_a, dy_a,
                                                          _K2d, _cF2d)
                    _rec['iter'] = it
                    self.mom_residuals.append(_rec)
                    self.final_res_mom = _Rmom
                    _reason = _f2.submit(it, _Rmom, _Rml, _Rmg, _vd, _bf)
                    if _reason == 'nonfinite':
                        return f2_nonfinite_exit(self, it)
                    if _reason is not None:
                        self._enforce_mass_conservation(verbose=verbose)
                        if not f2_state_is_finite(self, (self.u, self.v)):
                            return f2_nonfinite_exit(self, it)
                        # Re-measure the returned field after local outlet closure.
                        # Keep the original exit decision; post-checks may only
                        # reject convergence, never upgrade a failed pre-check.
                        _rho_eps_post = np.ascontiguousarray(
                            self.rho_field * self.eps_field, dtype=np.float64)
                        _Rml_p, _ = _mass_res_solved_jit_2d(
                            self.u, self.v, Nx, Ny, dx_a, dy_a,
                            _rho_eps_post, self._pp_sparsity['cell_kind'])
                        _min_p, _mout_p, _bf_p = _mass_global_jit_2d(
                            self.v, Nx, Ny, dx_a, _rho_eps_post)
                        _Rmg_p = global_mass_residual(_min_p, _mout_p)
                        _Rmom_p, _ = self._momentum_residual(
                            Nx, Ny, dx_a, dy_a, _K2d, _cF2d)
                        self.final_res_mass_local = _Rml_p
                        self.final_res_mass_global = _Rmg_p
                        self.final_res_mom = _Rmom_p
                        self.outlet_backflow_frac = _bf_p
                        if not np.isfinite((_Rmom_p, _Rml_p, _Rmg_p, _bf_p)).all():
                            return f2_nonfinite_exit(self, it)
                        self.f2_cert_post_rescale_ok = bool(
                            _Rmom_p < _f2.mom_tol
                            and _Rml_p < _f2.mass_local_tol
                            and _Rmg_p < _f2.mass_global_tol
                            and _bf_p <= _f2.backflow_max)
                        if _reason == 'tol' and not self.f2_cert_post_rescale_ok:
                            _log.warning(
                                "  [WARN] F2 gates held BEFORE the outlet mass "
                                "closure but not after (mom %.2e local %.2e "
                                "global %.2e backflow %.2e) — the returned "
                                "field's certificate exceeds the gates; "
                                "inspect the returned outlet field.",
                                _Rmom_p, _Rml_p, _Rmg_p, _bf_p)
                        self.exit_reason = _reason
                        self.final_res = res
                        return (_reason == 'tol' and self.f2_cert_post_rescale_ok), it
                # NOTE: no `velocity` exit. A static field only TRIGGERS a check
                # (F2Monitor.should_eval_momentum); it never terminates.
                continue

            # ── LEGACY path ──────────────────────────────────────────────
            # Require minimum iterations for pressure field to develop
            # (exact PP gives mass convergence in 1 iter, but P needs more).
            #
            # ⚠️ Ledger C9: on a FULL-FACE outlet `res` is a TAUTOLOGY. The pp
            # solve drives the per-cell divergence to zero, so every plane's flux
            # telescopes to the inlet's and this plane-integrated defect reaches
            # ~1e-15. `tol` therefore fires at THIS `it >= 20` floor, and the
            # solve stops at iteration 20 — measured cost on the production
            # Pipeline2D: dP_A under-converged by -3.3 %. Use convergence_mode
            # ='f2' for a criterion that means something.
            if res < tol and it >= 20:
                if verbose:
                    _log.info(f"  [OK] Converged at iter {it}, |R| = {res:.3e}")
                self._enforce_mass_conservation(verbose=verbose)
                self.exit_reason = 'tol'
                self.final_res = res
                return True, it

            # ── A+B early-exit — see LowReExit. Closeout mirrors the strict
            # path (2D-specific _enforce_mass_conservation).
            _reason = _lowre.check((self.u, self.v), res, it)
            if _reason is not None:
                if verbose:
                    _label = ('velocity static' if _reason == 'velocity'
                              else 'plateau stall')
                    _log.info(f"  [OK] Early exit ({_label}) at "
                              f"iter {it}, |R| = {res:.3e}")
                self._enforce_mass_conservation(verbose=verbose)
                # A2 (2026-07-06): 'velocity' (field static) = converged
                # fixed point; 'stall' (residual plateau, still-creeping
                # field) returns the fields but reports converged=False.
                self.exit_reason = _reason
                self.final_res = res
                return (_reason == 'velocity'), it

        if verbose:
            _log.warning(f"  [!!] NOT converged after {max_iter} iters, |R| = {res:.3e}")

        # Post-solve: enforce mass conservation at partial outlet
        self._enforce_mass_conservation(verbose=verbose)
        if _f2 is not None and not f2_state_is_finite(self, (self.u, self.v)):
            return f2_nonfinite_exit(self, max_iter)

        self.exit_reason = 'max_iter'
        self.final_res = res
        return False, max_iter

    # ── ledger C9 — momentum residual, balanced normalisation (mirrors 3D) ──
    _MOM_FLOOR_FRAC = 1e-3

    def _momentum_residual(self, Nx, Ny, dx_a, dy_a, K2d, cF2d):
        """(R_max, record) on the solver's CURRENT state.

        Balanced denominator (see `_mom_res_jit_2d` / `_mom_res_jit_3d`):
        den_c = Σ½(|lhs| + |rhs|), so `num > 0 ⟹ den > 0` and a false zero is
        structurally impossible; the ratio is bounded by 2.

        COMMON FLOOR: each component is divided by `max(den_c, floor)` with
        `floor = _MOM_FLOOR_FRAC * max(den_u, den_v)`, so a physically negligible
        component cannot hold the gate open on numerical noise.

        Raw num/den are kept in the record so the normalisation can be revisited
        without re-running.
        """
        nu_, du_, nv_, dv_ = _mom_res_jit_2d(
            self.u, self.v, self.P, Nx, Ny, dx_a, dy_a,
            self.rho_field, self._mu_eff_field, K2d, cF2d, self.mu_field,
            self.eps_field, self.outlet_u_frac, self.cf_aniso)
        ru, rv = momentum_component_residuals(
            (nu_, nv_), (du_, dv_), self._MOM_FLOOR_FRAC)
        rmax = max(ru, rv)
        return rmax, {'u': ru, 'v': rv, 'max': rmax,
                      'num': (nu_, nv_), 'den': (du_, dv_)}

    def _enforce_mass_conservation(self, verbose=True):
        """Close outlet CV mass with the current density and porosity.

        The final density update may change the face fluxes. Reapply the local
        closure without hiding interior mass defects with a global rescale.
        Set enforce_outlet_mass_balance=False to disable this exit closeout.
        """
        self._last_outlet_mass_scale = 1.0  # No global velocity scaling.
        if not getattr(self, 'enforce_outlet_mass_balance', True):
            return
        _close_outlet_mass(self.u, self.v, self.outlet_geom_frac, self.Nx, self.Ny,
                           self.dx_arr, self.dy_arr, self.rho_field, self.eps_field)

    # ──────────────── temperature solve ───────────────────────────
    def solve_temperature(self, K_ff, K_ss, h_v, rho_cp_f,
                          T_in, T_other=None, h_v2=0.0,
                          max_iter=5000, tol=1e-4, verbose=True):
        """
        Solve LTNE temperature with frozen velocity field.

        Parameters
        ----------
        K_ff      : fluid effective conductivity [W/(m K)]   (= eps * k_f)
        K_ss      : solid effective conductivity [W/(m K)]   (= (1-eps) * k_s)
        h_v       : volumetric HTC, fluid <-> solid [W/(m3 K)]  (= H_sf * A_0)
        rho_cp_f  : fluid volumetric heat capacity [J/(m3 K)]
        T_in      : fluid inlet temperature [K]
        T_other   : other-fluid temperature [K] (scalar).
                    If None, solid is adiabatic (h_v2 forced to 0).
        h_v2      : volumetric HTC, other-fluid <-> solid [W/(m3 K)]
        """
        Nx, Ny = self.Nx, self.Ny
        if T_other is None:
            T_other = T_in
            h_v2 = 0.0

        # Initialise temperature fields
        self.Tf = np.full((Nx, Ny), T_in)
        self.Ts = np.full((Nx, Ny), 0.5 * (T_in + T_other))

        iters = _solve_temp_jit(
            self.Tf, self.Ts, self.u, self.v, self.inlet_mask,
            Nx, Ny, self.dx_arr, self.dy_arr, self.eps,
            K_ff, K_ss, h_v, h_v2, rho_cp_f,
            T_in, T_other, max_iter, tol)

        if verbose:
            tag = "[OK]" if iters < max_iter else "[!!]"
            _log.info(f"  {tag} Temperature: {iters} iters, "
                      f"Tf=[{self.Tf.min():.2f}, {self.Tf.max():.2f}], "
                      f"Ts=[{self.Ts.min():.2f}, {self.Ts.max():.2f}]")
        return iters < max_iter, iters

    # ──────────────── output for coupling ─────────────────────────
    def _check_uniform(self, j, threshold):
        """Check if cross-section j has uniform flow.

        Two conditions must BOTH be met:
        1. Main flow (v) uniformity:  std(v) / mean(v) < threshold
        2. Transverse flow (u) negligible: mean(|u|) / mean(v) < threshold

        References:
          - Mueller & Chiou (1988): 5% CV = significant maldistribution
          - Lalot et al. (1999): relative std dev for HX flow distribution
          - ~5% is the standard HX threshold; the code default is 0.045 (4.5%)
        """
        Nx = self.Nx
        v_row = self.v[:, j]
        v_mean = v_row.mean()
        if v_mean < 1e-10:
            return False

        # Condition 1: main flow uniformity (coefficient of variation)
        cv_v = v_row.std() / v_mean
        if cv_v >= threshold:
            return False

        # Condition 2: transverse velocity negligible
        # u lives on x-faces: u[0..Nx, j]. Average |u| at internal faces.
        u_at_j = self.u[1:Nx, j]   # internal x-face velocities at row j
        u_ratio = np.abs(u_at_j).mean() / v_mean
        if u_ratio >= threshold:
            return False

        return True

    def detect_uniform_boundary(self, threshold=0.045):
        """Find the first cross-section (from pipe side) where flow is uniform.

        Scans from j=1 (near pipe) toward j=Ny-1 (far from pipe).
        Checks both v-uniformity AND u-negligibility.

        Parameters
        ----------
        threshold : float, default 0.045 (4.5%; ~5% is the textbook HX standard)

        Returns
        -------
        j_uniform : int   (row index where flow becomes uniform, or Ny-1)
        depth     : float (transition zone depth in metres)
        """
        for j in range(1, self.Ny):
            if self._check_uniform(j, threshold):
                return j, j * self.dy
        return self.Ny - 1, (self.Ny - 1) * self.dy

    def detect_nonuniform_boundary(self, threshold=0.045):
        """Scan from the UNIFORM side (top, j=Ny-1) toward the pipe (j=0).

        Find the first cross-section that is NOT uniform (where converging
        effects begin). Uses same dual check as detect_uniform_boundary.

        Returns
        -------
        j_start : int   (last uniform row, counting from top)
        depth   : float (outlet transition zone depth in metres)
        """
        for j in range(self.Ny - 1, 0, -1):
            if not self._check_uniform(j, threshold):
                depth = (self.Ny - 1 - j) * self.dy
                return j + 1, depth
        return 0, (self.Ny - 1) * self.dy

    def get_profile_at(self, j_row):
        """Extract velocity + temperature profiles at a specific row j."""
        Nx, Ny = self.Nx, self.Ny
        j = min(max(j_row, 0), Ny - 1)
        out = {
            'v_exit': self.v[:, j].copy(),
            'u_exit': self.u[1:Nx, j].copy(),
            # cell-center / face x-coords from per-cell dx_arr (correct on
            # non-uniform grids; == arange*dx on uniform grids).
            'x_v':   np.cumsum(self.dx_arr) - 0.5 * self.dx_arr,
            'x_u':   np.cumsum(self.dx_arr)[:Nx - 1],
            'j_row':  j,
            'depth':  float(np.sum(self.dy_arr[:j])),
        }
        if self.Tf is not None:
            out['Tf_exit'] = self.Tf[:, j].copy()
            out['Ts_exit'] = self.Ts[:, j].copy()
        return out

    def get_exit_profile(self):
        """Velocity + temperature at exit (top boundary) for uniform-zone BC."""
        Nx, Ny = self.Nx, self.Ny
        out = {
            'v_exit': self.v[:, Ny - 1].copy(),
            'u_exit': self.u[1:Nx, Ny - 1].copy(),
            'x_v':   np.cumsum(self.dx_arr) - 0.5 * self.dx_arr,
            'x_u':   np.cumsum(self.dx_arr)[:Nx - 1],
        }
        if self.Tf is not None:
            out['Tf_exit'] = self.Tf[:, Ny - 1].copy()
            out['Ts_exit'] = self.Ts[:, Ny - 1].copy()
        return out

    def get_fields_trimmed(self, j_start=0, j_end=None):
        """Return 2D fields trimmed to rows [j_start, j_end).

        Useful for extracting just the transition zone portion for plotting.
        """
        if j_end is None:
            j_end = self.Ny
        out = {'v': self.v[:, j_start:j_end+1].copy(),
               'u': self.u[:, j_start:j_end].copy(),
               'P': self.P[:, j_start:j_end].copy()}
        if self.Tf is not None:
            out['Tf'] = self.Tf[:, j_start:j_end].copy()
            out['Ts'] = self.Ts[:, j_start:j_end].copy()
        return out

    @staticmethod
    def solve_outlet_transition(W, H_search, Nx, Ny,
                                tpms_type, L_cell_mm, t_mm, eps, r_h,
                                rho, mu, T_uni_exit,
                                pipe_lo, pipe_hi, u_exit,
                                K_ff, K_ss, h_v, rho_cp_f,
                                T_other=None, h_v2=0.0,
                                threshold=0.02):
        """Solve outlet transition zone (uniform flow → converging to pipe).

        Uses the flip trick: solve bottom-inlet SIMPLE (spreading flow),
        then flip the domain vertically. The velocity field is approximately
        correct (porous media ≈ reversible). Temperature is solved with
        the flipped velocity and proper outlet BCs.

        Returns
        -------
        dict with keys: depth, dP, j_boundary, Tf_field, Ts_field, v_field, solver
        """
        # Step 1: Solve spreading flow (pipe at bottom) on oversized domain
        s = SIMPLESolver(W, H_search, Nx, Ny,
                         tpms_type, L_cell_mm, t_mm, eps, r_h,
                         rho, mu, T_uni_exit,
                         pipe_lo, pipe_hi, u_exit)
        s.solve(max_iter=3000, tol=1e-6, verbose=False)

        # Step 2: Detect where spreading flow becomes uniform
        j_uni, depth = s.detect_uniform_boundary(threshold)

        # Step 3: Solve temperature with correct BCs
        # The "inlet" of the outlet trans zone is the uniform zone exit (T_uni_exit)
        # which is already set as T_in for this solver.
        s.solve_temperature(K_ff, K_ss, h_v, rho_cp_f,
                            T_in=T_uni_exit, T_other=T_other,
                            h_v2=h_v2, verbose=False)

        # Step 4: Detect the outlet boundary from the uniform side
        j_start, depth_out = s.detect_nonuniform_boundary(threshold)

        # Pressure drop in the transition zone portion only
        if j_uni > 0:
            dP = abs(s.P[:, :j_uni+1].max() - s.P[:, :j_uni+1].min())
        else:
            dP = 0.0

        return {
            'depth': depth_out,
            'depth_spreading': depth,   # from inlet-like detection
            'dP': dP,
            'j_boundary': j_start,
            'solver': s,
        }

    def mass_flow_in(self):
        # Weight by per-cell dx_arr (== scalar dx on uniform grids).
        return self.rho * np.sum(self.v[self.inlet_mask, 0]
                                 * self.dx_arr[self.inlet_mask])

    def mass_flow_out(self):
        return self.rho * np.sum(self.v[:, self.Ny] * self.dx_arr)


# ===================================================================
#  Verification
# ===================================================================

if __name__ == '__main__':
    import time
    import warnings; warnings.filterwarnings('ignore')
    from sjtu_tpmshx.models.tpms_calc import compute as tpms_compute

    tpms = 'Diamond';  L_mm = 6.0;  t_mm = 0.4
    props = tpms_compute(tpms, L_mm, t_mm, 3.0, 300.0, 101325.0, 17.0)
    eps = props['epsilon'];  r_h = props['D_h'] / 2.0

    W, H = 0.03, 0.02;  Nx, Ny = 30, 20;  v_in = 3.0

    # ── Test 1: full-width inlet (uniform flow check) ──
    print("=" * 60)
    print("Test 1: full-width inlet")
    print("=" * 60)
    rho = air_density(300.0, 101325.0);  mu = air_viscosity(300.0)
    s = SIMPLESolver(W, H, Nx, Ny,
                     tpms, L_mm, t_mm, eps, r_h, rho, mu, 300.0,
                     0.0, W, v_in)

    print("  (first call includes Numba JIT compilation...)")
    t0 = time.time()
    ok, it = s.solve(max_iter=500, tol=1e-7, verbose=False)
    t1 = time.time()
    v_int = s.v[:, 1:-1];  u_int = s.u[1:-1, :]
    print(f"  time = {t1-t0:.2f}s  (includes JIT)")
    print(f"  converged={ok}, iters={it}")
    print(f"  v: mean={v_int.mean():.4f} std={v_int.std():.2e} (expect {v_in})")
    print(f"  u: mean={u_int.mean():.2e} (expect 0)")

    # Re-run to measure pure execution time
    s2 = SIMPLESolver(W, H, Nx, Ny,
                      tpms, L_mm, t_mm, eps, r_h, rho, mu, 300.0,
                      0.0, W, v_in)
    t0 = time.time()
    s2.solve(max_iter=500, tol=1e-7, verbose=False)
    t1 = time.time()
    print(f"  pure solve time (no JIT) = {t1-t0:.2f}s")
    print()

    # ── Test 2: half-width inlet + temperature ──
    print("=" * 60)
    print("Test 2: half-width inlet + temperature (T_other=400K)")
    print("=" * 60)
    inlet_lo = 0.25 * W;  inlet_hi = 0.75 * W
    s3 = SIMPLESolver(W, H, Nx, Ny,
                      tpms, L_mm, t_mm, eps, r_h, rho, mu, 300.0,
                      inlet_lo, inlet_hi, v_in)
    t0 = time.time()
    ok_v, it_v = s3.solve(max_iter=3000, tol=1e-6, verbose=False)
    t1 = time.time()
    print(f"  Velocity: converged={ok_v}, iters={it_v}, time={t1-t0:.2f}s")
    print(f"  m_in={s3.mass_flow_in():.6f}  m_out={s3.mass_flow_out():.6f}")

    # Temperature: Fluid B enters at 300K, Fluid A (other side) at 400K
    K_ff = eps * props['k_f']
    K_ss = (1.0 - eps) * 17.0
    A_0  = props['A_0']
    H_sf = props['H_sf']      # face HTC [W/(m2 K)]
    h_v  = H_sf * A_0         # volumetric HTC [W/(m3 K)]
    cp_air = 1005.0
    rho_cp = rho * cp_air

    t0 = time.time()
    ok_t, it_t = s3.solve_temperature(
        K_ff, K_ss, h_v, rho_cp,
        T_in=300.0, T_other=400.0, h_v2=h_v * 0.5)
    t1 = time.time()
    print(f"  Temperature: time={t1-t0:.2f}s")

    ex = s3.get_exit_profile()
    print(f"  Exit v: mean={ex['v_exit'].mean():.3f}")
    if 'Tf_exit' in ex:
        print(f"  Exit Tf: mean={ex['Tf_exit'].mean():.2f}K "
              f"(entered at 300K, other=400K)")
    print("=" * 60)


def _warmup_jit():
    """Pre-compile _assemble_pp_data_jit on import.

    Builds a tiny 4x4 sparsity pattern and runs one assembly to touch the
    compiled path. Failures are silently caught — warmup is best-effort.
    """
    try:
        import numpy as _np
        _Nx, _Ny = 4, 4
        _u = _np.zeros((_Nx + 1, _Ny), dtype=_np.float64)
        _v = _np.zeros((_Nx, _Ny + 1), dtype=_np.float64)
        _d_u = _np.full((_Nx + 1, _Ny), 0.05, dtype=_np.float64)
        _d_v = _np.full((_Nx, _Ny + 1), 0.05, dtype=_np.float64)
        _rho = _np.full((_Nx, _Ny), 1.0, dtype=_np.float64)
        _outlet = _np.zeros(_Nx, dtype=_np.float64)
        _outlet[_Nx // 2] = 1.0
        _dx = _np.full(_Nx, 0.01, dtype=_np.float64)
        _dy = _np.full(_Ny, 0.01, dtype=_np.float64)
        _pat = _build_pp_sparsity_pattern(_Nx, _Ny, _outlet)
        _data = _np.zeros(_pat['nnz'], dtype=_np.float64)
        _rhs = _np.zeros(_Nx * _Ny, dtype=_np.float64)
        _assemble_pp_data_jit(_data, _rhs, _u, _v, _d_u, _d_v, _outlet,
                              _Nx, _Ny, _dx, _dy, _rho,
                              _pat['cell_base'], _pat['cell_kind'])
    except Exception:
        pass  # warmup is best-effort; never block import


_warmup_jit()
