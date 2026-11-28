#pragma once

#include "tpmshx/fluid_properties.hpp"
#include <array>
#include <cstddef>
#include <cstdint>
#include <mutex>

namespace tpmshx {

constexpr std::size_t property_event_count = 32;
using PropertyNumber=double;
enum class Empirical : std::uint32_t {
    air_viscosity,air_conductivity,air_density,air_cp,
    water_density,water_viscosity,water_conductivity,water_cp
};
enum class NuRoute : std::uint32_t {air_direct,air_vector,water,sco2,co2};
enum class RoughnessQuantity : std::uint32_t {petukhov,haaland,height_ratio,friction_gain,extra_nu,identity};

// Fixed property and pressure expressions share float64 arithmetic and FP events.
// Bits 0 to 3 record invalid, divide-by-zero, overflow and underflow events.
// Bits 8 to 15 identify the operation.
class PropertyArithmetic {
public:
    explicit PropertyArithmetic(std::array<std::uint32_t,property_event_count>& events,bool observe=true);
    PropertyNumber add(PropertyNumber first,PropertyNumber second);
    PropertyNumber subtract(PropertyNumber first,PropertyNumber second);
    PropertyNumber multiply(PropertyNumber first,PropertyNumber second);
    PropertyNumber divide(PropertyNumber first,PropertyNumber second);
    PropertyNumber power(PropertyNumber first,PropertyNumber second);
    PropertyNumber logarithm(PropertyNumber value);
    PropertyNumber logarithm10(PropertyNumber value);
    PropertyNumber exponential(PropertyNumber value);
private:
    template<class Function> PropertyNumber apply(std::uint32_t operation,Function function);
    std::array<std::uint32_t,property_event_count>& events_;
    std::size_t node_=0;
    bool observe_;
};

// The point formulas are owned by fluid_properties.cpp.
PropertyNumber empirical_point(Empirical getter,PropertyNumber temperature,PropertyNumber pressure,
    std::array<std::uint32_t,property_event_count>& events,bool observe=true);
PropertyNumber nu_point(NuRoute route,Topology topology,PropertyNumber re,PropertyNumber pr,
    PropertyNumber cell,PropertyNumber diameter,PropertyNumber alpha,
    std::array<std::uint32_t,property_event_count>& events,bool observe=true);
PropertyNumber roughness_point(RoughnessQuantity quantity,PropertyNumber first,PropertyNumber second,
    std::array<std::uint32_t,property_event_count>& events,bool observe=true);
double native_roughness_factor(double re,double roughness_m,double diameter_m);

namespace detail {
// The CoolProp factory and property queries share one lock in each library image.
extern std::mutex eos_factory_mutex;
}

}  // namespace tpmshx
