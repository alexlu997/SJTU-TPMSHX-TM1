"""Quick design cancellation does not kill an active native solve or loky wave."""
from types import SimpleNamespace

import pytest

from sjtu_tpmshx.design import sizing, select
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl


def test_sizing_stops_between_forward_solves(monkeypatch):
    calls = []
    def forward(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(fields=None, T_out_hot=300.)
    monkeypatch.setattr(sizing, 'forward', forward)
    control = RunControl(cancel_check=lambda: bool(calls))
    with pytest.raises(CancelledError):
        sizing.solve_Lx(None, 'Diamond', 6., .4, .1, 'counter',
                        target=350., control=control)
    assert len(calls) == 1


@pytest.mark.parametrize('n_jobs', [1, 2])
def test_enumeration_retains_completed_candidates_before_cancel(monkeypatch, tmp_path, n_jobs):
    def candidate(cases, topo, l, t, *args, **kwargs):
        (tmp_path / f'{l}.txt').write_text('finished')
        return sizing.Design(False, l=l)
    monkeypatch.setattr(select, 'size_fixed_cell', candidate)
    control = RunControl(cancel_check=lambda: len(list(tmp_path.glob('*.txt'))) >= 2)
    with pytest.raises(select.SelectionCancelled) as exc:
        select.enumerate_select([], nodes=dict(topo=['Diamond'], l=[4, 5, 6, 7], t=[.4]),
                                n_jobs=n_jobs, control=control)
    assert sorted(path.name for path in tmp_path.glob('*.txt')) == ['4.txt', '5.txt']
    assert [d.l for d in exc.value.results] == [4, 5]


def test_partial_export_marks_scope_without_changing_feasibility(tmp_path):
    from openpyxl import load_workbook
    from sjtu_tpmshx.design.report import write_xlsx
    design = sizing.Design(True, topo='Gyroid', l=5., t=.4, V=.01)
    path = tmp_path / 'partial.xlsx'
    assert write_xlsx(path, [design], partial=True) == (1, 1, 0)
    workbook = load_workbook(path)
    for sheet in workbook:
        rows = list(sheet.values)
        status = rows[0].index('任务状态')
        assert '已取消：部分候选' in rows[1][status]
    summary = list(workbook['构型汇总'].values)
    assert summary[1][summary[0].index('可行')] == '是'
    assert summary[1][summary[0].index('标记')].startswith('已完成候选内')
