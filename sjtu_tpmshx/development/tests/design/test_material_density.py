from sjtu_tpmshx.applications.design.cases import DesignCase
from sjtu_tpmshx.applications.design.sizing import size_fixed_cell, RHO_S

def _cases():
    return [DesignCase(1,"air",688.23,1_088_700.0,0.2855,
                       "water",320.0,200_000.0,0.5,30_000.0,0.075,0.05)]

def test_rho_s_scales_weight_linearly():
    cs = _cases()
    d1 = size_fixed_cell(cs, "Diamond", 7.0, 0.5, "cross", rho_s=7900.0)
    d2 = size_fixed_cell(cs, "Diamond", 7.0, 0.5, "cross", rho_s=2700.0)
    if not (d1.feasible and d2.feasible):
        import pytest; pytest.skip("infeasible in this config")
    assert abs(d1.V - d2.V) < 1e-9
    assert abs(d2.weight / d1.weight - 2700.0/7900.0) < 1e-6

def test_rho_s_defaults_to_RHO_S():
    cs = _cases()
    d_def = size_fixed_cell(cs, "Diamond", 7.0, 0.5, "cross")
    d_exp = size_fixed_cell(cs, "Diamond", 7.0, 0.5, "cross", rho_s=RHO_S)
    if d_def.feasible and d_exp.feasible:
        assert abs(d_def.weight - d_exp.weight) < 1e-9
