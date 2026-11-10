"""Keep independent coordinate references for native full-driver tests."""
from __future__ import annotations
import numpy as np


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

    Returns independently writable (uf_real, vf_real, wf_real) of shapes:
      uf_real : (Nx+1, Ny, Nz)  — face velocities at real x-faces (+x signed)
      vf_real : (Nx, Ny+1, Nz)  — face velocities at real y-faces (+y signed)
      wf_real : (Nx, Ny, Nz+1)  — face velocities at real z-faces (+z signed)

    The stream component (solver's y-axis v) gets sign-flipped if is_reverse,
    because for reverse-dir fluids SIMPLE's local +y is the real -stream_axis.

    Native full-driver tests use these faces as an independent mapping reference.
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
    # Thermal outflow balancing must not modify the completed SIMPLE state.
    u_real = u_sol.transpose(perm).copy(order='C')
    v_real = v_sol.transpose(perm).copy(order='C')
    w_real = w_sol.transpose(perm).copy(order='C')

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
