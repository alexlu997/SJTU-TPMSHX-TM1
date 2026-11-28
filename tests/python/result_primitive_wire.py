"""Use the published result C ABI in raw primitive regression tests."""
import ctypes as ct

import numpy as np

from tm1.cpp_interface import _native_result as core

_D = ct.c_double
_AP = ct.POINTER(core._Array)
_DP = ct.POINTER(_D)


def _call(name, argtypes, *arguments):
    return core.call(f'tpmshx_result_{name}_v1', argtypes, *arguments)


def _packed(values):
    owners = [core.array(value) for value in values]
    return owners, (core._Array * len(owners))(*(item.raw for item in owners))


def boundary_mass(faces, dimension):
    owners, packed = _packed(faces)
    output = (ct.c_double * 2)()
    _call('boundary_mass_' + str(dimension) + 'd', [_AP, _DP], packed, output)
    return tuple(output)


def solid_mass(epsilon, density, widths):
    source, factor = core.array(epsilon), core.array(density)
    grid = [core.array(value) for value in widths]
    output = ct.c_double()
    _call('solid_mass_' + str(len(widths)) + 'd', [_AP, _AP] + [_AP] * len(grid) + [_DP],
          ct.byref(source.raw), ct.byref(factor.raw), *(ct.byref(item.raw) for item in grid), ct.byref(output))
    return output.value


def duty_magnitude(duty):
    output = ct.c_double()
    _call('duty_magnitude', [ct.c_double, _DP], duty, ct.byref(output))
    return output.value

class _Norms(ct.Structure):
    _fields_ = [('signed_sum', _D), ('l1', _D), ('cell_max', _D), ('cell_count', core._Size)]


class _Planes(ct.Structure):
    _fields_ = [('values', _D * 6), ('total', _D)]


def norm_record(value):
    return dict(signed_sum=value.signed_sum, l1=value.l1,
                cell_max=value.cell_max, cell_count=value.cell_count)


def norms(value):
    owner, output = core.array(value), _Norms()
    _call('balance_norms', [_AP, ct.POINTER(_Norms)], ct.byref(owner.raw), ct.byref(output))
    return norm_record(output)


def plane_sums(planes):
    owners = [core.array(plane) for plane in planes]
    inputs = (core._Array * len(owners))(*(owner.raw for owner in owners))
    output = _Planes()
    _call('balance_planes', [_AP, core._Size, ct.POINTER(_Planes)], inputs, len(owners), ct.byref(output))
    return output


def _enthalpy_balance_2d(T_field, uc, vc, rho_cp_field, dir_code,
                          dx_arr, dy_arr, inlet_mask=None, outlet_mask=None, *,
                          eps_side=None, T_in=None):
    """Inlet-capacity-based duty for the temperature formulation.

    Uses the inlet plane ρ·|u|·A·mask as ṁ·cp reference so the returned Q
    does not include a heat-duty contribution from unequal inlet/outlet mass
    flows. This diagnostic does not replace the independent mass-conservation
    check or certify convergence.

    Positive = fluid gives up heat (T_in > T_out).
    Optional 1D masks (length = cross-axis) gate the integral to partial
    inlet / outlet pipes; missing masks default to full face.
    ``T_in`` supplies the physical inlet temperature when the first stored
    row is a real control volume. Omit it for independent boundary-field data.

    ``eps_side`` (N1 fix, 2026-07-07): the PER-SIDE void fraction (scalar or
    2D field). Velocities are interstitial, so the physical face mass flux is
    ε_side·ρ·|u|·A — without it the duty over-reads by 1/ε_side (verified
    2.7086 vs 1/ε_A = 2.7147 against the independent Σh_vB·(Ts−Tb)·dA
    integral on the golden air-air case). None keeps the legacy ε-less
    arithmetic for callers that pre-scale externally.

    """
    if dir_code in (0, 1):
        i_in, i_out = (0, -1) if dir_code == 0 else (-1, 0)
        A_cell = dy_arr
        n_cross = T_field.shape[1]
        m_in_arr  = (np.asarray(inlet_mask,  dtype=np.float64)
                     if inlet_mask  is not None else np.ones(n_cross))
        m_out_arr = (np.asarray(outlet_mask, dtype=np.float64)
                     if outlet_mask is not None else np.ones(n_cross))
        u_in_face, u_out_face = uc[i_in, :], uc[i_out, :]
        rho_cp_in, rho_cp_out = rho_cp_field[i_in, :], rho_cp_field[i_out, :]
        T_in_face, T_out_face = T_field[i_in, :], T_field[i_out, :]
        if eps_side is None:
            eps_in = eps_out = 1.0
        elif np.ndim(eps_side) == 0:
            eps_in = eps_out = float(eps_side)
        else:
            eps_in, eps_out = eps_side[i_in, :], eps_side[i_out, :]
    else:
        j_in, j_out = (0, -1) if dir_code == 2 else (-1, 0)
        A_cell = dx_arr
        n_cross = T_field.shape[0]
        m_in_arr  = (np.asarray(inlet_mask,  dtype=np.float64)
                     if inlet_mask  is not None else np.ones(n_cross))
        m_out_arr = (np.asarray(outlet_mask, dtype=np.float64)
                     if outlet_mask is not None else np.ones(n_cross))
        u_in_face, u_out_face = vc[:, j_in], vc[:, j_out]
        rho_cp_in, rho_cp_out = rho_cp_field[:, j_in], rho_cp_field[:, j_out]
        T_in_face, T_out_face = T_field[:, j_in], T_field[:, j_out]
        if eps_side is None:
            eps_in = eps_out = 1.0
        elif np.ndim(eps_side) == 0:
            eps_in = eps_out = float(eps_side)
        else:
            eps_in, eps_out = eps_side[:, j_in], eps_side[:, j_out]

    if T_in is not None:
        T_in_face = np.asarray(T_in, dtype=np.float64)

    inlet_owners, inlet = _packed((eps_in, rho_cp_in, u_in_face, A_cell, m_in_arr))
    outlet_owners, outlet = _packed((eps_out, rho_cp_out, u_out_face, A_cell, m_out_arr))
    tin, tout = core.array(T_in_face), core.array(T_out_face)
    output = _D()
    _call('capacity_duty', [_AP, _AP, _AP, _AP, _DP], inlet, outlet,
          ct.byref(tin.raw), ct.byref(tout.raw), ct.byref(output))
    return output.value


def _outlet_temperature_2d(temperature, mass_flux, direction, outlet_fraction):
    """Raw outlet-cell T weighted by positive outward mass, in K.

    Outlet zero-gradient uses the adjacent cell T. Face mass already includes
    area; geometry only selects the real opening. Keep signed inputs intact
    for the separate full-boundary mass and energy checks.
    """
    mx, my = mass_flux
    if direction == 0:
        face_T, outward = temperature[-1, :], mx[-1, :]
    elif direction == 1:
        face_T, outward = temperature[0, :], mx[0, :]
    elif direction == 2:
        face_T, outward = temperature[:, -1], my[:, -1]
    else:
        face_T, outward = temperature[:, 0], my[:, 0]
    sources = [core.array(value) for value in (face_T, outward, np.asarray(outlet_fraction))]
    output = _D()
    _call('outlet_temperature_2d', [_AP, _AP, _AP, core._UInt, _DP],
          *(ct.byref(item.raw) for item in sources), int(direction not in (0, 2)), ct.byref(output))
    return output.value


def _boundary_enthalpy_duty(h, h_in, mass_flux):
    """Heat lost by a stream from its six boundary-face enthalpy flows."""
    Fx, Fy, Fz = mass_flux
    h_owners, enthalpy = _packed((h[0], h[-1], h[:, 0], h[:, -1], h[:, :, 0], h[:, :, -1]))
    flow_owners, flow = _packed((Fx[0], Fx[-1], Fy[:, 0], Fy[:, -1], Fz[:, :, 0], Fz[:, :, -1]))
    output = _D()
    _call('boundary_enthalpy_duty', [_AP, _AP, _D, _DP],
          enthalpy, flow, core.scalar(h_in), ct.byref(output))
    return output.value
