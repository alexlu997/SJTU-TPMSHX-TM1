"""bc_to_dict (domain.compute_config) must reproduce the three legacy
_bc_cfg_to_dict_* functions it replaced (DUP-E / #8), including the
intentional side-B None asymmetry. Exhaustive over (dir, in_w, out_w, z)."""
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
