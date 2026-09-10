"""Prepared SIMPLE inputs cross the boundary without recomputing geometry/drag."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers import simple_solver as module


def test_prepared_mesh_and_drag_are_consumed_without_rebuilding(monkeypatch):
    kwargs = dict(W=.03, H=.04, Nx=3, Ny=4, tpms_type='Diamond',
                  L_cell_mm=6., t_mm=.4, eps=.8, r_h=.001,
                  rho=1.2, mu=1.8e-5, T_in=300., inlet_lo=0.,
                  inlet_hi=.03, v_inlet=1., wall_refine=False)
    original = module.SIMPLESolver(**kwargs)
    prepared = dict(dx_arr=original.dx_arr.copy(), dy_arr=original.dy_arr.copy(),
                    K_arr=original._K_arr.copy(), cF_arr=original._cF_arr.copy())

    def forbidden(*args, **kwargs):
        raise AssertionError('prepared execution rebuilt geometry or drag')

    monkeypatch.setattr(module, '_aligned_grid', forbidden)
    monkeypatch.setattr(module, 'predict_K_cF', forbidden)
    monkeypatch.setattr(module, 'predict_K_cF_vec', forbidden)
    solver = module.SIMPLESolver(**kwargs, **prepared)
    for key in ('dx_arr', 'dy_arr', '_K_arr', '_cF_arr', 'u', 'v', 'P',
                'inlet_frac', 'outlet_frac', 'rho_field', '_mu_eff_field'):
        np.testing.assert_array_equal(getattr(solver, key), getattr(original, key))
    prepared['K_arr'][:] = 1.
    np.testing.assert_array_equal(solver._K_arr, original._K_arr)
    for bad in (dict(dx_arr=np.ones(3)), dict(dy_arr=np.zeros(4)),
                dict(K_arr=np.zeros(4)), dict(cF_arr=np.full(4, np.nan))):
        with pytest.raises(ValueError, match='prepared SIMPLE'):
            module.SIMPLESolver(**kwargs, **{**prepared, **bad})
