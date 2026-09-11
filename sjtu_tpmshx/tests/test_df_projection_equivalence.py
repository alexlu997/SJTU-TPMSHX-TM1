"""B2 2.3 — df_projection refactor equivalence vs pre-refactor baseline.

tests/_data_df_projection_baseline.json was captured from the
pre-refactor projectors (2026-06-12) on deterministic synthetic fields:
2D + 3D × fluid A/B × uniform/non-uniform streamwise (and z) spacings.
The shared-helper extraction (_cell_centre_fracs / _nearest_src_idx /
_stream_profile) must reproduce every value within cross-platform floating
point tolerance; the golden 3D gate runs uniform cfgs only, so this file is
the gate for the projector. The captured baseline used gamma_df, so this test
pins that research backend; production closure selection is tested separately.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from sjtu_tpmshx.solvers.df_projection import (_cell_centre_fracs, _nearest_src_idx,
                                   project_fields_to_streamwise_K_cF as p2d,
                                   project_fields_to_streamwise_K_cF_3d as p3d)
from sjtu_tpmshx.models.tpms_calc import geometry as _geom

_BASE = json.loads(
    (Path(__file__).parent / '_data_df_projection_baseline.json')
    .read_text(encoding='utf-8'))

_NX, _NY, _NZ = 9, 7, 5
_DX_NU = np.array([1.0, 1.5, 0.5, 2.0, 1.0, 0.8])
_ZDX_NU = np.array([1.0, 0.5, 1.5, 1.0])


@pytest.fixture(autouse=True)
def _captured_backend(monkeypatch):
    monkeypatch.setenv('TPMSHX_DF_METHOD', 'gamma_df')


def _fields_2d():
    ii, jj = np.meshgrid(np.arange(_NX), np.arange(_NY), indexing='ij')
    L2 = 5.0 + 2.0 * np.sin(0.3 * ii + 0.5 * jj)
    t2 = 0.40 + 0.08 * np.cos(0.4 * ii - 0.2 * jj)
    return L2, t2


def _fields_3d():
    ii, jj, kk = np.meshgrid(np.arange(_NX), np.arange(_NY), np.arange(_NZ),
                             indexing='ij')
    L3 = 5.0 + 1.5 * np.sin(0.3 * ii + 0.4 * jj + 0.2 * kk)
    t3 = 0.40 + 0.07 * np.cos(0.2 * ii - 0.3 * jj + 0.1 * kk)
    e3 = np.empty_like(L3)
    for a in range(_NX):
        for b in range(_NY):
            for c in range(_NZ):
                e3[a, b, c] = _geom(
                    'Gyroid', float(np.round(L3[a, b, c], 4)),
                    float(np.round(t3[a, b, c], 4)), 16.0)['epsilon'] / 2
    return L3, t3, e3


@pytest.mark.parametrize('fluid', ('A', 'B'))
@pytest.mark.parametrize('tag,dx', (('uni', None), ('nonuni', _DX_NU)))
def test_2d_projector_baseline_cross_platform(fluid, tag, dx):
    L2, t2 = _fields_2d()
    K, cF = p2d(L2, t2, 'Gyroid', 16.0, _NX, _NY, 6, fluid,
                streamwise_dx=dx)
    K_ref, cF_ref = _BASE[f'2d_{fluid}_{tag}']
    np.testing.assert_allclose(K, K_ref, rtol=1e-12, atol=0.0)
    np.testing.assert_allclose(cF, cF_ref, rtol=1e-12, atol=0.0)


@pytest.mark.parametrize('fluid', ('A', 'B'))
@pytest.mark.parametrize('tag,sdx,zdx', (('uni', None, None),
                                         ('nonuni', _DX_NU, _ZDX_NU)))
def test_3d_projector_baseline_cross_platform(fluid, tag, sdx, zdx):
    L3, t3, e3 = _fields_3d()
    K, cF = p3d(L3, t3, e3, 'Gyroid', 6, 4, fluid,
                streamwise_dx=sdx, z_dx=zdx)
    K_ref, cF_ref = _BASE[f'3d_{fluid}_{tag}']
    np.testing.assert_allclose(K.ravel(), K_ref, rtol=1e-12, atol=0.0)
    np.testing.assert_allclose(cF.ravel(), cF_ref, rtol=1e-12, atol=0.0)


def test_helper_semantics():
    """Uniform fracs == (i+0.5)/n; non-uniform integrate widths; index
    mapping reproduces the retired int(min(...)) form for in-range fracs."""
    f = _cell_centre_fracs(4, None)
    assert np.allclose(f, [0.125, 0.375, 0.625, 0.875])
    fn = _cell_centre_fracs(2, np.array([3.0, 1.0]))
    assert np.allclose(fn, [0.375, 0.875])
    idx = _nearest_src_idx(np.array([0.0, 0.49, 0.99, 1.0]), 10)
    assert idx.tolist() == [0, 4, 9, 9]


def test_invalid_fluid_raises():
    L2, t2 = _fields_2d()
    with pytest.raises(ValueError, match="fluid must be"):
        p2d(L2, t2, 'Gyroid', 16.0, _NX, _NY, 6, 'C')
