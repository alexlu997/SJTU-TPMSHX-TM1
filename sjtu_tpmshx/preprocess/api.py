"""Public physical preparation entry point; no numerical backend import."""
from dataclasses import replace

from sjtu_tpmshx.domain.run_warnings import warning_scope, warning_messages
from sjtu_tpmshx.domain.provenance import source_context


def prepare_case(config, *, case_id):
    if config.is_3d:
        from .three_d.preparation import prepare_case as prepare
    else:
        from .two_d.preparation import prepare_case as prepare
    provenance = source_context()
    with warning_scope({}) as records:
        case = prepare(config, case_id=case_id)
    return replace(case, metadata={**case.metadata, 'provenance': provenance, 'warnings': tuple(dict.fromkeys((*case.metadata.get('warnings', ()), *warning_messages(records))))})


def prepare_quick_design(*args, **kwargs):
    """Explicit prescribed-velocity design mode; no SIMPLE substitution."""
    from .app_modes.quick_design import prepare_quick_design as prepare
    provenance = source_context()
    with warning_scope({}) as records:
        case = prepare(*args, **kwargs)
    return replace(case, metadata={**case.metadata, 'provenance': provenance, 'warnings': tuple(dict.fromkeys((*case.metadata.get('warnings', ()), *warning_messages(records))))})


def prepare_screening_2d(*args, **kwargs):
    """Prepare the existing air/air continuous-field optimization model."""
    from .app_modes.screening_2d import prepare_screening_2d as prepare
    provenance = source_context()
    with warning_scope({}) as records:
        case = prepare(*args, **kwargs)
    return replace(case, metadata={**case.metadata, 'provenance': provenance, 'warnings': tuple(dict.fromkeys((*case.metadata.get('warnings', ()), *warning_messages(records))))})


def prepare_screening_3d(*args, **kwargs):
    """Prepare the existing frozen-B 3D screening model."""
    from .app_modes.screening_3d import prepare_screening_3d as prepare
    provenance = source_context()
    with warning_scope({}) as records:
        case = prepare(*args, **kwargs)
    return replace(case, metadata={**case.metadata, 'provenance': provenance, 'warnings': tuple(dict.fromkeys((*case.metadata.get('warnings', ()), *warning_messages(records))))})
