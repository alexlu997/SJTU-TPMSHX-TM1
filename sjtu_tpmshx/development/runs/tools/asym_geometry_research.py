"""Historical asymmetric-geometry research methods, outside formal preparation.

The existing search, percolation and extrapolation mathematics are retained.
Raw geometry queries use the shared native entry points.
"""
import numpy as np
from scipy import ndimage

from sjtu_tpmshx.shared.models.asym_geometry import eps_sides, a0_sides_mc


def _eps_from_C(phi: np.ndarray, C: float) -> float:
    """Porosity for the retained research threshold search."""
    return float(1.0 - np.mean(np.abs(phi) <= C))


def _find_C_for_eps(phi: np.ndarray, target_eps: float) -> float:
    """Binary search for C that gives target porosity."""
    C_lo, C_hi = 0.0, float(np.max(np.abs(phi)))
    for _ in range(60):
        C_mid = (C_lo + C_hi) / 2.0
        eps = _eps_from_C(phi, C_mid)
        if eps > target_eps:
            C_lo = C_mid
        else:
            C_hi = C_mid
    return (C_lo + C_hi) / 2.0


def delta_for_split(phi, C, target, n=6000):
    """Return the first sampled offset with epsilon_A/epsilon_B >= target."""
    if target <= 1.0:
        return 0.0
    for d in np.linspace(0.0, float(np.abs(phi).max()), n):
        eA, eB, _ = eps_sides(phi, C, d)
        if eB <= 1e-9:
            break
        if eA / eB >= target:
            return float(d)
    return None




def a0_sides_richardson(tpms_type, C: float, delta: float, L_m: float,
                        Ns=(96, 144, 216)):
    """Extrapolate each side's area density (1/m) from three grids.

    The 2026-06-09 study reported about 3% low area at extreme offsets
    on N=128. It reported less than 1% error after this extrapolation.
    Those historical results are not acceptance of a new configuration.
    The default grids have a refinement ratio of 1.5.
    """
    from sjtu_tpmshx.shared.models.tpms_geometry import _phi_grid
    A_vals, B_vals = [], []
    for N in Ns:
        aA, aB = a0_sides_mc(_phi_grid(tpms_type, N), C, delta, L_m, N)
        A_vals.append(aA)
        B_vals.append(aB)
    return _richardson3(Ns, A_vals), _richardson3(Ns, B_vals)



def _richardson3(Ns, f):
    """Estimate the order and extrapolate three geometrically spaced grids.

    Use f(N) = f_inf - c*N**(-p) with p = log(d1/d2)/log(r).
    Return the finest value for zero or nonmonotone differences.
    """
    (N1, N2, N3), (f1, f2, f3) = Ns, f
    d1, d2 = f2 - f1, f3 - f2
    if f3 == 0.0 or d1 == 0.0 or d2 == 0.0 or d1 * d2 <= 0.0:
        return f3
    r = ((N2 / N1) + (N3 / N2)) / 2.0
    p = float(np.clip(np.log(d1 / d2) / np.log(r), 0.5, 3.0))
    return f3 + d2 / (r ** p - 1.0)



def percolates_z(mask: np.ndarray) -> bool:
    """Check whether a void component touches both z end faces."""
    lab, _ = ndimage.label(mask)
    if lab.max() == 0:
        return False
    top = set(np.unique(lab[:, :, 0])) - {0}
    bot = set(np.unique(lab[:, :, -1])) - {0}
    return len(top & bot) > 0



def find_delta_max(phi: np.ndarray, C: float, dstep: float = None) -> float:
    """Find the last sampled offset with two connected void networks.

    This historical research method fixes 2*C. It does not constrain
    physical wall thickness or establish manufacturing limits.
    """
    phimax = float(np.max(np.abs(phi)))
    if dstep is None:
        dstep = phimax / 200.0
    delta = 0.0
    last_ok = 0.0
    while delta <= phimax:
        if not (percolates_z(phi < (delta - C)) and percolates_z(phi > (delta + C))):
            break
        last_ok = delta
        delta += dstep
    return last_ok

