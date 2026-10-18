"""Generated coefficient sheets are directly consumable as seven-column CSV."""
import csv
import importlib
from unittest.mock import patch

import openpyxl
import pytest


@pytest.mark.parametrize('name', ['asym_build_cfd_design_xlsx', 'asym_build_cfd_worklist_xlsx'])
@pytest.mark.parametrize('topology, expected', [
    ('Diamond', dict(C=.3714, delta=.277, phi_lo=-.0944, phi_hi=.6484,
        eps_A=.459, eps_B=.2295, eps_sym=.3442, solid=.3115,
        kr_A=1.3333, kr_B=.6667, A0_A=711.1, A0_B=596.3,
        Dh_A_mm=2.5818, Dh_B_mm=1.5394)),
    ('Gyroid', dict(C=.3809, delta=.3886, phi_lo=.0077, phi_hi=.7694,
        eps_A=.5015, eps_B=.2505, eps_sym=.376, solid=.248,
        kr_A=1.3338, kr_B=.6662, A0_A=572.3, A0_B=492.,
        Dh_A_mm=3.505, Dh_B_mm=2.0363)),
])
def test_real_geometry_keeps_values_and_skip_policy(monkeypatch, capsys, name, topology, expected):
    from skimage import measure

    # Values come from the separate generators at 51204406, before extraction.
    generator = importlib.import_module(f'sjtu_tpmshx.runs.tools.{name}')
    monkeypatch.setattr(generator, 'N', 32)
    monkeypatch.setattr(generator, 'TPMS', [topology])
    monkeypatch.setattr(generator, 'SPLITS', [1., 2., 1e12])
    with patch.object(measure, 'marching_cubes', wraps=measure.marching_cubes) as triangulate:
        symmetric, split = generator._geom()
    assert triangulate.call_count == 4
    assert symmetric['delta'] == 0
    assert symmetric['eps_A'] == symmetric['eps_B'] == symmetric['eps_sym']
    assert symmetric['kr_A'] == symmetric['kr_B'] == 1
    assert split['tpms'] == topology
    assert split['split_r'] == 2
    assert {key: split[key] for key in expected} == pytest.approx(expected, rel=0, abs=5e-5)
    output = capsys.readouterr().out
    common = {'tpms', 'split_r', *expected}
    if name == 'asym_build_cfd_design_xlsx':
        assert set(split) == common | {'L_mm', 't_mm', 'tL', 'conn', 'label'}
        assert (split['L_mm'], split['t_mm'], split['tL']) == (5., .4, .08)
        assert split['conn'] == 'OK'
        assert split['label'] == f'{topology}_L5_t0.4_r2'
        assert output == f'[warn] {topology} r=1000000000000.0 unreachable (pinch); skipped\n'
    else:
        assert set(split) == common | {'pA', 'pB'}
        assert split['pA'] is split['pB'] is True
        assert output == ''


@pytest.mark.parametrize('name', ['asym_build_cfd_design_xlsx', 'asym_build_cfd_worklist_xlsx'])
@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig'])
def test_filled_template_csv_reaches_real_ingest(tmp_path, monkeypatch, name, encoding):
    from sjtu_tpmshx.df_surrogate import ingest_cfd_kappa, kappa_asym

    generator = importlib.import_module(f'sjtu_tpmshx.runs.tools.{name}')
    book = tmp_path / 'template.xlsx'
    geometry = dict(tpms='Gyroid', L_mm=5., t_mm=.4, tL=.08, C=.3,
        delta=.1, phi_lo=-.2, phi_hi=.4, solid=.2, split_r=1.5,
        eps_A=.48, eps_B=.32, eps_sym=.4, kr_A=1.2, kr_B=.8,
        A0_A=500., A0_B=500., Dh_A_mm=2., Dh_B_mm=2., conn='OK',
        label='synthetic', pA=True, pB=True)
    monkeypatch.setattr(generator, 'OUT', tmp_path)
    monkeypatch.setattr(generator, 'XLSX', book)
    monkeypatch.setattr(generator, '_geom', lambda: [geometry])
    if name == 'asym_build_cfd_worklist_xlsx':
        monkeypatch.setattr(generator, '_water_r1_ref', lambda: {})
    generator.build()
    workbook = openpyxl.load_workbook(book)
    rows = list(workbook['results_template'].values)
    workbook.close()
    expected = ('tpms', 'L_mm', 't_mm', 'eps_side', 'eps_sym', 'K_cfd', 'cF_cfd')
    assert rows[0] == expected
    assert len(rows) == 3
    path = tmp_path / 'filled.csv'
    with path.open('w', encoding=encoding, newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(rows[0])
        for row in rows[1:]:
            writer.writerow([*row[:5], 1e-8, 100.])
    # Isolate process-local research registration; parsing and model ratios run normally.
    monkeypatch.setattr(kappa_asym, '_KAPPA', {})
    assert ingest_cfd_kappa.ingest(str(path)) == {'Gyroid': 2}
    assert kappa_asym.has_table('Gyroid')
