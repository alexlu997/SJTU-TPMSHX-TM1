"""Independent geometry builds retain environment gates and avoid solver inputs."""
import sys

import pytest

from engineering.scripts import build_native_dependencies as native


@pytest.fixture(params=['macos-arm64', 'windows-x64'])
def geometry_build(request, tmp_path, monkeypatch):
    host = request.param
    root = tmp_path / 'project'
    cache = root / '.cache/native-deps'
    python = root / 'configured python'
    lock = root / 'engineering/requirements/selected-role.txt'
    cmake = cache / 'tools/bin' / ('cmake.exe' if host == 'windows-x64' else 'cmake')
    cmake.parent.mkdir(parents=True)
    cmake.write_bytes(b'locked tool placeholder')
    generator = 'Visual Studio 17 2022' if host == 'windows-x64' else 'Unix Makefiles'
    monkeypatch.setattr(native, 'ROOT', root)
    monkeypatch.setattr(native, 'LOCK', {'cmake': {
        'version': '4.4.4', host: {'generator': generator,
            'executable': cmake.relative_to(cache / 'tools').as_posix(),
            'url': 'https://example.invalid/locked-cmake.zip'}}})

    def forbidden(*args, **kwargs):
        pytest.fail('geometry entered a solver source or LU operation')

    for name in ('verify_sources', 'apply_lu_patch', 'verify_lu_patch', 'fetch_source'):
        monkeypatch.setattr(native, name, forbidden)
    commands = []

    def run(command, *args, **kwargs):
        commands.append(tuple(str(value) for value in command))
        return 'cmake version 4.4.4\n' if '--version' in command else ''

    monkeypatch.setattr(native, 'run', run)
    return host, root, cache, python, lock, cmake, generator, commands


def test_geometry_build_uses_role_lock_and_standalone_source(geometry_build):
    host, root, cache, python, lock, cmake, generator, commands = geometry_build
    native.build(cache, host, python, lock, 'geometry')
    assert commands[:2] == [
        (str(python), '-m', 'sjtu_tpmshx.development.runs.tools.check_locked_environment', str(lock)),
        (str(python), '-m', 'pip', 'check'),
    ]
    generated = cache / 'generated/tpmshx/model_coefficients.hpp'
    assert (str(python), '-m', 'engineering.scripts.generate_native_model_coefficients',
            '--output', str(generated)) in commands
    configure, = (command for command in commands if '-S' in command)
    assert configure[0] == str(cmake)
    assert configure[configure.index('-S') + 1] == str(root / 'sjtu_tpmshx/solvers/native/geometry')
    assert configure[configure.index('-B') + 1] == str(cache / 'build' / ('geometry-' + host))
    assert configure[configure.index('-G') + 1] == generator
    assert f'-DTPMSHX_MODEL_INCLUDE_DIR={generated.parent.parent}' in configure
    assert not any('COOLPROP' in arg or 'dependency-pilot' in arg for arg in configure)
    if host == 'windows-x64':
        assert configure[configure.index('-A') + 1] == 'x64'
    else:
        assert '-DCMAKE_OSX_ARCHITECTURES=arm64' in configure
    build, = (command for command in commands if '--build' in command)
    assert build[build.index('--build') + 1] == str(cache / 'build' / ('geometry-' + host))
    assert not (cache / 'src').exists()


@pytest.mark.parametrize('failure', ['check_locked_environment', 'pip'])
def test_failed_geometry_environment_check_stops_before_generation(geometry_build, monkeypatch, failure):
    host, _, cache, python, lock, _, _, commands = geometry_build

    def fail_check(command, *args, **kwargs):
        command = tuple(str(value) for value in command)
        commands.append(command)
        if (command[2] == 'pip' if failure == 'pip'
                else command[2].endswith('check_locked_environment')):
            raise RuntimeError('environment gate failed')
        return ''

    monkeypatch.setattr(native, 'run', fail_check)
    with pytest.raises(RuntimeError, match='environment gate failed'):
        native.build(cache, host, python, lock, 'geometry')
    assert commands and all(command[0] == str(python) and command[1] == '-m' for command in commands)
    assert not any('engineering.scripts.generate_native_model_coefficients' in command for command in commands)


def test_geometry_verify_runs_only_the_three_independent_callers(geometry_build):
    host, _, cache, _, _, cmake, _, commands = geometry_build
    native.verify(cache, host, 'geometry')
    suffix = '.exe' if host == 'windows-x64' else ''
    build = cache / 'build' / ('geometry-' + host)
    assert commands[0] == (str(cmake), '--version')
    assert set(commands[1:]) == {(str(build / (name + suffix)),) for name in (
        'geometry_c_static', 'geometry_c_shared', 'geometry_kernel_smoke')}


def test_geometry_verify_cli_checks_the_selected_lock_first(geometry_build, monkeypatch):
    host, _, cache, python, lock, _, _, commands = geometry_build
    monkeypatch.setattr(native, 'configured_python', lambda: python)
    monkeypatch.setattr(native, 'platform_name', lambda: host)
    monkeypatch.setattr(sys, 'argv', ['native-build', 'verify', '--component', 'geometry',
                                    '--cache', str(cache), '--python-lock', str(lock)])
    native.main()
    assert commands[:2] == [
        (str(python), '-m', 'sjtu_tpmshx.development.runs.tools.check_locked_environment', str(lock)),
        (str(python), '-m', 'pip', 'check'),
    ]
    assert commands[2][1:] == ('--version',)


def test_fetch_cmake_cli_selects_only_the_tool_action(geometry_build, monkeypatch):
    host, _, cache, python, _, _, _, commands = geometry_build
    selected = []
    monkeypatch.setattr(native, 'configured_python', lambda: python)
    monkeypatch.setattr(native, 'platform_name', lambda: host)
    monkeypatch.setattr(native, 'fetch_cmake', lambda directory, platform: selected.append((directory, platform)))

    def forbidden(*args, **kwargs):
        pytest.fail('fetch-cmake selected a solver or Eigen fetch')

    monkeypatch.setattr(native, 'fetch', forbidden)
    monkeypatch.setattr(native, 'fetch_eigen', forbidden)
    monkeypatch.setattr(sys, 'argv', ['native-build', 'fetch-cmake', '--cache', str(cache)])
    native.main()
    assert selected == [(cache, host)]
    assert commands == []


def test_interrupted_cmake_download_has_no_solver_source_side_effects(geometry_build, monkeypatch):
    host, _, cache, _, _, _, _, commands = geometry_build
    attempted = []

    def unavailable(url, target):
        attempted.append((url, target))
        raise OSError('tool download interrupted')

    monkeypatch.setattr(native, 'download', unavailable)
    with pytest.raises(OSError, match='tool download interrupted'):
        native.fetch_cmake(cache, host)
    assert attempted == [('https://example.invalid/locked-cmake.zip', cache / 'downloads/locked-cmake.zip')]
    assert commands == []
    assert not (cache / 'src').exists()
