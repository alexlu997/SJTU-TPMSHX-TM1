"""Keep saved offset and discrete runs equal to the existing full 2D driver."""
import ctypes as ct
from dataclasses import replace
import json

import numpy as np
import pytest

from sjtu_tpmshx.preprocess.api import prepare_case
from tests.python import test_native_run_adapter as adapter
from tests.python import test_native_prepare_spatial_adapter as spatial
from tests.python.test_native_prepare_adapter import _same
from sjtu_tpmshx.file_io.case_io import load_case, save_case
from sjtu_tpmshx.cpp_interface import full_2d_stage as stage
from sjtu_tpmshx.cpp_interface import preparation_host
from tests.python import native_stage_support
from tests.python import result_stage_fixture


def _case(monkeypatch, tmp_path, mode='uniform', pair=('air', 'air'), delta=.1):
    config = (native_stage_support.plane_configuration(pair) if mode == 'uniform' else
              spatial.configuration(monkeypatch, tmp_path, mode))
    native_stage_support.bound_plane_controls(config)
    config.geometry.delta_levelset = delta
    return prepare_case(config, case_id='offset-run')


def _saved(case):
    """Pack the saved v5 case as the production run does."""
    driver = stage.StageDriver(adapter.library_path())
    checked = preparation_host.borrow_solver_mesh(case, driver.library, 2)
    shape = stage.execution_grid(case, None if checked is None else checked.shape)
    entries = stage._stage_entries(driver.library)
    cfg, prepared, experiment = stage.saved_inputs(case, shape, checked_geometry=checked is not None,
        check_experiment=entries['check_experiment'], port_windows_fit=entries['port_windows_fit'])
    prepared['solver_mesh'] = checked
    saved, _, keepalive = stage.pack_saved(case, cfg, prepared, experiment)
    request, energy = stage._request(cfg, driver.library)
    control = stage._Control(b'offset-run', None, 2)
    return saved, request, control, (keepalive, energy)


def _report(case, result):
    from sjtu_tpmshx.solvers.applicability_evidence import capture_applicability
    from sjtu_tpmshx.solvers.execution_record import full_execution_record
    enriched = replace(result, metadata=dict(result.metadata,
        execution_record=full_execution_record(case, result),
        applicability_evidence=capture_applicability(case, result, {})))
    value = result_stage_fixture.python_report(enriched)
    value['source_result_id'] = case.case_id
    value['qualification']['source_result_id'] = case.case_id
    return value


@pytest.mark.parametrize('mode,pair,delta', [
    *[('uniform', pair, delta) for pair in (('air', 'air'), ('air', 'water'), ('water', 'air'), ('water', 'water'))
      for delta in (-.1, .1)],
    *[(mode, ('air', 'air'), delta) for mode in ('x', 'y', 'grid', 'sigmoid') for delta in (-.1, 0., .1)],
])
def test_complete_offset_and_discrete_result(monkeypatch, tmp_path, mode, pair, delta):
    case = _case(monkeypatch, tmp_path, mode, pair, delta)
    if mode in ('grid', 'sigmoid'):
        save_case(case, tmp_path / 'case.h5')
        case = load_case(tmp_path / 'case.h5')
    reports = []
    query_view = stage.executed_view
    def capture(query, result):
        evidence = ct.cast(ct.pointer(result.evidence), ct.POINTER(result_stage_fixture.Evidence)).contents
        reports.append(native_stage_support.evaluate_evidence(evidence))
        assert result.evidence.thermal_mode == b'temperature'
        assert result.evidence.temperature_transport == b'model_enthalpy_temperature_v1'
        assert not result.evidence.thermal.model_h
        assert result.evidence.model_certificate_count == 0
        return query_view(query, result)
    monkeypatch.setattr(stage, 'executed_view', capture)
    actual = adapter._compare(case, tmp_path, monkeypatch)
    expected = _report(case, actual)
    _same(reports[0], expected, 'native evaluation')
    (tmp_path / 'native-report.json').write_text(json.dumps(reports[0]))
    (tmp_path / 'reference-report.json').write_text(json.dumps(expected))


@pytest.mark.parametrize('mode', ['uniform', 'x', 'grid', 'sigmoid'])
def test_offset_snapshot_restore_keeps_exact_inputs(monkeypatch, tmp_path, mode):
    case = _case(monkeypatch, tmp_path, mode)
    snapshots = []
    class Paused(Exception):
        pass
    def pause(snapshot):
        snapshots.append(snapshot)
        raise Paused
    for run in (adapter._old, stage.run_case):
        with pytest.raises(Paused):
            run(case, adapter._control([]), checkpoint=pause)
    native_stage_support.plane_state_equal(snapshots[1], snapshots[0])
    for key in ('input.asymmetric', 'input.split_a', 'input.spatial_geometry', 'input.thermal_mode'):
        assert key in snapshots[1]
    expected = adapter._old(case, adapter._control([]), resume_state=snapshots[0])
    actual = stage.run_case(case, adapter._control([]), resume_state=snapshots[1])
    actual = adapter._checked_applicability(actual, expected, case)
    _same(replace(actual, result_id=expected.result_id), expected)
    np.savez(tmp_path / 'state.npz', **snapshots[1])


@pytest.mark.parametrize('failure', ['abi', 'size', 'flag', 'mode', 'missing-sides', 'bad-side', 'cell-extent'])
def test_saved_v5_rejects_invalid_descriptor(monkeypatch, tmp_path, failure):
    case = _case(monkeypatch, tmp_path, 'grid')
    saved, request, control, keepalive = _saved(case)
    if failure == 'abi':
        saved.abi_version = 1
    elif failure == 'size':
        saved.struct_size -= 1
    elif failure == 'flag':
        saved.have_side_geometry = 2
    elif failure == 'mode':
        saved.prepared.contents.input.geometry_mode = 3
    elif failure == 'missing-sides':
        saved.have_side_geometry = 0
    elif failure == 'bad-side':
        saved.side_geometry[1][2] = float('nan')
    else:
        saved.prepared.contents.cell_length.size -= 1
    library = ct.CDLL(str(adapter.library_path()))
    with pytest.raises(ValueError):
        stage._Run(library, saved, request, control, [], None)
    del keepalive


@pytest.mark.parametrize('operation', ['create', 'restore'])
@pytest.mark.parametrize('target', ['descriptor', 'side-geometry', 'field'])
@pytest.mark.parametrize('output_alias', [False, True])
def test_saved_v5_diagnostic_and_output_aliases(monkeypatch, tmp_path, operation, target, output_alias):
    case = _case(monkeypatch, tmp_path, 'grid')
    saved, request, control, keepalive = _saved(case)
    library = ct.CDLL(str(adapter.library_path()))
    function = getattr(library, 'tpmshx_stage_run_2d_' + operation + '_saved_v5')
    from sjtu_tpmshx.cpp_interface.run_state import _Field
    common = [ct.POINTER(stage._Saved), ct.POINTER(stage._Request), ct.POINTER(stage._Control)]
    if operation == 'restore':
        common += [ct.POINTER(_Field), ct.c_size_t]
    function.argtypes = [*common, ct.POINTER(ct.c_void_p), ct.POINTER(ct.c_char), ct.c_size_t]
    function.restype = ct.c_int
    if target == 'descriptor':
        address, size = ct.addressof(saved), ct.sizeof(saved)
    elif target == 'side-geometry':
        address, size = ct.addressof(saved.side_geometry), ct.sizeof(saved.side_geometry)
    else:
        field = saved.prepared.contents.cell_length
        address, size = ct.cast(field.data, ct.c_void_p).value, field.size * 8
    before = ct.string_at(address, size)
    handle, error = ct.c_void_p(), ct.create_string_buffer(b'preserved', 256)
    arguments = [ct.byref(saved), ct.byref(request), ct.byref(control)]
    if operation == 'restore':
        arguments += [None, 0]
    output = ct.cast(address, ct.POINTER(ct.c_void_p)) if output_alias else ct.byref(handle)
    message = error if output_alias else ct.cast(address, ct.POINTER(ct.c_char))
    assert function(*arguments, output, message, len(error) if output_alias else size) == 1
    assert ct.string_at(address, size) == before
    assert error.value == b'preserved' and not handle.value
    del keepalive


def test_saved_v5_transfer_protects_side_geometry(monkeypatch, tmp_path):
    case = _case(monkeypatch, tmp_path)
    saved, request, control, keepalive = _saved(case)
    library = ct.CDLL(str(adapter.library_path()))
    with stage._Run(library, saved, request, control, [], None) as run:
        result = stage._StageResult()
        before, empty = bytes(saved), bytes(result)
        error = ct.cast(saved.side_geometry, ct.POINTER(ct.c_char))
        assert run._take_result(run.handle, ct.byref(result), error, ct.sizeof(saved.side_geometry)) == 1
        assert bytes(saved) == before and bytes(result) == empty
        assert run.phase not in (3, 4, 5)
    del keepalive
