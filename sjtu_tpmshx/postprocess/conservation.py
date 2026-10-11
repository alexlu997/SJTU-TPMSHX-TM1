"""Conservation certificate shared by native finishing and offline evaluation."""
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.result_math import compute_phase2a as _compute_phase2a


def compute_phase2a(result):
    """Evaluate a prepared result or the thermal operator's certificate data."""
    if isinstance(result, FieldResult):
        result = {**result.metadata['diagnostics'],
                  '_audit_fB': result.metadata['parameters']['fluid_B_cfg'],
                  'h_vB_field': result.fields['h_vB']}
    return _compute_phase2a(result)
