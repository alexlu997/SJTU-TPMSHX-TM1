"""Exercise opt-in collection hooks in fresh pytest/xdist processes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_CHECKER = _ROOT / 'scripts' / 'check_ci_shards.py'


@pytest.fixture(scope='module')
def suite(tmp_path_factory):
    root = tmp_path_factory.mktemp('ci-shard-suite')
    shutil.copyfile(Path(__file__).with_name('ci_shard.py'), root / 'ci_shard.py')
    (root / '_ci_shard0.txt').write_text('test_packed.py\n', encoding='utf-8')
    (root / 'pytest.ini').write_text(
        '[pytest]\naddopts = --strict-markers\nmarkers =\n    heavy\n    slow\n', encoding='utf-8')
    # Use the project's existing heavy-marker hook, pointed at a tiny manifest.
    (root / 'conftest.py').write_text(
        'from pathlib import Path\n'
        'import sjtu_tpmshx.tests.conftest as project\n'
        'project._FAST_TIER_MANIFEST = Path(__file__).with_name("_fast_tier_manifest.txt")\n'
        'pytest_collection_modifyitems = project.pytest_collection_modifyitems\n', encoding='utf-8')
    (root / '_fast_tier_manifest.txt').write_text('test_packed.py::test_heavy\n', encoding='utf-8')
    (root / 'test_packed.py').write_text(
        'import pytest\n'
        '@pytest.mark.parametrize("value", [1, 2])\n'
        'def test_keep(value): assert value > 0\n'
        'def test_heavy(): assert False\n'
        '@pytest.mark.slow\n'
        'def test_slow(): assert False\n'
        'def test_keyword_filtered(): assert False\n', encoding='utf-8')
    (root / 'test_rest.py').write_text('def test_keep_rest(): pass\n', encoding='utf-8')
    (root / 'test_new.py').write_text('def test_keep_new(): pass\n', encoding='utf-8')
    return root


def run_pytest(root, *options, workers=2):
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
               PYTHONPATH=os.pathsep.join([str(root), str(_ROOT), os.environ.get('PYTHONPATH', '')]))
    return subprocess.run(
        [sys.executable, '-m', 'pytest', '-p', 'xdist.plugin', '-p', 'ci_shard',
         '-c', str(root / 'pytest.ini'),
         '-n', str(workers), '--dist=loadscope', '-q', '-m', 'not heavy and not slow',
         '-k', 'keep or heavy or slow', *options], cwd=root, env=env,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45)


def run_checker(*shards, baseline=None, serial=False):
    args = [sys.executable, '-S', str(_CHECKER), *map(str, shards)]
    if baseline is not None:
        args += ['--baseline', str(baseline)]
    if serial:
        args += ['--serial']
    return subprocess.run(args, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=10)


@pytest.fixture(scope='module')
def manifests(suite):
    directories = {label: suite / label for label in ('baseline', 'zero', 'one')}
    for label, shard in (('baseline', None), ('zero', 0), ('one', 1)):
        options = ['--ci-manifest', str(directories[label])]
        if shard is not None:
            options += [f'--ci-shard={shard}']
        result = run_pytest(suite, *options)
        assert result.returncode == 0, result.stdout
    return directories


def test_filters_module_partition_new_files_and_baseline(manifests):
    expected = {'test_packed.py::test_keep[1]', 'test_packed.py::test_keep[2]',
                'test_rest.py::test_keep_rest', 'test_new.py::test_keep_new'}
    for label in ('zero', 'one', 'baseline'):
        records = [json.loads((manifests[label] / f'gw{i}.json').read_text()) for i in (0, 1)]
        assert records[0]['full_nodeids'] == records[1]['full_nodeids']
        assert set(records[0]['full_nodeids']) == expected
        selected = set(records[0]['selected_nodeids'])
        if label == 'zero':
            assert selected == {n for n in expected if n.startswith('test_packed.py::')}
        elif label == 'one':
            assert selected == {n for n in expected if not n.startswith('test_packed.py::')}
        else:
            assert selected == expected
    checked = run_checker(manifests['zero'], manifests['one'], baseline=manifests['baseline'])
    assert checked.returncode == 0, checked.stdout


def test_serial_shards_with_custom_modules(suite, tmp_path):
    modules = tmp_path / 'native-modules.txt'
    modules.write_text('test_rest.py\n', encoding='utf-8')
    directories = {label: tmp_path / label for label in ('baseline', 'zero', 'one')}
    for label, shard in (('baseline', None), ('zero', 0), ('one', 1)):
        options = ['--ci-manifest', str(directories[label]), '--ci-shard-modules', str(modules)]
        if shard is not None:
            options += [f'--ci-shard={shard}']
        result = run_pytest(suite, *options, workers=0)
        assert result.returncode == 0, result.stdout
    selected = json.loads((directories['zero'] / 'controller.json').read_text())
    assert selected['selected_nodeids'] == ['test_rest.py::test_keep_rest']
    checked = run_checker(directories['zero'], directories['one'], baseline=directories['baseline'], serial=True)
    assert checked.returncode == 0, checked.stdout
    assert run_checker(directories['zero'], directories['one']).returncode != 0
    path = directories['one'] / 'controller.json'
    record = json.loads(path.read_text())
    record['exitstatus'] = 1
    path.write_text(json.dumps(record), encoding='utf-8')
    assert run_checker(directories['zero'], directories['one'], serial=True).returncode != 0
    record['exitstatus'] = 0
    record['selected_nodeids'].pop()
    path.write_text(json.dumps(record), encoding='utf-8')
    assert run_checker(directories['zero'], directories['one'], serial=True).returncode != 0


def test_three_shards_split_exact_parameters_and_keep_new_tests(suite, tmp_path):
    groups = [tmp_path / 'group0.txt', tmp_path / 'group1.txt']
    groups[0].write_text('test_packed.py::test_keep[1]\n', encoding='utf-8')
    groups[1].write_text('test_rest.py\ntest_packed.py::test_keep[2]\n', encoding='utf-8')
    directories = [tmp_path / f'shard{i}' for i in range(3)]
    for shard, directory in enumerate(directories):
        result = run_pytest(suite, f'--ci-shard={shard}', '--ci-manifest', str(directory),
                            *[f'--ci-shard-modules={path}' for path in groups], workers=0)
        assert result.returncode == 0, result.stdout
    expected = [{'test_packed.py::test_keep[1]'},
                {'test_packed.py::test_keep[2]', 'test_rest.py::test_keep_rest'},
                {'test_new.py::test_keep_new'}]
    for directory, nodes in zip(directories, expected):
        record = json.loads((directory / 'controller.json').read_text())
        assert set(record['selected_nodeids']) == nodes
    checked = run_checker(*directories, serial=True)
    assert checked.returncode == 0, checked.stdout
    assert run_checker(*directories[:2], serial=True).returncode != 0
    assert run_checker(directories[0], directories[2], serial=True).returncode != 0


def test_overlapping_groups_are_rejected(suite, tmp_path):
    group = tmp_path / 'overlap.txt'
    group.write_text('test_packed.py::test_keep[1]\n', encoding='utf-8')
    result = run_pytest(suite, '--ci-shard=0', '--ci-manifest', str(tmp_path / 'manifest'),
                        f'--ci-shard-modules={suite / "_ci_shard0.txt"}',
                        f'--ci-shard-modules={group}', workers=0)
    assert result.returncode != 0 and 'belongs to multiple shards' in result.stdout


@pytest.mark.parametrize('shard', [-1, 2])
def test_shard_outside_configured_groups_is_rejected(suite, tmp_path, shard):
    result = run_pytest(suite, f'--ci-shard={shard}', '--ci-manifest', str(tmp_path), workers=0)
    assert result.returncode != 0 and '--ci-shard must be between 0 and 1' in result.stdout


@pytest.mark.parametrize('damage', ['missing', 'worker_disagreement', 'overlap', 'incomplete',
                                   'different_full', 'empty', 'collection_error', 'test_failure'])
def test_gate_rejects_incomplete_or_invalid_records(manifests, tmp_path, damage):
    zero, one = tmp_path / 'zero', tmp_path / 'one'
    shutil.copytree(manifests['zero'], zero)
    shutil.copytree(manifests['one'], one)
    if damage == 'missing':
        (zero / 'gw1.json').unlink()
    else:
        for worker in ('gw0', 'gw1'):
            path = one / f'{worker}.json'
            record = json.loads(path.read_text())
            if damage == 'worker_disagreement' and worker == 'gw0':
                continue
            if damage in ('worker_disagreement', 'incomplete'):
                record['selected_nodeids'].pop()
            elif damage == 'overlap':
                record['selected_nodeids'].append('test_packed.py::test_keep[1]')
            elif damage == 'different_full':
                record['full_nodeids'].append('test_extra.py::test_keep')
            elif damage == 'empty':
                record['selected_nodeids'] = []
            elif damage == 'collection_error':
                record['testsfailed'] = 1
            elif damage == 'test_failure':
                record['exitstatus'] = 1
            path.write_text(json.dumps(record), encoding='utf-8')
    assert run_checker(zero, one).returncode != 0


@pytest.mark.parametrize('failure', ['missing_option', 'empty', 'collection_error'])
def test_real_pytest_failure_cannot_pass_manifest_gate(suite, manifests, tmp_path, failure):
    isolated = tmp_path / 'suite'
    shutil.copytree(suite, isolated)
    output = tmp_path / 'manifest'
    args = ['--ci-shard=0']
    if failure != 'missing_option':
        args += ['--ci-manifest', str(output)]
    if failure == 'empty':
        (isolated / '_ci_shard0.txt').write_text('nonexistent.py\n', encoding='utf-8')
    if failure == 'collection_error':
        (isolated / 'test_broken.py').write_text('raise RuntimeError("collection failed")\n', encoding='utf-8')
    result = run_pytest(isolated, *args)
    assert result.returncode != 0, result.stdout
    assert run_checker(output, manifests['one']).returncode != 0
