"""P1.3 slice-A guards: the 3D evaluator's 1D D-F seed must come from the
models/envelope authority, not a local copy of the algebra (architecture
audit 2026-07 §2 — the copies are how evaluator/pipeline physics drifted in
the C8 era), and a BO campaign must start with fresh warn-dedup registries
(audit §5 — latched warnings from a previous campaign silence this one).

Wiring/identity tests only — cheap and grid-independent. The NUMBER lock for
the evaluators is test_evaluator_frozen_values (rel=1e-12) in the same suite.
"""
import inspect


def test_seed_algebra_bitwise_matches_envelope():
    """The swap is a pure refactor ONLY if the authority computes the exact
    same float — same op order, same constant. Lock the bitwise equality."""
    from sjtu_tpmshx.models.envelope import predict_outlet_p_sq, R_AIR_DEFAULT
    for P_in, T, C, L in [
        (101325.0, 350.0, 1.7e4, 0.182),
        (304746.0, 370.7, 8.3e5, 0.042),
        (1.01e5, 293.15, 2.4e3, 0.05),
    ]:
        manual = P_in ** 2 - 2.0 * R_AIR_DEFAULT * T * C * L
        assert predict_outlet_p_sq(P_in, T, C, L) == manual


def test_evaluate_3d_has_no_local_seed_algebra():
    """All three historical hand-copy sites (cold A/B seeds + hot var-rho
    reseed) must call predict_outlet_p_sq; the inline algebra must be gone."""
    from sjtu_tpmshx.preprocess.app_modes import screening_3d as prep
    from sjtu_tpmshx.solvers.backends.python.screening import three_d as execution
    src = inspect.getsource(prep) + inspect.getsource(execution)
    assert src.count('predict_outlet_p_sq(') >= 3, (
        "cold-A, cold-B and hot-reseed sites must all use the envelope "
        "authority")
    assert '2.0 * R_AIR *' not in src, (
        "hand-copied 1D D-F seed algebra crept back into core/evaluators "
        "(P1.3 regression)")


class _FakeSolver3D:
    """Minimal staggered-field stand-in for the post-solve gate unit tests.

    grid = (n0, n1, n2) in the SOLVER frame; u/v/w staggered MAC-style on
    axes 0/1/2 respectively; P is the gauge cell field.
    """
    def __init__(self, grid, speed, P_gauge_min, P_ref_abs=101325.0):
        import numpy as np
        n0, n1, n2 = grid
        self.u = np.full((n0 + 1, n1, n2), speed)
        self.v = np.zeros((n0, n1 + 1, n2))
        self.w = np.zeros((n0, n1, n2 + 1))
        self.P = np.full((n0, n1, n2), 0.0)
        self.P[0, 0, 0] = P_gauge_min
        self.P_ref_abs = P_ref_abs


def _gate_with_fakes(speed_A=5.0, speed_B=5.0,
                     P_gauge_min_A=0.0, P_gauge_min_B=0.0):
    import numpy as np
    from sjtu_tpmshx.solvers.backends.python.screening.three_d import _post_solve_gate_3d
    # Real grid (Nx, Ny, Nz) = (3, 2, 2); solver-A frame = (Ny, Nx, Nz).
    sA = _FakeSolver3D((2, 3, 2), speed_A, P_gauge_min_A)
    sB = _FakeSolver3D((3, 2, 2), speed_B, P_gauge_min_B)
    Ta = np.full((3, 2, 2), 350.0)
    Tb = np.full((3, 2, 2), 300.0)
    return _post_solve_gate_3d(sA, sB, Ta, Tb)


def test_post_solve_gate_passes_clean_fields():
    ok, reasons = _gate_with_fakes()
    assert ok and reasons == []


def test_post_solve_gate_flags_supersonic():
    """|v| past the local sound speed must invalidate — Mach is the
    load-bearing signal (the pressure floor bounds the stored gauge, but a
    choked solve still drives v = G/rho supersonic)."""
    ok, reasons = _gate_with_fakes(speed_A=500.0)   # a ≈ 375 m/s @ 350 K
    assert not ok
    assert any('[A]' in r and 'supersonic' in r for r in reasons)


def test_post_solve_gate_flags_floor_clipped_pressure():
    from sjtu_tpmshx.models.envelope import PRESSURE_FLOOR_PA
    ok, reasons = _gate_with_fakes(
        P_gauge_min_B=-(101325.0 - PRESSURE_FLOOR_PA))  # abs P at the floor
    assert not ok
    assert any('[B]' in r and 'floor' in r for r in reasons)


def test_evaluate_3d_wires_post_solve_gate():
    """The gate must run in evaluate_3d before the result dict is built."""
    from sjtu_tpmshx.solvers.backends.python.screening import three_d as execution
    src = inspect.getsource(execution.run_case)
    assert '_post_solve_gate_3d(' in src, (
        "evaluate_3d lost its post-solve envelope gate (P1.3-B regression)")


def test_qnehvi_campaign_resets_warn_registries(monkeypatch):
    """_reset_warn_registries clears both process-global registries, and
    run_qnehvi calls it at campaign entry (per-campaign granularity — a
    500-eval campaign still dedups; mirrors ComputePipeline.run)."""
    import sjtu_tpmshx.optimization.optimizer_qnehvi as oq
    import sjtu_tpmshx.models.nu_correlations as nc
    import sjtu_tpmshx.df_surrogate.predict as dp

    calls = []
    monkeypatch.setattr(nc, 'reset_extrap_warn_registry',
                        lambda: calls.append('extrap'))
    monkeypatch.setattr(dp, 'reset_choke_warn_registry',
                        lambda: calls.append('choke'))
    oq._reset_warn_registries()
    assert calls == ['extrap', 'choke']

    src = inspect.getsource(oq.run_qnehvi)
    assert '_reset_warn_registries()' in src, (
        "run_qnehvi must reset the warn registries at campaign entry")


def _core_temperature_case(monkeypatch, *, max_outer, bad_side=None, bad_value=None,
                           bad_call=1, simple_solvers=None):
    import numpy as np
    from sjtu_tpmshx.core import evaluators as ev
    from sjtu_tpmshx.solvers.backends.python.screening import three_d as execution
    from sjtu_tpmshx.models.continuous_field import encode_decision_vector

    calls = []

    def unsolved(s, **kwargs):
        calls.append('simple')
        if simple_solvers is not None:
            simple_solvers.append(s)
        return False, kwargs['max_iter']

    def forbidden(*args, **kwargs):
        raise AssertionError('bad temperature reached properties or final gate')

    class UnreadInfo(dict):
        def get(self, *args):
            raise AssertionError('bad temperature reached ltne_info')

    def thermal(*args, **kwargs):
        calls.append('thermal')
        fields = [np.full((3, 2, 2), t) for t in (350., 300., 325.)]
        if bad_side is not None and calls.count('thermal') == bad_call:
            fields[bad_side][-1, -1, -1] = bad_value
            monkeypatch.setattr(execution, 'air_viscosity', forbidden)
            monkeypatch.setattr(execution, '_post_solve_gate_3d', forbidden)
            return *fields, UnreadInfo()
        return *fields, {'converged': False}

    monkeypatch.setattr(execution.SIMPLESolver3D, 'solve', unsolved)
    monkeypatch.setattr(execution, 'solve_full_domain_3d', thermal)
    cfg = dict(L_domain=.1, H_domain=.05, u_A=1., u_B=1.,
               T_inA=350., T_inB=300.)
    x = encode_decision_vector(np.full((4, 4), 6.), np.full((4, 4), .4), True)
    try:
        result = ev.evaluate_3d(
            x, cfg, Nx=3, Ny=2, Nz=2, max_outer=max_outer,
            max_iter_simple=1, max_iter_energy=1,
            roughness_mode='baseline', roughness_eps_um=0., verbose=False)
    finally:
        expected_thermal = bad_call if bad_side is not None else min(max_outer, 2)
        assert calls.count('thermal') == expected_thermal
        assert calls.count('simple') == expected_thermal + 1
    return result


def test_core_temperature_return_rejected_before_use(monkeypatch):
    import numpy as np
    import pytest

    # Last/only return; return before refresh; later return before dT early-break.
    for max_outer, bad_call in ((1, 1), (3, 1), (3, 2)):
        for side, label in enumerate(('A', 'B', 'solid')):
            for value in (np.nan, np.inf):
                with monkeypatch.context() as patch:
                    with pytest.raises(ValueError) as error:
                        _core_temperature_case(patch, max_outer=max_outer,
                                               bad_side=side, bad_value=value,
                                               bad_call=bad_call)
                assert f'3D evaluator temperature return: {label} temperature index=(2, 1, 1)' in str(error.value)


def test_core_finite_unconverged_screening_keeps_verdict(monkeypatch):
    import numpy as np
    from sjtu_tpmshx.optimization import evaluator_3d as wrapper

    result = _core_temperature_case(monkeypatch, max_outer=1)
    assert not result['invalid'] and result['finite']
    assert not result['converged'] and not result['simple_A_converged']
    assert not result['simple_B_converged'] and not result['ltne_inner_converged']
    assert not result['outer_converged']
    # The real wrapper continues to accept this explicitly unconverged screen.
    monkeypatch.setattr(wrapper, '_evaluate_3d_dict', lambda *a, **k: result)
    Qn, dp, mass = wrapper.evaluate_design_3d(np.zeros(16), {'Lz': result['Lz_m']})
    assert Qn == -result['Q_3D_W'] / result['Lz_m']
    assert dp == result['dP_total_Pa'] and mass == result['mass_kg'] / result['Lz_m']
