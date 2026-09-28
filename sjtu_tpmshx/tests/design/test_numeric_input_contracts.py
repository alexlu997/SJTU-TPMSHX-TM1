"""Invalid scalar inputs and residuals must fail before they become designs."""
import pytest

from sjtu_tpmshx.design import sizing
from sjtu_tpmshx.design.cases import DesignCase
from sjtu_tpmshx.design.forward import ForwardResult


def _case():
    return DesignCase(1, 'air', 400., 2e5, .01, 'air', 300., 2e5, .01,
                      100., .05, .05)


@pytest.mark.parametrize('density', [float('nan'), float('inf'), -float('inf'), 0., -7900.])
def test_invalid_material_density_stops_before_geometry(monkeypatch, density):
    monkeypatch.setattr(sizing, 'tpms_geometry', lambda *a, **kw: pytest.fail('geometry reached'))
    with pytest.raises(ValueError, match='rho_s.*finite.*positive'):
        sizing.size_fixed_cell([_case()], 'Diamond', 6., .4, rho_s=density)


@pytest.mark.parametrize('density', ['nan', '-7900'])
def test_cli_invalid_density_preserves_existing_report(tmp_path, monkeypatch, density):
    from sjtu_tpmshx.design import cli
    source, output = tmp_path / 'cases.csv', tmp_path / 'report.xlsx'
    source.write_text('case,hot_fluid,T_in_h_K,P_in_h_kPa,mdot_h,cold_fluid,'
                      'T_in_c_K,P_in_c_kPa,mdot_c,Q_kW,dPlim_h,dPlim_c\n'
                      '1,air,400,200,.01,air,300,200,.01,.1,.05,.05\n')
    output.write_bytes(b'existing report')
    monkeypatch.setattr(sizing, 'tpms_geometry', lambda *a, **kw: pytest.fail('geometry reached'))
    with pytest.raises(ValueError, match='rho_s.*finite.*positive'):
        cli.run(['--xlsx', str(source), '--mode', 'fixed', '--cell', 'Diamond,6,.4',
                 '--rho-s', density, '--out', str(output)])
    assert output.read_bytes() == b'existing report'


@pytest.mark.parametrize('target', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_explicit_target_stops_before_first_forward(monkeypatch, target):
    monkeypatch.setattr(sizing, 'forward', lambda *a, **kw: pytest.fail('forward reached'))
    with pytest.raises(ValueError, match='target.*finite'):
        sizing.solve_Lx(_case(), 'Diamond', 6., .4, .1, 'cross', target=target)


@pytest.mark.parametrize('quantity', ['Q_hot', 'T_out_hot'])
def test_nonfinite_residual_in_brent_callback_never_enters_bisection(monkeypatch, quantity):
    calls = []
    def forward(case, topo, l, t, s, length, arrangement, **kwargs):
        calls.append(length)
        values = dict(T_out_hot=400.-1000.*length, Q_hot=1000.*length)
        if len(calls) == 3:  # First callback after the successful bracket checks.
            values[quantity] = float('nan')
        return ForwardResult(values['T_out_hot'], 310., values['Q_hot'], 100.,
                             .01, .01, 1000., 1000., run_status={'converged': True})
    monkeypatch.setattr(sizing, 'forward', forward)
    with pytest.raises(ValueError, match='residual.*finite'):
        sizing.solve_Lx(_case(), 'Diamond', 6., .4, .1, 'cross',
                        target=300. if quantity == 'T_out_hot' else None)
    assert len(calls) == 3


def test_nonfinite_final_residual_is_not_returned_as_a_length(monkeypatch):
    calls = []
    def forward(case, topo, l, t, s, length, arrangement, **kwargs):
        calls.append(length)
        duty = float('nan') if kwargs['tol'] == sizing.LTNE_TOL else 1000.*length
        return ForwardResult(300., 310., duty, 100., .01, .01, 1000., 1000.,
                             run_status={'converged': True})
    monkeypatch.setattr(sizing, 'forward', forward)
    with pytest.raises(ValueError, match='residual.*finite'):
        sizing.solve_Lx(_case(), 'Diamond', 6., .4, .1, 'cross')
