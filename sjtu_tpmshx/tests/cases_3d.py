"""Shared 3D regression input; historical numerical goldens are separate."""

def air_air_cfg(**ov):
    cfg = dict(
        L=0.182, H=0.042, Lz=0.042,
        Nx=15, Ny=15, Nz=15,
        u_A=10.0, u_B=20.0, T_inA=422.0, T_inB=322.0,
        P_inA=192362.0, P_inB=101325.0,
        tpms_type='Gyroid', Lcell=7.0, t_wall=0.6, k_s=16.0, eps=0.85,
        fluid_A_cfg=dict(dir=0, in_ctr=0.021, in_w=0.042,
                         out_ctr=0.021, out_w=0.042,
                         in_z_ctr=0.021, in_z_w=0.042,
                         out_z_ctr=0.021, out_z_w=0.042),
        fluid_B_cfg=dict(dir=3, in_ctr=0.154, in_w=0.042,
                         out_ctr=0.028, out_w=0.042,
                         in_z_ctr=0.021, in_z_w=0.042,
                         out_z_ctr=0.021, out_z_w=0.042),
        fluid_type_A='air', fluid_type_B='air',
        wall_refine_3d=False,
    )
    cfg.update(ov)
    return cfg


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


def run_research(cfg, *, control=None):
    """Execute regression inputs through the public prepared-case contract."""
    from sjtu_tpmshx.domain.module_ports import RunControl
    from sjtu_tpmshx.preprocess.api import prepare_research_case
    from sjtu_tpmshx.solvers.api import run_case

    control = RunControl() if control is None else control
    control.check_cancelled()
    return run_case(prepare_research_case(cfg, case_id='research-regression'), control)


def prepared_problem(cfg, *, control=None):
    """Build the runtime object under test without running the outer loop."""
    from sjtu_tpmshx.domain.module_ports import RunControl
    from sjtu_tpmshx.preprocess.api import prepare_research_case
    from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
    from sjtu_tpmshx.solvers.backends.python.three_d.runtime import build_problem

    control = RunControl() if control is None else control
    control.check_cancelled()
    case = prepare_research_case(cfg, case_id='runtime-regression')
    inputs, prepared = build_execution_inputs(case)
    return build_problem(inputs, prepared, control=control)
