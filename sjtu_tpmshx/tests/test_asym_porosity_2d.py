"""Asymmetric porosity reaches the public native 2D calculation."""
from sjtu_tpmshx.controllers.module_adapter import compute_result

import numpy as np















# ── Phase 2: end-to-end through the 2D workflow (δ split plumbing) ─────────────────

def _air_air_delta_cfg(delta):
    """Fixed 2D air-air regression case with geometry offset δ."""
    from sjtu_tpmshx.domain.compute_config import (
        ComputeConfig, FluidConfig, GeometryConfig, SolverConfig,
        PartialBCConfig, ExtrapPolicy, FeatureFlags,
    )
    return ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=10.0, T_in_K=422.0, P_in_Pa=192362.0),
        fluid_B=FluidConfig(type='air', u_mps=20.0, T_in_K=322.0, P_in_Pa=101325.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.6,
                                k_s_W_mK=16.0, L_dom_m=0.182, H_dom_m=0.042,
                                delta_levelset=float(delta)),
        solver=SolverConfig(Nx=20, Ny=20),
        bc_A=PartialBCConfig(dir=0, in_ctr=0.021, in_w=0.042,
                             out_ctr=0.021, out_w=0.042),
        bc_B=PartialBCConfig(dir=3, in_ctr=0.021, in_w=0.042,
                             out_ctr=0.021, out_w=0.042),
        extrap=ExtrapPolicy(allow=True),
        flags=FeatureFlags(),
    )


def test_delta_pos_pipeline_runs_and_conserves():
    """A δ≠0 config runs end-to-end through the 2D workflow, returns finite headline
    scalars, and the A↔B energy balance still closes (split conserves)."""
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.solvers.api import run_case
    raw0 = run_case(prepare_case(_air_air_delta_cfg(0.0), case_id='symmetric')).metadata['diagnostics']
    rawd = run_case(prepare_case(_air_air_delta_cfg(0.6), case_id='asymmetric')).metadata['diagnostics']

    assert np.isfinite(rawd['Q_total']) and rawd['Q_total'] > 0.0
    assert np.isfinite(rawd['dP_A']) and np.isfinite(rawd['dP_B'])
    # The asymmetric split must not degrade the AB energy balance relative to
    # the symmetric run (conservation is preserved by the ε·split).
    assert rawd['energy_imbalance_rel'] <= max(0.05, 1.5 * raw0['energy_imbalance_rel'])


def test_delta_pos_differs_from_symmetric_pipeline():
    """δ≠0 actually drives an asymmetric run end-to-end — at least one headline
    scalar moves vs the symmetric δ=0 path (guards that δ is plumbed at all)."""
    r0 = compute_result(_air_air_delta_cfg(0.0))
    rd = compute_result(_air_air_delta_cfg(0.6))
    assert (rd.Q_W != r0.Q_W) or (rd.dP_A_Pa != r0.dP_A_Pa) or (rd.T_out_A_K != r0.T_out_A_K)
