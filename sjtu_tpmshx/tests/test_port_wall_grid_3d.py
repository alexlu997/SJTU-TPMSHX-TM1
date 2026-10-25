"""Keep nonuniform-grid solve coverage and the original comparison limits."""
from dataclasses import replace

import numpy as np
import pytest


def _full_face_config(port_wall_refine=True):
    from sjtu_tpmshx.tests.cases_3d import air_air_config
    config = air_air_config()
    return replace(config,
        solver=replace(config.solver, Nx=24, Ny=22, Nz=22),
        bc_B=replace(config.bc_B, in_ctr=.091, in_w=.182, out_ctr=.091, out_w=.182),
        flags=replace(config.flags, port_wall_refine=port_wall_refine))


@pytest.mark.slow
def test_port_wall_grid_solves_and_matches_uniform():
    """Check convergence, conservation and agreement for the same physical case."""
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.solvers.api import run_case

    result = run_case(prepare_case(_full_face_config(), case_id='port-wall-refined'))
    assert result.run_status['converged'], result.run_status
    r = result.metadata['diagnostics']
    for key in ('T_A_out', 'T_B_out', 'dP_A', 'Q_enthalpy_A', 'Q_enthalpy_B'):
        assert np.isfinite(r[key]), f"{key} not finite on refined grid"
    assert r['dP_A'] > 0.0
    assert np.isfinite(r['mass_imbalance_rel_A'])
    assert r['mass_imbalance_rel_A'] < 0.05

    Qa, Qb = abs(r['Q_enthalpy_A']), abs(r['Q_enthalpy_B'])
    assert Qa > 1.0 and Qb > 1.0, f"degenerate duties: {Qa:.3g}/{Qb:.3g}"
    assert abs(Qa - Qb) / max(Qa, Qb) < 0.15, \
        f"A/B energy imbalance on refined grid: {Qa:.1f} vs {Qb:.1f}"

    # Keep the original limits on the same physical case and total cell count.
    ru = run_case(prepare_case(_full_face_config(False), case_id='uniform')).metadata['diagnostics']
    dP_u, dP_r = ru['dP_A'], r['dP_A']
    assert abs(dP_r - dP_u) / dP_u < 0.15, \
        f"refined dP {dP_r:.0f} vs uniform {dP_u:.0f} (>15%)"
    Qu = abs(ru['Q_enthalpy_A'])
    assert abs(Qa - Qu) / Qu < 0.10, \
        f"refined Q {Qa:.0f} vs uniform {Qu:.0f} (>10%)"
