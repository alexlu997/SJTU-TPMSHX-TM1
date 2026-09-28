"""The experimental-Q runner's two-file checkpoint, without automatic reuse."""
from io import StringIO
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys

import pandas as pd

from sjtu_tpmshx.domain.provenance import repository_environment
from sjtu_tpmshx.io.file_set import staged_files
from sjtu_tpmshx.runs.tools.check_locked_environment import installed_versions


def runtime_identity(root, *, generated=()):
    """Record actual code/environment; only clean identified code can resume."""
    root = Path(root).resolve()
    env = repository_environment(root)
    commit, dirty = '', True
    if env is not None:
        try:
            commit = subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'], cwd=root, env=env, text=True,
                stderr=subprocess.DEVNULL).strip()
            tracked = subprocess.check_output(
                ['git', 'diff', '--name-only', '-z', 'HEAD'], cwd=root, env=env).split(b'\0')
            untracked = subprocess.check_output(
                ['git', 'ls-files', '--others', '--exclude-standard', '-z'],
                cwd=root, env=env).split(b'\0')
            outputs = {Path(path).resolve() for path in generated}
            dirty = any(tracked) or any(
                path and (root / os.fsdecode(path)).resolve() not in outputs
                for path in untracked)
        except (OSError, subprocess.CalledProcessError):
            commit, dirty = '', True
    return dict(commit=commit, dirty=dirty, python=sys.version,
                interpreter=sys.executable, platform=platform.platform(),
                packages={key: sorted(value) for key, value in installed_versions().items()
                          if key != 'pip'},
                environment={key: value for key, value in os.environ.items()
                             if key.startswith('TPMSHX_')})


def member_key(row):
    case = row['case']
    if isinstance(case, bool) or int(case) != case or case <= 0:
        raise ValueError('checkpoint contains an invalid case ID')
    return f"{row['topology']}/{row['dimension']}/{int(case)}"


def reusable(row):
    """Execution completion alone is not numerical/reference qualification."""
    return (all(row.get(key) is True for key in ('converged', 'numerical_ok', 'reference_ok'))
            and all(math.isfinite(row.get(key, float('nan'))) and row[key] > 0
                    for key in ('Q_solver_W', 'Q_ref_W')))


def publish(root, state, rows):
    frame = pd.DataFrame(list(rows.values())) if rows else pd.DataFrame(
        columns=['topology', 'case', 'dimension'])
    with staged_files([root / 'partial.csv', root / 'state.json']) as stage:
        frame.to_csv(stage / 'partial.csv', index=False, encoding='utf-8')
        (stage / 'state.json').write_text(
            json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def open_checkpoint(root, snapshot, members, *, resume):
    root = Path(root)
    if not resume:
        root.mkdir(parents=True, exist_ok=True)
        if any(root.iterdir()):
            raise ValueError('checkpoint output directory must be new or empty')
        state = dict(schema_version=1, snapshot=snapshot, status='running',
                     members={member_key(member): dict(**member, status='pending', attempts=[])
                              for member in members})
        publish(root, state, {})
        return state, {}
    state = json.loads((root / 'state.json').read_text(encoding='utf-8'))
    identity = snapshot['runtime']
    if not identity['commit'] or identity['dirty']:
        raise ValueError('resume requires an identified clean code checkout')
    if state.get('schema_version') != 1 or state.get('snapshot') != snapshot:
        raise ValueError('checkpoint code, environment, settings or input snapshot differs')
    if set(state.get('members', {})) != {member_key(member) for member in members}:
        raise ValueError('checkpoint member list differs')
    frame = pd.read_csv(root / 'partial.csv', float_precision='round_trip')
    rows = {}
    for row in frame.to_dict('records'):
        key = member_key(row)
        if key in rows or key not in state['members']:
            raise ValueError('checkpoint has duplicate or unexpected result members')
        rows[key] = row
    for key, member in state['members'].items():
        if member_key(member) != key or member['status'] not in (
                'pending', 'running', 'completed', 'failed', 'cancelled'):
            raise ValueError('checkpoint member state is invalid')
        receipts = [attempt['result_csv'] for attempt in member['attempts']
                    if 'result_csv' in attempt]
        if bool(receipts) != (key in rows):
            raise ValueError('checkpoint result rows are incomplete')
        if receipts:
            expected = pd.read_csv(StringIO(receipts[-1]), float_precision='round_trip')
            actual = frame[frame.apply(member_key, axis=1) == key].reset_index(drop=True)
            try:
                pd.testing.assert_frame_equal(actual, expected, check_dtype=False,
                                              check_exact=True)
            except AssertionError as exc:
                raise ValueError('checkpoint CSV disagrees with its published member result') from exc
        if member['status'] == 'completed' and not receipts:
            raise ValueError('completed checkpoint member has no result')
    return state, rows
