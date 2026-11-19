"""Independent preparation formulas frozen before batch4 native extraction.

Source: preprocess/inlet_flow.py and shared/models/quick_design.py at fda946ad.
These references do not call production geometry, property or DF evaluators.
"""
import numpy as np


def capacity_2d(epsilon, opening, geometric, widths, rho, depth):
    epsilon = np.asarray(epsilon, dtype=np.float64) * .5
    scale = 1.0
    if np.any(opening != geometric):
        geometric_area = float(np.sum(geometric * widths))
        profile_area = float(np.sum(opening * widths))
        if profile_area > 1e-30 and geometric_area > 0.0:
            scale = geometric_area / profile_area
    return rho * float(np.sum(epsilon * opening * widths)) * depth * scale


def capacity_3d(epsilon, direction, widths1, widths2, opening, rho):
    epsilon = np.take(epsilon, -1 if direction % 2 else 0, axis=direction // 2)
    area = np.asarray(widths1)[:, None] * np.asarray(widths2)[None, :]
    return rho * float(np.sum(epsilon * opening * area))


def quick_design_sections(epsilon, width, length, height, cross):
    area_hot = epsilon * width * height
    if cross:
        area_cold, length_cold = epsilon * length * height, width
    else:
        area_cold, length_cold = epsilon * width * height, length
    return area_hot, length, area_cold, length_cold


def side_flow(mdot, area, rho, air):
    flux = mdot / area
    return flux, None if air else flux / rho


def temperature_target(temperature, delta, duty, mass_flow, heat_capacity):
    return temperature - delta if delta is not None else temperature - duty / (mass_flow * heat_capacity)


def cooling_proxy(hot, cold, target, mass_flow):
    denominator = hot - cold
    required = (hot - target) / denominator if abs(denominator) > 1e-9 else 0.0
    return required * mass_flow


def volume(width, height, length):
    return width * height * length


def legacy_air_fields(geometry, speed, rho, mu, conductivity, nu):
    diameter = geometry['r_h_arr'] * 2.0
    reynolds = np.maximum(rho * speed * diameter / mu, 10.0)
    surface = nu * conductivity / diameter
    return reynolds, surface * geometry['A_0_arr'], geometry['eps_f_arr'] * conductivity


def closure_geometry_ratio(diameter_m, cell_mm):
    return diameter_m * 1000. / cell_mm
