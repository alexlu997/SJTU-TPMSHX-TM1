#pragma once

#include "tpmshx/fluid_properties.hpp"
#include "tpmshx/temperature_driver.hpp"

#include <array>

namespace tpmshx {

enum class QuickDesignArrangement { cross, counter };
enum class QuickDesignProperties { constant, mean };

class QuickDesignWaterFieldError : public WaterStateError {
public:
    using WaterStateError::WaterStateError;
};

struct QuickDesignGeometry {
    double length, span, height, cell_length, area_density, hydraulic_diameter;
    ArrayView<const double> epsilon, epsilon_a, k_ss;
};

struct QuickDesignSide {
    Fluid fluid;
    double inlet_temperature, inlet_pressure, mass_flow;
    // Already prepared by the inlet-state analytic D-F model. Never updated
    // by a mean-property pass; values >= 1 retain the existing choked result.
    double inlet_pressure_fraction;
};

struct QuickDesignControl {
    // Resolved existing budgets; the caller resolves Python's None values.
    std::size_t max_iterations, chunk_iterations;
    double q_relative_tolerance, alpha;
    bool warm_start = false;
    bool (*cancel)(void*) = nullptr;
    void (*progress)(void*, unsigned percent) = nullptr;
    void* context = nullptr;
};

struct QuickDesignPassSide {
    double evaluation_temperature;
    FluidProperties properties;
    double reynolds, speed, hv, conductivity;
};

struct QuickDesignPass {
    std::array<QuickDesignPassSide,2> sides;
    TemperatureResult thermal;
};

struct QuickDesignPressure {
    double inlet, outlet;
    bool choked;
};

struct QuickDesignResult {
    TemperatureStop stop;
    std::size_t completed_passes;
    std::array<QuickDesignPass,2> passes;
    std::array<QuickDesignPressure,2> pressure;
};

// Complete prepared plug-LTNE property-pass execution. const executes one
// pass; mean executes exactly two and seeds pass 2 with the full pass-1 fields.
// The next evaluation T is (Tin + arithmetic outlet-face mean)/2, preserving
// the current QD policy. All returned water fields are checked at side inlet P
// after each pass, before reuse or success; an external warm field is checked
// before the first pass. Inlet errors and field errors retain distinct types.
// Fields are borrowed C-order state arrays. Final uniform K/hv/velocity fields
// are represented by the last pass's scalar coefficients and arrangement;
// no hidden property recomputation is needed by a future result adapter.
// No geometry, drag fitting, pressure solve, production binding, range-warning
// framework or physical-validation certificate is provided by this function.
QuickDesignResult solve_quick_design(
    const GridView& grid, const QuickDesignGeometry& geometry,
    Topology topology, QuickDesignArrangement arrangement,
    QuickDesignProperties property_mode, const QuickDesignSide& a,
    const QuickDesignSide& b, TemperatureStateView state,
    const QuickDesignControl& control);

}  // namespace tpmshx
