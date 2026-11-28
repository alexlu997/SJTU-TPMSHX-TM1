"""Release native owners when an interrupt follows a successful transfer."""
import ctypes as ct
from pathlib import Path

import pytest

from tests.python.native_adapters import test_native_run_adapter as plane

from tests.python.native.shared_library import library_path
from tm1.preprocess.api import prepare_case
from tm1.run_control.module_ports import RunControl
from tm1.solvers.api import run_case
from tm1.solvers import full_2d, full_3d
from tm1.cpp_interface import full_2d_stage
from tm1.cpp_interface import full_3d_stage
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
    monkeypatch.setattr(full_2d if dimension == 2 else full_3d, 'capture_result', forbidden)
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


def test_full_2d_capture_detaches_before_release_and_survives_second_solve(monkeypatch):
    from tm1.postprocess.api import evaluate

    library = library_path()
    control = RunControl(native_library=str(library), cpu_threads=1)
    _, case_one = plane._case(False, ('air', 'water'))
    _, case_two = plane._case(True, ('water', 'sco2'))

    original_entries = full_2d_stage.stage_entries
    original_capture = full_2d.capture_result
    events = []

    def tracked_entries(native_lib):
        bound = original_entries(native_lib)
        release = bound['release']

        def tracked_release(pointer):
            assert pointer._obj.owner
            release(pointer)
            assert not pointer._obj.owner
            events.append('release')

        return dict(bound, release=tracked_release)

    def checked_capture(*args, **kwargs):
        # The native stage result must already be released before host assembly runs.
        events.append('capture')
        hv = kwargs['application_hv']
        assert isinstance(hv, tuple) and len(hv) == 2 and all(type(value) is float for value in hv)
        assert not callable(hv)
        assert kwargs['zone_summary'] is None or isinstance(kwargs['zone_summary'], dict)
        return original_capture(*args, **kwargs)

    monkeypatch.setattr(full_2d_stage, 'stage_entries', tracked_entries)
    monkeypatch.setattr(full_2d, 'capture_result', checked_capture)

    first = run_case(case_one, control)
    assert events == ['release', 'capture']
    snapshot_fields = {name: (arr.dtype, arr.shape, arr.tobytes()) for name, arr in first.fields.items()}
    snapshot_coeffs = dict(first.metadata['application']['coeffs'])
    first_metrics = {
        name: (metric.status, None if metric.value is None else float(metric.value))
        for name, metric in evaluate(first).metrics.items()
    }

    second = run_case(case_two, control)
    assert events == ['release', 'capture', 'release', 'capture']
    second_eval = evaluate(second)
    assert second_eval.source_result_id == second.result_id

    for name, (dtype, shape, raw_bytes) in snapshot_fields.items():
        actual = first.fields[name]
        assert actual.dtype == dtype and actual.shape == shape and actual.tobytes() == raw_bytes
    assert first.metadata['application']['coeffs'] == snapshot_coeffs
    after_metrics = {
        name: (metric.status, None if metric.value is None else float(metric.value))
        for name, metric in evaluate(first).metrics.items()
    }
    assert after_metrics == first_metrics


def test_fake_owner_mutation_on_release_leaves_detached_capture_intact():
    import numpy as np
    from tm1.cpp_interface import _native_result as core
    from tm1.cpp_interface import _native_result_stage as wire
    from tm1.cpp_interface.solver_library import stage_capture

    buf = (ct.c_double * 4)(10.5, 20.25, 30.75, 40.125)
    shape = (ct.c_size_t * 2)(2, 2)
    raw_array = core._Array(ct.addressof(buf), 2, shape)
    name_a = ct.create_string_buffer(b'Ta')
    name_disp = ct.create_string_buffer(b'Ta_display')
    unit_k = ct.create_string_buffer(b'K')
    state_raw = ct.create_string_buffer(b'raw')
    state_disp = ct.create_string_buffer(b'display')
    named = (wire.Named * 2)(
        wire.Named(ct.cast(name_a, ct.c_char_p), raw_array),
        wire.Named(ct.cast(name_disp, ct.c_char_p), raw_array),
    )
    decls = (wire.Declaration * 2)(
        wire.Declaration(ct.cast(name_a, ct.c_char_p), ct.cast(unit_k, ct.c_char_p), ct.cast(state_raw, ct.c_char_p)),
        wire.Declaration(ct.cast(name_disp, ct.c_char_p), ct.cast(unit_k, ct.c_char_p), ct.cast(state_disp, ct.c_char_p)),
    )
    evidence = wire.Evidence(dimension=2, fields=named, field_count=2, field_metadata=decls, field_metadata_count=2)

    version = ct.create_string_buffer(b'applicability_evidence_v1')
    group = ct.create_string_buffer(b'nu')
    side = ct.create_string_buffer(b'A')
    src_text = ct.create_string_buffer(b'air')
    src_arr = (ct.c_char_p * 1)(ct.cast(src_text, ct.c_char_p))
    req = (wire.Required * 1)(wire.Required(
        ct.cast(group, ct.c_char_p), ct.cast(side, ct.c_char_p), src_arr, 1))
    app = wire.Applicability(
        version=ct.cast(version, ct.c_char_p), inlet=None, final_state=None,
        inlet_count=0, final_count=0, required=req, required_count=1, inlet_recorded=1)

    fields, metadata = stage_capture.detach_stage_fields(evidence, (2, 2))
    applicability = stage_capture.copy_applicability(ct.pointer(app), ())
    assert np.shares_memory(fields['Ta'], fields['Ta_display'])

    # Simulate native release clobbering every raw backing buffer.
    for owned in (buf, name_a, name_disp, unit_k, state_raw, state_disp, version, group, side, src_text):
        ct.memset(ct.addressof(owned), 0, ct.sizeof(owned))

    np.testing.assert_array_equal(fields['Ta'], np.array([[10.5, 20.25], [30.75, 40.125]]))
    np.testing.assert_array_equal(fields['Ta_display'], np.array([[10.5, 20.25], [30.75, 40.125]]))
    assert metadata == {
        'Ta': dict(unit='K', state='raw', axes=('x', 'y'), location='cell'),
        'Ta_display': dict(unit='K', state='display', axes=('x', 'y'), location='cell'),
    }
    assert applicability == dict(
        version='applicability_evidence_v1', inlet_recorded=True,
        inlet=[], final=[], required=[dict(group='nu', side='A', source=('air',))])


@pytest.mark.parametrize('exception_type', [StopIteration, LookupError, MemoryError])
@pytest.mark.parametrize('seam', [
    'borrow_array', 'borrow_text', 'completed_report', 'detach_stage_fields',
    'executed_view', 'stage_closures', 'copy_applicability',
    'application_hv_A', 'application_hv_B',
])
def test_full_2d_injected_failures_preserve_exception_and_release_once(monkeypatch, exception_type, seam):
    from dataclasses import replace
    from tm1.cpp_interface.solver_library import stage_capture

    library = library_path()
    control = RunControl(native_library=str(library), cpu_threads=1)
    _, case = plane._case(False, ('air', 'water'))
    if seam == 'borrow_text':
        case = replace(case, metadata={**case.metadata, 'notices': (*case.metadata['notices'], 'saved-notice')})
    sentinel = exception_type(f'injected-{seam}')
    released = []
    original_entries = full_2d_stage.stage_entries

    def tracked_entries(native_lib):
        bound = original_entries(native_lib)
        release = bound['release']
        query = bound['query']
        query_calls = 0

        def tracked_release(pointer):
            assert pointer._obj.owner
            release(pointer)
            released.append(pointer._obj.owner)

        def wrapped_query(result_ptr, app_ptr, summary_ptr):
            nonlocal query_calls
            query_calls += 1
            if seam == 'application_hv_A' and query_calls == 2:
                raise sentinel
            if seam == 'application_hv_B' and query_calls == 3:
                raise sentinel
            return query(result_ptr, app_ptr, summary_ptr)

        return dict(bound, release=tracked_release, query=wrapped_query)

    def fail(*args, **kwargs):
        raise sentinel

    def forbidden(*args, **kwargs):
        pytest.fail('capture_result must not run after an injected native read or pack failure')

    monkeypatch.setattr(full_2d_stage, 'stage_entries', tracked_entries)
    monkeypatch.setattr(full_2d, 'capture_result', forbidden)
    if seam in ('borrow_array', 'borrow_text', 'completed_report', 'detach_stage_fields', 'executed_view'):
        monkeypatch.setattr(full_2d_stage, seam, fail)
    elif seam in ('stage_closures', 'copy_applicability'):
        monkeypatch.setattr(stage_capture, seam, fail)

    with pytest.raises(exception_type) as caught:
        run_case(case, control)
    assert caught.value is sentinel
    expected_releases = [] if seam in ('borrow_array', 'borrow_text') else [None]
    assert released == expected_releases


def test_copy_applicability_and_zone_temperatures_preserve_stop_iteration(monkeypatch):
    from tm1.cpp_interface import _native_result as core
    from tm1.cpp_interface import _native_result_stage as wire
    from tm1.cpp_interface.solver_library import stage_capture

    sentinel = StopIteration('native-read-stop')

    class ExplodingBytes:
        def decode(self):
            raise sentinel

    class FakeRow:
        group = b'nu'
        side = b'A'
        source = [ExplodingBytes()]
        source_count = 1

    class FakeValue:
        version = b'applicability_evidence_v1'
        inlet_count = 0
        final_count = 0
        inlet_recorded = 1
        required = [FakeRow()]
        required_count = 1

    class FakePointer:
        contents = FakeValue()

    with pytest.raises(StopIteration) as caught:
        stage_capture.copy_applicability(FakePointer(), ())
    assert caught.value is sentinel

    monkeypatch.setattr(core, 'array', lambda *args, **kwargs: (_ for _ in ()).throw(sentinel))
    with pytest.raises(StopIteration) as caught:
        wire._zone_temperatures(([1.], [1.]), ([300.], [300.], [300.]), [[0]], [('z0', 7., .6)], (1., 1.), ((), ()))
    assert caught.value is sentinel


def test_native_run_requires_error_types_and_stage_maps_match_hosts():
    from tm1.cpp_interface.run_state import NativeRun
    from tm1.physical_models.envelope import ChokedFlowError
    from tm1.physical_models.fluid_props import WaterStateError
    from tm1.run_control.cancellation import CancelledError

    assert not hasattr(NativeRun, 'error_types')
    with pytest.raises(TypeError):
        NativeRun(None, [], [], None, None)

    for code, expected in (
        (1, ValueError),
        (2, WaterStateError),
        (3, FloatingPointError),
        (4, ChokedFlowError),
        (6, CancelledError),
        (99, RuntimeError),
    ):
        message = ct.create_string_buffer(f'status-{code}'.encode())
        with pytest.raises(expected, match=f'^status-{code}$'):
            full_2d_stage._raise_stage_error(code, message, full_2d._ERROR_TYPES)

    msg7 = ct.create_string_buffer(b'outer: detail reason')
    with pytest.raises(ValueError, match='^outer: detail reason$') as caught7:
        full_2d_stage._raise_stage_error(7, msg7, full_2d._ERROR_TYPES)
    assert isinstance(caught7.value.__cause__, ValueError)
    assert str(caught7.value.__cause__) == 'detail reason'
    assert caught7.value.__cause__.__cause__ is None

    msg8 = ct.create_string_buffer(b'outer: window detail')
    with pytest.raises(ValueError, match='^outer: window detail$') as caught8:
        full_2d_stage._raise_stage_error(8, msg8, full_2d._ERROR_TYPES)
    assert isinstance(caught8.value.__cause__, ValueError)
    assert str(caught8.value.__cause__) == 'window detail'
    assert isinstance(caught8.value.__cause__.__cause__, ValueError)
    assert str(caught8.value.__cause__.__cause__) == 'HX velocity outside application window'

    assert full_3d._DOMAIN_ERRORS == {1: ValueError, 2: WaterStateError, 3: FloatingPointError}


def test_zone_result_warning_stacklevel_and_solver_only_image_isolation(monkeypatch, tmp_path):
    import warnings
    import numpy as np
    from tm1.cpp_interface import _native_result as core
    from tm1.cpp_interface import _native_result_stage as wire
    from tm1.physical_models.zone_config import Zone, ZoneConfig
    from tests.python.native_adapters import test_native_prepare_spatial_adapter as spatial
    from tests.python.native_preparation_abi import _configuration_fluids

    # Pin floating-point RuntimeWarning provenance across the zone_temperatures wrapper.
    def fake_call(name, argtypes, *arguments, stacklevel=4, library=None):
        diagnostics = core._Diagnostics()
        diagnostics.event_count = 1
        diagnostics.events[0].flags = 1
        diagnostics.events[0].operation = 4
        core.notify(diagnostics, stacklevel=stacklevel)

    monkeypatch.setattr(core, 'call', fake_call)
    widths = (np.array([1., 1.]), np.array([1., 1.]))
    temps = [np.full((2, 2), 300.) for _ in range(3)]
    zone_id = np.array([[0, 0], [1, 1]], dtype=np.int32)
    zones = [Zone('a', 0., .5, 7., .6), Zone('b', .5, 1., 7., .6)]
    cfg = dict(z_axis='x', za=dict(zone_id=zone_id), zone_config=ZoneConfig(zones=zones, tpms_type='Diamond', k_s=16.),
               L=2., H=2.)
    prepared = dict(energy_dx=widths[0], energy_dy=widths[1])

    with warnings.catch_warnings(record=True) as direct_caught:
        warnings.simplefilter('always')
        wire._zone_temperatures(widths, temps, zone_id, [('a', 7., .6), ('b', 7., .6)], (2., 2.), (([.5]), ()))
    assert len(direct_caught) == 1
    assert direct_caught[0].category is RuntimeWarning
    assert str(direct_caught[0].message) == 'divide by zero encountered in divide'
    assert direct_caught[0].filename.endswith('test_native_run_ownership.py')

    with warnings.catch_warnings(record=True) as host_caught:
        warnings.simplefilter('always')
        full_2d.zone_result(cfg, prepared, temps)
    assert len(host_caught) == 1
    assert host_caught[0].category is RuntimeWarning
    assert str(host_caught[0].message) == 'divide by zero encountered in divide'
    assert Path(host_caught[0].filename).parts[-2:] == ('solvers', 'full_2d.py')

    monkeypatch.undo()

    # Verify solver-only image isolation for discrete zones, continuous zones, and experimental D-F.
    discrete_cfg = spatial.configuration(monkeypatch, tmp_path, 'x')
    native_stage_support.bound_plane_controls(discrete_cfg)
    discrete_case = prepare_case(discrete_cfg, case_id='iso-discrete')

    _, cont_case = plane._case(True, ('air', 'water'))

    exp_cfg = _configuration_fluids('Gyroid', ('air', 'water'), mode='experimental')
    exp_cfg.geometry.L_cell_mm, exp_cfg.geometry.t_wall_mm = 7., .6
    exp_cfg.geometry.L_dom_m, exp_cfg.geometry.H_dom_m = .182, .042
    exp_case = prepare_case(exp_cfg, case_id='iso-exp')

    control = RunControl(native_library=str(library_path()), cpu_threads=1)
    with monkeypatch.context() as isolated:
        isolated.setenv('TPMSHX_PREPARATION_LIBRARY', str(tmp_path / 'missing-prep'))
        isolated.setenv('TPMSHX_RESULT_LIBRARY', str(tmp_path / 'missing-result'))
        isolated.setenv('TPMSHX_GEOMETRY_LIBRARY', str(tmp_path / 'missing-geom'))
        r_disc = run_case(discrete_case, control)
        r_cont = run_case(cont_case, control)
        r_exp = run_case(exp_case, control)
    from tm1.data_types.portable_data import mutable_data
    assert r_disc.run_status['execution'] == 'completed'
    assert len(r_disc.metadata['application']['zones']['stats']) == 2
    assert r_cont.run_status['execution'] == 'completed'
    assert mutable_data(r_cont.metadata['application']['zones']) == dict(
        axis_dir='continuous', boundaries=[], boundaries_x=[], boundaries_y=[], stats=[])
    assert r_exp.run_status['execution'] == 'completed'

