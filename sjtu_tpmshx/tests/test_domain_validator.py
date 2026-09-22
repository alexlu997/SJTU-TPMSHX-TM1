"""Unit tests for domain.validator pure-function suite.

Phase 4 of 2026-05-06 main.py refactor (audit fix #4). No Qt — every
test exercises the rule logic directly without instantiating a window.
"""
from __future__ import annotations


import pytest

from sjtu_tpmshx.models.grid import suggest_grid_3d
from sjtu_tpmshx.domain.validator import (
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


def test_suggest_grid_3d_uses_total_counts_without_six_wall_padding():
    assert suggest_grid_3d(.080, .040, .020, .005, max_cells=2050) == (16, 16, 8)


def test_suggest_grid_3d_floors():
    assert suggest_grid_3d(.001, .001, .001, .005) == (14, 8, 3)


def test_suggest_grid_3d_caps_all_axes_without_cross_axis_budget_escape():
    import math
    counts = suggest_grid_3d(1., 1., 1., .001, max_cells=20_000)
    assert math.prod(counts) <= 20_000
    assert all(n >= floor for n, floor in zip(counts, (14, 8, 3)))


def test_suggest_grid_3d_rejects_budget_below_required_minimum():
    with pytest.raises(ValueError, match='required minimum'):
        suggest_grid_3d(.1, .1, .1, .005, max_cells=100)


@pytest.mark.parametrize('direction', range(6))
def test_port_wall_suggestion_uses_real_axis_and_opening_minima(direction):
    import math
    import numpy as np
    from sjtu_tpmshx.models.grid import build_port_wall_grid, port_wall_min_counts
    lengths = (.182, .042, .030)
    cross = [i for i in range(3) if i != direction // 2]
    port = {'dir': direction}
    for axis, suffix in zip(cross, ('', '_z')):
        for end in ('in', 'out'):
            port[end + suffix + '_ctr'] = lengths[axis] * .5
            port[end + suffix + '_w'] = lengths[axis] * .4
    minimum = port_wall_min_counts(lengths, (port,))
    assert minimum[direction // 2] == 10
    assert all(minimum[i] == 30 for i in cross)
    counts = suggest_grid_3d(*lengths, .02, port_wall_refine=True, ports=(port,))
    widths = build_port_wall_grid(lengths, counts, (port,))
    assert tuple(map(len, widths)) == counts
    assert math.prod(counts) <= 50_000
    for width, length in zip(widths, lengths):
        assert np.all(width > 0)
        assert width.sum() == pytest.approx(length)
    too_small = list(counts)
    too_small[cross[0]] = minimum[cross[0]] - 1
    with pytest.raises(ValueError, match='at least 30'):
        build_port_wall_grid(lengths, too_small, (port,))


# ---------------------------------------------------------------- geometry


def test_validate_geometry_clean_passes():
    """Training-grid geometry, in domain → no warnings."""
    warns = validate_geometry(
        L_dom=0.080, H_dom=0.040, Lz_dom=0.020,
        L_cell_mm=8.0, t_mm=0.4, ks=16.0, is_3d=True)
    assert warns == []


@pytest.mark.parametrize('cell,wall', [(4., .6), (8., .3), (6.5, .55)])
def test_validate_geometry_uses_current_fixed_cfd_grid_not_obsolete_t_over_L(cell, wall):
    assert validate_geometry(.08, .04, None, cell, wall) == []


@pytest.mark.parametrize('cell,wall', [(3.9, .4), (8.1, .4), (7., .29), (7., .61)])
def test_geometry_extrapolation_names_only_the_resource_it_checked(cell, wall):
    warnings = validate_geometry(.08, .04, None, cell, wall)
    assert len(warnings) == 1
    assert warnings[0].code == 'geometry_extrapolation'
    assert 'geometry/D-F' in warnings[0].message
    assert 'Nu correlations and experimental corrections have separate' in warnings[0].message


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
