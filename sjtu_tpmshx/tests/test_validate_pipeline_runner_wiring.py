"""Regression guards for the production pipeline in
validate_shanghai_3d_real.py (bugs found in the 2026-07-11 Windows-Server
handoff audit).

Two independent defects, both of them SILENT — the runner produced plausible
CSVs while dropping information the RMSRE口径 depends on:

1. `--max-outer` was accepted by `_run_one_case_pipeline` but never written
   into `SolverConfig`, so the pipeline ran its own built-in `_MAX_OUTER=5`
   while the banner printed the requested value.

2. `pressure_clip_hits` / `pressure_state_valid` were hard-coded to `0` / `1`.
   `pressure_state_valid=1` makes `valid_mask` in `main()` permanently
   all-True, so the "exclude pressure-invalid cases from the RMSRE" step —
   which the code comment there explicitly requires to be "auditable, never
   silent" — became a no-op on this branch.

These tests assert the WIRING (config plumbing + diagnostics forwarding), not
physics numbers, so they are cheap and grid-independent.
"""


from sjtu_tpmshx.domain.compute_config import SolverConfig  # noqa: E402
import pytest


def test_solver_config_carries_max_outer_ltne():
    """The knob the pipeline branch must populate exists and is settable.

    Guards the plumbing `_run_one_case_pipeline` now uses; if this field is
    ever renamed, the runner's `--max-outer` would go silently dead again.
    """
    sc = SolverConfig(Nx=8, Ny=4, Nz=3, max_outer_ltne=4)
    assert sc.max_outer_ltne == 4
    # Default stays None so the pipeline keeps its own built-in budget.
    assert SolverConfig(Nx=8, Ny=4, Nz=3).max_outer_ltne is None


@pytest.mark.parametrize('df_mode', ['cfd_smooth', 'experimental'])
def test_pipeline_branch_wires_max_outer_into_solver_config(df_mode):
    """`_run_one_case_pipeline(max_outer=N)` must reach SolverConfig.

    Rather than run a real 16-case solve, capture the ComputeConfig the runner
    builds by intercepting Pipeline3D.
    """
    import sjtu_tpmshx.validation.cases.validate_shanghai_3d_real as v3d
    import sjtu_tpmshx.controllers.compute_pipeline as cp

    captured = {}

    class _FakePipeline3D:
        def __init__(self, cc):
            captured['cc'] = cc

        def run(self):
            class _R:
                converged = True
                dP_A_Pa = 1.0
                dP_B_Pa = 2.0
                Q_W = 1.0
                residuals = {'Q_A': 1., 'Q_B': -1., 'energy_imbalance_rel': 0.,
                             'mass_imbalance_rel_A': 0., 'mass_imbalance_rel_B': 0.}
                metadata = {'metric_status': dict(Q='available', dP_A='available', dP_B='available'),
                            'darcy_forchheimer': {'mode': df_mode},
                            'timings_s': dict(prepare=.1, solve=2., postprocess=.3)}
                fields = {'dx': [1.] * 8, 'dy': [1.] * 4, 'dz': [1.] * 3}
                diagnostics = {'envelope_valid': True, 'p_clip_hits': 0,
                               '_max_outer': 4,   # the CAP — must NOT be read
                               'convergence_detail': {
                                   'outer_iters': 3, 'outer_converged': True}}
                warnings = []
            return _R()

    import pandas as pd
    # 35 source columns include separate water pressure drop and heat duty.
    row = {i: 0.0 for i in range(35)}
    row[5] = 0.05      # m_air
    row[7] = 0.10      # m_water
    row[24] = 20.0     # T_Bin degC
    row[28] = 200.0    # T_Ain degC
    row[30] = 3000.0   # P_Ain gauge
    row[31] = 1000.0   # P_Aout gauge
    row[33] = 5000.0   # Q_exp
    df = pd.DataFrame([row])
    df['water_P_in_abs_Pa'] = 99325.0  # supplied by the experiment loader

    orig = cp.Pipeline3D
    v3d_orig = getattr(v3d, 'Pipeline3D', None)
    cp.Pipeline3D = _FakePipeline3D
    try:
        kwargs = {} if df_mode == 'cfd_smooth' else {'df_mode': df_mode}
        result = v3d._run_one_case_pipeline(0, df, 8, 4, 3, max_outer=4, **kwargs)
    finally:
        cp.Pipeline3D = orig
        if v3d_orig is not None:
            v3d.Pipeline3D = v3d_orig

    cc = captured.get('cc')
    assert cc is not None, "runner never constructed a ComputeConfig"
    assert cc.fluid_B.P_in_Pa == 99325.0
    assert cc.df_mode == result['df_mode'] == df_mode
    assert (result['prepare_s'], result['solve_s'], result['postprocess_s']) == (.1, 2., .3)
    assert cc.solver.max_outer_ltne == 4, (
        "--max-outer must reach SolverConfig.max_outer_ltne; it was silently "
        "dropped before the 2026-07-11 fix (pipeline ran _MAX_OUTER=5)")


@pytest.mark.parametrize('water_pressure_available', [True, False])
def test_pipeline_branch_reports_real_pressure_diagnostics(water_pressure_available):
    """Keep both sides' evidence, unavailable metrics and native diagnostics."""
    import sjtu_tpmshx.validation.cases.validate_shanghai_3d_real as v3d
    import sjtu_tpmshx.controllers.compute_pipeline as cp

    class _FakePipeline3D:
        def __init__(self, cc):
            pass

        def run(self):
            class _R:
                converged = False
                dP_A_Pa = 2000.0
                dP_B_Pa = 1200.0 if water_pressure_available else float('nan')
                Q_W = 5000.0
                residuals = {'Q_A': 5000., 'Q_B': -4400., 'energy_imbalance_rel': .12,
                             'mass_imbalance_rel_A': .001, 'mass_imbalance_rel_B': .002}
                metadata = {'metric_status': dict(Q='available', dP_A='available',
                                                 dP_B='available' if water_pressure_available else 'missing'),
                            'darcy_forchheimer': {'mode': 'cfd_smooth'},
                            'timings_s': dict(prepare=.1, solve=2., postprocess=.3)}
                fields = {'dx': [1.] * 8, 'dy': [1.] * 4, 'dz': [1.] * 3}
                # A case the post-solve gate marked NON-physical, with clips.
                # `_max_outer` is the CAP (30). The runner must report the work
                # ACTUALLY done (4) and that it was TRUNCATED — reading the cap
                # made the printed `outer=` track --max-outer, so a cap of 12
                # and a cap of 30 both printed their own value while returning
                # bit-identical fields (found 2026-07-12).
                diagnostics = {'envelope_valid': False, 'p_clip_hits': 7,
                               '_max_outer': 30,
                               'convergence_detail': {
                                   'outer_iters': 4, 'outer_converged': False}}
                warnings = ['3D-A: Mach 1.02 >= 1.0']
            return _R()

    import pandas as pd
    row = {i: 0.0 for i in range(35)}
    row[5], row[7], row[24], row[28] = 0.05, 0.10, 20.0, 200.0
    row[30], row[31], row[33] = 3000.0, 1000.0, 5000.0
    row[32], row[34] = 1000.0, 4000.0
    df = pd.DataFrame([row])
    df['water_P_in_abs_Pa'] = 99325.0

    orig = cp.Pipeline3D
    cp.Pipeline3D = _FakePipeline3D
    try:
        r = v3d._run_one_case_pipeline(0, df, 8, 4, 3)
    finally:
        cp.Pipeline3D = orig

    assert r['pressure_state_valid'] == 0, (
        "an envelope-invalid pipeline result must NOT be reported valid; the "
        "hard-coded 1 disabled main()'s valid_mask exclusion entirely")
    assert r['pressure_clip_hits'] == 7, (
        "p_clip_hits must come from the pipeline diagnostics, not a literal 0")
    assert r['outer_iters'] == 4, (
        "outer_iters must be the work ACTUALLY done (convergence_detail), not "
        "diagnostics['_max_outer'] — that key is the CAP, so reading it made "
        "the reported count echo --max-outer regardless of what ran")
    assert r['outer_converged'] is False, (
        "a run that exhausted the cap must be reported as truncated")
    assert r['dP_water_exp'] == 1000.
    if water_pressure_available:
        assert r['dP_water_sim'] == 1200. and r['err_dP_water%'] == 20.
        assert r['dP_B_status'] == 'available'
    else:
        import math
        assert math.isnan(r['dP_water_sim']) and math.isnan(r['err_dP_water%'])
        assert r['dP_B_status'] == 'missing'
    assert r['Q_exp'] == 5000. and r['Q_water_exp'] == 4000.
    assert r['Q_A_native_signed_W'] == 5000. and r['Q_B_native_signed_W'] == -4400.
    assert r['Q_water_sim'] == 4400. and r['err_Q_water%'] == 10.
    assert r['experimental_heat_imbalance_rel'] == .2
    assert r['energy_imbalance_rel'] == .12
    assert r['mass_imbalance_rel_A'] == .001 and r['mass_imbalance_rel_B'] == .002
    assert r['warnings'] == '3D-A: Mach 1.02 >= 1.0'


def test_wall_refinement_reaches_actual_prepared_case():
    import numpy as np
    import pandas as pd
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.validation.cases.validate_shanghai_3d_real import _pipeline_config
    row = {i: 0.0 for i in range(34)}
    row.update({5: .05, 7: .10, 24: 20., 28: 200., 30: 3000., 31: 1000., 33: 5000.})
    df = pd.DataFrame([row])
    df['water_P_in_abs_Pa'] = 99325.
    plain = prepare_case(_pipeline_config(0, df, 8, 4, 3, max_outer=4), case_id='plain')
    refined = prepare_case(_pipeline_config(0, df, 8, 4, 3, max_outer=4, wall_refine=True), case_id='refined')
    assert refined.config_snapshot['flags']['wall_refine_3d'] is True
    assert refined.parameters['wall_refine_3d'] is True
    assert refined.parameters['max_outer_ltne'] == 4
    assert any(not np.array_equal(plain.grid['d' + axis], refined.grid['d' + axis]) for axis in 'xyz')
    for axis in 'xyz':
        assert len(refined.grid[axis + '_edges']) == len(refined.grid['d' + axis]) + 1


def test_pipeline_rejects_explicit_unsupported_options_before_data_access(monkeypatch, capsys):
    import pytest
    from sjtu_tpmshx.validation.cases import validate_shanghai_3d_real as runner
    monkeypatch.setattr(runner, 'load_cases_df', lambda *a: pytest.fail('data read before option validation'))
    for option in (['--runner', 'kernel'], ['--profile', 'uniform'], ['--profile', 'edge'], ['--eta', '0'], ['--disp-c', '0.1']):
        with pytest.raises(SystemExit) as exc:
            runner.main(option)
        assert exc.value.code == 2
        assert 'unrecognized arguments' in capsys.readouterr().err


@pytest.mark.parametrize('dimension', [2, 3])
def test_shanghai_actual_native_flow_matches_measured_total(monkeypatch, tmp_path, dimension):
    """Catch the old 4.33x water-flow error through real port fluxes."""
    import pandas as pd
    import numpy as np
    from sjtu_tpmshx.io.case_io import save_case, load_case
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.postprocess.api import evaluate
    from sjtu_tpmshx.validation.cases import validate_shanghai_aligned as v2
    from sjtu_tpmshx.validation.cases import validate_shanghai_3d_real as v3
    row = {i: 0. for i in range(34)}
    row.update({5: .0023, 7: .0108, 24: 20., 28: 120., 30: 1500.})
    df = pd.DataFrame([row])
    df['water_P_in_abs_Pa'] = 101500.
    cfg = v2._pipeline_config(0, df) if dimension == 2 else v3._pipeline_config(0, df, 12, 8, 3)
    if dimension == 2:
        # Use a small regular grid for this real inlet-flux contract; default
        # port/wall mesh selection has its own preparation tests.
        cfg.solver.Nx, cfg.solver.Ny = 12, 8
        cfg.flags.port_wall_refine = False
    assert (cfg.bc_B.dir, cfg.bc_B.in_ctr, cfg.bc_B.out_ctr,
            cfg.bc_B.in_w, cfg.bc_B.out_w) == (3, .154, .028, .042, .042)
    assert cfg.bc_B.uniform_inlet_2d and not cfg.bc_A.uniform_inlet_2d
    # This checks imposed inlet flux under normal solve criteria, not Q accuracy.
    case = prepare_case(cfg, case_id=f'shanghai-flow-{dimension}d')
    save_case(case, tmp_path / 'case.yaml')
    case = load_case(tmp_path / 'case.yaml')
    native = run_case(case)
    if dimension == 2:
        opening = case.parameters['boundary_openings']['B']
        np.testing.assert_array_equal(opening['in_geom_frac'], opening['in_profile_frac'])
        width = np.asarray(case.grid['dx']) * opening['in_geom_frac']
        mass_per_width = -native.boundary_fluxes['mass_B'][1][:, -1][width > 0] / width[width > 0]
        np.testing.assert_allclose(mass_per_width, mass_per_width[0], rtol=1e-12)
        fine = native.boundary_fluxes['fine']
        # The auxiliary thermal solve must preserve the selected inlet too.
        np.testing.assert_allclose(fine['inlet_B'][fine['inlet_B'] > 0], 1., atol=1e-12)
    result = evaluate(native)
    for side, column in (('A', 5), ('B', 7)):
        flow = result.metrics['mass_flow_' + side]
        assert flow.status == 'available'
        actual = flow.value * (.042 if dimension == 2 else 1.)
        assert actual == pytest.approx(row[column], rel=1e-6)
