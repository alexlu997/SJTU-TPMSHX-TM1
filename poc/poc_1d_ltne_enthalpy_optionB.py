"""Option B (solve-in-enthalpy) 1D LTNE conservation PoC.

Two 1D three-temperature LTNE counterflow solvers on the SAME variable-cp sCO2
case, to prove the enthalpy formulation conserves where the legacy one does not:

  solve_cpT      — legacy: primary unknown T, convection telescopes the
                   face-shared flux F = ṁ·cp_face on T, i.e. conserves ṁ·cp·T.
                   This historical temperature-form control conserves the
                   wrong quantity for variable cp.
  solve_enthalpy — Option B: primary fluid unknown h. Convection telescopes the
                   mass flux ṁ on h, i.e. conserves the true enthalpy flux ṁ·h.
                   Diffusion recast (εk/cp)∇h; inter-phase h_v(Ts−T(h))
                   linearized T≈T*+(h−h*)/cp*; T=T(h,P) per outer (Picard).

Conserved-quantity gap: ṁ·cp·T vs ṁ·h differ by ∫T·dcp, which does NOT vanish
under grid refinement when cp varies strongly (sCO2 pseudocritical spike). That
∫T·dcp explains the historical ~41% A/B imbalance on the 703 recuperator.

The current production enthalpy path is implemented in
sjtu_tpmshx/solvers/ltne_enthalpy_3d.py. This PoC retains the independent
1D formulation comparison; production 3D regression has its own tests.

Run as a script for the tuning sweep; the pytest test asserts the key gates.
"""
from __future__ import annotations

import functools

import numpy as np
from CoolProp.CoolProp import PropsSI as _PropsSI

_FLUID = "CO2"
_T_LO, _T_HI = 240.0, 420.0   # clamp transients into CoolProp's valid CO2 range


# ── CoolProp property helpers (scalar cached + vectorised field) ────────────
@functools.lru_cache(maxsize=200000)
def _h_of_T_scalar(T, P):
    return float(_PropsSI("H", "T", float(T), "P", float(P), _FLUID))


@functools.lru_cache(maxsize=200000)
def _T_of_h_scalar(h, P):
    return float(_PropsSI("T", "H", float(h), "P", float(P), _FLUID))


def h_of_T(T, P):
    T = np.asarray(T, dtype=float)
    if T.ndim == 0:
        return _h_of_T_scalar(float(T), P)
    return np.asarray(_PropsSI("H", "T", T.ravel(), "P", float(P), _FLUID),
                      dtype=float).reshape(T.shape)


def T_of_h(h, P):
    h = np.asarray(h, dtype=float)
    if h.ndim == 0:
        return _T_of_h_scalar(float(h), P)
    return np.asarray(_PropsSI("T", "H", h.ravel(), "P", float(P), _FLUID),
                      dtype=float).reshape(h.shape)


def cp_of_T(T, P):
    T = np.asarray(T, dtype=float)
    return np.asarray(_PropsSI("C", "T", T.ravel(), "P", float(P), _FLUID),
                      dtype=float).reshape(T.shape)


def k_of_T(T, P):
    T = np.asarray(T, dtype=float)
    return np.asarray(_PropsSI("L", "T", T.ravel(), "P", float(P), _FLUID),
                      dtype=float).reshape(T.shape)


# ── 1D variable-cp sCO2 counterflow setup (straddles the pseudocritical line) ─
def make_setup_sco2(Nx=60):
    """Hot A (+x) and cold B (−x) sCO2 streams at 8 MPa exchanging heat through
    the pseudocritical region (Tpc≈307.7 K), so both traverse the cp spike."""
    L = 0.20
    dx = L / Nx
    Apipe = 1e-4
    P = 8.0e6

    # ASYMMETRIC across the cp spike (Tpc≈307.7K @8MPa): the HOT stream sits well
    # ABOVE the spike (cp moderate, cp·T≈h); the COLD stream traverses the spike
    # as it warms (cp×~50). The legacy cp·T form then mis-reports the COLD duty
    # but not the hot → a large A/B imbalance; the enthalpy form closes it.
    T_in_A = 360.0     # hot inlet (+x), well above the spike
    T_in_B = 298.0     # cold inlet (−x, counterflow), below → crosses the spike
    h_v = 2.5e5
    k_s = 14.0

    eps_face_A = np.full(Nx + 1, 0.34)
    eps_face_B = np.full(Nx + 1, 0.34)

    # Constant signed mass flux per stream. Cold side throttled (smaller |ṁ|) so
    # it warms further INTO the spike, amplifying the cp·T mis-conservation.
    m_dot_A = +1.6e-4
    m_dot_B = -1.0e-4

    return dict(
        Nx=Nx, dx=dx, L=L, Apipe=Apipe, P=P,
        k_s=k_s, h_v=h_v,
        T_in_A=T_in_A, T_in_B=T_in_B,
        eps_face_A=eps_face_A, eps_face_B=eps_face_B,
        m_dot_A=m_dot_A, m_dot_B=m_dot_B,
    )


# ── Historical temperature-form control: solve T, convect ṁ·cp·T ─
def solve_cpT(s, n_outer=500, n_sweep=2, omega=0.3, tol=1e-9):
    Nx, dx, A = s["Nx"], s["dx"], s["Apipe"]
    P, ks, hv = s["P"], s["k_s"], s["h_v"]
    Vc = dx * A
    Sf = A
    eA, eB = s["eps_face_A"], s["eps_face_B"]
    mA, mB = s["m_dot_A"], s["m_dot_B"]
    Tin_A, Tin_B = s["T_in_A"], s["T_in_B"]

    Ta = np.full(Nx, 0.5 * (Tin_A + Tin_B))
    Tb = Ta.copy()
    Ts = Ta.copy()

    for outer in range(n_outer):
        cpA = cp_of_T(Ta, P); cpB = cp_of_T(Tb, P)
        kA = k_of_T(Ta, P); kB = k_of_T(Tb, P)
        Ta_o = Ta.copy(); Tb_o = Tb.copy()

        for _ in range(n_sweep):
            # Fluid A (mA>0, +x). F_face = ṁ·cp_face (signed); cp_face lagged.
            for i in range(Nx):
                cpf_w = cpA[i - 1] if i > 0 else cpA[0]
                cpf_e = cpA[i + 1] if i < Nx - 1 else cpA[i]
                cpf_w = 0.5 * (cpA[i] + cpf_w)
                cpf_e = 0.5 * (cpA[i] + cpf_e)
                FW = mA * cpf_w
                FE = mA * cpf_e
                kf_w = 0.5 * (kA[i] + (kA[i - 1] if i > 0 else kA[i]))
                kf_e = 0.5 * (kA[i] + (kA[i + 1] if i < Nx - 1 else kA[i]))
                DW = eA[i] * kf_w * Sf / dx if i > 0 else 2.0 * eA[0] * kA[0] * Sf / dx
                DE = eA[i + 1] * kf_e * Sf / dx if i < Nx - 1 else 0.0
                aW = DW + max(FW, 0.0)
                aE = DE + max(-FE, 0.0)
                aP = aE + aW + (FE - FW) + hv * Vc
                S = hv * Vc * Ts[i]
                if i == 0:
                    S += aW * Tin_A
                    aW = 0.0
                TW = Ta[i - 1] if i > 0 else 0.0
                TE = Ta[i + 1] if i < Nx - 1 else 0.0
                if i == Nx - 1:
                    aE = 0.0
                new = (aW * TW + aE * TE + S) / max(aP, 1e-12)
                Ta[i] = min(max((1 - omega) * Ta[i] + omega * new, _T_LO), _T_HI)

            # Fluid B (mB<0, −x). Inlet at i=Nx-1, outlet at i=0.
            for i in range(Nx):
                cpf_w = 0.5 * (cpB[i] + (cpB[i - 1] if i > 0 else cpB[i]))
                cpf_e = 0.5 * (cpB[i] + (cpB[i + 1] if i < Nx - 1 else cpB[i]))
                FW = mB * cpf_w
                FE = mB * cpf_e
                kf_w = 0.5 * (kB[i] + (kB[i - 1] if i > 0 else kB[i]))
                kf_e = 0.5 * (kB[i] + (kB[i + 1] if i < Nx - 1 else kB[i]))
                DW = eB[i] * kf_w * Sf / dx if i > 0 else 0.0
                DE = eB[i + 1] * kf_e * Sf / dx if i < Nx - 1 else 2.0 * eB[Nx] * kB[i] * Sf / dx
                aW = DW + max(FW, 0.0)
                aE = DE + max(-FE, 0.0)
                aP = aE + aW + (FE - FW) + hv * Vc
                S = hv * Vc * Ts[i]
                if i == Nx - 1:
                    S += aE * Tin_B
                    aE = 0.0
                TW = Tb[i - 1] if i > 0 else 0.0
                TE = Tb[i + 1] if i < Nx - 1 else 0.0
                if i == 0:
                    aW = 0.0
                new = (aW * TW + aE * TE + S) / max(aP, 1e-12)
                Tb[i] = min(max((1 - omega) * Tb[i] + omega * new, _T_LO), _T_HI)

            _solve_solid(Ta, Tb, Ts, eA, eB, ks, hv, Sf, dx, Vc, omega)

        if max(np.max(np.abs(Ta - Ta_o)), np.max(np.abs(Tb - Tb_o))) < tol:
            break
    return dict(Ta=Ta, Tb=Tb, Ts=Ts, n_outer=outer + 1)


# ── Option B: solve h, convect ṁ·h (true enthalpy flux) ─────────────────────
def solve_enthalpy(s, n_outer=4000, n_sweep=3, omega=0.6, tol=2e-5):
    Nx, dx, A = s["Nx"], s["dx"], s["Apipe"]
    P, ks, hv = s["P"], s["k_s"], s["h_v"]
    Vc = dx * A
    Sf = A
    eA, eB = s["eps_face_A"], s["eps_face_B"]
    mA, mB = s["m_dot_A"], s["m_dot_B"]
    Tin_A, Tin_B = s["T_in_A"], s["T_in_B"]
    hin_A = h_of_T(Tin_A, P)
    hin_B = h_of_T(Tin_B, P)
    h_lo = h_of_T(_T_LO, P)
    h_hi = h_of_T(_T_HI, P)

    hA = np.full(Nx, hin_A)
    hB = np.full(Nx, hin_B)
    Ts = np.full(Nx, 0.5 * (Tin_A + Tin_B))

    for outer in range(n_outer):
        T_A = T_of_h(hA, P); T_B = T_of_h(hB, P)
        cpA = cp_of_T(T_A, P); cpB = cp_of_T(T_B, P)
        kA = k_of_T(T_A, P); kB = k_of_T(T_B, P)
        hA_star = hA.copy(); hB_star = hB.copy()  # linearisation point

        for _ in range(n_sweep):
            # Fluid A (mA>0, +x): unknown hA. Convection flux coefficient = ṁ.
            for i in range(Nx):
                FW = mA; FE = mA
                # diffusion in h-space: (eps*k/cp)_face
                dcf_w = 0.5 * (kA[i] / max(cpA[i], 1e-30)
                               + (kA[i - 1] / max(cpA[i - 1], 1e-30) if i > 0 else kA[i] / max(cpA[i], 1e-30)))
                dcf_e = 0.5 * (kA[i] / max(cpA[i], 1e-30)
                               + (kA[i + 1] / max(cpA[i + 1], 1e-30) if i < Nx - 1 else kA[i] / max(cpA[i], 1e-30)))
                DW = eA[i] * dcf_w * Sf / dx if i > 0 else 2.0 * eA[0] * (kA[0] / max(cpA[0], 1e-30)) * Sf / dx
                DE = eA[i + 1] * dcf_e * Sf / dx if i < Nx - 1 else 0.0
                aW = DW + max(FW, 0.0)
                aE = DE + max(-FE, 0.0)
                cpi = max(cpA[i], 1e-30)
                aP = aE + aW + (FE - FW) + hv * Vc / cpi
                # inter-phase: hv*Vc*(Ts - T(h)) linearised about hA_star
                S = hv * Vc * (Ts[i] - T_A[i] + hA_star[i] / cpi)
                if i == 0:
                    S += aW * hin_A
                    aW = 0.0
                hW = hA[i - 1] if i > 0 else 0.0
                hE = hA[i + 1] if i < Nx - 1 else 0.0
                if i == Nx - 1:
                    aE = 0.0
                new = (aW * hW + aE * hE + S) / max(aP, 1e-12)
                hA[i] = min(max((1 - omega) * hA[i] + omega * new, h_lo), h_hi)

            # Fluid B (mB<0, −x): inlet i=Nx-1, outlet i=0.
            for i in range(Nx):
                FW = mB; FE = mB
                dcf_w = 0.5 * (kB[i] / max(cpB[i], 1e-30)
                               + (kB[i - 1] / max(cpB[i - 1], 1e-30) if i > 0 else kB[i] / max(cpB[i], 1e-30)))
                dcf_e = 0.5 * (kB[i] / max(cpB[i], 1e-30)
                               + (kB[i + 1] / max(cpB[i + 1], 1e-30) if i < Nx - 1 else kB[i] / max(cpB[i], 1e-30)))
                DW = eB[i] * dcf_w * Sf / dx if i > 0 else 0.0
                DE = eB[i + 1] * dcf_e * Sf / dx if i < Nx - 1 else 2.0 * eB[Nx] * (kB[i] / max(cpB[i], 1e-30)) * Sf / dx
                aW = DW + max(FW, 0.0)
                aE = DE + max(-FE, 0.0)
                cpi = max(cpB[i], 1e-30)
                aP = aE + aW + (FE - FW) + hv * Vc / cpi
                S = hv * Vc * (Ts[i] - T_B[i] + hB_star[i] / cpi)
                if i == Nx - 1:
                    S += aE * hin_B
                    aE = 0.0
                hW = hB[i - 1] if i > 0 else 0.0
                hE = hB[i + 1] if i < Nx - 1 else 0.0
                if i == 0:
                    aW = 0.0
                new = (aW * hW + aE * hE + S) / max(aP, 1e-12)
                hB[i] = min(max((1 - omega) * hB[i] + omega * new, h_lo), h_hi)

            # Solid coupling uses the CURRENT fluid temperatures so the
            # fluid↔solid exchange tightens within the outer iteration. Estimate
            # them from the in-sweep h via the SAME local linearisation used in
            # the fluid source (T ≈ T* + (h−h*)/cp*) — cheap arithmetic, no
            # per-sweep CoolProp inversion, and exact at convergence (h→h*).
            T_A_lin = T_A + (hA - hA_star) / np.maximum(cpA, 1e-30)
            T_B_lin = T_B + (hB - hB_star) / np.maximum(cpB, 1e-30)
            _solve_solid(T_A_lin, T_B_lin, Ts,
                         eA, eB, ks, hv, Sf, dx, Vc, omega)

        if max(np.max(np.abs(hA - hA_star)),
               np.max(np.abs(hB - hB_star))) / max(abs(hin_A - hin_B), 1.0) < tol:
            break

    return dict(Ta=T_of_h(hA, P), Tb=T_of_h(hB, P), Ts=Ts, n_outer=outer + 1)


def _solve_solid(Ta, Tb, Ts, eA, eB, ks, hv, Sf, dx, Vc, omega):
    """Solid: pure diffusion + LTNE source, adiabatic ends. Ta/Tb are the
    current fluid temperatures (frozen per outer for the enthalpy solver)."""
    Nx = len(Ts)
    for i in range(Nx):
        eps_e = 0.5 * (eA[i + 1] + eB[i + 1]) if i < Nx - 1 else 0.0
        eps_w = 0.5 * (eA[i] + eB[i]) if i > 0 else 0.0
        DE = (1.0 - eps_e) * ks * Sf / dx if i < Nx - 1 else 0.0
        DW = (1.0 - eps_w) * ks * Sf / dx if i > 0 else 0.0
        aP = DE + DW + 2.0 * hv * Vc
        TE = Ts[i + 1] if i < Nx - 1 else Ts[i]
        TW = Ts[i - 1] if i > 0 else Ts[i]
        S = hv * Vc * (Ta[i] + Tb[i])
        new = (DE * TE + DW * TW + S) / max(aP, 1e-30)
        Ts[i] = (1 - omega) * Ts[i] + omega * new


# ── Metrics — Q_enth via TRUE enthalpy (CoolProp), not cp·ΔT ─────────────────
def compute_metrics(res, s):
    Ta, Tb, Ts = res["Ta"], res["Tb"], res["Ts"]
    P, hv = s["P"], s["h_v"]
    Vc = s["dx"] * s["Apipe"]
    mA = abs(s["m_dot_A"]); mB = abs(s["m_dot_B"])
    Tin_A, Tin_B = s["T_in_A"], s["T_in_B"]

    # A: inlet T_in_A (i=0 west), outlet Ta[-1]. B: inlet T_in_B (i=-1), outlet Tb[0].
    Q_enth_A = mA * abs(h_of_T(Ta[-1], P) - h_of_T(Tin_A, P))
    Q_enth_B = mB * abs(h_of_T(Tin_B, P) - h_of_T(Tb[0], P))

    Q_sA = float(np.sum(hv * (Ts - Ta) * Vc))
    Q_sB = float(np.sum(hv * (Ts - Tb) * Vc))

    AB_imbal = abs(Q_enth_A - Q_enth_B) / max(Q_enth_A, Q_enth_B, 1e-30)
    e_imb_LTNE = abs(Q_sA + Q_sB) / max(abs(Q_sA), abs(Q_sB), 1e-30)
    diff_A = abs(Q_enth_A - abs(Q_sA)) / max(Q_enth_A, 1e-30)
    diff_B = abs(Q_enth_B - abs(Q_sB)) / max(Q_enth_B, 1e-30)
    return dict(Q_enth_A=Q_enth_A, Q_enth_B=Q_enth_B, Q_sA=Q_sA, Q_sB=Q_sB,
                AB_imbal=AB_imbal, e_imb_LTNE=e_imb_LTNE,
                diff_A=diff_A, diff_B=diff_B)


def _report(label, res, s):
    m = compute_metrics(res, s)
    print(f"\n--- {label} (outer={res['n_outer']}) ---")
    print(f"  Ta[0]={res['Ta'][0]:.2f} Ta[-1]={res['Ta'][-1]:.2f}  "
          f"Tb[0]={res['Tb'][0]:.2f} Tb[-1]={res['Tb'][-1]:.2f}")
    print(f"  Q_enth_A={m['Q_enth_A']:.5f} W  Q_enth_B={m['Q_enth_B']:.5f} W")
    print(f"  Q_sA={m['Q_sA']:.5f} W  Q_sB={m['Q_sB']:.5f} W")
    print(f"  AB_imbal={m['AB_imbal']*100:.3f}%  LTNE e_imb={m['e_imb_LTNE']*100:.3f}%")
    print(f"  diff_A={m['diff_A']*100:.2f}%  diff_B={m['diff_B']*100:.2f}%")
    return m


def main():
    print("=" * 72)
    print("Option B (solve-in-enthalpy) 1D LTNE conservation PoC — sCO2 @ 8 MPa")
    print("=" * 72)
    s = make_setup_sco2()
    print(f"  Tpc(8MPa)≈307.7K; hot A in {s['T_in_A']}K, cold B in {s['T_in_B']}K")
    m_cpT = _report("LEGACY  ṁ·cp·T transport", solve_cpT(s), s)
    m_h = _report("OPTION B ṁ·h transport", solve_enthalpy(s), s)
    print("\n" + "=" * 72)
    print(f"  cp·T  A/B imbalance: {m_cpT['AB_imbal']*100:.2f}%")
    print(f"  h     A/B imbalance: {m_h['AB_imbal']*100:.2f}%")
    ok = m_h["AB_imbal"] < 0.01 and m_cpT["AB_imbal"] > 0.03
    print("  *** PoC SUCCESS ***" if ok else "  *** needs tuning ***")


if __name__ == "__main__":
    main()
