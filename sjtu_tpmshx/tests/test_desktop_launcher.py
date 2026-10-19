"""The installed launcher must preserve CLI errors and use writable caches."""
import sys

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
    shutil.copy2(Path(__file__).resolve().parents[2] / launcher.name, launcher)
    interpreter = project / 'configured python'
    interpreter.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$MPLCONFIGDIR" "$XDG_CACHE_HOME" "$@"\n')
    interpreter.chmod(0o755)
    (project / '.venv-path').write_text(str(interpreter) + '\n')
    library = project / 'native/lib/macos-arm64/libtpmshx_solver_shared.dylib'
    library.parent.mkdir(parents=True)
    library.touch()
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
    from sjtu_tpmshx import cli
    calls = []
    monkeypatch.setattr(desktop.multiprocessing, 'freeze_support', lambda: calls.append('freeze'))
    monkeypatch.setattr(desktop, 'configure_cache', lambda: calls.append('cache'))
    monkeypatch.setattr(cli, 'main', lambda args: calls.append(args) or 2)
    assert desktop.main(['--cli', 'run', 'input.json', 'output']) == 2
    assert calls == ['freeze', 'cache', ['run', 'input.json', 'output']]


def test_desktop_gui_forwards_backend_and_qt_arguments(monkeypatch):
    from sjtu_tpmshx import main as gui
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
    from sjtu_tpmshx.runs.tools.check_locked_environment import read_lock
    root = Path(__file__).resolve().parents[2]
    lock = read_lock(root / 'requirements/desktop.txt')
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    for raw in project['optional-dependencies']['desktop-build']:
        requirement = Requirement(raw)
        assert lock[canonicalize_name(requirement.name)].specifier == requirement.specifier
    assert 'macholib' in lock if sys.platform == 'darwin' else 'macholib' not in lock


def test_bundle_resource_selection_excludes_user_state_and_jit_cache():
    """Check the declared collection boundary without installing PyInstaller."""
    import ast
    from pathlib import Path, PurePath
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / 'packaging' / 'desktop.spec').read_text(encoding='utf-8'))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == 'collect_data_files']
    assert len(calls) == 1
    patterns = ast.literal_eval(next(arg.value for arg in calls[0].keywords if arg.arg == 'includes'))
    def included(name):
        return any(PurePath(name).match(pattern) for pattern in patterns)
    for resource in ('configs/sco2_effective_nu.json',
                     'df_surrogate/_prebuilt/cfd_full_core_3cell_fixed_v2.csv',
                     'ui/assets/icons/search.svg', 'ui/assets/icons/LICENSE'):
        assert included(resource)
        assert (root / 'sjtu_tpmshx' / resource).is_file()
    for private_file in ('.last_session.json', '.session_timeline.jsonl', '.first_run_done',
                         'ui/mixins/.accent', 'solvers/__pycache__/sweep.py313.1.nbc',
                         'solvers/__pycache__/sweep.py313.nbi', 'solvers/lut_Gyroid.npz'):
        assert not included(private_file)
