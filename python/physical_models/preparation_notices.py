"""Report inlet and geometry observations from the preparation model."""
from sjtu_tpmshx.run_control.run_warnings import _range_context, current_warnings, merge_warnings


def range_notices(key, record, cached, scalar, *, records=None):
    """Replay source records and the original standalone warning filters."""
    stage = key[-1][1]
    if key[-1] == ('unbound', 'unbound', 'source'):
        key = (*key[:-1], _range_context.get())
    merge_warnings(current_warnings(), [{key: record}])
    merge_warnings(records, [{key[:-1]: record}])
    if cached or current_warnings() is not None or scalar is None:
        return ()
    from sjtu_tpmshx.physical_models import tpms_props, nu_correlations, co2_correlations
    source = key[:-2]
    if source[0] == 'property':
        notice = tpms_props._range_notice(source[1], scalar, scalar, *record.bounds)
        return () if notice is None else (notice,)
    elif source[0] in ('nu', 'nu_pr') and stage in ('inlet', 'unbound'):
        fluid, topology = source[1:]
        if fluid == 'air':
            notices = nu_correlations._extrap_notices(topology, scalar, scalar)
        elif fluid == 'water':
            notices = nu_correlations._water_nu_notices(scalar, scalar, topology)
        elif fluid == 'sco2':
            notices = nu_correlations._sco2_nu_notices(scalar, scalar, topology)
        else:
            notices = ([co2_correlations._calibration_notice(record.quantity, record.bounds)]
                       if scalar < record.bounds[0] or scalar > record.bounds[1] else [])
        return notices
    return ()
