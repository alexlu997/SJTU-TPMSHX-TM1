#pragma once

#include "tpmshx/closure_evidence.hpp"
#include "tpmshx/fluid_properties.hpp"
#include "tpmshx/model_coefficients.hpp"

namespace tpmshx::closure_ranges {

inline const char* fluid_name(Fluid fluid) {
    return fluid==Fluid::air?"air":fluid==Fluid::water?"water":fluid==Fluid::co2?"co2":"sco2";
}

inline RangeObservation property(Fluid fluid,const char* name,std::size_t side,
                                 const char* source,const char* stage,const char* layout,
                                 const std::vector<std::size_t>& shape) {
    const auto bounds=fluid==Fluid::water?model_coefficients::water_temperature_range:
        std::string(name)=="cp"?model_coefficients::air_cp_temperature_range:model_coefficients::air_temperature_range;
    return {source,std::string(fluid_name(fluid))+"_"+name,"",stage,layout,side,shape,bounds};
}

inline RangeObservation nu(Fluid fluid,Topology topology,std::size_t side,
                           const char* source,const char* stage,const char* layout,
                           std::vector<std::size_t> shape) {
    const auto bounds=fluid==Fluid::air?model_coefficients::air_nu_re_range:
        fluid==Fluid::water?model_coefficients::water_nu_re_range:
        fluid==Fluid::co2?model_coefficients::co2_nu_re_range:model_coefficients::sco2_nu_re_range;
    return {source,fluid_name(fluid),topology==Topology::diamond?"Diamond":"Gyroid",
            stage,layout,side,std::move(shape),bounds};
}

} // namespace tpmshx::closure_ranges
