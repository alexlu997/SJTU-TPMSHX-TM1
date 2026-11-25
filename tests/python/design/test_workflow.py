"""Check the shared Quick Design workflow and its retention contracts."""
from __future__ import annotations

import pytest

from sjtu_tpmshx.applications.design import cli, optimize, select, sizing
from sjtu_tpmshx.applications.design.workflow import run_design
from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.run_control.module_ports import RunControl


@pytest.mark.parametrize('feasible', [True, False])
def test_run_design_fixed_forwards_controls_and_skips_refinement(monkeypatch, feasible):
    seen = {}
    design = sizing.Design(feasible, topo='Diamond', l=7., t=.5, V=.002)

    def fixed(cases, topo, l, t, arrangement, *, rho_s, k_s, prop_model, height, control):
        seen.update(cases=cases, cell=(topo, l, t), arrangement=arrangement,
                    rho_s=rho_s, k_s=k_s, prop_model=prop_model,
                    height=height, control=control)
        return design

    monkeypatch.setattr(sizing, 'size_fixed_cell', fixed)
    monkeypatch.setattr(optimize, 'warm_start_joint',
                        lambda *a, **kw: pytest.fail('refinement ran in fixed mode'))
    cases = ['case1']
    control = RunControl(cpu_threads=2)
    completed = []
    results, best = run_design(
        cases,
        mode='fixed',
        arrangement='counter',
        cell=('Diamond', 7., .5),
        refine=True,
        rho_s=2700.,
        k_s=150.,
        prop_model='mean',
        height=.75,
        control=control,
        completed=completed,
    )
    assert results is completed and results == [design]
    assert best is (design if feasible else None)
    assert seen == dict(
        cases=cases, cell=('Diamond', 7., .5), arrangement='counter',
        rho_s=2700., k_s=150., prop_model='mean', height=.75, control=control,
    )


@pytest.mark.parametrize('outcome,appended', [
    ('improved', True),
    ('fallback', False),
    ('infeasible', False),
    ('not_smaller', False),
    ('nan_volume', False),
])
def test_run_design_auto_and_refinement_acceptance(monkeypatch, outcome, appended):
    candidates = {
        5.: sizing.Design(False, topo='Diamond', l=5., t=.4, V=.0005, reason='dP>lim@final'),
        6.: sizing.Design(True, topo='Diamond', l=6., t=.4, V=.003),
        7.: sizing.Design(True, topo='Diamond', l=7., t=.4, V=.002),
    }
    refine_seen = {}

    def candidate(cases, topo, l, t, arrangement, **kwargs):
        return candidates[l]

    def refine(cases, baseline, arrangement, *, rho_s, k_s, prop_model, height, control):
        refine_seen.update(baseline=baseline, arrangement=arrangement, rho_s=rho_s,
                           k_s=k_s, prop_model=prop_model, height=height, control=control)
        if outcome == 'improved':
            return sizing.Design(True, topo='Diamond', l=6.8, t=.42, V=.0015)
        if outcome == 'fallback':
            return baseline
        if outcome == 'infeasible':
            return sizing.Design(False, topo='Diamond', l=6.8, t=.42, V=.001)
        if outcome == 'not_smaller':
            return sizing.Design(True, topo='Diamond', l=6.8, t=.42, V=baseline.V)
        return sizing.Design(True, topo='Diamond', l=6.8, t=.42, V=float('nan'))

    monkeypatch.setattr(select, 'size_fixed_cell', candidate)
    monkeypatch.setattr(optimize, 'warm_start_joint', refine)
    control = RunControl(cpu_threads=1)
    completed = []
    results, best = run_design(
        ['case1'],
        mode='auto',
        arrangement='counter',
        nodes=dict(topo=['Diamond'], l=[5., 6., 7.], t=[.4]),
        refine=True,
        rho_s=2700.,
        k_s=150.,
        prop_model='mean',
        height=.5,
        n_jobs=1,
        control=control,
        completed=completed,
    )
    expected_base = [candidates[5.], candidates[6.], candidates[7.]]
    assert results is completed
    assert refine_seen == dict(
        baseline=candidates[7.], arrangement='counter', rho_s=2700.,
        k_s=150., prop_model='mean', height=.5, control=control,
    )
    if appended:
        assert results[:3] == expected_base and len(results) == 4
        assert best is results[3] and best.V == .0015
    else:
        assert results == expected_base
        assert best is candidates[7.]


def test_run_design_skips_refinement_when_no_feasible_candidate(monkeypatch):
    infeasible = sizing.Design(False, topo='Diamond', l=5., t=.4, reason='cooling-unreachable')
    monkeypatch.setattr(select, 'size_fixed_cell', lambda *a, **kw: infeasible)
    monkeypatch.setattr(optimize, 'warm_start_joint',
                        lambda *a, **kw: pytest.fail('refinement ran without feasible baseline'))
    results, best = run_design(
        ['case1'],
        mode='auto',
        nodes=dict(topo=['Diamond'], l=[5.], t=[.4]),
        refine=True,
        n_jobs=1,
    )
    assert results == [infeasible] and best is None


@pytest.mark.parametrize('stage', ['enumeration', 'refinement'])
def test_run_design_retains_completed_candidates_on_failure(monkeypatch, stage):
    failure = RuntimeError(f'failed during {stage}')
    designs = {
        5.: sizing.Design(True, topo='Diamond', l=5., t=.4, V=.003),
        6.: sizing.Design(True, topo='Diamond', l=6., t=.4, V=.002),
    }

    def candidate(cases, topo, l, t, *args, **kwargs):
        if stage == 'enumeration' and l == 6.:
            raise failure
        return designs[l]

    def refine(*args, **kwargs):
        raise failure

    monkeypatch.setattr(select, 'size_fixed_cell', candidate)
    monkeypatch.setattr(optimize, 'warm_start_joint', refine)
    completed = []
    with pytest.raises(RuntimeError) as caught:
        run_design(
            ['case1'],
            mode='auto',
            nodes=dict(topo=['Diamond'], l=[5., 6.], t=[.4]),
            refine=(stage == 'refinement'),
            n_jobs=1,
            completed=completed,
        )
    assert caught.value is failure
    expected = [designs[5.]] if stage == 'enumeration' else [designs[5.], designs[6.]]
    assert completed == expected


@pytest.mark.parametrize('stage', ['enumeration', 'refinement'])
def test_run_design_retains_completed_candidates_on_cancellation(monkeypatch, stage):
    designs = {
        5.: sizing.Design(True, topo='Diamond', l=5., t=.4, V=.003),
        6.: sizing.Design(True, topo='Diamond', l=6., t=.4, V=.002),
    }
    cancelled = False

    def candidate(cases, topo, l, t, *args, **kwargs):
        nonlocal cancelled
        if stage == 'enumeration' and l == 5.:
            cancelled = True
        return designs[l]

    def refine(*args, **kwargs):
        raise CancelledError('cancelled during refinement')

    monkeypatch.setattr(select, 'size_fixed_cell', candidate)
    monkeypatch.setattr(optimize, 'warm_start_joint', refine)
    completed = []
    with pytest.raises(select.SelectionCancelled) as caught:
        run_design(
            ['case1'],
            mode='auto',
            nodes=dict(topo=['Diamond'], l=[5., 6.], t=[.4]),
            refine=(stage == 'refinement'),
            n_jobs=1,
            control=RunControl(cancel_check=lambda: cancelled),
            completed=completed,
        )
    expected = [designs[5.]] if stage == 'enumeration' else [designs[5.], designs[6.]]
    assert completed == expected
    assert caught.value.results == expected


def test_run_design_validates_mode_cell_completed_and_precancel(monkeypatch):
    monkeypatch.setattr(sizing, 'size_fixed_cell',
                        lambda *a, **kw: pytest.fail('sizing reached on invalid input'))
    monkeypatch.setattr(select, 'enumerate_select',
                        lambda *a, **kw: pytest.fail('selection reached on invalid input'))
    with pytest.raises(ValueError, match='mode'):
        run_design(['case1'], mode='unknown')
    with pytest.raises(ValueError, match='cell'):
        run_design(['case1'], mode='fixed', cell=None)
    existing = sizing.Design(True, topo='Diamond', l=5., t=.4, V=.002)
    retained = [existing]
    with pytest.raises(ValueError, match='empty'):
        run_design(['case1'], mode='auto', completed=retained)
    assert retained == [existing]

    cancelled = RunControl(cancel_check=lambda: True)
    with pytest.raises(CancelledError):
        run_design(['case1'], mode='fixed', cell=('Diamond', 7., .5), control=cancelled)
    with pytest.raises(select.SelectionCancelled) as caught:
        run_design(['case1'], mode='auto', control=cancelled)
    assert caught.value.results == []


def test_cli_defaults_use_design_density_and_keep_const_prop_model(monkeypatch, tmp_path):
    seen = {}
    design = sizing.Design(True, topo='Diamond', l=7., t=.5, V=.002)
    monkeypatch.setattr(sizing, 'RHO_S', 2700.)
    monkeypatch.setattr(sizing, 'K_STEEL', 150.)
    monkeypatch.setattr(cli, 'load_cases', lambda path: ['case1'])

    def fixed(cases, topo, l, t, arrangement, **kwargs):
        seen.update(arrangement=arrangement, **kwargs)
        return design

    monkeypatch.setattr(sizing, 'size_fixed_cell', fixed)
    assert cli.run(['--xlsx', str(tmp_path / 'in.xlsx'), '--mode', 'fixed',
                    '--cell', 'Diamond,7,0.5', '--out', str(tmp_path / 'out.xlsx')]) == 0
    assert seen['rho_s'] == 2700.
    assert seen['k_s'] == 150.
    assert seen['prop_model'] == 'const'
    assert seen['height'] is None
    assert seen['arrangement'] == 'cross'
