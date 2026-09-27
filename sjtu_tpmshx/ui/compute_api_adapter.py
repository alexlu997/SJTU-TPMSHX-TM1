"""GUI worker boundary around the public-module Pipeline implementation."""


def run(config, cancel_token, progress_cb, *, pipeline_cls, ui_hooks):
    return pipeline_cls(config, progress_cb=progress_cb,
                        cancel_token=cancel_token, ui_hooks=ui_hooks).run()
