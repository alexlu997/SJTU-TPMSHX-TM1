#pragma once

#include "tpmshx/closure_evidence.hpp"
#include "tpmshx/fluid_properties.hpp"
#include "tpmshx/model_coefficients.hpp"

#include <array>
#include <stdexcept>

namespace tpmshx::closure_ranges {

inline const char* fluid_name(Fluid fluid) {
    switch (fluid) {
    case Fluid::air: return "air";
    case Fluid::water: return "water";
    case Fluid::sco2: return "sco2";
    case Fluid::co2: return "co2";
    }
    throw std::invalid_argument("unsupported closure range fluid "+std::to_string(static_cast<int>(fluid)));
}

inline RangeObservation property(Fluid fluid,const char* name,std::size_t side,
                                 const char* source,const char* stage,const char* layout,
                                 const std::vector<std::size_t>& shape) {
    std::array<double,2> bounds;
    switch (fluid) {
    case Fluid::water: bounds=model_coefficients::water_temperature_range; break;
    case Fluid::air:
    case Fluid::sco2:
    case Fluid::co2:
        bounds=std::string(name)=="cp" ? model_coefficients::air_cp_temperature_range
                                      : model_coefficients::air_temperature_range;
        break;
    default: throw std::invalid_argument("unsupported property range fluid "+std::to_string(static_cast<int>(fluid)));
    }
    return {source,std::string(fluid_name(fluid))+"_"+name,"",stage,layout,side,shape,bounds};
}

inline RangeObservation nu(Fluid fluid,Topology topology,std::size_t side,
                           const char* source,const char* stage,const char* layout,
                           std::vector<std::size_t> shape) {
    const char* name;
    switch (topology) {
    case Topology::diamond: name="Diamond"; break;
    case Topology::gyroid: name="Gyroid"; break;
    default: throw std::invalid_argument("unsupported Nu range topology "+std::to_string(static_cast<int>(topology)));
    }
    std::array<double,2> bounds;
    switch (fluid) {
    case Fluid::air: bounds=model_coefficients::air_nu_re_range; break;
    case Fluid::water: bounds=model_coefficients::water_nu_re_range; break;
    case Fluid::sco2: bounds=model_coefficients::sco2_nu_re_range; break;
    case Fluid::co2: bounds=model_coefficients::co2_nu_re_range; break;
    default: throw std::invalid_argument("unsupported Nu range fluid "+std::to_string(static_cast<int>(fluid)));
    }
    return {source,fluid_name(fluid),name,stage,layout,side,std::move(shape),bounds};
}

} // namespace tpmshx::closure_ranges
