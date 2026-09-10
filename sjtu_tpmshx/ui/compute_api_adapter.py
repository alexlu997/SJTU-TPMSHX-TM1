"""GUI worker boundary around the public-module Pipeline implementation."""


def run(config, cancel_token, progress_cb, *, pipeline_cls, ui_hooks):
    from sjtu_tpmshx.domain.cancellation import CancelledError
    from sjtu_tpmshx.controllers.compute_orchestrator import ComputeOrchestrator
    try:
        return pipeline_cls(config, progress_cb=progress_cb,
                            cancel_token=cancel_token, ui_hooks=ui_hooks).run()
    except CancelledError as exc:
        raise ComputeOrchestrator.CancelledError() from exc
