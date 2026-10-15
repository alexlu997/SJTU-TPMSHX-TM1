#pragma once

#include "tpmshx/anderson_state.hpp"
#include "tpmshx/fluid_properties.hpp"
#include "tpmshx/temperature_driver.hpp"

#include <array>
#include <limits>
#include <memory>
#include <optional>
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

struct ModelHIterationOverrides {
    // Zero retains the route default, including its refined-grid budget.
    std::size_t max_iterations=0;
    double temperature_tolerance=0.,q_relative_tolerance=0.;
    bool active() const { return max_iterations || temperature_tolerance || q_relative_tolerance; }
};

struct ModelHIterationSettings {
    std::size_t max_iterations,chunk_iterations;
    double temperature_tolerance,q_relative_tolerance;
    std::size_t total_iteration_budget;
};

struct ModelHControl2D {
    std::size_t max_iterations, chunk_iterations;
    double q_relative_tolerance;
    bool warm_start = false, accelerate = false, red_black = false;
    bool (*cancel)(void*) = nullptr;
    void (*progress)(void*, std::size_t, std::size_t) = nullptr;
    void* context = nullptr;
    bool second_order_a = true, second_order_b = true;
    // FullCC uses the existing h(T) model with its own strict final-state
    // energy gate. The original model-h certificate/stopping defaults remain.
    bool strict_energy_balance = false;
    double temperature_tolerance = .01;
};

struct ModelHFinishingCheck2D {
    std::size_t iterations;
    bool passed, equations_ok;
    double energy_error_ratio = std::numeric_limits<double>::quiet_NaN();
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
    // Independent common ledger; never promotes fullCC to model-h eligibility.
    bool physical_audit_available = false;
    double energy_error_ratio = std::numeric_limits<double>::quiet_NaN();
};

enum class ModelHPhase { active, completed, cancelled, failed };

struct ModelHIterationState {
    std::array<std::vector<double>,3> temperature;
    std::vector<double> previous;
    double previous_q=0.;
    bool have_q=false;
    std::optional<ModelHChunkState> chunk;
};

struct ModelHRunState2D {
    ModelHIterationState iteration;
    ModelHResult2D result;
};

// Caller arrays remain live. The caller must not change them between calls.
// Restore requires the same input and controls. Snapshots own their arrays.
class ModelHRun2D {
public:
    ModelHRun2D(const GridView&, const ModelHFluid2D&, const ModelHFluid2D&,
                 ArrayView<const double> k_ss,
                 TemperatureStateView, const ModelHControl2D&,
                 ArrayView<const double> prescribed_b={}, PhysicalHeatLedger* physical_audit=nullptr);
    ModelHRun2D(const GridView&, const ModelHFluid2D&, const ModelHFluid2D&,
                 ArrayView<const double> k_ss,
                 TemperatureStateView, const ModelHControl2D&, const ModelHRunState2D&,
                 ArrayView<const double> prescribed_b={}, PhysicalHeatLedger* physical_audit=nullptr);
    ~ModelHRun2D();
    ModelHRun2D(const ModelHRun2D&)=delete;
    ModelHRun2D& operator=(const ModelHRun2D&)=delete;
    // Advance one complete selection, or one nonaccelerated chunk.
    ModelHPhase advance();
    ModelHPhase phase() const;
    ModelHRunState2D snapshot() const;
    ModelHResult2D take_result();
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

// Complete fixed-flow 2D model-h thermal driver, in W/m and kg/(s m).
// A -> solid -> B, with frozen-face SOU by default on both fluids.
// Serial or two-color GS, original 0.2 fluid damping, optional existing
// Anderson policy, charged chunk/trial budgets and final nonlinear audit.
// Grid requires nz==1,dz==1. Coefficients and signed full mass faces are
// caller-owned immutable inputs; state arrays must not alias each other or
// inputs. Progress/cancel callbacks must not mutate any borrowed arrays.
// No EOS, SIMPLE or outer property refresh is performed here. In particular,
// water phase checks remain the outer driver's responsibility, as in Python.
// Invalid inputs throw before state writes; arithmetic failure invalidates
// partially written state. Cancelled returns have no physical audit.
// strict_energy_balance requires actual-state error / exchange scale <=1e-7
// within the same max_iterations. Its common ledger is distinct from the
// original model-h audit. Strict SOU uses the declared physical inlet at its
// half-cell distance and one-sided outflow reconstruction; a one-cell axis
// retains FOU. The default model-h boundary reconstruction is unchanged.
// Optional prescribed B requires this strict mode;
// B is copied once, then excluded from updates, Anderson and solved equations.
// A zero-budget or cancelled strict call has no physical audit.
ModelHResult2D solve_model_h_2d(const GridView& grid, const ModelHFluid2D& a,
                              const ModelHFluid2D& b, ArrayView<const double> k_ss,
                              TemperatureStateView state, const ModelHControl2D& control,
                              ArrayView<const double> prescribed_b = {},
                              PhysicalHeatLedger* physical_audit = nullptr);

}  // namespace tpmshx
