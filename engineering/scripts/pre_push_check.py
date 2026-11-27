"""Run the light pre-push check on the current commit and write its run record.

Usage (from the repository root, with the `.venv-path` interpreter):

    python -m engineering.scripts.pre_push_check [--base origin/main] [--head HEAD]

The check selects work from the paths that changed between the selection base
(the merge base of --base and --head) and --head. --head must be the clean,
checked-out commit. The check runs only light work: check_docs.py, the lock
check, pip check, ruff, check_types for darwin and win32, the import audit with
its cycle check, and the verified-light nodes of the changed test files and of
the mapped consumers. Other selected nodes stay "pending heavy". Changes that
only CI can verify stay "CI pending". The run record goes to
.cache/pre-push/<head>.txt. The Git pre-push hook calls this module with --hook.
"""
import argparse
from fnmatch import fnmatch
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys
import tempfile
import time

import pytest

from engineering.scripts.ci_scope import select_scope

ROOT = Path(__file__).resolve().parents[2]
RECORDS = ROOT / '.cache/pre-push'
HAZARDS = ROOT / 'docs/agent-hazards.md'
LOCKS = ('engineering/requirements/base.txt',
         'engineering/requirements/bo-windows.txt' if sys.platform == 'win32'
         else 'engineering/requirements/bo-macos.txt')
EVENTS = 'TM1_PRE_PUSH_EVENTS'
END = 'end of record'

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
    ((UI + 'main_window.py', UI + 'workbench.py', UI + 'mixins/*.py', UI + 'panel_vis_3d.py',
      UI + 'plot_3d_results.py', UI + 'volume_*.py', UI + 'vis3d_*.py'),
     (CLOSE,)),
)
# Verified-light test files (checked like the consumer nodes). Only these files and the
# consumer nodes run. Every other selected node is "pending heavy".
LIGHT_FILES = (
    'tests/python/architecture/test_three_module_imports.py',
    'tests/python/engineering_tm1/test_ci_scope.py',
    'tests/python/engineering_tm1/test_check_docs.py',
)
VERIFIED = LIGHT_FILES + tuple(node for _, nodes in CONSUMERS for node in nodes)
HEAVY_DIRECTORIES = ('tests/python/native/', 'tests/python/integration_tm1/')
SHARD_LISTS = r'tests/python/(?:native/)?_ci_[^/]*\.txt'
SHARD_JOB = 'tests (...) step "Require complete coverage and platform reports"'
_ABSOLUTE = re.compile(r'(?<![\w.])(?:[A-Za-z]:)?[\\/][^\s\'":,)]*')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def changed_paths(base, head):
    # No rename detection: a rename gives the old and the new name, as in ci_scope.py.
    output = git('diff', '--name-only', '--no-renames', '-z', base, head, '--')
    return sorted(path for path in output.split('\0') if path)


def is_test_file(path):
    name = path.rsplit('/', 1)[-1]
    return path.startswith('tests/python/') and name.startswith('test_') and name.endswith('.py')


def matches(node, prefix):
    return node == prefix or node.startswith((prefix + '::', prefix + '['))


def select(paths, exists):
    """Return the pytest targets, the pending-heavy items, and the CI-pending items."""
    files, nodes, heavy, ci = [], [], [], []
    for path in paths:
        if re.fullmatch(SHARD_LISTS, path):
            # A removed or renamed shard list also needs the CI coverage check.
            ci.append((path, f'shard coverage needs CI reports; closed by {SHARD_JOB}'))
        elif not exists(path) or not is_test_file(path):
            continue
        elif path.startswith(HEAVY_DIRECTORIES):
            heavy.append((path, 'native or integration test directory'))
        else:
            files.append(path)
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


def public(text):
    """Remove local absolute paths from a diagnostic."""
    return _ABSOLUTE.sub('<local path>', text.replace(str(ROOT) + os.sep, ''))


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

    def __call__(self, *args, accept=(0,)):
        start = time.monotonic()
        code = subprocess.run([self.python, *args], cwd=ROOT, env=self.env).returncode
        self.commands.append((code in accept, round(time.monotonic() - start, 1), shlex.join(['python', *args])))
        return code in accept


def run_tests(run, files, nodes):
    """Run the verified-light nodes of the targets once. Return one result for each node."""
    targets = files + nodes
    with tempfile.TemporaryDirectory(prefix='tm1-pre-push-') as directory:
        events = Path(directory) / 'events.jsonl'
        run.env[EVENTS] = str(events)
        # Exit code 5: every collected node was deselected (all pending heavy). Missing targets fail below.
        run('-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-p', 'engineering.scripts.pre_push_check',
            '-m', 'not slow and not heavy', *targets, accept=(0, 5))
        del run.env[EVENTS]
        records = [json.loads(line) for line in events.read_text(encoding='utf-8').splitlines()] \
            if events.exists() else []
    results = {}
    for record in records:
        node, kind = record['node'], record['kind']
        if kind == 'deselected':
            results[node] = ('pending heavy', record['reason'])
        elif kind == 'error':
            results[node] = ('failed', 'collection error')
        elif record['outcome'] == 'failed':
            results[node] = ('failed', record['when'])
        elif record['outcome'] == 'skipped' and results.get(node, ('',))[0] != 'failed':
            results[node] = ('skipped', public(record['reason']))
        elif node not in results:
            results[node] = ('passed', '')
    for target in targets:
        if not any(matches(node, target) for node in results):
            results[target] = ('not collected', 'no test matches this node ID')
    return results


def check(base_ref, head_ref='HEAD'):
    head = git('rev-parse', head_ref)
    if head != git('rev-parse', 'HEAD') or git('status', '--porcelain'):
        sys.exit(f'pre-push check: check out {head_ref} in a clean worktree first '
                 '(no uncommitted or untracked changes).')
    base = git('merge-base', base_ref, head)
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
        # AGENTS.md section 3: a failed environment check stops the dependent work.
        if lock and run('-m', 'pip', 'check'):
            exists = set(git('ls-files').splitlines()).__contains__
            changed_python = [path for path in paths if path.endswith('.py') and exists(path)]
            if changed_python:
                run('-m', 'ruff', 'check', *changed_python)
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
                missing = tree_paths((ROOT / path).read_text(encoding='utf-8')) if exists(path) else []
                results[path] = ('failed', f'missing paths: {missing}') if missing else ('CI pending', reason)
    counts = {}
    for result, _ in results.values():
        counts[result] = counts.get(result, 0) + 1
    passed = (all(ok for ok, _, _ in run.commands)
              and not {'failed', 'skipped', 'not collected'} & set(counts))
    seconds = round(time.monotonic() - start)
    summary = (f'Pre-push light check: {"pass" if passed else "FAIL"} at {head[:12]} '
               f'(selection base {base[:12]}, tier {tier}); '
               + (', '.join(f'{n} {result}' for result, n in sorted(counts.items())) or 'no test nodes')
               + f'; {seconds} s')
    version = subprocess.check_output([python, '-c', 'import platform; print(platform.python_version())'],
                                      text=True).strip()
    lines = [
        'TM1 pre-push light check (engineering/scripts/pre_push_check.py)',
        f'base ref: {base_ref}', f'selection base: {base}', f'head: {head}', 'tree: clean',
        f'platform: {sys.platform} {platform.machine()}', f'python: {version}', f'lock: {lock}',
        'native library variables: ' + (', '.join(sorted(k for k in os.environ if re.fullmatch(r'TPMSHX_\w*LIBRARY', k)))
                                        or 'none (package library directory)'),
        f'tier: {tier}', f'verdict: {"pass" if passed else "fail"}', f'summary: {summary}', '', 'commands:',
        *[f'  {"passed" if ok else "failed"}\t{seconds_} s\t{text}' for ok, seconds_, text in run.commands],
        '', 'nodes:',
        *[f'  {result}\t{node}' + (f'\t{reason}' if reason else '') for node, (result, reason) in sorted(results.items())],
        '', 'changed modules without a mapped consumer (trace their importers):', *[f'  {path}' for path in unmapped],
        '', END,
    ]
    RECORDS.mkdir(parents=True, exist_ok=True)
    # Write a complete record in one file replacement.
    partial = RECORDS / f'{head}.txt.partial'
    partial.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    os.replace(partial, RECORDS / f'{head}.txt')
    rows = hazard_rows(paths)
    print('\n'.join(lines[lines.index('commands:'):lines.index('nodes:')]))
    print('nodes other than passed:', *[f'  {result}\t{node}\t{reason}' for node, (result, reason)
                                        in sorted(results.items()) if result != 'passed'], sep='\n')
    print('\n'.join(lines[lines.index('changed modules without a mapped consumer (trace their importers):'):-2]))
    if rows:
        print('\nOpen hazards for the changed paths (docs/agent-hazards.md):', *rows, sep='\n')
    print(f'\n{summary}\nRun record: .cache/pre-push/{head}.txt')
    return passed


def record_matches(head, base):
    """Accept only a complete, passing record for this head and selection base."""
    record = RECORDS / f'{head}.txt'
    if not record.exists():
        return False
    lines = record.read_text(encoding='utf-8').splitlines()
    if lines[-1:] != [END] or 'commands:' not in lines or 'nodes:' not in lines:
        return False
    fields = dict(line.split(': ', 1) for line in lines[1:lines.index('')])
    commands = lines[lines.index('commands:') + 1:lines.index('nodes:') - 1]
    nodes = lines[lines.index('nodes:') + 1:lines.index('changed modules without a mapped consumer '
                                                        '(trace their importers):') - 1]
    return (fields.get('head') == head and fields.get('selection base') == base
            and fields.get('tree') == 'clean' and fields.get('verdict') == 'pass'
            and all(line.startswith('  passed\t') for line in commands)
            and all(line.split('\t')[0].strip() in {'passed', 'pending heavy', 'CI pending'} for line in nodes))


def hook():
    """Check each pushed branch. Git gives '<local ref> <local sha> <remote ref> <remote sha>' lines."""
    for line in sys.stdin.read().splitlines():
        _, local_sha, remote_ref = line.split()[:3]
        # Classify by the destination ref: tags are not checked; an all-zero source SHA is a deletion.
        if not remote_ref.startswith('refs/heads/') or not local_sha.strip('0'):
            continue
        base = git('merge-base', 'origin/main', local_sha)
        if record_matches(local_sha, base):
            print(f'pre-push: run record for {local_sha[:12]} passed.')
            continue
        if git('rev-parse', 'HEAD') != local_sha or git('status', '--porcelain'):
            sys.exit(f'pre-push: no passing run record for {remote_ref} at {local_sha[:12]}. '
                     'In a clean worktree at that commit, run: '
                     'python -m engineering.scripts.pre_push_check')
        if not check('origin/main'):
            sys.exit('pre-push: the light check failed. See the run record above.')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base', default='origin/main', help='base ref; the selection base is its merge base with --head')
    parser.add_argument('--head', default='HEAD', help='the commit to check; it must be the clean, checked-out commit')
    parser.add_argument('--hook', action='store_true', help='read the refs that Git gives to the pre-push hook')
    args = parser.parse_args()
    if args.hook:
        hook()
    elif not check(args.base, args.head):
        sys.exit(1)


# pytest plugin hooks: the check loads this module with -p and reads the events.
def _event(**record):
    with open(os.environ[EVENTS], 'a', encoding='utf-8') as events:
        events.write(json.dumps(record) + '\n')


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    if EVENTS in os.environ:
        other = [item for item in items if not any(matches(item.nodeid, node) for node in VERIFIED)]
        if other:
            items[:] = [item for item in items if item not in other]
            for item in other:
                _event(kind='deselected', node=item.nodeid, reason='not on the verified-light list')
            config.hook.pytest_deselected(items=other)


def pytest_deselected(items):
    if EVENTS in os.environ:
        for item in items:
            marks = {mark.name for mark in item.iter_markers()}
            if marks & {'slow', 'heavy'}:
                _event(kind='deselected', node=item.nodeid,
                       reason='slow marker (real solve)' if 'slow' in marks else 'heavy manifest')


def pytest_collectreport(report):
    if EVENTS in os.environ and report.failed:
        _event(kind='error', node=report.nodeid)


def pytest_runtest_logreport(report):
    if EVENTS in os.environ and (report.when == 'call' or not report.passed):
        reason = report.longrepr[2] if report.skipped and isinstance(report.longrepr, tuple) else ''
        _event(kind='report', node=report.nodeid, when=report.when, outcome=report.outcome, reason=reason)


if __name__ == '__main__':
    main()
