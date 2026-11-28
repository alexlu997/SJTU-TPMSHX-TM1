#include "tpmshx/result_checks.hpp"
#include "result_c_boundary.hpp"

#include <algorithm>
#include <array>

namespace {
namespace r=tpmshx::result;
namespace c=tpmshx::result::c_api;
namespace checks=tpmshx::result::checks;
using Buffers=c::Buffers;
using Diagnostics=r::Diagnostics;

void exact_count(std::size_t actual,std::size_t expected) {
    if (actual!=expected) throw std::invalid_argument("result output extent is incorrect");
}
void flag(std::uint32_t value) {
    if (value>1) throw std::invalid_argument("result flag must be zero or one");
}
void copy_double(const r::arithmetic::Tensor& values,double* output) {
    std::copy(values.values.begin(),values.values.end(),output);
}
void publish(const r::arithmetic::Tensor& value,const r::RawArray* output) {
    if (output->rank!=value.shape.size() || !std::equal(value.shape.begin(),value.shape.end(),output->shape))
        throw std::invalid_argument("native box output shape disagrees with calculation");
    std::copy(value.values.begin(),value.values.end(),const_cast<double*>(output->data));
}
}  // namespace

extern "C" {
int TPMSHX_RESULT_CALL tpmshx_result_collect_range_v1(r::RawArray values,double lower,double upper,
    tpmshx_result_range_sample_v1* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.array(values);b.output(output,1);},
        [&](Diagnostics&){const auto result=checks::collect_range(r::Array(values),lower,upper);*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_scalar_samples_v1(r::RawArray values,double lower,double upper,
    tpmshx_result_scalar_sample_indices_v1* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.array(values);b.output(output,1);},
        [&](Diagnostics&){const auto result=checks::scalar_samples(r::Array(values),lower,upper);*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_parameter_bounds_v1(double lower,double upper,double* output,
    std::size_t count,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.output(output,count);},
        [&](Diagnostics&){exact_count(count,2);const auto result=checks::parameter_bounds(lower,upper);
            std::copy(result.begin(),result.end(),output);});
}
int TPMSHX_RESULT_CALL tpmshx_result_source_bounds_v1(double lower,double upper,
    tpmshx_result_source_bounds_values_v1* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.output(output,1);},
        [&](Diagnostics&){const auto result=checks::source_bounds(lower,upper);*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_range_values_v1(double lower,double upper,double minimum,double maximum,
    std::uint32_t hard,tpmshx_result_range_decision_v1* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.output(output,1);},
        [&](Diagnostics&){flag(hard);const auto result=checks::range_values(lower,upper,minimum,maximum,hard!=0);*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_array_checks_v1(r::RawArray values,
    tpmshx_result_array_check_values_v1* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.array(values);b.output(output,1);},
        [&](Diagnostics&){const auto result=checks::array_checks(r::Array(values));*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_strict_certificate_v1(std::uint32_t active_b,const double* ratios,
    std::size_t count,double source_a,double source_b,tpmshx_result_strict_values_v1* output,
    Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.input(ratios,count);b.output(output,1);},
        [&](Diagnostics&){flag(active_b);exact_count(count,4);
            const auto result=checks::strict_certificate(active_b!=0,{ratios[0],ratios[1],ratios[2],ratios[3]},source_a,source_b);
            *output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_energy_ratio_v1(double ratio,double tolerance,
    std::uint32_t* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.output(output,1);},
        [&](Diagnostics&){const auto result=checks::energy_ratio(ratio,tolerance);*output=result?1u:0u;});
}
int TPMSHX_RESULT_CALL tpmshx_result_pressure_square_v1(double inlet,double* output,
    Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.output(output,1);},
        [&](Diagnostics&){const auto result=checks::pressure_square(inlet);*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_outlet_pressure_squared_v1(double square,double gas_constant,double temperature,
    double drag,double length,double* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.output(output,1);},
        [&](Diagnostics&){const auto result=checks::outlet_pressure_squared(square,gas_constant,temperature,drag,length);*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_sound_speed_v1(double gamma,double gas_constant,double temperature,double* output,
    Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.output(output,1);},
        [&](Diagnostics&){const auto result=checks::sound_speed(gamma,gas_constant,temperature);*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_mach_from_sound_v1(double speed,double sound,double* output,
    Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.output(output,1);},
        [&](Diagnostics&){const auto result=checks::mach_from_sound(speed,sound);*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_field_temperature_floor_v1(r::RawArray values,double* output,std::size_t count,
    Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.array(values);b.output(output,count);},
        [&](Diagnostics& d){const r::Array input(values);exact_count(count,input.size());
            const auto result=checks::field_temperature_floor(input,d);copy_double(result,output);});
}
int TPMSHX_RESULT_CALL tpmshx_result_field_sound_speed_v1(r::RawArray values,double gamma,double gas_constant,
    double* output,std::size_t count,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.array(values);b.output(output,count);},
        [&](Diagnostics& d){const r::Array input(values);exact_count(count,input.size());
            const auto result=checks::field_sound_speed(input,gamma,gas_constant,d);copy_double(result,output);});
}
int TPMSHX_RESULT_CALL tpmshx_result_field_mach_max_v1(r::RawArray speed,r::RawArray sound,double* output,
    Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.array(speed);b.array(sound);b.output(output,1);},
        [&](Diagnostics& d){const auto result=checks::field_mach_max(r::Array(speed),r::Array(sound),d);*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_pressure_flags_v1(double pressure,double floor,double allowance,
    std::uint32_t* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.output(output,1);},
        [&](Diagnostics&){const auto result=checks::pressure_flags(pressure,floor,allowance);*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_mach_limit_flags_v1(double mach,double limit,
    std::uint32_t* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.output(output,1);},
        [&](Diagnostics&){const auto result=checks::mach_limit_flags(mach,limit);*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_mach_limit_array_flags_v1(double mach,r::RawArray limit,
    std::uint32_t* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.array(limit);b.output(output,1);},
        [&](Diagnostics&){const auto result=checks::mach_limit_array_flags(mach,r::Array(limit));*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_box_density_length_v1(double density,double length,
    double* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.output(output,1);},
        [&](Diagnostics&){const auto result=checks::box_density_length(density,length);*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_box_bulk_mass_v1(double density_length,double height,double depth,
    double* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.output(output,1);},
        [&](Diagnostics&){const auto result=checks::box_bulk_mass(density_length,height,depth);*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_box_solid_mass_v1(double bulk_mass,double epsilon,
    double* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.output(output,1);},
        [&](Diagnostics&){const auto result=checks::box_solid_mass(bulk_mass,epsilon);*output=result;});
}
int TPMSHX_RESULT_CALL tpmshx_result_box_density_length_array_v1(r::RawArray density,r::RawArray length,
    const r::RawArray* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.array(density);b.array(length);b.output_array(output);},
        [&](Diagnostics& d){const auto result=checks::box_density_length_array(r::Array(density),r::Array(length),d);
            publish(result,output);});
}
int TPMSHX_RESULT_CALL tpmshx_result_box_bulk_mass_array_v1(r::RawArray prefix,r::RawArray height,r::RawArray depth,
    const r::RawArray* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.array(prefix);b.array(height);b.array(depth);b.output_array(output);},
        [&](Diagnostics& d){const auto result=checks::box_bulk_mass_array(r::Array(prefix),r::Array(height),r::Array(depth),d);
            publish(result,output);});
}
int TPMSHX_RESULT_CALL tpmshx_result_box_solid_mass_array_v1(r::RawArray bulk_mass,r::RawArray epsilon,
    const r::RawArray* output,Diagnostics* diagnostics,char* error,std::size_t capacity) {
    return c::boundary(diagnostics,error,capacity,[&](Buffers& b){b.array(bulk_mass);b.array(epsilon);b.output_array(output);},
        [&](Diagnostics& d){const auto result=checks::box_solid_mass_array(r::Array(bulk_mass),r::Array(epsilon),d);
            publish(result,output);});
}
}  // extern "C"
