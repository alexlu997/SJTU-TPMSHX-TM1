#include "preparation_properties.hpp"
#include <CoolProp/CoolProp.h>
#include <cmath>
#include <mutex>

namespace tpmshx::preparation {
namespace {
using Number=PropertyNumber;
}

PropertyNumber reynolds_point(Number rho,Number speed,Number diameter,Number mu,
    std::array<std::uint32_t,property_event_count>& events) {
    PropertyArithmetic calc(events);
    const auto mass_speed=calc.multiply(rho,speed);
    const auto scaled=calc.multiply(mass_speed,diameter);
    return calc.divide(scaled,mu);
}
PropertyNumber prandtl_point(Number mu,Number cp,Number conductivity,
    std::array<std::uint32_t,property_event_count>& events) {
    PropertyArithmetic calc(events);
    const auto capacity=calc.multiply(mu,cp);
    return calc.divide(capacity,conductivity);
}
PropertyNumber surface_transfer_point(Number nu,Number conductivity,Number diameter,
    std::array<std::uint32_t,property_event_count>& events) {
    PropertyArithmetic calc(events);
    const auto scaled=calc.multiply(nu,conductivity);
    return calc.divide(scaled,diameter);
}
PropertyNumber volumetric_transfer_point(Number surface,Number area,
    std::array<std::uint32_t,property_event_count>& events) {
    PropertyArithmetic calc(events);return calc.multiply(surface,area);
}
PropertyNumber pore_conductivity_point(Number epsilon,Number conductivity,
    std::array<std::uint32_t,property_event_count>& events) {
    PropertyArithmetic calc(events);return calc.multiply(epsilon,conductivity);
}

std::vector<std::vector<double>> property_eos_query(const std::vector<std::string>& keys,
    const char* input,const std::vector<double>& first,const std::vector<double>& pressure,bool scalar) {
    const std::lock_guard<std::mutex> lock(detail::eos_factory_mutex);
    if (scalar) {
        const double value=CoolProp::PropsSI(keys.at(0),input,first.at(0),"P",pressure.at(0),"CO2");
        if (!std::isfinite(value)) throw std::runtime_error(CoolProp::get_global_param_string("errstring"));
        return {{value}};
    }
    auto result=CoolProp::PropsSImulti(keys,input,first,"P",pressure,"HEOS",{"CO2"},{1.});
    if (result.empty()) throw std::runtime_error(CoolProp::get_global_param_string("errstring"));
    return result;
}
}  // namespace tpmshx::preparation
