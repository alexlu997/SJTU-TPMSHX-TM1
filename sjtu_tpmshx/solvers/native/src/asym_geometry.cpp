#include "tpmshx/asym_geometry.hpp"
#include "tpmshx/scalar_precision.hpp"
#include "geometry/marching_cubes.hpp"
#include <cmath>
#include <limits>
#include <stdexcept>

namespace tpmshx::geometry::asym {
namespace {
std::size_t voxel_count(const Shape& shape) {
    if (!shape[0] || !shape[1] || !shape[2]) return 0;
    std::size_t count=1;
    for (const auto size:shape) {
        if (count>std::numeric_limits<std::size_t>::max()/size)
            throw std::invalid_argument("asymmetric geometry shape is too large");
        count*=size;
    }
    if (count>static_cast<std::size_t>(std::numeric_limits<std::int64_t>::max()/6))
        throw std::invalid_argument("asymmetric geometry face count exceeds int64 range");
    return count;
}
template<class T> void check_view(ArrayView<const T> values) {
    if (values.size && !values.data) throw std::invalid_argument("asymmetric geometry input has a null buffer");
}
template<class T> void check_shape(ArrayView<const T> values, const Shape& shape) {
    check_view(values);
    if (values.size!=voxel_count(shape))
        throw std::invalid_argument("asymmetric geometry input size disagrees with shape");
}
double divide(double numerator, double denominator) {
    if (denominator==0.) throw std::domain_error("float division by zero");
    return numerator/denominator;
}
Levels double_levels(double C, double delta) {
    return {delta-C,delta+C,delta-C,delta+C,64,64};
}
struct Masks { std::vector<std::uint8_t> solid, a, b; };
Masks masks(ArrayView<const double> phi, const Levels& levels) {
    Masks result;
    result.solid.resize(phi.size); result.a.resize(phi.size); result.b.resize(phi.size);
    const double lower=levels.comparison_lower, upper=levels.comparison_upper;
    for (std::size_t i=0; i<phi.size; ++i) {
        // These tests are independent, including negative and NaN thresholds.
        result.solid[i]=(phi[i]>=lower) && (phi[i]<=upper);
        result.a[i]=phi[i]<lower;
        result.b[i]=phi[i]>upper;
    }
    return result;
}
ArrayView<const std::uint8_t> view(const std::vector<std::uint8_t>& values) {
    return {values.data(),values.size()};
}
}  // namespace

Porosity eps_sides(ArrayView<const double> phi, const Levels& levels) {
    check_view(phi);
    if (!phi.size) {
        const auto nan=std::numeric_limits<double>::quiet_NaN();
        return {nan,nan,nan};
    }
    std::size_t count_a=0, count_b=0;
    const double lower=levels.comparison_lower, upper=levels.comparison_upper;
    for (std::size_t i=0; i<phi.size; ++i) {
        count_a+=phi[i]<lower;
        count_b+=phi[i]>upper;
    }
    const double a=static_cast<double>(count_a)/static_cast<double>(phi.size);
    const double b=static_cast<double>(count_b)/static_cast<double>(phi.size);
    return {a,b,a+b};
}

std::int64_t count_interface(ArrayView<const std::uint8_t> a,
                             ArrayView<const std::uint8_t> b, const Shape& shape) {
    check_shape(a,shape); check_shape(b,shape);
    if (!a.size) return 0;
    std::int64_t count=0;
    const std::array<std::size_t,3> strides={shape[1]*shape[2],shape[2],1};
    for (std::size_t axis=0; axis<3; ++axis) {
        for (std::size_t x=0; x<shape[0]; ++x)
            for (std::size_t y=0; y<shape[1]; ++y)
                for (std::size_t z=0; z<shape[2]; ++z) {
                    const Shape index={x,y,z};
                    if (index[axis]+1>=shape[axis]) continue;
                    const std::size_t i=(x*shape[1]+y)*shape[2]+z, j=i+strides[axis];
                    count+=(a[i]!=0) && (b[j]!=0);
                    count+=(b[i]!=0) && (a[j]!=0);
                }
    }
    return count;
}

Sides a0_sides(ArrayView<const double> phi, const Shape& shape, const Levels& levels,
               double length_m, double N, double area_correction) {
    check_shape(phi,shape);
    const auto phases=masks(phi,levels);
    const double dx=divide(length_m,N);
    const double norm=std::pow(length_m,3.)*area_correction;
    const auto count_a=count_interface(view(phases.solid),view(phases.a),shape);
    const auto count_b=count_interface(view(phases.solid),view(phases.b),shape);
    const double a=divide(static_cast<double>(count_a)*std::pow(dx,2.),norm);
    const double b=divide(static_cast<double>(count_b)*std::pow(dx,2.),norm);
    return {a,b};
}

Sides a0_sides_mc(ArrayView<const double> phi, const Shape& shape, const Levels& levels,
                  double length_m, double N) {
    check_shape(phi,shape);
    const double dx=divide(length_m,N);
    const double volume=std::pow(length_m,3.);
    if (!phi.size) throw std::invalid_argument("zero-size array has no reduction minimum or maximum");
    double minimum=phi[0], maximum=phi[0];
    for (std::size_t i=0; i<phi.size; ++i) {
        if (std::isnan(phi[i])) { minimum=maximum=phi[i]; break; }
        if (phi[i]<minimum) minimum=phi[i];
        if (phi[i]>maximum) maximum=phi[i];
    }
    std::vector<float> converted;
    const auto iso_area=[&](double level, std::uint32_t precision) {
        // Retain the level scalar's comparison precision before the mesh cast.
        if (level<=detail::round_scalar(minimum,precision) ||
            level>=detail::round_scalar(maximum,precision)) return 0.;
        if (converted.empty()) {
            converted.reserve(phi.size);
            for (std::size_t i=0; i<phi.size; ++i) converted.push_back(static_cast<float>(phi[i]));
        }
        return tpmshx::geometry::marching_cubes::area(converted.data(),shape[0],shape[1],shape[2],level,{dx,dx,dx});
    };
    const double a=divide(iso_area(levels.lower,levels.lower_precision),volume);
    const double b=divide(iso_area(levels.upper,levels.upper_precision),volume);
    return {a,b};
}

Sides dh_from_sides(double eps_a, double eps_b, double area_a, double area_b) {
    return {area_a>0. ? 4.*eps_a/area_a : 0., area_b>0. ? 4.*eps_b/area_b : 0.};
}
Sides dh_sides(ArrayView<const double> phi, const Shape& shape, const Levels& levels,
               double length_m, double N, double area_correction, bool mc) {
    const auto eps=eps_sides(phi,levels);
    const auto areas=mc ? a0_sides_mc(phi,shape,levels,length_m,N)
                       : a0_sides(phi,shape,levels,length_m,N,area_correction);
    return dh_from_sides(eps.a,eps.b,areas[0],areas[1]);
}
double wall_thickness_from_sides(double eps_total, double area_a, double area_b) {
    const double wall_area=.5*(area_a+area_b);
    return wall_area>0. ? (1.-eps_total)/wall_area : 0.;
}
double wall_thickness(ArrayView<const double> phi, const Shape& shape, const Levels& levels,
                      double length_m, double N, double area_correction) {
    const auto eps=eps_sides(phi,levels);
    const auto areas=a0_sides(phi,shape,levels,length_m,N,area_correction);
    return wall_thickness_from_sides(eps.total,areas[0],areas[1]);
}
double split_a(ArrayView<const double> phi, const Levels& levels, bool zero_delta) {
    if (zero_delta) return .5;
    const auto eps=eps_sides(phi,levels);
    return divide(eps.a,eps.a+eps.b);
}
SplitFields split_porosity(ArrayView<const double> eps_total, double fraction_a) {
    check_view(eps_total);
    SplitFields result;
    result.a.resize(eps_total.size); result.b.resize(eps_total.size);
    for (std::size_t i=0; i<eps_total.size; ++i) {
        result.a[i]=eps_total[i]*fraction_a;
        result.b[i]=eps_total[i]*(1.-fraction_a);
    }
    return result;
}
PreparedSides prepare_sides(ArrayView<const double> phi, const Shape& shape, const Levels& levels,
                            const Levels& reference_levels, bool zero_delta,
                            double length_m, double N, double area_correction) {
    if (zero_delta) return {.5,std::nullopt};
    const double fraction=split_a(phi,levels,false);
    const auto area=a0_sides(phi,shape,levels,length_m,N,area_correction);
    const auto diameter=dh_sides(phi,shape,levels,length_m,N,area_correction,true);
    const auto reference_area=a0_sides(phi,shape,reference_levels,length_m,N,area_correction);
    const auto reference_diameter=dh_sides(phi,shape,reference_levels,length_m,N,area_correction,true);
    return {fraction,std::array<ThermalSide,2>{{
        {area[0],diameter[0],reference_area[0],reference_diameter[0]},
        {area[1],diameter[1],reference_area[1],reference_diameter[1]}}}};
}

double split_from_index(const PhiIndex& index, const Calibration& model,
                        double cell_mm, double wall_mm, double delta) {
    if (delta == 0.) return .5;
    const double C = level_set_threshold(model.level_set, divide(wall_mm, cell_mm));
    const auto& phi = index.phi();
    return split_a({phi.data(), phi.size()}, double_levels(C,delta), false);
}

PreparedSides prepare_from_index(const PhiIndex& index, const Calibration& model,
                                 double cell_mm, double wall_mm, double delta) {
    if (delta == 0.) return {.5, std::nullopt};
    const double C = level_set_threshold(model.level_set, divide(wall_mm, cell_mm));
    const auto& phi = index.phi();
    return prepare_sides({phi.data(), phi.size()}, index.shape(), double_levels(C,delta),
                         double_levels(C,0.), false,
                         cell_mm / 1000., static_cast<double>(index.resolution()),
                         model.area_correction);
}
}  // namespace tpmshx::geometry::asym
