"""Unit tests for validation.harness._provenance.

C.4 of the 2026-05-06 audit fix campaign — every validation CSV now
carries a comment-prefixed provenance header (script + commit + date)
plus a sidecar ``.meta.json``. This test exercises the helper end-to-end
to lock in the contract.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from sjtu_tpmshx.validation.harness import _provenance as provenance
from sjtu_tpmshx.validation.harness._provenance import (
    write_csv_with_provenance,
    read_csv_with_provenance,
)


# ---------------------------------------------------------------- write


def test_write_csv_with_provenance_creates_header_and_sidecar(tmp_path):
    df = pd.DataFrame({'a': [1, 2, 3], 'b': [4.0, 5.0, 6.0]})
    out = tmp_path / 'out.csv'
    meta = write_csv_with_provenance(df, out, 'tests/fake.py')

    # Header on first three lines
    lines = out.read_text(encoding='utf-8').splitlines()
    assert lines[0].startswith('# script:')
    assert lines[1].startswith('# commit:')
    assert lines[2].startswith('# date:')
    assert lines[3] == 'a,b'

    # Sidecar present + minimal fields
    sidecar = out.with_suffix(out.suffix + '.meta.json')
    assert sidecar.exists()
    side = json.loads(sidecar.read_text(encoding='utf-8'))
    assert side['script'].endswith('tests/fake.py')
    assert side['rows'] == 3
    assert side['columns'] == ['a', 'b']

    # Returned meta consistent
    assert meta['rows'] == 3
    assert meta['date'] == side['date']


def test_write_csv_pandas_can_still_read_with_comment(tmp_path):
    df = pd.DataFrame({'x': [10, 20]})
    out = tmp_path / 'one_col.csv'
    write_csv_with_provenance(df, out, 'tests/fake.py')
    re = pd.read_csv(out, comment='#')
    assert list(re['x']) == [10, 20]


# ---------------------------------------------------------------- read


def test_read_csv_with_provenance_returns_df_and_meta(tmp_path):
    out = tmp_path / 'rt.csv'
    df = pd.DataFrame({'x': [1, 2]})
    write_csv_with_provenance(df, out, 'tests/round.py')
    df2, meta = read_csv_with_provenance(out)
    assert list(df2['x']) == [1, 2]
    assert meta['script'].endswith('tests/round.py')


def test_read_csv_with_provenance_falls_back_to_inline_when_no_sidecar(tmp_path):
    out = tmp_path / 'no_side.csv'
    df = pd.DataFrame({'x': [1]})
    write_csv_with_provenance(df, out, 'tests/no_side.py')
    # Drop the sidecar; reader should still get a meta dict.
    out.with_suffix(out.suffix + '.meta.json').unlink()
    _, meta = read_csv_with_provenance(out)
    assert 'script' in meta or 'commit' in meta


@pytest.mark.parametrize('failure,sidecar', [('csv', True), ('json', True), ('csv', False)])
def test_failed_replacement_preserves_csv_and_metadata(tmp_path, monkeypatch, failure, sidecar):
    out = tmp_path / 'result.csv'
    meta_path = out.with_suffix('.csv.meta.json')
    write_csv_with_provenance(pd.DataFrame({'old': [1]}), out, 'old.py')
    before = {path: path.read_bytes() for path in (out, meta_path)}

    if failure == 'csv':
        def fail_csv(self, path, **kwargs):
            Path(path).write_text('partial CSV', encoding='utf-8')
            raise OSError('CSV write failed')
        monkeypatch.setattr(pd.DataFrame, 'to_csv', fail_csv)
    else:
        def fail_json(value, stream, **kwargs):
            stream.write('{"partial":')
            raise OSError('JSON write failed')
        monkeypatch.setattr(provenance._json, 'dump', fail_json)

    with pytest.raises(OSError, match='write failed'):
        write_csv_with_provenance(pd.DataFrame({'new': [2]}), out, 'new.py', sidecar=sidecar)
    assert {path: path.read_bytes() for path in before} == before
    assert not list(tmp_path.glob('.tm1-publish-*'))


def test_replacement_without_sidecar_removes_old_metadata(tmp_path):
    out = tmp_path / 'result.csv'
    meta_path = out.with_suffix('.csv.meta.json')
    write_csv_with_provenance(pd.DataFrame({'old': [1]}), out, 'old.py')
    expected = pd.DataFrame({'new': [2.5], 'other': [3.5]})
    write_csv_with_provenance(expected, out, 'new.py', sidecar=False, sep=';', float_format='%.1f')
    result, meta = read_csv_with_provenance(out, sep=';')
    pd.testing.assert_frame_equal(result, expected)
    assert meta['script'] == 'new.py'
    assert not meta_path.exists()


@pytest.mark.parametrize('sidecar', [True, False])
def test_reference_sidecar_symlink_rejected_before_csv_write(tmp_path, monkeypatch, sidecar):
    reference_dir = tmp_path / 'references'
    reference_dir.mkdir()
    reference = reference_dir / 'original.meta.json'
    reference.write_text('frozen metadata', encoding='utf-8')
    monkeypatch.setattr(provenance, 'REFERENCE_DIR', reference_dir)
    out = tmp_path / 'result.csv'
    out.write_text('old CSV', encoding='utf-8')
    meta_path = out.with_suffix('.csv.meta.json')
    meta_path.symlink_to(reference)
    with pytest.raises(ValueError, match='reference directory is read-only'):
        write_csv_with_provenance(pd.DataFrame({'new': [2]}), out, 'new.py', sidecar=sidecar)
    assert out.read_text(encoding='utf-8') == 'old CSV'
    assert meta_path.is_symlink()
    assert reference.read_text(encoding='utf-8') == 'frozen metadata'
