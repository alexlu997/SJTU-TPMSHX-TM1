"""Test the shared Quick Design workflow and its candidate-keeping rules."""
from __future__ import annotations

import pytest

from sjtu_tpmshx.applications.design import cli, optimize, select, sizing
from sjtu_tpmshx.applications.design.workflow import run_design
from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.run_control.module_ports import RunControl


def _sized_with_source(cases, topo, l, t, *args, **kwargs):
    # Each loky worker imports this module. The patches of the test apply only to the parent process.
    from sjtu_tpmshx.run_control.provenance import source_context
    return sizing.Design(True, topo=topo, l=l, t=t, V=l, percase=[source_context()])


@pytest.mark.parametrize('n_jobs', [1, 2])
def test_run_design_keeps_the_source_revision_of_its_entry(monkeypatch, tmp_path, n_jobs):
    from sjtu_tpmshx.run_control import provenance
    pin = tmp_path / 'data-revision.txt'
    pin.write_text('A')
    monkeypatch.setattr(provenance, 'SOURCE_ROOT', tmp_path)
    monkeypatch.setattr(select, 'size_fixed_cell', _sized_with_source)

    def cancel_check():
        pin.write_text('B')  # The live revision changes after the study entry.
        return False

    results, _ = run_design(['case1'], nodes=dict(topo=['Diamond'], l=[5., 6.], t=[.4]),
                            n_jobs=n_jobs, control=RunControl(cancel_check=cancel_check))
    assert [design.percase[0]['data']['declared_revision'] for design in results] == ['A', 'A']
    assert provenance.source_context()['data']['declared_revision'] == 'B'


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


def test_run_design_validates_mode_cell_completed_height_and_precancel(monkeypatch):
    monkeypatch.setattr(sizing, 'size_fixed_cell',
                        lambda *a, **kw: pytest.fail('sizing reached on invalid input'))
    monkeypatch.setattr(select, 'enumerate_select',
                        lambda *a, **kw: pytest.fail('selection reached on invalid input'))
    with pytest.raises(ValueError, match='mode'):
        run_design(['case1'], mode='unknown')
    with pytest.raises(ValueError, match='cell'):
        run_design(['case1'], mode='fixed', cell=None)
    for bad_height in (0., -0.5, float('nan'), float('inf'), -float('inf'), True, '0.5'):
        with pytest.raises(ValueError, match='height'):
            run_design(['case1'], mode='fixed', cell=('Diamond', 7., .5), height=bad_height)
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


def test_workflow_and_cli_defaults_use_mean_cross_square_and_support_overrides(
        monkeypatch, tmp_path, capsys):
    import openpyxl

    seen = []

    def fixed(cases, topo, l, t, arrangement, **kwargs):
        seen.append(dict(arrangement=arrangement, **kwargs))
        return sizing.Design(
            True, topo=topo, l=l, t=t, s=.12, Lx=.08, arrangement=arrangement,
            V=.002, weight=1.0, height=(kwargs['height'] or 0.0),
        )

    monkeypatch.setattr(sizing, 'RHO_S', 2700.)
    monkeypatch.setattr(sizing, 'K_STEEL', 150.)
    monkeypatch.setattr(cli, 'load_cases', lambda path: ['case1'])
    monkeypatch.setattr(sizing, 'size_fixed_cell', fixed)

    # Shared workflow direct defaults.
    run_design(['case1'], mode='fixed', cell=('Diamond', 7., .5))
    assert seen[-1]['arrangement'] == 'cross'
    assert seen[-1]['prop_model'] == 'mean'
    assert seen[-1]['height'] is None

    # CLI defaults: cross, mean, square face, sizing.RHO_S, sizing.K_STEEL.
    out_default = tmp_path / 'default.xlsx'
    assert cli.run(['--xlsx', str(tmp_path / 'in.xlsx'), '--mode', 'fixed',
                    '--cell', 'Diamond,7,0.5', '--out', str(out_default)]) == 0
    assert seen[-1]['rho_s'] == 2700.
    assert seen[-1]['k_s'] == 150.
    assert seen[-1]['prop_model'] == 'mean'
    assert seen[-1]['arrangement'] == 'cross'
    assert seen[-1]['height'] is None
    assert '120.0×120.0×80.0mm' in capsys.readouterr().out

    # CLI overrides restore earlier const/counter behavior and set rectangular height in mm.
    out_override = tmp_path / 'override.xlsx'
    assert cli.run(['--xlsx', str(tmp_path / 'in.xlsx'), '--mode', 'fixed',
                    '--cell', 'Diamond,7,0.5', '--prop-model', 'const',
                    '--arrangement', 'counter', '--height', '750',
                    '--out', str(out_override)]) == 0
    assert seen[-1]['prop_model'] == 'const'
    assert seen[-1]['arrangement'] == 'counter'
    assert seen[-1]['height'] == pytest.approx(.75)
    assert '120.0×750.0×80.0mm' in capsys.readouterr().out
    wb = openpyxl.load_workbook(out_override, read_only=True, data_only=True)
    try:
        rows = list(wb['构型汇总'].values)
        assert rows[1][rows[0].index('H_mm')] == 750.0
    finally:
        wb.close()


@pytest.mark.parametrize('bad_height', ['0', '-10', 'nan', 'inf', '-inf', 'abc', '1e-322'])
def test_cli_rejects_invalid_height_before_loading_or_writing(
        monkeypatch, tmp_path, capsys, bad_height):
    source = tmp_path / 'in.xlsx'
    output = tmp_path / 'existing.xlsx'
    output.write_bytes(b'previous report')
    monkeypatch.setattr(cli, 'load_cases',
                        lambda *a, **kw: pytest.fail('input loaded before height check'))
    with pytest.raises(SystemExit) as caught:
        cli.run(['--xlsx', str(source), '--mode', 'fixed', '--cell', 'Diamond,7,0.5',
                 '--height', bad_height, '--out', str(output)])
    assert caught.value.code == 2
    assert '--height' in capsys.readouterr().err
    assert output.read_bytes() == b'previous report'


def test_cli_fixed_without_cell_raises_value_error(monkeypatch, tmp_path):
    output = tmp_path / 'out.xlsx'
    output.write_bytes(b'previous report')
    monkeypatch.setattr(cli, 'load_cases', lambda path: ['case1'])
    with pytest.raises(ValueError, match='cell is required'):
        cli.run(['--xlsx', str(tmp_path / 'in.xlsx'), '--mode', 'fixed',
                 '--out', str(output)])
    assert output.read_bytes() == b'previous report'


def test_cli_help_documents_unified_defaults_and_height(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.run(['--help'])
    assert caught.value.code == 0
    help_text = capsys.readouterr().out
    assert '--height' in help_text and '[mm]' in help_text
    assert 'cross=交叉流(默认)' in help_text
    assert 'mean=再按入口/出口均温更新物性求解一次(默认)' in help_text
