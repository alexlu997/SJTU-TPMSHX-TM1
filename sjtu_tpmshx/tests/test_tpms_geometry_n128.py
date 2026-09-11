"""Guard for voxel N=128 default vs N=256 reference (audit M-d / P3).

Default ``compute_geometry`` N is 128 as of 2026-05-28 (was 256). This cuts
per-process phi-grid memory from 128 MiB to 16 MiB, which matters for
parallel BO that rebuilds the un-shared lru_cache in each worker. The
core calibration tables (_C_COEFFS) were fit on N=256 grids; this test
asserts the N=128 outputs stay within the empirically-measured tolerances:
    |delta_eps|/eps    < 0.3 %  (0.003 relative; empirical max 0.21 %)
    |delta_A_0|/A_0    < 1 %    (0.01  relative)

Drift outside these bounds means either the level-set quadrature lost
significant precision at N=128 or the area-correction factor needs
re-calibration; either way it is a downstream regression that the
existing Shanghai 16-case validation would only catch much later.

The eps tolerance was set from observation rather than the docstring
claim of <0.08% (which was over-optimistic for some t/L corners); the
chosen 0.3 % keeps a ~50 % safety margin above the worst observed drift.
"""
from __future__ import annotations

import pytest

from sjtu_tpmshx.models.tpms_geometry import compute_geometry


# 12 (Diamond) + 12 (Gyroid) = 24 baseline geometries that span the
# validated design ranges L_cell in {4, 5, 6, 8} mm, t in {0.3, 0.4, 0.5} mm.
_BASELINE_GEOMS = [
    (tpms, L, t)
    for tpms in ("Diamond", "Gyroid")
    for L in (4, 5, 6, 8)
    for t in (0.3, 0.4, 0.5)
]

_EPS_REL_TOL = 3e-3   # 0.3 % (empirical max 0.21 %, audit 2026-05-28)
_A0_REL_TOL = 1e-2    # 1   %


@pytest.mark.parametrize("tpms_type,L_mm,t_mm", _BASELINE_GEOMS)
def test_n128_matches_n256_within_tol(tpms_type, L_mm, t_mm):
    g128 = compute_geometry(tpms_type, L_mm, t_mm, N=128)
    g256 = compute_geometry(tpms_type, L_mm, t_mm, N=256)

    eps_ref = g256["epsilon"]
    a0_ref = g256["A_0"]

    eps_drift = abs(g128["epsilon"] - eps_ref) / eps_ref
    a0_drift = abs(g128["A_0"] - a0_ref) / a0_ref

    assert eps_drift < _EPS_REL_TOL, (
        f"{tpms_type} L={L_mm} t={t_mm}: epsilon drift {eps_drift:.4%} "
        f"exceeds tol {_EPS_REL_TOL:.4%} (N128 {g128['epsilon']:.6f} "
        f"vs N256 {eps_ref:.6f})"
    )
    assert a0_drift < _A0_REL_TOL, (
        f"{tpms_type} L={L_mm} t={t_mm}: A_0 drift {a0_drift:.4%} "
        f"exceeds tol {_A0_REL_TOL:.4%} (N128 {g128['A_0']:.1f} "
        f"vs N256 {a0_ref:.1f})"
    )


def test_default_N_is_128():
    """Lock the docstring promise -- default arg should be 128."""
    import inspect

    sig = inspect.signature(compute_geometry)
    assert sig.parameters["N"].default == 128, (
        f"compute_geometry N default must be 128 (audit M-d, 2026-05-28); "
        f"got {sig.parameters['N'].default}"
    )
