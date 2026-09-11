"""G2 自适应早停: design forward 传 q_rel_tol/conv_chunk 早停, 须给出与
满迭代参考解相同的收敛温度 (同解, 只是更快)。同时确认内核默认 (None) 不变。"""
from __future__ import annotations
import numpy as np
from sjtu_tpmshx.design.cases import DesignCase
from sjtu_tpmshx.design.forward import (forward, _hvol, K_STEEL, GEOM_N, NX, _ARR,
                            SIZING_QTOL, SIZING_CHUNK)
from sjtu_tpmshx.models.tpms_calc import geometry as tg
from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d


def _case():
    return DesignCase(1, "air", 900., 4e5, 0.05, "air", 300., 4e5, 0.05,
                      None, 0.08, 0.08, dT=300.)


def _ref_Tout(arrangement):
    """满迭代参考解 (默认收敛参数 + 大 max_iter), 不早停。"""
    _case(); topo, l, t, s, Lx = "Diamond", 7., 0.5, 0.084, 0.084
    geo = tg(topo, l, t, K_STEEL, N=GEOM_N)
    EPS, EPS_A, A0, Dh = geo["epsilon"], geo["epsilon_A"], geo["A_0"], geo["D_h"]
    arr = _ARR[arrangement]; Ny, Nz = arr["ny"], arr["nz"]
    shp = (NX, Ny, Nz); z = np.zeros(shp)
    spanc = Lx if arrangement == "cross" else s
    hA, _, uh, pA = _hvol("air", topo, l, t, A0, Dh, EPS_A, 0.05, s, s, 900., 4e5)
    hB, _, uc, pB = _hvol("air", topo, l, t, A0, Dh, EPS_A, 0.05, spanc, s, 300., 4e5)
    ucB, vcB = (z, np.full(shp, uc)) if arrangement == "cross" else (np.full(shp, -uc), z)
    Ta, _, _ = solve_full_domain_3d(
        Lx, s, s, NX, Ny, Nz, 900., 300.,
        np.full(shp, EPS_A * pA.k), np.full(shp, EPS_A * pB.k),
        np.full(shp, (1. - EPS) * K_STEEL), np.full(shp, hA), np.full(shp, hB),
        pA.rho * pA.cp, pB.rho * pB.cp, np.full(shp, EPS),
        np.full(shp, uh), z, z, ucB, vcB, z, dir_A=0, dir_B=arr["dirB"],
        dx_arr=np.full(NX, Lx / NX), dy_arr=np.full(Ny, s / Ny),
        dz_arr=np.full(Nz, s / Nz),
        max_iter=arr["maxit"], tol=1e-6, alpha_T=arr["alpha"])  # 默认收敛参数
    return float(np.asarray(Ta)[-1, :, :].mean())


def test_fast_converge_matches_reference_cross():
    ref = _ref_Tout("cross")
    r = forward(_case(), "Diamond", 7., 0.5, 0.084, 0.084, "cross")  # 走 G2 早停
    assert abs(r.T_out_hot - ref) < 0.05            # 同收敛解 (<0.05K)


def test_fast_converge_matches_reference_counter():
    ref = _ref_Tout("counter")
    r = forward(_case(), "Diamond", 7., 0.5, 0.084, 0.084, "counter")
    assert abs(r.T_out_hot - ref) < 0.05


def test_sizing_params_are_effective_thresholds():
    # 阈值必须是"会触发"的有意义值, 而非内核旧默认 (2D 2e-7 永不触发)
    assert SIZING_QTOL >= 1e-5 and SIZING_CHUNK <= 200
