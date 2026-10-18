"""Shared geometry fields for the two asymmetric CFD workbooks."""

from sjtu_tpmshx.models.asym_geometry import (
    a0_sides_mc, delta_for_split, dh_sides, eps_sides, percolates_z,
)


def split_geometry(phi, C, r, L_m, N):
    """Return rounded workbook fields, or None when the split is unreachable."""
    d = delta_for_split(phi, C, r)
    if d is None:
        return None
    eA, eB, eps = eps_sides(phi, C, d)
    e_sym = 0.5 * eps
    A0A, A0B = a0_sides_mc(phi, C, d, L_m, N)
    DhA, DhB = dh_sides(phi, C, d, L_m, N, mc=True)
    return dict(
        C=round(C, 4), delta=round(d, 4),
        phi_lo=round(d - C, 4), phi_hi=round(d + C, 4),
        split_r=r, eps_A=round(eA, 4), eps_B=round(eB, 4),
        eps_sym=round(e_sym, 4), solid=round(1.0 - eps, 4),
        kr_A=round(eA / e_sym, 4), kr_B=round(eB / e_sym, 4),
        A0_A=round(A0A, 1), A0_B=round(A0B, 1),
        Dh_A_mm=round(DhA * 1e3, 4), Dh_B_mm=round(DhB * 1e3, 4),
        pA=percolates_z(phi < (d - C)), pB=percolates_z(phi > (d + C)),
    )
