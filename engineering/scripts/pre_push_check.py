"""Run the light pre-push check on the current commit and write its run record.

Usage (from the repository root, with the `.venv-path` interpreter):

    python -m engineering.scripts.pre_push_check [--base origin/main]

The check selects work from the paths that changed between the selection base
(the merge base of --base and HEAD) and HEAD. It runs only light work:
check_docs.py, the lock check, pip check, ruff, check_types for darwin and win32,
the import audit with its cycle check, the changed test files, and the mapped
consumer nodes. Nodes that start native solves stay "pending heavy". Changes
that only CI can verify stay "CI pending". The run record goes to
.cache/pre-push/<head>.txt. The Git pre-push hook calls this module with --hook.
"""
import argparse
from fnmatch import fnmatch
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time

from engineering.scripts.ci_scope import select_scope

ROOT = Path(__file__).resolve().parents[2]
RECORDS = ROOT / '.cache/pre-push'
HAZARDS = ROOT / 'docs/agent-hazards.md'
LOCKS = ('engineering/requirements/base.txt',
         'engineering/requirements/bo-windows.txt' if sys.platform == 'win32'
         else 'engineering/requirements/bo-macos.txt')
EVENTS = 'TM1_PRE_PUSH_EVENTS'

UI = 'python/applications/gui/ui/'
IO = 'tests/python/test_io_actions.py::'
CLOSE = 'tests/python/test_workbench_navigation.py::test_window_close_cleans_both_volume_plotters_and_their_popups'
# Consumer map: changed path patterns -> light consumer nodes.
# Each node was checked: its call chain starts no native solve and no long-running subprocess.
# A short Git metadata query (provenance.repository_revision for export metadata) is permitted.
CONSUMERS = (
    ((UI + 'optimize_panel.py', UI + 'pareto_view.py', UI + 'design_peek.py', UI + 'volume_*.py',
      UI + 'result_export.py', UI + 'plot_3d_results.py', UI + 'panel_vis_3d.py', UI + 'vis3d_*.py'),
     (IO + 'test_continuous_field_preview_button_shows_and_exports_after_preset_load',
      IO + 'test_optimization_copy_uses_selected_result_tab_and_rejects_empty_field',
      IO + 'test_pareto_figure_copy_export_survives_field_result_then_clears_on_empty',
      IO + 'test_retained_pareto_export_does_not_take_new_compute_preset_name',
      IO + 'test_optimization_volume_copy_and_export_require_current_render')),
    ((UI + 'main_window.py', UI + 'mixins/*.py', UI + 'panel_vis_3d.py', UI + 'plot_3d_results.py',
      UI + 'volume_*.py', UI + 'vis3d_*.py'),
     (CLOSE,)),
)
HEAVY_DIRECTORIES = ('tests/python/native/', 'tests/python/integration_tm1/')
# Nodes that start a native solve but have no slow or heavy marker.
UNMARKED_SOLVES = {
    'tests/python/test_native_geometry.py::test_public_quick_design_replays_without_geometry_calls':
        'starts a native Quick Design solve',
}
SHARD_JOB = 'tests (...) step "Require complete coverage and platform reports"'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def changed_paths(base, head):
    # No rename detection: a rename gives the old and the new name, as in ci_scope.py.
    output = git('diff', '--name-only', '--no-renames', '-z', base, head, '--')
    return sorted(path for path in output.split('\0') if path)


def is_test_file(path):
    name = path.rsplit('/', 1)[-1]
    return path.startswith('tests/python/') and name.startswith('test_') and name.endswith('.py')


def select(paths, exists):
    """Return the light pytest targets, the pending-heavy items, and the CI-pending items."""
    files, nodes, heavy, ci = [], [], [], []
    for path in paths:
        if not exists(path):
            continue
        if path.startswith(HEAVY_DIRECTORIES) and is_test_file(path):
            heavy.append((path, 'native or integration test directory'))
        elif is_test_file(path):
            files.append(path)
        elif re.fullmatch(r'tests/python/_ci_[^/]*\.txt', path):
            ci.append((path, f'shard coverage needs CI reports; closed by {SHARD_JOB}'))
    for patterns, consumers in CONSUMERS:
        if any(fnmatch(path, pattern) for path in paths for pattern in patterns):
            nodes.extend(node for node in consumers
                         if node not in nodes and node.split('::')[0] not in files)
    return files, nodes, heavy, ci


def tree_paths(text):
    """Return the paths in a shard list that are absent from the HEAD tree."""
    entries = [line.split('::')[0].strip() for line in text.splitlines()]
    entries = [entry for entry in entries if entry and not entry.startswith('#')]
    present = set(git('ls-files', '--', *entries).splitlines()) if entries else set()
    return [entry for entry in entries if entry not in present]


def hazard_rows(paths):
    rows = []
    for line in HAZARDS.read_text(encoding='utf-8').splitlines():
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if not re.fullmatch(r'H\d+', cells[0]):
            continue
        patterns = re.findall(r'`([^`]+)`', cells[1])
        if any(fnmatch(path, pattern) for path in paths for pattern in patterns):
            rows.append(line)
    return rows


class Run:
    def __init__(self, python):
        self.python = python
        self.commands = []
        # As in CI, a missing native library or caller fails the test and does not skip it.
        self.env = dict(os.environ, MPLCONFIGDIR=str(ROOT / '.cache/matplotlib'),
                        XDG_CACHE_HOME=str(ROOT / '.cache/xdg'), TPMSHX_REQUIRE_NATIVE_DEPS_TESTS='1')

    def __call__(self, *args, label=None):
        start = time.monotonic()
        result = subprocess.run([self.python, *args], cwd=ROOT, env=self.env)
        text = label or ' '.join(['python', *args])
        self.commands.append((result.returncode == 0, round(time.monotonic() - start, 1), text))
        return result.returncode == 0


def run_tests(run, files, nodes):
    """Run the light targets once and return one result line for each node."""
    deselect = [node for node in UNMARKED_SOLVES if node.split('::')[0] in files]
    with tempfile.TemporaryDirectory(prefix='tm1-pre-push-') as directory:
        events = Path(directory) / 'events.jsonl'
        run.env[EVENTS] = str(events)
        targets = files + nodes
        run('-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-p', 'engineering.scripts.pre_push_check',
            '-m', 'not slow and not heavy', *[f'--deselect={node}' for node in deselect], *targets,
            label=f'python -m pytest -m "not slow and not heavy" ({len(files)} files, {len(nodes)} nodes)')
        del run.env[EVENTS]
        records = [json.loads(line) for line in events.read_text(encoding='utf-8').splitlines()] \
            if events.exists() else []
    results = {}
    for record in records:
        node, kind = record['node'], record['kind']
        if kind == 'deselected':
            reason = UNMARKED_SOLVES.get(node) or ('slow marker (real solve)' if 'slow' in record['markers']
                                                   else 'heavy manifest')
            results[node] = ('pending heavy', reason)
        elif kind == 'error':
            results[node] = ('failed', 'collection error')
        elif record['outcome'] == 'failed':
            results[node] = ('failed', record['when'])
        elif record['outcome'] == 'skipped' and results.get(node, ('',))[0] != 'failed':
            results[node] = ('skipped', record['reason'])
        elif node not in results:
            results[node] = ('passed', '')
    for target in targets:
        if not any(node == target or node.startswith((target + '::', target + '['))
                   for node in results):
            results[target] = ('not collected', 'no test matches this node ID')
    return results


def check(base_ref):
    head = git('rev-parse', 'HEAD')
    base = git('merge-base', base_ref, head)
    if git('status', '--porcelain'):
        sys.exit('pre-push check: the worktree has uncommitted or untracked changes. Commit them first.')
    start = time.monotonic()
    paths = changed_paths(base, head)
    tier = select_scope('pull_request', paths) if paths else 'docs'
    python = (ROOT / '.venv-path').read_text(encoding='utf-8').splitlines()[0].strip()
    run = Run(python)
    run('engineering/scripts/check_docs.py')
    results, lock, unmapped = {}, 'not checked', []
    if tier != 'docs':
        # The applicable lock is the one that the .venv-path environment matches.
        lock = next((name for name in LOCKS if subprocess.run(
            [python, '-m', 'sjtu_tpmshx.development.runs.tools.check_locked_environment', name],
            cwd=ROOT, capture_output=True).returncode == 0), None)
        run.commands.append((lock is not None, 0.0, 'python -m sjtu_tpmshx.development.runs.tools.'
                             f'check_locked_environment {lock or " / ".join(LOCKS) + " (no match)"}'))
        run('-m', 'pip', 'check')
        exists = set(git('ls-files').splitlines()).__contains__
        changed_python = [path for path in paths if path.endswith('.py') and exists(path)]
        if changed_python:
            run('-m', 'ruff', 'check', *changed_python, label=f'python -m ruff check ({len(changed_python)} files)')
        run('-m', 'engineering.scripts.check_types', '--platform', 'darwin')
        run('-m', 'engineering.scripts.check_types', '--platform', 'win32')
        run('-m', 'sjtu_tpmshx.development.runs.tools.audit_import_graph', '--fail-on-violations')
        files, nodes, heavy, ci = select(paths, exists)
        unmapped = [path for path in changed_python if not is_test_file(path) and not any(
            fnmatch(path, pattern) for patterns, _ in CONSUMERS for pattern in patterns)]
        if files or nodes:
            results.update(run_tests(run, files, nodes))
        results.update({path: ('pending heavy', reason) for path, reason in heavy})
        for path, reason in ci:
            missing = tree_paths((ROOT / path).read_text(encoding='utf-8'))
            results[path] = ('failed', f'missing paths: {missing}') if missing else ('CI pending', reason)
    counts = {}
    for result, _ in results.values():
        counts[result] = counts.get(result, 0) + 1
    passed = (all(ok for ok, _, _ in run.commands)
              and not {'failed', 'not collected'} & set(counts))
    seconds = round(time.monotonic() - start)
    summary = (f'Pre-push light check: {"pass" if passed else "FAIL"} at {head[:12]} '
               f'(selection base {base[:12]}, tier {tier}); '
               + (', '.join(f'{n} {result}' for result, n in sorted(counts.items())) or 'no test nodes')
               + f'; {seconds} s')
    lines = [
        'TM1 pre-push light check (engineering/scripts/pre_push_check.py)',
        f'base ref: {base_ref}', f'selection base: {base}', f'head: {head}', 'tree: clean',
        f'platform: {sys.platform} {platform.machine()}',
        f'python: {subprocess.check_output([python, "-c", "import platform; print(platform.python_version())"], text=True).strip()}',
        f'lock: {lock}',
        'native library variables: ' + (', '.join(sorted(k for k in os.environ if re.fullmatch(r'TPMSHX_\w*LIBRARY', k)))
                                        or 'none (package library directory)'),
        f'tier: {tier}', f'verdict: {"pass" if passed else "fail"}', f'summary: {summary}', '', 'commands:',
        *[f'  {"passed" if ok else "failed"}\t{seconds_} s\t{text}' for ok, seconds_, text in run.commands],
        '', 'nodes:',
        *[f'  {result}\t{node}' + (f'\t{reason}' if reason else '') for node, (result, reason) in sorted(results.items())],
        '', 'changed modules without a mapped consumer (trace their importers):', *[f'  {path}' for path in unmapped],
    ]
    RECORDS.mkdir(parents=True, exist_ok=True)
    (RECORDS / f'{head}.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    rows = hazard_rows(paths)
    print('\n'.join(lines[lines.index('commands:'):lines.index('nodes:')]))
    print('nodes other than passed:', *[f'  {result}\t{node}\t{reason}' for node, (result, reason)
                                        in sorted(results.items()) if result != 'passed'], sep='\n')
    print('\n'.join(lines[lines.index('changed modules without a mapped consumer (trace their importers):'):]))
    if rows:
        print('\nOpen hazards for the changed paths (docs/agent-hazards.md):', *rows, sep='\n')
    print(f'\n{summary}\nRun record: .cache/pre-push/{head}.txt')
    return passed


def record_matches(head, base):
    record = RECORDS / f'{head}.txt'
    if not record.exists():
        return False
    header = record.read_text(encoding='utf-8').split('\n\n', 1)[0].splitlines()[1:]
    fields = dict(line.split(': ', 1) for line in header)
    return (fields.get('head') == head and fields.get('selection base') == base
            and fields.get('tree') == 'clean' and fields.get('verdict') == 'pass')


def hook():
    """Check each pushed branch. Git gives '<local ref> <local sha> <remote ref> <remote sha>' lines."""
    for line in sys.stdin.read().splitlines():
        local_ref, local_sha = line.split()[:2]
        if not local_ref.startswith('refs/heads/') or not local_sha.strip('0'):
            continue
        base = git('merge-base', 'origin/main', local_sha)
        if record_matches(local_sha, base):
            print(f'pre-push: run record for {local_sha[:12]} passed.')
            continue
        if git('rev-parse', 'HEAD') != local_sha or git('status', '--porcelain'):
            sys.exit(f'pre-push: no passing run record for {local_ref} at {local_sha[:12]}. '
                     'In the clean worktree of that branch, run: '
                     'python -m engineering.scripts.pre_push_check')
        if not check('origin/main'):
            sys.exit('pre-push: the light check failed. See the run record above.')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base', default='origin/main', help='base ref; the selection base is its merge base with HEAD')
    parser.add_argument('--hook', action='store_true', help='read the refs that Git gives to the pre-push hook')
    args = parser.parse_args()
    if args.hook:
        hook()
    elif not check(args.base):
        sys.exit(1)


# pytest plugin hooks: the check loads this module with -p and reads the events.
def _event(**record):
    with open(os.environ[EVENTS], 'a', encoding='utf-8') as events:
        events.write(json.dumps(record) + '\n')


def pytest_deselected(items):
    if EVENTS in os.environ:
        for item in items:
            _event(kind='deselected', node=item.nodeid, markers=[mark.name for mark in item.iter_markers()])


def pytest_collectreport(report):
    if EVENTS in os.environ and report.failed:
        _event(kind='error', node=report.nodeid)


def pytest_runtest_logreport(report):
    if EVENTS in os.environ and (report.when == 'call' or not report.passed):
        reason = report.longrepr[2] if report.skipped and isinstance(report.longrepr, tuple) else ''
        _event(kind='report', node=report.nodeid, when=report.when, outcome=report.outcome, reason=reason)


if __name__ == '__main__':
    main()
