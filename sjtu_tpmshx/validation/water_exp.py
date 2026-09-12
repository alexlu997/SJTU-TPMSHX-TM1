"""Pressure boundary for the explicitly confirmed water experiment workbooks."""
from pathlib import Path

from sjtu_tpmshx.models.fluid_props import check_water_state


WATER_EXPERIMENT_BOOKS = frozenset({
    'water-air_G7-t0p6_shanghai_experiment_20260401.xlsx',
    'water-air_G7-t0p6_shanghai_experiment_ports-swapped_20260407.xlsx',
    'water-air_D7-t0p6_experiment_water-straight_20260609.xlsx',
    'water-air_DG7-t0p6_hx_water-dp_with-air-temperature.xlsx',
})
WATER_P_ATM_ASSUMED_PA = 101325.0


def with_water_absolute_pressures(df, *, source, sheet, tin, tout, pin, pout):
    """Keep raw Pa gauge columns; derive absolute columns once at ingestion.

    101325 Pa is a user-approved standard-atmosphere assumption, not a
    measurement. This function is not a converter for generic runtime configs.
    """
    if Path(source).name not in WATER_EXPERIMENT_BOOKS:
        raise ValueError('water gauge convention unconfirmed for this source')
    d = df.copy()
    for endpoint, tcol, pcol in (('in', tin, pin), ('out', tout, pout)):
        d[f'water_P_{endpoint}_abs_Pa'] = d[pcol] + WATER_P_ATM_ASSUMED_PA
        check_water_state('water', d[tcol].to_numpy(float) + 273.15,
                          d[f'water_P_{endpoint}_abs_Pa'].to_numpy(float),
                          where=f'{Path(source).name}/{sheet} water {endpoint}')
    d.attrs['water_pressure'] = {
        'source': Path(source).name, 'sheet': sheet, 'raw_unit': 'Pa',
        'raw_basis': 'gauge', 'raw_in_column': pin, 'raw_out_column': pout,
        'absolute_unit': 'Pa', 'atmosphere_assumed_Pa': WATER_P_ATM_ASSUMED_PA,
        'atmosphere_measured': False,
    }
    return d
