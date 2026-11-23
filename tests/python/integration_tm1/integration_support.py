"""Shared B20 air input and its frozen public results."""
from sjtu_tpmshx.data_types.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig, PartialBCConfig,
)

# Frozen C++ v0.1 results, before Python retirement. Source: 23ea2cca.
# The original relative and absolute comparison tolerances remain unchanged.
AIR_BASELINE_METRICS = [31151.737386660214, 1631.0883215560673, 1212.573126277978,
                        303.276155996738, 334.79002576392344]
AIR_NATIVE_Q = 31131.514924465693
AIR_PUBLIC_METRICS = [AIR_NATIVE_Q, 1626.0284419863456, 1188.8114298952132,
                      303.2761559967381, 334.79002576392344]


def baseline_config():
    return ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=10., T_in_K=600., P_in_Pa=101325.),
        fluid_B=FluidConfig(type='air', u_mps=10., T_in_K=300., P_in_Pa=101325.),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7., t_wall_mm=.4,
                                k_s_W_mK=16., L_dom_m=.182, H_dom_m=.042),
        solver=SolverConfig(Nx=20, Ny=40, Nz=1),
        bc_A=PartialBCConfig(dir=0), bc_B=PartialBCConfig(dir=3))
