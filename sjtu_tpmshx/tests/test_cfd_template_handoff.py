"""Generated coefficient sheets are directly consumable as seven-column CSV."""
import csv
import importlib

import openpyxl
import pytest


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
