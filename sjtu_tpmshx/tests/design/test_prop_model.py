"""物性模型 const/mean: const=入口温(默认), mean=均温 2-pass。

const 必须与历史一致 (回归); mean 在大 ΔT 改变结果、小 ΔT 收敛回 const;
prop_model 须穿过 solve_Lx 且二分仍收敛。"""
from __future__ import annotations
import importlib
import numpy as np
import pytest
from sjtu_tpmshx.design.cases import DesignCase
from sjtu_tpmshx.design.forward import forward


def _case(dT):  # 单工况空气-空气, 可调热侧温降 ΔT
    return DesignCase(1, "air", 900., 4e5, 0.05, "air", 300., 4e5, 0.05,
                      None, 0.08, 0.08, dT=dT)


def test_const_is_default_and_unchanged():
    c = _case(300.)
    r0 = forward(c, "Diamond", 7., 0.5, 0.084, 0.084, "cross")
    r1 = forward(c, "Diamond", 7., 0.5, 0.084, 0.084, "cross", prop_model="const")
    assert r0.T_out_hot == r1.T_out_hot          # 默认 == const


def test_mean_differs_for_large_dT():
    c = _case(300.)
    rc = forward(c, "Diamond", 7., 0.5, 0.084, 0.084, "cross", prop_model="const")
    rm = forward(c, "Diamond", 7., 0.5, 0.084, 0.084, "cross", prop_model="mean")
    assert abs(rm.T_out_hot - rc.T_out_hot) > 0.1   # mean 确改变结果


def test_mean_approx_const_for_small_dT():
    c = _case(5.)
    c.T_in_h = 310.
    rc = forward(c, "Diamond", 7., .5, .084, .084, "cross", prop_model="const")
    rm = forward(c, "Diamond", 7., .5, .084, .084, "cross", prop_model="mean")
    assert rc.run_status['converged'] and rm.run_status['converged']
    assert abs(rm.T_out_hot - rc.T_out_hot) < .5


def test_mean_threads_solve_Lx_and_converges():
    from sjtu_tpmshx.design.sizing import solve_Lx
    c = _case(300.)
    Lx, r = solve_Lx(c, "Diamond", 7., 0.5, 0.084, "cross", prop_model="mean")
    assert Lx is not None                          # mean 下二分收敛


@pytest.mark.parametrize('side,value', [(i, v) for i in range(3) for v in (np.nan, np.inf)])
def test_forward_rejects_nonfinite_external_seed_before_properties(monkeypatch, side, value):
    preparation = importlib.import_module('sjtu_tpmshx.preprocess.app_modes.quick_design')
    execution = importlib.import_module('sjtu_tpmshx.solvers.backends.cpp.quick_design')
    seed = [np.full((2, 2, 1), 400.) for _ in range(3)]
    seed[side][0, 0, 0] = value

    def unexpected(*args, **kwargs):
        pytest.fail('bad external seed reached geometry/properties/thermal solve')

    monkeypatch.setattr(preparation, 'tpms_geometry', unexpected)
    monkeypatch.setattr(execution, 'run_case', unexpected)
    case = _case(100.)
    case.T_in_h = 600.
    with pytest.raises(ValueError, match='design external warm start'):
        forward(case, 'Diamond', 7., .5, .084, .084, init=seed)
