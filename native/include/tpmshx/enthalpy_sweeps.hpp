#pragma once

#include <cstddef>
#include <cstdint>

namespace tpmshx {

// Borrowed contiguous storage; the caller retains ownership for the whole call.
template <typename T> struct ArrayView {
    T* data;
    std::size_t size;
    T& operator[](std::size_t index) const { return data[index]; }
};

struct GridView {
    std::size_t nx, ny, nz;
    ArrayView<const double> dx, dy, dz;  // m; positive cell widths
};

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
    double h_in, h_lo, h_hi;          // J/kg; inward faces use h_in
};

struct ThermalStateView {
    ArrayView<double> h_a, h_b;       // J/kg, updated in place
    ArrayView<double> t_s;            // K, updated in place
};

struct ClipCounts {
    std::uint64_t a, b;
};

// Same serial A -> B -> solid / i -> j -> k order as the Python true-h kernel.
// Kss is solid effective conductivity, W/(m K); outside faces are adiabatic.
// Storage must not alias mutable fields or immutable input fields. No EOS,
// mass balancing, convergence decision, case preparation or result reduction.
// Invalid extents/nonfinite inputs/nonphysical coefficients throw before update.
// Arithmetic overflow throws std::domain_error; state may be partially updated
// and must not be consumed after that exception.
// n_sweeps == 0 leaves the fields unchanged and returns zero clip counts.
ClipCounts enthalpy_sweeps(const GridView& grid, const FluidView& a,
                          const FluidView& b, ArrayView<const double> k_ss,
                          ThermalStateView state, std::size_t n_sweeps,
                          double omega);

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
};

// Unrelaxed residuals: conduction + exchange - div(m*h); adiabatic exterior.
// Outputs are W/cell (W/m for a unit-depth 2D extrusion). Inputs and outputs
// must not alias. Actual temperatures/conductivities must come from the same
// final EOS state as h; this operator neither evaluates EOS nor certifies it.
// No acceptance threshold is applied. Invalid inputs throw before output writes;
// arithmetic overflow throws std::domain_error and invalidates all outputs.
EnergyAudit thermal_energy_audit(const GridView& grid, const FluidEnergyView& a,
                                const FluidEnergyView& b,
                                ArrayView<const double> t_s,
                                ArrayView<const double> k_ss,
                                ArrayView<double> residual_a,
                                ArrayView<double> residual_b,
                                ArrayView<double> residual_s);

}  // namespace tpmshx
