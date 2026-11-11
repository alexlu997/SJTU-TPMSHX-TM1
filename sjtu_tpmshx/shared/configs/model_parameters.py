"""Read fixed model data without importing numerical implementations."""
from importlib.resources import files
import json
import math


# These versions identify the extracted V2 formulas, not experimental accuracy.
MODEL_VERSIONS = {
    'quick_design': 'v2-5f1cafb',
    'fluid': 'v2-5f1cafb',
    'co2_fluid': 'co2-fixed-factors-20261009-v1',
    'co2_geometry': 'co2-segment2-20261002-v1',
    'geometry': 'v2-5f1cafb',
    'darcy_forchheimer': 'cfd_full_core_3cell_fixed_v2',
}


_SCALARS = {
    'constants': ('gas_constant', 'air_molar_mass', 'standard_pressure_pa',
                  'celsius_zero_K', 'model_h_reference_K'),
    'water': ('cp',),
    'nu': ('pr_air', 'roughness_factor', 'laminar_floor'),
    'roughness': ('nu_gain_power',),
    'envelope': ('r_air_default', 'gamma_air', 'pressure_floor_pa'),
    'geometry': ('area_correction',),
    'co2_application': ('pressure_multiplier', 'nu_multiplier'),
    'native_controls': ('inlet_pressure_relative_tolerance', 'model_h_relaxation'),
}
_VECTORS = {
    'air': {'cp_coefficients': 3, 'sutherland': 3, 'conductivity': 3,
            'temperature_range_K': 2, 'cp_temperature_range_K': 2},
    'water': {'density': 3, 'viscosity': 5, 'conductivity': 2, 'temperature_range_K': 2},
    'nu': {'air_re_range': 2, 'water_re_range': 2, 'sco2_re_range': 2},
    'roughness': {'petukhov': 2, 'haaland': 4},
    'sco2': {'temperature_range_K': 2, 'pressure_range_Pa': 2},
    'design_nu_reference_states': {'water': 2, 'sco2': 2},
}


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')


def _vector(value, size, name):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f'{name} requires {size} coefficients')
    for item in value:
        _number(item, name)


def load_model_parameters():
    """Return a fresh model-data mapping with validated shapes and bounds."""
    data = json.loads((files('sjtu_tpmshx.shared.configs') / 'model_parameters_v1.json').read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema_version') != 'tm1_model_parameters_v1':
        raise ValueError('unsupported model parameter resource schema')
    for section in set(_SCALARS) | set(_VECTORS):
        if not isinstance(data.get(section), dict):
            raise ValueError(f'missing model parameter section: {section}')
    for section, names in _SCALARS.items():
        for name in names:
            value = data[section].get(name)
            _number(value, f'{section}.{name}')
            if value <= 0.:
                raise ValueError(f'{section}.{name} must be positive')
    for section, entries in _VECTORS.items():
        for name, size in entries.items():
            value = data[section].get(name)
            _vector(value, size, f'{section}.{name}')
            if 'range' in name and not 0. < value[0] < value[1]:
                raise ValueError(f'{section}.{name} requires increasing positive bounds')
    for name, columns in (('air_coefficients', ('c', 'a', 'd')),
                          ('water_coefficients', ('c', 'a')),
                          ('sco2_coefficients', ('c', 'a', 'd'))):
        table = data['nu'].get(name)
        if not isinstance(table, dict) or set(table) != {'Diamond', 'Gyroid'}:
            raise ValueError(f'nu.{name} requires Diamond and Gyroid')
        for topology, row in table.items():
            if not isinstance(row, dict) or set(row) != set(columns):
                raise ValueError(f'nu.{name}.{topology} requires {columns}')
            for key in columns:
                _number(row[key], f'nu.{name}.{topology}.{key}')
    for name in ('level_set_coefficients', 'solid_tortuosity'):
        table = data['geometry'].get(name)
        if not isinstance(table, dict) or set(table) != {'Diamond', 'Gyroid'}:
            raise ValueError(f'geometry.{name} requires Diamond and Gyroid')
        for topology, value in table.items():
            _vector(value, 2, f'geometry.{name}.{topology}')
    if not isinstance(data['co2_application'].get('version'), str) or not data['co2_application']['version']:
        raise ValueError('CO2 application version is required')
    return data


def load_co2_coefficients(path=None):
    """Read the existing CO2 resource, including explicitly selected test files."""
    source = (files('sjtu_tpmshx.shared.configs') / 'co2_segment2_v1.json') if path is None else path
    data = json.loads(source.read_text(encoding='utf-8'))
    if data['model_version'] != 'co2-segment2-20261002-v1' or data['segment'] != 2:
        raise ValueError('CO2 coefficient resource/version mismatch')
    if set(data['topologies']) != {'Diamond', 'Gyroid'}:
        raise ValueError('CO2 requires both supported topologies')
    bounds = data.get('bounds')
    if not isinstance(bounds, dict):
        raise ValueError('CO2 bounds are required')
    re_range = bounds.get('Re')
    _vector(re_range, 2, 'CO2 bounds.Re')
    if not 0. < re_range[0] < re_range[1]:
        raise ValueError('CO2 bounds.Re requires increasing positive bounds')
    for model in data['topologies'].values():
        theta = model['Nu']['parameters']['theta']
        try:
            valid = (isinstance(theta, list) and len(theta) == 5
                     and all(math.isfinite(float(v)) for v in theta))
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            raise ValueError('CO2 Nu requires five finite coefficients')
    return data


def load_preparation_df_parameters():
    """Read fixed preparation data without loading a numerical implementation."""
    data = json.loads((files('sjtu_tpmshx.shared.configs') / 'preparation_df_v1.json').read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or data.get('schema_version') != 'tm1_preparation_df_v1'
            or data.get('method') != 'cfd_full_core_3cell_fixed_v2'):
        raise ValueError('unsupported preparation D-F resource schema or method')
    for section, key, count in (('domain', 'L_nodes_mm', 5), ('domain', 't_nodes_mm', 4),
                                ('air_specimen', 'L_nodes_mm', 2), ('air_specimen', 't_nodes_mm', 3)):
        nodes = data[section][key]
        _vector(nodes, count, f'{section}.{key}')
        if nodes[0] <= 0. or any(a >= b for a, b in zip(nodes, nodes[1:])):
            raise ValueError(f'{section}.{key} requires increasing positive nodes')
    for value in (data['bracket_relative_tolerance'], data['hx']['geometry_absolute_tolerance_mm'],
                  data['hx']['velocity_absolute_tolerance_mps']):
        _number(value, 'preparation D-F tolerance')
        if value <= 0.:
            raise ValueError('preparation D-F tolerances must be positive')
    _vector(data['hx']['geometry_mm'], 2, 'HX geometry')
    if any(value <= 0. for value in data['hx']['geometry_mm']):
        raise ValueError('HX geometry must be positive')
    for topology in ('Diamond', 'Gyroid'):
        rows = data['air_specimen']['sf'][topology]
        if not isinstance(rows, list) or len(rows) != 2:
            raise ValueError('air specimen factors require two length rows')
        for row in rows:
            _vector(row, 3, 'air specimen factors')
            if any(value <= 0. for value in row):
                raise ValueError('air specimen factors must be positive')
    for fluid in ('air', 'water', 'sco2'):
        for topology in ('Diamond', 'Gyroid'):
            factor = data['hx']['sf'][fluid][topology]
            _number(factor, 'HX factor')
            if factor <= 0.:
                raise ValueError('HX factors must be positive')
            for name in ('calibration_u_mps', 'application_u_mps', 'runtime_u_mps'):
                bounds = data['hx'][name][fluid][topology]
                _vector(bounds, 2, f'HX {name}')
                if not 0. < bounds[0] < bounds[1]:
                    raise ValueError(f'HX {name} requires increasing positive bounds')
    if not isinstance(data['hx']['application_scope'], str) or not data['hx']['application_scope']:
        raise ValueError('HX application scope is required')
    calibration = data['hx']['gyroid_air_calibration']
    if not isinstance(calibration, dict) or not calibration or any(
            not isinstance(value, str) or not value for value in calibration.values()):
        raise ValueError('Gyroid air calibration data require nonempty text')
    return data
