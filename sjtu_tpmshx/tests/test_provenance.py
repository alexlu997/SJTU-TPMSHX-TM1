"""Unit tests for validation.harness._provenance.

C.4 of the 2026-05-06 audit fix campaign — every validation CSV now
carries a comment-prefixed provenance header (script + commit + date)
plus a sidecar ``.meta.json``. This test exercises the helper end-to-end
to lock in the contract.
"""
from __future__ import annotations

import json

import pandas as pd

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
