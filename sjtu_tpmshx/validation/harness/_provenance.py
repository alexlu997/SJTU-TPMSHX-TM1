"""Provenance helper for validation CSV outputs.

C.4 of the 2026-05-06 audit fix campaign — every CSV produced by a
validation script should carry a header naming the producer, the
git commit it was run against, and the wall-clock timestamp. Without
this, regenerating a CSV silently overwrites prior numbers and the
"which run does this dP table belong to?" question becomes folklore.

Two artefacts per CSV:

1. **Comment-prefixed header** inside the CSV:

       # script: validation/cases/mms_phase_a3_h_refine.py
       # commit: d15be56
       # date:   2026-05-07T13:10:42+08:00
       case,N,h,L2_A,...

   Readers can keep using ``pd.read_csv(path, comment='#')`` to skip
   it transparently. Reading without ``comment='#'`` can misinterpret
   the provenance lines as a table header; use the read helper below.

2. **Sidecar ``<csv>.meta.json``** with structured metadata, useful
   when something other than pandas reads the CSV (R, awk, Excel).

API
---
``write_csv_with_provenance(df, path, script)`` — preferred entry
``read_csv_with_provenance(path)`` — returns ``(df, meta_dict)``
"""
from __future__ import annotations

import datetime as _dt
import json as _json
import subprocess as _sp
import tempfile
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

from sjtu_tpmshx.io.file_set import staged_files


REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = REPO_ROOT / 'validation'


def output_path(path) -> Path:
    """Resolve a new output path without allowing writes to frozen references."""
    path = Path(path).resolve()
    if path.is_relative_to(REFERENCE_DIR.resolve()):
        raise ValueError(f'Validation reference directory is read-only: {path}. '
                         'Write new results under .cache/validation instead.')
    return path


def output_directory(name: str, path=None) -> Path:
    """Use an explicit output directory or create a separate local run directory."""
    if path is not None:
        out = output_path(path)
        out.mkdir(parents=True, exist_ok=True)
        return out
    root = REPO_ROOT.parent / '.cache' / 'validation'
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f'{name}-', dir=root))


# ---------------------------------------------------------------- git/time


def _git_sha(short: bool = True) -> str:
    """Return current commit sha (short by default). Empty string if not
    in a git repo or git is unavailable."""
    try:
        cmd = ['git', 'rev-parse', '--short' if short else 'HEAD', 'HEAD']
        if not short:
            cmd = ['git', 'rev-parse', 'HEAD']
        out = _sp.check_output(cmd, cwd=str(REPO_ROOT),
                               stderr=_sp.DEVNULL).decode('utf-8').strip()
        return out
    except Exception:
        return ''


def _iso_now() -> str:
    """Local time, ISO 8601 with offset. Example: 2026-05-07T13:10:42+08:00."""
    return _dt.datetime.now().astimezone().isoformat(timespec='seconds')


# ---------------------------------------------------------------- write


def _normalise_script(script: str) -> str:
    """Render script as a repo-relative posix path for stable headers."""
    p = Path(script)
    if p.is_absolute():
        try:
            p = p.relative_to(REPO_ROOT)
        except ValueError:
            pass
    return str(p).replace('\\', '/')


def _build_header_lines(script: str, sha: str, when: str) -> str:
    return (
        f"# script: {_normalise_script(script)}\n"
        f"# commit: {sha or '<no-git>'}\n"
        f"# date:   {when}\n"
    )


def write_csv_with_provenance(df: pd.DataFrame, path,
                              script: str,
                              sidecar: bool = True,
                              **to_csv_kw) -> Dict[str, str]:
    """Write ``df`` to ``path`` with a comment-prefixed provenance header.

    ``to_csv_kw`` is forwarded to ``DataFrame.to_csv`` (e.g. ``index=False``).
    Default behaviour matches ``df.to_csv(path, index=False)``.
    The package validation directory holds recorded references and cannot be
    used as a destination, including through a resolved symbolic link.
    CSV and sidecar are published together; disabling the sidecar removes
    any previous companion so readers use the new inline provenance.

    Returns the metadata dict, also written when sidecar is enabled.
    """
    path = output_path(path)
    meta_path = path.with_suffix(path.suffix + '.meta.json')
    output_path(meta_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sha = _git_sha(short=True)
    when = _iso_now()
    header = _build_header_lines(script, sha, when)
    to_csv_kw.setdefault('index', False)
    meta = dict(
        script=_normalise_script(script),
        commit=sha,
        date=when,
        rows=int(len(df)),
        columns=list(map(str, df.columns)),
    )
    with staged_files([path, meta_path] if sidecar else [path],
                      remove=() if sidecar else [meta_path]) as stage:
        staged_csv = stage / path.name
        with open(staged_csv, 'w', encoding='utf-8', newline='') as f:
            f.write(header)
        df.to_csv(staged_csv, mode='a', **to_csv_kw)
        if sidecar:
            with open(stage / meta_path.name, 'w', encoding='utf-8') as f:
                _json.dump(meta, f, indent=2, ensure_ascii=False)
    return meta


# ---------------------------------------------------------------- read


def read_csv_with_provenance(path, **read_csv_kw
                             ) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """Read CSV honouring ``# ...`` provenance lines + load sidecar meta.

    ``read_csv_kw`` is forwarded to ``pd.read_csv`` (``comment='#'`` is
    forced). Returns ``(df, meta_dict)``; meta dict is the raw sidecar
    JSON or, if no sidecar exists, parsed from the first three # lines.
    """
    path = Path(path)
    read_csv_kw['comment'] = '#'
    df = pd.read_csv(path, **read_csv_kw)
    meta_path = path.with_suffix(path.suffix + '.meta.json')
    meta: Dict[str, str] = {}
    if meta_path.exists():
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = _json.load(f)
        except Exception:
            meta = {}
    if not meta:
        # Fallback: parse the leading # lines
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for ln in f.readlines()[:6]:
                    if not ln.startswith('#'):
                        break
                    if ':' in ln:
                        k, v = ln.lstrip('#').split(':', 1)
                        meta[k.strip()] = v.strip()
        except Exception:
            pass
    return df, meta
