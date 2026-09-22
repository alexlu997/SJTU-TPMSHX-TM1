"""runs/smoke_ui_3d_modes.py — Phase B: smoke 3D Compute path with 3 roughness modes.

Constructs minimal cfg mirroring UI 3D Compute, calls _run_3d_stack
directly, compares Q + dP across {baseline, norris_1a, bhatti_shah_1b}.
Also exercises fluid_type_B='water' path (Shanghai-style) to verify
roughness skipped on water side.
"""
from __future__ import annotations
import os, warnings
import math

warnings.filterwarnings('ignore')

from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack
from sjtu_tpmshx.runs._case_template import build_cfg as _template_cfg


def build_cfg(tpms='Gyroid', Lcell=7.0, t_wall=0.6, k_s=16.0,
               L=0.182, H=0.042, Lz=0.042,
               Nx=20, Ny=10, Nz=8,
               u_A=12.0, T_inA=422.0, P_inA=101325.0,
               u_B=8.0, T_inB=302.0, P_inB=101325.0,
               fluid_type_A='air', fluid_type_B='air'):
    # B2 2.6: canonical template + this smoke's deltas (fast_sweep
    # profile, fixed-width 42 mm crossflow B inlet).
    return _template_cfg(
        tpms_type=tpms, Lcell=Lcell, t_wall=t_wall, k_s=k_s,
        L=L, H=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        u_A=u_A, T_inA=T_inA, P_inA=P_inA,
        u_B=u_B, T_inB=T_inB, P_inB=P_inB,
        fluid_type_A=fluid_type_A, fluid_type_B=fluid_type_B,
        fluid_B_cfg=dict(dir=3, in_ctr=L/2, in_w=0.042,
                         out_ctr=L/2, out_w=0.042),
        sweep_profile='fast_sweep',
        use_adaptive_amg_tol=True,
    )


def run_with_mode(label, mode, eps_um=100, **kw):
    old_env = {name: os.environ.get(name) for name in
               ('TPMSHX_ROUGH_MODE', 'TPMSHX_ROUGH_EPS_UM')}
    os.environ['TPMSHX_ROUGH_MODE'] = mode
    os.environ['TPMSHX_ROUGH_EPS_UM'] = str(eps_um)
    cfg = build_cfg(**kw)
    print(f"\n=== {label}  mode={mode} eps={eps_um}μm "
          f"fluid_B={cfg['fluid_type_B']} ===", flush=True)
    try:
        res = _run_3d_stack(cfg)
    except Exception as e:
        print(f"  CRASH: {type(e).__name__}: {e}", flush=True)
        return None
    finally:
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    Q = float(res.get('Q_total', float('nan')))
    dP_A = float(res.get('dP_A', float('nan')))
    dP_B = float(res.get('dP_B', float('nan')))
    if not all(math.isfinite(value) for value in (Q, dP_A, dP_B)):
        print('  FAIL: nonfinite Q or pressure drop', flush=True)
        return None
    print(f"  Q_total = {Q:.1f} W   dP_A = {dP_A:.0f} Pa   dP_B = {dP_B:.0f} Pa", flush=True)
    return {'Q': Q, 'dP_A': dP_A, 'dP_B': dP_B}


def main():
    print("=== Phase B: 3D UI Compute path × 4 modes ===", flush=True)
    print("Shanghai-style: Gyroid L=7 t=0.6, u_A=12 air @ 422K, u_B=8 air @ 302K, 20×10×8\n", flush=True)

    results = {}
    results['baseline'] = run_with_mode('baseline (no roughness)',  'baseline')
    results['norris_1a'] = run_with_mode('norris_1a (f×1.0 alias)',  'norris_1a')
    results['bs100']     = run_with_mode('bhatti_shah_1b ε=100',     'bhatti_shah_1b', 100)
    results['bs150']     = run_with_mode('bhatti_shah_1b ε=150',     'bhatti_shah_1b', 150)

    # Water B test — should NOT change dP_B (water Nu (`nu_water_topo`) baked-in)
    print("\n=== Water B test (Shanghai HX type, dP_B should NOT respond to mode) ===", flush=True)
    res_w_base = run_with_mode('water B baseline', 'baseline', fluid_type_B='water',
                                T_inB=290.0, u_B=0.5)
    res_w_norr = run_with_mode('water B norris_1a', 'norris_1a', fluid_type_B='water',
                                T_inB=290.0, u_B=0.5)
    failed = any(value is None for value in [*results.values(), res_w_base, res_w_norr])

    # Summary table
    print("\n=== SUMMARY ===", flush=True)
    print(f"{'mode':<25} {'Q [W]':>10} {'dP_A [Pa]':>12} {'dP_B [Pa]':>12}", flush=True)
    print("-" * 65, flush=True)
    for k, v in results.items():
        if v is None: continue
        print(f"{k:<25} {v['Q']:>10.1f} {v['dP_A']:>12.0f} {v['dP_B']:>12.0f}", flush=True)
    if res_w_base and res_w_norr:
        print()
        print(f"{'water-B baseline':<25} {res_w_base['Q']:>10.1f} {res_w_base['dP_A']:>12.0f} {res_w_base['dP_B']:>12.0f}", flush=True)
        print(f"{'water-B norris_1a':<25} {res_w_norr['Q']:>10.1f} {res_w_norr['dP_A']:>12.0f} {res_w_norr['dP_B']:>12.0f}", flush=True)
        dPB_diff = abs(res_w_base['dP_B'] - res_w_norr['dP_B'])
        if dPB_diff < 1.0:
            print(f"\n  [OK] water-B dP_B unchanged ({dPB_diff:.2f} Pa diff) - water Nu (`nu_water_topo`) protected", flush=True)
        else:
            failed = True
            print(f"\n  [WARN] water-B dP_B differs by {dPB_diff:.0f} Pa - leak?", flush=True)

    # Verification (2026-05-14 revised): norris_1a is now alias of
    # baseline for friction → dP_A ratio should be ≈ 1.0.
    if results['baseline'] and results['norris_1a']:
        ratio = results['norris_1a']['dP_A'] / max(results['baseline']['dP_A'], 1.0)
        print(f"\n  norris_1a / baseline dP_A ratio: {ratio:.3f}  (expect ~ 1.00)", flush=True)
        if 0.97 < ratio < 1.03:
            print("  [OK] norris_1a == baseline for friction (as designed)", flush=True)
        else:
            failed = True
            print("  [WARN] unexpected drift between norris_1a and baseline", flush=True)
    print('Smoke comparisons only; fast_sweep does not certify solver convergence.')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
