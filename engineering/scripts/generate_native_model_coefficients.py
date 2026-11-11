"""Emit shared model data for native source builds.

Run from the repository root with the locked interpreter:
python -m engineering.scripts.generate_native_model_coefficients --output PATH
The generated header stays in .cache/ and introduces no runtime Python calls.
"""
from __future__ import annotations

import argparse
import csv
from importlib.resources import files
import math
import json
from pathlib import Path

from sjtu_tpmshx.shared.configs.model_parameters import (
    MODEL_VERSIONS, load_co2_coefficients, load_model_parameters, load_preparation_df_parameters)


def array(name, values):
    values = tuple(values)
    literals = ", ".join(repr(float(value)) for value in values)
    return f"inline constexpr std::array<double, {len(values)}> {name}{{{{{literals}}}}};"


def table(name, coefficients, columns):
    rows = ["{{" + ", ".join(repr(float(coefficients[topology][key])) for key in columns) + "}}"
            for topology in ("Diamond", "Gyroid")]
    return (f"inline constexpr std::array<std::array<double, {len(columns)}>, 2> {name}{{{{\n"
            + ",\n".join("    " + row for row in rows) + "\n}};")


def header():
    parameters = load_model_parameters()
    constants, nu = parameters['constants'], parameters['nu']
    roughness, air = parameters['roughness'], parameters['air']
    water, sco2 = parameters['water'], parameters['sco2']
    envelope, controls = parameters['envelope'], parameters['native_controls']
    states, co2 = parameters['design_nu_reference_states'], load_co2_coefficients()
    lines = [
        "// Generated from shared model data resources. Do not edit.",
        "// Topology table rows: Diamond, Gyroid. Nu columns: c, a[, d].",
        "#pragma once", "#include <array>", "", "namespace tpmshx::model_coefficients {",
    ]
    lines.extend(f"inline constexpr char {name}_version[] = {json.dumps(version)};"
                 for name, version in MODEL_VERSIONS.items())
    for name, value in (("gas_constant", constants['gas_constant']),
                        ("air_molar_mass", constants['air_molar_mass']),
                        ("pr_air", nu['pr_air']), ("nu_roughness_factor", nu['roughness_factor']),
                        ("nu_laminar_floor", nu['laminar_floor']),
                        ("co2_nu_multiplier", parameters['co2_application']['nu_multiplier']),
                        ("pressure_floor_pa", envelope['pressure_floor_pa']),
                        ("inlet_pressure_relative_tolerance", controls['inlet_pressure_relative_tolerance']),
                        ("envelope_r_air", envelope['r_air_default']),
                        ("envelope_gamma_air", envelope['gamma_air']),
                        ("roughness_nu_power", roughness['nu_gain_power']),
                        ("roughness_nu_baseline", nu['roughness_factor']),
                        ("model_h_relaxation", controls['model_h_relaxation'])):
        lines.append(f"inline constexpr double {name} = {float(value)!r};")
    vectors = {
        "roughness_petukhov": roughness['petukhov'],
        "roughness_haaland": roughness['haaland'],
        "air_sutherland": air['sutherland'],  # T0, mu0, S
        "air_conductivity": air['conductivity'],  # k0, T0, exponent
        "model_h_air": (*air['cp_coefficients'], constants['celsius_zero_K'],
                        constants['model_h_reference_K']),
        "model_h_water": (water['cp'], 0., 0., constants['celsius_zero_K'],
                          constants['model_h_reference_K']),
        "water_density": water['density'],  # a - b*T_C - c*T_C**2
        "water_viscosity": water['viscosity'],  # mu0,base,exponent,shift,floor
        "water_conductivity": water['conductivity'],  # a + b*T_C
        "air_temperature_range": air['temperature_range_K'],
        "air_cp_temperature_range": air['cp_temperature_range_K'],
        "water_temperature_range": water['temperature_range_K'],
        "sco2_temperature_range": sco2['temperature_range_K'],
        "sco2_pressure_range": sco2['pressure_range_Pa'],
        "air_nu_re_range": nu['air_re_range'],
        "water_nu_re_range": nu['water_re_range'],
        "sco2_nu_re_range": nu['sco2_re_range'],
        "co2_nu_re_range": co2['bounds']['Re'],
        "co2_nu_pr_range": co2['bounds']['Pr'],
        "water_nu_reference_state": states['water'],  # K, Pa(abs)
        "sco2_nu_reference_state": states['sco2'],
    }
    lines.extend(array(name, values) for name, values in vectors.items())
    lines.extend((table("nu_air", nu['air_coefficients'], ("c", "a", "d")),
                  table("nu_water", nu['water_coefficients'], ("c", "a")),
                  table("nu_sco2", nu['sco2_coefficients'], ("c", "a", "d"))))
    co2_theta = {topology: dict(enumerate(model['Nu']['parameters']['theta']))
                 for topology, model in co2['topologies'].items()}
    lines.append(table('nu_co2', co2_theta, range(5)))
    geometry = parameters['geometry']
    lines.append(f"inline constexpr double geometry_area_correction = {geometry['area_correction']!r};")
    for key, name in (('level_set_coefficients', 'geometry_level_set'),
                      ('solid_tortuosity', 'geometry_solid_tortuosity')):
        rows = {topology: dict(enumerate(values)) for topology, values in geometry[key].items()}
        lines.append(table(name, rows, range(2)))
    node_rows = []
    for topology in ('Diamond', 'Gyroid'):
        nodes = co2['topologies'][topology]['geometry_nodes']
        rows = ["    {{" + ", ".join(repr(float(node[key])) for key in (
            'L_mm', 't_mm', 'epsilon_single', 'Dh_m', 'A0_single_per_m')) + "}}"
                for node in nodes]
        node_rows.append("{{\n" + ",\n".join(rows) + "\n}}")
    lines.append("inline constexpr std::array<std::array<std::array<double, 5>, 20>, 2> co2_geometry_nodes{{\n"
                 + ",\n".join(node_rows) + "\n}};")
    lines.append("}  // namespace tpmshx::model_coefficients\n")
    return "\n".join(lines)


def nested_array(name, values, shape):
    def literal(value):
        if isinstance(value, (list, tuple)):
            return '{' + ', '.join(literal(item) for item in value) + '}'
        return repr(float(value))
    dimensions = ''.join(f'[{size}]' for size in shape)
    return f'inline constexpr double {name}{dimensions} = {literal(values)};'


def df_header(csv_path=None):
    data = load_preparation_df_parameters()
    lengths, walls = data['domain']['L_nodes_mm'], data['domain']['t_nodes_mm']
    topologies, fluids = ('Diamond', 'Gyroid'), ('air', 'water', 'sco2')
    tables = {topology: {} for topology in topologies}
    source = (files('sjtu_tpmshx.shared.df_surrogate') / '_prebuilt' / (data['method'] + '.csv')
              if csv_path is None else csv_path)
    with source.open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        if not {'tp', 'L_mm', 't_mm', 'K_m2', 'cF_fixed_1_m'}.issubset(reader.fieldnames or ()):
            raise ValueError('fixed sCO2 CFD coefficient schema mismatch')
        for row in reader:
            topology = row['tp']
            if topology not in tables:
                raise ValueError(f'unsupported TPMS topology: {topology!r}')
            key = (float(row['L_mm']), float(row['t_mm']))
            values = (float(row['K_m2']), float(row['cF_fixed_1_m']))
            if key in tables[topology]:
                raise ValueError(f'duplicate fixed sCO2 CFD node: {topology} {key}')
            if key[0] not in lengths or key[1] not in walls:
                raise ValueError(f'off-grid fixed sCO2 CFD node: {topology} {key}')
            if not all(math.isfinite(value) and value > 0. for value in values):
                raise ValueError(f'invalid fixed sCO2 CFD coefficients: {topology} {key}')
            tables[topology][key] = values
    expected = {(length, wall) for length in lengths for wall in walls}
    if any(set(table) != expected for table in tables.values()):
        raise ValueError('fixed sCO2 CFD coefficient grid is incomplete')
    fixed = [[[tables[topology][length, wall] for wall in walls] for length in lengths]
             for topology in topologies]
    specimen, hx = data['air_specimen'], data['hx']
    parameters = load_model_parameters()
    lines = ['// Generated from fixed preparation resources. Do not edit.', '#pragma once',
             '#include <array>', '', 'namespace tpmshx::preparation::df_data {',
             f'inline constexpr char method[] = "{data["method"]}";',
             array('df_L_nodes', lengths), array('df_t_nodes', walls),
             nested_array('df_values', fixed, (2, 5, 4, 2)),
             array('air_L_nodes', specimen['L_nodes_mm']), array('air_t_nodes', specimen['t_nodes_mm']),
             nested_array('air_sf', [specimen['sf'][topology] for topology in topologies], (2, 2, 3)),
             array('hx_geometry_mm', hx['geometry_mm']),
             nested_array('hx_sf', [[hx['sf'][fluid][topology] for topology in topologies]
                                     for fluid in fluids], (3, 2))]
    for name in ('calibration_u', 'application_u', 'runtime_u'):
        values = [[hx[name+'_mps'][fluid][topology] for topology in topologies] for fluid in fluids]
        lines.append(nested_array(name, values, (3, 2, 2)))
    for name, value in (
            ('df_bracket_relative_tolerance', data['bracket_relative_tolerance']),
            ('hx_geometry_absolute_tolerance', hx['geometry_absolute_tolerance_mm']),
            ('hx_velocity_absolute_tolerance', hx['velocity_absolute_tolerance_mps']),
            ('co2_pressure_multiplier', parameters['co2_application']['pressure_multiplier']),
            ('r_air_default', parameters['envelope']['r_air_default'])):
        lines.append(f'inline constexpr double {name} = {float(value)!r};')
    lines.append('}  // namespace tpmshx::preparation::df_data\n')
    return '\n'.join(lines)


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=root / ".cache/native-deps/generated/tpmshx/model_coefficients.hpp")
    parser.add_argument('--df-output', type=Path)
    args = parser.parse_args()
    targets = [(args.output.resolve(), header)]
    if args.df_output is not None:
        targets.append((args.df_output.resolve(), df_header))
    for target, build_header in targets:
        if not target.is_relative_to(root / '.cache'):
            raise ValueError("Generated model coefficients must remain in the worktree's .cache/")
    for target, build_header in targets:
        text = build_header()
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.read_text(encoding='utf-8') != text:
            target.write_text(text, encoding='utf-8')
        print(target)


if __name__ == "__main__":
    main()
