"""The root main.py routes each mode before heavy imports and keeps GUI caches writable."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtCore import QStandardPaths

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def entry():
    spec = spec_from_file_location('tm1_root_main', ROOT / 'main.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# A spawned child imports main.py as __mp_main__; the CLI routes stop at argparse help.
# The top-level help ("--help" alone) lists the modes; Linux result hosts have no Qt.
_CHILD = """
import runpy, sys
script, mode = sys.argv[1], sys.argv[2:]
sys.argv = [script, *dict.fromkeys([*mode, '--help'])] if mode else [script]
try:
    runpy.run_path(script, run_name='__main__' if mode else '__mp_main__')
except SystemExit as stop:
    assert stop.code == 0, stop.code
heavy = sorted(name for name in sys.modules
               if name.split('.')[0] in {'PySide6', 'vtk', 'vtkmodules', 'pyvista', 'matplotlib', 'torch'})
assert not heavy, heavy
"""


@pytest.mark.parametrize('mode', [[], ['--help'], ['run'], ['resume'], ['summary'], ['design'], ['optimize']],
                         ids=lambda mode: mode[0] if mode else 'spawn-child')
def test_cli_routes_and_spawn_children_import_no_gui_or_torch(mode):
    run = subprocess.run([sys.executable, '-c', _CHILD, str(ROOT / 'main.py'), *mode],
                         cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    if mode == ['--help']:
        assert all(name in run.stdout for name in ('prepare', 'summary', 'design', 'optimize'))


def test_gui_caches_respect_explicit_paths(tmp_path, monkeypatch):
    from tm1.applications.gui import main as gui
    monkeypatch.setattr(QStandardPaths, 'writableLocation', lambda *_: str(tmp_path))
    for name in ('MPLCONFIGDIR', 'XDG_CACHE_HOME'):
        monkeypatch.delenv(name, raising=False)
    explicit = tmp_path / 'chosen-matplotlib'
    monkeypatch.setenv('MPLCONFIGDIR', str(explicit))
    gui.configure_cache()
    assert explicit.is_dir()
    assert (tmp_path / 'SJTU-TPMSHX-TM1' / 'libraries').is_dir()


def test_stage_route_preserves_status(entry, monkeypatch):
    from tm1.applications.cli import stages
    calls = []
    monkeypatch.setattr(stages, 'main', lambda args: calls.append(args) or 2)
    assert entry.main(['run', 'input.json', 'output']) == 2
    assert calls == [['run', 'input.json', 'output']]


@pytest.mark.parametrize('prefix', [[], ['gui']])
def test_gui_is_default_and_forwards_backend_and_qt_arguments(entry, monkeypatch, prefix):
    from tm1.applications.gui import main as gui
    calls = []
    monkeypatch.setattr(gui, 'main', lambda args: calls.append(args) or 0)
    args = ['--backend', 'cpp', '--native-library', '/host/solver', '-platform', 'offscreen']
    assert entry.main([*prefix, *args]) == 0
    assert calls == [args]


def test_unknown_mode_fails(entry, capsys):
    assert entry.main(['unknown']) == 2
    assert "unknown mode 'unknown'" in capsys.readouterr().err


def test_gui_app_disables_automatic_gc_with_main_thread_timer():
    import gc
    from PySide6.QtWidgets import QApplication
    from tm1.applications.gui.controllers import main_thread_gc

    app = QApplication.instance()
    assert app is not None
    assert not gc.isenabled()
    timer = main_thread_gc._timer
    assert timer is not None and timer.isActive()
    assert timer.interval() == 1000
    assert timer.thread() is app.thread()


def test_desktop_build_lock_covers_declared_builder():
    from pathlib import Path
    import tomllib
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    from tm1.development.runs.tools.check_locked_environment import read_lock
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
    for resource in ('model_configs/sco2_effective_nu.json',
                     'model_configs/model_parameters_v1.json',
                     'physical_models/df_surrogate/_prebuilt/cfd_full_core_3cell_fixed_v2.csv',
                     'applications/gui/ui/assets/icons/search.svg', 'applications/gui/ui/assets/icons/LICENSE'):
        assert included(resource)
        assert (root / 'python' / resource).is_file()
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
    code = compile(tree, str(spec), 'exec')

    class InputsReady(Exception):
        pass

    def stop_before_build(*args, **kwargs):
        raise InputsReady

    for name in ('PyInstaller', 'PyInstaller.utils'):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    hooks = ModuleType('PyInstaller.utils.hooks')
    hooks.collect_data_files = lambda *args, **kwargs: []
    hooks.collect_submodules = lambda *args, **kwargs: []
    monkeypatch.setitem(sys.modules, hooks.__name__, hooks)

    from engineering.packaging import python_source
    monkeypatch.setattr(python_source, 'build_package', lambda root, directory: None)
    # The spec imports PyVista. Import it here under the host platform, not the simulated one.
    import pyvista  # noqa: F401

    def evaluate(platform):
        namespace = {'SPECPATH': str(spec.parent), 'Analysis': stop_before_build}
        with monkeypatch.context() as context:
            context.setattr(sys, 'platform', platform)
            context.setattr(sys, 'path', sys.path.copy())
            try:
                exec(code, namespace)
            except InputsReady:
                pass
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
    staged = root / '.cache/desktop/native-notices'
    assert (str(staged / 'THIRD_PARTY_NOTICES.md'), 'licenses/native') in namespace['data']
    assert (str(staged / 'licenses/CoolProp.txt'), 'licenses/native/licenses') in namespace['data']
    notices = (staged / 'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8')
    for record in ('preparation/sources.md', 'geometry/README.md', 'geometry/fields-sources.md', 'result/sources.md'):
        assert (staged / record).is_file()
        assert record in notices
    assert '(licenses/CoolProp.txt)' in notices
    assert (staged / 'licenses/CoolProp.txt').read_bytes() == (root / 'engineering/native_build/licenses/CoolProp.txt').read_bytes()
    assert 'tm1.development' in namespace['excluded']
    # PyVista and PyVistaQt import VTK modules through importlib, which Analysis does not see.
    # Read the module names from the installed packages, so that a new name upstream also fails.
    import re
    from pathlib import Path
    import pyvista
    from pyvista import _vtk as pyvista_vtk
    from pyvistaqt import _vtk as pyvistaqt_vtk
    direct = {name for path in Path(pyvista.__file__).parent.rglob('*.py')
              for name in re.findall(r'''(?:_VTK_ROOT\}\.|_import_from\(['"]|['"]vtkmodules\.)(vtk\w+)''',
                                     path.read_text(encoding='utf-8'))}
    assert {'vtkRenderingContextOpenGL2', 'vtkRenderingMatplotlib', 'vtkPythonContext2D'} <= direct
    requested = {*pyvista_vtk._CORE_MODULES, *pyvista_vtk._PLOTTING_MODULES, *pyvista_vtk._OPENGL_MODULES,
                 *direct, *pyvistaqt_vtk._FALLBACK_MODULES.values()}
    assert {f'vtkmodules.{name}' for name in requested} <= set(namespace['hidden'])


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
