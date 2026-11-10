#pragma once

#include "tpmshx/result_arithmetic.hpp"

#include <array>

namespace tpmshx::result::metrics {
using arithmetic::Tensor;
Tensor pressure_ratio(const Array& first,const Array& second,Diagnostics&);
Tensor pressure_face(const Array& first,const Array& second,const Array& ratio,Diagnostics&);
Tensor capacity_porosity(const Array& epsilon,const Array& split,Diagnostics&);
Tensor capacity_split_field(const Array& split,Diagnostics&);
Number capacity_split(const Number& split,bool cold,Diagnostics&);
bool port_width_valid(const Array&);
bool port_opening_valid(const Array&);
double weighted_mean(const Array& values,const Array& weights,Diagnostics&);
std::array<Tensor,2> port_weights(const Array& dx,const Array& dz,
    const Array& inlet_opening,const Array& outlet_opening,Diagnostics&);
double capacity_duty(const std::array<Array,5>& inlet,const std::array<Array,5>& outlet,
    const Array& inlet_temperature,const Array& outlet_temperature,Diagnostics&);
double outlet_temperature_2d(const Array& temperature,const Array& mass,const Array& opening,bool reverse,Diagnostics&);
double outlet_temperature_3d(const Array& temperature,const Array& mass,bool reverse,Diagnostics&);
double boundary_enthalpy_duty(const std::array<Array,6>& adjacent,const std::array<Array,6>& mass,const Number& inlet_h,Diagnostics&);
double plane_duty(const std::vector<Array>& faces,Diagnostics&);
double staggered_power_duty_2d(const std::array<Array,4>& faces,Diagnostics&);
std::array<double,2> boundary_mass_2d(const std::array<Array,4>& faces,Diagnostics&);
std::array<double,2> boundary_mass_3d(const std::array<Array,6>& faces,Diagnostics&);
double solid_mass_2d(const Array& epsilon,const Array& density,const Array& dx,const Array& dy,Diagnostics&);
double solid_mass_3d(const Array& epsilon,const Array& density,const Array& dx,const Array& dy,const Array& dz,Diagnostics&);
double outlet_mean(const Array& plane,Diagnostics&);
Tensor capture_area_weights(const Array& dx,const Array& dy,Diagnostics&);
double capture_area(const Array& dx,const Array& dy,Diagnostics&);
double duty_magnitude(double duty);
double mass_imbalance(double inlet,double outlet);
double full_energy_imbalance(double a,double b);
Number quick_energy_imbalance(const Number& a,const Number& b,Diagnostics&);
double richardson_duty(double fine,double coarse);
Number pressure_difference(const Number& inlet,const Number& outlet,Diagnostics&);
Number absolute_outlet_pressure(const Number& outlet,const Number& reference,Diagnostics&);
Number quick_temperature_difference(const Number& inlet,double outlet,Diagnostics&);
Number quick_capacity_product(const Number& mass,const Number& cp,Diagnostics&);
Number quick_duty_from_capacity(const Number& capacity,const Number& delta,bool cold,Diagnostics&);
Number quick_reynolds_flow(const Number& rho,const Number& velocity,Diagnostics&);
Number quick_reynolds_length(const Number& flow,const Number& diameter,Diagnostics&);
Number quick_reynolds_quotient(const Number& numerator,const Number& mu,Diagnostics&);
Tensor pressure_difference_field(const Array& inlet,const Array& outlet,Diagnostics&);
Tensor quick_temperature_difference_field(const Array& inlet,double outlet,Diagnostics&);
Tensor quick_capacity_product_field(const Array& mass,const Array& cp,Diagnostics&);
Tensor quick_duty_from_capacity_field(const Array& capacity,const Array& delta,bool cold,Diagnostics&);
Tensor quick_reynolds_flow_field(const Array& rho,const Array& velocity,Diagnostics&);
Tensor quick_reynolds_length_field(const Array& flow,const Array& diameter,Diagnostics&);
Tensor quick_reynolds_quotient_field(const Array& numerator,const Array& mu,Diagnostics&);
Tensor quick_energy_imbalance_field(const Array& first,const Array& second,Diagnostics&);
}  // namespace tpmshx::result::metrics
