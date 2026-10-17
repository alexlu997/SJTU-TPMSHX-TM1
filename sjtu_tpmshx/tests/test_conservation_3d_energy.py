"""Native dual-fluid audit cases retain one-percent mass and energy gates."""

import pytest

from sjtu_tpmshx.validation.cases.audit_3d_conservation import (
    make_T1, make_T2, make_T3, make_T4, make_T6,
)
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case

_GATE = 0.01  # < 1 %

# Keep the qualified full and partial-port grids.
_CASES = [
    ("T1_full_parallel", make_T1, 20),
    ("T2_full_cross", make_T2, 20),
    ("T3_partial_aligned", make_T3, 16),
    ("T4_partial_offset", make_T4, 18),
    ("T6_equi_temperature", make_T6, 20),
]


@pytest.mark.parametrize("name,maker,grid", _CASES, ids=[c[0] for c in _CASES])
def test_strict_energy_conservation(name, maker, grid):
    """Conservative discretisation balances per phase — global + per-cell — and
    does not break mass conservation, for every audit geometry."""
    cfg = maker(grid)
    result = run_case(prepare_case(cfg, case_id=name))
    assert result.run_status['converged']
    res = result.metadata['diagnostics']

    # Strict-conservation certificate must be emitted on the conservative path.
    for key in ("eps_A_strict", "eps_B_strict",
                "eps_A_strict_cellmax", "eps_B_strict_cellmax"):
        v = res.get(key)
        assert v is not None, f"{name}: {key} not emitted by conservative path"
        assert v < _GATE, f"{name}: {key}={v*100:.3f}% not < 1%"

    # Conservation of energy must not come at the cost of mass conservation.
    assert res["mass_imbalance_rel_A"] < _GATE, \
        f"{name}: mass_imbalance_A={res['mass_imbalance_rel_A']*100:.3f}% not < 1%"
    assert res["mass_imbalance_rel_B"] < _GATE, \
        f"{name}: mass_imbalance_B={res['mass_imbalance_rel_B']*100:.3f}% not < 1%"
