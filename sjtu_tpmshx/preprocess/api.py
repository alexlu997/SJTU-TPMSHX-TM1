"""Public physical preparation entry point; no numerical backend import."""
from dataclasses import replace

from sjtu_tpmshx.domain.run_warnings import warning_scope, warning_messages


def prepare_case(config, *, case_id):
    if config.is_3d:
        from .three_d.preparation import prepare_case as prepare
    else:
        from .two_d.preparation import prepare_case as prepare
    with warning_scope({}) as records:
        case = prepare(config, case_id=case_id)
    return replace(case, metadata={**case.metadata, 'warnings': tuple(warning_messages(records))})
