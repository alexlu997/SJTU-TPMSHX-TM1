"""The new Excel check must use historical mdot and developed-cell Nu."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sjtu_tpmshx.validation.cases import validate_water_nu_excel as validator


def test_current_basis_ignores_legacy_velocity_and_full_core_nu(monkeypatch):
    raw = pd.DataFrame(dict(
        geometry_id=['D_7_6'], lattice=['D'], cell_size_mm=[10.],
        wall_thickness_mm=[6.], rho_kg_m3=[1000.], mu_Pa_s=[.001],
        cp_J_kgK=[4200.], k_W_mK=[.6], Dh_m=[.001], mdot_in_kg_s=[.01],
        Core2_Nu=[20.], Core3_Nu=[40.], Core1_Nu=[1000.],
        Nu_core=[1000.], Um_m_s=[123.]))
    # A known geometry isolates the units/reduction from the geometry algorithm.
    monkeypatch.setattr(validator, 'attach_geometry', lambda d, topo:
                        d.assign(L_mm=10., eps_f=.25, Dh_cfd_m=d.Dh_m, Dh_m=.002))
    d = validator.evaluate(raw)
    assert len(d) == 1
    assert d.u_current_m_s.iloc[0] == pytest.approx(.4)
    assert d.Re_current.iloc[0] == pytest.approx(800.)
    assert d.Pr_current.iloc[0] == pytest.approx(7.)
    assert d.Nu_ref.iloc[0] == pytest.approx(60.)
    changed = validator.evaluate(raw.assign(Um_m_s=999., Nu_core=9999., Core1_Nu=9999.))
    pd.testing.assert_frame_equal(d[['Nu_ref', 'Nu_pred']], changed[['Nu_ref', 'Nu_pred']])
    with pytest.raises(ValueError, match='invalid required numeric data'):
        validator.evaluate(raw.assign(Core3_Nu=np.nan))


def test_accuracy_gate_rejects_either_error_without_rounding():
    assert validator.accepted(dict(rmsre=.10, bias=-.05))
    assert not validator.accepted(dict(rmsre=.100001, bias=0.))
    assert not validator.accepted(dict(rmsre=.09, bias=-.050001))


OUTPUT_NAMES = ('rows.csv', 'by_geometry.csv', 'by_Re.csv', 'worst_20.csv',
                'summary.json', 'report.md')


@pytest.mark.parametrize('name', ['rows.csv', 'summary.json', 'report.md'])
def test_cli_rejects_input_output_collision_before_loading(tmp_path, monkeypatch, capsys, name):
    source = tmp_path / name
    source.write_bytes(b'original workbook')
    monkeypatch.setattr(pd, 'read_excel', lambda *a, **kw: pytest.fail('input loaded before path check'))
    with pytest.raises(SystemExit) as error:
        validator.main(['--source', str(source), '--out', str(tmp_path)])
    assert error.value.code == 2
    assert 'output overlaps input' in capsys.readouterr().err
    assert source.read_bytes() == b'original workbook'


def test_cli_rejects_output_symlink_to_input_before_loading(tmp_path, monkeypatch, capsys):
    source = tmp_path / 'input.xlsx'
    source.write_bytes(b'original workbook')
    try:
        (tmp_path / 'rows.csv').symlink_to(source)
    except OSError as exc:
        pytest.skip(f'symlinks unavailable: {exc}')
    monkeypatch.setattr(pd, 'read_excel', lambda *a, **kw: pytest.fail('input loaded before path check'))
    with pytest.raises(SystemExit) as error:
        validator.main(['--source', str(source), '--out', str(tmp_path)])
    assert error.value.code == 2
    assert 'output overlaps input' in capsys.readouterr().err
    assert source.read_bytes() == b'original workbook'
    assert (tmp_path / 'rows.csv').is_symlink()


def test_cli_rejects_colliding_outputs_before_loading(tmp_path, monkeypatch, capsys):
    summary = tmp_path / 'summary.json'
    summary.write_text('previous summary', encoding='utf-8')
    try:
        (tmp_path / 'report.md').symlink_to(summary)
    except OSError as exc:
        pytest.skip(f'symlinks unavailable: {exc}')
    monkeypatch.setattr(pd, 'read_excel', lambda *a, **kw: pytest.fail('input loaded before path check'))
    with pytest.raises(SystemExit) as error:
        validator.main(['--source', str(tmp_path / 'input.xlsx'), '--out', str(tmp_path)])
    assert error.value.code == 2
    assert 'output paths overlap' in capsys.readouterr().err
    assert summary.read_text(encoding='utf-8') == 'previous summary'


def test_cli_rejects_frozen_output_directory_before_loading(monkeypatch, capsys):
    from sjtu_tpmshx.validation.harness._provenance import REFERENCE_DIR

    monkeypatch.setattr(pd, 'read_excel', lambda *a, **kw: pytest.fail('input loaded before path check'))
    with pytest.raises(SystemExit) as error:
        validator.main(['--out', str(REFERENCE_DIR)])
    assert error.value.code == 2
    assert 'reference directory is read-only' in capsys.readouterr().err


@pytest.fixture
def workbook(tmp_path, monkeypatch):
    # Isolate voxel geometry only; keep the real reader, 1879-row membership,
    # current correlation, reduction, gates and all six writers.
    monkeypatch.setattr(validator, 'attach_geometry', lambda d, topo:
                        d.assign(L_mm=10., eps_f=.25, Dh_cfd_m=d.Dh_m, Dh_m=.002))
    rows = []
    for lattice, count, topology in [('D', 940, 'Diamond'), ('G', 939, 'Gyroid')]:
        reference = float(validator.nu_water_topo(topology, 800., 7.)) / 2
        for index in range(count):
            rows.append(dict(W=f'{lattice}{index:05}', geometry_id=f'{lattice}_{index % 20}',
                             lattice=lattice, cell_size_mm=10., wall_thickness_mm=.6,
                             rho_kg_m3=1000., mu_Pa_s=.001, cp_J_kgK=4200., k_W_mK=.6,
                             Dh_m=.001, mdot_in_kg_s=.01,
                             Core2_Nu=reference, Core3_Nu=reference))
    raw = pd.DataFrame(rows)

    def write(multiplier):
        source = tmp_path / f'input-{multiplier}.xlsx'
        raw.assign(Core2_Nu=raw.Core2_Nu * multiplier,
                   Core3_Nu=raw.Core3_Nu * multiplier).to_excel(source, index=False)
        return source

    return write


def test_cli_replaces_complete_pass_with_complete_failed_verdict(tmp_path, workbook):
    out = tmp_path / 'output'
    for multiplier, expected_exit in [(1, 0), (2, 2)]:
        source = workbook(multiplier)
        original = source.read_bytes()
        assert validator.main(['--source', str(source), '--out', str(out)]) == expected_exit
        assert source.read_bytes() == original
        assert {path.name for path in out.iterdir()} == set(OUTPUT_NAMES)
        summary = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
        assert summary['source'] == str(source.resolve())
        assert summary['passed'] is (expected_exit == 0)
        assert summary['native_exit'] == expected_exit
        assert summary['n_planned'] == 1880 and summary['n_evaluated'] == 1879
        assert {topo: score['n'] for topo, score in summary['topology'].items()} == {
            'Diamond': 940, 'Gyroid': 939}
        rows = pd.read_csv(out / 'rows.csv')
        assert len(rows) == 1879 and rows.W.is_unique
        np.testing.assert_allclose(rows.relative_error, 1 / multiplier - 1, atol=1e-14)
        assert f'原生退出码 {expected_exit}' in (out / 'report.md').read_text(encoding='utf-8')


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('failed_name', ['by_geometry.csv', 'report.md'])
def test_cli_write_failure_preserves_entire_previous_set(
        tmp_path, workbook, monkeypatch, existing, failed_name):
    out = tmp_path / 'output'
    out.mkdir()
    if existing:
        for name in OUTPUT_NAMES:
            (out / name).write_text(f'previous {name}', encoding='utf-8')
    before = {path.name: path.read_bytes() for path in out.iterdir()}
    source = workbook(2)
    original_csv, original_text = pd.DataFrame.to_csv, Path.write_text

    def csv(frame, path, *args, **kwargs):
        if Path(path).name == failed_name:
            raise OSError('output write denied')
        return original_csv(frame, path, *args, **kwargs)

    def text(path, *args, **kwargs):
        if path.name == failed_name:
            raise OSError('output write denied')
        return original_text(path, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, 'to_csv', csv)
    monkeypatch.setattr(Path, 'write_text', text)
    with pytest.raises(OSError, match='output write denied'):
        validator.main(['--source', str(source), '--out', str(out)])
    assert {path.name: path.read_bytes() for path in out.iterdir()} == before


@pytest.mark.parametrize('existing', [False, True])
def test_cli_last_publication_failure_rolls_back_entire_set(tmp_path, workbook, monkeypatch, existing):
    from sjtu_tpmshx.io import file_set

    out = tmp_path / 'output'
    out.mkdir()
    if existing:
        for name in OUTPUT_NAMES:
            (out / name).write_text(f'previous {name}', encoding='utf-8')
    before = {path.name: path.read_bytes() for path in out.iterdir()}
    source = workbook(2)
    original = file_set.os.replace

    def replace(source, target):
        if Path(target) == out / 'report.md' and Path(source).parent.name.startswith('.tm1-publish-'):
            raise OSError('final publication denied')
        return original(source, target)

    monkeypatch.setattr(file_set.os, 'replace', replace)
    with pytest.raises(OSError, match='final publication denied'):
        validator.main(['--source', str(source), '--out', str(out)])
    assert {path.name: path.read_bytes() for path in out.iterdir()} == before
