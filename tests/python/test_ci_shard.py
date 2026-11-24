"""Exercise opt-in collection hooks in fresh pytest/xdist processes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree

import pytest

from engineering.scripts import check_ci_shards
from engineering.scripts.check_ci_shards import check, check_report
from tests.python import ci_shard

_ROOT = Path(__file__).resolve().parents[2]
_CHECKER = _ROOT / 'engineering' / 'scripts' / 'check_ci_shards.py'


@pytest.fixture(scope='module')
def suite(tmp_path_factory):
    root = tmp_path_factory.mktemp('ci-shard-suite')
    shutil.copyfile(Path(__file__).with_name('ci_shard.py'), root / 'ci_shard.py')
    (root / '_ci_shard0.txt').write_text('test_packed.py\n', encoding='utf-8')
    (root / 'pyproject.toml').write_text(
        '[tool.pytest.ini_options]\naddopts = ["--strict-markers"]\nmarkers = ["heavy", "slow"]\n', encoding='utf-8')
    # Use the project's existing heavy-marker hook, pointed at a tiny manifest.
    (root / 'conftest.py').write_text(
        'from pathlib import Path\n'
        'import tests.python.conftest as project\n'
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


def run_pytest(root, *options, workers=2, distribution='loadscope'):
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
               PYTHONPATH=os.pathsep.join([str(root), str(_ROOT), os.environ.get('PYTHONPATH', '')]))
    return subprocess.run(
        [sys.executable, '-m', 'pytest', '-p', 'xdist.plugin', '-p', 'ci_shard',
         '-c', str(root / 'pyproject.toml'),
         '-n', str(workers), '--dist', distribution, '-q', '-m', 'not heavy and not slow',
         '-k', 'keep or heavy or slow', *options], cwd=root, env=env,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45)


def checker_arguments(*shards, baseline=None, serial=False, covered_by=()):
    args = [*map(str, shards)]
    if baseline is not None:
        args += ['--baseline', str(baseline)]
    if serial:
        args += ['--serial']
    if covered_by:
        args += ['--covered-by', *map(str, covered_by)]
    return args


def checker_status(*shards, **options):
    """Return the exit status of the checker command line, run in this process."""
    with patch.object(sys, 'argv', ['check_ci_shards', *checker_arguments(*shards, **options)]):
        try:
            check_ci_shards.main()
        except SystemExit as error:
            return error.code
    return 0


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
    # The real command line runs without site packages because the checker uses only the standard library.
    checked = subprocess.run([sys.executable, '-S', str(_CHECKER), *checker_arguments(
        manifests['zero'], manifests['one'], baseline=manifests['baseline'])],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
    assert checked.returncode == 0, checked.stdout


def test_serial_shards_split_exact_parameters_and_keep_new_tests(suite, tmp_path):
    groups = [tmp_path / 'group0.txt', tmp_path / 'group1.txt']
    groups[0].write_text('test_packed.py::test_keep[1]\n', encoding='utf-8')
    groups[1].write_text('test_rest.py\ntest_packed.py::test_keep[2]\n', encoding='utf-8')
    baseline = tmp_path / 'baseline'
    directories = [tmp_path / f'shard{i}' for i in range(3)]
    for shard, directory in [(None, baseline), *enumerate(directories)]:
        options = [] if shard is None else [f'--ci-shard={shard}']
        result = run_pytest(suite, *options, '--ci-manifest', str(directory),
                            *[f'--ci-shard-modules={path}' for path in groups], workers=0)
        assert result.returncode == 0, result.stdout
    expected = [{'test_packed.py::test_keep[1]'},
                {'test_packed.py::test_keep[2]', 'test_rest.py::test_keep_rest'},
                {'test_new.py::test_keep_new'}]
    for directory, nodes in zip(directories, expected):
        record = json.loads((directory / 'controller.json').read_text())
        assert set(record['selected_nodeids']) == nodes
    assert checker_status(*directories, baseline=baseline, serial=True) == 0
    assert checker_status(*directories) != 0
    assert checker_status(*directories[:2], serial=True) != 0
    assert checker_status(directories[0], directories[2], serial=True) != 0
    path = directories[2] / 'controller.json'
    record = json.loads(path.read_text())
    record['exitstatus'] = 1
    path.write_text(json.dumps(record), encoding='utf-8')
    assert checker_status(*directories, serial=True) != 0
    record['exitstatus'] = 0
    record['selected_nodeids'].pop()
    path.write_text(json.dumps(record), encoding='utf-8')
    assert checker_status(*directories, serial=True) != 0


def plugin_options(**options):
    values = dict(ci_shard=None, ci_shard_modules=None, ci_covered_modules=None, ci_manifest=None)
    values.update(options)
    return values.__getitem__


@pytest.mark.parametrize('options, message', [
    (dict(ci_shard=-1, ci_manifest='manifest'), 'between 0 and 1'),
    (dict(ci_shard=2, ci_manifest='manifest'), 'between 0 and 1'),
    (dict(ci_shard=3, ci_shard_modules=[Path('a'), Path('b')], ci_manifest='manifest'), 'between 0 and 2'),
    (dict(ci_shard=0), 'require --ci-manifest'),
    (dict(ci_covered_modules=[Path('native.txt')]), 'require --ci-manifest'),
])
def test_plugin_rejects_invalid_options(options, message):
    with pytest.raises(pytest.UsageError, match=message):
        ci_shard.pytest_configure(SimpleNamespace(getoption=plugin_options(**options)))


def test_overlapping_groups_are_rejected(tmp_path):
    groups = [tmp_path / 'group0.txt', tmp_path / 'group1.txt']
    groups[0].write_text('test_packed.py\n', encoding='utf-8')
    groups[1].write_text('test_packed.py::test_keep[1]\n', encoding='utf-8')
    item = SimpleNamespace(path=tmp_path / 'test_packed.py', nodeid='test_packed.py::test_keep[1]')
    config = SimpleNamespace(rootpath=tmp_path, getoption=plugin_options(
        ci_shard=0, ci_shard_modules=groups, ci_manifest=str(tmp_path / 'manifest')))
    hook = ci_shard.pytest_collection_modifyitems(config, [item])
    next(hook)
    with pytest.raises(pytest.UsageError, match='belongs to multiple shards'):
        hook.send(None)


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
    assert checker_status(zero, one) != 0


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
    assert checker_status(output, manifests['one']) != 0


@pytest.fixture(scope='module')
def partitioned_manifests(suite, tmp_path_factory):
    root = tmp_path_factory.mktemp('ci-partition') / 'suite'
    shutil.copytree(suite, root)
    (root / 'test_native.py').write_text(
        'import pytest\n@pytest.mark.parametrize("value", [1, 2])\n'
        'def test_keep_native(value): assert value > 0\n', encoding='utf-8')
    (root / 'test_new_native.py').write_text(
        'def test_keep_unlisted_native(): pass\n', encoding='utf-8')
    (root / 'test_stage.py').write_text(
        'def test_keep_stage(): pass\n', encoding='utf-8')
    modules = root / 'native-suite.txt'
    modules.write_text('test_native.py\n', encoding='utf-8')
    stages = root / 'stage-suite.txt'
    stages.write_text('test_stage.py\n', encoding='utf-8')
    group = root / 'native-shard0.txt'
    group.write_text('test_native.py::test_keep_native[1]\n', encoding='utf-8')
    app = [root / f'app{i}' for i in range(2)]
    native = [root / f'native{i}' for i in range(2)]
    for shard in range(2):
        result = run_pytest(root, f'--ci-shard={shard}', '--ci-manifest', str(app[shard]),
                            f'--ci-covered-modules={modules}', f'--ci-covered-modules={stages}',
                            distribution='worksteal')
        assert result.returncode == 0, result.stdout
        result = run_pytest(root, '@' + str(modules), '@' + str(stages), f'--ci-shard={shard}',
                            '--ci-manifest', str(native[shard]),
                            f'--ci-shard-modules={group}')
        assert result.returncode == 0, result.stdout
    return app, native


def test_native_partition_keeps_full_collection_and_unlisted_tests(partitioned_manifests):
    app, native = partitioned_manifests
    records = [json.loads((path / 'gw0.json').read_text()) for path in app]
    assert all(len(record['full_nodeids']) == 8 for record in records)
    selected = {node for record in records for node in record['selected_nodeids']}
    assert len(selected) == 5
    assert 'test_new_native.py::test_keep_unlisted_native' in selected
    assert not any(node.startswith('test_native.py::') for node in selected)
    assert 'test_stage.py::test_keep_stage' not in selected
    assert checker_status(*app, covered_by=native) == 0
    assert checker_status(*app) != 0


@pytest.mark.parametrize('damage', ['missing_native', 'native_failure', 'native_gap',
                                   'native_overlap', 'app_overlap', 'app_gap'])
def test_cross_group_gate_rejects_missing_or_duplicate_coverage(partitioned_manifests, tmp_path, damage):
    original_app, original_native = partitioned_manifests
    app = [tmp_path / f'app{i}' for i in range(2)]
    native = [tmp_path / f'native{i}' for i in range(2)]
    for source, target in zip(original_app + original_native, app + native):
        shutil.copytree(source, target)
    if damage == 'missing_native':
        (native[0] / 'gw1.json').unlink()
    else:
        paths = list((app[0] if damage.startswith('app') else native[0]).glob('*.json'))
        for path in paths:
            record = json.loads(path.read_text())
            if damage == 'native_failure':
                record['exitstatus'] = 1
            elif damage.endswith('gap'):
                record['selected_nodeids'].pop()
            else:
                node = 'test_native.py::test_keep_native[2]'
                record['selected_nodeids'].append(node)
            path.write_text(json.dumps(record), encoding='utf-8')
    assert checker_status(*app, covered_by=native) != 0


def test_application_tier_allows_only_the_listed_native_modules(partitioned_manifests):
    app, native = partitioned_manifests
    assert check(app, omitted_modules={'test_native.py', 'test_stage.py'}) == (8, [2, 3])
    for modules in ({'test_native.py'}, {'test_native.py::test_keep_native[1]'}, {'test_other.py'},
                    {'test_native.py', 'test_stage.py', 'test_new_native.py'}):
        with pytest.raises(ValueError):
            check(app, omitted_modules=modules)
    with pytest.raises(ValueError):
        check(app, covered_by=native, omitted_modules={'test_native.py'})


@pytest.fixture(scope='module')
def serial_report(suite, tmp_path_factory):
    root = tmp_path_factory.mktemp('ci-report-suite') / 'suite'
    shutil.copytree(suite, root)
    (root / 'test_class.py').write_text(
        'import pytest\n'
        'class TestOuter:\n'
        '    class TestInner:\n'
        '        @pytest.mark.parametrize("value", [1, 2], ids=["one::two", "a<&"])\n'
        '        def test_keep(self, value): assert value > 0\n', encoding='utf-8')
    directory = tmp_path_factory.mktemp('ci-report')
    result = run_pytest(root, '--ci-manifest', str(directory / 'bo-manifest'),
                        f'--junitxml={directory / "bo.xml"}', workers=0)
    assert result.returncode == 0, result.stdout
    return directory


def test_report_matches_class_parameters_independent_of_order(serial_report, tmp_path):
    assert check_report(serial_report, 'bo') == (6, 0)
    report = tmp_path / 'report'
    shutil.copytree(serial_report, report)
    tree = ElementTree.parse(report / 'bo.xml')
    group = next(tree.iter('testsuite'))
    group[:] = list(reversed(group))
    tree.write(report / 'bo.xml')
    assert check_report(report, 'bo') == (6, 0)


@pytest.mark.parametrize('damage', ['missing_platform', 'missing_report', 'failed_manifest',
                                   'missing_case', 'wrong_case', 'wrong_class', 'duplicate_case',
                                   'failed_case', 'skipped_case', 'all_skipped'])
def test_report_rejects_missing_failed_or_skipped_execution(serial_report, tmp_path, damage):
    directory = tmp_path / 'report'
    if damage != 'missing_platform':
        shutil.copytree(serial_report, directory)
    if damage == 'missing_report':
        (directory / 'bo.xml').unlink()
    elif damage == 'failed_manifest':
        path = directory / 'bo-manifest' / 'controller.json'
        record = json.loads(path.read_text())
        record['exitstatus'] = 1
        path.write_text(json.dumps(record), encoding='utf-8')
    elif damage not in ('missing_platform', 'missing_report'):
        path = directory / 'bo.xml'
        tree = ElementTree.parse(path)
        group = next(tree.iter('testsuite'))
        cases = list(group.iter('testcase'))
        if damage == 'missing_case':
            group.remove(cases[0])
        elif damage == 'wrong_case':
            cases[0].set('name', 'test_unrelated')
        elif damage == 'wrong_class':
            cases[0].set('classname', 'unrelated.module')
        elif damage == 'duplicate_case':
            for key in ('classname', 'name'):
                cases[0].set(key, cases[1].get(key))
        else:
            for case in cases if damage == 'all_skipped' else cases[:1]:
                ElementTree.SubElement(case, 'failure' if damage == 'failed_case' else 'skipped')
        tree.write(path)
    with pytest.raises((OSError, ValueError)):
        check_report(directory, 'bo')
    if damage == 'skipped_case':
        assert check_report(directory, 'bo', allow_skips=True) == (6, 1)
    else:
        with pytest.raises((OSError, ValueError)):
            check_report(directory, 'bo', allow_skips=True)
