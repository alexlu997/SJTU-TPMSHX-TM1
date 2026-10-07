"""Emit the current Python model's coefficients for native source builds.

Run from the repository root with the locked interpreter:
python -m scripts.generate_native_model_coefficients --output PATH
The generated header stays in .cache/ and introduces no runtime Python calls.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from sjtu_tpmshx.models import nu_correlations as nu, roughness
from sjtu_tpmshx.models import sco2_props, tpms_props as props
from sjtu_tpmshx.models.design_fluids import DESIGN_NU_REFERENCE_STATES
from sjtu_tpmshx.models.envelope import GAMMA_AIR, PRESSURE_FLOOR_PA, R_AIR_DEFAULT
from sjtu_tpmshx.solvers._solve_common import INLET_PRESSURE_REL_TOL
from sjtu_tpmshx.solvers._kernels_2d import MODEL_H_RELAXATION
from sjtu_tpmshx.solvers.ltne_enthalpy_3d import _ENTHALPY_BRACKET_MARGIN_K, _FL_TLO


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
    lines = [
        "// Generated from the authoritative Python models. Do not edit.",
        "// Topology table rows: Diamond, Gyroid. Nu columns: c, a[, d].",
        "#pragma once", "#include <array>", "", "namespace tpmshx::model_coefficients {",
    ]
    for name, value in (("gas_constant", props.R), ("air_molar_mass", props.M_air),
                        ("pr_air", nu.Pr_AIR), ("nu_roughness_factor", nu.NU_ROUGHNESS_FACTOR),
                        ("nu_laminar_floor", nu.NU_LAM_FLOOR),
                        ("pressure_floor_pa", PRESSURE_FLOOR_PA),
                        ("inlet_pressure_relative_tolerance", INLET_PRESSURE_REL_TOL),
                        ("envelope_r_air", R_AIR_DEFAULT),
                        ("envelope_gamma_air", GAMMA_AIR),
                        ("roughness_nu_power", roughness._NU_GAIN_POWER),
                        ("roughness_nu_baseline", nu.NU_ROUGHNESS_FACTOR),
                        ("enthalpy_bracket_margin", _ENTHALPY_BRACKET_MARGIN_K),
                        ("model_h_relaxation", MODEL_H_RELAXATION)):
        lines.append(f"inline constexpr double {name} = {float(value)!r};")
    vectors = {
        "roughness_petukhov": roughness._PETUKHOV,
        "roughness_haaland": roughness._HAALAND,
        "air_sutherland": props._AIR_SUTHERLAND,  # T0, mu0, S
        "air_conductivity": props._AIR_CONDUCTIVITY,  # k0, T0, exponent
        "model_h_air": props.model_h_coefficients("air"),  # cp0,cp1,cp2,Torigin,Tref
        "model_h_water": props.model_h_coefficients("water"),
        "water_density": props._WATER_DENSITY,  # a - b*T_C - c*T_C**2
        "water_viscosity": props._WATER_VISCOSITY,  # mu0,base,exponent,shift,floor
        "water_conductivity": props._WATER_CONDUCTIVITY,  # a + b*T_C
        "air_temperature_range": props._AIR_T_RANGE,
        "air_cp_temperature_range": props._AIR_CP_RANGE,
        "water_temperature_range": props._WATER_T_RANGE,
        "sco2_temperature_range": sco2_props.T_RANGE_K,
        "sco2_pressure_range": sco2_props.P_RANGE_PA,
        "air_nu_re_range": nu.NU_RE_FIT_RANGE,
        "water_nu_re_range": nu.WATER_NU_RE_RANGE,
        "sco2_nu_re_range": nu.SCO2_NU_RE_RANGE,
        "water_nu_reference_state": DESIGN_NU_REFERENCE_STATES["water"],  # K, Pa(abs)
        "sco2_nu_reference_state": DESIGN_NU_REFERENCE_STATES["sco2"],
        "enthalpy_temperature_lower_bounds": [_FL_TLO[fluid] for fluid in ("air", "water", "sco2")],
    }
    lines.extend(array(name, values) for name, values in vectors.items())
    lines.extend((table("nu_air", nu.NU_COEFFS, ("c", "a", "d")),
                  table("nu_water", nu.WATER_NU_COEFFS, ("c", "a")),
                  table("nu_sco2", nu.SCO2_NU_COEFFS, ("c", "a", "d"))))
    lines.append("}  // namespace tpmshx::model_coefficients\n")
    return "\n".join(lines)


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=root / ".cache/native-deps/generated/tpmshx/model_coefficients.hpp")
    target = parser.parse_args().output.resolve()
    if not target.is_relative_to(root / ".cache"):
        raise ValueError("Generated model coefficients must remain in the worktree's .cache/")
    text = header()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file() or target.read_text(encoding="utf-8") != text:
        target.write_text(text, encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
