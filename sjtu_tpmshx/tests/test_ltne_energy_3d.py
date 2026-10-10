"""
tests/test_ltne_energy_3d.py — Phase 1 Week 3 verification

Five tests:
  1. nz1_matches_2d        — Nz=1 delegate path == 2D solver bitwise
  2. mass_balance          — mass_balance_3d probe on divergence-free field
  3. energy_balance        — steady LTNE Q_sA + Q_sB ≈ 0 on Nz=5 extrude
  4. alpha_T_robustness    — α ∈ {0.5, 0.7, 0.9} converge to same fields
  5. model_h_first_caller  — face transport and audit ignore compilation order
"""

import numpy as np
from sjtu_tpmshx.solvers.ltne_energy_3d import (
    solve_full_domain_3d,
    energy_balance_3d,
    mass_balance_3d,
)
from sjtu_tpmshx.solvers.ltne_energy import solve_full_domain


def test_runtime_mass_diagnostic_uses_local_porosity():
    from types import SimpleNamespace
    from sjtu_tpmshx.solvers.backends.python.three_d.runtime import _conservation_diagnostics_3d
    cells = np.ones((2, 2, 2))
    porosity = cells.copy()
    porosity[:, 0, :] = .25
    porosity[:, 1, :] = .5
    velocity = np.ones((2, 3, 2))
    velocity[:, -1, :] = .5
    solver = SimpleNamespace(u=np.zeros((3, 2, 2)), v=velocity, w=np.zeros((2, 2, 3)),
                             rho_field=cells, eps_field=porosity,
                             dx=np.ones(2), dy=np.ones(2), dz=np.ones(2))
    result = _conservation_diagnostics_3d(cells, cells, cells, cells, cells,
        solver, solver, {'dir': 2}, {'dir': 2}, solver.dx, solver.dy, solver.dz)
    assert result['mass_rel_A'] == result['mass_rel_B'] == 0.
    solver.v[:, -1, :] *= .8
    result = _conservation_diagnostics_3d(cells, cells, cells, cells, cells,
        solver, solver, {'dir': 2}, {'dir': 2}, solver.dx, solver.dy, solver.dz)
    assert np.isclose(result['mass_rel_A'], .2)
    assert np.isclose(result['mass_rel_B'], .2)

def test_model_h_faces_and_audit_do_not_depend_on_first_caller(tmp_path):
    import json
    import os
    import subprocess
    import sys

    # A direct energy audit and a fastmath sweep can compile these same helpers
    # first. Separate processes/caches expose that order; no thermal solve is needed.
    script = '''
import json, sys
import numpy as np
from numba import njit
from sjtu_tpmshx.models.tpms_props import model_h_coefficients
from sjtu_tpmshx.result_math import compute_phase2a
from sjtu_tpmshx.solvers import ltne_energy_3d as energy
from sjtu_tpmshx.solvers._kernels_ltne_3d import _model_h_faces, _face_divergence
from sjtu_tpmshx.tests.native.test_model_h_3d import case

@njit(fastmath=True)
def fast_caller(T, mass, cp, direction, inlet, opening, dx, dy, dz):
    capacity, deferred = _model_h_faces(T, mass, cp, direction, inlet, opening, dx, dy, dz)
    return capacity, deferred, _face_divergence(deferred)

def direct_caller(*args):
    capacity, deferred = _model_h_faces(*args)
    return capacity, deferred, _face_divergence(deferred)

# Existing deterministic 4x3x3 nonuniform, nonisothermal qualification input.
c = case(fluids=(0, 0))
a, b = c['a'], c['b']
cp = tuple(model_h_coefficients('air'))
inputs = (c['state'][0], tuple(a[2:5]), cp, c['directions'][0], a[5], a[6], *c['widths'])
first = fast_caller if sys.argv[1] == 'fast-first' else direct_caller
capacity, deferred, divergence = first(*inputs)
fields = dict(zip(('capacity_x', 'capacity_y', 'capacity_z',
                   'deferred_x', 'deferred_y', 'deferred_z', 'divergence'),
                  (*capacity, *deferred, divergence)))
zero = np.zeros(c['shape'])
eps = np.full(c['shape'], .35)
zero_faces = tuple(np.zeros_like(f) for f in a[2:5])
exchange = []
for index, (name, side) in enumerate((('A', a), ('B', b))):
    residual, source, diffusion = energy._conservation_residual_sum(
        c['state'][index], c['state'][2], *zero_faces, eps, side[0], zero, side[1],
        *c['widths'], c['directions'][index], side[5], side[6], zero,
        model_mass=tuple(side[2:5]), model_cp=cp, return_field=True)
    fields[name+'_residual'] = residual
    fields[name+'_inlet_diffusion'] = diffusion
    exchange.append(source)
solid, _, _ = energy._conservation_residual_sum(
    c['state'][2], c['state'][2], *zero_faces, eps, c['ks'], zero, zero,
    *c['widths'], 0, c['state'][2][0], zero[0], zero, return_field=True)
fields['solid_residual'] = solid + exchange[0] + exchange[1]
balance = energy._model_h_balance(
    tuple(c['state'][:2]), c['state'][2], (tuple(a[2:5]), tuple(b[2:5])), (cp, cp),
    c['directions'], (a[5], b[5]), (a[6], b[6]), (a[0], b[0]), c['ks'],
    (a[1], b[1]), (eps, eps), (zero, zero), zero, *c['widths'])
info = dict(model_h_balance=balance, _audit_fB=True)
for name in ('A', 'B'):
    side = balance['sides'][name]
    info['eps_'+name+'_strict'] = abs(side['residual_sum_W']) / side['strict_normalization_W']
    info['eps_'+name+'_strict_cellmax'] = side['residual_max_abs_W'] * zero.size / side['strict_normalization_W']
    info['Q_s'+name] = side['fluid_solid_exchange_to_fluid_W']
    fields.update({name+'_'+face: value for face, value in balance['_native_faces'][name].items()})
fields['balance'] = np.array([balance[key] for key in (
    'numerical_external_inward_W', 'explicit_source_W', 'solid_residual_sum_W',
    'solid_residual_max_abs_W', 'full_residual_sum_W', 'telescoping_error_W')])
print(json.dumps(dict(fields={name: value.tolist() for name, value in fields.items()},
                      gates=compute_phase2a(info)['gates'])))
'''
    results = []
    for order in ('direct-first', 'fast-first'):
        child = subprocess.run(
            [sys.executable, '-c', script, order], check=True, capture_output=True,
            text=True, env=os.environ | {'NUMBA_CACHE_DIR': str(tmp_path / order)})
        results.append(json.loads(child.stdout))
    assert results[0]['gates'] == results[1]['gates']
    assert results[0]['fields'].keys() == results[1]['fields'].keys()
    for name in results[0]['fields']:
        np.testing.assert_array_equal(results[0]['fields'][name], results[1]['fields'][name], err_msg=name)


def _toy_case(Nx=10, Ny=8, Nz=1, T_inA=350.0, T_inB=300.0):
    L, H, D = 0.10, 0.05, 0.02
    K_ffA = 0.05; K_ffB = 0.6; K_ss = 20.0
    h_vA = 5e4; h_vB = 5e4
    rho_cp_fA = 1.2 * 1007.0
    rho_cp_fB = 1000.0 * 4180.0
    eps = 0.8
    ucA = np.full((Nx, Ny, Nz), 5.0)
    vcA = np.zeros((Nx, Ny, Nz))
    wcA = np.zeros((Nx, Ny, Nz))
    ucB = np.zeros((Nx, Ny, Nz))
    vcB = np.full((Nx, Ny, Nz), -0.1)
    wcB = np.zeros((Nx, Ny, Nz))
    return dict(
        L=L, H=H, D=D, Nx=Nx, Ny=Ny, Nz=Nz,
        T_inA=T_inA, T_inB=T_inB,
        K_ffA=K_ffA, K_ffB=K_ffB, K_ss=K_ss,
        h_vA=h_vA, h_vB=h_vB,
        rho_cp_fA=rho_cp_fA, rho_cp_fB=rho_cp_fB,
        epsilon=eps,
        ucA=ucA, vcA=vcA, wcA=wcA,
        ucB=ucB, vcB=vcB, wcB=wcB,
        dir_A=0, dir_B=3,
        max_iter=6000, tol=1e-6,
    )


def test_nz1_matches_2d():
    cfg = _toy_case(Nz=1)
    Ta3, Tb3, Ts3 = solve_full_domain_3d(**cfg)

    # 2D direct
    cfg2 = dict(cfg)
    cfg2.pop('D'); cfg2.pop('Nz'); cfg2.pop('wcA'); cfg2.pop('wcB')
    # 2D ucA/vcA shape (Nx, Ny)
    cfg2['ucA'] = cfg['ucA'][..., 0]
    cfg2['vcA'] = cfg['vcA'][..., 0]
    cfg2['ucB'] = cfg['ucB'][..., 0]
    cfg2['vcB'] = cfg['vcB'][..., 0]
    Ta2, Tb2, Ts2 = solve_full_domain(**cfg2)

    assert Ta3.shape == (cfg['Nx'], cfg['Ny'], 1)
    assert np.allclose(Ta3[..., 0], Ta2, atol=1e-12, rtol=1e-10)
    assert np.allclose(Tb3[..., 0], Tb2, atol=1e-12, rtol=1e-10)
    assert np.allclose(Ts3[..., 0], Ts2, atol=1e-12, rtol=1e-10)
    print("test_nz1_matches_2d PASS")


def test_mass_balance():
    # Construct divergence-free staggered field: uniform u = 3 m/s, v = w = 0
    Nx, Ny, Nz = 12, 8, 5
    u = np.full((Nx + 1, Ny, Nz), 3.0)
    v = np.zeros((Nx, Ny + 1, Nz))
    w = np.zeros((Nx, Ny, Nz + 1))
    rho = np.full((Nx, Ny, Nz), 1.2)
    dx = np.full(Nx, 0.01); dy = np.full(Ny, 0.005); dz = np.full(Nz, 0.004)

    res = mass_balance_3d(u, v, w, rho, dy, dx, dz, dir_code=0)
    assert res['rel'] < 1e-12, f"uniform flow rel={res['rel']}"

    # -y direction (dir 3) — use v
    v2 = np.full((Nx, Ny + 1, Nz), -0.5)
    u2 = np.zeros((Nx + 1, Ny, Nz))
    w2 = np.zeros((Nx, Ny, Nz + 1))
    res2 = mass_balance_3d(u2, v2, w2, rho, dy, dx, dz, dir_code=3)
    assert res2['rel'] < 1e-12, f"dir=3 uniform rel={res2['rel']}"

    # +z direction (dir 4)
    u3 = np.zeros((Nx + 1, Ny, Nz))
    v3 = np.zeros((Nx, Ny + 1, Nz))
    w3 = np.full((Nx, Ny, Nz + 1), 0.2)
    res3 = mass_balance_3d(u3, v3, w3, rho, dy, dx, dz, dir_code=4)
    assert res3['rel'] < 1e-12, f"dir=4 uniform rel={res3['rel']}"

    print("test_mass_balance PASS (rel < 1e-12 all 3 dirs)")


def test_energy_balance():
    # Nz=5 uniform z-extrude: solve 3D, check Q_sA + Q_sB ≈ 0
    cfg = _toy_case(Nx=16, Ny=10, Nz=5)
    Ta, Tb, Ts = solve_full_domain_3d(**cfg)

    dx = np.full(cfg['Nx'], cfg['L'] / cfg['Nx'])
    dy = np.full(cfg['Ny'], cfg['H'] / cfg['Ny'])
    dz = np.full(cfg['Nz'], cfg['D'] / cfg['Nz'])
    h_vA = np.full((cfg['Nx'], cfg['Ny'], cfg['Nz']), cfg['h_vA'])
    h_vB = np.full((cfg['Nx'], cfg['Ny'], cfg['Nz']), cfg['h_vB'])

    bal = energy_balance_3d(Ta, Tb, Ts, h_vA, h_vB, dx, dy, dz)
    # steady state solid balance: Q_sA + Q_sB → 0 (heat in from hot fluid = heat out to cold fluid)
    scale = max(abs(bal['Q_sA']), abs(bal['Q_sB']), 1.0)
    rel = abs(bal['Q_net']) / scale
    print(f"test_energy_balance: Q_sA={bal['Q_sA']:.2e} Q_sB={bal['Q_sB']:.2e} "
          f"Q_net={bal['Q_net']:.2e} rel={rel:.2e}")
    assert rel < 1e-2, f"solid energy imbalance rel={rel:.2e}"
    print("test_energy_balance PASS")


def test_alpha_T_robustness():
    results = {}
    for alpha in (0.5, 0.7, 0.9):
        cfg = _toy_case(Nx=12, Ny=8, Nz=3)
        cfg['alpha_T'] = alpha
        Ta, Tb, Ts = solve_full_domain_3d(**cfg)
        results[alpha] = (Ta, Tb, Ts)

    # All α should converge to the same steady-state field (within chunk tol)
    ref = results[0.7]
    for a, (Ta, Tb, Ts) in results.items():
        if a == 0.7:
            continue
        dTa = np.max(np.abs(Ta - ref[0])) / (np.max(np.abs(ref[0])) + 1e-30)
        dTb = np.max(np.abs(Tb - ref[1])) / (np.max(np.abs(ref[1])) + 1e-30)
        dTs = np.max(np.abs(Ts - ref[2])) / (np.max(np.abs(ref[2])) + 1e-30)
        print(f"  alpha={a}: dTa={dTa:.2e} dTb={dTb:.2e} dTs={dTs:.2e}")
        assert dTa < 1e-2, f"alpha={a} Ta drift {dTa}"
        assert dTb < 1e-2, f"alpha={a} Tb drift {dTb}"
        assert dTs < 1e-2, f"alpha={a} Ts drift {dTs}"
    print("test_alpha_T_robustness PASS")


if __name__ == '__main__':
    test_nz1_matches_2d()
    test_mass_balance()
    test_energy_balance()
    test_alpha_T_robustness()
    print("\nAll ltne_energy_3d tests PASS")
