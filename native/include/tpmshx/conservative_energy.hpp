#pragma once

#include "tpmshx/enthalpy_sweeps.hpp"

#include <array>

namespace tpmshx {

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
