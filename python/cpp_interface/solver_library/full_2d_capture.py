"""Map raw 2D driver fields for standalone and archived runtimes."""
import numpy as np

from sjtu_tpmshx.postprocess.result_display import describe_fields, display_fields_2d
from ..full_2d_stage import capture_result


def _legacy_fields(evidence, main, native):
    fields = {key: evidence[key] for key in (
        'Ta', 'Tb', 'Ts', 'P_thermal_A', 'P_thermal_B', 'P_report_A', 'P_report_B',
        'h_vA', 'h_vB', 'K_ss')}
    fields.update(display_fields_2d(main['temperature'], [flow['absolute_pressure'] for flow in native['flow']],
        [(flow['uc'], flow['vc']) for flow in native['flow']]))
    for key in ('h_vA', 'h_vB', 'K_ss'):
        fields[key] = np.broadcast_to(fields[key], np.shape(fields['Ta']))
    return fields, describe_fields(fields, 2)
