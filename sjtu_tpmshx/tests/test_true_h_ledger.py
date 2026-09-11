"""Ledger ownership: last thermal return, including a final cap/post update."""
import inspect

import numpy as np
import pytest

from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D, Pipeline3D
from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig, ExtrapPolicy,
)
from sjtu_tpmshx.solvers.backends.python.two_d import coupling as solve_2d
from sjtu_tpmshx.solvers.backends.python.three_d import runtime as run_stack_3d_stages
from sjtu_tpmshx.solvers import ltne_enthalpy_3d


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('cap', [False, True])
def test_last_true_h_return_survives_outer_post(monkeypatch, dimension, cap):
    cfg = ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=3., T_in_K=360., P_in_Pa=200000.),
        fluid_B=FluidConfig(type='sco2', u_mps=.2, T_in_K=300., P_in_Pa=12000000.),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7., t_wall_mm=.6,
            k_s_W_mK=16., L_dom_m=.03, H_dom_m=.03,
            Lz_m=.03 if dimension == 3 else None),
        solver=SolverConfig(Nx=4, Ny=4, Nz=4 if dimension == 3 else 1,
                            max_outer_ltne=2), extrap=ExtrapPolicy(allow=True))
    signature = inspect.signature(ltne_enthalpy_3d.solve_ltne_enthalpy_3d_pipeline)
    seen = []
    posts = []

    def thermal(*args, **kwargs):
        b = signature.bind(*args, **kwargs).arguments
        shape = b['Nx'], b['Ny'], b['Nz']
        n = len(seen) + 1
        info = dict(Q_A=7.25*n, Q_B=-7.26*n, iterations=11*n,
                    converged=True, residual=.001*n, energy_imbalance_rel=.001)
        seen.append((info.copy(), b['pressure_A_field'].copy(), b['pressure_B_field'].copy()))
        return (np.full(shape, 360.-n), np.full(shape, 300.+.05*n),
                np.full(shape, 330.), info)

    def outer(*, step, post, **kwargs):
        # Exercise real production step/post bodies with deterministic stopping.
        for n in range(2):
            _, carry = step(n)
            if n == 1 and not cap:
                return n, True
            post(n, carry)
            posts.append(n)
        return 1, False

    monkeypatch.setattr(ltne_enthalpy_3d, 'solve_ltne_enthalpy_3d_pipeline', thermal)
    target = solve_2d if dimension == 2 else run_stack_3d_stages
    monkeypatch.setattr(target, 'run_outer_coupling', outer)
    result = (Pipeline2D if dimension == 2 else Pipeline3D)(cfg).run()
    ledger = result.diagnostics['true_h_balance']
    assert len(seen) == 2 and posts == ([0, 1] if cap else [0])
    last, pa, pb = seen[-1]
    for key in ('Q_A', 'Q_B', 'iterations', 'converged', 'residual'):
        assert ledger[key] == last[key]
    assert ledger['units'] == ('W/m' if dimension == 2 else 'W')
    assert ledger['outer_index'] == 1
    assert ledger['post_after_last_thermal'] == cap
    assert ledger['outer_converged'] == (not cap)
    assert ledger['P_A_range_Pa'] == [float(pa.min()), float(pa.max())]
    assert ledger['P_B_range_Pa'] == [float(pb.min()), float(pb.max())]
    assert ledger['P_in_A_Pa'] == 200000.
    assert ledger['P_in_B_Pa'] == 12000000.
    if cap:
        assert not result.converged
