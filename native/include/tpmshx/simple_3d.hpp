#pragma once

#include "tpmshx/simple_convergence.hpp"

#include <memory>

namespace tpmshx {

struct Simple3DMaterialView {
    ArrayView<const double> epsilon, viscosity, effective_viscosity, permeability, forchheimer;
    ArrayView<const double> temperature;  // K; frozen during one SIMPLE call
};

struct Simple3DStateView {
    ArrayView<double> u, v, w, pressure, pressure_correction, d_u, d_v, d_w, density;
    ArrayView<double> inlet_velocity;  // (nx,nz), already geometric face-average
};

struct Simple3DBoundaryView {
    ArrayView<const double> outlet_u_fraction;  // (nx+1,nz), tangential viscous wall weight
    ArrayView<const double> outlet_w_fraction;  // (nx,nz+1), tangential viscous wall weight
};

// Both execution paths are single-threaded here. red_black preserves the
// Python FOU color ordering; SOU's distance-two stencil requires natural.
// The caller resolves the existing size/explicit-option dispatch.
enum class Simple3DOrdering { natural, red_black };

struct Simple3DControl {
    std::size_t max_iterations, inner_sweeps, pressure_rebuild_every;
    double alpha_velocity, alpha_pressure, alpha_density;
    double pressure_reference_absolute, gas_constant, pressure_diagonal_drift;
    bool ideal_gas = true, massflux_inlet = true, second_order_upwind = false;
    bool adaptive_pressure_tolerance = true, track_momentum = false;
    Simple3DOrdering ordering = Simple3DOrdering::natural;
    SimpleF2Control convergence;
    bool (*cancel)(void*) = nullptr;
    void (*progress)(void*, std::size_t iteration, double legacy_residual) = nullptr;
    void* context = nullptr;
};

struct Simple3DResult {
    SimpleStop stop = SimpleStop::ongoing;
    bool converged = false, post_closure_measured = false, post_closure_certified = false;
    std::size_t iterations = 0, pressure_clip_hits = 0, post_closure_rejections = 0;
    double legacy_residual = std::numeric_limits<double>::quiet_NaN();
    double legacy_reference = 1.;
    SimpleMomentumResidual momentum;
    SimpleMassAudit mass{std::numeric_limits<double>::quiet_NaN(), 0., 0.,
        std::numeric_limits<double>::quiet_NaN(), 0., 0};
    PressureResult linear;  // latest solve evidence; accepted x is copied into state
};

// Current 3D Darcy-Forchheimer equations, half-strip transport and optional
// physical-coordinate SOU. Predictor includes relaxation/diagonal compensation;
// the residual evaluates the unrelaxed equation without that compensation.
void simple_3d_predictor(const GridView& grid, ArrayView<const unsigned char> outlet_open,
                         const Simple3DMaterialView& material,
                         const Simple3DBoundaryView& boundary, Simple3DStateView state,
                         double alpha_velocity, std::size_t sweeps, bool second_order_upwind,
                         Simple3DOrdering ordering = Simple3DOrdering::natural);
SimpleMomentumResidual simple_3d_momentum_residual(
    const GridView& grid, const Simple3DMaterialView& material,
    const Simple3DBoundaryView& boundary, Simple3DStateView state, bool second_order_upwind);

// One prepared solver +y grid / outlet support per instance. Widths and support
// are copied; fields remain caller-owned. The caller supplies prepared fields
// and any coarse seed. No geometry generation, bootstrap, external property backend, outer thermal
// coupling or physical inlet-pressure shooting occurs here.
// Fixed inlet mass-flux targets, PPE hierarchy, clip count and histories persist
// across warm calls. Entry and each iteration poll cancellation. Final closure
// uses fresh density, certifies ALL cells, and rejected provisional tol restarts
// confirmation within the ORIGINAL iteration budget. Failures can leave partial
// fields, which cannot be published as a converged solution.
class Simple3DSolver {
public:
    Simple3DSolver(const GridView& grid, ArrayView<const unsigned char> outlet_open);
    ~Simple3DSolver();
    Simple3DSolver(const Simple3DSolver&) = delete;
    Simple3DSolver& operator=(const Simple3DSolver&) = delete;
    Simple3DResult solve(const Simple3DMaterialView& material,
                        const Simple3DBoundaryView& boundary, Simple3DStateView state,
                        const Simple3DControl& control);
    const SimpleHistory& history() const;
    // Iterations actually entered in the latest call, including a failing
    // iteration; zero for entry rejection/cancellation. Diagnostic only.
    std::size_t charged_iterations() const;
    const std::vector<double>& massflux_target() const;
    // Full-driver bootstrap captures the original throughput before changing
    // rho and inlet velocity. One finite (nx,nz) target may be supplied only
    // before the first solve/capture; ordinary solve still captures by default.
    void capture_massflux_target(ArrayView<const double> target);
    // Existing bootstrap closeout: one ideal-gas density/inlet refresh then
    // current fine-grid y boundaries. Invalid seed fields remain untouched and
    // return false for the subsequent F2 entry guard, never a repaired seed.
    bool refresh_after_seed(const Simple3DMaterialView& material,
                            const Simple3DBoundaryView& boundary, Simple3DStateView state,
                            const Simple3DControl& control);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace tpmshx
