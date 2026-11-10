#pragma once
#include "tpmshx/finite_volume.hpp"
#include <utility>
#include <vector>

namespace tpmshx {
// Keep the original full-solver double rule.
std::vector<double> port_overlap_1d(ArrayView<const double> widths,double lo,double hi,bool staggered=false);
std::pair<std::vector<double>,std::vector<double>> port_fractions_1d(
    ArrayView<const double> widths,double lo,double hi,bool uniform=false);

}  // namespace tpmshx
