"""The installed launcher must preserve CLI errors and use writable caches."""
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QStandardPaths

from sjtu_tpmshx import desktop


@pytest.mark.skipif(sys.platform != 'darwin', reason='The source-folder launcher uses macOS zsh.')
def test_macos_source_launcher_without_retired_cache(tmp_path, monkeypatch):
    import shutil
    import subprocess
    from pathlib import Path

    project = tmp_path / 'source folder'
    project.mkdir()
    launcher = project / 'launch-macos.command'
    shutil.copy2(Path(__file__).resolve().parents[3] / launcher.name, launcher)
    interpreter = project / 'configured python'
    interpreter.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$MPLCONFIGDIR" "$XDG_CACHE_HOME" "$@"\n')
    interpreter.chmod(0o755)
    (project / '.venv-path').write_text(str(interpreter) + '\n')
    library = project / 'sjtu_tpmshx/solvers/native/lib/macos-arm64/libtpmshx_solver_shared.dylib'
    library.parent.mkdir(parents=True)
    library.touch()
    for component in ('geometry', 'preparation', 'result'):
        library.with_name(f'libtpmshx_{component}_shared.dylib').touch()
    monkeypatch.delenv('NUMBA_CACHE_DIR', raising=False)

    run = subprocess.run(['/bin/zsh', str(launcher)], cwd=tmp_path,
                         capture_output=True, text=True, check=False)

    assert run.returncode == 0, run.stderr
    caches = [project / '.cache' / name for name in ('matplotlib', 'xdg')]
    assert all(path.is_dir() for path in caches)
    assert run.stdout.splitlines() == [str(project), *(str(path) for path in caches),
        '-m', 'sjtu_tpmshx.main', '--backend', 'cpp', '--native-library', str(library),
        '--native-table-directory', str(project / '.cache/native-deps/tables')]


def test_caches_respect_explicit_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(QStandardPaths, 'writableLocation', lambda *_: str(tmp_path))
    for name in ('MPLCONFIGDIR', 'XDG_CACHE_HOME'):
        monkeypatch.delenv(name, raising=False)
    explicit = tmp_path / 'chosen-matplotlib'
    monkeypatch.setenv('MPLCONFIGDIR', str(explicit))
    desktop.configure_cache()
    assert explicit.is_dir()
    assert (tmp_path / 'SJTU-TPMSHX-TM1' / 'libraries').is_dir()


def test_bundled_cli_dispatch_preserves_status(monkeypatch):
    from sjtu_tpmshx.applications.cli import main as cli
    calls = []
    monkeypatch.setattr(desktop.multiprocessing, 'freeze_support', lambda: calls.append('freeze'))
    monkeypatch.setattr(desktop, 'configure_cache', lambda: calls.append('cache'))
    monkeypatch.setattr(cli, 'main', lambda args: calls.append(args) or 2)
    assert desktop.main(['--cli', 'run', 'input.json', 'output']) == 2
    assert calls == ['freeze', 'cache', ['run', 'input.json', 'output']]


def test_desktop_gui_forwards_backend_and_qt_arguments(monkeypatch):
    from sjtu_tpmshx.applications.gui import main as gui
    calls = []
    monkeypatch.setattr(desktop.multiprocessing, 'freeze_support', lambda: None)
    monkeypatch.setattr(desktop, 'configure_cache', lambda: None)
    monkeypatch.setattr(gui, 'main', lambda args: calls.append(args) or 0)
    args = ['--backend', 'cpp', '--native-library', '/host/solver', '-platform', 'offscreen']
    assert desktop.main(args) == 0
    assert calls == [args]


def test_desktop_build_lock_covers_declared_builder():
    from pathlib import Path
    import tomllib
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    from sjtu_tpmshx.development.runs.tools.check_locked_environment import read_lock
    root = Path(__file__).resolve().parents[3]
    lock = read_lock(root / 'engineering/requirements/desktop.txt')
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    for raw in project['optional-dependencies']['desktop-build']:
        requirement = Requirement(raw)
        assert lock[canonicalize_name(requirement.name)].specifier == requirement.specifier
    assert 'macholib' in lock if sys.platform == 'darwin' else 'macholib' not in lock


def test_bundle_resource_selection_excludes_user_state_and_jit_cache():
    """Check the declared collection boundary without installing PyInstaller."""
    import ast
    from pathlib import Path, PurePath
    root = Path(__file__).resolve().parents[3]
    tree = ast.parse((root / 'engineering' / 'packaging' / 'desktop.spec').read_text(encoding='utf-8'))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == 'collect_data_files']
    assert len(calls) == 1
    patterns = ast.literal_eval(next(arg.value for arg in calls[0].keywords if arg.arg == 'includes'))
    def included(name):
        return any(PurePath(name).match(pattern) for pattern in patterns)
    for resource in ('shared/configs/sco2_effective_nu.json',
                     'shared/configs/model_parameters_v1.json',
                     'shared/df_surrogate/_prebuilt/cfd_full_core_3cell_fixed_v2.csv',
                     'applications/gui/ui/assets/icons/search.svg', 'applications/gui/ui/assets/icons/LICENSE'):
        assert included(resource)
        assert (root / 'sjtu_tpmshx' / resource).is_file()
    for private_file in ('.last_session.json', '.session_timeline.jsonl', '.first_run_done',
                         'applications/gui/ui/mixins/.accent', 'solvers/__pycache__/sweep.py313.1.nbc',
                         'solvers/__pycache__/sweep.py313.nbi', 'solvers/lut_Gyroid.npz'):
        assert not included(private_file)


@pytest.fixture
def desktop_spec_prefix(monkeypatch):
    """Execute prebuilt input validation without invoking a bundler."""
    import ast
    from pathlib import Path
    from types import ModuleType

    root = Path(__file__).resolve().parents[3]
    spec = root / 'engineering/packaging/desktop.spec'
    tree = ast.parse(spec.read_text(encoding='utf-8'))
    analysis = next(i for i, node in enumerate(tree.body)
                    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name) and node.value.func.id == 'Analysis')
    code = compile(ast.Module(body=tree.body[:analysis], type_ignores=[]), str(spec), 'exec')
    for name in ('PyInstaller', 'PyInstaller.utils'):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    hooks = ModuleType('PyInstaller.utils.hooks')
    hooks.collect_data_files = lambda *args, **kwargs: []
    hooks.collect_submodules = lambda *args, **kwargs: []
    monkeypatch.setitem(sys.modules, hooks.__name__, hooks)

    def evaluate(platform):
        namespace = {'SPECPATH': str(spec.parent)}
        with monkeypatch.context() as context:
            context.setattr(sys, 'platform', platform)
            context.setattr(sys, 'path', sys.path.copy())
            exec(code, namespace)
        return namespace

    return root, evaluate


@pytest.fixture(params=['darwin', 'win32'])
def desktop_prebuilt(request, tmp_path, monkeypatch):
    names = {
        'darwin': ('libtpmshx_solver_shared.dylib', 'libtpmshx_geometry_shared.dylib', 'libtpmshx_preparation_shared.dylib', 'libtpmshx_result_shared.dylib'),
        'win32': ('tpmshx_solver_shared.dll', 'tpmshx_geometry_shared.dll', 'tpmshx_preparation_shared.dll', 'tpmshx_result_shared.dll'),
    }[request.param]
    libraries = {}
    for component, name in zip(('SOLVER', 'GEOMETRY', 'PREPARATION', 'RESULT'), names):
        path = tmp_path / name
        path.write_bytes(b'prebuilt library placeholder')
        variable = 'TPMSHX_NATIVE_' + component + '_LIBRARY'
        monkeypatch.setenv(variable, str(path))
        libraries[variable] = path
    return request.param, libraries


def test_bundle_requires_and_collects_four_prebuilt_libraries(desktop_spec_prefix, desktop_prebuilt):
    root, evaluate = desktop_spec_prefix
    platform, libraries = desktop_prebuilt
    namespace = evaluate(platform)
    assert set(namespace['binaries']) == {(str(path.resolve()), 'native') for path in libraries.values()}
    assert (str(root / 'sjtu_tpmshx/solvers/native/licenses'), 'licenses/native/licenses') in namespace['data']
    for record in ('preparation/sources.md', 'geometry/README.md', 'geometry/fields-sources.md', 'result/sources.md'):
        source = root / 'sjtu_tpmshx/solvers/native' / record
        target = 'licenses/native/' + Path(record).parent.as_posix()
        assert source.is_file()
        assert (str(source), target) in namespace['data']
    assert 'sjtu_tpmshx.development' in namespace['excluded']


@pytest.mark.parametrize('component', ['SOLVER', 'GEOMETRY', 'PREPARATION', 'RESULT'])
@pytest.mark.parametrize('fault', ['unset', 'empty', 'wrong_name', 'missing_file', 'directory'])
def test_bundle_rejects_invalid_prebuilt_input(desktop_spec_prefix, desktop_prebuilt,
                                              monkeypatch, tmp_path, component, fault):
    _, evaluate = desktop_spec_prefix
    platform, libraries = desktop_prebuilt
    variable = 'TPMSHX_NATIVE_' + component + '_LIBRARY'
    original = libraries[variable]
    expected = ValueError
    message = variable
    if fault == 'unset':
        monkeypatch.delenv(variable)
    elif fault == 'empty':
        monkeypatch.setenv(variable, '')
    else:
        parent = tmp_path / fault
        parent.mkdir()
        invalid = parent / ('wrong-library' if fault == 'wrong_name' else original.name)
        if fault == 'directory':
            invalid.mkdir()
        elif fault == 'wrong_name':
            invalid.write_bytes(b'incorrect library')
        else:
            expected = FileNotFoundError
        monkeypatch.setenv(variable, str(invalid))
        message = original.name
    with pytest.raises(expected) as error:
        evaluate(platform)
    assert message in str(error.value)
