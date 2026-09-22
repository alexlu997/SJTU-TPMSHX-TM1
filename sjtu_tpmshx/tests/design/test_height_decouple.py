"""矩形迎风解耦守护: height=s 必须等价方形 (height=None), 且 height≠s 真生效。

锁不变量 — 给 forward/dP_fracs 加的 height 参数, 当 sz=s 时逐位回到旧方形物理
(UI 走方形, 此测试保护该路径); height≠s 时水侧迎风/压损必须随之改变 (解耦有效)。
"""
import math

from sjtu_tpmshx.design.cases import DesignCase
from sjtu_tpmshx.design.forward import forward
from sjtu_tpmshx.models.quick_design import dP_fracs


def _case():
    return DesignCase(
        case=1, hot_fluid="air", T_in_h=344.15, P_in_h=145e3, mdot_h=0.381,
        cold_fluid="water", T_in_c=311.15, P_in_c=1.0e6, mdot_c=1.111,
        Q=10_000.0, dPlim_h=1.0, dPlim_c=1.0, dT=26.0)


S, LX = 0.30, 0.05


def test_dpfracs_height_eq_s_is_square():
    c = _case()
    a0 = dP_fracs(c, "Diamond", 6.0, 0.4, S, LX, "cross")
    a1 = dP_fracs(c, "Diamond", 6.0, 0.4, S, LX, "cross", height=S)
    assert math.isclose(a0[0], a1[0], rel_tol=1e-12, abs_tol=0.0)
    assert math.isclose(a0[1], a1[1], rel_tol=1e-12, abs_tol=0.0)


def test_forward_height_eq_s_is_square():
    c = _case()
    r0 = forward(c, "Diamond", 6.0, 0.4, S, LX, "cross", prop_model="const")
    r1 = forward(c, "Diamond", 6.0, 0.4, S, LX, "cross", prop_model="const", height=S)
    assert math.isclose(r0.T_out_hot, r1.T_out_hot, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(r0.T_out_cold, r1.T_out_cold, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(r0.Q_hot, r1.Q_hot, rel_tol=1e-12, abs_tol=1e-6)
    assert math.isclose(r0.dP_hot_frac, r1.dP_hot_frac, rel_tol=1e-12, abs_tol=0.0)
    assert math.isclose(r0.dP_cold_frac, r1.dP_cold_frac, rel_tol=1e-12, abs_tol=0.0)


def test_rect_height_changes_water_side():
    """height≠s: 水侧迎风随 z 高变 → 水侧 dP 必须不同 (证解耦真起作用)。"""
    c = _case()
    sq = dP_fracs(c, "Diamond", 6.0, 0.4, S, LX, "cross")
    rect = dP_fracs(c, "Diamond", 6.0, 0.4, S, LX, "cross", height=0.75)
    # 两侧迎风都含 sz → height≠s 时两侧 dP 均改变 (rect sz 大 → 迎风大 → 流速/压损低)
    assert not math.isclose(sq[0], rect[0], rel_tol=1e-3)   # 气侧 dP 改变
    assert not math.isclose(sq[1], rect[1], rel_tol=1e-3)   # 水侧 dP 改变


def test_nu_re_window_per_fluid():
    from sjtu_tpmshx.models.design_fluids import nu_re_window, NU_RE_FIT_RANGE, WATER_NU_RE_RANGE
    assert nu_re_window("air") == NU_RE_FIT_RANGE        # (400, 16000)
    assert nu_re_window("water") == WATER_NU_RE_RANGE     # 拓扑专属新式 (90, 51000)
    assert WATER_NU_RE_RANGE == (90.0, 51000.0)            # 2026-07-23 重拟窗口


def test_design_validity_fields_default():
    from sjtu_tpmshx.design.sizing import Design
    d = Design(False)
    assert d.height == 0.0 and d.validity == ""
    assert d.Re_hot_max == 0.0 and d.Re_cold_max == 0.0
