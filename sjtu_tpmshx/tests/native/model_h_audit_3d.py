"""Read-only model-h residuals for the returned native state."""
import numpy as np

from sjtu_tpmshx.tests.native.thermal_face_audit import _model_h, limited_face_increment
from sjtu_tpmshx.tests.native.thermal_face_audit import _sou_field_cons

_Q_FLOOR_W = 1.0


def _model_h_faces(T, mass, coefficients, direction, Tin, ifrac, dx=None, dy=None, dz=None):
    """Shared Picard faces: flux = capacity*T_up + deferred.

    Freeze once per sweep, including both RB colours. Retain the temperature
    minmod stencil and its edge exclusions, integrating cp at its face T.
    Boundary backflow outside the inlet retains numerical self-extrapolation;
    the ledger must identify that missing physical inflow state.
    """
    a, b, c, origin, _ = coefficients
    capacity = (np.empty_like(mass[0]), np.empty_like(mass[1]), np.empty_like(mass[2]))
    deferred = (np.empty_like(mass[0]), np.empty_like(mass[1]), np.empty_like(mass[2]))
    for axis in range(3):
        for i in range(mass[axis].shape[0]):
            for j in range(mass[axis].shape[1]):
                for k in range(mass[axis].shape[2]):
                    face = (i, j, k)
                    pos = face[axis]
                    count = T.shape[axis]
                    m = mass[axis][face]
                    u = pos - 1 if m >= 0.0 else pos
                    u = min(max(u, 0), count - 1)
                    up = (u, j, k) if axis == 0 else ((i, u, k) if axis == 1 else (i, j, u))
                    t = T[up]
                    inc = 0.0
                    if 0 < pos < count and 0 < u < count - 1:
                        prev = (u-1, j, k) if axis == 0 else ((i, u-1, k) if axis == 1 else (i, j, u-1))
                        nxt = (u+1, j, k) if axis == 0 else ((i, u+1, k) if axis == 1 else (i, j, u+1))
                        dm = dp = 1.0
                        half = 0.5
                        if dx is not None:
                            width = (dx, dy, dz)[axis]
                            dm = 0.5*(width[u-1]+width[u])
                            dp = 0.5*(width[u]+width[u+1])
                            half = 0.5*width[u]
                        inc = limited_face_increment(T[prev], t, T[nxt], dm, dp,
                                                     half if m >= 0.0 else -half)
                    if axis == direction // 2 and pos == (0 if direction % 2 == 0 else count):
                        patch = (j, k) if axis == 0 else ((i, k) if axis == 1 else (i, j))
                        inward = m if direction % 2 == 0 else -m
                        if ifrac[patch] > 0.0 and inward > 0.0:
                            t = Tin[patch]
                    x = t - origin
                    cp = a + b*x + c*x*x
                    capacity[axis][face] = m * cp
                    deferred[axis][face] = m * (_model_h(t+inc, coefficients) - cp*t)
    return capacity, deferred


def _face_divergence(faces):
    return (faces[0][1:] - faces[0][:-1]
            + faces[1][:, 1:] - faces[1][:, :-1]
            + faces[2][:, :, 1:] - faces[2][:, :, :-1])


def _conservation_residual_sum(T, Ts, uf, vf, wf, eps_f, K, rcp, hv,
                               dx, dy, dz, dir_code, Tin, ifrac, mms_source,
                               inlet_flux=None, model_mass=None, model_cp=None,
                               return_field=False):
    """Full-CV conservative temperature-equation residual for one fluid phase (B-plan B2).

    Evaluates, on the CONVERGED field, the residual of the *conservative*
    discrete energy equation per cell — using the exact same shared face
    fluxes, harmonic-mean diffusion and hybrid-upwind coefficients as the
    conservative kernel, with the (F_e−F_w+…) net-out term in a_P:

        r[c] = a_P·T_c − Σ a_nb·T_nb − h_v·V·Ts

    All actual cells, including both end layers, are included. The physical
    inlet has Tin and half-cell diffusion; other exterior diffusion is zero.
    Returns (sum residual, full-volume solid exchange, max cell residual).
    With model_mass, rebuild nonlinear model-h fluxes at the returned T.
    Otherwise this certifies the original capacity-temperature discretisation.
    """
    Nx, Ny, Nz = T.shape
    Ax = (dy[None, :, None] * dz[None, None, :])
    Ay = (dx[:, None, None] * dz[None, None, :])
    Az = (dx[:, None, None] * dy[None, :, None])
    vol = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]

    # Kernel interpolates eps and rho*cp separately, then multiplies them.
    face_coefs = []
    for axis in range(3):
        ef = np.moveaxis(eps_f, axis, 0)
        rc = np.moveaxis(rcp, axis, 0)
        cf = np.empty((ef.shape[0] + 1, *ef.shape[1:]))
        cf[1:-1] = 0.25 * (ef[:-1] + ef[1:]) * (rc[:-1] + rc[1:])
        cf[0] = ef[0] * rc[0]; cf[-1] = ef[-1] * rc[-1]
        face_coefs.append(np.moveaxis(cf, 0, axis))
    cf_x, cf_y, cf_z = face_coefs
    Fx = cf_x * uf * np.broadcast_to(Ax, uf.shape)   # (Nx+1,Ny,Nz)
    Fy = cf_y * vf * np.broadcast_to(Ay, vf.shape)
    Fz = cf_z * wf * np.broadcast_to(Az, wf.shape)
    if inlet_flux is not None:
        inlet_face = np.moveaxis((Fx, Fy, Fz)[dir_code // 2], dir_code // 2, 0)[
            0 if dir_code % 2 == 0 else -1]
        inlet_face[:] = np.where(
            ifrac > 0.0, inlet_flux * (1.0 if dir_code % 2 == 0 else -1.0), inlet_face)
    if model_mass is not None:
        (Fx, Fy, Fz), deferred = _model_h_faces(
            T, model_mass, model_cp, dir_code, Tin, ifrac, dx, dy, dz)
    Fe = Fx[1:]; Fw = Fx[:-1]; Fn = Fy[:, 1:]; Fs = Fy[:, :-1]
    Ft = Fz[:, :, 1:]; Fb = Fz[:, :, :-1]
    net_out = (Fe - Fw) + (Fn - Fs) + (Ft - Fb)

    # Two physical half-cell thermal resistances in series on every shared face.
    dE = np.zeros_like(T); dW = np.zeros_like(T)
    dN = np.zeros_like(T); dS = np.zeros_like(T)
    dT_ = np.zeros_like(T); dB = np.zeros_like(T)
    for axis, (width, area, forward, backward) in enumerate((
            (dx, Ax, dE, dW), (dy, Ay, dN, dS), (dz, Az, dT_, dB))):
        lo = [slice(None)] * 3; hi = lo.copy()
        lo[axis] = slice(None, -1); hi[axis] = slice(1, None)
        lo, hi = tuple(lo), tuple(hi)
        shape = [1, 1, 1]; shape[axis] = -1
        kl, kr = K[lo], K[hi]
        denominator = .5*width[:-1].reshape(shape)*kr + .5*width[1:].reshape(shape)*kl
        conductance = np.zeros_like(kl)
        np.divide(kl*kr, denominator, out=conductance, where=(kl > 0.) & (kr > 0.))
        shared = conductance * np.broadcast_to(area, T.shape)[lo]
        forward[lo] = shared; backward[hi] = shared

    aE = dE + np.maximum(-Fe, 0.0); aW = dW + np.maximum(Fw, 0.0)
    aN = dN + np.maximum(-Fn, 0.0); aS = dS + np.maximum(Fs, 0.0)
    aT = dT_ + np.maximum(-Ft, 0.0); aB = dB + np.maximum(Fb, 0.0)
    aP = aE + aW + aN + aS + aT + aB + net_out + hv * vol

    # Neighbour T with boundary = self (kernel convention).
    TE = T.copy(); TE[:-1] = T[1:]
    TW = T.copy(); TW[1:] = T[:-1]
    TN = T.copy(); TN[:, :-1] = T[:, 1:]
    TS = T.copy(); TS[:, 1:] = T[:, :-1]
    TT = T.copy(); TT[:, :, :-1] = T[:, :, 1:]
    TB = T.copy(); TB[:, :, 1:] = T[:, :, :-1]
    r = (aP * T - aE * TE - aW * TW - aN * TN - aS * TS - aT * TT - aB * TB
         - hv * vol * Ts)
    # Subtract the conservative HO deferred source so this measures the TRUE
    # residual of the equation the kernel actually solves (FO implicit + sou).
    # The sou itself telescopes, so conservation is preserved; r → 0 at
    # convergence. (For pure-upwind it is identically 0 ⇒ no-op.)
    r = (r + _face_divergence(deferred) if model_mass is not None
         else r - _sou_field_cons(T, Fx, Fy, Fz, dx, dy, dz))

    axis = dir_code // 2
    sl = [slice(None)] * 3
    sl[axis] = 0 if dir_code % 2 == 0 else -1
    sl = tuple(sl)
    area = np.broadcast_to((Ax, Ay, Az)[axis], T.shape)[sl]
    dn = (dx, dy, dz)[axis][0 if dir_code % 2 == 0 else -1]
    Din = 2.0 * K[sl] * area * ifrac / dn
    incoming = (np.maximum(Fw, 0.0), np.maximum(-Fe, 0.0),
                np.maximum(Fs, 0.0), np.maximum(-Fn, 0.0),
                np.maximum(Fb, 0.0), np.maximum(-Ft, 0.0))[dir_code][sl]
    r[sl] += (Din + np.where(ifrac > 0.0, incoming, 0.0)) * (T[sl] - Tin)
    r -= mms_source * vol
    src = hv * vol * (Ts - T)
    if return_field:
        return r, src, Din * (Tin - T[sl])
    return float(np.sum(r)), float(np.sum(src)), float(np.max(np.abs(r)))


def _model_h_balance(temperatures, Ts, masses, coefficients, directions, inlets,
                     masks, conductivities, Kss, exchanges, porosities, sources,
                     solid_source, dx, dy, dz):
    """Last returned thermal state; no EOS, flow correction or physical PASS."""
    volume = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]
    zeros = np.zeros_like(Ts)
    zero_faces = tuple(np.zeros_like(f) for f in masses[0])
    result = dict(reference_K=coefficients[0][4], cell_count=int(Ts.size),
                  full_volume_m3=float(volume.sum()),
                  mass_source='completed SIMPLE raw faces before capacity balance/MAC',
                  thermal_state='last returned temperatures; nonlinear model h and temperature SOU',
                  sides={}, _native_faces={})
    from sjtu_tpmshx.solvers.physical_ledger import FACE_NAMES, boundary_zeros, heat_ledger
    residuals, diffusion = [], []
    exchange_fields = []
    for side, T, mass, coeff, direction, Tin, mask, K, hv, eps, source in zip(
            ('A', 'B'), temperatures, masses, coefficients, directions, inlets,
            masks, conductivities, exchanges, porosities, sources):
        capacity, deferred = _model_h_faces(T, mass, coeff, direction, Tin, mask, dx, dy, dz)
        r, exchange, inlet_diffusion = _conservation_residual_sum(
            T, Ts, *zero_faces, eps, K, zeros, hv, dx, dy, dz, direction, Tin,
            mask, source, model_mass=mass, model_cp=coeff, return_field=True)
        faces = {}
        native_faces = {}
        for axis in range(3):
            for end, sign in ((0, -1), (-1, 1)):
                face_T = np.take(T, end, axis=axis)
                outward_mass = sign * np.take(mass[axis], end, axis=axis)
                inlet = axis == direction // 2 and end == (0 if direction % 2 == 0 else -1)
                patch = mask > 0 if inlet else np.zeros_like(face_T, dtype=bool)
                inflow = outward_mass < 0.0
                up_T = np.where(patch & inflow, Tin if inlet else face_T, face_T)
                energy = sign * (np.take(capacity[axis], end, axis=axis) * up_T
                                 + np.take(deferred[axis], end, axis=axis))
                native_faces['xyz'[axis] + ('-' if end == 0 else '+')] = energy.copy()
                unknown = inflow & ~patch
                faces['xyz'[axis] + ('-' if end == 0 else '+')] = dict(
                    outward_mass_kg_s=float(outward_mass.sum()),
                    outward_model_h_W=float(energy.sum()),
                    non_inlet_inward_mass_kg_s=float(-outward_mass[unknown].sum()),
                    unknown_inflow_count=int(unknown.sum()),
                    inlet_reverse_outward_mass_kg_s=float(outward_mass[patch & ~inflow].sum()))
        result['_native_faces'][side] = native_faces
        diff = boundary_zeros(T.shape)
        diff[FACE_NAMES[direction]] = -inlet_diffusion
        diffusion.append(diff)
        complete = all(f['unknown_inflow_count'] == 0 for f in faces.values())
        convective_inward = -sum(f['outward_model_h_W'] for f in faces.values())
        diffusion_inward = float(inlet_diffusion.sum())
        result['sides'][side] = dict(
            faces=faces, physical_boundary_complete=complete,
            model_cp_coefficients=list(coeff),
            temperature_range_K=[float(T.min()), float(T.max())],
            net_outward_mass_kg_s=sum(f['outward_mass_kg_s'] for f in faces.values()),
            convective_inward_W=convective_inward,
            inlet_diffusion_inward_W=diffusion_inward,
            numerical_external_inward_W=convective_inward+diffusion_inward,
            physical_external_inward_W=convective_inward+diffusion_inward if complete else None,
            fluid_solid_exchange_to_fluid_W=float(exchange.sum()),
            explicit_source_W=float((source*volume).sum()),
            residual_sum_W=float(r.sum()), residual_max_abs_W=float(np.max(np.abs(r))),
            strict_normalization_W=max(abs(float(exchange.sum())), _Q_FLOOR_W))
        residuals.append(r)
        exchange_fields.append(exchange)
    # Reuse the existing nonuniform conduction operator for the solid, with
    # zero advection/inlet area; exchange cancels the two fluid equations.
    rsolid, _, _ = _conservation_residual_sum(
        Ts, Ts, *zero_faces, porosities[0], Kss, zeros, zeros, dx, dy, dz, 0,
        Ts[0], np.zeros_like(Ts[0]), solid_source, return_field=True)
    rsolid += exchange_fields[0] + exchange_fields[1]
    all_residual = residuals[0] + residuals[1] + rsolid
    external = sum(s['numerical_external_inward_W'] for s in result['sides'].values())
    explicit = float(((sources[0]+sources[1]+solid_source)*volume).sum())
    complete = all(s['physical_boundary_complete'] for s in result['sides'].values())
    result.update(
        _physical_ledger=heat_ledger(
            (-residuals[0], -residuals[1], -rsolid),
            tuple(result['_native_faces'][side] for side in ('A', 'B')), diffusion,
            tuple(float((source*volume).sum()) for source in (*sources, solid_source)), complete),
        physical_boundary_complete=complete,
        numerical_external_inward_W=external,
        physical_external_inward_W=external if complete else None,
        explicit_source_W=explicit, solid_external_diffusion_W=0.0,
        solid_residual_sum_W=float(rsolid.sum()),
        solid_residual_max_abs_W=float(np.max(np.abs(rsolid))),
        full_residual_sum_W=float(all_residual.sum()),
        telescoping_error_W=float(all_residual.sum())+external+explicit,
        qualification='No physical acceptance inferred. Non-inlet inflow uses numerical self-extrapolation; its external h is unspecified.')
    return result
