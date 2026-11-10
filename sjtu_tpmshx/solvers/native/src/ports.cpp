#include "tpmshx/ports.hpp"
#include "tpmshx/grid.hpp"
#include "tpmshx/scalar_precision.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace tpmshx {
namespace {
namespace g=grid;
namespace p=geometry::detail;
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
g::Scalar spacing(g::Scalar scale) {
    const auto bits=scale.strong==2?g::result_precision(scale,{0.,16,1}):scale.precision;
    scale.value=p::round_scalar(scale.value,bits);
    double value;
    if (!std::isfinite(scale.value)) value=std::numeric_limits<double>::quiet_NaN();
    else if (bits==16) {
        if (scale.value==65504.) value=std::numeric_limits<double>::infinity();
        else if (scale.value==0.) value=std::ldexp(1.,-24);
        else {int exponent=0;std::frexp(scale.value,&exponent);value=std::ldexp(1.,std::max(-24,exponent-11));}
    } else if (bits==32) {
        const float x=static_cast<float>(scale.value);
        value=static_cast<double>(std::nextafter(x,std::numeric_limits<float>::infinity())-x);
    } else value=std::nextafter(scale.value,std::numeric_limits<double>::infinity())-scale.value;
    return {value,bits,1};
}
g::Scalar tolerance(g::Scalar lower,g::Scalar upper,double last,std::uint32_t bits) {
    g::Scalar selected{std::abs(lower.value),lower.precision,lower.strong};
    const g::Scalar high{std::abs(upper.value),upper.precision,upper.strong};
    if (g::less(selected,high)) selected=high;
    const g::Scalar length{std::abs(last),bits,1};
    if (g::less(selected,length)) selected=length;
    return g::multiply(g::weak(8.),spacing(selected));
}
}
std::vector<double> port_overlap_1d_typed(ArrayView<const double> widths,std::uint32_t bits,
                                        const grid::Scalar& lower,const grid::Scalar& upper,bool staggered) {
    p::require_precision(bits);
    if (widths.size && !widths.data) throw std::invalid_argument("nonempty cell widths are null");
    if (!widths.size) return {};
    const auto edges=g::cumulative_widths(widths,bits);
    const auto roundoff=tolerance(lower,upper,edges.back(),bits);
    auto upper_edges=edges;
    if (staggered) {
        for (std::size_t i=0;i<widths.size;++i)
            upper_edges[i+1]=g::subtract({edges[i+1],bits,1},g::divide({widths[i],bits,1},g::weak(2.))).value;
        upper_edges.push_back(edges.back());
    }
    const auto upper_bits=g::result_precision({0.,bits,1},upper);
    const auto lower_bits=g::result_precision({0.,staggered?bits:64,1},lower);
    const double hi=p::round_scalar(upper.value,upper_bits);
    const double lo=p::round_scalar(lower.value,lower_bits);
    std::vector<double> result(upper_edges.size()-1);
    for (std::size_t i=0;i<result.size();++i) {
        const double high=minimum(p::round_scalar(upper_edges[i+1],upper_bits),hi);
        const double low=maximum(p::round_scalar(upper_edges[i],lower_bits),lo);
        auto overlap=g::subtract({high,upper_bits,1},{low,lower_bits,1});
        const auto comparison_bits=g::result_precision(overlap,roundoff);
        if (p::round_scalar(std::abs(overlap.value),comparison_bits)<=p::round_scalar(roundoff.value,comparison_bits))
            overlap.value=0.;
        const auto width=staggered?g::subtract({upper_edges[i+1],bits,1},{upper_edges[i],bits,1}):g::Scalar{widths[i],bits,1};
        result[i]=std::clamp(g::divide(overlap,width).value,0.,1.);
    }
    return result;
}
std::vector<double> port_overlap_1d(ArrayView<const double> widths,double lo,double hi,bool staggered) {
    require_solver_widths(widths,lo,hi);
    return port_overlap_1d_typed(widths,64,g::weak(lo),g::weak(hi),staggered);
}
std::pair<std::vector<double>,std::vector<double>> port_fractions_1d_typed(
    ArrayView<const double> widths,std::uint32_t bits,const grid::Scalar& lo,const grid::Scalar& hi,bool uniform) {
    auto raw=port_overlap_1d_typed(widths,bits,lo,hi,false),profile=raw;
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
    return port_fractions_1d_typed(widths,64,g::weak(lo),g::weak(hi),uniform);
}
}  // namespace tpmshx
