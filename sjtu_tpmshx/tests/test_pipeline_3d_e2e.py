"""Pipeline3D.run() end-to-end smoke (audit T5, 2026-07-07).

Until this file, no test executed the full 3D orchestration
(config parse → _run_3d_stack → finalize): unit tests constructed
Pipeline3D without running it, and the golden gate calls _run_3d_stack
directly, bypassing the assembly layers. The 2D side has always run
Pipeline2D.run() in its golden — this closes the asymmetry at the pytest
level (physical-consistency assertions, not pinned values).
"""
import math

import pytest

from sjtu_tpmshx.domain.compute_config import (ComputeConfig, ExtrapPolicy, FeatureFlags,
                                   FluidConfig, GeometryConfig,
                                   PartialBCConfig, SolverConfig)


def _small_air_cfg():
    return ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=10.0, T_in_K=422.0,
                            P_in_Pa=192362.0),
        fluid_B=FluidConfig(type='air', u_mps=20.0, T_in_K=322.0,
                            P_in_Pa=101325.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.6,
                                k_s_W_mK=16.0, L_dom_m=0.06, H_dom_m=0.03,
                                Lz_m=0.03),
        solver=SolverConfig(Nx=8, Ny=6, Nz=4),
        bc_A=PartialBCConfig(dir=0, in_ctr=0.015, in_w=0.03,
                             out_ctr=0.015, out_w=0.03,
                             in_z_ctr=0.015, in_z_w=0.03,
                             out_z_ctr=0.015, out_z_w=0.03),
        bc_B=PartialBCConfig(dir=3, in_ctr=0.03, in_w=0.06,
                             out_ctr=0.03, out_w=0.06,
                             in_z_ctr=0.015, in_z_w=0.03,
                             out_z_ctr=0.015, out_z_w=0.03),
        extrap=ExtrapPolicy(allow=True),
        flags=FeatureFlags(),
    )


@pytest.mark.slow
def test_pipeline3d_run_end_to_end():
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline3D
    from sjtu_tpmshx.domain.compute_result import ComputeResult

    cfg = _small_air_cfg()
    assert cfg.is_3d

    res = Pipeline3D(cfg).run()

    assert isinstance(res, ComputeResult)
    assert math.isfinite(res.Q_W) and res.Q_W > 0
    assert math.isfinite(res.dP_A_Pa) and res.dP_A_Pa > 0
    assert isinstance(res.converged, bool)
    assert 300.0 < res.T_out_A_K < 430.0
    assert 300.0 < res.T_out_B_K < 430.0
    # finalize populated the field slots
    assert res.fields.get('Ta') is not None
    assert res.fields.get('Tb') is not None


@pytest.mark.slow
def test_pipeline3d_water_a_runs_through_incompressible_path():
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline3D

    cfg = ComputeConfig(
        fluid_A=FluidConfig(type='water', u_mps=0.5, T_in_K=360.0,
                            P_in_Pa=200000.0),
        fluid_B=FluidConfig(type='air', u_mps=8.0, T_in_K=300.0,
                            P_in_Pa=150000.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.6,
                                k_s_W_mK=16.0, L_dom_m=0.06, H_dom_m=0.03,
                                Lz_m=0.03),
        solver=SolverConfig(Nx=8, Ny=6, Nz=4),
        bc_A=PartialBCConfig(dir=0, in_ctr=0.015, in_w=0.03,
                             out_ctr=0.015, out_w=0.03,
                             in_z_ctr=0.015, in_z_w=0.03,
                             out_z_ctr=0.015, out_z_w=0.03),
        bc_B=PartialBCConfig(dir=3, in_ctr=0.03, in_w=0.06,
                             out_ctr=0.03, out_w=0.06,
                             in_z_ctr=0.015, in_z_w=0.03,
                             out_z_ctr=0.015, out_z_w=0.03),
        extrap=ExtrapPolicy(allow=True),
        flags=FeatureFlags(),
    )

    res = Pipeline3D(cfg).run()

    assert math.isfinite(res.Q_W) and res.Q_W > 0
    assert math.isfinite(res.dP_A_Pa) and res.dP_A_Pa > 0
    assert res.fields.get('Ta') is not None


@pytest.mark.slow
@pytest.mark.parametrize(
    'fluid_A,u_A,P_A,fluid_B,P_B',
    [('sco2', 0.3, 12e6, 'water', 2e6),
     ('air', 3.0, 2e5, 'sco2', 12e6)],
    ids=['sco2-water', 'air-sco2'],
)
def test_pipeline3d_mixed_sco2_z_and_x_ports(fluid_A, u_A, P_A, fluid_B, P_B):
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline3D

    def port(direction):
        return PartialBCConfig(
            dir=direction, in_ctr=0.015, in_w=0.015,
            out_ctr=0.015, out_w=0.015,
            in_z_ctr=0.015, in_z_w=0.015,
            out_z_ctr=0.015, out_z_w=0.015)

    cfg = ComputeConfig(
        fluid_A=FluidConfig(type=fluid_A, u_mps=u_A, T_in_K=500.0,
                            P_in_Pa=P_A),
        fluid_B=FluidConfig(type=fluid_B, u_mps=0.2, T_in_K=300.0,
                            P_in_Pa=P_B),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0,
                                t_wall_mm=0.6, k_s_W_mK=16.0,
                                L_dom_m=0.03, H_dom_m=0.03, Lz_m=0.03),
        solver=SolverConfig(Nx=4, Ny=4, Nz=4, max_outer_ltne=2,
                            max_iter_simple=300),
        bc_A=port(4),
        bc_B=port(1),
        extrap=ExtrapPolicy(allow=True),
    )
    result = Pipeline3D(cfg).run()
    eos = result.metadata['sco2_enthalpy_eos']
    assert list(eos['sides']) == (['A'] if fluid_A == 'sco2' else ['B'])
    assert eos['final_backend'] == 'HEOS'
    assert result.Q_W > 0
    assert result.T_out_A_K < cfg.fluid_A.T_in_K
    assert result.T_out_B_K > cfg.fluid_B.T_in_K
    assert result.residuals['enthalpy_imbalance_rel'] < 0.05
