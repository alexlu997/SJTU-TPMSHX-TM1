from sjtu_tpmshx.applications.design.select import enumerate_select
from sjtu_tpmshx.applications.design import select, sizing
from sjtu_tpmshx.run_control.module_ports import RunControl
import pytest


def test_enumerate_returns_pareto_and_best(monkeypatch):
    candidates = {
        6.: sizing.Design(True, l=6., V=.002),
        7.: sizing.Design(True, l=7., V=.001),
        8.: sizing.Design(False, l=8.),
    }
    monkeypatch.setattr(select, 'size_fixed_cell', lambda cases, topo, l, *a, **kw: candidates[l])
    designs, best = enumerate_select([], nodes=dict(topo=['Diamond'], l=[6., 7., 8.], t=[.5]))
    assert designs == list(candidates.values()) and best is candidates[7.]
    assert 'min-V' in select.pareto_tags(designs)[id(best)]


@pytest.mark.parametrize('n_jobs', [1, 2])
def test_failed_selection_preserves_completed_candidates(monkeypatch, tmp_path, n_jobs):
    failure = ValueError('candidate failed')

    def candidate(cases, topo, l, t, *args, **kwargs):
        assert kwargs['control'].cpu_threads == 3
        (tmp_path / str(l)).write_text('started')
        if l == 6:
            raise failure
        return sizing.Design(False, topo=topo, l=l, t=t, reason='not feasible')

    monkeypatch.setattr(select, 'size_fixed_cell', candidate)
    completed = []
    with pytest.raises(ValueError, match='candidate failed') as caught:
        enumerate_select([], nodes=dict(topo=['Diamond'], l=[4, 5, 6, 7, 8, 9], t=[.4]),
                         n_jobs=n_jobs, completed=completed, control=RunControl(cpu_threads=3))
    assert [d.l for d in completed] == [4, 5]
    assert not any((tmp_path / str(l)).exists() for l in (8, 9))
    if n_jobs == 1:
        assert caught.value is failure
        assert not (tmp_path / '7').exists()
        assert any(frame.name == 'candidate' for frame in caught.traceback)
    else:
        assert caught.value.__cause__ is not None  # Original loky remote traceback.


def test_selection_completed_buffer_belongs_to_one_run(monkeypatch):
    design = sizing.Design(True, topo='Diamond', l=5., t=.4, V=.01)
    monkeypatch.setattr(select, 'size_fixed_cell', lambda *a, **kw: design)
    completed = []
    nodes = dict(topo=['Diamond'], l=[5], t=[.4])
    results, best = enumerate_select([], nodes=nodes, completed=completed)
    assert results is completed and results == [design] and best is design
    with pytest.raises(ValueError, match='empty'):
        enumerate_select([], nodes=nodes, completed=completed)
    assert completed == [design]  # A rejected reuse must not clear old results.
