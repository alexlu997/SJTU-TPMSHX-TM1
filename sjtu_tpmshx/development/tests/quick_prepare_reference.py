"""Frozen Quick preparation reference from 2026-11-12 before N12.

This test-only implementation supplies an independent sequence reference.
Retain it while raw preparation comparisons require the original contract.
It must never be imported by production code.
"""
from sjtu_tpmshx.shared.domain.run_warnings import range_context
from sjtu_tpmshx.shared.models.tpms_calc import geometry as tpms_geometry
from sjtu_tpmshx.shared.df_surrogate.predict import predict_dP_compressible, predict_dP
from sjtu_tpmshx.shared.models.design_fluids import fluid_props
from sjtu_tpmshx.shared.models import _native_flow

K_STEEL = 16.0
NX, NY_CROSS = 60, 40
LTNE_TOL = 1e-5
# G2 自适应早停: 收敛即停 (代替烧满 max_iter)。内核默认收敛阈 (2D 2e-7 / 3D 1e-3)
# 对 sizing 要么太严永不触发 (2D → 烧满 8000 sweep, 实需 ~200), 要么 chunk=500 太粗。
# 设计路径传有意义且会触发的阈: Q 相对变化 <1e-4 + (2D 还需) T 漂移 <0.01K, 每 100
# sweep 查一次 → T_out 在 ~200 sweep 即定, 同收敛解但 ~5-10× 少 sweep。仅 design opt-in;
# 内核默认 (None) 对 Shanghai/MMS/优化器逐位不变。
SIZING_QTOL = 1e-4
SIZING_CHUNK = 100
# 几何体素化分辨率。设计路径只需标量 (eps/A_0/D_h), N=128 vs 256 误差 eps<0.08%
# / A_0<0.5% (远低于模型 ~10% Nu/dP 不确定度), 但内存 8×↓ (128MiB→16MiB phi grid)。
# 关键: enumerate_select 全核 loky 并行, 各进程 lru_cache 不共享 → 各自重建 phi grid;
# N=256 时 16 进程 × 2 拓扑 × 128MiB ≈ 4GiB 常驻 → MemoryError。N=128 解此瓶颈。
GEOM_N = 128
# dir 编码 (verified vs ltne_energy_3d docstring): 0=+x, 1=−x, 2=+y, 3=−y
# 内核选择: 叉流走 2D 内核 (Nz=1, 垂直流股稳定快)。逆流两股同轴反向, 2D 内核
# solve_full_domain 无欠松弛 → 极限环 (水出口 347↔357 跳, 能量不平衡 7-33%);
# 改走 3D 内核 (Nz=2) + 低 α 欠松弛阻尼 → 稳定收敛 (实证 α=0.3 gap 0.4%, 各
# max_iter 字节一致)。详见 vault .../2026-05-26-quick-design-tool-plan §执行修正。
# qtol/chunk = G2 自适应早停参数 (传入 LTNE 内核)。
# cross (2D 内核): 旧默认收敛阈 2e-7 永不触发 → 烧满 8000; 传 (1e-4, 100) 早停 ~200 sweep。
# counter (3D 内核, α=0.3 欠松弛): 旧默认 (q_rel=1e-3@tol1e-4, chunk500) 已正常早停 ~2000
#   sweep; 小 chunk 会在欠松弛慢漂中误判早停 (实测 3.3K 偏差) → 保持 None (内核默认不变)。
_ARR = {
    "cross":   dict(dirB=2, ny=NY_CROSS, nz=1, alpha=0.7, maxit=8000,
                    qtol=SIZING_QTOL, chunk=SIZING_CHUNK),
    "counter": dict(dirB=1, ny=1,        nz=2, alpha=0.3, maxit=20000,
                    qtol=None, chunk=None),
}

def _dp_one(fluid, topo, l, t, eps_A, mdot, A_flow, T, P, props, L_chan, *, df_options=None):
    """单股压损 [Pa]。air→可压缩理想气体 D-F (predict_dP_compressible);
    water/不可压→不可压 D-F (predict_dP)。两者共用同一 K/c_F 几何闭合, 仅密度处理不同:
    可压版内嵌 ρ=P/(R_AIR·T) (气体专用), 不可压版传入常数 ρ。A_flow=开口迎风面积 ε_A·迎风。"""
    options = dict(df_options or {})
    G, u = _native_flow.quick_design_flow(mdot, A_flow, 0. if fluid == 'air' else props.rho, fluid == 'air')
    if fluid == "air":
        return predict_dP_compressible(topo, l, t, eps_A, G, T, P, props.mu, L_chan, **options)
    return predict_dP(topo, l, t, eps_A, u, props.rho, props.mu, L_chan, **options)


def dP_fracs(case, topo, l, t, s, Lx, arrangement="cross", height=None, *, df_options=None):
    """两侧归一化前压损分数 (纯解析 D-F, 不触发 LTNE 解)。返回 (dP_h_frac, dP_c_frac)。
    按流体分派 (air 可压 / water 不可压); 迎风面积按流向取 (叉流冷侧 +y → Lx·s)。
    height: 矩形迎风时高(z)向尺寸 [m]; None → 方形 (s_z=s, 现状/UI 默认)。"""
    sz = s if height is None else height          # z(高)向跨度
    geo = tpms_geometry(topo, l, t, K_STEEL, N=GEOM_N); EPS_A = geo["epsilon_A"]
    return _dp_fractions(case, topo, l, t, EPS_A, s, Lx, arrangement, sz, df_options=df_options)


def _dp_fractions(case, topo, l, t, EPS_A, s, Lx, arrangement, sz, *, df_options=None):
    with range_context(side='A', stage='design-dp-inlet', layout='scalar'):
        pA = fluid_props(case.hot_fluid, case.T_in_h, case.P_in_h)
    with range_context(side='B', stage='design-dp-inlet', layout='scalar'):
        pB = fluid_props(case.cold_fluid, case.T_in_c, case.P_in_c)
    A_h, L_h, A_c, L_c = _native_flow.quick_design_sections(EPS_A, s, Lx, sz, arrangement == 'cross')
    with range_context(side='A', stage='design-dp-inlet', layout='scalar'):
        dP_h = _dp_one(case.hot_fluid, topo, l, t, EPS_A, case.mdot_h, A_h,
                       case.T_in_h, case.P_in_h, pA, L_h, df_options=df_options)
    with range_context(side='B', stage='design-dp-inlet', layout='scalar'):
        dP_c = _dp_one(case.cold_fluid, topo, l, t, EPS_A, case.mdot_c, A_c,
                       case.T_in_c, case.P_in_c, pB, L_c, df_options=df_options)
    return (_native_flow.relative_pressure(dP_h, case.P_in_h),
            _native_flow.relative_pressure(dP_c, case.P_in_c))


from dataclasses import asdict

import numpy as np

from sjtu_tpmshx.shared.domain.case_data import CaseData
from sjtu_tpmshx.shared.domain.model_refs import ModelRef
from sjtu_tpmshx.shared.domain.run_environment import capture_environment
from sjtu_tpmshx.shared.models.catalog import MODEL_VERSIONS
from sjtu_tpmshx.shared.models import _native_geometry
from sjtu_tpmshx.shared.models.fluid_props import check_finite_temperatures
from sjtu_tpmshx.shared.df_surrogate.predict import (
    _resolve_method,
)


def prepare_quick_design(case, topo, l, t, s, Lx, arrangement='cross', *,
                         case_id, init=None, k_s=K_STEEL, prop_model='const',
                         tol=LTNE_TOL, height=None):
    if init is not None:
        check_finite_temperatures(*init, where='design external warm start')
    if arrangement not in _ARR or prop_model not in ('const', 'mean'):
        raise ValueError('unsupported quick-design arrangement or property model')
    sz = s if height is None else height
    for name, value in dict(l=l, t=t, s=s, Lx=Lx, height=sz, k_s=k_s, tol=tol,
                            mdot_h=case.mdot_h, mdot_c=case.mdot_c,
                            T_in_h=case.T_in_h, T_in_c=case.T_in_c,
                            P_in_h=case.P_in_h, P_in_c=case.P_in_c).items():
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f'quick-design {name} must be finite and positive')
    arr = _ARR[arrangement]
    shape = (NX, arr['ny'], arr['nz'])
    if init is not None and (len(init) != 3 or any(np.shape(a) != shape for a in init)):
        raise ValueError('quick-design warm start must match the prepared grid')
    geo = tpms_geometry(topo, l, t, k_s, N=GEOM_N)
    grid = dict(dimension=3, length_unit='m', axis_order=('x', 'y', 'z'))
    for axis, count, length in zip('xyz', shape, (Lx, s, sz)):
        widths = _native_flow.uniform_widths(count, length)
        grid['d' + axis] = widths
        grid[axis + '_edges'] = np.r_[0., np.cumsum(widths)]
    inputs = {name: getattr(case, name) for name in
              ('hot_fluid', 'cold_fluid', 'T_in_h', 'T_in_c', 'P_in_h', 'P_in_c', 'mdot_h', 'mdot_c')}
    df_options = dict(method=_resolve_method())
    fractions = _dp_fractions(case, topo, l, t, geo['epsilon_A'], s, Lx,
                              arrangement, sz, df_options=df_options)
    return CaseData(
        case_id=case_id, config_snapshot=asdict(case), grid=grid,
        design_fields=dict(eps=np.full(shape, geo['epsilon']),
                           eps_A=np.full(shape, geo['epsilon_A']),
                           K_ss=np.full(shape, _native_geometry.material_fields(
                               topo, geo['epsilon'], k_s, chi_s=1.)['K_ss'][()])),
        parameters=dict(operating_point=inputs, topology=topo, L_cell_m=l / 1000.,
                        t_wall_m=t / 1000., Lx=Lx, s=s, height=sz,
                        k_s=k_s, A_0=geo['A_0'], D_h=geo['D_h'],
                        arrangement=arrangement, prop_model=prop_model, tol=tol,
                        controls={key: value for key, value in arr.items() if key not in ('ny', 'nz')}, initial_fields=init,
                        df_options=df_options, _environment=capture_environment(),
                        inlet_pressure_fractions=dict(zip(('A', 'B'), fractions))),
        model_refs=(ModelRef('quick_design', MODEL_VERSIONS['quick_design']),
                    ModelRef('fluid', MODEL_VERSIONS['fluid'], {'fluid': case.hot_fluid}),
                    ModelRef('fluid', MODEL_VERSIONS['fluid'], {'fluid': case.cold_fluid})),
        metadata=dict(mode='quick_design', model='plug_ltne_analytic_dp_v1',
                      quantity_basis='total', geometry_resolution=GEOM_N,
                      thermal_kernel=('2d_delegation' if shape[2] == 1 else '3d'),
                      applicability='Sizing approximation; prescribed velocity, analytical inlet-state dP; not full SIMPLE or experimental validation.'))
