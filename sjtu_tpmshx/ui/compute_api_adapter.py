"""GUI worker boundary around the public-module Pipeline implementation."""
from sjtu_tpmshx.domain.module_ports import RunControl


def run(config, cancel_token, progress_cb, *, pipeline_cls, ui_hooks, control=RunControl()):
    return pipeline_cls(config, progress_cb=progress_cb,
                        cancel_token=cancel_token, ui_hooks=ui_hooks, control=control).run()
