#pragma once

#include "tpmshx/simple_convergence.hpp"

#include <memory>
#include <optional>

namespace tpmshx {

struct Simple2DMaterialView {
    ArrayView<const double> epsilon, viscosity, effective_viscosity, permeability, forchheimer;
    ArrayView<const double> temperature;  // fixed within this SIMPLE call, K
};

struct Simple2DStateView {
    ArrayView<double> u, v, pressure, pressure_correction, d_u, d_v, density;
    ArrayView<double> inlet_velocity;  // nx; BC still multiplies inlet_fraction
};

struct Simple2DBoundaryView {
    ArrayView<const double> inlet_fraction, outlet_u_fraction;
    double reference_inlet_velocity, taper_flux_scale = 1.;
    std::optional<double> inlet_density_reference;
};

struct Simple2DControl {
    // All numerical settings are resolved by the caller, including the
    // current Python defaults. No second physical-constant registry lives here.
    std::size_t max_iterations, inner_sweeps;
    double alpha_velocity, alpha_pressure, alpha_density;
    double pressure_reference_absolute, gas_constant, cf_anisotropy;
    bool ideal_gas = true, massflux_inlet = true, close_outlet_on_exit = true;
    SimpleF2Control convergence;
    bool (*cancel)(void*) = nullptr;
    void (*progress)(void*, std::size_t, double) = nullptr;  // iteration, old-rho legacy residual
    void* context = nullptr;
};

struct Simple2DResult {
    SimpleStop stop = SimpleStop::ongoing;
    bool converged = false, post_closure_measured = false, post_closure_certified = false;
    std::size_t iterations = 0, pressure_clip_hits = 0;
    double legacy_residual = std::numeric_limits<double>::quiet_NaN();
    SimpleMomentumResidual momentum;
    SimpleMassAudit mass{std::numeric_limits<double>::quiet_NaN(), 0., 0.,
        std::numeric_limits<double>::quiet_NaN(), 0., 0};
    PressureResult linear;  // most recent PPE evidence; x lives in state.pressure_correction
};

// Same serial SOU/Darcy-Forchheimer equations as the Python 2D kernel.
// Exposed separately for equation/predictor qualification. No pressure solve,
// density update or convergence decision is hidden in these two operators.
void simple_2d_predictor(const GridView& grid, ArrayView<const unsigned char> outlet_open,
                         const Simple2DMaterialView& material,
                         const Simple2DBoundaryView& boundary, Simple2DStateView state,
                         double alpha_velocity, std::size_t sweeps, double cf_anisotropy);
SimpleMomentumResidual simple_2d_momentum_residual(
    const GridView& grid, const Simple2DMaterialView& material,
    const Simple2DBoundaryView& boundary, Simple2DStateView state, double cf_anisotropy);

// One prepared grid/port support per instance; constructor owns width/support
// copies and the canonical PPE cache. State/coefficient arrays remain borrowed
// during solve. No geometry, D-F surrogate, EOS backend, thermal solve, outer
// pressure shooting or physical acceptance is performed here.
// Persistent target and histories survive warm solves; each call resets F2
// confirmation/stall snapshots, matching SIMPLESolver.solve. Initial nonfinite
// state and numerical nonfinite iterates return failure with their evidence.
// Cancellation occurs once before each SIMPLE iteration. Failed/cancelled
// state can be partial and must not be published as an accepted solution.
class Simple2DSolver {
public:
    Simple2DSolver(const GridView& grid, ArrayView<const unsigned char> outlet_open);
    ~Simple2DSolver();
    Simple2DSolver(const Simple2DSolver&) = delete;
    Simple2DSolver& operator=(const Simple2DSolver&) = delete;
    Simple2DResult solve(const Simple2DMaterialView& material,
                        const Simple2DBoundaryView& boundary, Simple2DStateView state,
                        const Simple2DControl& control);
    const SimpleHistory& history() const;
    std::optional<double> massflux_target() const;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace tpmshx
