#pragma once

#include "tpmshx/fluid_properties.hpp"
#include "tpmshx/grid.hpp"
#include "tpmshx/preparation_c_api.h"
#include <array>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace tpmshx::preparation {

using grid::Scalar;
constexpr std::size_t property_event_count=TPMSHX_PREPARATION_FP_EVENT_COUNT;
enum class Empirical : std::uint32_t {
    air_viscosity,air_conductivity,air_density,air_cp,
    water_density,water_viscosity,water_conductivity,water_cp
};
enum class NuRoute : std::uint32_t {air_direct,air_vector,water,sco2,co2};
enum class RoughnessQuantity : std::uint32_t {petukhov,haaland,height_ratio,friction_gain,extra_nu,identity};
// Layout: Python scalar, NumPy scalar, zero-dimensional array, other array.
struct PropertyInput {
    ArrayView<const double> values;Scalar kind;std::uint32_t layout;
    double imaginary=0.;std::uint32_t category=0;
};
struct PropertyNumber {Scalar real;double imaginary=0.;std::uint32_t category=0,layout=0;bool empty=false;};
struct PropertyResult {
    std::vector<double> values,imaginary;
    Scalar kind{0.,64,0};
    std::uint32_t category=0;
    std::array<std::uint32_t,property_event_count> events{};
};
struct PropertyFailure {
    std::uint32_t reason=0,input=0;
    std::size_t index=std::numeric_limits<std::size_t>::max();
    std::size_t first_t_index=std::numeric_limits<std::size_t>::max();
    std::size_t first_p_index=std::numeric_limits<std::size_t>::max();
    double temperature=std::numeric_limits<double>::quiet_NaN();
    double pressure=std::numeric_limits<double>::quiet_NaN();
    double detail=std::numeric_limits<double>::quiet_NaN();
    tpmshx_preparation_fp_failure_v1 fp{};
};
class PropertyError : public std::runtime_error {
public:
    PropertyError(int status,const std::string& text,PropertyFailure failure={})
        :std::runtime_error(text),status(status),failure(failure) {
        if (status==3 && !this->failure.fp.python_cause) this->failure.fp.python_cause=3;
    }
    int status;
    PropertyFailure failure;
};

// Fixed property and pressure expressions share typed arithmetic and events.
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
    template<class Function> PropertyNumber binary(std::uint32_t operation,
        PropertyNumber first,PropertyNumber second,Function function);
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
PropertyNumber reynolds_point(PropertyNumber rho,PropertyNumber speed,PropertyNumber diameter,
    PropertyNumber mu,std::array<std::uint32_t,property_event_count>& events);
PropertyNumber prandtl_point(PropertyNumber mu,PropertyNumber cp,PropertyNumber conductivity,
    std::array<std::uint32_t,property_event_count>& events);
PropertyNumber surface_transfer_point(PropertyNumber nu,PropertyNumber conductivity,PropertyNumber diameter,
    std::array<std::uint32_t,property_event_count>& events);
PropertyNumber volumetric_transfer_point(PropertyNumber surface,PropertyNumber area,
    std::array<std::uint32_t,property_event_count>& events);
PropertyNumber pore_conductivity_point(PropertyNumber epsilon,PropertyNumber conductivity,
    std::array<std::uint32_t,property_event_count>& events);
std::vector<std::vector<double>> property_eos_query(const std::vector<std::string>& keys,
    const char* input,const std::vector<double>& first,const std::vector<double>& pressure,
    bool scalar);
PropertyResult empirical(Empirical getter,PropertyInput temperature,PropertyInput pressure);
PropertyResult nu_inputs(NuRoute route,PropertyInput re,PropertyInput pr,PropertyInput cell,
    PropertyInput diameter,PropertyInput floor,std::array<double,4>& extrema);
PropertyResult nusselt(NuRoute route,Topology topology,PropertyInput re,PropertyInput pr,
    PropertyInput cell,PropertyInput diameter,Scalar alpha);
PropertyResult roughness(RoughnessQuantity quantity,PropertyInput first,PropertyInput second);
PropertyResult reynolds(PropertyInput rho,PropertyInput speed,PropertyInput diameter,PropertyInput mu);
PropertyResult prandtl(PropertyInput mu,PropertyInput cp,PropertyInput conductivity);
PropertyResult surface_transfer(PropertyInput nu,PropertyInput conductivity,PropertyInput diameter);
std::array<PropertyResult,2> inlet_re_pr(PropertyInput rho,PropertyInput mu,PropertyInput k,
    PropertyInput cp,PropertyInput speed,PropertyInput diameter);
PropertyResult volumetric_transfer(PropertyInput surface,PropertyInput area);
PropertyResult pore_conductivity(PropertyInput epsilon,PropertyInput conductivity);
std::array<PropertyResult,3> inlet_transfer(PropertyInput nu,PropertyInput k,PropertyInput diameter,
    PropertyInput area,PropertyInput epsilon);
void validate_water_pt(ArrayView<const double> temperature,ArrayView<const double> pressure);
void validate_co2_pt(ArrayView<const double> temperature,ArrayView<const double> pressure);
void validate_sco2(ArrayView<const double> temperature,ArrayView<const double> pressure);
std::vector<double> co2_pt(const std::vector<std::uint32_t>& keys,
    ArrayView<const double> temperature,ArrayView<const double> pressure,bool scalar_bundle);
std::vector<double> sco2_pt(std::uint32_t form,const std::vector<std::string>& keys,
    ArrayView<const double> temperature,ArrayView<const double> pressure);
std::vector<double> sco2_hp(ArrayView<const double> enthalpy,ArrayView<const double> pressure,bool scalar);

}  // namespace tpmshx::preparation
