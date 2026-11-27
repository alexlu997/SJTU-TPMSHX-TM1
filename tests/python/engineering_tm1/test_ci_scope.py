"""Keep unknown changes and missing jobs inside the full CI gate."""
import pytest

from engineering.scripts import ci_scope
from engineering.scripts.ci_scope import require_jobs, select_scope
from engineering.scripts.pre_push_check import CONSUMERS, select


@pytest.mark.parametrize('event,paths,expected', [
    ('push', ['README.md'], 'docs'),
    ('push', ['python/applications/gui/ui/theme.py', 'docs/desktop.md'], 'full'),
    ('workflow_dispatch', ['README.md'], 'full'),
    ('pull_request', [], 'full'),
    ('pull_request', ['README.md', 'docs/architecture.md'], 'docs'),
    ('pull_request', ['python/applications/gui/ui/theme.py', 'docs/desktop.md'], 'application'),
    ('pull_request', ['tests/python/test_ui_typography.py'], 'application'),
    ('pull_request', ['python/applications/gui/ui/assets/icons/play.svg'], 'application'),
    ('pull_request', ['python/applications/gui/ui/expr_eval.py'], 'full'),
    ('pull_request', ['python/applications/gui/ui/single_run.py'], 'full'),
    ('pull_request', ['python/applications/result_adapter.py'], 'full'),
    ('pull_request', ['docs/contracts/three_module_v1/files.md'], 'full'),
    ('pull_request', ['tests/python/fixture.md'], 'full'),
    ('pull_request', ['README.md', 'engineering/requirements/base.txt'], 'full'),
    ('pull_request', ['solver/full_3d.cpp', 'docs/old.md'], 'full'),
    ('pull_request', ['.github/workflows/ci.yml'], 'full'),
    ('pull_request', ['new-package/readme.md'], 'full'),
])
def test_scope_keeps_conservative_boundaries(event, paths, expected):
    assert select_scope(event, paths) == expected


IO_NODES = list(CONSUMERS[0][1])
CLOSE_NODE = ('tests/python/test_workbench_navigation.py::'
              'test_window_close_cleans_both_volume_plotters_and_their_popups')


@pytest.mark.parametrize('paths,deleted,expected', [
    (['python/applications/gui/ui/optimize_panel.py'], [], ([], IO_NODES, [], [])),
    # workbench.py owns close_views(), which releases both volume plotters.
    (['python/applications/gui/ui/workbench.py'], [], ([], [CLOSE_NODE], [], [])),
    # A rename gives the old name. The old name still selects its consumers.
    (['python/applications/gui/ui/main_window.py'], ['python/applications/gui/ui/main_window.py'],
     ([], [CLOSE_NODE], [], [])),
    # Mapped nodes stay required when their file also changed.
    (['python/applications/gui/ui/panel_vis_3d.py', 'tests/python/test_io_actions.py'], [],
     (['tests/python/test_io_actions.py'], IO_NODES + [CLOSE_NODE], [], [])),
    # A removed shard list still needs the CI coverage check.
    (['tests/python/native/test_cpp_quick_design.py', 'tests/python/integration_tm1/test_public_gui.py',
      'tests/python/_ci_shard0.txt', 'tests/python/native/_ci_suite.txt', 'tests/python/test_removed.py',
      'docs/architecture.md'],
     ['tests/python/test_removed.py', 'tests/python/_ci_shard0.txt'],
     ([], [], ['tests/python/native/test_cpp_quick_design.py', 'tests/python/integration_tm1/test_public_gui.py'],
      ['tests/python/_ci_shard0.txt', 'tests/python/native/_ci_suite.txt'])),
])
def test_pre_push_selects_light_consumers_and_defers_heavy_and_ci_items(paths, deleted, expected):
    files, nodes, heavy, ci = select(paths, lambda path: path not in deleted)
    assert (files, nodes, [path for path, _ in heavy], [path for path, _ in ci]) == expected


@pytest.mark.parametrize('tier', ['docs', 'application', 'full'])
@pytest.mark.parametrize('stage', ['summary', 'minimal'])
def test_gate_requires_exact_jobs_and_results(tier, stage):
    native = {'result': 'skipped' if tier == 'docs' else 'success'}
    needs = {'scope': {'result': 'success'}, 'native-macos': native}
    if stage == 'summary':
        needs['native-windows'] = native
    else:
        needs['result-build'] = native
    require_jobs(tier, needs, stage)
    for name in needs:
        missing = {key: value for key, value in needs.items() if key != name}
        with pytest.raises(ValueError):
            require_jobs(tier, missing, stage)
        for result in ('failure', 'cancelled', 'skipped', 'success'):
            if result == needs[name]['result']:
                continue
            with pytest.raises(ValueError):
                require_jobs(tier, {**needs, name: {'result': result}}, stage)
    with pytest.raises(ValueError):
        require_jobs(tier, {**needs, 'unexpected': {'result': 'success'}}, stage)


def test_gate_rejects_unknown_tier():
    with pytest.raises(ValueError):
        require_jobs('unknown', {}, 'summary')


@pytest.mark.parametrize('event', ['pull_request', 'push'])
def test_rename_from_code_to_docs_still_requires_full_ci(tmp_path, event, monkeypatch):
    from pathlib import Path
    import shutil
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[3]
    script = root / 'engineering' / 'scripts' / 'ci_scope.py'
    def git(*args):
        return subprocess.check_output(['git', '-c', 'user.name=CI Test',
                                       '-c', 'user.email=ci@example.invalid',
                                       *args], cwd=tmp_path, text=True).strip()

    git('init', '-q')
    workflows = tmp_path / '.github/workflows'
    workflows.mkdir(parents=True)
    (workflows / 'ci.yml').write_text('jobs: {}\n', encoding='utf-8')
    git('add', '.')
    git('commit', '-qm', 'Record the CI layout before the native jobs')
    previous = git('rev-parse', 'HEAD')
    shutil.copytree(root / '.github/workflows', workflows, dirs_exist_ok=True)
    (tmp_path / 'solver').mkdir()
    (tmp_path / 'solver/model.cpp').write_text('unchanged content\n', encoding='utf-8')
    for path in ('docs/native-stages.md', 'docs/native-stages.zh-CN.md'):
        assert select_scope(event, [path]) == 'full'
    git('add', '.')
    git('commit', '-qm', 'Add source')
    base = git('rev-parse', 'HEAD')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('GITHUB_REPOSITORY_ID', '10')
    origin = dict(head_branch='main', head_sha=base, repository_id=10, head_repository_id=10)
    archives = [dict(expired=False, workflow_run=dict(origin, id=i, head_sha=sha))
                for i, sha in ((2, base), (1, base), (3, previous))]
    monkeypatch.setattr(ci_scope, 'records', lambda *args: archives)
    hosts = {p: dict(image=p, python='3.13.17') for p in ci_scope.PLATFORMS}
    matching = {p: dict(hosts[p], id=p) for p in hosts}
    # During an image rollout, the most recent main build can match only one platform.
    runs = {2: {**matching, 'windows-2022': dict(image='previous', python='3.13.17')}, 1: matching}
    monkeypatch.setattr(ci_scope, 'qualified_pair', runs.__getitem__)
    restored = []

    def restore(platform, source, tools):
        restored.append(source)
        return True

    monkeypatch.setattr(ci_scope, 'restore_native', restore)
    candidates = ci_scope.native_candidates(base)
    assert candidates == [2, 1]
    assert ci_scope.restore_pair(candidates, hosts)
    assert restored == list(matching.values())
    git('mv', 'solver/model.cpp', 'README.md')
    git('commit', '-qm', 'Move source')
    result = subprocess.check_output(
        [sys.executable, '-S', str(script), 'select', '--event', event,
         '--base', base, '--head', git('rev-parse', 'HEAD')], cwd=tmp_path, text=True)
    assert result.strip() == 'full'
    assert ci_scope.native_candidates(base) == []

    git('switch', '-q', '--detach', base)
    (tmp_path / 'solver/model.cpp').write_text('changed content\n', encoding='utf-8')
    git('commit', '-qam', 'Change the source at the same path')
    assert ci_scope.native_candidates(base) == []
