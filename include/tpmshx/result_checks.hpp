#pragma once

#include "tpmshx/result_checks_c_api.h"
#include "tpmshx/result_arithmetic.hpp"

#include <array>

namespace tpmshx::result::checks {

tpmshx_result_range_sample_v1 collect_range(const Array&, double lower, double upper);
tpmshx_result_scalar_sample_indices_v1 scalar_samples(const Array&, double lower, double upper);
std::array<double, 2> parameter_bounds(double lower, double upper);
tpmshx_result_source_bounds_values_v1 source_bounds(double lower, double upper);
tpmshx_result_range_decision_v1 range_values(double lower, double upper, double minimum,
    double maximum, bool hard_bounds);
tpmshx_result_array_check_values_v1 array_checks(const Array&);
tpmshx_result_strict_values_v1 strict_certificate(bool active_b, const std::array<double, 4>&,
    double source_a, double source_b);
bool energy_ratio(const Number& ratio, const Number& tolerance, Diagnostics&);
double pressure_square(double inlet);
double outlet_pressure_squared(double square, double gas_constant, double temperature, double drag, double length);
double sound_speed(double gamma, double gas_constant, double temperature);
double mach_from_sound(double speed, double sound);
arithmetic::Tensor field_temperature_floor(const Array&, Diagnostics&);
arithmetic::Tensor field_sound_speed(const Array&, double gamma, double gas_constant, Diagnostics&);
double field_mach_max(const Array& speed, const Array& sound, Diagnostics&);
std::uint32_t pressure_flags(const Number& pressure, double floor, double allowance, Diagnostics&);
std::uint32_t mach_limit_flags(const Number& mach, const Number& limit, Diagnostics&);
std::uint32_t mach_limit_array_flags(const Number& mach, const Array& limit, Diagnostics&);
Number box_density_length(const Number& density, const Number& length, Diagnostics&);
Number box_bulk_mass(const Number& density_length, const Number& height, const Number& depth, Diagnostics&);
Number box_solid_mass(const Number& bulk_mass, const Number& epsilon, Diagnostics&);
arithmetic::Tensor box_density_length_array(const Array&, const Array&, Diagnostics&);
arithmetic::Tensor box_bulk_mass_array(const Array&, const Array&, const Array&, Diagnostics&);
arithmetic::Tensor box_solid_mass_array(const Array&, const Array&, Diagnostics&);

}  // namespace tpmshx::result::checks
