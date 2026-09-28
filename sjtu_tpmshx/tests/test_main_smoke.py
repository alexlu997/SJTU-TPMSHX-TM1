"""Real startup controls and isolated CPU thread-mask changes."""
import pytest

from sjtu_tpmshx.tests.gui_workbench_support import win as win


@pytest.fixture
def solver_threads():
    from sjtu_tpmshx.solvers import threads

    original = threads.get_solver_threads()
    try:
        yield threads
    finally:
        threads.set_solver_threads(original)


def test_cpu_cores_spinbox_sets_threads(solver_threads, win):
    """The real window keeps its startup controls and changes the active mask."""
    for name in ('combo_tpms', 'le_L', 'le_H', 'canvas_temp', 'progress'):
        assert hasattr(win, name), f'{name} missing after startup'
    mx = solver_threads.max_threads()
    assert win.spin_cpu_cores.maximum() == mx
    assert win.spin_cpu_cores.value() == solver_threads.get_solver_threads()
    if mx > 1:  # A real value change must emit the signal.
        win.spin_cpu_cores.setValue(mx)
        target = mx // 2
        win.spin_cpu_cores.setValue(target)
        assert solver_threads.get_solver_threads() == target
        win.spin_cpu_cores.setValue(mx)
        assert solver_threads.get_solver_threads() == mx


@pytest.mark.parametrize('failed', [False, True], ids=['normal', 'assertion-failure'])
def test_thread_fixture_restores_original_mask(failed):
    from sjtu_tpmshx.solvers import threads

    original = threads.get_solver_threads()
    lifecycle = solver_threads.__wrapped__()
    try:
        threads.set_solver_threads(1)
        next(lifecycle)
        threads.set_solver_threads(threads.max_threads())
        if failed:
            with pytest.raises(AssertionError, match='failed CPU check'):
                lifecycle.throw(AssertionError('failed CPU check'))
        else:
            with pytest.raises(StopIteration):
                next(lifecycle)
        assert threads.get_solver_threads() == 1
    finally:
        try:
            lifecycle.close()
        finally:
            threads.set_solver_threads(original)
