"""Pure numpy helpers extracted verbatim from stages_3d.py (Phase 3 god-file
split). No module-global / solver-import dependencies — index/face/slice math,
staggered<->real remap and stream-outflow balance. Current preparation and numerical backends import these helpers
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
