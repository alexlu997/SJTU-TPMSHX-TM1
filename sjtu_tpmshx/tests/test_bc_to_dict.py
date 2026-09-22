"""bc_to_dict (domain.compute_config) retains the supported legacy cases of
_bc_cfg_to_dict_* functions it replaced (DUP-E / #8), including the
intentional side-B None asymmetry, and independent 3D second-axis ports."""
import itertools

import pytest

from sjtu_tpmshx.domain.compute_config import PartialBCConfig, bc_to_dict


# ── Reference reimplementations of the deleted legacy functions ──────

def _ref_2d(bc, L, H):                       # was _bc_cfg_to_dict_2d
    cd = H if bc.dir in (0, 1) else L
    if bc.in_w > 0 and bc.out_w > 0:
        return dict(dir=bc.dir, in_ctr=bc.in_ctr, in_w=bc.in_w,
                    out_ctr=bc.out_ctr, out_w=bc.out_w)
    return dict(dir=bc.dir, in_ctr=cd / 2, in_w=cd,
                out_ctr=cd / 2, out_w=cd)


def _ref_3d_A(bc, L, H):                     # was _bc_cfg_to_dict_3d_A
    cd = H if bc.dir in (0, 1) else L
    if bc.in_w > 0 and bc.out_w > 0:
        d = dict(dir=bc.dir, in_ctr=bc.in_ctr, in_w=bc.in_w,
                 out_ctr=bc.out_ctr, out_w=bc.out_w)
    else:
        d = dict(dir=bc.dir, in_ctr=cd / 2, in_w=cd,
                 out_ctr=cd / 2, out_w=cd)
    if bc.in_z_ctr is not None:
        d['in_z_ctr'] = bc.in_z_ctr
        d['in_z_w'] = bc.in_z_w
        d['out_z_ctr'] = bc.out_z_ctr
        d['out_z_w'] = bc.out_z_w
    return d


def _ref_3d_B(bc):                           # was _bc_cfg_to_dict_3d_B
    if bc.in_w <= 0 and bc.out_w <= 0:
        return None
    d = dict(dir=bc.dir, in_ctr=bc.in_ctr, in_w=bc.in_w,
             out_ctr=bc.out_ctr, out_w=bc.out_w)
    if bc.in_z_ctr is not None:
        d['in_z_ctr'] = bc.in_z_ctr
        d['in_z_w'] = bc.in_z_w
        d['out_z_ctr'] = bc.out_z_ctr
        d['out_z_w'] = bc.out_z_w
    return d


def _mk(dir_, in_w, out_w, z):
    return PartialBCConfig(
        dir=dir_, in_ctr=0.3, in_w=in_w, out_ctr=0.4, out_w=out_w,
        in_z_ctr=(0.5 if z else None), in_z_w=(0.2 if z else None),
        out_z_ctr=(0.6 if z else None), out_z_w=(0.25 if z else None))


L_DOM, H_DOM = 0.182, 0.084


@pytest.mark.parametrize(
    "dir_,in_w,out_w,z",
    itertools.product((0, 1, 2, 3), (-1.0, 0.0, 0.5), (-1.0, 0.0, 0.7), (False, True)))
def test_bc_to_dict_matches_legacy(dir_, in_w, out_w, z):
    bc = _mk(dir_, in_w, out_w, z)
    # 2D path: both sides used the full-face (side='A') conversion, no z.
    assert bc_to_dict(bc, L_DOM, H_DOM, side='A', with_z=False) == _ref_2d(bc, L_DOM, H_DOM)
    # 3D side A: full-face fallback + z overlay.
    assert bc_to_dict(bc, L_DOM, H_DOM, side='A', with_z=True) == _ref_3d_A(bc, L_DOM, H_DOM)
    # 3D side B: None when fully degenerate, else raw partial dict + z.
    assert bc_to_dict(bc, L_DOM, H_DOM, side='B', with_z=True) == _ref_3d_B(bc)


def test_side_b_none_asymmetry():
    # fully degenerate side B -> None; side A -> full-face dict (not None)
    bc = _mk(0, 0.0, -1.0, False)
    assert bc_to_dict(bc, L_DOM, H_DOM, side='B', with_z=True) is None
    assert bc_to_dict(bc, L_DOM, H_DOM, side='A', with_z=True) is not None


def test_side_b_mixed_returns_raw_partial():
    # side B, one width >0 -> raw partial dict (no full-face fallback)
    bc = _mk(0, 0.5, -1.0, False)
    d = bc_to_dict(bc, L_DOM, H_DOM, side='B', with_z=True)
    assert d['in_w'] == 0.5 and d['out_w'] == -1.0


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('partial_port', ['in', 'out'])
def test_independent_cross2_window_reaches_prepared_physical_area(monkeypatch, direction, side, partial_port):
    import numpy as np
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.tests.test_pipeline_3d_e2e import _small_air_cfg
    from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime

    cfg = _small_air_cfg()
    cross1 = cfg.geometry.H_dom_m if direction < 2 else cfg.geometry.L_dom_m
    cross2 = cfg.geometry.H_dom_m if direction >= 4 else cfg.geometry.Lz_m
    width = .6 * cross1
    port = PartialBCConfig(dir=direction, in_ctr=cross1 / 2, in_w=width,
                           out_ctr=cross1 / 2, out_w=width)
    setattr(port, partial_port + '_z_ctr', cross2 / 2)
    setattr(port, partial_port + '_z_w', .2 * cross2)
    setattr(cfg, 'bc_' + side, port)
    case = prepare_case(cfg, case_id='independent-cross2-port')
    prepared = case.parameters['prepared']
    axis = prepared['axes'][side]
    areas = np.asarray(axis['dcross1'])[:, None] * np.asarray(axis['dcross2'])[None, :]
    for name, prefix in (('inlet', 'in'), ('outlet', 'out')):
        opening_area = np.sum(prepared['openings'][side][name] * areas)
        expected = width * cross2 * (.2 if prefix == partial_port else 1.)
        assert opening_area == pytest.approx(expected, rel=1e-12)
    # Runtime must carry the same physical rectangles into SIMPLE, including
    # the full-depth end whose second-axis pair was omitted.
    monkeypatch.setattr(runtime, '_run_two_simple', lambda *a, **k: None)
    parameters, data = build_execution_inputs(case)
    problem = runtime.build_problem(parameters, data)
    solver = getattr(problem, 's' + side)
    for name, prefix in (('inlet_frac', 'in'), ('outlet_frac', 'out')):
        expected = width * cross2 * (.2 if prefix == partial_port else 1.)
        assert np.sum(getattr(solver, name) * areas) == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('partial_port', ['in', 'out'])
@pytest.mark.parametrize('center,width,message', [
    (None, .006, 'set together'), (.015, None, 'set together'),
    (.015, -.006, 'must be > 0'), (.3, .006, 'leaves Z-range'),
])
def test_independent_cross2_invalid_pair_is_rejected(side, partial_port, center, width, message):
    from sjtu_tpmshx.tests.test_pipeline_3d_e2e import _small_air_cfg

    cfg = _small_air_cfg()
    port = PartialBCConfig(dir=0)
    setattr(port, partial_port + '_z_ctr', center)
    setattr(port, partial_port + '_z_w', width)
    setattr(cfg, 'bc_' + side, port)
    with pytest.raises(ValueError, match=message):
        cfg.validate()


def test_outlet_only_cross2_window_reaches_port_refined_grid():
    import numpy as np
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.tests.test_pipeline_3d_e2e import _small_air_cfg

    cfg = _small_air_cfg()
    cfg.solver.Nx, cfg.solver.Ny, cfg.solver.Nz = 12, 12, 32
    cfg.flags.port_wall_refine = True
    cfg.bc_A = PartialBCConfig(dir=0, out_z_ctr=.015, out_z_w=.006)
    case = prepare_case(cfg, case_id='refined-outlet-only')
    dz = case.grid['dz']
    assert not np.allclose(dz, np.mean(dz))
    for edge in (.012, .018):
        assert np.min(np.abs(case.grid['z_edges'] - edge)) < 1e-14
    prepared = case.parameters['prepared']
    axis = prepared['axes']['A']
    area = axis['dcross1'][:, None] * axis['dcross2'][None, :]
    assert np.sum(prepared['openings']['A']['inlet'] * area) == pytest.approx(.03 * .03)
    assert np.sum(prepared['openings']['A']['outlet'] * area) == pytest.approx(.03 * .006)


@pytest.mark.parametrize('end', ['in', 'out'])
@pytest.mark.parametrize('missing', ['ctr', 'w'])
def test_raw_cross2_half_pair_is_rejected_at_geometry_boundaries(end, missing):
    import numpy as np
    from sjtu_tpmshx.models.field_coordinates_3d import _build_partial_masks, _port_rectangles
    from sjtu_tpmshx.models.grid import port_wall_min_counts

    port = dict(dir=0, in_ctr=.015, in_w=.03, out_ctr=.015, out_w=.03)
    port.update({end + '_z_ctr': .015, end + '_z_w': .006})
    port[end + '_z_' + missing] = None
    widths = np.full(4, .03 / 4)
    with pytest.raises(ValueError, match='set together'):
        _build_partial_masks(port, widths, widths, 4)
    with pytest.raises(ValueError, match='set together'):
        _port_rectangles(port, .03)
    with pytest.raises(ValueError, match='set together'):
        port_wall_min_counts((.03, .03, .03), (port,))
