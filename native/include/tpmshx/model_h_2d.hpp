#pragma once

#include "tpmshx/fluid_properties.hpp"
#include "tpmshx/temperature_driver.hpp"

#include <array>
#include <vector>

namespace tpmshx {

struct ModelHFluid2D {
    Fluid fluid;  // air or water, from the authoritative generated cp model
    ArrayView<const double> conductivity, hv, mass_x, mass_y;
    TemperatureBoundary boundary;  // capacity_flux must be empty: use mass faces
};

struct ModelHSideAudit2D {
    double q_advective, inlet_conduction, exchange;
    double residual_sum, residual_max, linearized_sum, linearized_max;
    double defect_sum, defect_max, mass_net, mass_local_max, mass_in, mass_out;
    double normalization, cell_ratio;
    std::size_t unknown_inflow_faces;
    std::array<std::vector<double>, 4> boundary_mass_out, boundary_h_out;
    std::array<std::vector<double>, 2> h_faces;
    std::vector<double> inlet_conduction_faces, residual, linearization_defect;
    std::array<double, 5> cp_coefficients;
};

struct ModelHAudit2D {
    std::array<ModelHSideAudit2D, 2> sides;
    std::vector<double> solid_residual;
    double solid_sum, solid_max, solid_cell_ratio, residual_sum, telescoping_error;
    double net_boundary_in, denominator, energy_imbalance, solid_imbalance;
    bool boundary_complete, finite, energy_ok, solid_ok, equations_ok, passed;
};

struct ModelHControl2D {
    std::size_t max_iterations, chunk_iterations;
    double q_relative_tolerance;
    bool warm_start = false, accelerate = false, red_black = false;
    bool (*cancel)(void*) = nullptr;
    void (*progress)(void*, std::size_t, std::size_t) = nullptr;
    void* context = nullptr;
};

struct ModelHFinishingCheck2D {
    std::size_t iterations;
    bool passed, equations_ok;
};

struct ModelHResult2D {
    TemperatureStop stop;
    std::size_t iterations;
    double residual, q_b;
    bool audit_available;
    ModelHAudit2D audit;
    std::vector<ModelHFinishingCheck2D> finishing_checks;
    // Last actual GS linearization, including restoration after rejected trials.
    std::vector<double> last_a, last_b;
};

// Complete fixed-flow 2D model-h thermal driver, in W/m and kg/(s m).
// All cells are solved; A -> solid -> B, both fluids use frozen-face SOU.
// Serial or two-color GS, original 0.2 fluid damping, optional existing
// Anderson policy, charged chunk/trial budgets and final nonlinear audit.
// Grid requires nz==1,dz==1. Coefficients and signed full mass faces are
// caller-owned immutable inputs; state arrays must not alias each other or
// inputs. Progress/cancel callbacks must not mutate any borrowed arrays.
// No EOS, SIMPLE or outer property refresh is performed here. In particular,
// water phase checks remain the outer driver's responsibility, as in Python.
// Invalid inputs throw before state writes; arithmetic failure invalidates
// partially written state. Cancelled returns have no physical audit.
ModelHResult2D solve_model_h_2d(const GridView& grid, const ModelHFluid2D& a,
                              const ModelHFluid2D& b, ArrayView<const double> k_ss,
                              TemperatureStateView state, const ModelHControl2D& control);

}  // namespace tpmshx
