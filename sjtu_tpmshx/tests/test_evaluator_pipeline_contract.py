"""Evaluator ↔ Pipeline CONTRACT (P1.4, architecture audit 2026-07 §2).

The BO evaluators (optimization/evaluator.py 2D, core/evaluators.py 3D) are a
CHEAP SCREENING TIER, deliberately not routed through ComputePipeline — their
throughput budget is why BO is affordable. The master rule this file encodes:

    **Pareto picks must be re-solved through the production Pipeline
    (verify_pareto_3d / stages_*) before any number is quoted.**

Each test below pins ONE deliberate divergence with its rationale. If a test
here fails, either (a) an accidental drift crept in — fix the code, or (b) a
divergence was consciously resolved — update the assertion AND the openspec
change evaluator-envelope-authority (design.md) in the same commit. Never
"fix" these by deleting the assertion.

Several assertions are source-marker checks (repo precedent:
test_validate_pipeline_runner_wiring.py). They are deliberately brittle:
renaming the marker means you touched the contract surface — re-read the
rationale before updating.
"""
import inspect


def test_3d_evaluator_and_pipeline_share_f2_default():
    from types import SimpleNamespace
    import sjtu_tpmshx.core.evaluators as ev
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime as rs
    assert inspect.signature(ev.evaluate_3d).parameters['convergence_mode'].default == 'f2'
    solver = SimpleNamespace()
    rs._apply_accel_flags(solver, {'_environment': {}})
    assert solver.convergence_mode == 'f2' and solver.mom_tol == 1e-4


def test_3d_evaluator_keeps_b_side_frozen():
    """DELIBERATE (BO throughput): the var-rho outer loop re-solves SIMPLE-A
    only; fluid B stays the cold solve (frozen-B tier, core/evaluators
    rationale at the rho_B_ltne block). The pipeline reseeds B too."""
    from sjtu_tpmshx.solvers.backends.python.screening import three_d as execution
    src = inspect.getsource(execution.run_case)
    assert 're-solving SIMPLE A' in src, (
        "lost the A-side re-solve marker — if the loop structure changed, "
        "re-read the frozen-B rationale before updating this contract")
    assert 're-solving SIMPLE B' not in src, (
        "a B-side re-solve appeared: that is a Pipeline-tier feature; adding "
        "it to the evaluator changes the BO cost model — conscious decision "
        "required (openspec evaluator-envelope-authority)")


def test_objective_shaping_is_evaluator_only():
    """DELIBERATE: manufacturability penalty / dp_cap / reject_unconverged
    are OPTIMIZER objective shaping. The physics pipeline must stay free of
    them (a validation number must never contain a penalty term)."""
    import sjtu_tpmshx.optimization.evaluator as ev2d
    import sjtu_tpmshx.solvers.backends.python.two_d.runtime as st2d
    src_ev = inspect.getsource(ev2d)
    src_pipe = inspect.getsource(st2d)
    for token in ('penalty_enabled', 'dp_cap_pa'):
        assert token in src_ev, f"evaluator lost its {token} shaping knob"
        assert token not in src_pipe, (
            f"objective-shaping token {token!r} leaked into the pipeline")


def test_evaluators_do_not_route_through_pipeline():
    """DELIBERATE (audit §2 verdict): full routing would destroy the BO
    throughput budget. The convergence path is shared AUTHORITIES (envelope,
    df_surrogate, extract_dP), not shared orchestration. Pareto numbers go
    through verify_pareto_3d / the Pipeline instead."""
    import sjtu_tpmshx.core.evaluators as ev3d
    import sjtu_tpmshx.optimization.evaluator as ev2d
    for mod in (ev3d, ev2d):
        assert 'compute_pipeline' not in inspect.getsource(mod), (
            f"{mod.__name__} started importing the Pipeline — that is a "
            "tier change, not a refactor")


def test_2d_choke_policy_evaluator_raises_pipeline_clips():
    """CURRENT STATE, both sides pinned: the 2D evaluator rejects choked
    designs pre-solve (raise -> bounded penalty, aa3f477); the 2D pipeline
    has never had a choke guard and CLIPS the seed instead (ledger O1).
    The evaluator being stricter than its pipeline is accepted; the pipeline
    growing a gate is DECISIONS D2 territory."""
    import sjtu_tpmshx.preprocess.app_modes.screening_2d as prep2d
    import sjtu_tpmshx.solvers.backends.python.two_d.runtime as st2d
    src_ev = inspect.getsource(prep2d)
    src_pipe = inspect.getsource(st2d)
    assert 'ChokedFlowError' in src_ev
    # The word appears in a stages_2d COMMENT (the ledger-O1 rationale), so
    # assert the absence of the raising MECHANISMS, not of the token.
    assert 'raise ChokedFlowError' not in src_pipe, (
        "the 2D pipeline grew a choke raise — that resolves DECISIONS D2; "
        "update this contract with the decision reference")
    assert 'check_compressible_envelope' not in src_pipe, (
        "the 2D pipeline adopted the raising pre-solve gate — DECISIONS D2")
    assert 'max(_P_out_sq, 1.0e4)' in src_pipe, (
        "2D pipeline lost its documented clip-not-raise seed floor")
    assert 'predict_outlet_p_sq' in src_pipe, (
        "2D pipeline lost its envelope seed authority")


def test_g_reference_density_convention_post_d3c():
    """G-reference convention after D3(c) (Alex 2026-07-20; the original
    decision record remains in Git history): per-dimension INTERNAL consistency.

    2D: BOTH the full-model runtime and the screening evaluator pin the physical
    inlet mass flux via an explicit rho_inlet_ref = rho(T_in, P_in) — the
    evaluator was aligned in iter 41 (frozen 2D values re-baselined with it).

    3D: DELIBERATELY unchanged — and candidate A2 (iter 50) FALSIFIED the
    feared outlet-datum deficit: the capture reads the CALLER-supplied
    physical rho(T_in, P_in) (stages:736 / evaluators:247) at solve() entry;
    the only offset is the seeded-profile half-cell datum (~0.5%, grid-
    convergent — openspec a2-3d-physical-g). These assertions still guard
    the convention: growing a rho_inlet_ref knob in 3D means re-opening the
    golden_3d + Shanghai re-validation question, consciously."""
    import sjtu_tpmshx.core.evaluators as ev3d
    import sjtu_tpmshx.solvers.backends.python.two_d.runtime as st2d
    from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D

    assert 'rho_inlet_ref' in inspect.getsource(st2d), (
        "2D pipeline stopped passing rho_inlet_ref — the C8-era ratchet "
        "guard is gone; that is a regression, not a D3 change")
    from sjtu_tpmshx.preprocess.app_modes import screening_2d
    assert 'rho_inlet_ref' in inspect.getsource(screening_2d), (
        "2D evaluator stopped passing rho_inlet_ref — D3(c) alignment "
        "regressed; frozen values were re-baselined WITH it (iter 41)")
    assert 'rho_inlet_ref' not in inspect.getsource(ev3d), (
        "3D evaluator G convention changed — candidate A2 executed? "
        "Update contract + golden_3d + Shanghai validation together")
    assert 'rho_inlet_ref' not in inspect.signature(
        SIMPLESolver3D.__init__).parameters, (
        "SIMPLESolver3D grew a rho_inlet_ref knob — candidate A2 executed? "
        "golden_3d + Shanghai headline re-validation are prerequisites")
