#pragma once
#include "tpmshx/finite_volume.hpp"
#include <cstdint>
#include <utility>
#include <vector>

namespace tpmshx {
namespace grid {struct Scalar;}

// Keep the original full-solver double rule.
std::vector<double> port_overlap_1d(ArrayView<const double> widths,double lo,double hi,bool staggered=false);
std::pair<std::vector<double>,std::vector<double>> port_fractions_1d(
    ArrayView<const double> widths,double lo,double hi,bool uniform=false);

// Values borrow original IEEE width values; precision retains their array arithmetic.
std::vector<double> port_overlap_1d_typed(ArrayView<const double> widths,std::uint32_t width_precision,
    const grid::Scalar& lo,const grid::Scalar& hi,bool staggered=false);
std::pair<std::vector<double>,std::vector<double>> port_fractions_1d_typed(
    ArrayView<const double> widths,std::uint32_t width_precision,const grid::Scalar& lo,
    const grid::Scalar& hi,bool uniform=false);
}  // namespace tpmshx
