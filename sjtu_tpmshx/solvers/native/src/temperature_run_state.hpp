#pragma once

#include "tpmshx/temperature_driver.hpp"
#include <cmath>
#include <stdexcept>

namespace tpmshx::detail {

inline void validate_temperature_state(const TemperatureRunState& saved,
        const TemperatureControl& control, std::size_t cells,
        ArrayView<const double> prescribed_b) {
    const auto& result=saved.result;
    if(result.stop!=TemperatureStop::budget_exhausted
        || result.iterations>=control.max_iterations
        || result.iterations%control.chunk_iterations!=0
        || !std::isfinite(result.residual) || result.residual<0.
        || (result.iterations==0
            ? (result.residual!=0. || !std::isnan(result.q_b))
            : !std::isfinite(result.q_b)))
        throw std::invalid_argument("invalid temperature save boundary");
    for(const auto& field:saved.temperature) {
        if(field.size()!=cells)
            throw std::invalid_argument("saved temperature extent differs from grid");
        for(double value:field)
            if(!std::isfinite(value))
                throw std::invalid_argument("nonfinite saved temperature");
    }
    for(std::size_t p=0;p<prescribed_b.size;++p)
        if(saved.temperature[1][p]!=prescribed_b[p])
            throw std::invalid_argument("saved prescribed temperature differs from input");
}

}  // namespace tpmshx::detail
