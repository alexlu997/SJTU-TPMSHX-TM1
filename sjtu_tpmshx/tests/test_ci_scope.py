"""Keep unknown changes and missing jobs inside the full CI gate."""
import pytest

from scripts.ci_scope import require_jobs, select_scope


@pytest.mark.parametrize('event,paths,expected', [
    ('push', ['README.md'], 'full'),
    ('workflow_dispatch', ['README.md'], 'full'),
    ('pull_request', [], 'full'),
    ('pull_request', ['README.md', 'docs/architecture.md'], 'docs'),
    ('pull_request', ['sjtu_tpmshx/ui/theme.py', 'docs/desktop.md'], 'application'),
    ('pull_request', ['sjtu_tpmshx/tests/test_ui_typography.py'], 'application'),
    ('pull_request', ['sjtu_tpmshx/ui/assets/icons/play.svg'], 'application'),
    ('pull_request', ['sjtu_tpmshx/ui/expr_eval.py'], 'full'),
    ('pull_request', ['sjtu_tpmshx/ui/mixins/run_controller.py'], 'full'),
    ('pull_request', ['sjtu_tpmshx/controllers/module_adapter.py'], 'full'),
    ('pull_request', ['schemas/three_module_v1/files.md'], 'full'),
    ('pull_request', ['sjtu_tpmshx/tests/fixture.md'], 'full'),
    ('pull_request', ['README.md', 'requirements/base.txt'], 'full'),
    ('pull_request', ['native/src/full_3d.cpp', 'docs/old.md'], 'full'),
    ('pull_request', ['.github/workflows/ci.yml'], 'full'),
    ('pull_request', ['new-package/readme.md'], 'full'),
])
def test_scope_keeps_conservative_boundaries(event, paths, expected):
    assert select_scope(event, paths) == expected


@pytest.mark.parametrize('tier', ['docs', 'application', 'full'])
@pytest.mark.parametrize('stage', ['summary', 'minimal'])
def test_gate_requires_exact_jobs_and_results(tier, stage):
    needs = {'scope': {'result': 'success'},
             'native': {'result': 'skipped' if tier == 'docs' else 'success'}}
    if stage == 'summary':
        needs.update({'bo-tests': dict(needs['native']),
                      'minimal-postprocess': {'result': 'success'}})
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


def test_rename_from_code_to_docs_still_requires_full_ci(tmp_path):
    from pathlib import Path
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[2] / 'scripts' / 'ci_scope.py'
    def git(*args):
        return subprocess.check_output(['git', '-c', 'user.name=CI Test',
                                       '-c', 'user.email=ci@example.invalid',
                                       *args], cwd=tmp_path, text=True).strip()

    git('init', '-q')
    (tmp_path / 'model.py').write_text('unchanged content\n', encoding='utf-8')
    git('add', '.')
    git('commit', '-qm', 'Add source')
    base = git('rev-parse', 'HEAD')
    git('mv', 'model.py', 'README.md')
    git('commit', '-qm', 'Move source')
    result = subprocess.check_output(
        [sys.executable, '-S', str(script), 'select', '--event', 'pull_request',
         '--base', base, '--head', git('rev-parse', 'HEAD')], cwd=tmp_path, text=True)
    assert result.strip() == 'full'
