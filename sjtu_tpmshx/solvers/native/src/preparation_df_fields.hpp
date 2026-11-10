#pragma once

#include "preparation_properties.hpp"

namespace tpmshx::preparation {

PropertyResult df_pressure_gradient(PropertyInput density,PropertyInput viscosity,
    PropertyInput speed,PropertyInput permeability,PropertyInput inertial);

}  // namespace tpmshx::preparation
