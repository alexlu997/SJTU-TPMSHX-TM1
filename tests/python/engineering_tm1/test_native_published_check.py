"""Compare the selected published images with the export manifests (A2-2)."""
import json
import sys

import pytest

from engineering.scripts import build_native_dependencies as native

MANIFESTS = {
    'solver': ('solver/solver.exports', ['_tpmshx_solver_abi_version_v1', '_tpmshx_superlu_solve_v1']),
    'geometry': ('geometry/geometry.exports', ['_tpmshx_geometry_abi_version_v1', '_tpmshx_field_abi_version_v1']),
    'preparation': ('preprocess/preparation.exports', ['_tpmshx_preparation_abi_version_v1']),
    'result': ('postprocess/result.exports', ['_tpmshx_result_abi_version_v1']),
}


def exported_names(host, kind):
    return [name[1:] for name in MANIFESTS[kind][1]
            if not (host == 'windows-x64' and kind == 'solver' and name.startswith('_tpmshx_superlu_'))]


def publish_fixture(tmp_path, monkeypatch, host, *, exports=None, record=None, absent=()):
    """Write small manifests and published files; return a fake tool runner."""
    root = tmp_path / 'project'
    for path, symbols in MANIFESTS.values():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text('\n'.join(symbols) + '\n')
    monkeypatch.setattr(native, 'ROOT', root)
    directory = tmp_path / 'published'
    directory.mkdir()
    for kind, metadata_name in native.PUBLISHED_LIBRARIES:
        if kind not in absent:
            (directory / native.shared_library_name(host, kind)).write_bytes(b'image placeholder')
        (directory / metadata_name).write_text(json.dumps(record or {
            'component': kind, 'source_commit': 'a' * 40, 'source_changes': []}))
    exports = exports or {}
    commands = []

    def symbols(command):
        name = next(kind for kind in MANIFESTS if f'tpmshx_{kind}_shared' in str(command[-1]))
        return exports.get(name, exported_names(host, name))

    def run(command, log):
        commands.append([str(value) for value in command])
        if command[:2] == ['nm', '-gU']:
            return ''.join(f'0000000000000100 T _{symbol}\n' for symbol in symbols(command))
        if command[:2] == ['nm', '-gu']:
            return 'U _malloc\n'
        if command[0] == 'otool':
            return ('library:\n\t@rpath/library (compatibility version 0.0.0)\n'
                    '\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n')
        if '/EXPORTS' in command:
            return ''.join(f'          {index + 1}    {index:X} 00000100 {symbol}\n'
                           for index, symbol in enumerate(symbols(command)))
        assert '/DEPENDENTS' in command
        return 'Dump of file image.dll\n\n    KERNEL32.dll\n    VCRUNTIME140.dll\n'

    monkeypatch.setattr(native, 'run', run)
    return directory, commands


@pytest.mark.parametrize('host', ['macos-arm64', 'windows-x64'])
def test_matching_published_images_pass_and_report_the_build_record(tmp_path, monkeypatch, capsys, host):
    directory, commands = publish_fixture(tmp_path, monkeypatch, host)
    native.verify_published(directory, host, 'all', tmp_path / 'check.log')
    output = capsys.readouterr().out
    assert f'Published directory: {directory}' in output
    assert output.count(f'source_commit={"a" * 40}, source_changes=0') == 4
    assert output.count('exports: agree with the manifest') == 4
    assert 'WARNING' not in output
    assert f'PASS: {host} published images' in output
    inspected = {command[-1] for command in commands}
    assert inspected == {str(directory / native.shared_library_name(host, kind))
                         for kind in MANIFESTS}


@pytest.mark.parametrize('host', ['macos-arm64', 'windows-x64'])
@pytest.mark.parametrize('kind,extra,missing', [
    ('solver', 'tpmshx_solve_full_2d_v6', 'tpmshx_solver_abi_version_v1'),
    ('geometry', 'tpmshx_geometry_probe_v1', 'tpmshx_field_abi_version_v1'),
])
@pytest.mark.parametrize('fault', ['extra', 'missing'])
def test_an_extra_or_missing_export_fails(tmp_path, monkeypatch, capsys, host, kind, extra, missing, fault):
    symbols = exported_names(host, kind)
    if fault == 'extra':
        symbols.append(extra)
    else:
        symbols.remove(missing)
    directory, _ = publish_fixture(tmp_path, monkeypatch, host, exports={kind: symbols})
    with pytest.raises(RuntimeError, match=f'check failed for: {kind}$'):
        native.verify_published(directory, host, 'all', tmp_path / 'check.log')
    output = capsys.readouterr().out
    expected = f"extra=['_{extra}']" if fault == 'extra' else f"missing=['_{missing}']"
    assert expected in output
    # The check continues and reports the other images.
    assert output.count('exports: agree with the manifest') == 3


def test_windows_solver_keeps_the_superlu_hook_exception(tmp_path, monkeypatch):
    # Windows never exported the macOS SuperLU hooks; an image with them has extra exports.
    hooks = ['tpmshx_solver_abi_version_v1', 'tpmshx_superlu_solve_v1']
    directory, _ = publish_fixture(tmp_path, monkeypatch, 'windows-x64', exports={'solver': hooks})
    with pytest.raises(RuntimeError, match='check failed for: solver$'):
        native.verify_published(directory, 'windows-x64', 'all', tmp_path / 'check.log')


def test_a_dirty_build_from_another_commit_is_reported_without_failure(tmp_path, monkeypatch, capsys):
    record = {'source_commit': 'b' * 40, 'source_changes': [' M solver/solver.cpp', ' M solver/a.cpp']}
    directory, _ = publish_fixture(tmp_path, monkeypatch, 'macos-arm64', record=record)
    native.verify_published(directory, 'macos-arm64', 'all', tmp_path / 'check.log')
    output = capsys.readouterr().out
    assert output.count(f'source_commit={"b" * 40}, source_changes=2') == 4
    assert output.count('WARNING: dirty build; the source checkout had 2 tracked changes') == 4
    assert 'PASS:' in output


def test_a_missing_image_fails_and_one_component_checks_only_that_image(tmp_path, monkeypatch, capsys):
    directory, commands = publish_fixture(tmp_path, monkeypatch, 'macos-arm64', absent=('preparation',))
    with pytest.raises(RuntimeError, match='check failed for: preparation$'):
        native.verify_published(directory, 'macos-arm64', 'all', tmp_path / 'check.log')
    assert 'the published image is missing' in capsys.readouterr().out
    commands.clear()
    native.verify_published(directory, 'macos-arm64', 'result', tmp_path / 'check.log')
    assert {command[-1] for command in commands} == {
        str(directory / native.shared_library_name('macos-arm64', 'result'))}


def test_command_selects_the_host_directory_by_default(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(native, 'ROOT', tmp_path)
    monkeypatch.setattr(native, 'configured_python', lambda: tmp_path / 'python')
    monkeypatch.setattr(native, 'platform_name', lambda: 'macos-arm64')
    monkeypatch.setattr(native, 'verify_published', lambda *args: calls.append(args))
    monkeypatch.setattr(sys, 'argv', ['build_native_dependencies.py', 'verify-published'])
    native.main()
    selected = tmp_path / 'other'
    monkeypatch.setattr(sys, 'argv', ['build_native_dependencies.py', 'verify-published', '--directory', str(selected)])
    native.main()
    assert [call[0] for call in calls] == [
        (tmp_path / 'native/lib/macos-arm64').resolve(), selected.resolve()]
    assert calls[0][1:3] == ('macos-arm64', 'all')
    monkeypatch.setattr(sys, 'argv', ['build_native_dependencies.py', 'verify', '--directory', str(selected)])
    with pytest.raises(SystemExit):
        native.main()


def test_linux_command_checks_only_the_result_image(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(native, 'ROOT', tmp_path)
    monkeypatch.setattr(native, 'configured_python', lambda: tmp_path / 'python')
    monkeypatch.setattr(native, 'platform_name', lambda: 'linux-x86_64')
    monkeypatch.setattr(native, 'verify_published', lambda *args: calls.append(args))
    monkeypatch.setattr(sys, 'argv', ['build_native_dependencies.py', 'verify-published', '--component', 'result'])
    native.main()
    assert calls[0][1:3] == ('linux-x86_64', 'result')
    monkeypatch.setattr(sys, 'argv', ['build_native_dependencies.py', 'verify-published'])
    with pytest.raises(RuntimeError, match='Linux x86_64 supports only --component result'):
        native.main()


@pytest.mark.parametrize('content,report', [
    (None, 'WARNING: build record missing (build.json)'),
    ('{"source_commit": "' + 'c' * 40 + '"}', f'source_commit={"c" * 40}, source_changes=unknown'),
    ('{not json', 'WARNING: build record unreadable (build.json: '),
    ('[]', 'WARNING: build record unreadable (build.json: not a JSON object)'),
    ('{"source_changes": "M a.cpp"}', 'WARNING: build record unreadable (build.json: source_changes is not a list)'),
])
def test_a_missing_or_incomplete_build_record_is_reported_without_failure(tmp_path, monkeypatch, capsys,
                                                                         content, report):
    directory, _ = publish_fixture(tmp_path, monkeypatch, 'macos-arm64')
    record = directory / 'build.json'
    if content is None:
        record.unlink()
    else:
        record.write_text(content)
    native.verify_published(directory, 'macos-arm64', 'all', tmp_path / 'check.log')
    output = capsys.readouterr().out
    assert report in output
    assert output.count('exports: agree with the manifest') == 4
    assert 'PASS:' in output


@pytest.mark.parametrize('component', ['coolprop', 'pilot'])
def test_command_rejects_a_component_without_a_published_image(tmp_path, monkeypatch, component):
    monkeypatch.setattr(native, 'ROOT', tmp_path)
    monkeypatch.setattr(native, 'verify_published', lambda *args: pytest.fail('check started'))
    monkeypatch.setattr(sys, 'argv', ['build_native_dependencies.py', 'verify-published', '--component', component])
    with pytest.raises(SystemExit):
        native.main()
