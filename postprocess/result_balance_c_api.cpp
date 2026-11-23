#include "tpmshx/result_balance.hpp"
#include "result_c_boundary.hpp"
#include "result_zone_capture.hpp"

#include <algorithm>
#include <stdexcept>

namespace {
namespace r = tpmshx::result;
namespace b = r::balance;
using r::c_api::Buffers;
using r::c_api::boundary;

void flag(std::uint32_t value) {
    if (value>1) throw std::invalid_argument("zone weight flag must be zero or one");
}

template<class Function> int zone_weighted(
    const r::RawArray* values, const r::RawArray* weights, std::uint32_t weighted,
    double* output, r::Diagnostics* diagnostics, char* error, std::size_t capacity,
    Function function) {
    return boundary(diagnostics,error,capacity,[&](Buffers& buffers) {
        buffers.arrays(values,1); buffers.arrays(weights,weighted?1:0); buffers.output(output,1);
    },[&](r::Diagnostics& state) {
        flag(weighted);
        const r::Array field(*values);
        if (weighted) {
            const r::Array weight(*weights);
            const auto value=function(field,&weight,state).value; *output=value;
        } else {
            const auto value=function(field,nullptr,state).value; *output=value;
        }
    });
}

template<class Function> int zone_reduction(const r::RawArray* values, double* output,
    r::Diagnostics* diagnostics, char* error, std::size_t capacity, Function function) {
    return boundary(diagnostics,error,capacity,[&](Buffers& buffers) {
        buffers.arrays(values,1); buffers.output(output,1);
    },[&](r::Diagnostics& state) {
        const auto value=function(r::Array(*values),state).value; *output=value;
    });
}

void publish_tensor(const r::arithmetic::Tensor& value, double* output, std::size_t count) {
    if (value.size()!=count) throw std::invalid_argument("zone output extent is incorrect");
    std::copy(value.values.begin(),value.values.end(),output);
}
}  // namespace

extern "C" int TPMSHX_RESULT_CALL tpmshx_result_balance_norms_v1(
    const r::RawArray* residual, b::NormValues* output, r::Diagnostics* diagnostics,
    char* error, std::size_t capacity) {
    return boundary(diagnostics,error,capacity,[&](Buffers& buffers) {
        buffers.arrays(residual,1); buffers.output(output,1);
    },[&](r::Diagnostics& state) {
        const auto value=b::norms(*residual,state); *output=value;
    });
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_balance_mass_v1(
    const r::RawArray* faces, std::size_t dimension, b::MassValues* output,
    r::Diagnostics* diagnostics, char* error, std::size_t capacity) {
    return boundary(diagnostics,error,capacity,[&](Buffers& buffers) {
        buffers.arrays(faces,dimension); buffers.output(output,1);
    },[&](r::Diagnostics& state) {
        const auto value=b::mass(faces,dimension,state); *output=value;
    });
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_balance_planes_v1(
    const r::RawArray* planes, std::size_t count, b::PlaneValues* output,
    r::Diagnostics* diagnostics, char* error, std::size_t capacity) {
    return boundary(diagnostics,error,capacity,[&](Buffers& buffers) {
        buffers.arrays(planes,count); buffers.output(output,1);
    },[&](r::Diagnostics& state) {
        const auto value=b::plane_sums(planes,count,state); *output=value;
    });
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_balance_energy_v1(
    const b::EnergyPhase* phases, std::size_t count, double reservoir,
    b::EnergyValues* output, r::Diagnostics* diagnostics, char* error, std::size_t capacity) {
    return boundary(diagnostics,error,capacity,[&](Buffers& buffers) {
        buffers.input(phases,count); buffers.output(output,1);
    },[&](r::Diagnostics&) {
        const auto value=b::energy(phases,count,reservoir); *output=value;
    });
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_temperatures_2d_v1(
    const r::RawArray* widths,const r::RawLabels* labels,const r::RawArray* temperatures,
    size_t zone_count,tpmshx_result_zone_temperatures_v1* output,double length_m,double height_m,
    const double* x_fractions,size_t nx,double* x_positions,
    const double* y_fractions,size_t ny,double* y_positions,r::Diagnostics* diagnostics,
    char* error,size_t capacity) {
    return r::c_api::capture_zone_temperatures_2d(widths,labels,temperatures,zone_count,output,length_m,height_m,
        x_fractions,nx,x_positions,y_fractions,ny,y_positions,diagnostics,error,capacity);
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_mean_v1(
    const r::RawArray* values, const r::RawArray* weights, std::uint32_t weighted,
    double* output, r::Diagnostics* diagnostics, char* error, std::size_t capacity) {
    return zone_weighted(values,weights,weighted,output,diagnostics,error,capacity,b::zone_mean);
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_std_v1(
    const r::RawArray* values, const r::RawArray* weights, std::uint32_t weighted,
    double* output, r::Diagnostics* diagnostics, char* error, std::size_t capacity) {
    return zone_weighted(values,weights,weighted,output,diagnostics,error,capacity,b::zone_std);
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_minimum_v1(
    const r::RawArray* values, double* output, r::Diagnostics* diagnostics,
    char* error, std::size_t capacity) {
    return zone_reduction(values,output,diagnostics,error,capacity,
        [](const r::Array& field,r::Diagnostics&) {return b::zone_minimum(field);});
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_maximum_v1(
    const r::RawArray* values, double* output, r::Diagnostics* diagnostics,
    char* error, std::size_t capacity) {
    return zone_reduction(values,output,diagnostics,error,capacity,
        [](const r::Array& field,r::Diagnostics&) {return b::zone_maximum(field);});
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_spread_v1(
    const r::RawArray* values, double* output, r::Diagnostics* diagnostics,
    char* error, std::size_t capacity) {
    return zone_reduction(values,output,diagnostics,error,capacity,b::zone_spread);
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_power_two_v1(
    const r::RawArray* values, double* output, std::size_t count,
    r::Diagnostics* diagnostics, char* error, std::size_t capacity) {
    return boundary(diagnostics,error,capacity,[&](Buffers& buffers) {
        buffers.arrays(values,1); buffers.output(output,count);
    },[&](r::Diagnostics& state) {
        publish_tensor(b::zone_power_two(r::Array(*values),state),output,count);
    });
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_speed_from_squared_v1(
    const r::RawArray* u, const r::RawArray* v, double* output, std::size_t count,
    r::Diagnostics* diagnostics, char* error, std::size_t capacity) {
    return boundary(diagnostics,error,capacity,[&](Buffers& buffers) {
        buffers.arrays(u,1); buffers.arrays(v,1); buffers.output(output,count);
    },[&](r::Diagnostics& state) {
        publish_tensor(b::zone_speed_from_squared(r::Array(*u),r::Array(*v),state),output,count);
    });
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_cv_v1(
    double deviation, double mean, double* output, r::Diagnostics* diagnostics,
    char* error, std::size_t capacity) {
    return boundary(diagnostics,error,capacity,[&](Buffers& buffers) {
        buffers.output(output,1);
    },[&](r::Diagnostics&) {
        const auto value=b::zone_cv(deviation,mean); *output=value;
    });
}
