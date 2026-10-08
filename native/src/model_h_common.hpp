#pragma once
// Shared by the actual 2D and 3D model-h thermal drivers.
#include "tpmshx/fluid_properties.hpp"
#include "tpmshx/temperature_driver.hpp"
#include "tpmshx/model_coefficients.hpp"
#include <Eigen/Dense>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <deque>
#include <limits>
#include <stdexcept>
#include <vector>
#ifdef __APPLE__
#include "anderson_lapack.hpp"
#endif

namespace tpmshx::model_h_common {
template <typename T> ArrayView<const double> view(const T& x) { return {x.data(), x.size()}; }
inline ArrayView<const double> view(ArrayView<double> x) { return {x.data, x.size}; }

inline std::size_t product(std::size_t a, std::size_t b) {
    if (!a || !b || a > std::numeric_limits<std::size_t>::max()/b)
        throw std::invalid_argument("invalid model-h grid extent");
    return a*b;
}
template <typename T> void check(ArrayView<T> x, std::size_t n, bool finite = true) {
    if (!x.data || x.size != n) throw std::invalid_argument("model-h array extent mismatch");
    if (finite)
        for (std::size_t p=0; p<n; ++p)
            if (!std::isfinite(x[p])) throw std::invalid_argument("nonfinite model-h input");
}
inline void coefficient(ArrayView<const double> x, std::size_t n, bool positive = false) {
    check(x,n);
    for (std::size_t p=0; p<n; ++p)
        if (positive ? x[p]<=0 : x[p]<0) throw std::invalid_argument("invalid model-h coefficient");
}
inline void disjoint(ArrayView<const double> a, ArrayView<const double> b) {
    if (!a.size || !b.size) return;
    const auto ap=reinterpret_cast<std::uintptr_t>(a.data), bp=reinterpret_cast<std::uintptr_t>(b.data);
    const auto maximum=std::numeric_limits<std::uintptr_t>::max();
    if (a.size>(maximum-ap)/sizeof(double) || b.size>(maximum-bp)/sizeof(double)
        || (ap<bp+b.size*sizeof(double) && bp<ap+a.size*sizeof(double)))
        throw std::invalid_argument("model-h input/output arrays overlap");
}
inline const std::array<double,5>& coefficients(Fluid fluid) {
    if (fluid==Fluid::air) return model_coefficients::model_h_air;
    if (fluid==Fluid::water) return model_coefficients::model_h_water;
    throw std::invalid_argument("model-h requires air or water");
}
inline double optional(ArrayView<const double> x, std::size_t p, double fallback) {
    return x.size ? x[p] : fallback;
}
inline double enthalpy(double t, const std::array<double,5>& cp) {
    const double x=t-cp[3], x0=cp[4]-cp[3];
    return cp[0]*(x-x0)+0.5*cp[1]*(x*x-x0*x0)+cp[2]/3.0*(x*x*x-x0*x0*x0);
}
inline double increment(double tm, double t, double tp, double dm, double dp, double offset) {
    const double a=(t-tm)/dm, b=(tp-t)/dp;
    if (a*b<=0) return 0;
    return (a<0 ? -std::min(std::abs(a),std::abs(b)) : std::min(std::abs(a),std::abs(b)))*offset;
}
// Endpoint geometry matches the existing high-order enthalpy transport:
// a defined incoming state lies at the boundary face, half a cell away;
// an outgoing end uses its available interior slope. This reconstructs T,
// leaving the model-h caller responsible for evaluating the existing h(T).
inline double boundary_increment(double t, double neighbor, double distance,
        double inlet, double half_width, bool known_inflow, bool low_end,
        double offset) {
    if (known_inflow)
        return low_end ? increment(inlet,t,neighbor,half_width,distance,offset)
                       : increment(neighbor,t,inlet,distance,half_width,offset);
    return (low_end ? neighbor-t : t-neighbor)/distance*offset;
}
inline Eigen::VectorXd pack(TemperatureStateView t, bool solve_b=true) {
    const std::size_t count=solve_b ? 3 : 2;
    Eigen::VectorXd values(static_cast<Eigen::Index>(count*t.a.size));
    const ArrayView<double> fields[]{t.a,solve_b ? t.b : t.solid,t.solid};
    for (std::size_t side=0; side<count; ++side)
        std::copy(fields[side].data,fields[side].data+fields[side].size,values.data()+side*t.a.size);
    return values;
}
inline void restore(TemperatureStateView t, const Eigen::VectorXd& values, bool solve_b=true) {
    const ArrayView<double> fields[]{t.a,solve_b ? t.b : t.solid,t.solid};
    for (std::size_t side=0; side<(solve_b ? 3U : 2U); ++side)
        std::copy(values.data()+side*t.a.size,values.data()+(side+1)*t.a.size,fields[side].data);
}

inline double energy_scale(const GridView& g, ArrayView<const double> hv_a,
                           ArrayView<const double> hv_b, TemperatureStateView t) {
    double qa=0.,qb=0.;
    for(std::size_t i=0;i<g.nx;++i) for(std::size_t j=0;j<g.ny;++j)
        for(std::size_t k=0;k<g.nz;++k) {
            const auto p=(i*g.ny+j)*g.nz+k;
            const double volume=g.dx[i]*g.dy[j]*g.dz[k];
            qa+=hv_a[p]*(t.a[p]-t.solid[p])*volume;
            qb+=hv_b[p]*(t.solid[p]-t.b[p])*volume;
        }
    return std::max({std::abs(qa),std::abs(qb),1.});
}

// Existing Type-II Anderson policy: model-h defaults to six (x,r) samples,
// five differences. Outer property coupling supplies its original m+1 limit.
// macOS follows the locked NumPy LAPACK calls; the existing Eigen path on
// other platforms still requires native full-case qualification.
struct Anderson {
    std::deque<Eigen::VectorXd> x, r;
    std::size_t history_limit;
    double condition_limit;
    explicit Anderson(std::size_t history=6,double condition=1e10)
        : history_limit(history),condition_limit(condition) {}
    void reset() { x.clear(); r.clear(); }
    void push(Eigen::VectorXd previous, const Eigen::VectorXd& image) {
        r.push_back(image-previous); x.push_back(std::move(previous));
        if (x.size()>history_limit) { x.pop_front(); r.pop_front(); }
    }
    bool candidate(const Eigen::VectorXd& image, Eigen::VectorXd& output) const {
        if (x.size()<2) return false;
        const auto count=static_cast<Eigen::Index>(x.size()-1);
        Eigen::MatrixXd dx(image.size(),count), dr(image.size(),count);
        for (Eigen::Index i=0; i<count; ++i) {
            dx.col(i)=x[static_cast<std::size_t>(i+1)]-x[static_cast<std::size_t>(i)];
            dr.col(i)=r[static_cast<std::size_t>(i+1)]-r[static_cast<std::size_t>(i)];
        }
        if (!dr.allFinite()) return false;
#ifdef __APPLE__
        return lapack_anderson(dx,dr,r.back(),image,condition_limit,output);
#else
        Eigen::JacobiSVD<Eigen::MatrixXd> svd(dr,Eigen::ComputeThinU|Eigen::ComputeThinV);
        const auto& singular=svd.singularValues();
        if (svd.info()!=Eigen::Success || singular.size()==0 || singular[0]==0
            || singular[0]/std::max(singular[singular.size()-1],1e-30)>condition_limit) return false;
        svd.setThreshold(std::numeric_limits<double>::epsilon()*static_cast<double>(std::max(dr.rows(),dr.cols())));
        output=image-(dx+dr)*svd.solve(r.back());
        return output.allFinite();
#endif
    }
};

}  // namespace tpmshx::model_h_common
