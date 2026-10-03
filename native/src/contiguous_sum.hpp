#pragma once

#include "tpmshx/enthalpy_sweeps.hpp"

#include <algorithm>
#include <array>
#include <numeric>

namespace tpmshx::detail {

// Preserve the NumPy contiguous reduction order at numerical handoffs. Tiny
// pressure-anchor changes can alter a later SIMPLE stopping iteration.
inline double contiguous_sum(ArrayView<const double> x) {
    if (!x.size) return -0.;
    if (x.size<8) return std::accumulate(x.data,x.data+x.size,-0.);
    if (x.size>128) {
        const auto middle=(x.size/2)/8*8;
        return contiguous_sum({x.data,middle})+contiguous_sum({x.data+middle,x.size-middle});
    }
    std::array<double,8> partial;
    std::copy_n(x.data,8,partial.begin());
    std::size_t i=8;
    for (;i+8<=x.size;i+=8)
        for (std::size_t lane=0;lane<8;++lane) partial[lane]+=x[i+lane];
    double value=((partial[0]+partial[1])+(partial[2]+partial[3]))
                +((partial[4]+partial[5])+(partial[6]+partial[7]));
    for (;i<x.size;++i) value+=x[i];
    return value;
}

}  // namespace tpmshx::detail
