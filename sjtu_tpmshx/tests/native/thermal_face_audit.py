"""Read-only face arithmetic for independent native thermal audits."""
import numpy as np


def _model_h(T, coefficients):
    a, b, c, origin, reference = coefficients
    x = T - origin
    x0 = reference - origin
    return a*(x-x0) + 0.5*b*(x*x-x0*x0) + c/3.0*(x*x*x-x0*x0*x0)


def minmod(gu, gd):
    """Return the smaller same-sign slope, or zero at a local extremum."""
    if gu * gd > 0:
        value = min(abs(gu), abs(gd))
        return -value if gu < 0 else value
    return 0.0


def limited_face_increment(tm, t0, tp, dm, dp, offset):
    """Limited physical gradient times the signed centre-to-face distance."""
    return minmod((t0 - tm) / dm, (tp - t0) / dp) * offset


def _sou_face_x_cons(T, i, j, k, Nx, Fw, Fe, widths=None, one_sided=True):
    """Shared-face minmod reconstruction using physical centre distances."""
    result = 0.0
    for face, flux, sign in ((i, Fw, 1.0), (i+1, Fe, -1.0)):
        up = face-1 if flux >= 0.0 else face
        if 0 < face < Nx and Nx >= 3 and (one_sided or 0 < up < Nx-1):
            mid = min(max(up, 1), Nx-2)
            dm = 1.0 if widths is None else 0.5*(widths[mid-1]+widths[mid])
            dp = 1.0 if widths is None else 0.5*(widths[mid]+widths[mid+1])
            half = 0.5 if widths is None else 0.5*widths[up]
            inc = limited_face_increment(T[mid-1, j, k], T[mid, j, k], T[mid+1, j, k],
                                         dm, dp, half if flux >= 0.0 else -half)
            result += sign*flux*inc
    return result


def _sou_face_y_cons(T, i, j, k, Ny, Fs, Fn, widths=None, one_sided=True):
    """Shared-face minmod reconstruction using physical centre distances."""
    result = 0.0
    for face, flux, sign in ((j, Fs, 1.0), (j+1, Fn, -1.0)):
        up = face-1 if flux >= 0.0 else face
        if 0 < face < Ny and Ny >= 3 and (one_sided or 0 < up < Ny-1):
            mid = min(max(up, 1), Ny-2)
            dm = 1.0 if widths is None else 0.5*(widths[mid-1]+widths[mid])
            dp = 1.0 if widths is None else 0.5*(widths[mid]+widths[mid+1])
            half = 0.5 if widths is None else 0.5*widths[up]
            inc = limited_face_increment(T[i, mid-1, k], T[i, mid, k], T[i, mid+1, k],
                                         dm, dp, half if flux >= 0.0 else -half)
            result += sign*flux*inc
    return result


def _sou_face_z_cons(T, i, j, k, Nz, Fb, Ft, widths=None, one_sided=True):
    """Shared-face minmod reconstruction using physical centre distances."""
    result = 0.0
    for face, flux, sign in ((k, Fb, 1.0), (k+1, Ft, -1.0)):
        up = face-1 if flux >= 0.0 else face
        if 0 < face < Nz and Nz >= 3 and (one_sided or 0 < up < Nz-1):
            mid = min(max(up, 1), Nz-2)
            dm = 1.0 if widths is None else 0.5*(widths[mid-1]+widths[mid])
            dp = 1.0 if widths is None else 0.5*(widths[mid]+widths[mid+1])
            half = 0.5 if widths is None else 0.5*widths[up]
            inc = limited_face_increment(T[i, j, mid-1], T[i, j, mid], T[i, j, mid+1],
                                         dm, dp, half if flux >= 0.0 else -half)
            result += sign*flux*inc
    return result


def _sou_field_cons(T, Fx, Fy, Fz, dx=None, dy=None, dz=None):
    """Use the same shared physical face reconstruction as the sweep."""
    Nx, Ny, Nz = T.shape
    sou = np.zeros_like(T)
    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                sou[i, j, k] = (
                    _sou_face_x_cons(T, i, j, k, Nx, Fx[i, j, k], Fx[i+1, j, k], dx)
                    + _sou_face_y_cons(T, i, j, k, Ny, Fy[i, j, k], Fy[i, j+1, k], dy)
                    + _sou_face_z_cons(T, i, j, k, Nz, Fz[i, j, k], Fz[i, j, k+1], dz))
    return sou
