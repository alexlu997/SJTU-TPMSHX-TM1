#include "tpmshx/result_metrics_c_api.h"
#include "tpmshx/result_metrics.hpp"
#include "result_c_boundary.hpp"

#include <algorithm>
#include <utility>

namespace {
namespace r=tpmshx::result;
namespace m=tpmshx::result::metrics;
using r::RawArray;using r::Diagnostics;
template<std::size_t N,std::size_t... I> std::array<r::Array,N> array_group(const RawArray* values,std::index_sequence<I...>) {return {r::Array(values[I])...};}
template<std::size_t N> std::array<r::Array,N> array_group(const RawArray* values) {return array_group<N>(values,std::make_index_sequence<N>{});}
void output_array(r::c_api::Buffers& buffers,const RawArray* out) {
    buffers.output_array(out);
}
void verify_output(const m::Tensor& value,const RawArray* output) {
    if (output->rank!=value.shape.size() || !std::equal(value.shape.begin(),value.shape.end(),output->shape))
        throw std::invalid_argument("native metric output shape disagrees with calculation");
}
void publish(const m::Tensor& value,const RawArray* output) {
    verify_output(value,output);
    std::copy(value.values.begin(),value.values.end(),const_cast<double*>(output->data));
}
void publish(const std::array<double,2>& value,double* output) {std::copy(value.begin(),value.end(),output);}
}
#define DIAG r::Diagnostics* diagnostics,char* error,std::size_t capacity
#define BOUNDARY(registers,body) return r::c_api::boundary(diagnostics,error,capacity,[&](auto& buffers) registers,[&](r::Diagnostics& d) body)
#define ENTRY(name) extern "C" int TPMSHX_RESULT_CALL tpmshx_result_##name##_v1

ENTRY(pressure_ratio)(const RawArray* first,const RawArray* second,const RawArray* out,DIAG) {
    BOUNDARY({buffers.arrays(first,1);buffers.arrays(second,1);output_array(buffers,out);},
             {auto value=m::pressure_ratio(r::Array(*first),r::Array(*second),d);publish(value,out);});
}
ENTRY(pressure_face)(const RawArray* first,const RawArray* second,const RawArray* ratio,const RawArray* out,DIAG) {
    BOUNDARY({buffers.arrays(first,1);buffers.arrays(second,1);buffers.arrays(ratio,1);output_array(buffers,out);},
             {auto value=m::pressure_face(r::Array(*first),r::Array(*second),r::Array(*ratio),d);publish(value,out);});
}
ENTRY(capacity_porosity)(const RawArray* epsilon,const RawArray* split,const RawArray* out,DIAG) {
    BOUNDARY({buffers.arrays(epsilon,1);buffers.arrays(split,1);output_array(buffers,out);},
             {auto value=m::capacity_porosity(r::Array(*epsilon),r::Array(*split),d);publish(value,out);});
}
ENTRY(capacity_split_field)(const RawArray* split,const RawArray* out,DIAG) {
    BOUNDARY({buffers.arrays(split,1);output_array(buffers,out);},
             {auto value=m::capacity_split_field(r::Array(*split),d);publish(value,out);});
}
ENTRY(capacity_split)(double split,std::uint32_t cold,double* out,DIAG) {
    BOUNDARY({buffers.output(out,1);},
             {if (cold>1) throw std::invalid_argument("invalid capacity side");const auto value=m::capacity_split(r::arithmetic::python_float(split),cold!=0,d).value;*out=value;});
}
#define VALID_ENTRY(name) ENTRY(name)(const RawArray* input,std::uint32_t* out,DIAG) {BOUNDARY({buffers.arrays(input,1);buffers.output(out,1);},{(void)d;const auto value=m::name(r::Array(*input));*out=value?1u:0u;});}
VALID_ENTRY(port_width_valid)
VALID_ENTRY(port_opening_valid)
#undef VALID_ENTRY
ENTRY(weighted_mean)(const RawArray* values,const RawArray* weights,double* out,DIAG) {
    BOUNDARY({buffers.arrays(values,1);buffers.arrays(weights,1);buffers.output(out,1);},
             {const auto value=m::weighted_mean(r::Array(*values),r::Array(*weights),d);*out=value;});
}
ENTRY(port_weights)(const RawArray* dx,const RawArray* dz,const RawArray* wi,const RawArray* wo,const RawArray* oi,const RawArray* oo,DIAG) {
    BOUNDARY({buffers.arrays(dx,1);buffers.arrays(dz,1);buffers.arrays(wi,1);buffers.arrays(wo,1);output_array(buffers,oi);output_array(buffers,oo);},
             {const auto value=m::port_weights(r::Array(*dx),r::Array(*dz),r::Array(*wi),r::Array(*wo),d);
              verify_output(value[0],oi);verify_output(value[1],oo);
              publish(value[0],oi);publish(value[1],oo);});
}
ENTRY(capacity_duty)(const RawArray* inlet,const RawArray* outlet,const RawArray* tin,const RawArray* tout,double* out,DIAG) {
    BOUNDARY({buffers.arrays(inlet,5);buffers.arrays(outlet,5);buffers.arrays(tin,1);buffers.arrays(tout,1);buffers.output(out,1);},
             {const auto value=m::capacity_duty(array_group<5>(inlet),array_group<5>(outlet),r::Array(*tin),r::Array(*tout),d);*out=value;});
}
ENTRY(outlet_temperature_2d)(const RawArray* temperature,const RawArray* mass,const RawArray* opening,std::uint32_t reverse,double* out,DIAG) {
    BOUNDARY({buffers.arrays(temperature,1);buffers.arrays(mass,1);buffers.arrays(opening,1);buffers.output(out,1);},
             {if (reverse>1) throw std::invalid_argument("invalid outlet orientation");const auto value=m::outlet_temperature_2d(r::Array(*temperature),r::Array(*mass),r::Array(*opening),reverse!=0,d);*out=value;});
}
ENTRY(outlet_temperature_3d)(const RawArray* temperature,const RawArray* mass,std::uint32_t reverse,double* out,DIAG) {
    BOUNDARY({buffers.arrays(temperature,1);buffers.arrays(mass,1);buffers.output(out,1);},
             {if (reverse>1) throw std::invalid_argument("invalid outlet orientation");const auto value=m::outlet_temperature_3d(r::Array(*temperature),r::Array(*mass),reverse!=0,d);*out=value;});
}
ENTRY(boundary_enthalpy_duty)(const RawArray* adjacent,const RawArray* mass,double inlet_h,double* out,DIAG) {
    BOUNDARY({buffers.arrays(adjacent,6);buffers.arrays(mass,6);buffers.output(out,1);},
             {const auto value=m::boundary_enthalpy_duty(array_group<6>(adjacent),array_group<6>(mass),r::arithmetic::python_float(inlet_h),d);*out=value;});
}
ENTRY(plane_duty)(const RawArray* faces,std::size_t count,double* out,DIAG) {
    BOUNDARY({buffers.arrays(faces,count);buffers.output(out,1);},
             {if (count!=6) throw std::invalid_argument("metric duty requires six boundary planes");std::vector<r::Array> inputs;for (std::size_t i=0;i<count;++i) inputs.emplace_back(faces[i]);const auto value=m::plane_duty(inputs,d);*out=value;});
}
ENTRY(staggered_power_duty_2d)(const RawArray* faces,double* out,DIAG) {
    BOUNDARY({buffers.arrays(faces,4);buffers.output(out,1);},{const auto value=m::staggered_power_duty_2d(array_group<4>(faces),d);*out=value;});
}
ENTRY(boundary_mass_2d)(const RawArray* faces,double* out,DIAG) {
    BOUNDARY({buffers.arrays(faces,4);buffers.output(out,2);},{const auto value=m::boundary_mass_2d(array_group<4>(faces),d);publish(value,out);});
}
ENTRY(boundary_mass_3d)(const RawArray* faces,double* out,DIAG) {
    BOUNDARY({buffers.arrays(faces,6);buffers.output(out,2);},{const auto value=m::boundary_mass_3d(array_group<6>(faces),d);publish(value,out);});
}
ENTRY(solid_mass_2d)(const RawArray* eps,const RawArray* density,const RawArray* dx,const RawArray* dy,double* out,DIAG) {
    BOUNDARY({buffers.arrays(eps,1);buffers.arrays(density,1);buffers.arrays(dx,1);buffers.arrays(dy,1);buffers.output(out,1);},
             {const auto value=m::solid_mass_2d(r::Array(*eps),r::Array(*density),r::Array(*dx),r::Array(*dy),d);*out=value;});
}
ENTRY(solid_mass_3d)(const RawArray* eps,const RawArray* density,const RawArray* dx,const RawArray* dy,const RawArray* dz,double* out,DIAG) {
    BOUNDARY({buffers.arrays(eps,1);buffers.arrays(density,1);buffers.arrays(dx,1);buffers.arrays(dy,1);buffers.arrays(dz,1);buffers.output(out,1);},
             {const auto value=m::solid_mass_3d(r::Array(*eps),r::Array(*density),r::Array(*dx),r::Array(*dy),r::Array(*dz),d);*out=value;});
}
ENTRY(outlet_mean)(const RawArray* plane,double* out,DIAG) {
    BOUNDARY({buffers.arrays(plane,1);buffers.output(out,1);},{const auto value=m::outlet_mean(r::Array(*plane),d);*out=value;});
}
ENTRY(capture_area)(const RawArray* dx,const RawArray* dy,double* out,DIAG) {
    BOUNDARY({buffers.arrays(dx,1);buffers.arrays(dy,1);buffers.output(out,1);},
             {const auto value=m::capture_area(r::Array(*dx),r::Array(*dy),d);*out=value;});
}
ENTRY(capture_area_weights)(const RawArray* dx,const RawArray* dy,const RawArray* out,DIAG) {
    BOUNDARY({buffers.arrays(dx,1);buffers.arrays(dy,1);output_array(buffers,out);},
             {auto value=m::capture_area_weights(r::Array(*dx),r::Array(*dy),d);publish(value,out);});
}
ENTRY(duty_magnitude)(double duty,double* out,DIAG) {
    BOUNDARY({buffers.output(out,1);},{(void)d;const auto value=m::duty_magnitude(duty);*out=value;});
}
#define DOUBLE_ENTRY(name) ENTRY(name)(double a,double b,double* out,DIAG) {BOUNDARY({buffers.output(out,1);},{(void)d;const auto value=m::name(a,b);*out=value;});}
DOUBLE_ENTRY(mass_imbalance)
DOUBLE_ENTRY(full_energy_imbalance)
DOUBLE_ENTRY(richardson_duty)
#undef DOUBLE_ENTRY
#define SCALAR_ENTRY(name) ENTRY(name)(double a,double b,double* out,DIAG) {BOUNDARY({buffers.output(out,1);},{namespace a_=r::arithmetic;const auto value=m::name(a_::python_float(a),a_::python_float(b),d).value;*out=value;});}
SCALAR_ENTRY(pressure_difference)
SCALAR_ENTRY(absolute_outlet_pressure)
#undef SCALAR_ENTRY
ENTRY(pressure_difference_field)(const RawArray* first,const RawArray* second,const RawArray* out,DIAG) {
    BOUNDARY({buffers.arrays(first,1);buffers.arrays(second,1);output_array(buffers,out);},
             {auto value=m::pressure_difference_field(r::Array(*first),r::Array(*second),d);publish(value,out);});
}
#undef ENTRY
#undef BOUNDARY
#undef DIAG
