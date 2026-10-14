"""Record selected original domains from authoritative prepared inputs."""
from sjtu_tpmshx.domain.run_warnings import range_context, record_range
from sjtu_tpmshx.df_surrogate._domain import TRAIN_L_NODES, TRAIN_T_NODES


def record_geometry_ranges(case):
    if case.metadata.get('mode', 'full') != 'full':
        return
    with range_context(side='shared', stage='prepared-geometry', layout='physical-cell'):
        for field, nodes, quantity in (
                ('L_field_m', TRAIN_L_NODES, 'cell length'),
                ('t_field_m', TRAIN_T_NODES, 'wall thickness')):
            values = case.design_fields.get(field)
            if values is not None:
                record_range(('geometry', field), values * 1e3, (nodes[0], nodes[-1]),
                             label='fixed geometry domain', quantity=quantity, unit='mm')
