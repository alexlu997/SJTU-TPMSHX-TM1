"""Regression guards for the `--runner pipeline` branch of
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


def test_solver_config_carries_max_outer_ltne():
    """The knob the pipeline branch must populate exists and is settable.

    Guards the plumbing `_run_one_case_pipeline` now uses; if this field is
    ever renamed, the runner's `--max-outer` would go silently dead again.
    """
    sc = SolverConfig(Nx=8, Ny=4, Nz=3, max_outer_ltne=4)
    assert sc.max_outer_ltne == 4
    # Default stays None so the pipeline keeps its own built-in budget.
    assert SolverConfig(Nx=8, Ny=4, Nz=3).max_outer_ltne is None


def test_pipeline_branch_wires_max_outer_into_solver_config():
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
                dP_A_Pa = 1.0
                Q_W = 1.0
                diagnostics = {'envelope_valid': True, 'p_clip_hits': 0,
                               '_max_outer': 4,   # the CAP — must NOT be read
                               'convergence_detail': {
                                   'outer_iters': 3, 'outer_converged': True}}
                warnings = []
            return _R()

    import pandas as pd
    # 34 columns: the runner reads iloc[ci, {5,7,24,28,30,31,33}].
    row = {i: 0.0 for i in range(34)}
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
        v3d._run_one_case_pipeline(0, df, 8, 4, 3, max_outer=4)
    finally:
        cp.Pipeline3D = orig
        if v3d_orig is not None:
            v3d.Pipeline3D = v3d_orig

    cc = captured.get('cc')
    assert cc is not None, "runner never constructed a ComputeConfig"
    assert cc.fluid_B.P_in_Pa == 99325.0
    assert cc.solver.max_outer_ltne == 4, (
        "--max-outer must reach SolverConfig.max_outer_ltne; it was silently "
        "dropped before the 2026-07-11 fix (pipeline ran _MAX_OUTER=5)")


def test_pipeline_branch_reports_real_pressure_diagnostics():
    """The runner must read envelope_valid / p_clip_hits, not hard-code 0/1."""
    import sjtu_tpmshx.validation.cases.validate_shanghai_3d_real as v3d
    import sjtu_tpmshx.controllers.compute_pipeline as cp

    class _FakePipeline3D:
        def __init__(self, cc):
            pass

        def run(self):
            class _R:
                dP_A_Pa = 2000.0
                Q_W = 5000.0
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
    row = {i: 0.0 for i in range(34)}
    row[5], row[7], row[24], row[28] = 0.05, 0.10, 20.0, 200.0
    row[30], row[31], row[33] = 3000.0, 1000.0, 5000.0
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
