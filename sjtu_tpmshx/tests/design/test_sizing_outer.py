from sjtu_tpmshx.design.cases import DesignCase
from sjtu_tpmshx.design.sizing import size_fixed_cell
import pytest


@pytest.mark.parametrize('arrangement', ['cross', 'counter'])
@pytest.mark.parametrize('n_cases,boundary', [
    (1, .4498), (1, .45), (1, .46),
    (2, .3), (2, .45), (2, .46),
])
def test_width_endpoint_feasibility(monkeypatch, arrangement, n_cases, boundary):
    """Controlled thermal response, real length and width search; no PDE claim."""
    from sjtu_tpmshx.design import sizing
    from sjtu_tpmshx.design.forward import ForwardResult
    cases = [DesignCase(i, 'air', 400., 2e5, .01, 'air', 300., 2e5, .01,
                        None, .05, .05, dT=50. if i == 1 else 10.)
             for i in range(1, n_cases + 1)]
    calls = []

    def thermal(case, topo, l, t, s, length, arrangement, **kwargs):
        calls.append((case.case, s, length, kwargs.get('init')))
        drop = (50. * length / .03 if n_cases == 2 and case.case == 1
                else case.dT * (s / boundary) * (length / sizing.LX_MAX))
        return ForwardResult(400. - drop, 310., 100., 100., .001, .001,
                             1000., 1000., run_status={'converged': True})

    monkeypatch.setattr(sizing, 'forward', thermal)
    monkeypatch.setattr(sizing, 'tpms_geometry', lambda *a, **kw: {'epsilon': .8})
    monkeypatch.setattr(sizing, 'dP_fracs', lambda *a, **kw: (.001, .001))
    design = sizing.size_fixed_cell(cases, 'Diamond', 7., .5,
                                    arrangement=arrangement)
    if boundary > sizing.S_MAX:
        assert not design.feasible and design.reason == 'cooling-unreachable'
    else:
        assert design.feasible, design.reason
        assert boundary <= design.s <= sizing.S_MAX
        assert 0. < design.Lx <= sizing.LX_MAX
        assert len(design.percase) == n_cases
        for case, row, final_call in zip(cases, design.percase, calls[-n_cases:]):
            assert row['T_air_out'] <= case.T_in_h - case.dT
            assert row['dP_hot_frac'] <= case.dPlim_h
            assert row['dP_cold_frac'] <= case.dPlim_c
            assert row['run_status']['converged']
            assert final_call == (case.case, design.s, design.Lx, None)

def _cases():
    return [DesignCase(1,"air",688.23,1_088_700.0,0.2855,
                       "water",320.0,200_000.0,0.5,30_000.0,0.075,0.05)]

def test_size_returns_feasible_within_envelope():
    d = size_fixed_cell(_cases(), "Diamond", 7.0, 0.5, arrangement="cross")
    if d.feasible:
        assert 0 < d.s <= 0.450 and 0 < d.Lx <= 0.450
        assert d.dP_hot_max <= 0.075 + 1e-6          # 热侧 ≤ dPlim_h
        assert d.dP_cold_max <= 0.05 + 1e-6          # 冷侧 ≤ dPlim_c
        assert d.weight > 0                          # (1-ε)·V·ρ_s
    else:
        assert d.reason in ("dP>lim@s_max", "dP>lim@final",
                            "cooling-unreachable", "Lx>envelope")

def test_size_counter_flow():
    # 逆流 (Nz=2 内核 + 低 α, 不再极限环): 整条定尺管线应给出可行或带 reason
    d = size_fixed_cell(_cases(), "Diamond", 7.0, 0.5, arrangement="counter")
    if d.feasible:
        assert 0 < d.s <= 0.450 and 0 < d.Lx <= 0.450
        assert d.dP_hot_max <= 0.075 + 1e-6
        assert d.dP_cold_max <= 0.05 + 1e-6
        assert d.weight > 0
    else:
        assert d.reason in ("dP>lim@s_max", "dP>lim@final",
                            "cooling-unreachable", "Lx>envelope")

def test_allK_boundary_correction_counter():
    # 回归: governing 代理可行边界可能 < 全-K 边界 → golden 精准落缝, 误判 dP>lim@final。
    # 修后须向上二分到全-K 可行边界。3 工况 air-air counter (template 同形) 该构型本可行,
    # 细扫全-K 在 s≈108mm 起可行 (V≈0.37L); 修前 golden 选 s≈107 全-K 失败误判不可行。
    cs = [DesignCase(1, "air", 688.0, 1_089_000.0, 0.2855, "air", 320.0, 300_000.0, 0.3, 30_000.0, 0.075, 0.05),
          DesignCase(2, "air", 700.0, 1_000_000.0, 0.25,   "air", 320.0, 300_000.0, 0.3, None, 0.07, 0.05, dT=100.0),
          DesignCase(3, "air", 650.0,   900_000.0, 0.3,    "air", 315.0, 250_000.0, 0.35, 28_000.0, 0.08, 0.05)]
    d = size_fixed_cell(cs, "Gyroid", 8.0, 0.5, arrangement="counter")
    assert d.feasible                                  # 不再误判
    assert d.dP_hot_max <= 0.08 + 1e-6 and d.dP_cold_max <= 0.05 + 1e-6  # 全-K dP 真达标
    assert 0 < d.s <= 0.450 and 0 < d.Lx <= 0.450


def test_infeasible_carries_identity():
    # 不可行件须带 topo/l/t/arrangement (否则汇总表全塌成 _l0_t0/cross, 看不出哪个构型为何失败)。
    # 物理不可能: dT=400 → 目标出口 288K < 冷侧入口 320K (违反二定律) → 任何几何冷却不可达。
    c = [DesignCase(1, "air", 688.0, 1_089_000.0, 0.2855,
                    "air", 320.0, 300_000.0, 0.3, None, 0.075, 0.05, dT=400.0)]
    d = size_fixed_cell(c, "Gyroid", 8.0, 0.6, arrangement="counter")
    assert not d.feasible                      # 冷却不可达 → 不可行
    assert d.topo == "Gyroid" and d.l == 8.0 and d.t == 0.6   # 身份保留
    assert d.arrangement == "counter"          # 布置非默认 cross
    assert d.reason                            # 有失败原因


def test_golden_finds_feasible_min_v():
    # 黄金分割 s-搜索 (C) 应找到可行 min-V, 且优于旧 20 点网格 (步长 22mm 漏真min)。
    # 空气-空气 ΔT=300 工况: golden 解 ~0.193L (旧网格 0.222L)。锚定改进 + 可行性。
    c = [DesignCase(1, "air", 900., 4e5, 0.05, "air", 300., 4e5, 0.05,
                    None, 0.08, 0.08, dT=300.)]
    d = size_fixed_cell(c, "Diamond", 7.0, 0.5, arrangement="cross")
    assert d.feasible
    assert d.dP_hot_max <= 0.08 + 1e-6 and d.dP_cold_max <= 0.08 + 1e-6
    assert d.T_out_hot_max <= 600.0 + 0.5            # 冷到目标
    assert d.V * 1e3 < 0.210                         # 优于旧网格 0.222L (golden ≈0.193)


def test_size_two_cases_governing():
    # 多工况: governing 0-D 预选 + 全 K 终验; 返回的单 (s,Lx) 须满足两工况
    cases = [
        DesignCase(1,"air",688.23,1_088_700.0,0.2855,
                   "water",320.0,200_000.0,0.5,30_000.0,0.075,0.05),
        DesignCase(2,"air",700.0,1_050_000.0,0.30,
                   "water",325.0,200_000.0,0.55,34_000.0,0.075,0.05),
    ]
    d = size_fixed_cell(cases, "Diamond", 7.0, 0.5, arrangement="cross")
    if d.feasible:
        assert 0 < d.s <= 0.450 and 0 < d.Lx <= 0.450
        assert d.dP_hot_max <= 0.075 + 1e-6          # 全K 热侧 max ≤ lim
        assert d.dP_cold_max <= 0.05 + 1e-6          # 全K 冷侧 max ≤ lim
        assert d.T_out_hot_max < 700.0               # 两工况都被冷却
        assert d.weight > 0
    else:
        assert d.reason in ("dP>lim@s_max", "dP>lim@final",
                            "cooling-unreachable", "Lx>envelope")
