"""Quick-design budgets and analytical inlet-pressure preparation."""
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

