#include "tpmshx/ports.hpp"
#include "tpmshx/grid.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace tpmshx {
namespace {
namespace g=grid;
void require_solver_widths(ArrayView<const double> widths,double lower,double upper) {
    if (!widths.size || !std::isfinite(lower) || !std::isfinite(upper))
        throw std::invalid_argument("port overlap requires nonempty widths and finite endpoints");
    if (!widths.data) throw std::invalid_argument("cell widths has incorrect extent");
    for (std::size_t i=0;i<widths.size;++i)
        if (!std::isfinite(widths[i]) || widths[i]<=0.)
            throw std::invalid_argument("cell widths must be finite and positive");
}
double minimum(double first,double second) {
    if (std::isnan(first)) return first;
    if (std::isnan(second)) return second;
    return std::min(first,second);
}
double maximum(double first,double second) {
    if (std::isnan(first)) return first;
    if (std::isnan(second)) return second;
    return std::max(first,second);
}
// The spacing to the next larger double, as np.spacing returns for float64.
double spacing(double scale) {
    if (!std::isfinite(scale)) return std::numeric_limits<double>::quiet_NaN();
    return std::nextafter(scale,std::numeric_limits<double>::infinity())-scale;
}
double tolerance(double lower,double upper,double last) {
    double selected=std::abs(lower);
    const double high=std::abs(upper);
    if (selected<high) selected=high;
    const double length=std::abs(last);
    if (selected<length) selected=length;
    return 8.*spacing(selected);
}
}
std::vector<double> port_overlap_1d_unchecked(ArrayView<const double> widths,
                                              double lower,double upper,bool staggered) {
    if (widths.size && !widths.data) throw std::invalid_argument("nonempty cell widths are null");
    if (!widths.size) return {};
    const auto edges=g::cumulative_widths(widths);
    const double roundoff=tolerance(lower,upper,edges.back());
    auto upper_edges=edges;
    if (staggered) {
        for (std::size_t i=0;i<widths.size;++i) upper_edges[i+1]=edges[i+1]-widths[i]/2.;
        upper_edges.push_back(edges.back());
    }
    std::vector<double> result(upper_edges.size()-1);
    for (std::size_t i=0;i<result.size();++i) {
        const double high=minimum(upper_edges[i+1],upper);
        const double low=maximum(upper_edges[i],lower);
        double overlap=high-low;
        if (std::abs(overlap)<=roundoff) overlap=0.;
        const double width=staggered?upper_edges[i+1]-upper_edges[i]:widths[i];
        result[i]=std::clamp(overlap/width,0.,1.);
    }
    return result;
}
std::vector<double> port_overlap_1d(ArrayView<const double> widths,double lo,double hi,bool staggered) {
    require_solver_widths(widths,lo,hi);
    return port_overlap_1d_unchecked(widths,lo,hi,staggered);
}
std::pair<std::vector<double>,std::vector<double>> port_fractions_1d_unchecked(
    ArrayView<const double> widths,double lo,double hi,bool uniform) {
    auto raw=port_overlap_1d_unchecked(widths,lo,hi,false),profile=raw;
    if (!uniform) for (std::size_t i=0;i<raw.size();++i) if (raw[i]>.99)
        for (std::size_t distance=1;distance<5;++distance)
            if ((i>=distance && raw[i-distance]<.01) || (i+distance<raw.size() && raw[i+distance]<.01)) {
                profile[i]=1.-.8*std::exp(-static_cast<double>(distance));break;
            }
    return {std::move(raw),std::move(profile)};
}
std::pair<std::vector<double>,std::vector<double>> port_fractions_1d(
    ArrayView<const double> widths,double lo,double hi,bool uniform) {
    require_solver_widths(widths,lo,hi);
    return port_fractions_1d_unchecked(widths,lo,hi,uniform);
}
double inlet_profile_scale(bool differs,double geometric_area,double profile_area) {
    return differs && profile_area>1e-30 && geometric_area>0. ? geometric_area/profile_area : 1.;
}
}  // namespace tpmshx
