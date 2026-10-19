#pragma once

#include "tpmshx/finite_volume.hpp"

#include <cstdint>

namespace tpmshx {

struct FluidView {
    // Cell arrays, C order (i * ny + j) * nz + k.
    ArrayView<const double> dh;       // epsilon * conductivity / cp
    ArrayView<const double> cp;       // J/(kg K), frozen for this Picard step
    ArrayView<const double> t_star;   // K, frozen Picard linearization state
    ArrayView<const double> h_star;   // J/kg, at the same state as t_star
    ArrayView<const double> hv;       // W/(m^3 K), exchange per total volume
    // Signed mass flow (kg/s), positive along the real coordinate axis.
    // Shapes: (nx+1,ny,nz), (nx,ny+1,nz), (nx,ny,nz+1); zero = wall.
    ArrayView<const double> mass_x, mass_y, mass_z;
    double h_in;          // J/kg; inward faces use h_in
};

struct ClipCounts {
    std::uint64_t a, b;
};

struct FluidEnergyView {
    // Actual EOS state, not the frozen linearization used by the sweeps.
    ArrayView<const double> h, temperature, hv, conductivity;
    ArrayView<const double> mass_x, mass_y, mass_z;
    double h_in;
};

struct EnergyAudit {
    double q_a, q_b;  // signed inward boundary enthalpy power, W
    double net, solid_abs_sum, denominator, coupled_ratio;
    double fluid_abs_sum[2], fluid_cell_max[2], equation_ratio;
    bool fluid_equations_computed;
};

// Unrelaxed residuals: conduction + exchange - div(m*h); adiabatic exterior.
// Outputs are W/cell (W/m for a unit-depth 2D extrusion). Inputs and outputs
// must not alias. Actual temperatures/conductivities must come from the same
// final EOS state as h; this operator neither evaluates EOS nor certifies it.
// No acceptance threshold is applied. Invalid inputs throw before output writes;
// arithmetic overflow throws std::domain_error and invalidates all outputs.
// With fluid_equations=false, conductivity is neither read nor validated;
// fluid residual arrays/metrics and equation_ratio are filled with NaN and
// fluid_equations_computed=false. Boundary/solid/coupled evidence is unchanged.
EnergyAudit thermal_energy_audit(const GridView& grid, const FluidEnergyView& a,
                                const FluidEnergyView& b,
                                ArrayView<const double> t_s,
                                ArrayView<const double> k_ss,
                                ArrayView<double> residual_a,
                                ArrayView<double> residual_b,
                                ArrayView<double> residual_s,
                                bool fluid_equations = true);

}  // namespace tpmshx
