"""Historical Pipeline API, now a sequence of the three public modules."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace
from time import perf_counter
from typing import Any, Callable, Dict, Optional

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.compute_result import ComputeResult
from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.run_warnings import warning_scope, warning_messages


# ── Pipeline ABC ─────────────────────────────────────────────────────


ProgressFn = Callable[[int], None]


class ComputePipeline(ABC):
    """3-phase abstract pipeline driven by :class:`ComputeConfig`.

    Parameters
    ----------
    cfg : ComputeConfig
        Strict-typed compute settings.  Built at the UI boundary via
        ``ui.window_config.config_from_window`` or from JSON via
        :meth:`ComputeConfig.from_json`.
    progress_cb : callable, optional
        Single-argument ``(percent: int)`` callback fired at 20 / 90 /
        100 %.  Default no-op.
    cancel_token : object, optional
        Any object with a ``cancelled`` attribute that resolves to a
        bool.  Checked before each phase; truthy value raises
        :class:`CancelledError`.
    control : RunControl, optional
        Host backend/library selection and runtime callbacks. GUI progress,
        iteration hooks and cancellation are combined with these callbacks;
        the controls are not saved in portable cases or results.

    Subclass contract
    -----------------

    Concrete pipelines exchange CaseData and FieldResult through the public
    module APIs. ``finalize(raw, fields)`` evaluates the native result and
    maps it to the existing :class:`ComputeResult` display contract.
    """

    def __init__(self, cfg: ComputeConfig,
                 progress_cb: Optional[ProgressFn] = None,
                 cancel_token: Optional[Any] = None,
                 ui_hooks: Optional[Dict[str, Any]] = None, *,
                 control: RunControl = RunControl()) -> None:
        self.cfg = cfg
        self.progress_cb: ProgressFn = progress_cb or (lambda _pct: None)
        self.cancel = cancel_token
        self.control = control
        # Optional GUI iteration callbacks; solver residuals stay in RunControl.
        self.ui_hooks: Dict[str, Any] = ui_hooks or {}

    def _check_cancel(self) -> None:
        self.control.check_cancelled()
        if self.cancel is None:
            return
        if getattr(self.cancel, 'cancelled', False):
            raise CancelledError("Pipeline cancelled by user")

    def run(self) -> ComputeResult:
        """Drive the 3 phases + cancel checks + progress ticks."""
        # Config validation (2026-07-13, codex review): `validate()` used to
        # run ONLY on the from_dict/from_json factory paths — every direct
        # dataclass construction (gate scripts, goldens, tests, scripted
        # callers) bypassed it, so illegal F2 tolerances / grid combos went
        # straight into the solvers. The pipeline is the chokepoint every
        # run passes through; validate here, fail loud before solving.
        with warning_scope({}) as records:
            self.cfg.validate()
            self._check_cancel()
            started = perf_counter()
            fields = self.build_fields()
            timings = {'prepare': perf_counter() - started}
            self.progress_cb(20)
            self._check_cancel()
            started = perf_counter()
            raw = self.run_solvers(fields)
            timings['solve'] = perf_counter() - started
            self.progress_cb(90)
            self._check_cancel()
            started = perf_counter()
            result = self.finalize(raw, fields)
            timings['postprocess'] = perf_counter() - started
            result.metadata['timings_s'] = timings
            self._check_cancel()
            self.progress_cb(100)
            for message in warning_messages(records):
                if message not in result.warnings:
                    result.warnings.append(message)
            return result

    # ── subclass hooks ──────────────────────────────────────────────

    @abstractmethod
    def build_fields(self) -> CaseData:
        """Phase 1: prepared physical data."""

    @abstractmethod
    def run_solvers(self, fields: CaseData) -> FieldResult:
        """Phase 2: execute prepared data and return native evidence."""

    @abstractmethod
    def finalize(self, raw: FieldResult,
                 fields: CaseData) -> ComputeResult:
        """Phase 3: assemble :class:`ComputeResult` from raw output."""


# ── 2D / 3D concrete implementations ─────────────────────────────────


class Pipeline2D(ComputePipeline):
    """Prepare CaseData, execute it, then map evaluated native results."""

    dimension = 2

    def build_fields(self) -> CaseData:
        from uuid import uuid4
        from sjtu_tpmshx.preprocess.api import prepare_case
        if self.cfg.is_3d != (self.dimension == 3):
            raise ValueError(f'{type(self).__name__} requires a {self.dimension}D config')
        return prepare_case(self.cfg, case_id=str(uuid4()))

    def run_solvers(self, fields: CaseData) -> FieldResult:
        from sjtu_tpmshx.solvers.api import run_case
        def progress(percent):
            self.progress_cb(20 + int(.7 * percent))
            self.control.report_progress(percent)
        def cancelled():
            return bool(getattr(self.cancel, 'cancelled', False) or
                        (self.control.cancel_check is not None and self.control.cancel_check()))
        def with_ui_hook(name, callback):
            hook = self.ui_hooks.get(name)
            if hook is None:
                return callback
            if callback is None:
                return hook
            def report(*args):
                hook(*args)
                callback(*args)
            return report
        control = replace(self.control, progress=progress, cancel_check=cancelled,
            iteration=with_ui_hook('iter_label_cb', self.control.iteration),
            outer_iteration=with_ui_hook('iter_cb', self.control.outer_iteration))
        return run_case(fields, control)

    def finalize(self, raw: FieldResult, fields: CaseData) -> ComputeResult:
        from sjtu_tpmshx.postprocess.api import evaluate
        from sjtu_tpmshx.controllers.module_adapter import to_compute_result
        return to_compute_result(raw, evaluate(raw))


class Pipeline3D(Pipeline2D):
    """The same public workflow with explicit 3D input validation."""

    dimension = 3


def pipeline_for(cfg: ComputeConfig,
                 progress_cb: Optional[ProgressFn] = None,
                 cancel_token: Optional[Any] = None,
                 ui_hooks: Optional[Dict[str, Any]] = None, *,
                 control: RunControl = RunControl()) -> ComputePipeline:
    """Dim-dispatch factory: return :class:`Pipeline3D` if ``cfg.is_3d``,
    otherwise :class:`Pipeline2D`.

    Convenience wrapper for adapters / scripts that do not know upfront
    whether the cfg represents a 2D or 3D run.
    """
    cls = Pipeline3D if cfg.is_3d else Pipeline2D
    return cls(cfg, progress_cb=progress_cb, cancel_token=cancel_token,
               ui_hooks=ui_hooks, control=control)


__all__ = [
    'ComputeResult',
    'ComputePipeline',
    'Pipeline2D',
    'Pipeline3D',
    'CancelledError',
    'pipeline_for',
]
