"""B-plan B1/B2/B3 — strict energy-conservation golden, all 6 audit cases.

Conservation contract (vault: 2026-06-03-3d-strict-energy-conservation-B-plan-CN.md):
  the discrete FV energy balance must satisfy ∮_∂Ω F·n dA = ∫_Ω S dV per phase,
  for EVERY geometry: full-face parallel (T1), full-face cross-flow (T2),
  aligned partial-B (T3), offset partial-B / Shanghai-like (T4), B-isolated
  (T5) and equi-temperature (T6).

Metrics — emitted by the solver when cfg['conservative_ltne']=True:
  eps_{A,B}_strict          global balance |Σ_interior r| / max(|∫_interior S|, floor)
  eps_{A,B}_strict_cellmax  per-cell      max|r[c]|·N / max(|∫S|, floor)
  where r[c] = a_P·T_c − Σ a_nb·T_nb − h_v·V·Ts is the residual of the
  *conservative* discretisation (a_P carries the (F_e−F_w+…) net-out term) on
  the converged field. Shared SIMPLE face fluxes make internal faces telescope,
  so a solution that solves the conservative balance drives both to ~0; a
  non-conservative field leaves them O(1) (validated: synthetic non-solution
  → 100 %). The relative denominator carries a physical floor so the degenerate
  no-net-heat-exchange cases (T5 solid↔single-fluid equilibrium, T6 equi-T,
  both ∫S → 0) do not divide by ~0 — there the absolute residual is
  machine-level, i.e. trivially conserving.

This supersedes the earlier compute_phase2a_interior heuristic (advective
enthalpy m·cp·ΔT vs interior source), which dropped the boundary-diffusion
term and so read ~8.5 % for a cold fluid even when the scheme conserved.

The legacy cell-local-|u_c| upwind kernel (cfg default) does NOT satisfy this
balance. The face-centered Patankar rewrite (SIMPLE staggered fluxes,
(F_e−F_w) telescoping in a_P, MAC projection to discrete solenoidality) drives
all six cases < 1 % on BOTH the global and per-cell certificate AND keeps mass
conservation intact.
"""

import pytest

from sjtu_tpmshx.validation.cases.audit_3d_conservation import (
    make_T1, make_T2, make_T3, make_T4, make_T5, make_T6,
)
from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack

_GATE = 0.01  # < 1 %

# Per-case grids (D4(a), 2026-07-21). The certificate is a STRUCTURAL property
# (telescoping of the conservative kernel — grid-size-independent semantics),
# so the partial-B monsters run coarser with measured margin under the 1% gate:
#   T3@16: worst 0.280% (was 526s @20 → 134s);  T4@18: worst 0.729%
#   (was 604s @20 → 288s; @16 was 0.957% — too thin, rejected).
# T1/T2/T5/T6 stay at 20 (cheap). Suite critical path drops ~600s → ~460s
# (now bounded by test_wall_refine_3d — its 448s refined solve on a 288-cell
# base grid is a flagged performance anomaly for the D4(c) profile round,
# deliberately NOT dieted away here).
_CASES = [
    ("T1_full_parallel", make_T1, 20),
    ("T2_full_cross", make_T2, 20),
    ("T3_partial_aligned", make_T3, 16),
    ("T4_partial_offset", make_T4, 18),
    ("T5_B_isolated", make_T5, 20),
    ("T6_equi_temperature", make_T6, 20),
]


@pytest.mark.parametrize("name,maker,grid", _CASES, ids=[c[0] for c in _CASES])
def test_strict_energy_conservation(name, maker, grid):
    """Conservative discretisation balances per phase — global + per-cell — and
    does not break mass conservation, for every audit geometry."""
    cfg = maker(grid)
    cfg["conservative_ltne"] = True
    res = _run_3d_stack(cfg)

    # Strict-conservation certificate must be emitted on the conservative path.
    for key in ("eps_A_strict", "eps_B_strict",
                "eps_A_strict_cellmax", "eps_B_strict_cellmax"):
        v = res.get(key)
        if cfg['fluid_B_cfg'] is None and key.startswith('eps_B_'):
            # No B equation was solved; zero is not a conservation certificate.
            assert v is None
            assert res['Q_sB'] == 0.0
            continue
        assert v is not None, f"{name}: {key} not emitted by conservative path"
        assert v < _GATE, f"{name}: {key}={v*100:.3f}% not < 1%"

    # Conservation of energy must not come at the cost of mass conservation.
    assert res["mass_imbalance_rel_A"] < _GATE, \
        f"{name}: mass_imbalance_A={res['mass_imbalance_rel_A']*100:.3f}% not < 1%"
    assert res["mass_imbalance_rel_B"] < _GATE, \
        f"{name}: mass_imbalance_B={res['mass_imbalance_rel_B']*100:.3f}% not < 1%"
