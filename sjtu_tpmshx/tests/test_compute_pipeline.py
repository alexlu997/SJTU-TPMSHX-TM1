"""Tests for ``controllers/compute_pipeline.py`` — audit C4 ABC.

Covers the ABC contract independently of the 2D / 3D implementations:

- ``ComputeResult`` default construction
- ``ComputePipeline`` cancel + progress fires in order
- ``CancelledError`` raised on truthy cancel token
- ``pipeline_for(cfg)`` dim dispatch by ``cfg.is_3d``
- ``Pipeline2D`` / ``Pipeline3D`` instantiate without invoking the
  public preparation, solve and postprocessing APIs

The concrete 2D / 3D pipelines are covered by their own integration
tests (``test_pipeline_2d_smoke.py`` etc.).
"""
from __future__ import annotations

import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig, SolverConfig
from sjtu_tpmshx.controllers.compute_pipeline import (
    CancelledError,
    ComputePipeline,
    ComputeResult,
    Pipeline2D,
    Pipeline3D,
    pipeline_for,
)


# ── ComputeResult ───────────────────────────────────────────────────


def test_compute_result_defaults_are_zero_or_empty():
    """Empty constructor must not raise; numbers default to zero, dicts
    + lists default empty so downstream JSON serialisers don't blow up."""
    r = ComputeResult()
    assert r.Q_W == 0.0
    assert r.dP_A_Pa == 0.0
    assert r.dP_B_Pa == 0.0
    assert r.T_out_A_K == 0.0
    assert r.T_out_B_K == 0.0
    assert r.fields == {}
    assert r.coeffs == {}
    assert r.props == {}
    assert r.residuals == {}
    assert r.zones is None
    assert r.warnings == []
    assert r.extrap_reasons == []
    assert r.diagnostics == {}


def test_compute_result_independent_default_dicts():
    """``field(default_factory=dict)`` must give each instance its own
    dict, not a shared class-level singleton."""
    a = ComputeResult()
    b = ComputeResult()
    a.fields['foo'] = 1
    assert 'foo' not in b.fields


# ── ABC harness ─────────────────────────────────────────────────────


class _RecordingPipeline(ComputePipeline):
    """Stub pipeline that records the order phases ran in."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []
        self.progress_calls = []
        # Re-wire so we record both the user cb and our own observation.
        _orig_cb = self.progress_cb
        def _record_cb(pct):
            self.progress_calls.append(pct)
            _orig_cb(pct)
        self.progress_cb = _record_cb

    def build_fields(self):
        self.calls.append('build_fields')
        return {'stub': 'fields'}

    def run_solvers(self, fields):
        self.calls.append('run_solvers')
        assert fields == {'stub': 'fields'}
        return {'stub': 'raw'}

    def finalize(self, raw, fields):
        self.calls.append('finalize')
        assert raw == {'stub': 'raw'}
        assert fields == {'stub': 'fields'}
        return ComputeResult(Q_W=42.0)


def test_pipeline_run_calls_phases_in_order():
    cfg = ComputeConfig()
    pipe = _RecordingPipeline(cfg)
    result = pipe.run()
    assert result.Q_W == 42.0
    assert pipe.calls == ['build_fields', 'run_solvers', 'finalize']


def test_pipeline_progress_cb_fires_20_90_100():
    cfg = ComputeConfig()
    pipe = _RecordingPipeline(cfg)
    pipe.run()
    assert pipe.progress_calls == [20, 90, 100]


def test_pipeline_progress_cb_default_is_noop():
    """No explicit ``progress_cb`` → ``run()`` must not raise."""
    cfg = ComputeConfig()
    pipe = _RecordingPipeline(cfg)
    pipe.run()  # should not raise


def test_pipeline_times_phases_without_between_phase_progress_callbacks(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr('sjtu_tpmshx.controllers.compute_pipeline.perf_counter',
                        lambda: clock[0])

    class TimedPipeline(_RecordingPipeline):
        def build_fields(self):
            clock[0] += 1.0
            return super().build_fields()

        def run_solvers(self, fields):
            clock[0] += 2.0
            return super().run_solvers(fields)

        def finalize(self, raw, fields):
            clock[0] += 3.0
            result = super().finalize(raw, fields)
            result.metadata['units'] = {'Q': 'W'}
            return result

    def progress(_percent):
        clock[0] += 100.0

    result = TimedPipeline(ComputeConfig(), progress_cb=progress).run()
    assert result.metadata['timings_s'] == {
        'prepare': 1.0, 'solve': 2.0, 'postprocess': 3.0}
    assert result.metadata['units'] == {'Q': 'W'}
    assert result.Q_W == 42.0


class _CancelToken:
    def __init__(self):
        self.cancelled = False


def test_pipeline_cancel_at_start_raises():
    cfg = ComputeConfig()
    tok = _CancelToken()
    tok.cancelled = True
    pipe = _RecordingPipeline(cfg, cancel_token=tok)
    with pytest.raises(CancelledError):
        pipe.run()
    assert pipe.calls == []


def test_pipeline_cancel_between_phases_raises():
    cfg = ComputeConfig()
    tok = _CancelToken()

    class _MidCancel(_RecordingPipeline):
        def build_fields(self):
            tok.cancelled = True  # cancel after phase 1
            return super().build_fields()

    pipe = _MidCancel(cfg, cancel_token=tok)
    with pytest.raises(CancelledError):
        pipe.run()
    assert pipe.calls == ['build_fields']


def test_pipeline_no_cancel_token_runs_clean():
    cfg = ComputeConfig()
    pipe = _RecordingPipeline(cfg, cancel_token=None)
    r = pipe.run()
    assert r.Q_W == 42.0


def test_abstract_methods_enforced():
    """Instantiating ``ComputePipeline`` itself must raise."""
    with pytest.raises(TypeError):
        ComputePipeline(ComputeConfig())  # type: ignore[abstract]


# ── Pipeline2D / Pipeline3D / pipeline_for ──────────────────────────


def test_pipeline2d_can_be_constructed_with_cfg():
    """Constructor must not invoke the not-yet-implemented runs helpers;
    those only fire on ``.run()``."""
    cfg = ComputeConfig()
    pipe = Pipeline2D(cfg)
    assert pipe.cfg is cfg


def test_pipeline3d_can_be_constructed_with_cfg():
    cfg = ComputeConfig()
    pipe = Pipeline3D(cfg)
    assert pipe.cfg is cfg


def test_pipeline_for_returns_2d_when_not_is_3d():
    cfg = ComputeConfig(solver=SolverConfig(Nz=1))
    pipe = pipeline_for(cfg)
    assert isinstance(pipe, Pipeline2D)


def test_pipeline_for_returns_3d_when_is_3d():
    cfg = ComputeConfig(solver=SolverConfig(Nz=5))
    pipe = pipeline_for(cfg)
    assert isinstance(pipe, Pipeline3D)


def test_pipeline_for_passes_progress_and_cancel():
    cfg = ComputeConfig()
    tok = _CancelToken()
    seen = []
    pipe = pipeline_for(cfg, progress_cb=lambda p: seen.append(p),
                        cancel_token=tok)
    assert pipe.cancel is tok
    # progress_cb is stored even on the concrete subclass
    pipe.progress_cb(33)
    assert seen == [33]
