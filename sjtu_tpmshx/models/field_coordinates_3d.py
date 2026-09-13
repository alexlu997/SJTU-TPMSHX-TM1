"""Pure numpy helpers extracted verbatim from stages_3d.py (Phase 3 god-file
split). No module-global / solver-import dependencies — index/face/slice math,
3D smoothing, staggered<->real remap, stream-outflow balance, and chi_B field
builders. Current preparation and numerical backends import these helpers
from models; the former stage facade is retired."""
from __future__ import annotations

import numpy as np


def _stream_axis(dir_code):
    """Real-coord streamwise axis: 0/1→x(0), 2/3→y(1), 4/5→z(2)."""
    return int(dir_code) // 2


def _dir_is_reverse(dir_code):
    """True for negative-going dirs (-x/-y/-z = odd codes 1/3/5)."""
    return bool(int(dir_code) % 2)


def _inlet_index(dir_code):
    """Stream-axis index of the REAL inlet face (0 forward, -1 reverse)."""
    return -1 if _dir_is_reverse(dir_code) else 0


def _outlet_index(dir_code):
    """Stream-axis index of the REAL outlet face (-1 forward, 0 reverse)."""
    return 0 if _dir_is_reverse(dir_code) else -1


def _face_slice(field, dir_code, which):
    """View of ``field``'s real inlet/outlet face. which ∈ {'inlet','outlet'}.
    Returns the same axis-collapsed view the hand-rolled ladders did."""
    idx = _inlet_index(dir_code) if which == 'inlet' else _outlet_index(dir_code)
    sl = [slice(None), slice(None), slice(None)]
    sl[_stream_axis(dir_code)] = idx
    return field[tuple(sl)]


def _real_outlet_slice(T_field, dir_code):
    return _face_slice(T_field, dir_code, 'outlet')


def _port_rectangles(fluid_cfg, cross2_length):
    """Keep the original physical edges; reversing flow never swaps ports."""
    return {
        f'{end}let_rect': (
            fluid_cfg[f'{end}_ctr'] - fluid_cfg[f'{end}_w'] / 2,
            fluid_cfg[f'{end}_ctr'] + fluid_cfg[f'{end}_w'] / 2,
            fluid_cfg.get(f'{end}_z_ctr', cross2_length / 2)
            - fluid_cfg.get(f'{end}_z_w', cross2_length) / 2,
            fluid_cfg.get(f'{end}_z_ctr', cross2_length / 2)
            + fluid_cfg.get(f'{end}_z_w', cross2_length) / 2)
        for end in ('in', 'out')}


def _build_partial_masks(fA, dcross1, dcross2, N_cross1, N_cross2, is_reverse):
    """Build inlet/outlet exact open-area fractions on the 2-axis inlet face.

    Solver's inlet_frac shape is (Nx_sol, Nz_sol) = (N_cross1, N_cross2).
    UI inputs `in_ctr/in_w` → cross1 axis; `in_z_ctr/in_z_w` → cross2 axis.
    For ±x/±y streamwise cross2 is real-z; for ±z streamwise cross2 is real-y.
    (Semantic mismatch noted in UI docs — future UI pass may relabel.)
    """
    from sjtu_tpmshx.models.grid import _port_fractions_1d
    in_lo = fA['in_ctr'] - fA['in_w'] / 2
    in_hi = fA['in_ctr'] + fA['in_w'] / 2
    out_lo = fA['out_ctr'] - fA['out_w'] / 2
    out_hi = fA['out_ctr'] + fA['out_w'] / 2
    in_c1, _ = _port_fractions_1d(dcross1, in_lo, in_hi)
    out_c1, _ = _port_fractions_1d(dcross1, out_lo, out_hi)
    if not in_c1.any() or not out_c1.any():
        raise ValueError("Inlet / outlet range (cross1) resolves to zero cells.")

    # cross2 (z-partial keys — treated as second cross-axis regardless of label)
    has_c2_partial = all(k in fA for k in
                          ('in_z_ctr', 'in_z_w', 'out_z_ctr', 'out_z_w'))
    if has_c2_partial and dcross2 is not None:
        in_z_lo = fA['in_z_ctr'] - fA['in_z_w'] / 2
        in_z_hi = fA['in_z_ctr'] + fA['in_z_w'] / 2
        out_z_lo = fA['out_z_ctr'] - fA['out_z_w'] / 2
        out_z_hi = fA['out_z_ctr'] + fA['out_z_w'] / 2
        in_c2, _ = _port_fractions_1d(dcross2, in_z_lo, in_z_hi)
        out_c2, _ = _port_fractions_1d(dcross2, out_z_lo, out_z_hi)
        if not in_c2.any() or not out_c2.any():
            raise ValueError("Inlet / outlet range (cross2) resolves to zero cells.")
    else:
        in_c2 = np.ones(N_cross2, dtype=bool)
        out_c2 = np.ones(N_cross2, dtype=bool)
    # approach-(a) reverse convention: NO in/out swap. The solver always
    # injects at j=0 with inlet_frac and exhausts at j=-1 with outlet_frac;
    # the reverse-dir spatial flip (in the velocity transforms) maps solver
    # j=0 onto the real inlet end, so in_mask must carry the PHYSICAL inlet
    # patch (in_ctr) regardless of direction. (Was: swap in_c<->out_c for
    # is_reverse — that was approach-(b) and contradicted the LTNE kernel.)
    in_mask = np.outer(in_c1, in_c2).astype(np.float64)   # (N_cross1, N_cross2)
    out_mask = np.outer(out_c1, out_c2).astype(np.float64)
    return in_mask, out_mask


def _solver_velocity_to_real(solver, axis_map, real_shape):
    """Map SIMPLE3D staggered velocity components back to real coordinates."""
    perm = axis_map['solver_to_real_perm']
    u_cc = 0.5 * (solver.u[:-1, :, :] + solver.u[1:, :, :])
    v_cc = 0.5 * (solver.v[:, :-1, :] + solver.v[:, 1:, :])
    w_cc = 0.5 * (solver.w[:, :, :-1] + solver.w[:, :, 1:])

    comps = [np.zeros(real_shape, dtype=np.float64) for _ in range(3)]
    comps[axis_map['cross1_real_axis']] = np.ascontiguousarray(
        u_cc.transpose(perm))
    stream = np.ascontiguousarray(v_cc.transpose(perm))
    if axis_map['is_reverse']:
        stream = -stream
    comps[axis_map['stream_real_axis']] = stream
    comps[axis_map['cross2_real_axis']] = np.ascontiguousarray(
        w_cc.transpose(perm))
    # approach-(a) reverse convention: y-reflection of the velocity field.
    # The solver injects at j=0 (its +stream); for a reverse-dir fluid the
    # real inlet is at the OPPOSITE stream end, so the field is spatially
    # flipped along the real stream axis (stream component already negated
    # above). Matches evaluate_3d's -vB_cc[:, ::-1, :] and the LTNE kernel's
    # approach-(a) inlet/outlet placement.
    if axis_map['is_reverse']:
        sax = axis_map['stream_real_axis']
        comps = [np.flip(c, axis=sax) for c in comps]
    return tuple(np.ascontiguousarray(c) for c in comps)


def _solver_staggered_to_real(solver, axis_map, real_shape):
    """Map SIMPLE3D staggered face velocities to REAL-coord face arrays.

    Returns (uf_real, vf_real, wf_real) of shapes:
      uf_real : (Nx+1, Ny, Nz)  — face velocities at real x-faces (+x signed)
      vf_real : (Nx, Ny+1, Nz)  — face velocities at real y-faces (+y signed)
      wf_real : (Nx, Ny, Nz+1)  — face velocities at real z-faces (+z signed)

    The stream component (solver's y-axis v) gets sign-flipped if is_reverse,
    because for reverse-dir fluids SIMPLE's local +y is the real -stream_axis.

    This is what `_gs_full_chunk_3d_stag` consumes — identical face fluxes
    to SIMPLE's momentum solver so ∇·(ρv) = 0 cell-wise (to SIMPLE's
    continuity residual) and the LTNE metric's NET_OUT is zero.
    """
    perm = axis_map['solver_to_real_perm']
    Nx, Ny, Nz = real_shape

    # SIMPLE's u is staggered in solver's X axis (cross1 in real).
    # Shape (Nx_sol+1, Ny_sol, Nz_sol). After transpose(perm): must end
    # up staggered in cross1_real_axis.
    # SIMPLE's v is staggered in solver Y (the stream).
    # SIMPLE's w is staggered in solver Z (cross2 in real).
    u_sol = solver.u  # (Nx_sol+1, Ny_sol, Nz_sol)
    v_sol = solver.v  # (Nx_sol, Ny_sol+1, Nz_sol)
    w_sol = solver.w  # (Nx_sol, Ny_sol, Nz_sol+1)

    # Transpose mirrors cell-centred components' perm. The extra +1
    # dimension survives the transpose automatically.
    u_real = np.ascontiguousarray(u_sol.transpose(perm))
    v_real = np.ascontiguousarray(v_sol.transpose(perm))
    w_real = np.ascontiguousarray(w_sol.transpose(perm))

    # Classify each transposed array into (x-staggered, y-staggered, z-staggered).
    # The original array is staggered along ONE solver axis; perm maps that axis
    # to the corresponding real axis. After transpose, the staggered axis lives
    # at real axis = perm.index(original_axis).
    # SIMPLE conventions:
    #   u staggered on solver axis 0 (cross1 in real → cross1_real_axis)
    #   v staggered on solver axis 1 (stream)
    #   w staggered on solver axis 2 (cross2)
    stream_ax = axis_map['stream_real_axis']
    cross1_ax = axis_map['cross1_real_axis']
    cross2_ax = axis_map['cross2_real_axis']

    # sign-flip the stream array for reverse dirs.
    is_reverse = axis_map['is_reverse']

    # Build outputs — assign each transposed staggered array to the slot
    # indexed by its real axis.
    out = [None, None, None]  # slot[k] = face array staggered in real axis k
    # u_real: staggered in axis perm.index(0) → cross1_real_axis
    # v_real: staggered in axis perm.index(1) → stream_real_axis
    # w_real: staggered in axis perm.index(2) → cross2_real_axis
    out[cross1_ax] = u_real
    stream_arr = v_real if not is_reverse else -v_real
    out[stream_ax] = stream_arr
    out[cross2_ax] = w_real

    # approach-(a) reverse convention: spatially flip the staggered face
    # arrays along the real stream axis (the stream component is already
    # negated above). A staggered array of size N+1 along the flip axis
    # reverses so the +1 face lands on the mirrored boundary — matches
    # evaluate_3d's sB.u/-sB.v/sB.w [:, ::-1, :] and keeps the face fluxes
    # discretely solenoidal for the conservative LTNE kernel.
    if is_reverse:
        out = [np.flip(o, axis=stream_ax) for o in out]

    uf_real = np.ascontiguousarray(out[0], dtype=np.float64)
    vf_real = np.ascontiguousarray(out[1], dtype=np.float64)
    wf_real = np.ascontiguousarray(out[2], dtype=np.float64)

    # Shape sanity check
    assert uf_real.shape == (Nx+1, Ny, Nz), f"uf {uf_real.shape} != ({Nx+1},{Ny},{Nz})"
    assert vf_real.shape == (Nx, Ny+1, Nz), f"vf {vf_real.shape} != ({Nx},{Ny+1},{Nz})"
    assert wf_real.shape == (Nx, Ny, Nz+1), f"wf {wf_real.shape} != ({Nx},{Ny},{Nz+1})"
    return uf_real, vf_real, wf_real


def _balance_stream_outflow(faces, axis_map, coef, dx, dy, dz):
    """Rescale the OUTFLOW stream-boundary face so the coef-weighted net flux
    through the two stream boundary faces is zero — discrete global mass
    conservation, ∮F·n dA = 0.

    Why: the strict conservative-LTNE kernel telescopes the SIMPLE staggered
    face fluxes (`F_e[i] ≡ F_w[i+1]`), so summing the per-cell energy balance
    over the domain collapses to the boundary integral ∮F·n. SIMPLE's converged
    velocity carries a small continuity residual; partial-BC inlet/outlet masks
    + the outlet taper amplify it for offset/reverse cases, leaving a nonzero
    net ΣD ≡ ∮F·n. The homogeneous-Neumann MAC projection
    (`_project_faces_div_free`) removes only the zero-mean part of that
    divergence — the constant null-space component (= the net ΣD) is
    irreducible, so it survives as a uniform spurious energy divergence and the
    reverse-dir heat load drifts (y-mirror breaks ~17 %, spurious over-heating).
    Enforcing Σ_inlet = Σ_outlet here drives ΣD → 0 BEFORE the projection, so
    the projection then cleans the interior to machine precision and the kernel
    is genuinely conservative for reverse-dir/offset fluids too.

    `coef` = eps_f · ρcp = the projection's per-cell flux coefficient (eps_f =
    0.5·ε). Near-balanced cases (full-face, Shanghai) get scale ≈ 1 → no-op.

    Mutates and returns `faces` = [uf, vf, wf] (already contiguous copies).
    """
    sax = int(axis_map['stream_real_axis'])
    is_rev = bool(axis_map['is_reverse'])
    F = faces[sax]
    # Perpendicular face area + boundary-cell coef (matching the projection's
    # boundary-face coefficient `cf[0]=coef[0]`, `cf[-1]=coef[-1]`).
    if sax == 0:
        A = dy[:, None] * dz[None, :]
        cf_lo, cf_hi = coef[0, :, :], coef[-1, :, :]
        sl_lo = (0, slice(None), slice(None)); sl_hi = (-1, slice(None), slice(None))
    elif sax == 1:
        A = dx[:, None] * dz[None, :]
        cf_lo, cf_hi = coef[:, 0, :], coef[:, -1, :]
        sl_lo = (slice(None), 0, slice(None)); sl_hi = (slice(None), -1, slice(None))
    else:
        A = dx[:, None] * dy[None, :]
        cf_lo, cf_hi = coef[:, :, 0], coef[:, :, -1]
        sl_lo = (slice(None), slice(None), 0); sl_hi = (slice(None), slice(None), -1)
    flux_lo = float(np.sum(cf_lo * F[sl_lo] * A))
    flux_hi = float(np.sum(cf_hi * F[sl_hi] * A))
    # Reverse-dir: inlet at the high-index face, outlet at low; forward: vice-versa.
    inlet_flux, outlet_flux = (flux_hi, flux_lo) if is_rev else (flux_lo, flux_hi)
    sl_out = sl_lo if is_rev else sl_hi
    # Degenerate / inconsistent outflow → leave to the projection's mean-zero
    # fallback rather than rescale by a wild factor.
    if abs(outlet_flux) < 1e-12 * (abs(inlet_flux) + 1e-30):
        return faces
    scale = inlet_flux / outlet_flux
    if not np.isfinite(scale) or scale <= 0.0:
        return faces
    F[sl_out] = F[sl_out] * scale
    return faces


# ──────────────────────────────────────────────────────────────────────────
# Per-cell χ_B participation field (Phase 1, 2026-05-04)
#
# Replaces the M4 0D scalar effective-area closure with a per-cell field
# in real (Nx, Ny, Nz) coords. χ_B(x) ∈ [0, 1] modulates BOTH:
#     h_vB_field *= χ_B          (zero source in pure ghost)
#     K_ffB      *= χ_B + floor  (zero diffusion path in pure ghost)
# Together they cut the ghost-B → active-B heat-leak path identified in the
# 2026-05-04 partial-B audit (vault/reports/3d-solver/2026-05-04-partial-b-
# ltne-audit-CN.md). Energy carried by the SIMPLE momentum solution is
# unaffected (eps_f, ρ_cp, advection face fluxes untouched).
#
# Two construction methods. Selectable via cfg['chi_B_method'].
#   - 'union_extrude'      Method A: streamwise extrusion of inlet ∪ outlet
#                          patches with cross-stream tanh ramp. Simple,
#                          works only for aligned partial-B.
#   - 'velocity_threshold' Method B (default): use the converged SIMPLE B
#                          velocity magnitude as the participation indicator,
#                          then dilate + smooth. Works for cross-flow with
#                          offset inlet/outlet patches (Shanghai case 1).
# ──────────────────────────────────────────────────────────────────────────


def _dilate_one_step_3d(arr):
    """Single-step 6-connected 3D max-dilation (no scipy dep)."""
    out = arr.copy()
    out[:-1] = np.maximum(out[:-1], arr[1:])
    out[1:]  = np.maximum(out[1:],  arr[:-1])
    out[:, :-1] = np.maximum(out[:, :-1], arr[:, 1:])
    out[:, 1:]  = np.maximum(out[:, 1:],  arr[:, :-1])
    out[:, :, :-1] = np.maximum(out[:, :, :-1], arr[:, :, 1:])
    out[:, :, 1:]  = np.maximum(out[:, :, 1:],  arr[:, :, :-1])
    return out


def _box_smooth_3d(arr, n_passes=2):
    """3-point box filter applied n_passes times along each of 3 axes.

    Edge cells use 2-point average. After n_passes, the discrete kernel
    approximates a Gaussian with σ ≈ sqrt(n_passes) cells; combined with
    binary input this gives a smooth tanh-like ramp at boundaries.
    """
    out = arr.copy()
    for _ in range(n_passes):
        # axis 0
        s = out.copy()
        if s.shape[0] >= 3:
            s[1:-1] = (out[:-2] + out[1:-1] + out[2:]) / 3.0
            s[0]    = (out[0]   + out[1])             / 2.0
            s[-1]   = (out[-1]  + out[-2])            / 2.0
        out = s
        # axis 1
        s = out.copy()
        if s.shape[1] >= 3:
            s[:, 1:-1] = (out[:, :-2] + out[:, 1:-1] + out[:, 2:]) / 3.0
            s[:, 0]    = (out[:, 0]   + out[:, 1])                 / 2.0
            s[:, -1]   = (out[:, -1]  + out[:, -2])                / 2.0
        out = s
        # axis 2
        s = out.copy()
        if s.shape[2] >= 3:
            s[:, :, 1:-1] = (out[:, :, :-2] + out[:, :, 1:-1] + out[:, :, 2:]) / 3.0
            s[:, :, 0]    = (out[:, :, 0]   + out[:, :, 1])                    / 2.0
            s[:, :, -1]   = (out[:, :, -1]  + out[:, :, -2])                   / 2.0
        out = s
    return out


def _build_chi_B_union_extrude(fB, dx_arr, dy_arr, dz_arr, shape, n_taper=3):
    """Method A: streamwise extrusion of (inlet ∪ outlet) patches in real coords.

    Patch boxes from fB cfg (in_ctr/in_w + in_z_ctr/in_z_w, same for out_*).
    Streamwise axis from fB['dir']:
        dir 0/1 → streamwise=x, cross=(y, z)
        dir 2/3 → streamwise=y, cross=(x, z)
        dir 4/5 → streamwise=z, cross=(x, y)
    Cross-stream tanh ramp via n_taper-pass box smoothing.

    Limitation: cross-flow with offset inlet/outlet patches creates two
    disconnected streamwise channels — the diagonal connecting corridor
    is NOT included. Use Method B (velocity_threshold) for such cases.
    """
    Nx, Ny, Nz = shape
    x_c = np.cumsum(dx_arr) - dx_arr / 2
    y_c = np.cumsum(dy_arr) - dy_arr / 2
    z_c = np.cumsum(dz_arr) - dz_arr / 2
    dir_B = int(fB['dir'])

    if dir_B in (0, 1):
        sw_axis = 0
        c1, c2 = y_c, z_c
    elif dir_B in (2, 3):
        sw_axis = 1
        c1, c2 = x_c, z_c
    else:
        sw_axis = 2
        c1, c2 = x_c, y_c

    eps_g = 1e-12
    in_lo_c1 = float(fB['in_ctr']) - float(fB['in_w']) / 2
    in_hi_c1 = float(fB['in_ctr']) + float(fB['in_w']) / 2
    out_lo_c1 = float(fB['out_ctr']) - float(fB['out_w']) / 2
    out_hi_c1 = float(fB['out_ctr']) + float(fB['out_w']) / 2
    in_lo_c2 = float(fB.get('in_z_ctr', c2.mean())) - float(fB.get('in_z_w', c2.max() - c2.min())) / 2
    in_hi_c2 = float(fB.get('in_z_ctr', c2.mean())) + float(fB.get('in_z_w', c2.max() - c2.min())) / 2
    out_lo_c2 = float(fB.get('out_z_ctr', c2.mean())) - float(fB.get('out_z_w', c2.max() - c2.min())) / 2
    out_hi_c2 = float(fB.get('out_z_ctr', c2.mean())) + float(fB.get('out_z_w', c2.max() - c2.min())) / 2

    in_c1 = (c1 >= in_lo_c1 - eps_g) & (c1 <= in_hi_c1 + eps_g)
    in_c2 = (c2 >= in_lo_c2 - eps_g) & (c2 <= in_hi_c2 + eps_g)
    out_c1 = (c1 >= out_lo_c1 - eps_g) & (c1 <= out_hi_c1 + eps_g)
    out_c2 = (c2 >= out_lo_c2 - eps_g) & (c2 <= out_hi_c2 + eps_g)

    in_2d = np.outer(in_c1, in_c2).astype(np.float64)
    out_2d = np.outer(out_c1, out_c2).astype(np.float64)
    union_2d = np.maximum(in_2d, out_2d)

    if sw_axis == 0:
        chi_3d = np.broadcast_to(union_2d[None, :, :], shape).copy()
    elif sw_axis == 1:
        chi_3d = np.broadcast_to(union_2d[:, None, :], shape).copy()
    else:
        chi_3d = np.broadcast_to(union_2d[:, :, None], shape).copy()

    if n_taper > 0:
        chi_3d = _box_smooth_3d(chi_3d, n_passes=n_taper)
    return np.clip(chi_3d, 0.0, 1.0)


def _build_chi_B_mass_flux_threshold(sB, axis_map_B, shape,
                                      threshold_frac=0.05,
                                      n_dilate=2, n_smooth=1,
                                      ref_mode='p75'):
    """Method H8: per-cell χ_B from actual mass-flux throughput.

    For each cell, compute the mass throughput as the **maximum** of the
    six face mass-fluxes |ρ·u_face·A|. A cell is 'participating' if its
    throughput > `threshold_frac` · ref_throughput.

    `ref_mode` selects the reference throughput value:
        'p75'  — 75th percentile (default, stable across grids)
        'p90'  — 90th percentile (closer to max, less robust)
        'p50'  — median (most robust, may be too low for narrow corridors)
        'max'  — max throughput (legacy; sensitive to extreme cells)
        'mean' — arithmetic mean (no robustness to skewed distributions)

    Percentile-based ref (p75 default) gives grid-independent sweet spot:
    median throughput in the active corridor scales with mass conservation,
    not with grid resolution. The factor 'threshold_frac' then represents
    the fraction of typical-flow throughput that defines the cutoff.

    Returns chi_B in REAL (Nx, Ny, Nz) coordinates.
    """
    Nx, Ny, Nz = shape
    u_sol = sB.u; v_sol = sB.v; w_sol = sB.w
    rho_sol = sB.rho_field
    dx_sol = sB.dx; dy_sol = sB.dy; dz_sol = sB.dz
    Nx_s, Ny_s, Nz_s = rho_sol.shape

    # Per-cell face-area arrays (broadcast)
    Ax_3d = np.broadcast_to(
        (dy_sol[None, :, None] * dz_sol[None, None, :]), rho_sol.shape)
    Ay_3d = np.broadcast_to(
        (dx_sol[:, None, None] * dz_sol[None, None, :]), rho_sol.shape)
    Az_3d = np.broadcast_to(
        (dx_sol[:, None, None] * dy_sol[None, :, None]), rho_sol.shape)

    # Face-cell ρ (linear interpolation between adjacent cells)
    if Nx_s > 1:
        rho_xface = 0.5 * (rho_sol[:-1, :, :] + rho_sol[1:, :, :])
    if Ny_s > 1:
        rho_yface = 0.5 * (rho_sol[:, :-1, :] + rho_sol[:, 1:, :])
    if Nz_s > 1:
        rho_zface = 0.5 * (rho_sol[:, :, :-1] + rho_sol[:, :, 1:])

    # |Mass flux| at each face of each cell, kg/s
    # u_sol shape (Nx_s+1, Ny_s, Nz_s). u_sol[i, :, :] is the face between
    # cell i-1 and cell i.
    flux_w = np.abs(rho_sol * u_sol[:-1, :, :]) * Ax_3d  # west face per cell
    flux_e = np.abs(rho_sol * u_sol[1:, :, :])  * Ax_3d  # east face per cell
    if Nx_s > 1:
        flux_w[1:, :, :] = np.abs(rho_xface * u_sol[1:-1, :, :]) * Ax_3d[1:, :, :]
        flux_e[:-1, :, :] = np.abs(rho_xface * u_sol[1:-1, :, :]) * Ax_3d[:-1, :, :]

    flux_s = np.abs(rho_sol * v_sol[:, :-1, :]) * Ay_3d
    flux_n = np.abs(rho_sol * v_sol[:, 1:, :])  * Ay_3d
    if Ny_s > 1:
        flux_s[:, 1:, :] = np.abs(rho_yface * v_sol[:, 1:-1, :]) * Ay_3d[:, 1:, :]
        flux_n[:, :-1, :] = np.abs(rho_yface * v_sol[:, 1:-1, :]) * Ay_3d[:, :-1, :]

    flux_b = np.abs(rho_sol * w_sol[:, :, :-1]) * Az_3d
    flux_t = np.abs(rho_sol * w_sol[:, :, 1:])  * Az_3d
    if Nz_s > 1:
        flux_b[:, :, 1:] = np.abs(rho_zface * w_sol[:, :, 1:-1]) * Az_3d[:, :, 1:]
        flux_t[:, :, :-1] = np.abs(rho_zface * w_sol[:, :, 1:-1]) * Az_3d[:, :, :-1]

    # Per-cell mass throughput = max of 6 face fluxes
    throughput_solver = np.maximum.reduce([
        flux_w, flux_e, flux_s, flux_n, flux_b, flux_t])

    m_max = float(np.max(throughput_solver))
    if m_max < 1e-30:
        return np.ones(shape, dtype=np.float64)

    # Reference throughput — percentile-based for grid-independence.
    if ref_mode == 'p50':
        m_ref = float(np.percentile(throughput_solver, 50))
    elif ref_mode == 'p75':
        m_ref = float(np.percentile(throughput_solver, 75))
    elif ref_mode == 'p90':
        m_ref = float(np.percentile(throughput_solver, 90))
    elif ref_mode == 'mean':
        m_ref = float(np.mean(throughput_solver))
    else:  # 'max' (legacy)
        m_ref = m_max
    if m_ref < 1e-30:
        m_ref = m_max   # fallback

    chi_binary_solver = (throughput_solver > threshold_frac * m_ref).astype(np.float64)

    # Transpose solver-coord chi to real-coord chi using axis_map_B perm
    perm = axis_map_B['solver_to_real_perm']
    chi_3d = np.ascontiguousarray(chi_binary_solver.transpose(perm))
    # approach-(a) reverse convention: the solver is direction-agnostic, so the
    # solver-coord χ is identical for ±stream; the real-coord χ for a reverse
    # dir must be spatially flipped along the real stream axis to track the
    # mirrored flow corridor (same flip the velocity transforms apply).
    if axis_map_B.get('is_reverse'):
        chi_3d = np.ascontiguousarray(
            np.flip(chi_3d, axis=axis_map_B['stream_real_axis']))
    if chi_3d.shape != shape:
        # Fallback: identity if shape mismatch (shouldn't happen)
        chi_3d = np.ones(shape, dtype=np.float64)

    for _ in range(int(n_dilate)):
        chi_3d = _dilate_one_step_3d(chi_3d)
    if n_smooth > 0:
        chi_3d = _box_smooth_3d(chi_3d, n_passes=int(n_smooth))
    return np.clip(chi_3d, 0.0, 1.0)


def _build_chi_B_velocity_threshold(ucB, vcB, wcB,
                                     threshold_frac=0.5,
                                     u_ref_mode='inlet',
                                     u_inlet=None,
                                     n_dilate=3, n_smooth=2):
    """Method B: per-cell χ_B from the converged SIMPLE B velocity field.

    A cell is 'participating' if |v_cell| > threshold_frac · u_ref.

    `u_ref_mode` selects the reference velocity:
        'inlet'    — u_ref = u_inlet (passed param). Stable, recommended.
        'p50'      — u_ref = median(|v|) (50th percentile). Robust.
        'p90'      — u_ref = 90th percentile. Closer to max but resistant
                     to pathological hot cells.
        'max'      — u_ref = max(|v|). Original behavior; sensitive to
                     porous-medium pressure-driven hotspots.

    Then: dilate by n_dilate cells (6-connected, Chebyshev radius 1 per step)
    to capture the diffusion-affected boundary layer beyond pure advection,
    then box-smooth n_smooth times for a tanh-like ramp at the boundary.

    Inputs are cell-center velocity components in REAL (Nx, Ny, Nz) coords —
    same arrays already produced by `_solver_velocity_to_real`.
    """
    vmag = np.sqrt(ucB ** 2 + vcB ** 2 + wcB ** 2)
    v_max = float(np.max(vmag))
    if v_max < 1e-30:
        return np.ones_like(vmag, dtype=np.float64)
    if u_ref_mode == 'inlet':
        u_ref = float(u_inlet) if (u_inlet is not None and u_inlet > 0) else v_max
    elif u_ref_mode == 'p50':
        u_ref = float(np.median(vmag))
    elif u_ref_mode == 'p90':
        u_ref = float(np.percentile(vmag, 90))
    else:  # 'max'
        u_ref = v_max
    chi_binary = (vmag > threshold_frac * u_ref).astype(np.float64)
    chi_3d = chi_binary
    for _ in range(int(n_dilate)):
        chi_3d = _dilate_one_step_3d(chi_3d)
    if n_smooth > 0:
        chi_3d = _box_smooth_3d(chi_3d, n_passes=int(n_smooth))
    return np.clip(chi_3d, 0.0, 1.0)
