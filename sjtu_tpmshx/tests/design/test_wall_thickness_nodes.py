"""壁厚 t=0.3 / 0.6 必须可参与计算 (无硬性域阻断)。

当前固定CFD资源覆盖 t=0.3–0.6 mm；两个端点均应可计算，不能被域守卫拒绝。
本测试是闭合级廉价守护 (不跑 LTNE 解), 防回归。
"""
import math

from sjtu_tpmshx.models.tpms_calc import geometry, nu_from_Re
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF, predict_dP_compressible


def test_closures_accept_t_0p3_and_0p6():
    for t in (0.3, 0.6):
        g = geometry("Diamond", 7.0, t, 16.0)
        epsA, Dh = g["epsilon_A"], g["D_h"]
        assert 0.0 < epsA < 0.5 and Dh > 0.0          # geometry 有效
        K, cF = predict_K_cF("Diamond", 7.0, t, epsA)
        assert K > 0.0 and cF > 0.0                    # D-F 渗透率有限正值
        nu = nu_from_Re("Diamond", 5000.0, epsA, 7.0, Dh * 1e3)
        assert nu > 0.0                                # Nu 有限
        dp = predict_dP_compressible("Diamond", 7.0, t, epsA,
                                     100.0, 650.0, 1e6, 3e-5, 0.05)
        assert math.isfinite(dp) and dp > 0.0          # dP 有限


def test_default_enumeration_nodes_include_t_0p6():
    from sjtu_tpmshx.design.select import NODES
    assert 0.3 in NODES["t"]
    assert 0.6 in NODES["t"]
