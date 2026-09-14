"""
simple_solver_3d.py — 3D SIMPLE solver for porous-media Brinkman-Forchheimer flow.

Extends the 2D `simple_solver.py` architecture to a full 3D staggered MAC grid
with PyAMG-based pressure-Poisson solution. Designed for the SJTU-TPMSHX 3D
extension (plan archived: vault/reports/_archive/3d-solver/
2026-04-19-3D-extension-plan-CN.md).

Key design choices (header re-verified against code 2026-07-06; the original
Phase-1 "MVP" caveats are superseded):
  * Full 3D momentum: u, v, w staggered face velocities.
  * First-order upwind for momentum convective fluxes by default; a
    deferred-correction SOU exists and is opt-in via `use_sou_momentum`
    (default False — benefit never quantified, see research ledger idea pool).
  * PyAMG smoothed-aggregation for the pressure-Poisson solve; hierarchy
    rebuilt every `pyamg_rebuild_every` SIMPLE iterations (default 100) to
    track variable Brinkman coefficient drift.
  * Non-uniform cell spacings accepted since E1 (2026-06-09); the default
    path remains uniform dx/dy/dz (wall_refine=False).
  * Partial inlet/outlet supported via `inlet_frac` / `outlet_frac`
    (Nx, Nz) face fractions, with optional 8-cell corner taper
    (`apply_outlet_taper`); offset-outlet asym configs rely on this.
  * D-F closure: K, c_F supplied as (Ny, Nz) arrays; uniform-geometry case
    broadcasts a single (K, c_F) pair.

Physics (velocity, interstitial convention — matches 2D). Production default
is COMPRESSIBLE ideal-gas ρ=ρ(P,T) with a mass-flux inlet and the choke
envelope guard (solvers/envelope.py); the discrete pressure-correction
continuity operator carries ε·ρ (rho_eps_field), so per-side and spatially
varying ε enter mass conservation.

ε IN THE MOMENTUM OPERATOR — corrected 2026-07-12. This docstring used to say
"the momentum operator carries no ε weighting and no ∇ε source". THAT IS STALE:
M2b (2026-07-09, ledger B5) added the ε-divided VANS form to all three 3D
momentum cell bodies. Every flux face carries the ratio r_f = ε_f/ε_CV on BOTH
the convective (F) and diffusive (D) coefficients, so a spatially varying ε does
enter momentum. It is guarded: `_use_eps` is 1 only when `eps_field` is genuinely
non-uniform (`solve()`, ~line 888), so the uniform-ε path keeps the pre-M2b
expression tree bit-for-bit (these kernels are fastmath; an inline ×1.0 could be
re-associated and break golden bit-identity). The pressure term is unfactored and
the D-F drag is untouched — the ratio form captures ∇ε without an explicit source
term and without double-counting the calibrated drag.

    ∂(ερu)/∂x + ∂(ερv)/∂y + ∂(ερw)/∂z = 0                       (continuity)
    ρ(u·∇)u = -∂P/∂x + μ_eff ∇²u − R·u                          (x-momentum)
    ρ(u·∇)v = -∂P/∂y + μ_eff ∇²v − R·v                          (y-momentum)
    ρ(u·∇)w = -∂P/∂z + μ_eff ∇²w − R·w                          (z-momentum)
  with R = μ/K + ρ·c_F·|U| (D-F closure, ConstDF-v1 interstitial form).

BOUNDARY CONDITIONS (be precise — the two ends are NOT symmetric):
  * INLET (j=0): MASS-FLUX. ρ·v is held at the physical throughput and
    `v_inlet_field` is recomputed from the current inlet ρ every density update
    (`_apply_massflux_inlet`). HARD INVARIANT — see docs/architecture.md.
  * OUTLET (j=Ny-1): DIRICHLET PRESSURE. Every open outlet cell is pinned
    `Pp = 0` and its P is never corrected (`_correct_jit_3d`), so its GAUGE
    pressure stays 0 for the whole solve ⇒ **the outlet ABSOLUTE pressure is
    exactly `self.P_ref_abs`**. `self.P` is a GAUGE field (init 0 everywhere,
    line ~600); absolute pressure is always `P + P_ref_abs`.
  ⇒ the solver solves "given the mass flow and the outlet pressure, what is Δp?"
    Δp is an OUTPUT. Specifying BOTH end pressures and solving for the mass flow
    is a DIFFERENT problem (pressure-driven flow) and needs a different inlet BC.

Staggered grid:
    P : cell-centre (Nx, Ny, Nz)
    u : x-face (Nx+1, Ny, Nz)
    v : y-face (Nx, Ny+1, Nz)
    w : z-face (Nx, Ny, Nz+1)

Coordinate convention differs from 2D validate_shanghai axis-swap:
    physical x → solver i-axis (usually streamwise for Fluid A)
    physical y → solver j-axis (usually streamwise for Fluid B)
    physical z → solver k-axis (TPMS channel stacking direction)

Callers should set up fluid-specific orientations via explicit transposes
outside this class; the solver itself is coordinate-agnostic.
"""
from __future__ import annotations

import os
from time import perf_counter as _perf_counter
import numpy as np
from sjtu_tpmshx.domain.cancellation import CancelledError
from scipy import sparse

try:
    import pyamg
    _HAS_PYAMG = True
except ImportError:
    _HAS_PYAMG = False

from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)


# ─── Adaptive parallel-dispatch threshold ─────────────────────────
# Below this cell count the serial natural-ordering Gauss-Seidel sweep is
# faster (Numba thread-launch overhead ~50 µs per prange > per-sweep work).
# Above it, red-black GS with `prange` wins by roughly #cores / 2.
#
# Break-even at ~150-200k cells on an 8-core desktop, empirically measured.
# Override via env `TPMSHX_PARALLEL_THRESHOLD`.
_PARALLEL_CELL_THRESHOLD = int(
    os.environ.get('TPMSHX_PARALLEL_THRESHOLD', '200000'))


def _should_parallelize(Nx: int, Ny: int, Nz: int) -> bool:
    """Return True when grid is big enough that red-black prange beats
    serial natural-ordering GS."""
    return (Nx * Ny * Nz) >= _PARALLEL_CELL_THRESHOLD


# ─── AMG-active gate (pressure-correction inner solver) ───────────
# Below this N the pressure-correction system uses scipy.sparse.linalg.spsolve
# (sparse LU); above it, PyAMG ruge_stuben_solver as a preconditioner for
# BiCGStab. The old "break-even ~30 k" was never measured on the mid band:
# D4(b)-1 profiling (2026-07-22) measured per-call
# pp cost LU vs AMG on identical assembled systems — AMG wins at EVERY size
# ≥ 2 k cells (2.0k: 13→3 ms, 4.9k: 79→5 ms, 11.6k: 459→20 ms, 19.7k:
# 1505→169 ms, 29.8k: 4896→219 ms; spsolve refactorizes every call, the
# hierarchy cache amortises). Gate lowered 30_000 → 2_000 accordingly
# (golden-3D re-baselined same commit — 15³ grids now take the AMG path;
# Shanghai validation cases at 600 cells stay on LU, headline unchanged).
# This constant is also used to auto-enable `coarse_bootstrap_3d` warm-start
# (audit P4 / phase L-d Option B).
_AMG_GATE = 2_000

from sjtu_tpmshx.models.tpms_calc import P_atm
from .threads import warn_if_default_pool as _warn_if_default_pool
from ._solve_common import (LowReExit, F2Monitor, f2_state_is_finite,
                            f2_nonfinite_exit, momentum_component_residuals,
                            global_mass_residual)


# ===================================================================
#  Numba kernels — moved verbatim to _kernels_simple_3d.py
#  (openspec split-solver-kernels, 2026-07-03). Re-exported here so
#  existing `from solvers.simple_solver_3d import <kernel>` imports
#  keep working.
# ===================================================================
from ._kernels_simple_3d import (  # noqa: F401
    _umag_u_3d,
    _umag_v_3d,
    _umag_w_3d,
    _porous_src_df_3d,
    _sou_axis,
    _u_coeffs_df_3d,
    _u_cell_df_3d,
    _sweep_u_jit_df_3d,
    _sweep_u_jit_df_3d_parallel,
    _v_coeffs_df_3d,
    _v_cell_df_3d,
    _v_bc_3d,
    _sweep_v_jit_df_3d,
    _sweep_v_jit_df_3d_parallel,
    _w_coeffs_df_3d,
    _w_cell_df_3d,
    _sweep_w_jit_df_3d,
    _sweep_w_jit_df_3d_parallel,
    _assemble_pp_3d,
    _correct_jit_3d,
    _mass_res_jit_3d,
    _mass_res_solved_jit_3d,
    _mass_global_jit_3d,
    _mom_res_jit_3d,
)


def _build_pp_sparsity_3d(Nx, Ny, Nz, outlet_mask_ij):
    """Pre-compute CSR indptr/indices/cell_base/cell_kind for 7-point stencil.

    outlet_mask_ij : (Nx, Ny) bool — True where the j=Ny-1 cells of that
        (i, k) column are treated as outlet reference. Actually we use the
        j-direction outlet (Fluid A) by default; Phase 1 pins k=Nz-1 too if
        provided. For MVP we use j=Ny-1 only.

    WHAT THE PIN ACTUALLY IS (be precise — ledger C6, corrected 2026-07-12).
    `cell_kind = 1` marks EVERY open outlet cell, and `_assemble_pp_3d` then
    REPLACES that cell's continuity equation with `Pp = 0`. That is a DIRICHLET
    PRESSURE-OUTLET boundary condition on the whole outlet face — not merely a
    single-point gauge fixing the pressure datum of a singular system. The two
    are different things and this docstring (and C6's first draft) blurred them.
    Consequences:
      * the outlet row's continuity is excluded from the PPE; `_v_bc_3d`
        closes its six-face mass balance by setting the outlet velocity;
      * a uniform outlet pressure is defensible physics for a plenum exit, but
        it is a MODELLING CHOICE, not a numerical necessity. Revisiting it
        (ledger F3: impose Pp=0 on the outlet FACE and keep the last CV's
        continuity equation) is a boundary-condition change needing its own V&V
        — NOT a convergence patch, and NOT to be bundled with F2.
    """
    N = Nx * Ny * Nz

    def idx(i, j, k):
        return (i * Ny + j) * Nz + k

    indptr = np.zeros(N + 1, dtype=np.int32)
    cell_base = np.zeros(N, dtype=np.int32)
    cell_kind = np.zeros(N, dtype=np.int8)
    indices_list = []
    pos = 0

    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                flat = idx(i, j, k)
                cell_base[flat] = pos

                # Outlet pin: j=Ny-1 row with outlet_mask_ij
                if j == Ny - 1 and outlet_mask_ij[i, k]:
                    cell_kind[flat] = 1
                    indices_list.append(flat)
                    pos += 1
                    indptr[flat + 1] = pos
                    continue

                # 7 slots: [diag, E, W, N, S, T, B]
                indices_list.append(flat)                           # diag
                indices_list.append(idx(i + 1, j, k) if i < Nx - 1 else flat)  # E
                indices_list.append(idx(i - 1, j, k) if i > 0 else flat)        # W
                indices_list.append(idx(i, j + 1, k) if j < Ny - 1 else flat)   # N
                indices_list.append(idx(i, j - 1, k) if j > 0 else flat)        # S
                indices_list.append(idx(i, j, k + 1) if k < Nz - 1 else flat)   # T
                indices_list.append(idx(i, j, k - 1) if k > 0 else flat)        # B
                pos += 7
                indptr[flat + 1] = pos

    indices = np.asarray(indices_list, dtype=np.int32)
    return {'indptr': indptr, 'indices': indices,
            'cell_base': cell_base, 'cell_kind': cell_kind,
            'nnz': pos}


def _solve_pp_amg(Pp, u, v, w, d_u, d_v, d_w,
                   Nx, Ny, Nz, dx, dy, dz, rho_field, sparsity,
                   ml_cache, rebuild, rtol_dyn=1e-5, drift_thresh=0.05):
    """Assemble pressure correction; use cached AMG above ``_AMG_GATE``.

    ml_cache : dict holding the reusable multilevel hierarchy. Rebuilt when
        `rebuild` is True or when no cached entry exists.
    rtol_dyn : adaptive BiCGStab relative tolerance (Phase A acceleration).
        Caller passes ~0.05 * outer_simple_residual so inner solve does not
        over-solve while outer is still loose. Default 1e-5 reproduces legacy
        fixed-tol behaviour.
    drift_thresh : relative L2 change of the unpinned diagonal that forces
        a rebuild on a non-cadence iter. 0 disables.
    """
    N = Nx * Ny * Nz
    nnz = sparsity['nnz']
    data = np.zeros(nnz, dtype=np.float64)
    rhs = np.zeros(N, dtype=np.float64)

    _assemble_pp_3d(data, rhs, u, v, w, d_u, d_v, d_w,
                     Nx, Ny, Nz, dx, dy, dz, rho_field,
                     sparsity['cell_base'], sparsity['cell_kind'])

    A = sparse.csr_matrix((data,
                            sparsity['indices'].copy(),
                            sparsity['indptr'].copy()),
                           shape=(N, N))

    N = A.shape[0]
    if _HAS_PYAMG and N > _AMG_GATE:
        # Large grids: AMG-preconditioned BiCGStab on the pressure-correction
        # system.
        #
        # Canonicalize FIRST. pyamg's Ruge-Stuben coarsening and the Krylov
        # matvec require a sorted, duplicate-summed CSR; the assembled pattern
        # is neither. A non-canonical matrix silently builds a poor AMG
        # hierarchy → BiCGStab diverges, exhausts maxiter and falls back to a
        # ~16 s direct LU on every fresh solver. That was the TRUE cause of the
        # old "cold-start" symptom — NOT the zero-velocity diagonal
        # heterogeneity the previous comment blamed (measured 2026-06-24:
        # on a canonicalized matrix AMG-BiCGStab/CG converge to 1e-9 in ~0.3 s,
        # 58× the SuperLU per-solve, on the SAME first-iteration matrix). With
        # canonicalization BiCGStab converges from the first iter, so the
        # cold-start direct bypass is removed entirely.
        A.sort_indices()
        A.sum_duplicates()

        # Outlet rows are unit pressure pins, not momentum coefficients.
        # Including them can hide a ~99% change in the active diagonal as
        # <0.2% global-norm drift. Compare the active vectors themselves:
        # equal scalar norms can also hide a spatial redistribution.
        if drift_thresh > 0.0 and not rebuild and 'ml' in ml_cache:
            diagonal = A.diagonal()[sparsity['cell_kind'] == 0]
            diag_norm = float(np.linalg.norm(diagonal))
            last = ml_cache.get('diag_norm', None)
            if last is not None and last > 0.0:
                drift = float(np.linalg.norm(diagonal - ml_cache['diagonal'])) / last
                if drift > drift_thresh:
                    rebuild = True
                    ml_cache['drift_rebuild_count'] = (
                        ml_cache.get('drift_rebuild_count', 0) + 1)
                    ml_cache['last_drift'] = drift
                else:
                    ml_cache['skip_count'] = (
                        ml_cache.get('skip_count', 0) + 1)
                    ml_cache['last_drift'] = drift
            ml_cache['diag_norm_now'] = diag_norm

        if rebuild or 'ml' not in ml_cache:
            t0 = _perf_counter()
            ml = pyamg.ruge_stuben_solver(A, max_coarse=200)
            ml_cache['ml'] = ml
            ml_cache['diagonal'] = A.diagonal()[sparsity['cell_kind'] == 0]
            ml_cache['diag_norm'] = float(np.linalg.norm(ml_cache['diagonal']))
            ml_cache['rebuild_count'] = (
                ml_cache.get('rebuild_count', 0) + 1)
            ml_cache['rebuild_time'] = (
                ml_cache.get('rebuild_time', 0.0)
                + (_perf_counter() - t0))
        from scipy.sparse.linalg import bicgstab as _bcg
        M = ml_cache['ml'].aspreconditioner(cycle='V')
        # Phase A: adaptive rtol — caller schedules `rtol_dyn` ≈ 0.05 *
        # outer_residual, clipped to [1e-7, 1e-3]. Early outer iters with
        # res~1e-2 → inner rtol~5e-4 (~10× fewer V-cycles); late iters with
        # res~1e-6 → inner rtol~5e-7 (matches legacy precision).
        t0 = _perf_counter()
        Pp_flat, info = _bcg(A, rhs, M=M, rtol=rtol_dyn, maxiter=200)
        ml_cache['bcg_time'] = (
            ml_cache.get('bcg_time', 0.0) + (_perf_counter() - t0))
        ml_cache['bcg_calls'] = ml_cache.get('bcg_calls', 0) + 1
        if info != 0:
            # AMG-preconditioned BiCGStab failed; fall back to direct.
            # Keep cached hierarchy — popping forces next-iter rebuild that
            # is unlikely to fix the failure (A drift bounded within outer
            # SIMPLE step) and would double the cost. Track failure count
            # so callers can adjust `rtol_dyn` / `maxiter` if persistent.
            ml_cache['bcg_fail_count'] = (
                ml_cache.get('bcg_fail_count', 0) + 1)
            from scipy.sparse.linalg import spsolve
            Pp_flat = spsolve(A, rhs)
    else:
        # At or below _AMG_GATE, use direct sparse LU.
        from scipy.sparse.linalg import spsolve
        Pp_flat = spsolve(A, rhs)

    Pp[:, :, :] = Pp_flat.reshape(Nx, Ny, Nz)
    return A, rhs


# ===================================================================
#  SIMPLESolver3D class — thin wrapper orchestrating the kernels above
# ===================================================================


def _build_outlet_frac_taper(Nx, Nz, n_taper=8, min_frac=0.2):
    """Build (Nx, Nz) numerical outlet taper g near x/z walls.

    Mirror 2D `_taper(outlet_frac, ...)` which uses `1 - 0.8 * exp(-1.0 * d)`
    where d is the distance-from-wall in cells (1, 2, ..., n_taper).

    Returns full-width 1.0 interior, tapered down toward min_frac at corners.
    """
    arr = np.ones((Nx, Nz), dtype=np.float64)
    for i in range(min(n_taper, Nx // 2)):
        d = i + 1
        taper = 1.0 - 0.8 * np.exp(-1.0 * d)
        if taper < min_frac:
            taper = min_frac
        arr[i, :] = np.minimum(arr[i, :], taper)
        arr[Nx - 1 - i, :] = np.minimum(arr[Nx - 1 - i, :], taper)
    for k in range(min(n_taper, Nz // 2)):
        d = k + 1
        taper = 1.0 - 0.8 * np.exp(-1.0 * d)
        if taper < min_frac:
            taper = min_frac
        arr[:, k] = np.minimum(arr[:, k], taper)
        arr[:, Nz - 1 - k] = np.minimum(arr[:, Nz - 1 - k], taper)
    return arr


class SIMPLESolver3D:
    """3D staggered MAC SIMPLE solver for porous-media Brinkman-Forchheimer.

    PyAMG Poisson + first-order momentum upwind by default (SOU opt-in via
    `use_sou_momentum`); non-uniform spacings accepted since E1 (2026-06-09),
    uniform grid remains the default path. Compressible ideal-gas ρ=ρ(P,T)
    with mass-flux inlet is the production default.
    Callers supply Darcy-Forchheimer (K, c_F) as (Ny, Nz) arrays and the
    solver never queries the surrogate directly — matches the 2D pattern.

    Parameters
    ----------
    Lx, Ly, Lz : float
        Physical domain extents [m] along (x, y, z).
    Nx, Ny, Nz : int
        Cell counts along each axis.
    rho, mu : float
        Reference density [kg/m³] and dynamic viscosity [Pa·s].
    T_in : float
        Inlet temperature [K] (used for P_ref_abs default).
    v_inlet : float
        Inlet face-normal velocity magnitude (y-face, j=0).
    eps : float
        Uniform porosity (ε). Used to build μ_eff = μ/ε.
    K_arr, cF_arr : (Ny, Nz) arrays, optional
        Per-row D-F coefficients. If None, the caller must set them via
        `self.K_arr = ...` before calling solve().
    P_ref_abs : float, optional
        Outlet absolute pressure anchor [Pa]. Default: atmospheric.

    See also
    --------
    SIMPLESolver in `simple_solver.py` — the 2D companion this mirrors.
    """

    def apply_outlet_taper(self, n_taper=8, min_frac=0.2):
        """Enable numerical corner damping c=f*g without changing open area.

        Mirror 2D pattern: reduces wall-adjacent cell weights to avoid corner
        pressure artifacts. Use for Shanghai-type full-width validation runs.
        """
        self._outlet_taper = _build_outlet_frac_taper(
            self.Nx, self.Nz, n_taper=n_taper, min_frac=min_frac)
        self.outlet_coeff = self.outlet_frac * self._outlet_taper

    def set_ports(self, inlet_rect, outlet_rect):
        """Set physical (xlo, xhi, zlo, zhi) rectangles on this actual grid.

        Array velocities remain the caller's prescribed face averages. Scalar
        inlets can move only before their mass-flux reference is captured.
        Primary fractions cannot determine the staggered overlap at an edge.
        """
        from .simple_solver import _port_overlap_1d
        inlet_changed = tuple(inlet_rect) != getattr(self, 'inlet_rect', None)
        if (inlet_changed and self._scalar_inlet
                and hasattr(self, '_massflux_target')):
            raise ValueError('Cannot change scalar inlet after mass-flux capture; '
                             'create a new solver with a new inlet reference state.')
        self.inlet_rect, self.outlet_rect = tuple(inlet_rect), tuple(outlet_rect)
        xi, zi = (_port_overlap_1d(d, *bounds) for d, bounds in
                  ((self.dx, inlet_rect[:2]), (self.dz, inlet_rect[2:])))
        xo, zo = (_port_overlap_1d(d, *bounds) for d, bounds in
                  ((self.dx, outlet_rect[:2]), (self.dz, outlet_rect[2:])))
        if not (xi.any() and zi.any() and xo.any() and zo.any()):
            raise ValueError('Inlet / outlet range resolves to zero cells.')
        self.inlet_frac = np.outer(xi, zi)
        if inlet_changed and self._scalar_inlet:
            self.v_inlet_field = self.v_inlet * self.inlet_frac
            self.v[:, 0, :] = self.v_inlet_field
        self._outlet_frac = np.outer(xo, zo)
        self.outlet_u_frac = np.outer(
            _port_overlap_1d(self.dx, *outlet_rect[:2], staggered=True), zo)
        self.outlet_w_frac = np.outer(
            xo, _port_overlap_1d(self.dz, *outlet_rect[2:], staggered=True))
        self.outlet_coeff = self._outlet_frac * self._outlet_taper
        self.outlet_mask_ij = self._outlet_frac > 0.0
        # Changed open cells change Dirichlet pin rows on solver reuse.
        self._pp_sparsity = None

    # Raw geometry owns BC/PPE support; taper is retained for legacy reporting.
    @property
    def outlet_frac(self):
        return self._outlet_frac

    @staticmethod
    def extract_dP_weighted(s, *, numerical_taper=False):
        """Pipe-weighted inlet-outlet dP — geometric open-area weights.

        Uses `s.inlet_frac` / `s.outlet_frac` only (per-cell open-area
        fractions). Fine when density and velocity are nearly uniform across
        the inlet face; under-represents high-speed regions on non-uniform
        profiles. For physically-rigorous reduction use
        `extract_dP_mass_flux_weighted`.

        ``numerical_taper=True`` retains the historical corner-weighted
        report functional; it is not a geometric open-area average.
        """
        area = s.dx[:, None] * s.dz[None, :]
        wI = s.inlet_frac * area
        wO = (s.outlet_coeff if numerical_taper else s.outlet_frac) * area
        mI = wI > 0.0; mO = wO > 0.0
        if not (mI.any() and mO.any()):
            return 0.0
        return float(np.average(s.P[:, 0, :][mI], weights=wI[mI])
                     - np.average(s.P[:, -1, :][mO], weights=wO[mO]))

    @staticmethod
    def extract_dP_face_extrap(s, *, numerical_taper=False):
        """2nd-order inlet/outlet dP — pressure extrapolated to the FACES.

        ``extract_dP_weighted`` differences the first/last **cell-centre**
        pressures (``P[:, 0, :]`` / ``P[:, -1, :]``), which sit ~h/2 inside the
        physical inlet/outlet faces. That half-cell offset is an O(h) term, so
        the boundary pressure-drop functional is only ~1st-order grid-convergent
        even though the field itself is 2nd-order (and on uniform refinement the
        cell-centre dP is erratic / non-monotone).

        Extrapolating P to the faces with a one-sided 2nd-order stencil
        ``P_face = (1+r)·P₀ − r·P₁``, where ``r = dy₀/(dy₀+dy₁)``
        uses the boundary-to-centre / centre-to-centre distance ratio
        (uniform grid: ``1.5·P₀ − 0.5·P₁``). This removes that O(h) EXTRACTION term: as an
        operator on a smooth field the functional is 2nd-order (manufactured-field
        order 1.91, ``tests/test_dp_face_extrap_order.py``) and the cell-centre dP
        goes from non-monotone to monotone. NOTE the REAL-field dP convergence
        order is then capped by the 1st-order-upwind interior scheme, NOT by this
        reduction: an all-axis Shanghai refinement (16/32/64) observed p≈0.76, the
        dP RMSRE rising 5.2→8.0→9.7% toward a ~12% geometry/closure floor (both
        the cell-centre and face reducers converge to the SAME continuous-PDE dP
        as h→0 — face-extrap only accelerates it, the floor is the model error vs
        experiment). Same streamwise axis (1) and open-area weights as
        ``extract_dP_weighted``; falls back to the cell-centre value when the
        streamwise direction has < 2 cells.

        ``numerical_taper=True`` explicitly retains the historical f*g*A
        report weights, as in ``extract_dP_weighted``.
        """
        area = s.dx[:, None] * s.dz[None, :]
        wI = s.inlet_frac * area
        wO = (s.outlet_coeff if numerical_taper else s.outlet_frac) * area
        mI = wI > 0.0; mO = wO > 0.0
        if not (mI.any() and mO.any()):
            return 0.0
        if s.P.shape[1] < 2:          # need 2 cells to extrapolate
            return SIMPLESolver3D.extract_dP_weighted(s, numerical_taper=numerical_taper)
        r_in = s.dy[0] / (s.dy[0] + s.dy[1])
        r_out = s.dy[-1] / (s.dy[-2] + s.dy[-1])
        P_in_face = (1.0 + r_in) * s.P[:, 0, :] - r_in * s.P[:, 1, :]
        P_out_face = (1.0 + r_out) * s.P[:, -1, :] - r_out * s.P[:, -2, :]
        return float(np.average(P_in_face[mI], weights=wI[mI])
                     - np.average(P_out_face[mO], weights=wO[mO]))

    @staticmethod
    def extract_dP_mass_flux_weighted(s):
        """Pipe-weighted inlet-outlet dP using ρ·|v| mass-flux weights.

        Matches the physical inlet/outlet energy reduction more closely than
        geometric open-area weights when the velocity profile is skewed (e.g.
        partial-width inlets or stratified flow). Uses y-face streamwise
        velocity v at the first and last y-layers, density from rho_field.
        """
        v_inlet_face = s.v[:, 0, :]
        v_outlet_face = s.v[:, -1, :]
        rho_in = s.rho_field[:, 0, :]
        rho_out = s.rho_field[:, -1, :]
        area = s.dx[:, None] * s.dz[None, :]
        wI = rho_in * np.abs(v_inlet_face) * area
        wO = rho_out * np.abs(v_outlet_face) * area
        mI = wI > 0.0; mO = wO > 0.0
        if not (mI.any() and mO.any()):
            return SIMPLESolver3D.extract_dP_weighted(s)
        return float(np.average(s.P[:, 0, :][mI], weights=wI[mI])
                     - np.average(s.P[:, -1, :][mO], weights=wO[mO]))

    def __init__(self, Lx, Ly, Lz, Nx, Ny, Nz,
                 rho, mu, T_in, v_inlet,
                 eps=1.0,
                 K_arr=None, cF_arr=None,
                 P_ref_abs=None,
                 alpha_u=0.5, alpha_p=0.2,
                 pyamg_rebuild_every=100,
                 pyamg_rebuild_drift_thresh=0.05,
                 use_coarse_bootstrap=None,
                 fluid_type='ideal_gas',
                 R_gas=287.05,
                 alpha_rho=0.3,
                 dx_arr=None, dy_arr=None, dz_arr=None,
                 inlet_rect=None, outlet_rect=None):
        self.Lx, self.Ly, self.Lz = Lx, Ly, Lz
        self.Nx, self.Ny, self.Nz = Nx, Ny, Nz
        # E1 (2026-06-09): accept non-uniform cell spacings (wall_refine).
        # N4 correction (2026-07-07): the E1-era claim that the momentum
        # kernels were "already non-uniform-aware" was wrong for DIFFUSION —
        # the viscous conductances used the CV width instead of the actual
        # neighbour-node distance (up to ~30% face-conductance error on
        # growth-1.8 refined grids, non-telescoping across shared faces).
        # Fixed in _kernels_simple_3d cell bodies (and the 2D kernels);
        # uniform grids are bit-identical. Default None → uniform.
        self.dx = (np.full(Nx, Lx / Nx, dtype=np.float64) if dx_arr is None
                   else np.ascontiguousarray(dx_arr, dtype=np.float64))
        self.dy = (np.full(Ny, Ly / Ny, dtype=np.float64) if dy_arr is None
                   else np.ascontiguousarray(dy_arr, dtype=np.float64))
        self.dz = (np.full(Nz, Lz / Nz, dtype=np.float64) if dz_arr is None
                   else np.ascontiguousarray(dz_arr, dtype=np.float64))
        if (self.dx.shape != (Nx,) or self.dy.shape != (Ny,)
                or self.dz.shape != (Nz,)):
            raise ValueError(
                f"SIMPLESolver3D non-uniform spacing shape mismatch: "
                f"dx{self.dx.shape}/dy{self.dy.shape}/dz{self.dz.shape} "
                f"vs grid ({Nx},{Ny},{Nz})")

        self.rho = float(rho)
        self.mu = float(mu)
        self.eps = float(eps)
        self.T_in = float(T_in)
        # Scalar: uniform speed on the physical opening (owned by set_ports).
        # Array: prescribed face-average velocity, already including open area.
        self._scalar_inlet = np.ndim(v_inlet) == 0
        if self._scalar_inlet:
            self.v_inlet = float(v_inlet)
            self.v_inlet_field = np.full((Nx, Nz), float(v_inlet), dtype=np.float64)
        else:
            arr = np.ascontiguousarray(np.asarray(v_inlet, dtype=np.float64))
            if arr.shape != (Nx, Nz):
                raise ValueError(
                    f"v_inlet array shape {arr.shape} != (Nx={Nx}, Nz={Nz})")
            self.v_inlet_field = arr
            self.v_inlet = float(arr.mean())   # legacy scalar = mean for back-compat

        self.alpha_u = float(alpha_u)
        self.alpha_p = float(alpha_p)
        self.pyamg_rebuild_every = int(pyamg_rebuild_every)
        # On non-cadence iters, reuse the hierarchy unless the unpinned
        # diagonal's relative L2 change exceeds this threshold. 0
        # disables drift checks (legacy fixed-cadence-only behaviour).
        self.pyamg_rebuild_drift_thresh = float(pyamg_rebuild_drift_thresh)

        # Audit P4 / phase L-d Option B (2026-05-28): coarse-grid warm start.
        # None = auto-enable when N > _AMG_GATE (the same gate that turns on
        # AMG-BiCGStab); True/False = explicit override. Auto-mode removes the
        # cold-start cost on the only workloads where it hurts (AMG-active
        # grids), without touching small-grid solves that already run in
        # ~1 spsolve call.
        self.use_coarse_bootstrap = use_coarse_bootstrap

        # Compressibility knobs (mirror 2D SIMPLESolver)
        self.fluid_type = str(fluid_type)
        self.R_gas = float(R_gas)
        self.alpha_rho = float(alpha_rho)

        if P_ref_abs is None:
            self.P_ref_abs = float(P_atm)
        else:
            self.P_ref_abs = float(P_ref_abs)

        # Scalar broadcasts for rho, mu → 3D fields
        self.rho_field = np.full((Nx, Ny, Nz), self.rho, dtype=np.float64)
        self.mu_field = np.full((Nx, Ny, Nz), self.mu, dtype=np.float64)
        # mu_eff = mu/ε. Per-cell ε supports zoned via eps_field (set below).
        self._mu_eff_field = np.full((Nx, Ny, Nz),
                                       self.mu / self.eps,
                                       dtype=np.float64)
        # eps_field initialised after to allow re-init with zoned values
        # Per-cell porosity (default uniform; caller sets eps_field for zoned).
        # Used in mass conservation kernels: ∇·(ε·ρ·u) = 0 (correct macroscopic
        # form for porous media). Without ε factor, zoned-eps cases miss the
        # ∇ε term and accumulate ~5-20% per-cell mass divergence.
        self.eps_field = np.full((Nx, Ny, Nz), self.eps, dtype=np.float64)
        # T field for ideal-gas rho update (uniform T_in by default)
        self.T_field = np.full((Nx, Ny, Nz), self.T_in, dtype=np.float64)
        # v_inlet_field is a fixed-velocity BC; density updates do not modify it.

        # D-F coefficients
        if K_arr is None:
            # caller should set after __init__; give dummy to keep kernels happy
            self.K_arr = np.full((Ny, Nz), 1e-7, dtype=np.float64)
            self.cF_arr = np.zeros((Ny, Nz), dtype=np.float64)
        else:
            self.K_arr = np.ascontiguousarray(K_arr, dtype=np.float64)
            self.cF_arr = np.ascontiguousarray(cF_arr, dtype=np.float64)
            if self.K_arr.shape != (Ny, Nz):
                raise ValueError(
                    f"K_arr shape {self.K_arr.shape} != (Ny={Ny}, Nz={Nz})")

        # Fields
        self.u = np.zeros((Nx + 1, Ny, Nz), dtype=np.float64)
        self.v = np.zeros((Nx, Ny + 1, Nz), dtype=np.float64)
        self.w = np.zeros((Nx, Ny, Nz + 1), dtype=np.float64)
        self.P = np.zeros((Nx, Ny, Nz), dtype=np.float64)
        self.Pp = np.zeros((Nx, Ny, Nz), dtype=np.float64)
        self.d_u = np.zeros((Nx + 1, Ny, Nz), dtype=np.float64)
        self.d_v = np.zeros((Nx, Ny + 1, Nz), dtype=np.float64)
        self.d_w = np.zeros((Nx, Ny, Nz + 1), dtype=np.float64)

        # Geometry defaults to full-face; array inlet velocities include area.
        self._outlet_taper = np.ones((Nx, Nz), dtype=np.float64)
        full_face = (0., float(np.sum(self.dx)), 0., float(np.sum(self.dz)))
        self.set_ports(full_face if inlet_rect is None else inlet_rect,
                       full_face if outlet_rect is None else outlet_rect)

        # Inlet BC seed (may be non-uniform via v_inlet_field)
        self.v[:, 0, :] = self.v_inlet_field

        # PyAMG hierarchy cache + sparsity (lazy)
        self._pp_sparsity = None
        self._ml_cache = {}
        self.residuals = []

    def _update_density(self):
        """Compressible rho update: ρ = P_abs / (R·T), under-relaxed.

        The inlet is then re-imposed as a MASS-FLUX inlet (`_apply_massflux_inlet`
        at the tail of this method): ρ·v at the inlet is held at the physical
        throughput and `v_inlet_field` is recomputed as G_target / ρ_inlet. This
        is a HARD INVARIANT (docs/architecture.md) and the DEFAULT
        (`massflux_inlet=True`).

        (Corrected 2026-07-12. This docstring previously read "v_inlet_field
        stays fixed (velocity-inlet BC); mass flux at inlet floats with density"
        — the exact OPPOSITE of what the code does, and of the invariant. A
        velocity inlet + compressible ρ + Forchheimer is a positive feedback
        (dP↑→ρ↑→dP↑) that makes Δp drift with the grid; the mass-flux inlet is
        what makes Shanghai Δp grid-convergent (2D RMSRE 35.8%→8.4%). Do not
        "restore" the old behaviour on the strength of a stale comment.)

        No-op for incompressible fluid_type.

        Clipping policy (2026-05-06 fix #1, widened 2026-05-07 after UI
        report 2): clip P_abs to [1 kPa, 10 MPa] — physical HX envelope
        plus a generous transient margin so SIMPLE under-relaxation can
        overshoot the steady-state P during early iterations without
        engaging the clip and stalling momentum convergence at high u.
        Original [10 kPa, 1 MPa] tripped on u=20 m/s + P_in=192 kPa
        (Re~4500) — the Forchheimer branch's transient pressure peaks
        exceeded 1 MPa during outer iter ramp-up, locking ρ to the
        clipped value and bleeding momentum residuals.

        Engagement counter `_p_clip_hits` tracks how often the clip
        actually engaged so the caller can warn after a slow run.
        Derive ρ from ideal-gas; no ρ clip (clipping ρ violates the gas
        law and decouples it from (P,T))."""
        if self.fluid_type != 'ideal_gas':
            return
        P_abs = self.P_ref_abs + self.P
        # Diagnostic + robustness: cells outside [1 kPa, 10 MPa] BEFORE clip.
        # Cheap (one mask) compared to the clip itself.
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
        rho_new = P_abs / (self.R_gas * self.T_field)
        # No ρ clip: ρ derives from (P,T); clipping ρ violates ideal gas law.
        self.rho_field = (self.alpha_rho * rho_new
                          + (1.0 - self.alpha_rho) * self.rho_field)
        # Compressible inlet: hold the inlet MASS FLUX (ρ·v) constant, not v.
        self._apply_massflux_inlet()

    def _inlet_mass_flux(self, rho_eps_field):
        """Inlet-face mass flux Σ ε·ρ·|v|·dA at j=0 [kg/s] — normalisation
        reference for the SIMPLE mass residual (A2, 2026-07-06). Uses the
        same ε·ρ convention as the continuity operator so residual/ref is
        dimensionless ("worst-cell imbalance as a fraction of throughput").
        Returns 1.0 for a degenerate inlet (no-flow unit tests) so the
        residual stays absolute there.
        """
        mdot = float(np.sum(rho_eps_field[:, 0, :]
                            * np.abs(self.v[:, 0, :])
                            * self.dx[:, None] * self.dz[None, :]))
        return mdot if mdot > 1e-12 else 1.0

    def _apply_massflux_inlet(self):
        """Re-impose a mass-flux inlet: v_inlet = G_target / ρ_inlet.

        Velocity-inlet (fixed v) + compressible ρ=P/(RT) + Forchheimer
        (dP∝ρ·u² at fixed u) is a POSITIVE feedback (dP↑→P↑→ρ↑→dP↑) that runs
        away for high-resistance configs (air-air narrow offset outlet:
        v_out~2912 m/s, P~120 atm, no convergence — Bug B, 2026-06-04).
        Holding the mass flux G=ρ·v constant makes it NEGATIVE feedback
        (ρ↑→v=G/ρ↓→dP∝1/ρ↓) → stable, and is the physically-correct
        compressible inlet. `G_target` is captured once at solve start from
        the prescribed (v, ρ_ref). For low-dP runs (water, aligned air)
        ρ≈ρ_ref so v≈v_specified — behaviour ≈ the legacy velocity-inlet.

        No-op when disabled, before the target is captured, or for
        incompressible fluids (the ideal_gas guard in _update_density returns
        first; the flag guard here keeps the method self-safe for unit tests).
        """
        if not getattr(self, 'massflux_inlet', True):
            return
        if not hasattr(self, '_massflux_target'):
            return
        rho_in = np.maximum(self.rho_field[:, 0, :], 1e-9)
        self.v_inlet_field = self._massflux_target / rho_in

    def update_T_field(self, T_field):
        """Refresh T_field (and derived mu / mu_eff) for non-iso coupling.

        Accepts scalar or (Nx, Ny, Nz) array.
        """
        if np.ndim(T_field) == 0:
            self.T_field = np.full((self.Nx, self.Ny, self.Nz),
                                     float(T_field), dtype=np.float64)
        else:
            arr = np.asarray(T_field, dtype=np.float64)
            if arr.shape != (self.Nx, self.Ny, self.Nz):
                raise ValueError(
                    f"T_field shape {arr.shape} != "
                    f"({self.Nx}, {self.Ny}, {self.Nz})")
            self.T_field = np.ascontiguousarray(arr)
        if self.fluid_type == 'ideal_gas':
            from sjtu_tpmshx.models.tpms_calc import air_viscosity
            mu_new = air_viscosity(self.T_field).astype(np.float64)
            self.mu_field = np.ascontiguousarray(mu_new)
            # Use eps_field for per-cell μ/ε (zoned ε support); falls back to
            # uniform self.eps when eps_field is the default uniform array.
            eps_eff = self.eps_field if hasattr(self, 'eps_field') else self.eps
            self._mu_eff_field = np.ascontiguousarray(mu_new / eps_eff)

    def solve(self, max_iter=3000, tol=1e-6,
              n_inner=1, verbose=False, cancel_check=None):
        """Run the SIMPLE iterative loop.

        cancel_check : optional callable -> bool. Polled every 25 outer SIMPLE
            iterations (cheap; the JIT sweeps inside one iteration are not
            interruptible). True raises CancelledError; a cancelled solve
            never returns a partial iterate as a completed result.

        `tol` IS NOT THE CONVERGENCE CRITERION — read this before touching it
        ----------------------------------------------------------------------
        `tol` gates `self.final_res`, the mass residual from `_mass_res_jit_3d`.
        It measures the pressure-correction subproblem, not the momentum
        fixed point. Before the six-face outlet closure it was dominated by
        a boundary artifact (ledger C6, 2026-07-12):

          * `_build_pp_sparsity_3d` marks EVERY open outlet cell `cell_kind = 1`,
            and `_assemble_pp_3d` then REPLACES those cells' continuity equation
            with `Pp = 0`. Their continuity is now closed by `_v_bc_3d`.
            This is a DIRICHLET
            PRESSURE-OUTLET BC on the whole outlet face — NOT merely a
            single-point gauge for a singular system. (2D does the same.)
          * The residual is evaluated against `rho_eps_field`, the SAME array
            `_solve_pp_amg` just solved `div(rho_eps.u) = 0` against — before
            `_update_density` refreshed rho. So on every cell the pp equation
            solved, the residual is ~0 TO THE ACCURACY OF THE pp SOLVE.

        SCOPE (added 2026-07-12 after review — the original C6 wording overstated
        this). "~0 by construction" is exact only on the DIRECT-SOLVE path:
        `N <= _AMG_GATE` uses `spsolve`, and the historical measured
        outlet-row-excluded residual is 2.9e-17. Above the gate the pp system is
        solved by AMG-preconditioned BiCGStab with an ADAPTIVE `rtol_dyn` that
        can be as loose as 1e-3, so on server-sized grids the old mass residual
        also carries the pp LINEAR-SOLVE error. It is then a diagnostic of the pp
        sub-problem — still NOT a SIMPLE fixed-point residual; do not quote
        "2.9e-17" outside the small-
        grid regime.

        Historical consequences before local outlet closure, measured on
        the Shanghai production pipeline (600 cells, direct solve):

          * NO case has ever exited via 'tol'. Every one exits on LowReExit's
            velocity criterion. The `stall` exits are this plateau, not a solver
            failure.
          * Tripling max_iter (2000 -> 6000) moves the residual by ZERO to the
            last bit — it is not iterating toward anything.
          * The floor scales with Nz ONLY (the outlet-plane transverse mesh);
            refining Nx/Ny 4x leaves it unchanged.

        Local outlet closure removes that boundary floor, but does not make
        this residual a momentum certificate. The legacy mass-only `tol`
        may now fire earlier; its definition is unchanged. Production F2
        still requires independent momentum and fresh-density mass gates.

        The honest criterion is the MOMENTUM residual (`_mom_res_jit_3d`, ledger
        C7) ANDed with a solved-cell mass residual — see `convergence_mode`.

        Also note `self.residuals` is not inert: the adaptive AMG inner tolerance
        reads `self.residuals[-1]` to schedule `rtol_dyn`. Changing WHAT that list
        holds changes the pp solve's precision schedule on AMG-sized grids. The
        F2 path therefore keeps the legacy mass residual in `residuals` and drives
        the scheduler from it explicitly.

        Returns
        -------
        converged : bool
        iterations : int
        """
        Nx, Ny, Nz = self.Nx, self.Ny, self.Nz
        dx, dy, dz = self.dx, self.dy, self.dz

        # Validate before rejecting an input state or attempting coarse bootstrap.
        _mode = str(getattr(self, 'convergence_mode',
                            os.environ.get('TPMSHX_CONV_MODE', 'legacy')))
        if _mode not in ('legacy', 'f2'):
            raise ValueError(
                f"convergence_mode must be 'legacy' or 'f2', got {_mode!r}")
        if _mode == 'f2' and bool(getattr(self, 'use_anderson', False)):
            raise ValueError(
                "convergence_mode='f2' with use_anderson=True is not "
                "supported: Anderson's acceptance gate still uses the "
                "C6-falsified mass residual and its rollback does not "
                "restore rho_field/v_inlet_field exactly (ledger C7 P0-3). "
                "Disable one of them.")
        # Reset current diagnostics before either entry rejection, including
        # the optional bootstrap return. Histories survive warm restarts.
        self.exit_reason = None
        self.final_res = None
        self.res_norm_ref = 1.0
        if _mode == 'f2':
            self.final_res_mom = None
            self.final_res_mass_local = None
            self.final_res_mass_global = None
            self.outlet_backflow_frac = 0.0
        if _mode == 'f2' and not f2_state_is_finite(self, (self.u, self.v, self.w)):
            return f2_nonfinite_exit(self, 0)

        # Capture the mass-flux inlet target ONCE, at reference inlet
        # conditions (prescribed v × initial ρ), before any pressure build-up.
        # Reused across outer-loop warm restarts so the target never drifts
        # with the elevated ρ. See _apply_massflux_inlet.
        if (getattr(self, 'massflux_inlet', True)
                and self.fluid_type == 'ideal_gas'
                and self.v_inlet_field is not None
                and not hasattr(self, '_massflux_target')):
            self._massflux_target = (np.asarray(self.v_inlet_field,
                                                dtype=np.float64)
                                     * self.rho_field[:, 0, :]).copy()

        # Phase C — coarse-grid bootstrap. Halves grid each axis, solves to
        # loose tol (1e-3), prolongates (u,v,w,P) back as initial guess.
        # Skipped on already-warm solvers (residuals non-empty).
        # `use_coarse_bootstrap`:
        #   * None (default)  — auto: on when Nx*Ny*Nz > _AMG_GATE
        #     (audit P4 / phase L-d Option B). Removes cold-start cost on
        #     AMG-active grids where it dominates.
        #   * True            — always on (legacy explicit opt-in)
        #   * False           — always off
        _cb_flag = getattr(self, 'use_coarse_bootstrap', None)
        if _cb_flag is None:
            _cb_flag = (Nx * Ny * Nz > _AMG_GATE)
        if _cb_flag and not self.residuals:
            try:
                from .coarse_bootstrap_3d import bootstrap_simple_3d
                _bs_info = bootstrap_simple_3d(
                    self,
                    max_iter_coarse=int(getattr(
                        self, 'coarse_bootstrap_max_iter', 200)),
                    tol_coarse=float(getattr(
                        self, 'coarse_bootstrap_tol', 1e-3)),
                    verbose=verbose,
                )
                self._coarse_bootstrap_info = _bs_info
                if verbose and _bs_info.get('applied'):
                    _log.info(f"  3D coarse bootstrap: shape="
                              f"{_bs_info['coarse_shape']}, iters="
                              f"{_bs_info['coarse_iters']}, "
                              f"res={_bs_info['coarse_residual']:.3e}")
            except Exception as exc:   # robust: never block fine solve
                self._coarse_bootstrap_info = {
                    'applied': False, 'reason': f'exception:{exc}'}
                if verbose:
                    _log.warning(f"  3D coarse bootstrap skipped: {exc}")
            if _mode == 'f2' and not f2_state_is_finite(self, (self.u, self.v, self.w)):
                return f2_nonfinite_exit(self, 0)

        if self._pp_sparsity is None:
            self._pp_sparsity = _build_pp_sparsity_3d(Nx, Ny, Nz,
                                                        self.outlet_mask_ij)

        # Adaptive dispatch: small grids (<200k cells) use serial natural-
        # ordering GS; large grids use red-black GS on prange. Break-even
        # ~200k cells where Numba thread-launch overhead no longer dominates.
        if _should_parallelize(Nx, Ny, Nz):
            # P3.2: one-shot thread-count advisory on the unpinned all-cores
            # default (bandwidth-bound kernels; advisory only, pool untouched).
            _warn_if_default_pool(Nx * Ny * Nz)
            _sweep_u = _sweep_u_jit_df_3d_parallel
            _sweep_v = _sweep_v_jit_df_3d_parallel
            _sweep_w = _sweep_w_jit_df_3d_parallel
        else:
            _sweep_u = _sweep_u_jit_df_3d
            _sweep_v = _sweep_v_jit_df_3d
            _sweep_w = _sweep_w_jit_df_3d

        # R4 (openspec solver-efficiency-r1-r4): opt-in minmod SOU deferred
        # correction in the momentum sweeps. 0 (default) = first-order upwind,
        # numerically identical to the pre-R4 kernels.
        _use_sou = 1 if getattr(self, 'use_sou_momentum', False) else 0

        # M2b (2026-07-09, VANS ∇ε): momentum ε-ratio factors fire only for a
        # genuinely non-uniform eps_field. Uniform (production per-side /
        # golden) keeps use_eps=0 → the fastmath expression tree is untouched
        # → bit-identical to pre-M2b. Computed once per solve().
        _eps_f = self.eps_field
        _use_eps = 1 if float(_eps_f.max()) != float(_eps_f.min()) else 0

        # Phase B — Anderson acceleration on SIMPLE outer Picard map.
        # Off-by-default for safety; opt-in via solver attribute set by caller.
        use_anderson = getattr(self, 'use_anderson', False)
        if use_anderson:
            from .anderson_acceleration import (
                AndersonSIMPLE, stack_state, unstack_state)
            acc = AndersonSIMPLE(m=int(getattr(self, 'anderson_m', 5)),
                                  K=int(getattr(self, 'anderson_K', 3)))
            prev_x = stack_state(self.u, self.v, self.w, self.P)
        else:
            acc = None
            prev_x = None

        # ── A+B early-exit for low-Re / low-speed solves (e.g. water Re~33) ──
        # Historical motivation: the mass residual used to be an ABSOLUTE
        # divergence norm, so slow water plateaued ~1e-4 above an air-tuned
        # tol and burned all max_iter with a settled field. A2 (2026-07-06)
        # normalises the residual by the inlet mass flux, which removes the
        # scale mismatch; the early-exit stays as a safety net for genuinely
        # slow-converging cases (its criteria arithmetic is under the
        # bit-identity contract in _solve_common.py — do not modify there).
        # Two extra convergence tests, both gated by velocity STABILITY, so a
        # still-moving field can never exit early:
        #   (A) plateau-stall : residual barely improves for K consecutive iters
        #   (B) velocity-delta : max|Δv|/scale < vtol between iterations
        # Off → identical to the legacy behaviour. On (default) → only fires
        # AFTER the field stops moving, so the converged result is unchanged.
        # Criteria single-sourced in solvers/_solve_common.LowReExit since
        # arch-b-c-e batch C (shared with the 2D solver).
        _lowre = LowReExit(self, (self.u, self.v, self.w), min_iter=10)

        # Ledger C6 — OPT-IN momentum residual. DIAGNOSTIC ONLY: it is recorded
        # but does NOT gate the exit, so enabling it cannot change any result.
        # Default OFF (it costs one extra full coefficient assembly per SIMPLE
        # iteration). Enable per-solver via `track_momentum_residual = True`, or
        # globally via env TPMSHX_MOM_RES=1 (for sweeps / V&V studies).
        # `mom_residuals` accumulates across warm restarts, like `residuals`.
        _track_mom = bool(getattr(self, 'track_momentum_residual', False)
                          or os.environ.get('TPMSHX_MOM_RES', '') == '1')
        if _track_mom and not hasattr(self, 'mom_residuals'):
            self.mom_residuals = []

        # ── Ledger C7 / F2 — convergence mode ────────────────────────────
        # 'legacy' (default): `tol` on the mass residual + LowReExit. Ledger C6
        #     shows that `tol` is unreachable and LowReExit's velocity criterion
        #     is what actually decides. Kept as the default until F2 is priced
        #     and re-baselined; it is what every golden / gate number to date was
        #     produced with.
        # 'f2'    : three independent gates (momentum + solved-cell mass + global
        #     boundary mass), each with its OWN tolerance, confirmed over
        #     `f2_n_confirm` consecutive checks. A static velocity field triggers
        #     a check; it does NOT terminate. See F2Monitor.
        _f2 = None
        if _mode == 'f2':
            # Anderson mutates u/v/w/P/rho AFTER the Picard step, gates its
            # candidate on the C6-falsified mass artifact, and its rollback does
            # NOT restore rho_field exactly (`_update_density` re-blends against
            # the already-Anderson-mixed rho, and `_apply_massflux_inlet` then
            # rebuilds v_inlet_field from it). Every one of those breaks a
            # residual-gated exit. Fix Anderson first; do not silently combine.
            _f2 = F2Monitor(self, (self.u, self.v, self.w), min_iter=10)
            for _h in ('mass_local_residuals', 'mass_global_residuals'):
                if not hasattr(self, _h):
                    setattr(self, _h, [])
            if not hasattr(self, 'mom_residuals'):
                self.mom_residuals = []
        elif _track_mom and bool(getattr(self, 'use_anderson', False)):
            _log.warning(
                "  [WARN] track_momentum_residual + use_anderson: the recorded "
                "momentum residual is evaluated after the Anderson step, but "
                "Anderson's own accept/rollback still uses the legacy mass "
                "residual — treat the history as indicative only (ledger C7).")

        for it in range(1, max_iter + 1):
            # Cooperative cancel (point 4): poll every 25 iters — cheap, and
            # fine enough that a water solve aborts in well under a second.
            if cancel_check is not None and (it % 25 == 0) and cancel_check():
                self.exit_reason = 'cancelled'
                raise CancelledError("compute cancelled by user")
            # Effective density for continuity: ε·ρ. Uniform ε → multiplicative
            # constant (no functional change). Zoned ε → captures macroscopic
            # ∇·(ε·ρ·u)=0 form; without this the ∇ε contribution is dropped.
            # Reuse a persistent buffer instead of allocating ε·ρ every outer
            # iteration. Bit-identical to ascontiguousarray(rho*eps); rho_eps_field
            # is only read (PP solve + mass residual) within this iteration.
            if getattr(self, '_rho_eps', None) is None or \
                    self._rho_eps.shape != self.rho_field.shape:
                self._rho_eps = np.empty_like(self.rho_field)
            np.multiply(self.rho_field, self.eps_field, out=self._rho_eps)
            rho_eps_field = self._rho_eps
            _sweep_u(self.u, self.v, self.w, self.P, self.d_u,
                      Nx, Ny, Nz, dx, dy, dz,
                      self.rho_field, self._mu_eff_field, self.mu_field,
                      self.eps_field,
                      self.K_arr, self.cF_arr,
                      self.outlet_u_frac,
                      self.alpha_u, n_inner, _use_sou, _use_eps)
            _sweep_v(self.u, self.v, self.w, self.P, self.d_v,
                      self.v_inlet_field,
                      Nx, Ny, Nz, dx, dy, dz,
                      self.rho_field, self.eps_field,
                      self._mu_eff_field, self.mu_field,
                      self.K_arr, self.cF_arr,
                      self.alpha_u, n_inner, _use_sou, _use_eps,
                      self.outlet_mask_ij)
            _sweep_w(self.u, self.v, self.w, self.P, self.d_w,
                      Nx, Ny, Nz, dx, dy, dz,
                      self.rho_field, self._mu_eff_field, self.mu_field,
                      self.eps_field,
                      self.K_arr, self.cF_arr,
                      self.outlet_w_frac,
                      self.alpha_u, n_inner, _use_sou, _use_eps)

            # E2 (audit 2026-06-28): force a rebuild on the first inner iter only
            # when the hierarchy cache is COLD. On a warm restart (the 3D outer
            # SIMPLE-LTNE loop re-calls solve() up to _MAX_OUTER times keeping
            # self._ml_cache) the matrix only drifted by the alpha_T under-
            # relaxed rho/mu change, so let the drift check (drift_thresh) decide
            # instead of discarding a still-valid hierarchy every solve(). A cold
            # cache still builds via this it==1 force (and via 'ml' not in cache
            # inside _solve_pp_amg). Numerically identical at convergence — the
            # AMG hierarchy is only a preconditioner.
            rebuild = (it == 1 and 'ml' not in self._ml_cache) \
                or (it % self.pyamg_rebuild_every == 0)
            # Phase A — adaptive AMG inner tolerance. First iter (no residual
            # history) uses loose 1e-3; thereafter follows outer mass residual.
            if getattr(self, 'use_adaptive_amg_tol', True):
                prev_res = self.residuals[-1] if self.residuals else 1.0
                rtol_dyn = float(np.clip(0.05 * prev_res, 1e-7, 1e-3))
            else:
                rtol_dyn = 1e-5
            _solve_pp_amg(self.Pp, self.u, self.v, self.w,
                           self.d_u, self.d_v, self.d_w,
                           Nx, Ny, Nz, dx, dy, dz, rho_eps_field,
                           self._pp_sparsity, self._ml_cache, rebuild,
                           rtol_dyn=rtol_dyn,
                           drift_thresh=self.pyamg_rebuild_drift_thresh)

            _correct_jit_3d(self.u, self.v, self.w, self.P, self.Pp,
                             self.d_u, self.d_v, self.d_w,
                             self.v_inlet_field, Nx, Ny, Nz, self.alpha_p,
                             self.rho_field, self.eps_field, self.outlet_mask_ij,
                             dx, dy, dz)
            if (_f2 is not None and self.fluid_type == 'ideal_gas'
                    and not f2_state_is_finite(self, (self.u, self.v, self.w))):
                return f2_nonfinite_exit(self, it)
            self._update_density()  # compressible: ρ = P/(RT) + mass flux rescale
            if _f2 is not None and not f2_state_is_finite(self, (self.u, self.v, self.w)):
                return f2_nonfinite_exit(self, it)

            # NOTE: `rho_eps_field` here is the PRE-`_update_density` array —
            # the one `_solve_pp_amg` above just solved div(rho_eps.u)=0 against.
            # The outlet BC now also closes the pinned CVs against this same
            # density. This remains a pp-subproblem diagnostic, not a momentum
            # certificate. Keep its definition for the adaptive AMG schedule;
            # F2 below independently evaluates the final fresh-density state.
            res = _mass_res_jit_3d(self.u, self.v, self.w,
                                     Nx, Ny, Nz, dx, dy, dz,
                                     rho_eps_field)
            # A2 (2026-07-06): normalise the absolute cell-divergence norm by
            # the inlet mass flux so `tol` means "worst-cell imbalance as a
            # fraction of throughput" — scale-invariant across ṁ / fluids and
            # aligned with the 2D relative residual semantics. Degenerate
            # no-flow cases (unit tests, v_inlet=None) keep the absolute norm
            # via the ref=1.0 fallback.
            self.res_norm_ref = self._inlet_mass_flux(rho_eps_field)
            res = res / self.res_norm_ref
            self.final_res = res

            # Phase B — Anderson step (every K outer iters, after warmup).
            if acc is not None and it > 5:
                gx_picard = stack_state(self.u, self.v, self.w, self.P)
                acc.push(prev_x, gx_picard)
                if it % acc.K == 0:
                    x_anderson, applied = acc.candidate(gx_picard)
                    if applied:
                        u2, v2, w2, P2 = unstack_state(
                            x_anderson, self.u, self.v, self.w, self.P)
                        # Stash Picard state in case we need to roll back.
                        u_picard = self.u.copy()
                        v_picard = self.v.copy()
                        w_picard = self.w.copy()
                        P_picard = self.P.copy()
                        self.u[:] = u2
                        self.v[:] = v2
                        self.w[:] = w2
                        self.P[:] = P2
                        # Re-project to mass-conserving manifold (extra PC).
                        rho_eps_field2 = np.ascontiguousarray(
                            self.rho_field * self.eps_field, dtype=np.float64)
                        _solve_pp_amg(self.Pp, self.u, self.v, self.w,
                                       self.d_u, self.d_v, self.d_w,
                                       Nx, Ny, Nz, dx, dy, dz, rho_eps_field2,
                                       self._pp_sparsity, self._ml_cache,
                                       False, rtol_dyn=rtol_dyn,
                                       drift_thresh=(
                                           self.pyamg_rebuild_drift_thresh))
                        _correct_jit_3d(self.u, self.v, self.w, self.P, self.Pp,
                                         self.d_u, self.d_v, self.d_w,
                                         self.v_inlet_field, Nx, Ny, Nz,
                                         self.alpha_p, self.rho_field,
                                         self.eps_field, self.outlet_mask_ij,
                                         dx, dy, dz)
                        self._update_density()
                        # Same A2 inlet-flux normalisation as the main `res`
                        # (line ~910) — comparing a raw kg/s norm against the
                        # normalised one made acceptance depend on ṁ scale.
                        res_anderson = _mass_res_jit_3d(
                            self.u, self.v, self.w, Nx, Ny, Nz, dx, dy, dz,
                            rho_eps_field2) / self.res_norm_ref
                        if (not np.isfinite(res_anderson)
                                or res_anderson > res):
                            # Roll back to Picard state.
                            self.u[:] = u_picard
                            self.v[:] = v_picard
                            self.w[:] = w_picard
                            self.P[:] = P_picard
                            self._update_density()
                            acc.rolled_back_count += 1
                        else:
                            res = res_anderson
                # Always update prev_x using the post-step (post-Anderson if
                # accepted) state for the next iteration's diff.
                prev_x = stack_state(self.u, self.v, self.w, self.P)

            # `residuals` keeps holding the LEGACY mass residual, deliberately.
            # It is not inert: the adaptive AMG scheduler above reads
            # `self.residuals[-1]` to set `rtol_dyn`. Repurposing this list would
            # silently change the pp solve's precision schedule on AMG-sized
            # grids. The F2 metrics get their own histories (below).
            self.residuals.append(res)

            if verbose and it % 50 == 0:
                _log.info(f"  3D iter {it:5d}  |R| = {res:.3e}")

            # ══ Residuals evaluated on the FINAL state of this iteration ══
            # After the sweeps, the pp solve, the correction, the density update
            # AND any Anderson accept/rollback. Ordering matters: an earlier
            # revision computed the momentum residual BEFORE the Anderson block,
            # so on an accepted Anderson step the recorded residual described a
            # state that was then overwritten (codex review, 2026-07-12).
            _need_mom = _track_mom or (_f2 is not None)
            _vd = _f2.velocity_delta((self.u, self.v, self.w)) \
                if _f2 is not None else None
            _eval_mom = (_track_mom if _f2 is None
                         else (_f2.should_eval_momentum(it, _vd) or _track_mom))

            _Rmom = None
            if _need_mom and _eval_mom:
                _Rmom, _mom_rec = self._momentum_residual(
                    Nx, Ny, Nz, dx, dy, dz, _use_sou, _use_eps)
                self.final_res_mom = _Rmom
                if _track_mom:
                    _mom_rec['iter'] = it
                    self.mom_residuals.append(_mom_rec)

            if _f2 is not None:
                _rho_eps_now = np.ascontiguousarray(
                    self.rho_field * self.eps_field, dtype=np.float64)
                _Rml, _n_solved = _mass_res_solved_jit_3d(
                    self.u, self.v, self.w, Nx, Ny, Nz, dx, dy, dz,
                    _rho_eps_now, self._pp_sparsity['cell_kind'])
                _min, _mout, _bf = _mass_global_jit_3d(
                    self.v, Nx, Ny, Nz, dx, dz, _rho_eps_now)
                _Rmg = global_mass_residual(_min, _mout)
                self.mass_local_residuals.append(_Rml)
                self.mass_global_residuals.append(_Rmg)
                self.outlet_backflow_frac = _bf
                self.final_res_mass_local = _Rml
                self.final_res_mass_global = _Rmg
                if not np.isfinite((res, _vd, _Rml, _Rmg, _bf)).all():
                    return f2_nonfinite_exit(self, it)

                if _Rmom is not None:
                    self.final_res_mom = _Rmom
                    _reason = _f2.submit(it, _Rmom, _Rml, _Rmg, _vd, _bf)
                    if _reason == 'nonfinite':
                        return f2_nonfinite_exit(self, it)
                    if _reason is not None:
                        self.exit_reason = _reason
                        return (_reason == 'tol'), it
                # NOTE: no `velocity` exit here. A static field only TRIGGERS a
                # check (see F2Monitor.should_eval_momentum); it never
                # terminates. Returning False on it would merely convert a
                # premature success into a premature failure — the solve would
                # still stop at ~90 iters and never reach the real gate at ~250.
                continue

            # ── LEGACY path (convergence_mode='legacy') ──────────────────
            # Strict exit: residual below tol (A2: res is now the inlet-flux-
            # normalised relative norm, so tol means a throughput fraction).
            # Local outlet closure can remove the old outlet-pin floor. Keep
            # the legacy criterion unchanged; production uses F2 above.
            if res < tol and it >= 10:
                self.exit_reason = 'tol'
                return True, it

            # ── A+B early-exit (low-Re / low-speed) — see LowReExit.
            _reason = _lowre.check((self.u, self.v, self.w), res, it)
            if _reason is not None:
                # A2 (2026-07-06): 'velocity' (field static to vtol) counts as
                # converged — a reached fixed point. 'stall' (residual plateau
                # with a still-creeping field) returns the fields but reports
                # converged=False so the pipeline verdict can flag it.
                self.exit_reason = _reason
                return (_reason == 'velocity'), it

        self.exit_reason = 'max_iter'
        return False, max_iter

    # ── ledger C7 — momentum residual, balanced normalisation ─────────
    _MOM_FLOOR_FRAC = 1e-3

    def _momentum_residual(self, Nx, Ny, Nz, dx, dy, dz, use_sou, use_eps):
        """(R_max, record) on the solver's CURRENT state.

        Balanced denominator (see `_mom_res_jit_3d`): den_c = Σ½(|lhs| + |rhs|),
        so `num > 0 ⟹ den > 0` and a false zero is structurally impossible.

        COMMON FLOOR. Each component is divided by `max(den_c, floor)` with
        `floor = _MOM_FLOOR_FRAC * max(den_u, den_v, den_w)`. Without it, a
        physically negligible component (e.g. w-momentum in a plane-dominated
        flow, whose forces are orders of magnitude below u/v) would be scored on
        its own tiny scale and could hold the gate open on numerical noise. With
        it, a component carrying less than 0.1 % of the dominant momentum scale
        is measured against that dominant scale instead — it can still fail the
        gate, but only for an imbalance that is large in absolute terms.

        Raw num/den are kept in the record so the normalisation can be revisited
        without re-running.
        """
        nu_, du_, nv_, dv_, nw_, dw_ = _mom_res_jit_3d(
            self.u, self.v, self.w, self.P,
            Nx, Ny, Nz, dx, dy, dz,
            self.rho_field, self._mu_eff_field, self.mu_field,
            self.eps_field, self.K_arr, self.cF_arr,
            self.outlet_u_frac, self.outlet_w_frac, use_sou, use_eps)
        ru, rv, rw = momentum_component_residuals(
            (nu_, nv_, nw_), (du_, dv_, dw_), self._MOM_FLOOR_FRAC)
        rmax = max(ru, rv, rw)
        return rmax, {'u': ru, 'v': rv, 'w': rw, 'max': rmax,
                      'num': (nu_, nv_, nw_), 'den': (du_, dv_, dw_)}


# ── JIT warmup — pay the compile cost at module-import time, not on first
#    Run-Calculation click. Every @njit kernel called once on a tiny grid.
def _warmup_simple_3d():
    """Compile the Numba momentum/mass kernels on import so the first real
    solve() doesn't pay the JIT cost.

    Args MUST match the kernel signatures exactly. The previous version
    mis-ordered them (dx/dy/dz fell into the Nx/Ny/Nz int slots, eps into
    n_sweeps), so every call raised a TypeError that was silently swallowed
    — the warmup compiled nothing and the first Run ate the full compile.
    Both the serial and red-black ``_parallel`` variants are warmed because
    solve() dispatches either one depending on grid size
    (see ``_should_parallelize``).
    """
    try:
        Nx, Ny, Nz = 3, 3, 3
        zeros3 = lambda shp: np.zeros(shp, dtype=np.float64)
        ones3 = lambda shp: np.ones(shp, dtype=np.float64)
        u = zeros3((Nx + 1, Ny, Nz))
        v = zeros3((Nx, Ny + 1, Nz))
        w = zeros3((Nx, Ny, Nz + 1))
        P = zeros3((Nx, Ny, Nz))
        d_u = zeros3((Nx + 1, Ny, Nz))
        d_v = zeros3((Nx, Ny + 1, Nz))
        d_w = zeros3((Nx, Ny, Nz + 1))
        dx = ones3(Nx); dy = ones3(Ny); dz = ones3(Nz)
        rho = ones3((Nx, Ny, Nz))
        eps = ones3((Nx, Ny, Nz)) * 0.5
        mu = ones3((Nx, Ny, Nz))
        mu_eff = ones3((Nx, Ny, Nz))
        K_arr = ones3((Ny, Nz)) * 1e-7
        cF_arr = ones3((Ny, Nz)) * 340.0
        v_inlet = ones3((Nx, Nz))
        out_u_frac = ones3((Nx + 1, Nz))
        out_w_frac = ones3((Nx, Nz + 1))
        outlet_mask = np.ones((Nx, Nz), dtype=np.bool_)
        alpha_u = 0.5
        n = 1
        # u/w sig: (u,v,w,P,d, Nx,Ny,Nz, dx,dy,dz, rho,mu_eff,mu,eps, K,cF,
        #           staggered outlet fraction, alpha, n, use_sou, use_eps)
        for ku in (_sweep_u_jit_df_3d, _sweep_u_jit_df_3d_parallel):
            ku(u, v, w, P, d_u, Nx, Ny, Nz, dx, dy, dz,
               rho, mu_eff, mu, eps, K_arr, cF_arr, out_u_frac, alpha_u,
               n, 0, 0)
        # v sig inserts v_inlet right after d_v, before Nx,Ny,Nz; eps after rho.
        for kv in (_sweep_v_jit_df_3d, _sweep_v_jit_df_3d_parallel):
            kv(u, v, w, P, d_v, v_inlet, Nx, Ny, Nz, dx, dy, dz,
               rho, eps, mu_eff, mu, K_arr, cF_arr,
               alpha_u, n, 0, 0, outlet_mask)
        for kw in (_sweep_w_jit_df_3d, _sweep_w_jit_df_3d_parallel):
            kw(u, v, w, P, d_w, Nx, Ny, Nz, dx, dy, dz,
               rho, mu_eff, mu, eps, K_arr, cF_arr, out_w_frac, alpha_u,
               n, 0, 0)
        _mass_res_jit_3d(u, v, w, Nx, Ny, Nz, dx, dy, dz, rho)
    except Exception as e:
        import os
        if os.environ.get('TPMSHX_DEBUG'):
            import warnings
            warnings.warn(
                f"3D JIT warmup failed (kernels compile on first solve): {e!r}")


_warmup_simple_3d()
