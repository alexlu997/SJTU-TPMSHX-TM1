#pragma once

#include "tpmshx/enthalpy_sweeps.hpp"

#include <array>
#include <vector>

namespace tpmshx {

// Prepared positive-axis energy flux F=C*T_up+B. C is W/K, B is W;
// these are capacity/power arrays, never aliases labelled as mass flow.
struct EnergyFaces {
    std::array<ArrayView<const double>,3> capacity{}, offset{};
};

struct EnergyPhase {
    ArrayView<const double> K, hv, source_W_m3{};
    EnergyFaces faces;
    TemperatureBoundary inlet;
    bool inlet_conduction = false;
    // Two-center inlet Fourier flux for strict model-h; false keeps half-cell.
    bool second_order_inlet_conduction = false;
};

// Thin view over existing frozen true-h storage. C/B are computed at each
// face from m, cp, h*, T*; no new full-face capacity or offset buffers.
// inlet_h, when present, follows the same plane ordering as inlet.profile.
struct FrozenEnergyPhase {
    FluidView fluid;
    TemperatureBoundary inlet;
    ArrayView<const double> inlet_h{}, source_W_m3{};
    bool inlet_conduction = false;
};

// Audit-only view of actual positive-axis enthalpy powers. signed_transport
// carries the mass/capacity sign solely for inlet identity; power contains
// actual m*h_face in W, never a rounded C*T+B reconstruction. All storage is
// borrowed from the caller and must describe the same audited state.
struct PhysicalEnergyPhase {
    ArrayView<const double> K, hv, source_W_m3{};
    std::array<ArrayView<const double>,3> signed_transport{}, power{};
    TemperatureBoundary inlet;
    bool inlet_conduction = false;
    bool second_order_inlet_conduction = false;
};

struct PhysicalHeatLedger {
    // [A,B,solid][x-,x+,y-,y+,z-,z+], outward W (W/m for unit depth).
    std::array<std::array<std::vector<double>,6>,3> advective_out, diffusive_out;
    std::array<std::vector<double>,3> residual; // physical RHS-D*T, W/cell
    std::array<double,3> source_integral{};
    std::array<bool,3> solved{true,true,true};
    double prescribed_b_power = 0.; // external reservoir -> A+solid
    bool boundary_complete = true;
};

// Explicit component calls validate all extents, coefficients and inlet
// identities before writes. Unknown/closed inward faces throw on sweeps; raw
// audit retains interior-state diagnostic powers and boundary_complete=false. Source is
// physical W/m3, numerical correction is separately W/cell. Prescribed B is
// copied before the first sweep, skipped, and excluded from the solved ledger.
// Callers own geometry normalization, schedule blocks, EOS and stopping gates.
void energy_temperature_sweeps(
    const GridView&, const EnergyPhase&, const EnergyPhase&, ArrayView<const double> k_ss,
    TemperatureStateView, std::size_t sweeps, double omega,
    ArrayView<const double> source_s_W_m3 = {},
    ArrayView<const double> prescribed_b = {},
    ArrayView<const double> numerical_a_W = {},
    ArrayView<const double> numerical_b_W = {}, double solid_omega = 1.);
// Maximum absolute solved-phase L1 equation error and global power imbalance.
// Uses outward boundary powers, solved volumetric sources and reservoir power.
// Returns W (or W/m for unit depth); callers own normalization and acceptance.
double energy_balance_error(const PhysicalHeatLedger& ledger);
struct EnergyBalanceAudit { double error; bool boundary_complete; };
EnergyBalanceAudit energy_balance_audit(
    const GridView&,const EnergyPhase&,const EnergyPhase&,ArrayView<const double> k_ss,
    TemperatureStateView,ArrayView<const double> source_s_W_m3={},ArrayView<const double> prescribed_b={});

PhysicalHeatLedger energy_physical_audit(
    const GridView&, const EnergyPhase&, const EnergyPhase&, ArrayView<const double> k_ss,
    TemperatureStateView, ArrayView<const double> source_s_W_m3 = {},
    ArrayView<const double> prescribed_b = {});

void energy_temperature_sweeps(
    const GridView&, const FrozenEnergyPhase&, const FrozenEnergyPhase&, ArrayView<const double> k_ss,
    TemperatureStateView, std::size_t sweeps, double omega,
    ArrayView<const double> source_s_W_m3 = {},
    ArrayView<const double> prescribed_b = {},
    ArrayView<const double> numerical_a_W = {},
    ArrayView<const double> numerical_b_W = {}, double solid_omega = 1.);
PhysicalHeatLedger energy_physical_audit(
    const GridView&, const FrozenEnergyPhase&, const FrozenEnergyPhase&, ArrayView<const double> k_ss,
    TemperatureStateView, ArrayView<const double> source_s_W_m3 = {},
    ArrayView<const double> prescribed_b = {});

PhysicalHeatLedger energy_physical_audit(
    const GridView&, const PhysicalEnergyPhase&, const PhysicalEnergyPhase&, ArrayView<const double> k_ss,
    TemperatureStateView, ArrayView<const double> source_s_W_m3 = {},
    ArrayView<const double> prescribed_b = {});

// For FrozenEnergyPhase auditing, caller supplies actual h*/T*/cp at the
// audited T (no EOS is evaluated here). The prepared EnergyPhase offsets may
// include actual reconstructed face powers; physical source stays separate.

// Conservative frozen energy equations expressed in temperature. Each sweep
// updates all of A, then B, then solid. Cell order alternates forward/reverse
// within this call, starting forward; an odd block has one extra forward pass.
// omega relaxes fluid rows, and solid_omega independently relaxes solid rows.
// dh*cp is effective conductivity. Optional sources are frozen W/cell additions
// to the fluid balance. t_star/h_star/cp must remain independent of mutable T.
// No EOS, clipping, convergence decision or acceptance threshold is applied;
// FluidView::h_lo/h_hi are unused. Exterior conduction is adiabatic, and all
// inward mass faces use h_in; the caller must establish their physical identity.
// Mutable storage must not alias other mutable fields or immutable inputs.
// Invalid extents, nonfinite inputs and nonphysical coefficients throw before
// update. Arithmetic overflow throws std::domain_error and invalidates state.
// Zero sweeps validate inputs and leave the fields unchanged.
void conservative_temperature_sweeps(
    const GridView& grid, const FluidView& a, const FluidView& b,
    ArrayView<const double> k_ss, TemperatureStateView state,
    std::size_t sweeps, double omega, ArrayView<const double> source_a = {},
    ArrayView<const double> source_b = {}, double solid_omega = 1.0);

// Physical-coordinate minmod reconstruction of actual h. Returns the signed
// inward exterior correction in W and writes -div(delta(m*h)) in W/cell.
// Internal corrections are shared with opposite signs; inward boundary h is
// prescribed, outward h is reconstructed. A singleton axis has zero slope.
// Output need not be initialized and must not alias inputs. Invalid input is
// rejected before writes; arithmetic overflow invalidates the output.
double enthalpy_sou_correction(
    const GridView& grid, ArrayView<const double> h,
    const std::array<ArrayView<const double>, 3>& mass, double h_in,
    ArrayView<double> correction);

// Actual outward boundary power m_out*h_face in x-/x+/y-/y+/z-/z+ order.
// Plane shapes are (ny,nz), (nx,nz), (nx,ny), each twice, in C order.
// Net inward duty is minus the sum of all six planes. second_order uses the
// same physical h-minmod/outflow reconstruction as enthalpy_sou_correction;
// false uses FOU. Inward faces retain h_in. Units are W, or W/m for dz=1 in
// the 2D unit-depth contract. No EOS or convergence decision is performed.
std::array<std::vector<double>, 6> enthalpy_boundary_power(
    const GridView& grid, ArrayView<const double> h,
    const std::array<ArrayView<const double>, 3>& mass, double h_in,
    bool second_order);

// Full actual-state SOU energy audit: FOU Fourier/exchange/transport residuals
// plus reconstruction from the supplied actual h, including exterior duties.
// Uses the same non-aliasing, state consistency and error contracts as
// thermal_energy_audit; computes both fluid equations and applies no threshold.
EnergyAudit thermal_energy_audit_sou(
    const GridView& grid, const FluidEnergyView& a, const FluidEnergyView& b,
    ArrayView<const double> t_s, ArrayView<const double> k_ss,
    ArrayView<double> residual_a, ArrayView<double> residual_b,
    ArrayView<double> residual_s);

}  // namespace tpmshx
