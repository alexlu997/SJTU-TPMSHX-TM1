"""Guard: project-wide Re convention is Re = ρ · u · D_h / μ.

Ensures `tpms_calc.compute()` and hand-computed Re match — catches any
regression that reintroduces the legacy r_h = D_h/2 factor-of-two error.
"""
from sjtu_tpmshx.models.tpms_calc import compute, geometry, air_density, air_viscosity


def test_compute_Re_matches_hand_calculation():
    tpms, L_mm, t_mm, u, T_in, P_in, k_s = 'Gyroid', 7.0, 0.6, 10.0, 350.0, 101325.0, 15.0
    r = compute(tpms, L_mm, t_mm, u, T_in, P_in, k_s)
    g = geometry(tpms, L_mm, t_mm, k_s)
    rho = air_density(T_in, P_in)
    mu = air_viscosity(T_in)
    Re_hand = rho * u * g['D_h'] / mu
    assert abs(r['Re'] - Re_hand) / Re_hand < 1e-9


def test_Re_is_D_h_based_not_r_h():
    # r_h = D_h / 2 would halve Re — make sure that is NOT the case.
    r = compute('Diamond', 5.0, 0.4, 8.0, 300.0, 101325.0, 15.0)
    g = geometry('Diamond', 5.0, 0.4, 15.0)
    rho = air_density(300.0, 101325.0)
    mu = air_viscosity(300.0)
    Re_Dh = rho * 8.0 * g['D_h'] / mu
    Re_rh = rho * 8.0 * (g['D_h'] / 2.0) / mu
    assert abs(r['Re'] - Re_Dh) < 1.0
    assert abs(r['Re'] - Re_rh) > 100.0


def test_Re_scales_linearly_with_velocity():
    r1 = compute('Gyroid', 6.0, 0.4, 5.0, 300.0, 101325.0, 15.0)
    r2 = compute('Gyroid', 6.0, 0.4, 15.0, 300.0, 101325.0, 15.0)
    # u×3 → Re×3 at constant ρ, μ, D_h.
    assert abs(r2['Re'] / r1['Re'] - 3.0) < 1e-6


def test_Re_both_tpms_same_formula():
    # Diamond and Gyroid at the same (L, t, u, T, P) must differ only in
    # D_h, not in Re formula. Re ratio == D_h ratio.
    rD = compute('Diamond', 6.0, 0.4, 10.0, 300.0, 101325.0, 15.0)
    rG = compute('Gyroid',  6.0, 0.4, 10.0, 300.0, 101325.0, 15.0)
    gD = geometry('Diamond', 6.0, 0.4, 15.0)
    gG = geometry('Gyroid',  6.0, 0.4, 15.0)
    ratio_Re = rD['Re'] / rG['Re']
    ratio_Dh = gD['D_h'] / gG['D_h']
    assert abs(ratio_Re - ratio_Dh) / ratio_Dh < 1e-9
