from sjtu_tpmshx.design.cases import DesignCase
from sjtu_tpmshx.design.select import enumerate_select
from sjtu_tpmshx.design import select, sizing
import pytest


def _cases():
    return [DesignCase(1,"air",688.23,1_088_700.0,0.2855,
                       "water",320.0,200_000.0,0.5,30_000.0,0.075,0.05)]

def test_enumerate_returns_pareto_and_best():
    feas, best = enumerate_select(_cases(), arrangement="cross",
                                  nodes={"topo":["Diamond"],"l":[6.0,7.0],"t":[0.5]})
    assert isinstance(feas, list)
    if best is not None:
        assert best.feasible and best.V > 0
        assert "min-V" in best_tags(feas, best)  # 最小体积件被标

def best_tags(feas, d):
    from sjtu_tpmshx.design.select import pareto_tags
    return pareto_tags(feas).get(id(d), [])


@pytest.mark.parametrize('n_jobs', [1, 2])
def test_failed_selection_preserves_completed_candidates(monkeypatch, tmp_path, n_jobs):
    failure = ValueError('candidate failed')

    def candidate(cases, topo, l, t, *args, **kwargs):
        (tmp_path / str(l)).write_text('started')
        if l == 6:
            raise failure
        return sizing.Design(False, topo=topo, l=l, t=t, reason='not feasible')

    monkeypatch.setattr(select, 'size_fixed_cell', candidate)
    completed = []
    with pytest.raises(ValueError, match='candidate failed') as caught:
        enumerate_select([], nodes=dict(topo=['Diamond'], l=[4, 5, 6, 7, 8, 9], t=[.4]),
                         n_jobs=n_jobs, completed=completed)
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
