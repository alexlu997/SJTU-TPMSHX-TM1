"""Conservation certificate for a prepared public result."""
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.result_math import compute_phase2a as _compute_phase2a


def compute_phase2a(result: FieldResult):
    """Evaluate the recorded thermal certificate of a FieldResult."""
    return _compute_phase2a({**result.metadata['diagnostics'],
                            '_audit_fB': result.metadata['parameters']['fluid_B_cfg'],
                            'h_vB_field': result.fields['h_vB']})
