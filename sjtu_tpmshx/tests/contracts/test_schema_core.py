import importlib
import inspect
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.metric_spec import MetricSpec
from sjtu_tpmshx.domain.model_refs import ModelRef
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.performance_result import MetricValue, PerformanceResult


def test_case_snapshot_and_result_fields_are_detached_and_read_only():
    config = ComputeConfig()
    source_grid = {"x_m": np.array([0.0, 1.0])}
    case = CaseData.from_compute_config("case-1", config, grid=source_grid)
    result = FieldResult("result-1", case.case_id, "python", fields=source_grid)

    config.geometry.L_dom_m = 9.0
    source_grid["x_m"][0] = 7.0

    assert case.config_snapshot["geometry"]["L_dom_m"] == 0.182
    assert case.grid["x_m"][0] == result.fields["x_m"][0] == 0.0
    with pytest.raises(ValueError):
        result.fields["x_m"][0] = 2.0
    with pytest.raises(ValueError):
        result.fields["x_m"].setflags(write=True)
    with pytest.raises(TypeError):
        case.metadata["changed"] = True


@pytest.mark.parametrize('kind', ['case', 'result'])
def test_metadata_update_reuses_immutable_storage_with_independent_array_headers(kind):
    source = np.arange(12., dtype='>f8').reshape(3, 4)
    if kind == 'case':
        original = CaseData('case', design_fields={'values': source})
        name = 'design_fields'
    else:
        original = FieldResult('result', 'case', 'python', fields={'values': source})
        name = 'fields'
    updated = replace(original, metadata={'warnings': ['new warning']})
    before, after = (getattr(record, name)['values'] for record in (original, updated))
    assert before is not after
    assert np.shares_memory(before, after)
    np.testing.assert_array_equal(after, source)
    assert after.dtype == before.dtype
    for value in (before, after):
        with pytest.raises(ValueError):
            value.setflags(write=True)
        with pytest.raises(ValueError):
            value[0, 0] = -1
    after.shape = (12,)
    after.dtype = '<f8'
    assert before.shape == (3, 4)
    assert before.dtype == np.dtype('>f8')
    assert original.metadata == {}


@pytest.mark.parametrize('backing', ['array', 'bytearray'])
def test_readonly_facade_of_mutable_storage_is_still_detached(backing):
    source = np.arange(8.)
    if backing == 'array':
        readonly = source.view()
        readonly.flags.writeable = False
    else:
        owner = bytearray(source.tobytes())
        source = np.frombuffer(owner, dtype=float)
        readonly = np.frombuffer(memoryview(owner).toreadonly(), dtype=float)
    case = CaseData('case', design_fields={'values': readonly})
    frozen = case.design_fields['values']
    assert not np.shares_memory(frozen, source)
    source[:] = -1.
    np.testing.assert_array_equal(frozen, np.arange(8.))


def test_array_subclass_cannot_claim_mutable_storage_is_frozen():
    class MutableOwner(np.ndarray):
        @property
        def base(self):
            return bytes(self.nbytes)

    owner = np.ndarray.__new__(MutableOwner, (8,), dtype=float)
    owner[:] = np.arange(8.)
    readonly = owner.view(np.ndarray)
    readonly.flags.writeable = False
    frozen = CaseData('case', design_fields={'values': readonly}).design_fields['values']
    owner[:] = -1.
    np.testing.assert_array_equal(frozen, np.arange(8.))
    with pytest.raises(ValueError):
        frozen.setflags(write=True)


def test_bytes_subclass_cannot_hide_a_large_parent_buffer():
    class ParentBytes(bytes):
        def __len__(self):
            return 8

    owner = ParentBytes(np.arange(1024.).tobytes())
    source = np.frombuffer(owner, dtype=float)[:1]
    frozen = CaseData('case', design_fields={'values': source}).design_fields['values']
    assert not np.shares_memory(frozen, source)
    np.testing.assert_array_equal(frozen, source)


@pytest.mark.parametrize('view', ['small_slice', 'transpose'])
def test_immutable_views_keep_compact_contiguous_contract_storage(view):
    original = CaseData('large', design_fields={'values': np.arange(1024.).reshape(32, 32)})
    source = original.design_fields['values']
    values = source[:1, :] if view == 'small_slice' else source.T
    reduced = CaseData('reduced', design_fields={'values': values}).design_fields['values']
    assert not np.shares_memory(reduced, source)
    assert reduced.flags.c_contiguous
    np.testing.assert_array_equal(reduced, values)


def test_performance_result_keeps_explicit_insufficient_data_status():
    metric = MetricValue(None, MetricSpec("PEC", "1"), "insufficient_data", "reference definition missing")
    result = PerformanceResult("performance-1", "result-1", {"PEC": metric})
    assert result.metrics["PEC"].status == "insufficient_data"
    assert result.metrics["PEC"].value is None


def test_case_data_rejects_a_runtime_callback():
    with pytest.raises(TypeError, match="callables"):
        CaseData("case-1", metadata={"callback": lambda: None})


def test_schema_identity_required_fields_and_core_units_are_checked():
    with pytest.raises(ValueError, match="case_id"):
        CaseData("")
    with pytest.raises(ValueError, match="unsupported"):
        FieldResult("result-1", "case-1", "python", schema_version="v2")
    assert MetricSpec("Q", "W/m").unit == "W/m"
    assert MetricSpec("Q", "W").unit == "W"
    with pytest.raises(ValueError, match="must use"):
        MetricSpec("Q", "J")


def test_contract_imports_do_not_pull_ui_solver_or_optimizer_layers():
    for name in (
        "sjtu_tpmshx.domain.case_data",
        "sjtu_tpmshx.domain.field_result",
        "sjtu_tpmshx.domain.metric_spec",
        "sjtu_tpmshx.domain.performance_result",
        "sjtu_tpmshx.domain.module_ports",
    ):
        source = inspect.getsource(importlib.import_module(name))
        assert "PySide6" not in source
        assert "sjtu_tpmshx.ui" not in source
        assert "sjtu_tpmshx.solvers" not in source
        assert "sjtu_tpmshx.optimization" not in source


def test_runtime_values_cannot_hide_inside_arrays_models_or_results():
    callback = lambda: None
    with pytest.raises(TypeError, match="objects"):
        CaseData("case-1", grid={"x": np.array([callback], dtype=object)})
    with pytest.raises(TypeError, match="runtime"):
        ModelRef("fluid", "v1", {"nested": [callback]})
    with pytest.raises(TypeError, match="runtime"):
        FieldResult("r", "c", "python", metadata={"callback": callback})
    with pytest.raises(TypeError, match="ModelRef"):
        CaseData("case-1", model_refs=[{"callback": callback}])
    with pytest.raises(TypeError, match="keys"):
        CaseData("case-1", metadata={callback: "hidden in a key"})


def test_nonfinite_diagnostics_are_preserved_but_not_available_metrics():
    result = FieldResult("r", "c", "python", run_status={"residual": float("nan")})
    assert np.isnan(result.run_status["residual"])
    with pytest.raises(ValueError, match="finite"):
        MetricValue(float("nan"), MetricSpec("Q", "W"))


def test_run_control_keeps_callbacks_outside_persisted_data_and_propagates_errors():
    seen = []
    control = RunControl(progress=seen.append, cancel_check=lambda: True)
    control.report_progress(20)
    assert seen == [20]
    with pytest.raises(CancelledError):
        control.check_cancelled()

    def broken_callback():
        raise RuntimeError("callback failure")

    with pytest.raises(RuntimeError, match="callback failure"):
        RunControl(cancel_check=broken_callback).check_cancelled()
