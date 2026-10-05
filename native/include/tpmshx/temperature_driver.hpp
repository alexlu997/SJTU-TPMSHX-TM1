#pragma once

#include "tpmshx/finite_volume.hpp"
#include <array>

namespace tpmshx {

enum class TemperatureScheme { cell_centered_2d, cell_centered_3d };
enum class TemperatureStop { converged, budget_exhausted, cancelled };
struct PhysicalHeatLedger;

struct TemperatureFluidView {
    ArrayView<const double> conductivity, hv, epsilon, rho_cp;
    // Cell-centred real-coordinate velocities; optional w is validated but
    // ignored by 2D cell reconstruction. Explicit capacity_faces stay authoritative.
    ArrayView<const double> u, v, w;
    TemperatureBoundary boundary;
    // All empty retains the standalone cell-capacity contract. Otherwise all
    // three are authoritative signed positive-axis faces; no inlet override.
    std::array<ArrayView<const double>,3> capacity_faces{};
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
    // Each requested chunk is executed and charged in full, without exceeding
    // max_iterations; each block charges at most five sweep steps.
    std::size_t iterations;
    double residual;  // last block's maximum accepted temperature change, K
    double q_b;       // interface integral: W/m in 2D, W in 3D;
                      // NaN if cancelled or no chunk was audited
};

// Complete fixed-coefficient thermal iteration. Owns cold/prescribed starts,
// chunk budget, Q/field stability, progress and cancellation. No EOS, property
// pass, pressure solver or production binding. Optional audit returns a fresh
// physical ledger after a nonzero converged/budget-limited solve; cancellation
// and zero iteration budget leave that output untouched.
// 2D uses nz==1 and unit depth (dz is validated but not multiplied into rows);
// its capacity_flux is W/(m K). 3D CC requires nz>1 and capacity_flux is W/K.
// Explicit per-side epsilon is consumed once; K already includes porosity.
// With no explicit capacity_faces, unique faces use adjacent-cell arithmetic means and the
// adjacent cell at exterior faces. Explicit inward inlet capacity overrides
// that inlet; zero opening sets it to zero. Partial opening does not multiply
// an already prepared capacity a second time. Inlet conduction retains its
// profile/opening separately. All finite-volume rows are shared energy rows.
// Explicit capacity_faces bypass cell reconstruction and inlet capacity
// overrides, and require complete boundaries before convergence is reported.
// Point sweeps use per-cell A -> solid -> B, with SOU relaxation
// min(caller_alpha,.2); FOU B and solid retain caller alpha. Input validation
// still requires 2D alpha=(.7,1,1). Point sweeps in each block share frozen
// internal SOU face offsets; line assembly and the error guard reconstruct
// current-state corrections. Exterior corrections are zero. Upwind end cells
// use the two one-sided interior slopes when at least three cells exist.
// Nonempty prescribed_b pins B exactly while A and solid remain solved.
// With complete inflow, active SOU and no RB, each block performs up to four
// point sweeps followed by a line-Newton trial along each SOU phase's inlet
// axis, with the solid and FOU B point updates between/after fluid lines.
// The trial uses caller alpha and is accepted only if a fresh physical
// balance error strictly improves over the pre-trial state. Both compared
// states include T=old+.6*(updated-old). Rejected trials retain the damped
// point state. Other cases use up to five point sweeps and the same damping.
// There is no exterior self wall or outlet-specific relaxation.
// Optional 2D RB uses these same frozen A/B offsets; FOU and solid
// remain live, with colour 0 then 1 in forward cell order. The caller resolves
// the original opt-in / >30000-cell gate; default remains serial. CC3D has no RB.
// No staggered, conservative projection, MMS or model-h mode is
// exposed. An invalid scheme is rejected, never silently substituted.
// Unknown exterior inflow retains a local-state diagnostic proxy. Native
// Q/field convergence is not a physical boundary certificate; the separate
// raw shared audit reports boundary_complete=false for such a state.
// With complete boundaries, convergence additionally requires actual-state
// phase residuals and coupled boundary/source balance <=1e-7 relative to
// max(abs(interface_QA),abs(interface_QB),1), after a fresh face reconstruction.
// Arrays are borrowed, C-order and non-aliasing with mutable fields. All
// required extents/finite inputs are checked before state writes. Arithmetic
// failures throw domain_error and invalidate the partially updated fields.
TemperatureResult solve_temperature(
    TemperatureScheme scheme, const GridView& grid,
    const TemperatureFluidView& a, const TemperatureFluidView& b,
    ArrayView<const double> k_ss, TemperatureStateView state,
    const TemperatureControl& control,
    ArrayView<const double> prescribed_b = {}, bool red_black = false,
    PhysicalHeatLedger* audit = nullptr);

}  // namespace tpmshx
