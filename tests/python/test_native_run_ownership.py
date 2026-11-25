"""Release native owners when an interrupt follows a successful transfer."""
import ctypes as ct

import pytest

from tests.python import test_native_run_adapter as plane

from tests.python.native.shared_library import library_path
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.solvers import full_3d
from sjtu_tpmshx.cpp_interface import full_2d_stage
from sjtu_tpmshx.cpp_interface import full_3d_stage
from tests.python import native_stage_support


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('boundary', ['create', 'restore', 'snapshot', 'take_result'])
@pytest.mark.parametrize('exception', [KeyboardInterrupt, SystemExit])
def test_interrupt_after_native_transfer_releases_owner(dimension, boundary, exception, monkeypatch):
    library = library_path()
    control = RunControl(native_library=str(library), cpu_threads=2)
    if dimension == 2:
        _, case = plane._case()
        run_type = full_2d_stage._Run
        driver = full_2d_stage.StageDriver(library)
        native = driver.library
        monkeypatch.setattr(full_2d_stage, 'StageDriver', lambda *args, **kwargs: driver)
    else:
        config = native_stage_support.volume_configuration()
        case = prepare_case(config, case_id='ownership-transfer')
        run_type = full_3d_stage.SavedRun
        runtime = full_3d_stage.open_library(library, None)
        native = runtime[1]
        monkeypatch.setattr(full_3d_stage, 'open_library', lambda *args: runtime)

    def execute(**kwargs):
        return run_case(case, control, **kwargs)

    states = []
    if boundary == 'restore':
        execute(checkpoint=states.append)
        assert states
    prefix = f'tpmshx_stage_run_{dimension}d'
    entries = dict(run=prefix + '_release_run_v1', snapshot='tpmshx_run_state_release_v1',
                   result=prefix + '_release_v1')
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
        originals[kind] = getattr(native, entry)
        monkeypatch.setattr(native, entry, tracked(kind, originals[kind]))

    sentinel = exception('interrupt after native ' + boundary)
    original_call = run_type._call
    kind = 'run' if boundary in ('create', 'restore') else 'result' if boundary == 'take_result' else 'snapshot'

    def interrupted(self, function, *args):
        assert self.creation_version == (5 if dimension == 2 else 3)
        original_call(self, function, *args)
        if function is getattr(self, '_' + boundary):
            value = args[-1]._obj
            transferred.append((kind, owner(value, kind), value))
            assert transferred[-1][1]
            raise sentinel

    monkeypatch.setattr(run_type, '_call', interrupted)
    def forbidden(*args, **kwargs):
        pytest.fail('an interrupted transfer must not publish a FieldResult')
    monkeypatch.setattr(full_2d_stage if dimension == 2 else full_3d, 'capture_result', forbidden)
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
