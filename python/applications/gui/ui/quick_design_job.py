"""Run Quick Design and publish the inputs and results of that job."""
from __future__ import annotations

from dataclasses import replace
import sys
from time import perf_counter

from PySide6.QtCore import QThread, Signal

from sjtu_tpmshx.run_control.cancellation import CancelledError


class QuickDesignJob(QThread):
    finished_with_result = Signal(object)
    error_signal = Signal(str)
    cancelled = Signal()

    def __init__(self, params, *, control):
        super().__init__()
        self.params = params
        self.control = control
        # The desktop bundle has no loky subprocess entry point.
        self.n_jobs = 1 if getattr(sys, 'frozen', False) else -1

    def run(self):
        started = perf_counter()
        results = []
        case_limits = []

        def cancelled():
            return self.isInterruptionRequested() or (
                self.control.cancel_check is not None and self.control.cancel_check())

        def publish(reason, best):
            feasible = [design for design in results if design.feasible]
            if reason != 'completed':
                best = min(feasible, key=lambda design: design.V, default=None)
            self.finished_with_result.emit({
                'feasible': feasible, 'all': results, 'best': best, 'params': self.params,
                'termination_reason': reason, 'partial': reason != 'completed',
                'case_limits': case_limits, 'elapsed_s': perf_counter() - started,
            })

        try:
            from sjtu_tpmshx.applications.design.cases import load_cases
            from sjtu_tpmshx.applications.design.workflow import run_design

            control = replace(self.control, cancel_check=cancelled)
            control.check_cancelled()
            options = self.params.copy()
            cases = load_cases(options.pop('file'))
            case_limits = [dict(case=case.case, dPlim_h=case.dPlim_h, dPlim_c=case.dPlim_c)
                           for case in cases]
            results, best = run_design(cases, **options, n_jobs=self.n_jobs,
                                       control=control, completed=results)
            publish('completed', best)
        except CancelledError:
            publish('cancelled', None)
            self.cancelled.emit()
        except Exception as error:
            if results:
                publish('failed', None)
            self.error_signal.emit(f'{type(error).__name__}: {error}')
