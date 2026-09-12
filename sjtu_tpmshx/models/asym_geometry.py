"""
asym_geometry.py — 非对称孔隙率 PoC 核心（Phase 0）。

偏移等值面分相：固体带 solid = {δ−C ≤ φ ≤ δ+C}，δ 为中心偏移。
  void_A (得益, 气侧) = {φ < δ−C};  void_B (挤压, 液侧) = {φ > δ+C}
δ=0 退化为 tpms_geometry 的对称 50/50（见 tests）。

只读复用 tpms_geometry；不修改任何生产路径（Phase 2 才集成）。
计划：vault/reports/engineering/2026-06-05-asym-porosity-phase0-PLAN-CN.md
"""
import numpy as np
from scipy import ndimage

# 与 tpms_geometry._A0_from_C 内的体素面积校正常量一致（来源：该函数注释）。
_AREA_CORRECTION = 1.553


def eps_sides(phi: np.ndarray, C: float, delta: float = 0.0):
    """偏移带孔隙切分。返回 (eps_A, eps_B, eps_total)。

    eps_A = mean(phi < delta - C)  # 得益侧（大通道, 气侧）
    eps_B = mean(phi > delta + C)  # 挤压侧（小通道, 液侧）
    delta=0 时由 φ→−φ 对称给出 eps_A == eps_B == eps/2。
    """
    eps_A = float(np.mean(phi < (delta - C)))
    eps_B = float(np.mean(phi > (delta + C)))
    return eps_A, eps_B, eps_A + eps_B


def _count_interface(a: np.ndarray, b: np.ndarray) -> int:
    """数 a-区 与 b-区 相邻的体素面数（每面一次，三轴求和）。"""
    n = 0
    for ax in range(3):
        sl0 = [slice(None)] * 3
        sl1 = [slice(None)] * 3
        sl0[ax] = slice(None, -1)
        sl1[ax] = slice(1, None)
        s0, s1 = tuple(sl0), tuple(sl1)
        n += int(np.sum(a[s0] & b[s1])) + int(np.sum(b[s0] & a[s1]))
    return n


def delta_for_split(phi, C, target, n=6000):
    """Smallest δ≥0 whose ε_A/ε_B ≥ target (fixed C). target≤1 → δ=0."""
    if target <= 1.0:
        return 0.0
    for d in np.linspace(0.0, float(np.abs(phi).max()), n):
        eA, eB, _ = eps_sides(phi, C, d)
        if eB <= 1e-9:
            break
        if eA / eB >= target:
            return float(d)
    return None



def a0_sides(phi: np.ndarray, C: float, delta: float, L_m: float, N: int):
    """per-side 单侧比表面积 [1/m]。

    A0_side = F_side · dx² / (L³ · corr)，F_side = solid↔void_side 面数（每面一次）。
    δ=0 时 A0_A == A0_B == tpms_geometry._A0_from_C（无额外 ÷2；F_side=F_total/2，
    抵消了 _A0_from_C 里的 /2）。返回 (A0_A, A0_B)。
    """
    solid = (phi >= (delta - C)) & (phi <= (delta + C))
    void_A = phi < (delta - C)
    void_B = phi > (delta + C)
    dx = L_m / N
    norm = (L_m ** 3) * _AREA_CORRECTION
    A0_A = _count_interface(solid, void_A) * dx ** 2 / norm
    A0_B = _count_interface(solid, void_B) * dx ** 2 / norm
    return A0_A, A0_B


def a0_sides_mc(phi: np.ndarray, C: float, delta: float, L_m: float, N: int):
    """per-side 比表面积 [1/m] via marching cubes（三角化面积，无 voxel fudge 常数）。

    精确版：A0_side = area(isosurface φ=δ∓C) / V_domain。
      A0_A = φ=δ−C 面 (void_A↔solid)，A0_B = φ=δ+C 面。
    极端偏移下比 `a0_sides`（voxel face-count + 1.553，δ=0 标定）准 —— 后者的
    校正常数只对 δ=0 极小曲面有效，远离时曲面朝向/曲率变 → 偏。本函数直接量
    真实三角网面积，任意 δ 都准。Phase 1 生成 STL 后亦用此。
    """
    from skimage import measure
    dx = L_m / N
    V = L_m ** 3
    phimin, phimax = float(phi.min()), float(phi.max())

    def iso_area(level: float) -> float:
        if level <= phimin or level >= phimax:
            return 0.0  # 该侧空腔已消失 → 无界面
        verts, faces, _, _ = measure.marching_cubes(phi, level=level, spacing=(dx, dx, dx))
        return float(measure.mesh_surface_area(verts, faces))

    A0_A = iso_area(delta - C) / V
    A0_B = iso_area(delta + C) / V
    return A0_A, A0_B


def a0_sides_richardson(tpms_type, C: float, delta: float, L_m: float,
                        Ns=(96, 144, 216)):
    """per-side A0 [1/m]，3-网格 Richardson 外推（消薄侧网格分辨率偏差）。

    marching-cubes 薄通道面积从下方慢收敛（~O(N^-1.2)）：单网格 N=128 极端偏移下
    挤压侧 A0_B 可低 ~3%（实测 2026-06-09，与壁厚无关，纯分辨率）。本函数在 3 个
    等比网格上算 `a0_sides_mc`，估收敛阶后外推 N→∞，<1%。Ns 默认 (96,144,216)，
    比率 1.5。返回 (A0_A, A0_B)。极端 δ（Phase 1 选点）推荐用此替 `a0_sides_mc`。
    """
    from sjtu_tpmshx.models.tpms_geometry import _phi_grid
    A_vals, B_vals = [], []
    for N in Ns:
        aA, aB = a0_sides_mc(_phi_grid(tpms_type, N), C, delta, L_m, N)
        A_vals.append(aA)
        B_vals.append(aB)
    return _richardson3(Ns, A_vals), _richardson3(Ns, B_vals)


def _richardson3(Ns, f):
    """3-网格 Richardson 外推（等比网格，估阶 p）。

    f(N) ≈ f∞ − c·N^(−p)，三点估 p = ln(d1/d2)/ln(r)，外推 f∞ = f3 + d2/(r^p−1)。
    非单调 / 退化（某侧空腔消失 → f=0）→ 不外推，返回最细网格值 f3。
    """
    (N1, N2, N3), (f1, f2, f3) = Ns, f
    d1, d2 = f2 - f1, f3 - f2
    if f3 == 0.0 or d1 == 0.0 or d2 == 0.0 or d1 * d2 <= 0.0:
        return f3                              # 非单调/退化 → 不外推
    r = ((N2 / N1) + (N3 / N2)) / 2.0          # 平均细化比
    p = float(np.clip(np.log(d1 / d2) / np.log(r), 0.5, 3.0))
    return f3 + d2 / (r ** p - 1.0)


def dh_sides(phi: np.ndarray, C: float, delta: float, L_m: float, N: int,
             mc: bool = False):
    """per-side 水力直径 [m]：D_h = 4·ε_side / A0_side（教科书 4，单股 sheet）。

    返回 (Dh_A, Dh_B)。δ=0 时与 tpms_geometry.compute_geometry 的 D_h 一致。
    mc=True 用 marching-cubes 精确 A0（极端偏移推荐）；默认 voxel 快速版。
    """
    eps_A, eps_B, _ = eps_sides(phi, C, delta)
    A0_A, A0_B = (a0_sides_mc(phi, C, delta, L_m, N) if mc
                  else a0_sides(phi, C, delta, L_m, N))
    Dh_A = 4.0 * eps_A / A0_A if A0_A > 0 else 0.0
    Dh_B = 4.0 * eps_B / A0_B if A0_B > 0 else 0.0
    return Dh_A, Dh_B


def percolates_z(mask: np.ndarray) -> bool:
    """void 是否沿流向 z（axis=2）贯穿：某连通块同时触 z=0 与 z=N-1 面。"""
    lab, _ = ndimage.label(mask)
    if lab.max() == 0:
        return False
    top = set(np.unique(lab[:, :, 0])) - {0}
    bot = set(np.unique(lab[:, :, -1])) - {0}
    return len(top & bot) > 0


def wall_thickness(phi: np.ndarray, C: float, delta: float, L_m: float, N: int) -> float:
    """平均物理壁厚 [m]，slab 近似 t = V_solid / A_wall = (1−ε) / A0_wall。

    A0_wall ≈ 两侧单侧面积均值（同一道墙的两个面）。
    """
    eps_A, eps_B, eps = eps_sides(phi, C, delta)
    A0_A, A0_B = a0_sides(phi, C, delta, L_m, N)
    A0_wall = 0.5 * (A0_A + A0_B)
    return (1.0 - eps) / A0_wall if A0_wall > 0 else 0.0


def find_delta_max(phi: np.ndarray, C: float, dstep: float = None) -> float:
    """最大 |δ|：两侧 void 仍 percolate（连通夹断极限）。

    壁厚按「2C 常数」处理（PoC 简化，不约束物理壁厚）→ δ_max 只由连通定。
    物理可制造性（min wall ~0.3mm）延后到 STL 阶段（Phase 1+），此处不卡。
    """
    phimax = float(np.max(np.abs(phi)))
    if dstep is None:
        dstep = phimax / 200.0
    delta = 0.0
    last_ok = 0.0
    while delta <= phimax:
        if not (percolates_z(phi < (delta - C)) and percolates_z(phi > (delta + C))):
            break
        last_ok = delta
        delta += dstep
    return last_ok
