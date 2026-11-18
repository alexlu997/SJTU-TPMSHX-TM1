#pragma once

#include "tpmshx/finite_volume.hpp"
#include "tpmshx/grid.hpp"
#include <array>

namespace tpmshx::preparation {

struct FlowValues {
    ArrayView<const double> values;
    std::uint32_t precision, strong;
};
struct ClosureRatio {
    std::vector<double> values;
    grid::Scalar kind;
};

grid::Scalar inlet_capacity_2d(FlowValues epsilon_total, FlowValues opening,
    FlowValues geometric, FlowValues widths, grid::Scalar rho, grid::Scalar depth);
grid::Scalar inlet_capacity_3d(FlowValues epsilon_side, const std::array<std::size_t,3>& shape,
    std::int32_t direction, FlowValues widths1, FlowValues widths2, FlowValues opening, grid::Scalar rho);
grid::Scalar inlet_speed(grid::Scalar target, grid::Scalar capacity);
std::array<grid::Scalar,4> quick_design_sections(grid::Scalar epsilon_side, grid::Scalar width,
    grid::Scalar length, grid::Scalar height, bool cross);
std::array<grid::Scalar,2> quick_design_flow(grid::Scalar mass_flow, grid::Scalar area,
    grid::Scalar density, bool air);
grid::Scalar relative_pressure(grid::Scalar pressure_drop, grid::Scalar inlet_pressure);
grid::Scalar design_temperature_target(grid::Scalar inlet_temperature, bool has_delta,
    grid::Scalar delta, grid::Scalar duty, grid::Scalar mass_flow, grid::Scalar heat_capacity);
grid::Scalar design_cooling_proxy(grid::Scalar hot, grid::Scalar cold,
    grid::Scalar target, grid::Scalar mass_flow);
bool cooling_proxy_needs_target(grid::Scalar hot, grid::Scalar cold);
grid::Scalar design_volume(grid::Scalar width, grid::Scalar height, grid::Scalar length);
ClosureRatio closure_geometry_ratio(FlowValues hydraulic_diameter_m, FlowValues cell_length_mm);

}  // namespace tpmshx::preparation
