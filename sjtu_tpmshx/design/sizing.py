"""定尺: 每个 s 内定 Lx = max(冷却所需, 满足两侧 dP 所需), 对 s 求 min-V。
单模块 ≤ 450mm。叉流冷侧迎风 = Lx·s (随 Lx 变) → 冷侧 dP 紧时须加厚 Lx,
不能只取冷却最小值 (否则薄板憋水, 误报不可行)。逆流冷侧迎风 = s² (与 Lx 无关)。"""
from __future__ import annotations
import os
import math
from dataclasses import dataclass, field

from scipy.optimize import brentq
from sjtu_tpmshx.domain.run_warnings import warning_scope, warning_messages
from sjtu_tpmshx.domain.module_ports import RunControl

from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry
from sjtu_tpmshx.models.design_fluids import fluid_props, nu_re_window
from .forward import forward
from sjtu_tpmshx.models.quick_design import dP_fracs, K_STEEL, GEOM_N, LTNE_TOL

DP_DEGEN_FRAC = 0.30      # 单侧归一化压损 > 此 = 压降近进口压 → 退化 (超音速/迎风缩崩)

# Build envelope [m]. Read from env AT IMPORT so loky-spawned sizing workers
# (fresh re-import in a child process) pick up a relaxed cap set by the parent
# BEFORE import — a parent-process module-global mutation (the old
# `SZ.S_MAX = 2.0`) does NOT propagate to spawned workers (audit: r2-runs-01).
# Default = 0.450 m AM build limit; the UI / default path is unaffected.
S_MAX = float(os.environ.get("TPMSHX_BUILD_S_MAX", "0.450"))
LX_MAX = float(os.environ.get("TPMSHX_BUILD_LX_MAX", "0.450"))
N_MIN = 4              # 每向最少晶胞 (均质化)
BISECT_IT, TOL = 28, 1e-4
SIZING_TOL = 1e-4      # 定尺搜索期放松 LTNE 残差 (终点再用 LTNE_TOL 收紧)
GOLDEN_IT = 10         # min-V over s 黄金分割步数 (~12 解, s 分辨率 <5mm; 优于旧 20 网格 22mm)
S_REFINE_TOL = 0.004   # s 区间收敛阈 [m] (4mm)

def t_target(case) -> float:
    """热侧出口温目标: 优先用温降 ΔT, 否则由换热量 Q 反推。"""
    if case.dT is not None:
        return case.T_in_h - case.dT
    cp_h = fluid_props(case.hot_fluid, case.T_in_h, case.P_in_h).cp
    return case.T_in_h - case.Q / (case.mdot_h * cp_h)

def solve_Lx(case, topo, l, t, s, arrangement, target=None, k_s=K_STEEL,
             prop_model="const", seed=None, height=None, control=None):
    """求 Lx ∈ (0, LX_MAX] 使 T_out_hot = target (T_out 随 Lx 单调↓)。
    B: 用 brentq (超线性) 代替二分 → ~3× 少解。
    A: seed=(Ta,Tb,Ts) 跨-s 续解种子 (s 平滑变, 场近似); ev 内每步续解。
    D: 搜索用 SIZING_TOL (松), 终点用 LTNE_TOL (紧) → 渐进收紧。
    height: 矩形迎风高 (None=方形); 透传 forward。
    返回 (Lx, ForwardResult)。不可达 (LX_MAX 仍欠冷) → (None, None)。"""
    tgt = target if target is not None else t_target(case)
    control = control or RunControl()
    prev = {"f": seed, "last": None}
    forward_failed = False
    def ev(Lx, tol):
        nonlocal forward_failed
        control.check_cancelled()
        try:
            r = forward(case, topo, l, t, s, Lx, arrangement, init=prev["f"],
                        k_s=k_s, prop_model=prop_model, tol=tol, height=height,
                        control=control)
        except ValueError:
            forward_failed = True
            raise
        prev["f"] = r.fields                # 续解种子 (链式)
        prev["last"] = r
        return r
    lo, hi = max(2.0 * l / 1000.0, 1e-3), LX_MAX
    f_hi = ev(hi, SIZING_TOL).T_out_hot - tgt
    if f_hi > 0:                             # 最长也欠冷
        return None, None
    f_lo = ev(lo, SIZING_TOL).T_out_hot - tgt
    if f_lo <= 0:                            # 最短已够
        return lo, ev(lo, LTNE_TOL)          # 终点收紧
    # f_lo>0>f_hi 已 bracket → brentq 超线性求根 (T_out 单调)
    try:
        Lx_root = brentq(lambda Lx: ev(Lx, SIZING_TOL).T_out_hot - tgt,
                         lo, hi, xtol=TOL, maxiter=BISECT_IT)
    except ValueError:
        if forward_failed:
            raise  # A forward failure is not SciPy's changed-bracket condition.
        # 冷却临界点 (小 LMTD): ev() 改 warm-start 种子 → 松容差 LTNE 解非确定,
        # brentq 复评端点可能同号而崩。退回稳健二分 (不校验端点号; T_out 随 Lx 单调
        # 递减的假设下照常收敛), 取上界 = 满足 T_out≤tgt 的最小 Lx。
        a, b = lo, hi
        for _ in range(BISECT_IT):
            m = 0.5 * (a + b)
            if ev(m, SIZING_TOL).T_out_hot - tgt > 0:
                a = m              # 仍欠冷 → 需更长 Lx
            else:
                b = m
        Lx_root = b
    # The root is only resolved to TOL metres. Choose its cooling side;
    # the final cold-start solve still decides whether this design is usable.
    Lx_root = min(Lx_root + TOL, hi)
    return Lx_root, ev(Lx_root, LTNE_TOL)    # 终点收紧

RHO_S = 7900.0          # 304 SS [kg/m³]

@dataclass
class Design:
    feasible: bool
    topo: str = ""; l: float = 0.0; t: float = 0.0
    s: float = 0.0; Lx: float = 0.0; arrangement: str = "cross"
    V: float = 0.0; weight: float = 0.0
    dP_hot_max: float = 0.0; dP_cold_max: float = 0.0
    T_out_hot_max: float = 0.0; reason: str = ""
    percase: list = field(default_factory=list)   # 每工况明细 @ 定尺几何 (供工况明细表)
    height: float = 0.0          # 矩形迎风高 sz [m]; 0 = 方形 (H=W=s)
    Re_hot_max: float = 0.0      # 全工况热侧最大 Re (验证域判定)
    Re_cold_max: float = 0.0     # 全工况冷侧最大 Re
    validity: str = ""           # 验证域标记 (空=域内); A 外推 + B 退化

def _cool_proxy(case) -> float:
    """0-D 冷却难度代理 (无解): 所需效能 × 热侧流量 (越大越难冷→需更长 Lx)。"""
    denom = case.T_in_h - case.T_in_c
    eps_req = (case.T_in_h - t_target(case)) / denom if abs(denom) > 1e-9 else 0.0
    return eps_req * case.mdot_h

def _maxnorm_dP_sides(cases, topo, l, t, s, Lx, arrangement, height=None) -> tuple[float, float]:
    """全 K 工况分别取热/冷侧归一化 dP 最大值 (纯解析, 无 LTNE 解)。"""
    hot = cold = 0.0
    for c in cases:
        dh, dc = dP_fracs(c, topo, l, t, s, Lx, arrangement, height=height)
        hot = max(hot, dh / c.dPlim_h)
        cold = max(cold, dc / c.dPlim_c)
    return hot, cold

def _Lx_all(cases, topo, l, t, s, arrangement, k_s=K_STEEL, prop_model="const",
            seed=None, height=None, control=None):
    """全 K 工况冷却所需 Lx 的最大 (governing 终验)。任一不可达 → None。
    seed: 跨工况续解种子 (链式, 减 LTNE 迭代)。"""
    mx = 0.0
    for c in cases:
        Lx, r = solve_Lx(c, topo, l, t, s, arrangement, k_s=k_s,
                         prop_model=prop_model, seed=seed, height=height, control=control)
        if Lx is None:
            return None
        if r is not None:
            seed = r.fields                 # 链式续解
        mx = max(mx, Lx)
    return mx

def _min_Lx_for_dP(cases, topo, l, t, s, arrangement, Lx_floor, height=None):
    """返回 ≥ Lx_floor 的最小 Lx ∈ [Lx_floor, LX_MAX] 使全K两侧归一化 dP ≤ 1
    (纯解析, 无 LTNE 解)。叉流: 冷侧 dP 随 Lx↓ (迎风 Lx·s 变大), 热侧 dP 随 Lx↑
    (流程变长)。对冷侧单独二分，再检查热侧，避免漏过窄交集。
    逆流两侧均随 Lx↑，只需检查 floor。无可行 → None。"""
    if Lx_floor > LX_MAX:
        return None
    hot, cold = _maxnorm_dP_sides(cases, topo, l, t, s, Lx_floor, arrangement, height)
    if hot > 1.0:
        return None
    if cold <= 1.0:
        return Lx_floor
    if arrangement != 'cross':
        return None
    lo, hi = Lx_floor, LX_MAX
    if _maxnorm_dP_sides(cases, topo, l, t, s, hi, arrangement, height)[1] > 1.0:
        return None
    # Keep the cold-side feasible endpoint; final sizing uses the actual limit,
    # not a relaxed pressure ratio. Stop at adjacent floating-point lengths.
    while True:
        mid = (lo + hi) / 2.0
        if mid == lo or mid == hi:
            break
        if _maxnorm_dP_sides(cases, topo, l, t, s, mid, arrangement, height)[1] > 1.0:
            lo = mid
        else:
            hi = mid
    if _maxnorm_dP_sides(cases, topo, l, t, s, hi, arrangement, height)[0] <= 1.0:
        return hi
    return None

def size_fixed_cell(cases, topo, l, t, arrangement="cross", rho_s=RHO_S,
                    k_s=K_STEEL, prop_model="const", height=None,
                    control: RunControl | None = None) -> Design:
    """min-V over s: 每个 s 内定 Lx = max(冷却所需, 满足两侧 dP 所需) (≤450),
    取 V=s·sz·Lx 最小者 (方形 sz=s)。s-loop 冷却只跑 cooling-governing 工况 (其余
    dP 解析), s* 处对全 K 冷却终验。叉流冷侧迎风=Lx·sz → 冷侧 dP 紧时加厚 Lx。
    height: 矩形迎风高 sz [m] (固定, 搜索宽 s); None → 方形 sz=s (现状/UI 默认)。
    k_s: 固体热导率 [W/(m·K)], 默认 16 (304SS); 入 LTNE 固体能量 K_ss=(1-ε)·k_s。"""
    control = control or RunControl()
    control.check_cancelled()
    geo = tpms_geometry(topo, l, t, k_s, N=GEOM_N); EPS = geo["epsilon"]
    def _sz(sv):
        return sv if height is None else height        # z(高)向跨度 (方形=s)
    cool_gov = max(cases, key=_cool_proxy)              # 0-D 预选 (无解)
    s_lo = max(0.010, N_MIN * l / 1000.0); s_hi = S_MAX

    lo_lx = max(2.0 * l / 1000.0, 1e-3)                 # 最小流向晶胞长 (= solve_Lx 下界)

    def _dh_min(s):                                     # 全 K 热侧归一化 dP @Lx=lo_lx (解析, 无解)
        return max(dP_fracs(c, topo, l, t, s, lo_lx, arrangement, height=height)[0]
                   / c.dPlim_h for c in cases)

    state = {"seed": None, "cooled": False}             # warm-start 链 + 是否曾冷到

    def _eval_s(s):
        """该 s 的 (V, Lx); 不可行→(None,None)。热侧 dP 预筛 + governing 冷却 + 两侧 dP 定 Lx。"""
        if _dh_min(s) > 1.0:                            # 热侧 dP 超限 (任何 Lx 不可行)
            return None, None
        Lx_cool, r = solve_Lx(cool_gov, topo, l, t, s, arrangement, k_s=k_s,
                              prop_model=prop_model, seed=state["seed"], height=height,
                              control=control)
        if Lx_cool is None:                             # governing 冷不到
            return None, None
        state["cooled"] = True
        if r is not None:
            state["seed"] = r.fields                    # 携带场 (跨 s 平滑变)
        Lx = _min_Lx_for_dP(cases, topo, l, t, s, arrangement, Lx_cool, height=height)
        if Lx is None:
            return None, None
        return s * _sz(s) * Lx, Lx

    # C: min-V over s 用黄金分割 (代替 20 点网格)。V(s)=s²·Lx(s), Lx(s) 随 s↓ →
    # U 形单峰; 可行区为上区间 (大 s 更易冷 + dP 更松)。先解析定热侧 dP 可行下界
    # (无 LTNE), 黄金分割于 [a, s_hi]; 不可行点 V=+inf, 两点皆 inf 时推向更大 s。
    if _dh_min(s_hi) > 1.0:                             # 最大迎风热侧 dP 仍超 → 无解
        return Design(False, topo, l, t, arrangement=arrangement, reason="dP>lim@s_max")
    a = s_lo
    if _dh_min(s_lo) > 1.0:                             # 解析二分热侧 dP 可行下界 (廉价)
        a_lo, a_hi = s_lo, s_hi
        for _ in range(30):
            m = 0.5 * (a_lo + a_hi)
            if _dh_min(m) > 1.0: a_lo = m
            else: a_hi = m
        a = a_hi
    b = s_hi
    GR, INF = 0.6180339887498949, float("inf")
    best = None                                         # (V, s, Lx)
    def _upd(sv, vv, lv):
        nonlocal best
        if vv is not None and (best is None or vv < best[0]):
            best = (vv, sv, lv)
    c = b - GR * (b - a); d = a + GR * (b - a)
    Vc, Lc = _eval_s(c); Vd, Ld = _eval_s(d)
    _upd(c, Vc, Lc); _upd(d, Vd, Ld)
    for _ in range(GOLDEN_IT):
        fc = Vc if Vc is not None else INF
        fd = Vd if Vd is not None else INF
        if fc == INF and fd == INF:                     # 皆不可行 → 推向更大 s (冷却随 s↑ 改善)
            a, c, Vc, Lc = c, d, Vd, Ld
            d = a + GR * (b - a); Vd, Ld = _eval_s(d); _upd(d, Vd, Ld)
        elif fc <= fd:                                  # min 在 [a,d] 内 → 收右界
            b, d, Vd, Ld = d, c, Vc, Lc
            c = b - GR * (b - a); Vc, Lc = _eval_s(c); _upd(c, Vc, Lc)
        else:                                           # min 在 [c,b] 内 → 收左界
            a, c, Vc, Lc = c, d, Vd, Ld
            d = a + GR * (b - a); Vd, Ld = _eval_s(d); _upd(d, Vd, Ld)
        if b - a < S_REFINE_TOL:
            break

    if best is None:
        return Design(False, topo, l, t, arrangement=arrangement,
                      reason="cooling-unreachable" if not state["cooled"]
                      else "dP>lim@s_max")
    _, s_star, _ = best
    s_seed = state["seed"]

    def _allK(s):
        """该 s 的全-K (所有工况) 定尺: 返回 (Lx_floor, Lx_star)。
        Lx_floor None=某工况冷不到; Lx_star None=该长度下两侧 dP 超限。"""
        Lxf = _Lx_all(cases, topo, l, t, s, arrangement, k_s=k_s,
                      prop_model=prop_model, seed=s_seed, height=height, control=control)
        if Lxf is None or Lxf > LX_MAX:
            return None, None
        return Lxf, _min_Lx_for_dP(cases, topo, l, t, s, arrangement, Lxf, height=height)

    # s* 处全 K 终验。注意: s-搜索用 cooling-governing 代理, 其可行边界可能略低于全-K
    # 边界 (个别工况 dP 在更长全-K 冷却 Lx 下超限) → golden 可能精准落在该缝中。
    # 全-K 可行区是连续上区间 (大 s 迎风大 → dP 降 + 冷却易); 若 s* 全-K 不可行,
    # 向上二分找全-K 可行下边界 (= min-V 全-K 点, V 在可行区随 s 增)。
    Lx_floor, Lx_star = _allK(s_star)
    if Lx_star is None:
        # 全-K 边界紧邻 s* 上方 (governing≈全-K, 差几 mm) → 先指数扩张定位首个全-K
        # 可行 s (省去满程二分), 再在小区间 [last_infeas, first_feas] 二分到 ~1.5mm。
        lo_inf, s_feas = s_star, None
        s = s_star
        for _ in range(10):
            s = min(s * 1.08, s_hi)
            if _allK(s)[1] is not None:
                s_feas = s; break
            lo_inf = s
            if s >= s_hi - 1e-9:
                break
        if s_feas is None:                               # 连最大迎风也不行 → 真不可行
            cooled = _allK(s_hi)[0] is not None
            return Design(False, topo, l, t, arrangement=arrangement,
                          reason="dP>lim@final" if cooled else "cooling-unreachable")
        lo, hi = lo_inf, s_feas                          # 小区间二分边界 (~1.5mm 够)
        for _ in range(12):
            m = 0.5 * (lo + hi)
            if _allK(m)[1] is None: lo = m
            else: hi = m
            if hi - lo < 0.0015: break
        s_star = hi
        Lx_floor, Lx_star = _allK(s_star)
        if Lx_star is None:                              # 安全兜底
            return Design(False, topo, l, t, arrangement=arrangement,
                          reason="dP>lim@final")
    # 全 K 工况终验 (一次 forward/工况, 既出 percase 明细又汇总; 不再重复 dP_fracs)
    percase, dPh, dPc, Tout_max = [], 0.0, 0.0, 0.0
    failures = []
    re_h_max = re_c_max = 0.0
    warns = set()                                   # A 外推 + B 退化 标记
    for c in cases:
        control.check_cancelled()
        with warning_scope({}) as records:
            r = forward(c, topo, l, t, s_star, Lx_star, arrangement, k_s=k_s,
                        prop_model=prop_model, height=height, control=control)
        reasons = []
        if not r.run_status.get('converged', False):
            reasons.append('not-converged@final')
        values = (r.T_out_hot, r.T_out_cold, r.Q_hot, r.Q_cold,
                  r.dP_hot_frac, r.dP_cold_frac, r.Re_hot, r.Re_cold)
        if not all(math.isfinite(value) for value in values):
            reasons.append('nonfinite@final')
        else:
            if c.dT is not None:
                if r.T_out_hot > t_target(c):
                    reasons.append('T_out>target@final')
            elif r.Q_hot < c.Q:
                reasons.append('Q<target@final')
            if r.dP_hot_frac > c.dPlim_h or r.dP_cold_frac > c.dPlim_c:
                reasons.append('dP>lim@final')
        failures.extend(f'case {c.case}: {reason}' for reason in reasons)
        energy = r.energy_imbalance
        percase.append(dict(
            case=c.case, hot_fluid=c.hot_fluid, cold_fluid=c.cold_fluid,
            T_air_out=r.T_out_hot, T_cold_out=r.T_out_cold, Q_W=r.Q_hot,
            Q_cold_W=r.Q_cold,
            energy_imbalance_rel=energy.value if energy is not None else None,
            energy_imbalance_status=energy.status if energy is not None else 'insufficient_data',
            energy_imbalance_reason=energy.reason if energy is not None else '未提供能量不平衡诊断',
            dP_hot_frac=r.dP_hot_frac, dP_hot_pa=r.dP_hot_frac * c.P_in_h,
            dP_cold_frac=r.dP_cold_frac, dP_cold_pa=r.dP_cold_frac * c.P_in_c,
            Re_hot=r.Re_hot, Re_cold=r.Re_cold,
            warnings=list(dict.fromkeys((*warning_messages(records), *r.warnings))),
            run_status=r.run_status, acceptance_reasons=reasons))
        dPh = max(dPh, r.dP_hot_frac); dPc = max(dPc, r.dP_cold_frac)
        Tout_max = max(Tout_max, r.T_out_hot)
        re_h_max = max(re_h_max, r.Re_hot); re_c_max = max(re_c_max, r.Re_cold)
        hlo, hhi = nu_re_window(c.hot_fluid); clo, chi = nu_re_window(c.cold_fluid)
        if r.Re_hot < hlo: warns.add("热Re↓外推")    # A: Nu 关联式域外
        if r.Re_hot > hhi: warns.add("热Re↑外推")
        if r.Re_cold < clo: warns.add("冷Re↓外推")
        if r.Re_cold > chi: warns.add("冷Re↑外推")
        if r.dP_hot_frac > DP_DEGEN_FRAC: warns.add("热dP退化")   # B: 压降近进口压
        if r.dP_cold_frac > DP_DEGEN_FRAC: warns.add("冷dP退化")
    V = s_star * _sz(s_star) * Lx_star
    return Design(not failures, topo, l, t, s_star, Lx_star, arrangement,
                  V, (1.0 - EPS) * V * rho_s, dPh, dPc, Tout_max, reason='; '.join(failures),
                  percase=percase, height=(height or 0.0),
                  Re_hot_max=re_h_max, Re_cold_max=re_c_max,
                  validity=";".join(sorted(warns)))
