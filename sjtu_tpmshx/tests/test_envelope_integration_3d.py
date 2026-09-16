"""Pressure startup is numerical; final fields and inlet matching still gate."""

import pytest

from sjtu_tpmshx.runs._case_template import build_cfg
from sjtu_tpmshx.pipelines import run_stack_3d
from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack
from sjtu_tpmshx.solvers.envelope import ChokedFlowError, PRESSURE_FLOOR_PA


def test_unusable_seed_cannot_certify_the_inlet_by_default():
    # The 1D seed is unusable. Positive/subsonic fields alone still cannot
    # certify a run that never reaches the specified physical inlet pressure.
    cfg = build_cfg(L=0.7, H=0.7, Lz=0.7, Nx=20, Ny=20, Nz=20,
                    u_A=30.0, T_inA=800.0, u_B=10.0, T_inB=400.0)
    res = _run_3d_stack(cfg)
    inlet = res['convergence_detail']['inlet_pressure']['A']
    assert inlet['iterations'][0]['method'] == 'inlet-pressure'
    assert inlet['passed'] is False
    assert res['solver_converged'] is False


@pytest.mark.parametrize('side', ['A', 'B'])
def test_unusable_seed_preserves_failed_inlet_pressure_verdict(side):
    # These seed estimates fail, but pressure shooting leaves subsonic,
    # positive cell fields. The specified inlet pressure is still unmet;
    # the seed estimate alone does not determine the final-field envelope.
    cfg = build_cfg(L=0.7, H=0.7, Lz=0.7, Nx=12, Ny=12, Nz=12,
                    u_A=30.0 if side == 'A' else 3.0, T_inA=800.0,
                    u_B=10.0 if side == 'A' else 20.0, T_inB=400.0,
                    envelope_mode='warn', sweep_profile='fast_sweep')
    res = _run_3d_stack(cfg)
    inlet = res['convergence_detail']['inlet_pressure'][side]
    assert inlet['iterations'][0]['method'] == 'inlet-pressure'
    assert abs(inlet['relative_error']) > inlet['relative_tolerance']
    assert inlet['passed'] is False
    assert res['convergence_detail']['outer_converged'] is False
    assert res['solver_converged'] is False


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('invalid_field', ['pressure', 'mach'])
@pytest.mark.parametrize('mode', ['raise', 'warn'])
def test_final_field_violation_is_flagged_on_each_side(monkeypatch, side, invalid_field, mode):
    original = run_stack_3d._extract_3d_metrics

    def invalid_final_field(prob, outer):
        metrics = original(prob, outer)
        # Inject a known invalid final state at the verdict boundary. Leave
        # the real gate, its thresholds and its returned verdict untouched.
        if invalid_field == 'pressure':
            solver = prob.sA if side == 'A' else prob.sB
            solver.P_ref_abs = PRESSURE_FLOOR_PA - float(solver.P.min())
        else:
            speed = metrics.vmag if side == 'A' else metrics.vmag_B
            speed[:] = 2000.0  # supersonic throughout this 400–800 K case
        return metrics

    monkeypatch.setattr(run_stack_3d, '_extract_3d_metrics', invalid_final_field)
    cfg = build_cfg(L=0.05, H=0.05, Lz=0.05, Nx=6, Ny=6, Nz=3,
                    u_A=8.0, T_inA=800.0, u_B=4.0, T_inB=400.0,
                    envelope_mode=mode, max_outer_ltne=2)
    if mode == 'raise':
        with pytest.raises(ChokedFlowError, match=f'3D-{side}.*non-physical field'):
            _run_3d_stack(cfg)
        return
    res = _run_3d_stack(cfg)
    assert res['envelope_valid'] is False
    reason = 'pressure' if invalid_field == 'pressure' else 'supersonic'
    assert any(r.startswith(f'[{side}]') and reason in r
               for r in res['envelope_reasons'])
    assert not any(r.startswith('[B]' if side == 'A' else '[A]')
                   for r in res['envelope_reasons'])
    assert res['solver_converged'] is False


def test_in_envelope_case_valid_and_unclipped():
    cfg = build_cfg(L=0.05, H=0.05, Lz=0.05, Nx=12, Ny=12, Nz=12,
                    u_A=8.0, T_inA=800.0, u_B=4.0, T_inB=400.0)
    res = _run_3d_stack(cfg)
    assert res['envelope_valid'] is True
    assert res['p_clip_hits'] == 0
    assert res['envelope_warnings'] == []
