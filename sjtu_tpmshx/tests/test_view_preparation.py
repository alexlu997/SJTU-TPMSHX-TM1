"""3D imports keep the GUI responsive and preserve result ownership."""
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
from shiboken6 import isValid

from sjtu_tpmshx.tests.gui_workbench_support import _result
from sjtu_tpmshx.tests.gui_worker_support import _wait_for, win as win
from sjtu_tpmshx.ui import background_tasks, optimize_panel


@pytest.fixture
def imports(win, monkeypatch):
    state = SimpleNamespace(entered=threading.Event(), release=threading.Event(),
                            calls=[], error=None)

    def load(name):
        state.calls.append((name, QThread.currentThread()))
        state.entered.set()
        assert state.release.wait(10)
        if state.error:
            raise state.error

    monkeypatch.setattr(background_tasks, 'import_module', load)
    monkeypatch.setattr(win, '_vis3d_import_error', None)
    yield state
    state.release.set()
    _wait_for(lambda: not isValid(win) or not background_tasks.has_active_tasks(win))


def test_imports_share_one_worker_and_deliver_on_gui_thread(win, imports):
    calls, ticks = [], []
    timer = QTimer(win)
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start(10)

    def ready():
        calls.append(QThread.currentThread())
        assert background_tasks.has_active_tasks(win)

    background_tasks.prepare_3d(win, ready)
    worker = win._view_import_worker
    background_tasks.prepare_3d(win, ready)
    _wait_for(lambda: imports.entered.is_set() and len(ticks) >= 3)
    assert win._view_import_worker is worker and len(imports.calls) == 1
    assert not calls and not win.spin_cpu_cores.isEnabled()
    assert imports.calls[0][1] != QApplication.instance().thread()
    imports.release.set()
    _wait_for(lambda: not background_tasks.has_active_tasks(win))
    assert calls == [QApplication.instance().thread()] * 2
    assert [name for name, _ in imports.calls] == [
        'sjtu_tpmshx.ui.panel_vis_3d', 'scipy.interpolate']
    _wait_for(win.spin_cpu_cores.isEnabled)
    background_tasks.prepare_3d(win, lambda: calls.append('already ready'))
    assert calls[-1] == 'already ready' and len(imports.calls) == 2


@pytest.mark.parametrize('failure', [False, True])
def test_pending_result_publishes_once_and_remains_exportable(
        win, imports, monkeypatch, tmp_path, failure):
    from sjtu_tpmshx.tests.test_result_snapshot_lifecycle import _assert_export

    result = _result('3d')
    result.metadata['snapshot_marker'] = 123
    published = []
    write = win.write_result

    def publish(value):
        published.append(value)
        write(value)

    monkeypatch.setattr(win, 'write_result', publish)
    def render(window):
        if window._vis3d_import_error:
            return False
        window.canvas_3d = QWidget(window)
        return True
    monkeypatch.setattr('sjtu_tpmshx.ui.plot_3d_results.finalize_plots_3d', render)
    win.compute._mode = '3d'
    win._active_preset_name = 'prepared-original'
    win._on_orch_started('3d')
    if failure:
        imports.error = ImportError('view module unavailable')
    win._on_orch_finished(result)
    win._on_orch_finished(result)
    assert published == [result] and not win._compute_running
    assert not imports.entered.is_set()
    accepted = win.cache.get_result('3d')
    assert accepted is not result and accepted.Q_W == result.Q_W
    assert accepted.fields['Ta'] is result.fields['Ta'] and win.btn_export.isEnabled()
    assert not win._3d_view_ready and win._active_tab == 'temp'
    assert accepted.metadata['timings_s']['display'] > 0
    assert accepted.metadata['run_provenance']['preset_source'] == 'prepared-original'
    win._switch_tab('3d')
    _wait_for(imports.entered.is_set)
    assert win.cache.get_result('3d') is accepted and win.btn_export.isEnabled()
    assert win._active_tab == 'temp'
    win._active_preset_name = 'changed-draft'
    win.le_TinA.setText('444')
    imports.release.set()
    _wait_for(lambda: not background_tasks.has_active_tasks(win))
    assert win._3d_view_ready is not failure
    assert win._active_tab == ('temp' if failure else '3d')
    assert win.le_TinA.text() == '444'
    assert accepted.metadata['timings_s']['volume_display'] > 0
    _assert_export(win, monkeypatch, tmp_path / 'accepted.csv', accepted)
    if failure:
        assert 'view module unavailable' in win._vis3d_import_error
        assert len(imports.calls) == 1


def test_close_and_restart_keep_owner_alive_until_imports_finish(win, imports, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: messages.append(args))
    monkeypatch.setattr('os.execv', lambda *args: pytest.fail('restarted during imports'))
    monkeypatch.setattr(win, '_save_session', lambda: True)
    win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    win._schedule_3d_preinit()
    _wait_for(imports.entered.is_set)
    workspace = win._active_workspace
    win._restart_for_appearance()
    win._switch_workspace('B' if workspace == 'A' else 'A')
    assert len(messages) == 2 and win._active_workspace == workspace
    assert not win.close() and win._close_pending and isValid(win)
    imports.release.set()
    _wait_for(lambda: not isValid(win))


def test_optional_preinit_reports_import_failure(win, imports):
    imports.error = ImportError('view module unavailable')
    win._schedule_3d_preinit()
    _wait_for(imports.entered.is_set)
    imports.release.set()
    _wait_for(lambda: not background_tasks.has_active_tasks(win))
    assert win.canvas_3d is None
    assert 'view module unavailable' in win.statusBar().currentMessage()


def test_split_request_waits_for_volume_without_losing_primary_field(win, imports, monkeypatch):
    win.write_result(_result('3d'))
    win._rendered_3d_slices = True
    win._switch_tab('temp')

    def render(window):
        window.canvas_3d = QWidget(window)
        return True

    monkeypatch.setattr('sjtu_tpmshx.ui.plot_3d_results.finalize_plots_3d', render)
    win._split_with_current('3d')
    _wait_for(imports.entered.is_set)
    assert win._active_tab == 'temp'
    imports.release.set()
    _wait_for(lambda: not background_tasks.has_active_tasks(win))
    assert win._3d_view_ready
    assert win._split_tabs == ['temp', '3d']
    assert win._active_tab == 'temp'


@pytest.mark.parametrize('change', ['new_data', 'other_tab', 'no_data'])
def test_optimization_reads_current_fields_after_shared_imports(
        win, imports, monkeypatch, change):
    from sjtu_tpmshx.ui import panel_vis_3d

    created = []

    class Panel(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._volume_actor = object()
            self.fields = None
            created.append(self)

        def restore_color_ranges(self, _ranges):
            pass

        def set_fields(self, **fields):
            self.fields = fields

        def cleanup(self):
            pass

    monkeypatch.setattr(panel_vis_3d, 'ThreeDVisPanel', Panel)
    background_tasks.prepare_3d(win, lambda: None)
    worker = win._view_import_worker
    win._opt_3d_data = {'marker': 'old'}
    win._opt_result_tabs.setTabEnabled(2, True)
    win._opt_result_tabs.setCurrentWidget(win._opt_3d_host)
    optimize_panel.show_field_volume(win)
    assert win._view_import_worker is worker and win._opt_3d_loading
    win._opt_3d_data = None if change == 'no_data' else {'marker': 'current'}
    if change == 'other_tab':
        win._opt_result_tabs.setCurrentIndex(0)
    imports.release.set()
    _wait_for(lambda: not background_tasks.has_active_tasks(win))
    assert not win._opt_3d_loading
    if change == 'new_data':
        assert len(created) == 1 and created[0].fields == {'marker': 'current'}
        assert win._opt_3d_ready
    else:
        assert not created and not win._opt_3d_ready
    if change == 'other_tab':
        win._opt_result_tabs.setCurrentWidget(win._opt_3d_host)
        assert len(created) == 1 and created[0].fields == {'marker': 'current'}


@pytest.mark.parametrize('change', ['new_result', 'other_tab', 'no_result'])
def test_deferred_volume_does_not_show_an_obsolete_request(win, imports, monkeypatch, change):
    win.write_result(_result('3d'))
    calls = []
    monkeypatch.setattr('sjtu_tpmshx.ui.plot_3d_results.finalize_plots_3d',
                        lambda window: calls.append(window.cache.get_result('3d')))
    win._switch_tab('3d')
    _wait_for(imports.entered.is_set)
    if change == 'new_result':
        win.write_result(_result('3d'))
    elif change == 'other_tab':
        win._switch_tab('layout')
    else:
        win.cache.clear()
    imports.release.set()
    _wait_for(lambda: not background_tasks.has_active_tasks(win))
    assert not calls and not win._3d_view_ready
    assert win._requested_3d_result is None
