"""Final sizing evidence, not the search's candidate, controls recommendation."""
from dataclasses import replace
import math

import pytest

from sjtu_tpmshx.design import sizing
from sjtu_tpmshx.design.cases import DesignCase
from sjtu_tpmshx.design.forward import ForwardResult
from sjtu_tpmshx.design.report import detail_rows, summary_rows
from sjtu_tpmshx.design.select import pareto_tags


@pytest.mark.parametrize('change,reason', [
    ({}, ''),
    ({'T_out_hot': 370.}, 'T_out>target'),
    ({'run_status': {'converged': False}}, 'not-converged'),
    ({'run_status': {}}, 'not-converged'),
    ({'dP_hot_frac': .06}, 'dP>lim'),
    ({'Re_hot': float('nan')}, 'nonfinite'),
])
def test_final_case_controls_feasibility_and_report(monkeypatch, change, reason):
    condition = DesignCase(1, 'air', 400., 101325., .01, 'air', 300., 101325., .01,
                           None, .05, .05, dT=50.)
    good = ForwardResult(340., 330., 600., 600., .01, .01, 1000., 1000.,
                         run_status={'converged': True})
    def forward(*args, tol=sizing.LTNE_TOL, **kwargs):
        return replace(good, **change) if tol == sizing.LTNE_TOL else good
    monkeypatch.setattr(sizing, 'forward', forward)
    monkeypatch.setattr(sizing, 'tpms_geometry', lambda *a, **kw: {'epsilon': .7})
    monkeypatch.setattr(sizing, 'dP_fracs', lambda *a, **kw: (.01, .01))
    d = sizing.size_fixed_cell([condition], 'Diamond', 6., .4)
    assert d.feasible is (not reason)
    assert reason in d.reason
    tags = pareto_tags([d])
    assert bool(tags) is (not reason)
    assert summary_rows([d], tags)[0]['可行'] == ('否' if reason else '是')
    details = detail_rows([d])
    assert len(details) == 1  # Failed final evidence is still exported.
    assert reason in details[0]['终验']
    if reason == 'nonfinite':
        assert math.isnan(details[0]['Re热'])


def test_duty_target_is_checked_against_final_duty(monkeypatch):
    condition = DesignCase(1, 'air', 400., 101325., .01, 'air', 300., 101325., .01,
                           100., .05, .05)
    result = ForwardResult(300., 330., 90., 90., .01, .01, 1000., 1000.,
                           run_status={'converged': True})
    monkeypatch.setattr(sizing, 'solve_Lx', lambda *a, **kw: (.1, result))
    monkeypatch.setattr(sizing, 'forward', lambda *a, **kw: result)
    monkeypatch.setattr(sizing, 'tpms_geometry', lambda *a, **kw: {'epsilon': .7})
    monkeypatch.setattr(sizing, 'dP_fracs', lambda *a, **kw: (.01, .01))
    d = sizing.size_fixed_cell([condition], 'Diamond', 6., .4)
    assert not d.feasible and 'Q<target@final' in d.reason
