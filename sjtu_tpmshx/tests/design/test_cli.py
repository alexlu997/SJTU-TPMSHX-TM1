import openpyxl
import pytest
from types import SimpleNamespace
from sjtu_tpmshx.design.cli import run

def _spec(path):
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["case","hot_fluid","T_in_h_K","P_in_h_kPa","mdot_h",
               "cold_fluid","T_in_c_K","P_in_c_kPa","mdot_c","Q_kW","dPlim_h","dPlim_c"])
    ws.append([1,"air",688.23,1088.7,0.2855,"water",320.0,200.0,0.5,30.0,0.075,0.05])
    wb.save(path)

def test_run_fixed_mode(tmp_path):
    f = tmp_path / "spec.xlsx"; _spec(f); out = tmp_path / "out.xlsx"
    rc = run(["--xlsx", str(f), "--mode", "fixed",
              "--cell", "Diamond,7,0.5", "--out", str(out)])
    assert rc == 0 and out.exists()

def test_run_auto_mode_small_grid(tmp_path):
    f = tmp_path / "spec.xlsx"; _spec(f); out = tmp_path / "out.xlsx"
    rc = run(["--xlsx", str(f), "--mode", "auto",
              "--nodes", "Diamond:6,7:0.5", "--out", str(out)])
    assert rc == 0


def test_no_feasible_summary_preserves_actual_failure_reasons(monkeypatch, capsys):
    from sjtu_tpmshx.design import cli, report

    designs = [SimpleNamespace(reason=reason) for reason in
               ['not-converged@final', 'Q<target@final', 'not-converged@final']]
    monkeypatch.setattr(cli, 'load_cases', lambda _: [object()])
    monkeypatch.setattr(cli, 'enumerate_select', lambda *a, **kw: (designs, None))
    monkeypatch.setattr(report, 'write_xlsx', lambda *a: (3, 0, 3))
    assert cli.run(['--xlsx', 'unused.xlsx', '--out', 'unused-out.xlsx']) == 0
    message = capsys.readouterr().err
    assert 'not-converged@final (2)' in message
    assert 'Q<target@final (1)' in message
    assert '450mm' not in message


@pytest.mark.parametrize('stage', ['enumeration', 'refinement', 'first_candidate'])
def test_cli_failure_keeps_completed_report_and_original_error(monkeypatch, tmp_path, stage):
    from sjtu_tpmshx.design import select, optimize, sizing
    failure = RuntimeError('injected design failure')
    calls = []
    def candidate(cases, topo, l, t, *args, **kwargs):
        calls.append(l)
        if stage == 'first_candidate' or (stage == 'enumeration' and l == 6):
            raise failure
        return sizing.Design(True, topo=topo, l=l, t=t, V=l / 1000.)
    def refine(*args, **kwargs):
        raise failure
    monkeypatch.setattr(select, 'size_fixed_cell', candidate)
    monkeypatch.setattr(optimize, 'warm_start_joint', refine)
    source, output = tmp_path / 'spec.xlsx', tmp_path / 'partial.xlsx'
    _spec(source)
    output.write_bytes(b'previous report')
    args = ['--xlsx', str(source), '--nodes', 'Diamond:5,6,7:0.4', '--jobs', '1',
            '--out', str(output)]
    if stage == 'refinement':
        args.append('--refine')
    with pytest.raises(RuntimeError) as caught:
        run(args)
    assert caught.value is failure
    if stage == 'first_candidate':
        assert calls == [5] and output.read_bytes() == b'previous report'
        return
    assert calls == ([5, 6] if stage == 'enumeration' else [5, 6, 7])
    workbook = openpyxl.load_workbook(output)
    for sheet in workbook:
        rows = list(sheet.values)
        assert '失败' in rows[1][rows[0].index('任务状态')]
        assert '取消' not in rows[1][rows[0].index('任务状态')]
    rows = list(workbook['构型汇总'].values)
    assert len(rows) == (2 if stage == 'enumeration' else 4)
    assert rows[1][rows[0].index('可行')] == '是'
    assert rows[1][rows[0].index('标记')].startswith('已完成候选内')
    workbook.close()


def test_partial_report_error_does_not_hide_computation_error(monkeypatch, tmp_path, capsys):
    from sjtu_tpmshx.design import select, sizing, report
    failure = ValueError('original computation failure')
    def candidate(cases, topo, l, t, *args, **kwargs):
        if l == 6:
            raise failure
        return sizing.Design(False, topo=topo, l=l, t=t)
    def export(*args, **kwargs):
        raise OSError('output unavailable')
    monkeypatch.setattr(select, 'size_fixed_cell', candidate)
    monkeypatch.setattr(report, 'write_xlsx', export)
    source = tmp_path / 'spec.xlsx'
    _spec(source)
    with pytest.raises(ValueError) as caught:
        run(['--xlsx', str(source), '--nodes', 'Diamond:5,6:0.4', '--jobs', '1',
             '--out', str(tmp_path / 'partial.xlsx')])
    assert caught.value is failure
    assert 'output unavailable' in capsys.readouterr().err
