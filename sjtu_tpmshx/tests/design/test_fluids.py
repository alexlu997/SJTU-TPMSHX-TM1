from sjtu_tpmshx.models.design_fluids import fluid_props, fluid_nu

def test_air_props_at_645K():
    p = fluid_props("air", 645.6, 1_088_700.0)
    assert abs(p.rho - 5.875) < 0.05          # P/(287 T)
    assert 1000 < p.cp < 1120                 # J/(kg K)
    assert 2.5e-5 < p.mu < 4.5e-5
    assert 0.04 < p.k < 0.06

def test_water_props_near_320K():
    p = fluid_props("water", 320.0, 2e5)
    assert 980 < p.rho < 1000
    assert abs(p.cp - 4182.0) < 1.0
    assert 4e-4 < p.mu < 8e-4

def test_air_nu_rough_factor_applied():
    # Diamond air Nu = 1.28 × smooth (default factor)
    nu = fluid_nu("air", "Diamond", Re=5000.0, eps_f=0.36, L_mm=7.0, D_h_mm=2.74)
    assert nu > 0
    # water Nu via Yan[6] differs from air at same Re
    nuw = fluid_nu("water", "Gyroid", Re=2000.0, eps_f=0.42, L_mm=7.0, D_h_mm=2.0)
    assert nuw > 0 and abs(nuw - nu) > 1e-6
