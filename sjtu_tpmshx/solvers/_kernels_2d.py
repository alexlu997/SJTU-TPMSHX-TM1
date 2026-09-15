"""Shared Numba limiter and 2D/3D model-h helpers.

minmod() is the MINMOD-limited slope used by every SOU deferred-correction
kernel (_sou_corr_* in simple_solver.py and ltne_energy.py). It was previously
inlined ~24 times verbatim; extracting it with ``inline='always'`` keeps the
compiled output byte-identical while collapsing the duplication.
"""
from numba import njit


# Shared 2D/3D model-h Picard damping. Larger steps limit-cycle for turning
# flow with deferred SOU on stretched grids; this changes no steady equation.
MODEL_H_RELAXATION = 0.2


@njit(cache=True, fastmath=False)
def _model_h(T, coefficients):
    # Shared by 2D and fastmath 3D kernels: do not inherit the first caller's flags.
    a, b, c, origin, reference = coefficients
    x = T - origin
    x0 = reference - origin
    return a*(x-x0) + 0.5*b*(x*x-x0*x0) + c/3.0*(x*x*x-x0*x0*x0)


@njit(inline='always', cache=True)
def minmod(gu, gd):
    """MINMOD limiter: signed min(|gu|,|gd|) when gu,gd share a sign, else 0.

    Byte-identical to the block it replaces::

        phi = 0.0
        if gu * gd > 0:
            phi = min(abs(gu), abs(gd))
            if gu < 0: phi = -phi
    """
    if gu * gd > 0:
        phi = min(abs(gu), abs(gd))
        if gu < 0:
            phi = -phi
        return phi
    return 0.0
