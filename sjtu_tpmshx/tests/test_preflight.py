"""Tests for the grid-legality preflight (pure-logic layer)."""

import pytest

from sjtu_tpmshx.ui.preflight import FluidCfg, compute_preflight


def _shanghai_A():
    # Full-width 42 mm strip on +x flow → cross axis = y (H=42 mm).
    return FluidCfg(dir=0, in_ctr=0.021, in_w=0.042,
                    out_ctr=0.021, out_w=0.042)


def _shanghai_B_partial():
    # Staggered 42 mm strip cross-flow on -y → cross axis = x (L=182 mm).
    return FluidCfg(dir=3, in_ctr=0.154, in_w=0.042,
                    out_ctr=0.028, out_w=0.042)


def test_port_wall_counts_match_the_actual_grid():
    for nx, ny, nz in ((84, 24, 1), (92, 14, 10)):
        report = compute_preflight(L=.182, H=.042, Lz=.042, Nx=nx, Ny=ny, Nz=nz,
            is_3d=nz > 1, wall_refine_3d=False, port_wall_refine=True,
            fluid_A=_shanghai_A(), fluid_B=_shanghai_B_partial())
        assert not report.errors, report.errors
        assert not report.warnings, report.warnings
        assert any(f'{nx} × {ny}' in s and 'port/wall' in s for s in report.info)
    invalid = compute_preflight(L=.182, H=.042, Lz=.042, Nx=8, Ny=8, Nz=3,
        is_3d=True, wall_refine_3d=False, port_wall_refine=True,
        fluid_A=_shanghai_A(), fluid_B=_shanghai_B_partial())
    assert any('at least' in s for s in invalid.errors)


def test_failed_port_grid_keeps_bounds_checks_without_coverage_claims():
    # Stale 30 mm z-ports split the 42 mm domain into two segments; Nz=10
    # cannot build the graded grid. An independent x-span error must remain.
    A = _shanghai_A()
    A.z_in_ctr = A.z_out_ctr = .015
    A.z_in_w = A.z_out_w = .03
    B = _shanghai_B_partial()
    B.in_ctr = .19
    report = compute_preflight(
        L=.182, H=.042, Lz=.042, Nx=92, Ny=14, Nz=10,
        is_3d=True, wall_refine_3d=False, port_wall_refine=True,
        fluid_A=A, fluid_B=B, T_inA=300., T_inB=422.)

    assert any('at least 20 cells on z axis' in s and 'got 10' in s
               and '30 mm (2 segments)' in s and 'Increase Nz' in s
               for s in report.errors)
    assert any('exceeds x domain' in s for s in report.errors)
    assert any('B is the hot side' in s for s in report.info)
    assert not any('Effective grid' in s or 'covers' in s
                   for s in report.info + report.warnings + report.errors)


def test_shanghai_2d_partial_no_refine():
    """Partial-width B inlet forces 2D path onto uniform (no wall refine)."""
    r = compute_preflight(
        L=0.182, H=0.042, Lz=0.0,
        Nx=100, Ny=50, Nz=1, is_3d=False,
        wall_refine_3d=False,
        fluid_A=_shanghai_A(), fluid_B=_shanghai_B_partial())
    assert not r.errors, f"unexpected errors: {r.errors}"
    # Uniform grid means refined Nx == user Nx.
    assert any("uniform" in s for s in r.info), r.info
    assert any(f"{100} × {50}" in s for s in r.info), r.info
    print("test_shanghai_2d_partial_no_refine PASS")


def test_full_width_2d_activates_refine():
    """Both fluids full-width on cross axes → 2D path applies wall refine
    (Nx + 16, Ny + 16)."""
    A = FluidCfg(dir=0, in_ctr=0.021, in_w=0.042,
                 out_ctr=0.021, out_w=0.042)
    # Force B also full-width on its cross axis (x = 182 mm).
    B = FluidCfg(dir=3, in_ctr=0.091, in_w=0.182,
                 out_ctr=0.091, out_w=0.182)
    r = compute_preflight(
        L=0.182, H=0.042, Lz=0.0,
        Nx=100, Ny=50, Nz=1, is_3d=False,
        wall_refine_3d=False,
        fluid_A=A, fluid_B=B)
    assert not r.errors, r.errors
    assert any("wall-refined" in s for s in r.info), r.info
    assert any("116 × 66" in s for s in r.info), r.info
    print("test_full_width_2d_activates_refine PASS")


def test_3d_wall_refine_fits():
    """Explicit 30/20/5 input plus six-wall refinement yields 46/36/21."""
    r = compute_preflight(
        L=0.182, H=0.042, Lz=0.042,
        Nx=30, Ny=20, Nz=5, is_3d=True,
        wall_refine_3d=True,
        fluid_A=_shanghai_A(), fluid_B=_shanghai_B_partial())
    assert not r.errors, r.errors
    # 30+16 = 46, 20+16 = 36, 5+16 = 21
    assert any("46 × 36 × 21" in s for s in r.info), r.info
    print("test_3d_wall_refine_fits PASS")


def test_3d_small_domain_refine_errors():
    """If any domain axis is below ~5.5 mm, wall refine cannot fit."""
    r = compute_preflight(
        L=0.004, H=0.004, Lz=0.004,
        Nx=10, Ny=10, Nz=10, is_3d=True,
        wall_refine_3d=True,
        fluid_A=FluidCfg(dir=0, in_ctr=0.002, in_w=0.004,
                         out_ctr=0.002, out_w=0.004),
        fluid_B=None)
    assert r.errors, "expected at least one error"
    assert any("too small for wall refinement" in s for s in r.errors), r.errors
    print("test_3d_small_domain_refine_errors PASS")


def test_inlet_outside_domain_errors():
    """Pipe span exceeding domain cross-axis → hard error."""
    bad_A = FluidCfg(dir=0, in_ctr=0.03, in_w=0.040,
                     out_ctr=0.03, out_w=0.040)  # H = 42 mm, so top = 50 mm
    r = compute_preflight(
        L=0.182, H=0.042, Lz=0.0,
        Nx=100, Ny=50, Nz=1, is_3d=False,
        wall_refine_3d=False,
        fluid_A=bad_A, fluid_B=None)
    assert r.errors, "expected an out-of-domain error"
    assert any("exceeds y domain" in s for s in r.errors), r.errors
    print("test_inlet_outside_domain_errors PASS")


def test_inlet_too_narrow_warns():
    """Pipe narrower than 3 uniform cells → warning, not error."""
    # 182 mm L / 10 Ny with partial inlet ≈ 4.2 mm wide → covers 1 cell of H=42/10=4.2mm cells
    r = compute_preflight(
        L=0.182, H=0.042, Lz=0.0,
        Nx=10, Ny=10, Nz=1, is_3d=False,
        wall_refine_3d=False,
        fluid_A=FluidCfg(dir=0, in_ctr=0.021, in_w=0.0042,
                         out_ctr=0.021, out_w=0.0042),
        fluid_B=None)
    assert not r.errors, r.errors
    assert any("covers only" in s and "y axis" in s for s in r.warnings), r.warnings
    print("test_inlet_too_narrow_warns PASS")


def test_richardson_huge_grid_warns():
    r = compute_preflight(
        L=0.182, H=0.042, Lz=0.0,
        Nx=500, Ny=400, Nz=1, is_3d=False,
        wall_refine_3d=False,
        fluid_A=_shanghai_A(), fluid_B=_shanghai_B_partial())
    assert any("Richardson" in s for s in r.warnings), r.warnings
    print("test_richardson_huge_grid_warns PASS")


def test_stream_axis_too_coarse_warns():
    r = compute_preflight(
        L=0.182, H=0.042, Lz=0.0,
        Nx=10, Ny=50, Nz=1, is_3d=False,
        wall_refine_3d=False,
        fluid_A=_shanghai_A(), fluid_B=_shanghai_B_partial())
    assert any("stream axis x" in s and "under-resolved" in s
               for s in r.warnings), r.warnings
    print("test_stream_axis_too_coarse_warns PASS")


def test_clean_pass_no_dialog():
    """Small but legal config → no errors, no warnings, and ok()==True."""
    r = compute_preflight(
        L=0.182, H=0.042, Lz=0.042,
        Nx=60, Ny=40, Nz=20, is_3d=True,
        wall_refine_3d=True,
        fluid_A=_shanghai_A(),
        fluid_B=FluidCfg(dir=3, in_ctr=0.091, in_w=0.182,
                         out_ctr=0.091, out_w=0.182))
    assert r.ok(), (r.errors, r.warnings)
    print("test_clean_pass_no_dialog PASS")


def test_t_in_swap_infos():
    """T_inA < T_inB must emit an info notice about B being the hot side.

    Demoted from warning to info on 2026-05-14: Q is unsigned post-Option-C
    so the reverse-ordering case is valid, not suspect. The notice still
    surfaces so the user knows which side is hot.
    """
    r = compute_preflight(
        L=0.182, H=0.042, Lz=0.042,
        Nx=30, Ny=20, Nz=5, is_3d=True,
        wall_refine_3d=True,
        fluid_A=_shanghai_A(), fluid_B=_shanghai_B_partial(),
        T_inA=300.0, T_inB=422.0)
    assert any("hot side" in s and "T_inA" in s for s in r.info), r.info
    # And specifically NOT in warnings (no blocking dialog).
    assert not any("hot side" in s for s in r.warnings), r.warnings
    print("test_t_in_swap_infos PASS")


def test_t_in_normal_no_warn():
    """Canonical Shanghai ordering (hot A, cold B) must not trigger the
    swap notice even when everything else is legal."""
    r = compute_preflight(
        L=0.182, H=0.042, Lz=0.042,
        Nx=30, Ny=20, Nz=5, is_3d=True,
        wall_refine_3d=True,
        fluid_A=_shanghai_A(), fluid_B=_shanghai_B_partial(),
        T_inA=422.0, T_inB=300.0)
    assert not any("hot side" in s for s in r.warnings), r.warnings
    assert not any("hot side" in s for s in r.info), r.info
    print("test_t_in_normal_no_warn PASS")


if __name__ == '__main__':
    test_shanghai_2d_partial_no_refine()
    test_full_width_2d_activates_refine()
    test_3d_wall_refine_fits()
    test_3d_small_domain_refine_errors()
    test_inlet_outside_domain_errors()
    test_inlet_too_narrow_warns()
    test_richardson_huge_grid_warns()
    test_stream_axis_too_coarse_warns()
    test_clean_pass_no_dialog()
    test_t_in_swap_infos()
    test_t_in_normal_no_warn()
    print("\nAll tests PASS")


# Each physical transverse axis matters at both ends, including ±z flow.


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('end', ['in', 'out'])
@pytest.mark.parametrize('second_axis', [False, True])
@pytest.mark.parametrize('failure', ['outside', 'empty', 'narrow'])
def test_each_port_span_is_checked(direction, end, second_axis, failure):
    from sjtu_tpmshx.domain.validator import cross_axes_for_dir
    axes = [axis.lower() for axis in cross_axes_for_dir(direction)]
    cfg = FluidCfg(direction, .021, .02, .021, .02,
                   z_in_ctr=.021, z_in_w=.02, z_out_ctr=.021, z_out_w=.02)
    prefix = 'z_' if second_axis else ''
    if failure == 'outside':
        setattr(cfg, f'{prefix}{end}_ctr', .8)
    else:
        setattr(cfg, f'{prefix}{end}_w', 0. if failure == 'empty' else .0001)
    report = compute_preflight(.182, .042, .042, 30, 30, 30, True, False, cfg)
    label = 'inlet' if end == 'in' else 'outlet'
    axis = axes[int(second_axis)]
    messages = report.warnings if failure == 'narrow' else report.errors
    assert any(f'Fluid A {label}' in m and
               (f'exceeds {axis} domain' if failure == 'outside' else f'{axis} axis') in m
               for m in messages), (report.errors, report.warnings)


@pytest.mark.parametrize('direction', [0, 4])
@pytest.mark.parametrize('end', ['in', 'out'])
@pytest.mark.parametrize('missing', ['ctr', 'w', 'both'])
@pytest.mark.parametrize('graded', [False, True])
def test_second_transverse_span_requires_a_complete_pair(direction, end, missing, graded):
    cfg = FluidCfg(direction, .021, .02, .021, .02,
                   z_in_ctr=.021, z_in_w=.02, z_out_ctr=.021, z_out_w=.02)
    for field in (('ctr', 'w') if missing == 'both' else (missing,)):
        setattr(cfg, f'z_{end}_{field}', None)
    report = compute_preflight(.182, .042, .042, 30, 30, 30, True, False, cfg,
                               port_wall_refine=graded)
    if missing == 'both':
        assert not report.errors, report.errors
    else:
        label = 'inlet' if end == 'in' else 'outlet'
        axis = 'y' if direction == 4 else 'z'
        assert any(f'Fluid A {label} {axis} centre and width must be set together' in error
                   for error in report.errors)
        assert not any(f'Fluid A {label} covers' in info and f'{axis} axis' in info
                       for info in report.info)
