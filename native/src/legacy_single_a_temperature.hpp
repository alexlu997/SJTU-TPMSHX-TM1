#pragma once

#include "tpmshx/temperature_driver.hpp"

namespace tpmshx {

// Retained G4 cell-velocity/frozen-capacity kernel for full3D true-h CC
// warm-up and single-A sCO2 with prescribed B. An empty prescribed_b solves
// both sides. Its old row, sweep and stopping rules provide no h(P,T) ledger.
TemperatureResult solve_legacy_single_a_temperature(
    TemperatureScheme scheme, const GridView& grid,
    const TemperatureFluidView& a, const TemperatureFluidView& b,
    ArrayView<const double> k_ss, TemperatureStateView state,
    const TemperatureControl& control,
    ArrayView<const double> prescribed_b, bool red_black = false);

}  // namespace tpmshx
