import openpyxl
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
