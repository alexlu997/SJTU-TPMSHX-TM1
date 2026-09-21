"""Unit tests for domain.validator pure-function suite.

Phase 4 of 2026-05-06 main.py refactor (audit fix #4). No Qt — every
test exercises the rule logic directly without instantiating a window.
"""
from __future__ import annotations


import pytest

from sjtu_tpmshx.domain.validator import (
    suggest_grid_2d,
    suggest_grid_3d,
    validate_geometry,
    compute_volumetric_htc,
    wall_for_dir,
    cross_axes_for_dir,
    parse_unit_value,
    validate_pipe_config,
    geometry_extrapolation_warning,
    Warning as W,
)


# ---------------------------------------------------------------- grid suggest


def test_suggest_grid_2d_basic():
    Nx, Ny = suggest_grid_2d(L_dom=0.080, H_dom=0.040, D_h=0.005)
    assert Nx >= 8
    assert Ny >= 8
    # alpha=0.4 default → Nx ≈ 0.080 / (0.4 * 0.005) = 40
    assert 35 <= Nx <= 45


def test_suggest_grid_2d_floor_at_8():
    Nx, Ny = suggest_grid_2d(L_dom=0.001, H_dom=0.001, D_h=0.005)
    assert Nx == 8
    assert Ny == 8


@pytest.mark.parametrize('bad', [-1.0, 0.0])
def test_suggest_grid_2d_rejects_nonpos(bad):
    with pytest.raises(ValueError):
        suggest_grid_2d(L_dom=bad, H_dom=0.04, D_h=0.005)


def test_suggest_grid_3d_under_cap():
    Nx, Ny, Nz = suggest_grid_3d(0.080, 0.040, 0.020, 0.005)
    # Wall-refine pad 16 → total <= 50000
    assert (Nx + 16) * (Ny + 16) * (Nz + 16) <= 50_000


def test_suggest_grid_3d_floors():
    Nx, Ny, Nz = suggest_grid_3d(0.001, 0.001, 0.001, 0.005)
    assert Nx == 14
    assert Ny == 8
    assert Nz == 3


def test_suggest_grid_3d_caps_nx_when_under_pressure():
    """When Ny+Nz alone are reasonable, Nx is the lever the cap pulls."""
    # 0.080 m domain × D_h=0.005 → Ny ~ 32, Nz ~ 8 → no cap firing.
    # With max_cells=10000, Nx must drop from ~16 to satisfy cap.
    Nx_uncapped, _, _ = suggest_grid_3d(0.080, 0.040, 0.020, 0.005,
                                          max_cells=50_000)
    Nx_capped, Ny, Nz = suggest_grid_3d(0.080, 0.040, 0.020, 0.005,
                                          max_cells=10_000)
    # Cap loop floors at 14, so Nx_capped <= Nx_uncapped (and >= 14).
    assert Nx_capped >= 14
    assert Nx_capped <= Nx_uncapped


def test_suggest_grid_3d_cap_does_not_infinite_loop_on_huge_domain():
    """If Ny*Nz alone exceeds the cap, the loop must terminate at Nx=14
    rather than reduce Nx forever."""
    Nx, Ny, Nz = suggest_grid_3d(1.0, 1.0, 1.0, 0.001,
                                   max_cells=20_000)
    # The cap is unsatisfiable here — Ny ~ 2000, Nz ~ 2000. The function
    # must still return (no infinite loop, no exception). Nx is at floor.
    assert Nx == 14
    assert Ny > 100
    assert Nz > 100


# ---------------------------------------------------------------- geometry


def test_validate_geometry_clean_passes():
    """Training-grid geometry, in domain → no warnings."""
    warns = validate_geometry(
        L_dom=0.080, H_dom=0.040, Lz_dom=0.020,
        L_cell_mm=8.0, t_mm=0.4, ks=16.0, is_3d=True)
    assert warns == []


def test_validate_geometry_t_over_L_high_warns():
    warns = validate_geometry(
        L_dom=0.080, H_dom=0.040, Lz_dom=None,
        L_cell_mm=4.0, t_mm=0.6)   # t/L = 0.15
    codes = [w.code for w in warns]
    assert 'tL_ratio_high' in codes


def test_validate_geometry_t_over_L_low_warns():
    warns = validate_geometry(
        L_dom=0.080, H_dom=0.040, Lz_dom=None,
        L_cell_mm=8.0, t_mm=0.3)   # t/L = 0.0375
    codes = [w.code for w in warns]
    assert 'tL_ratio_low' in codes


def test_validate_geometry_cell_larger_than_domain_errors():
    warns = validate_geometry(
        L_dom=0.005, H_dom=0.005, Lz_dom=None,   # 5 mm domain
        L_cell_mm=8.0, t_mm=0.4)                  # 8 mm cell
    err = [w for w in warns if w.code == 'cell_larger_than_domain']
    assert len(err) == 1
    assert err[0].severity == 'error'


def test_validate_geometry_shanghai_has_no_invented_error_band():
    warns = validate_geometry(
        L_dom=0.080, H_dom=0.040, Lz_dom=0.020,
        L_cell_mm=7.0, t_mm=0.6, is_3d=True)
    assert not warns


def test_validate_geometry_3d_requires_Lz():
    with pytest.raises(ValueError, match='Lz_dom'):
        validate_geometry(
            L_dom=0.08, H_dom=0.04, Lz_dom=None,
            L_cell_mm=8.0, t_mm=0.4, is_3d=True)


def test_validate_geometry_rejects_nonpositive_inputs():
    with pytest.raises(ValueError):
        validate_geometry(L_dom=-0.1, H_dom=0.04, Lz_dom=None,
                          L_cell_mm=8.0, t_mm=0.4)


def test_geometry_extrapolation_warning_in_grid_returns_none():
    assert geometry_extrapolation_warning(L_cell_mm=8.0, t_mm=0.4) is None


def test_geometry_extrapolation_warning_off_grid():
    w = geometry_extrapolation_warning(L_cell_mm=7.0, t_mm=0.61)
    assert w is not None
    assert w.code == 'geometry_extrapolation'


# ---------------------------------------------------------------- physics


def test_compute_volumetric_htc_product():
    assert compute_volumetric_htc(A_0=2000.0, H_sf=50.0) == pytest.approx(100_000.0)


def test_compute_volumetric_htc_zero_safe():
    assert compute_volumetric_htc(0.0, 0.0) == 0.0


def test_compute_volumetric_htc_rejects_negative():
    with pytest.raises(ValueError):
        compute_volumetric_htc(-1.0, 50.0)


# ---------------------------------------------------------------- direction


@pytest.mark.parametrize('d, inlet, outlet', [
    (0, 'left',   'right'),
    (1, 'right',  'left'),
    (2, 'bottom', 'top'),
    (3, 'top',    'bottom'),
    (4, 'front',  'back'),
    (5, 'back',   'front'),
])
def test_wall_for_dir_full_table(d, inlet, outlet):
    assert wall_for_dir(d, 'inlet') == inlet
    assert wall_for_dir(d, 'outlet') == outlet


def test_wall_for_dir_rejects_bad_dir():
    with pytest.raises(ValueError):
        wall_for_dir(99, 'inlet')


def test_wall_for_dir_rejects_bad_role():
    with pytest.raises(ValueError):
        wall_for_dir(0, 'sideways')


@pytest.mark.parametrize('d, expected', [
    (0, ('Y', 'Z')), (1, ('Y', 'Z')),
    (2, ('X', 'Z')), (3, ('X', 'Z')),
    (4, ('X', 'Y')), (5, ('X', 'Y')),
])
def test_cross_axes_for_dir(d, expected):
    assert cross_axes_for_dir(d) == expected


# ---------------------------------------------------------------- pipe config


def test_validate_pipe_config_valid():
    cfg = dict(dir=0, in_ctr=0.020, in_w=0.010,
               out_ctr=0.020, out_w=0.010)
    warns = validate_pipe_config(cfg, L_dom=0.08, H_dom=0.04)
    assert warns == []


def test_validate_pipe_config_pipe_off_domain():
    cfg = dict(dir=0, in_ctr=0.050, in_w=0.020,   # 0.05+0.01 = 0.06 > H=0.04
               out_ctr=0.020, out_w=0.010)
    warns = validate_pipe_config(cfg, L_dom=0.08, H_dom=0.04)
    codes = [w.code for w in warns]
    assert 'pipe_in_out_of_domain' in codes


def test_validate_pipe_config_zero_width_errors():
    cfg = dict(dir=0, in_ctr=0.020, in_w=0.0,
               out_ctr=0.020, out_w=0.010)
    warns = validate_pipe_config(cfg, L_dom=0.08, H_dom=0.04)
    err = [w for w in warns if w.code == 'pipe_in_w_nonpos']
    assert len(err) == 1
    assert err[0].severity == 'error'


def test_validate_pipe_config_3d_z_partial_in_range():
    cfg = dict(dir=0, in_ctr=0.020, in_w=0.010,
               out_ctr=0.020, out_w=0.010,
               in_z_ctr=0.010, in_z_w=0.005,
               out_z_ctr=0.010, out_z_w=0.005)
    warns = validate_pipe_config(cfg, L_dom=0.08, H_dom=0.04,
                                   Lz_dom=0.020, is_3d=True)
    assert warns == []


def test_validate_pipe_config_3d_z_partial_off_domain():
    cfg = dict(dir=0, in_ctr=0.020, in_w=0.010,
               out_ctr=0.020, out_w=0.010,
               in_z_ctr=0.025, in_z_w=0.020,   # 0.025+0.01 = 0.035 > Lz=0.02
               out_z_ctr=0.010, out_z_w=0.005)
    warns = validate_pipe_config(cfg, L_dom=0.08, H_dom=0.04,
                                   Lz_dom=0.020, is_3d=True)
    codes = [w.code for w in warns]
    assert 'pipe_in_z_out_of_domain' in codes


def test_validate_pipe_config_bad_dir():
    cfg = dict(dir=99, in_ctr=0.020, in_w=0.010,
               out_ctr=0.020, out_w=0.010)
    warns = validate_pipe_config(cfg, L_dom=0.08, H_dom=0.04)
    assert any(w.code == 'pipe_bad_dir' for w in warns)


def test_validate_pipe_config_rejects_z_direction_in_2d():
    cfg = dict(dir=4, in_ctr=0.040, in_w=0.020,
               out_ctr=0.040, out_w=0.020)
    warns = validate_pipe_config(cfg, L_dom=0.08, H_dom=0.04)
    assert any(w.code == 'pipe_bad_dir' for w in warns)


def test_validate_pipe_config_z_flow_checks_y_cross_axis():
    cfg = dict(dir=4, in_ctr=0.040, in_w=0.020,
               out_ctr=0.040, out_w=0.020,
               in_z_ctr=0.045, in_z_w=0.010,
               out_z_ctr=0.020, out_z_w=0.010)
    warns = validate_pipe_config(
        cfg, L_dom=0.08, H_dom=0.04, Lz_dom=0.02, is_3d=True)
    assert any(w.code == 'pipe_in_z_out_of_domain' for w in warns)


def test_validate_pipe_config_rejects_incomplete_cross2_pair():
    cfg = dict(dir=0, in_ctr=0.020, in_w=0.010,
               out_ctr=0.020, out_w=0.010,
               in_z_ctr=0.010, in_z_w=None)
    warns = validate_pipe_config(
        cfg, L_dom=0.08, H_dom=0.04, Lz_dom=0.02, is_3d=True)
    assert any(w.code == 'pipe_in_z_incomplete' for w in warns)


# ---------------------------------------------------------------- unit parser


@pytest.mark.parametrize('val, unit, expect_m', [
    (150, 'mm',  0.150),
    (1.0, 'm',   1.0),
    (10,  'cm',  0.10),
    (1,   'in',  0.0254),
    (1,   'ft',  0.3048),
])
def test_parse_unit_value_length_to_m(val, unit, expect_m):
    out = parse_unit_value(val, unit, 'length', target_unit='m')
    assert out == pytest.approx(expect_m, rel=1e-4)


def test_parse_unit_value_length_to_mm():
    # 0.5 m → mm
    out = parse_unit_value(0.5, 'm', 'length', target_unit='mm')
    assert out == pytest.approx(500.0)


def test_parse_unit_value_length_unknown_returns_none():
    assert parse_unit_value(1, 'parsec', 'length',
                              target_unit='m') is None


@pytest.mark.parametrize('val, unit, target, expect', [
    (1, 'bar', 'pa',  1e5),
    (1, 'kpa', 'pa',  1000.0),
    (1, 'atm', 'pa',  101325.0),
])
def test_parse_unit_value_pressure(val, unit, target, expect):
    out = parse_unit_value(val, unit, 'pressure', target_unit=target)
    assert out == pytest.approx(expect, rel=1e-4)


def test_parse_unit_value_speed_kph_to_mps():
    out = parse_unit_value(36.0, 'km/h', 'speed', target_unit='m/s')
    assert out == pytest.approx(10.0)


def test_parse_unit_value_temp_C_to_K():
    out = parse_unit_value(25.0, 'C', 'temp', temp_unit='K')
    assert out == pytest.approx(298.15)


def test_parse_unit_value_temp_F_to_K():
    out = parse_unit_value(32.0, 'F', 'temp', temp_unit='K')
    assert out == pytest.approx(273.15)


def test_parse_unit_value_temp_K_to_C_when_display_C():
    out = parse_unit_value(298.15, 'K', 'temp', temp_unit='C')
    assert out == pytest.approx(25.0)


def test_parse_unit_value_unknown_family_raises():
    with pytest.raises(ValueError):
        parse_unit_value(1, 'm', 'mass', target_unit='kg')


# ---------------------------------------------------------------- Warning class


def test_warning_dataclass_default_severity():
    w = W(code='x', message='y')
    assert w.severity == 'warn'


def test_warning_explicit_severity():
    w = W(code='x', message='y', severity='error')
    assert w.severity == 'error'
