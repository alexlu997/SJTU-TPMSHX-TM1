#include "tpmshx/result_balance.hpp"
#include "result_c_boundary.hpp"

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
    r::RawScalar* output, r::Diagnostics* diagnostics, char* error, std::size_t capacity,
    Function function) {
    return boundary(diagnostics,error,capacity,[&](Buffers& buffers) {
        buffers.arrays(values,1); buffers.arrays(weights,weighted?1:0); buffers.output(output,1);
    },[&](r::Diagnostics& state) {
        flag(weighted);
        const auto value=r::pack_scalar(function(*values,weighted?weights:nullptr,state));
        *output=value;
    });
}

template<class Function> int zone_reduction(const r::RawArray* values, r::RawScalar* output,
    r::Diagnostics* diagnostics, char* error, std::size_t capacity, Function function) {
    return boundary(diagnostics,error,capacity,[&](Buffers& buffers) {
        buffers.arrays(values,1); buffers.output(output,1);
    },[&](r::Diagnostics& state) {
        const auto value=r::pack_scalar(function(*values,state)); *output=value;
    });
}

void publish_tensor(const r::arithmetic::Tensor& value, unsigned char* output,
    std::size_t capacity, r::RawScalar* output_type) {
    if (value.bytes.size()!=capacity)
        throw std::invalid_argument("zone output byte capacity is incorrect");
    r::RawScalar kind{};
    kind.dtype=value.dtype; kind.origin=TPMSHX_RESULT_NUMPY_SCALAR;
    kind.byte_order=TPMSHX_RESULT_NATIVE_ENDIAN;
    std::copy(value.bytes.begin(),value.bytes.end(),output); *output_type=kind;
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
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_mean_v1(
    const r::RawArray* values, const r::RawArray* weights, std::uint32_t weighted,
    r::RawScalar* output, r::Diagnostics* diagnostics, char* error, std::size_t capacity) {
    return zone_weighted(values,weights,weighted,output,diagnostics,error,capacity,b::zone_mean);
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_std_v1(
    const r::RawArray* values, const r::RawArray* weights, std::uint32_t weighted,
    r::RawScalar* output, r::Diagnostics* diagnostics, char* error, std::size_t capacity) {
    return zone_weighted(values,weights,weighted,output,diagnostics,error,capacity,b::zone_std);
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_minimum_v1(
    const r::RawArray* values, r::RawScalar* output, r::Diagnostics* diagnostics,
    char* error, std::size_t capacity) {
    return zone_reduction(values,output,diagnostics,error,capacity,b::zone_minimum);
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_maximum_v1(
    const r::RawArray* values, r::RawScalar* output, r::Diagnostics* diagnostics,
    char* error, std::size_t capacity) {
    return zone_reduction(values,output,diagnostics,error,capacity,b::zone_maximum);
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_spread_v1(
    const r::RawArray* values, r::RawScalar* output, r::Diagnostics* diagnostics,
    char* error, std::size_t capacity) {
    return zone_reduction(values,output,diagnostics,error,capacity,b::zone_spread);
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_power_two_v1(
    const r::RawArray* values, unsigned char* output, std::size_t output_capacity,
    r::RawScalar* output_type, r::Diagnostics* diagnostics, char* error, std::size_t capacity) {
    return boundary(diagnostics,error,capacity,[&](Buffers& buffers) {
        buffers.arrays(values,1); buffers.output_bytes(output,output_capacity); buffers.output(output_type,1);
    },[&](r::Diagnostics& state) {
        if (r::Array(*values).size() && !output_capacity)
            throw std::invalid_argument("zone output byte capacity is incorrect");
        const auto value=b::zone_power_two(*values,state);
        publish_tensor(value,output,output_capacity,output_type);
    });
}
extern "C" int TPMSHX_RESULT_CALL tpmshx_result_zone_speed_from_squared_v1(
    const r::RawArray* u, const r::RawArray* v, unsigned char* output, std::size_t output_capacity,
    r::RawScalar* output_type, r::Diagnostics* diagnostics, char* error, std::size_t capacity) {
    return boundary(diagnostics,error,capacity,[&](Buffers& buffers) {
        buffers.arrays(u,1); buffers.arrays(v,1);
        buffers.output_bytes(output,output_capacity); buffers.output(output_type,1);
    },[&](r::Diagnostics& state) {
        if (r::Array(*u).size() && !output_capacity)
            throw std::invalid_argument("zone speed byte capacity is incorrect");
        const auto value=b::zone_speed_from_squared(*u,*v,state);
        publish_tensor(value,output,output_capacity,output_type);
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
