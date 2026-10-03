#pragma once

#include "tpmshx/enthalpy_eos.hpp"
#include "tpmshx/enthalpy_sweeps.hpp"

#include <array>
#include <optional>
#include <string>

namespace tpmshx {

struct EnthalpySideView {
    Fluid fluid;
    double inlet_temperature, inlet_pressure;
    ArrayView<const double> pressure, epsilon, hv;
    ArrayView<const double> mass_x, mass_y, mass_z;
};

struct EnthalpyStateView {
    ArrayView<double> h_a, h_b, a, b, solid;
    // Supplied temperature fields are optional independently, as in Python.
    bool warm_a = false, warm_b = false, warm_solid = false;
};

struct EnthalpyControl {
    std::size_t max_iterations, sweeps;
    double omega, update_tolerance;
    std::optional<double> coupled_energy_tolerance, equation_energy_tolerance;
    std::string table_directory;
    bool (*cancel)(void*) = nullptr;
    void* context = nullptr;
};

enum class EnthalpyStop { converged, enthalpy_limited, iteration_limit, cancelled };

struct EnthalpyResult {
    EnthalpyStop stop;
    std::size_t iterations;
    double residual, q_a, q_b, energy_imbalance;
    std::array<double,2> inlet_enthalpy;
    ClipCounts last_clips, total_clips;
    // Present when either exact-EOS gate was requested. Full unrelaxed audit
    // remains evidence; only the requested gates affect convergence.
    std::optional<EnergyAudit> final_audit;
    std::array<bool,2> used_bicubic;
    bool heos_polish;
};

// Full true-h Picard driver for 3D or a unit-depth nz=1 2D extrusion. Input
// mass faces and local pressures are already prepared; no flow correction,
// SIMPLE, h_v refresh or model-h transport is performed here. All EOS, frozen
// property chunks, clipping, old convergence gates and requested exact-EOS
// finishing gates are inside this call. Inlet h uses scalar inlet pressure;
// cell EOS uses the supplied local pressure. A failed final exact-EOS audit
// continues permanently with HEOS within the same original iteration budget.
// Caller-owned arrays are borrowed and non-aliasing. An exception invalidates
// partially updated output fields; cancelled output is not a completed solve.
EnthalpyResult solve_enthalpy(const GridView& grid, const EnthalpySideView& a,
                             const EnthalpySideView& b, ArrayView<const double> k_ss,
                             EnthalpyStateView state, const EnthalpyControl& control);

}  // namespace tpmshx
