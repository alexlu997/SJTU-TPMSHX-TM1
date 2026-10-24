#pragma once

#include "tpmshx/temperature_driver.hpp"

namespace tpmshx {

// Keep the former CC input checks without changing the thermal fields.
void validate_true_h_preparation(TemperatureScheme,const GridView&,
    const TemperatureFluidView&,const TemperatureFluidView&,
    ArrayView<const double>,TemperatureStateView,const TemperatureControl&,bool red_black);

} // namespace tpmshx
