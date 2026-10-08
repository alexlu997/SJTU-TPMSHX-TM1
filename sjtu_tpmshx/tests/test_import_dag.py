"""Import-DAG locks (openspec arch-b-c-e batch B + contracts-layer).

The kernel import direction is:

    tpms_geometry ← tpms_props ← df_surrogate ← tpms_calc / simple_solver / ...

and pipelines must be importable without controllers (contracts-layer).
These tests run each probe in a FRESH interpreter so this test module's own
imports cannot pollute sys.modules.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = str(Path(__file__).resolve().parents[2])


def _probe(code: str) -> None:
    r = subprocess.run([sys.executable, '-c', code], cwd=_REPO,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"probe failed:\n{r.stdout}\n{r.stderr}"


def test_df_surrogate_is_below_the_kernel():
    """df_surrogate must import via the tpms_props LEAF only — pulling
    tpms_calc/simple_solver back in would recreate the two-way coupling."""
    _probe(
        "import sys; import sjtu_tpmshx.df_surrogate.predict; "
        "bad = [m for m in ('sjtu_tpmshx.models.tpms_calc', 'sjtu_tpmshx.solvers.simple_solver')"
        " if m in sys.modules]; "
        "assert not bad, f'df_surrogate pulled kernel modules: {bad}'; "
        "assert 'sjtu_tpmshx.models.tpms_props' not in sys.modules  # backend is lazy too"
    )


def test_tpms_props_is_a_leaf():
    """Property imports may reach training-domain constants, not inference/solvers."""
    _probe(
        "import sys; import sjtu_tpmshx.models.tpms_props; "
        "allowed = {'sjtu_tpmshx.df_surrogate', 'sjtu_tpmshx.df_surrogate._domain'}; "
        "bad = [m for m in sys.modules if (m.startswith('sjtu_tpmshx.df_surrogate')"
        " and m not in allowed) or m.startswith('sjtu_tpmshx.solvers')"
        " or m == 'sjtu_tpmshx.models.tpms_calc']; "
        "assert not bad, f'tpms_props is not a leaf: {bad}'"
    )


def test_pipelines_import_without_controllers():
    """Scripted orchestration and input preparation stay below controllers."""
    _probe(
        "import sys; import sjtu_tpmshx.pipelines.run_stack_3d; "
        "import sjtu_tpmshx.preprocess.two_d.preparation; "
        "import sjtu_tpmshx.preprocess.three_d.preparation; "
        "bad = [m for m in sys.modules if m == 'controllers' "
        "or m.startswith(('controllers.', 'sjtu_tpmshx.controllers'))]; "
        "assert not bad, f'pipelines pulled controllers: {bad}'"
    )


def test_legacy_orchestration_does_not_modify_backend_namespace():
    _probe(
        "from sjtu_tpmshx.solvers.backends.python.three_d import runtime; "
        "before = dict(vars(runtime)); "
        "import sjtu_tpmshx.pipelines.run_stack_3d; "
        "assert vars(runtime).keys() == before.keys(); "
        "assert all(vars(runtime)[key] is value for key, value in before.items())"
    )


def test_public_modules_prepare_without_numba_then_real_execution_initializes_once():
    _probe('''
import os
import sys
os.environ['NUMBA_NUM_THREADS'] = '2'
os.environ['TPMSHX_NUM_THREADS'] = '1'
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.preprocess.api import prepare_quick_design
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.design.cases import DesignCase
assert 'numba' not in sys.modules
assert 'sjtu_tpmshx.solvers.threads' not in sys.modules

condition = DesignCase(1, 'air', 688.23, 1088700., .2855,
                       'water', 320., 200000., .5, 30000., .075, .05)
prepared = prepare_quick_design(condition, 'Diamond', 7., .5, .084, .025,
                                case_id='lazy-python-backend')
assert 'numba' not in sys.modules
result = run_case(prepared)
import numba
assert numba.get_num_threads() == 1
assert result.run_status['converged']
assert evaluate(result).metrics['Q'].value > 0.

# Explicit runtime control must survive later imports and repeated execution.
from sjtu_tpmshx.solvers.threads import set_solver_threads
set_solver_threads(2)
from sjtu_tpmshx.solvers import simple_solver, simple_solver_3d, ltne_enthalpy_3d
assert numba.get_num_threads() == 2
second = run_case(prepared)
assert second.run_status['converged']
assert numba.get_num_threads() == 2
''')


def test_native_gui_worker_lifecycle_does_not_initialize_python_numerics():
    _probe('''
import sys
import time
from PySide6.QtCore import QCoreApplication
from sjtu_tpmshx.controllers.compute_orchestrator import ComputeOrchestrator
from sjtu_tpmshx.domain.cancellation import CancelledError
app = QCoreApplication([])
orch = ComputeOrchestrator(backend='cpp')
events = []
orch.finished.connect(lambda result: events.append(('finished', result)))
orch.error.connect(lambda message, log: events.append(('error', message)))
orch.cancelled.connect(lambda log: events.append(('cancelled', None)))
for outcome in ('finished', 'error', 'cancelled'):
    def worker(config, cancel, progress_cb):
        progress_cb(50)
        if outcome == 'error':
            raise ValueError('native-error')
        if outcome == 'cancelled':
            cancel.cancel()
            raise CancelledError()
        return 'native-result'
    assert orch.start('2d', worker, {})
    deadline = time.monotonic() + 5
    while orch.is_running() and time.monotonic() < deadline:
        app.processEvents()
    assert not orch.is_running()
assert events == [('finished', 'native-result'), ('error', 'native-error'), ('cancelled', None)]
assert 'numba' not in sys.modules
assert 'sjtu_tpmshx.solvers.threads' not in sys.modules
assert not any(name.startswith('sjtu_tpmshx.solvers.backends.python') for name in sys.modules)
''')


def test_native_desktop_and_quick_design_keep_host_control_without_numba():
    _probe('''
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from sjtu_tpmshx.controllers import user_storage
from sjtu_tpmshx.domain.module_ports import RunControl
with TemporaryDirectory() as temporary:
    def directory(location, *parts):
        target = Path(temporary, location.name, *parts)
        target.mkdir(parents=True, exist_ok=True)
        return target
    with patch.object(user_storage, '_directory', directory):
        from sjtu_tpmshx.main import Main_Menu
        app = QApplication([])
        control = RunControl(backend='cpp', native_library='/host/solver',
                             native_table_directory='/host/tables')
        window = Main_Menu(control=control)
        window._open_quick_design()
        assert window._qd_dialog.run_control is control
        assert window.compute.backend == 'cpp'
        assert not window.spin_cpu_cores.isEnabled()
        assert window.spin_cpu_cores.text() == '自动'
        assert 'numba' not in sys.modules
        assert 'sjtu_tpmshx.solvers.threads' not in sys.modules
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
''')
