"""Release native owners when an interrupt follows a successful transfer."""
import ctypes as ct

import pytest

from sjtu_tpmshx.development.tests import test_native_run_adapter as plane
from sjtu_tpmshx.development.tests import test_native_stage_3d as volume
from sjtu_tpmshx.development.tests.native.shared_library import library_path
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.shared.domain.module_ports import RunControl
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.solvers.backends.cpp import full_2d, full_2d_run, full_2d_stage
from sjtu_tpmshx.solvers.backends.cpp import full_3d, full_3d_capture, full_3d_run, full_3d_stage
from sjtu_tpmshx.solvers.backends import prepared_2d, prepared_3d


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('saved', [False, True], ids=['direct', 'saved-stage'])
@pytest.mark.parametrize('boundary', ['create', 'restore', 'snapshot', 'take_result'])
@pytest.mark.parametrize('exception', [KeyboardInterrupt, SystemExit])
def test_interrupt_after_native_transfer_releases_owner(dimension, saved, boundary, exception, monkeypatch):
    library = library_path()
    control = RunControl(native_library=str(library), cpu_threads=2)
    if dimension == 2:
        _, case = plane._case()
        module, driver_type = full_2d, full_2d.NativeFull2DDriver
        run_type = full_2d_stage._Run if saved else full_2d_run.NativeFull2DRun
        inputs = prepared_2d.build_execution_inputs(case, copy_design=False)
    else:
        config, _ = volume._configuration()
        case = prepare_case(config, case_id='ownership-transfer')
        module, driver_type = full_3d, full_3d.NativeFull3DDriver
        run_type = full_3d_stage.SavedRun if saved else full_3d_run.NativeFull3DRun
        inputs = prepared_3d.build_execution_inputs(case, copy_design=False)
    driver = driver_type(library)
    monkeypatch.setattr(module, driver_type.__name__, lambda *args, **kwargs: driver)

    def execute(**kwargs):
        return run_case(case, control, **kwargs) if saved else driver.run_prepared(*inputs, control, **kwargs)

    states = []
    if boundary == 'restore':
        execute(checkpoint=states.append)
        assert states
    prefix = f'tpmshx_stage_run_{dimension}d' if saved else f'tpmshx_full_{dimension}d_run'
    result_release = (f'tpmshx_stage_run_{dimension}d_release_v1' if saved else
                      f'tpmshx_full_{dimension}d_release_v{2 if dimension == 2 else 1}')
    entries = dict(run=prefix + ('_release_run_v1' if saved else '_release_v1'),
                   snapshot='tpmshx_run_state_release_v1', result=result_release)
    originals, released, transferred = {}, [], []

    def owner(value, kind):
        return value.value if kind == 'run' else value.owner

    def tracked(kind, function):
        def release(pointer):
            previous = owner(pointer._obj, kind)
            function(pointer)
            if previous:
                assert not owner(pointer._obj, kind)
                released.append((kind, previous))
        return release

    for kind, entry in entries.items():
        originals[kind] = getattr(driver.library, entry)
        function = tracked(kind, originals[kind])
        monkeypatch.setattr(driver.library, entry, function)
        if kind == 'result' and not saved:
            monkeypatch.setattr(driver, 'release', function)

    sentinel = exception('interrupt after native ' + boundary)
    original_call = run_type._call
    kind = 'run' if boundary in ('create', 'restore') else 'result' if boundary == 'take_result' else 'snapshot'

    def interrupted(self, function, *args):
        original_call(self, function, *args)
        if function is getattr(self, '_' + boundary):
            value = args[-1]._obj
            transferred.append((kind, owner(value, kind), value))
            assert transferred[-1][1]
            raise sentinel

    monkeypatch.setattr(run_type, '_call', interrupted)
    if saved:
        def forbidden(*args, **kwargs):
            pytest.fail('an interrupted transfer must not publish a FieldResult')
        monkeypatch.setattr(full_2d_stage if dimension == 2 else full_3d_capture, 'capture_result', forbidden)
    options = dict(checkpoint=lambda state: None, checkpoint_due=lambda: boundary == 'snapshot')
    if states:
        options['resume_state'] = states[0]
    try:
        with pytest.raises(exception) as caught:
            execute(**options)
        assert caught.value is sentinel
        assert len(transferred) == 1
        assert released.count(transferred[0][:2]) == 1
        assert not owner(transferred[0][2], kind)
        assert [name for name, _ in released].count('run') == 1
        assert len(released) == (1 if kind == 'run' else 2)
    finally:
        # Keep a failed regression from leaking its deliberately interrupted owner.
        for name, _, value in transferred:
            if owner(value, name):
                originals[name](ct.byref(value))
