#pragma once

#include "tpmshx/result_balance.hpp"
#include "result_c_boundary.hpp"

namespace tpmshx::result::c_api {

inline int capture_zone_temperatures_2d(
    const RawArray* widths, const RawArray* labels, const RawArray* temperatures,
    std::size_t zone_count, tpmshx_result_zone_temperatures_v1* output, double length_m, double height_m,
    const double* x_fractions, std::size_t nx, double* x_positions,
    const double* y_fractions, std::size_t ny, double* y_positions,
    Diagnostics* diagnostics, char* error, std::size_t capacity) {
    return boundary(diagnostics,error,capacity,[&](Buffers& buffers) {
        buffers.arrays(widths,2); buffers.arrays(labels,1); buffers.arrays(temperatures,3);
        buffers.output(output,zone_count);
        buffers.input(x_fractions,nx); buffers.output(x_positions,nx);
        buffers.input(y_fractions,ny); buffers.output(y_positions,ny);
    },[&](Diagnostics& state) {
        const auto rows=balance::zone_temperatures_2d(widths,*labels,temperatures,zone_count,state);
        std::copy(rows.begin(),rows.end(),output);
        for (std::size_t i=0;i<nx;++i) x_positions[i]=x_fractions[i]*length_m;
        for (std::size_t i=0;i<ny;++i) y_positions[i]=y_fractions[i]*height_m;
    });
}

}  // namespace tpmshx::result::c_api
