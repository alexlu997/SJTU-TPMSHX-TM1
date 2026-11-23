#pragma once

#include "tpmshx/finite_volume.hpp"
#include <array>
#include <vector>

namespace tpmshx::preparation {

using FlowValues=ArrayView<const double>;

// Scalar quotients reject a zero divisor. Array element quotients keep IEEE results.
double inlet_capacity_2d(FlowValues epsilon_total, FlowValues opening,
    FlowValues geometric, FlowValues widths, double rho, double depth);
double inlet_capacity_3d(FlowValues epsilon_side, const std::array<std::size_t,3>& shape,
    std::int32_t direction, FlowValues widths1, FlowValues widths2, FlowValues opening, double rho);
double inlet_speed(double target, double capacity);
std::array<double,4> quick_design_sections(double epsilon_side, double width,
    double length, double height, bool cross);
std::array<double,2> quick_design_flow(double mass_flow, double area, double density, bool air);
double relative_pressure(double pressure_drop, double inlet_pressure);
double design_temperature_target(double inlet_temperature, bool has_delta,
    double delta, double duty, double mass_flow, double heat_capacity);
double design_cooling_proxy(double hot, double cold, double target, double mass_flow);
bool cooling_proxy_needs_target(double hot, double cold);
double design_volume(double width, double height, double length);
std::vector<double> closure_geometry_ratio(FlowValues hydraulic_diameter_m, FlowValues cell_length_mm);

}  // namespace tpmshx::preparation
