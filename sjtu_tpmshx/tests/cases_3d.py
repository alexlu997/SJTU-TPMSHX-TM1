"""Shared 3D regression input; historical numerical goldens are separate."""

def air_air_config():
    from sjtu_tpmshx.domain.compute_config import (
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


def demo_fixture_cfg(**overrides):
    """Frozen inputs of the original demos, independent of current run scripts."""
    from sjtu_tpmshx.models.tpms_calc import geometry

    cfg = dict(L=.182, H=.042, Lz=.042, Nx=30, Ny=20, Nz=5,
        u_A=20., u_B=10., T_inA=422., T_inB=293.15,
        P_inA=192362., P_inB=101325., T_s_init=None,
        tpms_type='Gyroid', Lcell=7., t_wall=.5, k_s=16.,
        fluid_type_A='air', fluid_type_B='air', wall_refine_3d=False,
        zone_grid_cells=None)
    cfg.update(overrides)
    cfg['eps'] = geometry(cfg['tpms_type'], cfg['Lcell'], cfg['t_wall'], cfg['k_s'])['epsilon']
    if cfg.get('fluid_A_cfg') is None:
        cfg['fluid_A_cfg'] = dict(dir=0, in_ctr=cfg['H']/2, in_w=cfg['H'],
                                  out_ctr=cfg['H']/2, out_w=cfg['H'])
    if cfg.get('fluid_B_cfg') is None:
        cfg['fluid_B_cfg'] = dict(dir=3, in_ctr=cfg['L']/2, in_w=cfg['L'],
                                  out_ctr=cfg['L']/2, out_w=cfg['L'])
    return cfg
