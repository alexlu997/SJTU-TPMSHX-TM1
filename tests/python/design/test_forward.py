from sjtu_tpmshx.applications.design.cases import DesignCase
from sjtu_tpmshx.applications.design.forward import forward, ForwardResult

def _case():
    return DesignCase(1,"air",688.23,1_088_700.0,0.2855,
                      "water",320.0,200_000.0,0.5,36_700.0,0.075,0.05)

def test_energy_balance_closes():
    r = forward(_case(), topo="Diamond", l=7.0, t=0.5,
                s=0.084, Lx=0.025, arrangement="cross")
    assert isinstance(r, ForwardResult)
    assert r.fields is not None                  # 供 warm-start
    # 热侧放热 ≈ 冷侧吸热 (2D LTNE 守恒, 粗网格容差 10%)
    assert abs(r.Q_hot - r.Q_cold) / max(abs(r.Q_hot),1.0) < 0.10
    assert r.T_out_hot < _case().T_in_h          # 热空气被冷却
    assert 0 < r.dP_hot_frac < 1
    # 冷侧 (水) 不可压 D-F; 修前 predict_dP_compressible 对水钳值 → dP_cold_frac=1.0 会失败
    assert 0 < r.dP_cold_frac < 1

def test_longer_Lx_cools_more():
    a = forward(_case(),"Diamond",7.0,0.5,0.084,0.015,"cross")
    b = forward(_case(),"Diamond",7.0,0.5,0.084,0.040,"cross")
    assert b.T_out_hot < a.T_out_hot              # Lx↑ → 出口更冷 (单调)

def test_counter_flow_energy_balance():
    # 逆流: B 沿 −x (Ny=1), 冷侧迎风 = s² (与 Lx 无关), 出口 i=0
    r = forward(_case(), "Diamond", 7.0, 0.5, s=0.084, Lx=0.05,
                arrangement="counter")
    assert isinstance(r, ForwardResult)
    assert r.fields is not None
    assert abs(r.Q_hot - r.Q_cold) / max(abs(r.Q_hot), 1.0) < 0.10  # 守恒
    assert r.T_out_hot < _case().T_in_h          # 热空气被冷却
    assert 0 < r.dP_hot_frac < 1 and 0 < r.dP_cold_frac < 1
