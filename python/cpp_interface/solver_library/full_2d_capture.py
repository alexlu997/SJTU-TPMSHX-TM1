"""Map raw 2D direct-driver fields for the native solver verification tests."""
from functools import partial

import numpy as np

from sjtu_tpmshx.postprocess.result_display import describe_fields, display_fields_2d
from ..full_2d_stage import capture_result as _capture_result


def _legacy_fields(evidence, main, native):
    fields = {key: evidence[key] for key in (
        'Ta', 'Tb', 'Ts', 'P_thermal_A', 'P_thermal_B', 'P_report_A', 'P_report_B',
        'h_vA', 'h_vB', 'K_ss')}
    fields.update(display_fields_2d(main['temperature'], [flow['absolute_pressure'] for flow in native['flow']],
        [(flow['uc'], flow['vc']) for flow in native['flow']]))
    for key in ('h_vA', 'h_vB', 'K_ss'):
        fields[key] = np.broadcast_to(fields[key], np.shape(fields['Ta']))
    return fields, describe_fields(fields, 2)


capture_result = partial(_capture_result, legacy_fields=_legacy_fields)
