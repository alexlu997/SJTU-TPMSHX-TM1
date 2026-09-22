"""
simple_solver.py — 2D SIMPLE solver for porous-media transition zone

Solves steady-state Navier-Stokes + Brinkman porous resistance,
The coupled LTNE/enthalpy drivers own the temperature equations.
Production default is COMPRESSIBLE ideal-gas rho=rho(P,T) with a mass-flux
inlet (`massflux_inlet=True`) — repo hard invariants.

All inner loops are Numba-compiled for speed (~50-100x vs pure Python).

Physics (velocity; header re-verified against kernels 2026-07-06 — the old
friction-factor resistance form and its kernel no longer exist, D-F is the
only closure):
  div(eps rho U) = 0                              (mass continuity)
  rho(u du/dx + v du/dy) = -dP/dx + mu_eff nabla^2 u - Rx  (x-momentum)
  rho(u dv/dx + v dv/dy) = -dP/dy + mu_eff nabla^2 v - Ry  (y-momentum)
  Rx = (mu/K + rho c_F |U|) u,  Ry = (mu/K + rho c_F |U|) v
  (Darcy-Forchheimer ConstDF-v1, interstitial form; _porous_src_df)

Staggered grid:  P[i,j] cell centre (Nx,Ny)
                 u[i,j] x-face (Nx+1,Ny)    v[i,j] y-face (Nx,Ny+1)

Velocity convention (IMPORTANT — differs from textbook Brinkman-Forchheimer):
  u, v are *interstitial* (pore-average) velocities, not superficial. Inlet BC
  `v_inlet = m_dot / (rho * A_void)` where A_void = eps_f * A_total; training
  data (df_surrogate/) uses the same convention. Consequently K and c_F from the D-F
  surrogate are *effective interstitial* coefficients that already absorb the
  eps_f factor — they are not the canonical Darcy/Forchheimer values one would
  cite from a textbook. This is algebraically equivalent to the superficial
  form when eps_f is spatially uniform (e.g. Shanghai). Spatially varying
  porosity uses the epsilon-face/CV factors in _kernels_simple_2d; prepared
  per-cell drag and porosity fields carry the current zoned-TPMS geometry.
"""

import os

import numpy as np
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF
from sjtu_tpmshx.domain.run_environment import require_f2_mode
from ._solve_common import (F2Monitor, f2_state_is_finite,
                            f2_nonfinite_exit, momentum_component_residuals,
                            global_mass_residual)
from sjtu_tpmshx.models.tpms_calc import P_atm
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
                 P_ref=0.0, *,
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
                 uniform_inlet=False):
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

        # Scalar reference geometry; prepared fields carry spatial variation.
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

        # Prepared row coefficients take precedence over the uniform closure.

        if K_arr is not None:
            self._K_arr = np.array(K_arr, dtype=np.float64, copy=True)
            self._cF_arr = np.array(cF_arr, dtype=np.float64, copy=True)
        else:
            # Uniform: single (K, c_F), broadcast
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

        self._pp_sparsity = None  # lazily built on first solve() call
        self.uniform_inlet = uniform_inlet
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
        inf_raw, self.inlet_frac = _port_fractions_1d(
            self.dx_arr, inlet_lo, inlet_hi, uniform=self.uniform_inlet)
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

    def solve(self, max_iter=3000,
              alpha_u=0.7, alpha_p=0.3,
              n_inner=2,
              verbose=True, progress_cb=None, cancel_check=None):
        """
        Run SIMPLE iterations. PP equation solved by sparse direct solver.

        Returns (converged: bool, iterations: int).
        """
        Nx, Ny = self.Nx, self.Ny
        dx_a, dy_a = self.dx_arr, self.dy_arr

        self.convergence_mode = require_f2_mode(getattr(
            self, 'convergence_mode', os.environ.get('TPMSHX_CONV_MODE', 'f2')))
        _f2 = F2Monitor(self, (self.u, self.v), min_iter=20)
        self.final_res_mom = None
        self.final_res_mass_local = None
        self.final_res_mass_global = None
        self.outlet_backflow_frac = 0.0
        # Returned-field certificate after the local outlet closure.
        self.f2_cert_post_rescale_ok = None
        # A2: exit bookkeeping — 'tol' | 'stall' | 'max_iter' | 'nonfinite';
        # reset on every (re-)entry (the 2D pipeline rebuilds the solver per
        # outer iteration, but direct callers may reuse one instance).
        self.exit_reason = None
        self.final_res = None
        if not f2_state_is_finite(self, (self.u, self.v)):
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
            if (self.fluid_type == 'ideal_gas'
                    and not f2_state_is_finite(self, (self.u, self.v))):
                return f2_nonfinite_exit(self, it)
            self._update_density()  # compressible: update rho from P
            if not f2_state_is_finite(self, (self.u, self.v)):
                return f2_nonfinite_exit(self, it)

            res = _mass_res_jit(self.v, Nx, Ny, dx_a, rho_eps_field)
            self.residuals.append(res)

            # Live progress hook for UI sparklines — throttled to every
            # 20 iters so a compute with 5000 iters pushes 250 samples max.
            if progress_cb is not None and (it % 20 == 0 or it == 1):
                progress_cb(it, float(res))

            if verbose and it % 200 == 0:
                _log.info(f"  iter {it:5d}  |R| = {res:.3e}")

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
                    self._enforce_mass_conservation()
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
        if verbose:
            _log.warning(f"  [!!] NOT converged after {max_iter} iters, |R| = {res:.3e}")

        # Post-solve: enforce mass conservation at partial outlet
        self._enforce_mass_conservation()
        if not f2_state_is_finite(self, (self.u, self.v)):
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

    def _enforce_mass_conservation(self):
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
