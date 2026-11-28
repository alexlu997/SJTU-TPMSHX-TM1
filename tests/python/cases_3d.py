"""Shared 3D regression inputs; historical numerical goldens are separate."""
from dataclasses import replace


def air_air_config():
    from tm1.data_types.compute_config import (
        ComputeConfig, FluidConfig, GeometryConfig, PartialBCConfig, SolverConfig,
    )
    return ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=10., T_in_K=422., P_in_Pa=192362.),
        fluid_B=FluidConfig(type='air', u_mps=20., T_in_K=322., P_in_Pa=101325.),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7., t_wall_mm=.6,
            k_s_W_mK=16., L_dom_m=.182, H_dom_m=.042, Lz_m=.042),
        solver=SolverConfig(Nx=15, Ny=15, Nz=15),
        bc_A=PartialBCConfig(dir=0, in_ctr=.021, in_w=.042, out_ctr=.021, out_w=.042,
            in_z_ctr=.021, in_z_w=.042, out_z_ctr=.021, out_z_w=.042),
        bc_B=PartialBCConfig(dir=3, in_ctr=.154, in_w=.042, out_ctr=.028, out_w=.042,
            in_z_ctr=.021, in_z_w=.042, out_z_ctr=.021, out_z_w=.042),
    )


def full_face_config(port_wall_refine=True):
    """Full-face B ports on a nonuniform-grid candidate of air_air_config."""
    config = air_air_config()
    return replace(config,
        solver=replace(config.solver, Nx=24, Ny=22, Nz=22),
        bc_B=replace(config.bc_B, in_ctr=.091, in_w=.182, out_ctr=.091, out_w=.182),
        flags=replace(config.flags, port_wall_refine=port_wall_refine))


def small_air_config():
    """Small air/air 3D workflow input for end-to-end smoke tests."""
    from tm1.data_types.compute_config import (
        ComputeConfig, ExtrapPolicy, FeatureFlags, FluidConfig, GeometryConfig,
        PartialBCConfig, SolverConfig,
    )
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
