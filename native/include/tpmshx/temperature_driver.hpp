#pragma once

#include "tpmshx/finite_volume.hpp"

namespace tpmshx {

enum class TemperatureScheme { cell_centered_2d, cell_centered_3d };
enum class TemperatureStop { converged, budget_exhausted, cancelled };

struct TemperatureBoundary {
    int direction;  // 0:+x, 1:-x, 2:+y, 3:-y, 4:+z, 5:-z
    double inlet_temperature;
    // Optional materialized face arrays. Empty profile/opening means Tin/1.
    // A supplied capacity_flux is signed inward and already includes opening.
    // Shapes: (ny,nz), (nx,nz), or (nx,ny), according to direction.
    ArrayView<const double> profile{}, opening{}, capacity_flux{};
};

struct TemperatureFluidView {
    ArrayView<const double> conductivity, hv, epsilon, rho_cp;
    ArrayView<const double> u, v, w;  // cell-centred real-coordinate velocities
    TemperatureBoundary boundary;
};

struct TemperatureControl {
    // These are the resolved caller budgets; no mode-dependent defaults hide
    // here. Python defaults: 2D (50000,500,min(tol*2e-3,1e-3));
    // 3D (10000,250,max(tol*10,1e-4)). QD has its own resolved controls.
    std::size_t max_iterations, chunk_iterations;
    double q_relative_tolerance;
    double alpha_a, alpha_solid, alpha_b;
    bool warm_start = false;
    bool second_order_b = false;  // optional in 2D; must be true in 3D CC
    bool (*cancel)(void*) = nullptr;
    void (*progress)(void*, std::size_t, std::size_t) = nullptr;
    void* context = nullptr;
};

struct TemperatureResult {
    TemperatureStop stop;
    // Compatibility budget: each requested chunk is charged in full even
    // when its inner max-change < 1e-10 K exit executes fewer sweeps.
    std::size_t iterations;
    double residual;  // last executed sweep's maximum relaxed change, K
    double q_b;       // interface integral: W/m in 2D, W in 3D;
                      // NaN if cancelled or no chunk was audited
};

// Complete fixed-coefficient thermal iteration. Owns cold/prescribed starts,
// chunk budget, Q/field stability, progress and cancellation. No EOS, property
// pass, pressure solver, production binding or physical energy certificate.
// 2D uses nz==1 and unit depth (dz is validated but not multiplied into rows);
// its capacity_flux is W/(m K). 3D CC requires nz>1 and capacity_flux is W/K.
// Explicit per-side epsilon is consumed once; K already includes porosity.
// The phase schedule is per-cell A -> solid -> B. 2D requires alpha=(.7,1,1),
// with undamped A outlet cells; 3D honours all three relaxation factors.
// Nonempty prescribed_b pins B exactly while A and solid remain solved.
// Optional 2D RB reads SOU from a start-of-sweep A/B snapshot; FOU and solid
// remain live, with colour 0 then 1 in forward cell order. The caller resolves
// the original opt-in / >30000-cell gate; default remains serial. CC3D has no RB.
// No staggered, conservative projection, MMS, model-h or acceleration mode is
// exposed. An invalid scheme is rejected, never silently substituted.
// Arrays are borrowed, C-order and non-aliasing with mutable fields. All
// required extents/finite inputs are checked before state writes. Arithmetic
// failures throw domain_error and invalidate the partially updated fields.
TemperatureResult solve_temperature(
    TemperatureScheme scheme, const GridView& grid,
    const TemperatureFluidView& a, const TemperatureFluidView& b,
    ArrayView<const double> k_ss, TemperatureStateView state,
    const TemperatureControl& control,
    ArrayView<const double> prescribed_b = {}, bool red_black = false);

}  // namespace tpmshx
