#pragma once
// Shared by the actual 2D and 3D model-h thermal drivers.
#include "anderson.hpp"
#include "tpmshx/model_h_iteration.hpp"
#include "tpmshx/temperature_driver.hpp"
#include "tpmshx/model_coefficients.hpp"
#include <Eigen/Dense>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

namespace tpmshx::model_h_common {
inline void validate_iteration_overrides(const ModelHIterationOverrides& options) {
    for(double value:{options.temperature_tolerance,options.q_relative_tolerance})
        if(!std::isfinite(value) || value<0.)throw std::invalid_argument("invalid model-h iteration override");
}
inline std::size_t acceleration_block(const ModelHControl2D&) { return 25; }
inline std::size_t acceleration_history(const ModelHControl2D&) { return 6; }
inline std::size_t acceleration_block(const ModelHControl3D& control) {
    return control.strict_energy_balance?5:25;
}
inline std::size_t acceleration_history(const ModelHControl3D& control) {
    return control.strict_energy_balance?16:6;
}
template<class Control> ModelHIterationSettings apply_iteration_tolerances(
        Control& control,const ModelHIterationOverrides& options,std::size_t total_budget=0) {
    if(options.temperature_tolerance)control.temperature_tolerance=options.temperature_tolerance;
    if(options.q_relative_tolerance)control.q_relative_tolerance=options.q_relative_tolerance;
    return {control.max_iterations,control.chunk_iterations,control.temperature_tolerance,control.q_relative_tolerance,
            total_budget?total_budget:control.max_iterations,control.accelerate,
            acceleration_block(control),acceleration_history(control)};
}
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
inline double optional(ArrayView<const double> x, std::size_t p, double fallback) {
    return x.size ? x[p] : fallback;
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

class AcceleratedChunk {
    std::size_t count_,done_=0,sweep_block_;
    detail::Anderson accelerator_;
    bool boundary_=true;
public:
    explicit AcceleratedChunk(std::size_t count,std::size_t block=25,std::size_t history=6)
        :count_(count),sweep_block_(block),accelerator_(history) {
        if(!block || history<2)throw std::invalid_argument("invalid model-h acceleration policy");
    }
    AcceleratedChunk(std::size_t count,std::size_t fields,const ModelHChunkState& state,
                     std::size_t block=25,std::size_t history=6)
        :AcceleratedChunk(count,block,history) {
        done_=state.completed;
        if(state.count!=count || done_>count || state.sweep_block!=block
            || state.acceleration.history_limit!=history
            || state.acceleration.condition_limit!=1e10
            || ((done_==0)!=state.acceleration.x.empty()))
            throw std::invalid_argument("invalid saved model-h chunk");
        accelerator_.restore(state.acceleration);
        if(!accelerator_.x.empty() && static_cast<std::size_t>(accelerator_.x.front().size())!=fields)
            throw std::invalid_argument("saved model-h chunk field extent differs");
    }
    bool complete() const { return done_==count_; }
    ModelHChunkState snapshot() const {
        if(!boundary_)throw std::logic_error("model-h chunk has no complete save boundary");
        return {count_,done_,accelerator_.snapshot(),sweep_block_};
    }
    template<class Step,class Trial>
    void advance(TemperatureStateView fields,bool solve_b,Step&& step,Trial&& trial,double& residual) {
        if(!boundary_)throw std::logic_error("failed model-h chunk cannot advance");
        if(complete())return;
        boundary_=false;
        auto before=pack(fields,solve_b);
        const auto count=std::min(sweep_block_,count_-done_);
        residual=step(count);done_+=count;
        auto picard=pack(fields,solve_b);
        accelerator_.push(std::move(before),picard);
        Eigen::VectorXd candidate;
        if(accelerator_.candidate(picard,candidate) && count_-done_>=2) {
            const double selected=trial(picard,candidate);
            done_+=2;residual=selected;
        }
        boundary_=true;
    }
};


inline ModelHIterationState snapshot_iteration(TemperatureStateView fields,
        const Eigen::VectorXd& previous,double previous_q,bool have_q,
        const std::optional<AcceleratedChunk>& chunk) {
    ModelHIterationState state;
    const ArrayView<double> values[]{fields.a,fields.b,fields.solid};
    for(std::size_t i=0;i<3;++i)
        state.temperature[i].assign(values[i].data,values[i].data+values[i].size);
    state.previous.assign(previous.data(),previous.data()+previous.size());
    state.previous_q=previous_q;state.have_q=have_q;
    if(chunk)state.chunk=chunk->snapshot();
    return state;
}

template<class Result,class Control>
void validate_iteration_state(const ModelHIterationState& state,const Result& result,
        const Control& control,std::size_t cells,ArrayView<const double> prescribed_b) {
    for(const auto& field:state.temperature)check(view(field),cells);
    check(view(state.previous),cells*(prescribed_b.size?2:3));
    if(result.stop!=TemperatureStop::budget_exhausted
        || (control.max_iterations?result.iterations>=control.max_iterations:result.iterations!=0)
        || result.iterations%control.chunk_iterations || state.have_q!=(result.iterations!=0)
        || !std::isfinite(state.previous_q) || (!state.have_q && state.previous_q!=0.)
        || !std::isfinite(result.residual) || result.residual<0.
        || (state.have_q?!std::isfinite(result.q_b):!std::isnan(result.q_b)))
        throw std::invalid_argument("invalid saved model-h iteration");
    if(prescribed_b.size && !std::equal(state.temperature[1].begin(),state.temperature[1].end(),prescribed_b.data))
        throw std::invalid_argument("saved model-h prescribed field differs");
    std::size_t last=0;
    for(const auto& check:result.finishing_checks) {
        if(check.iterations<=last || check.iterations>result.iterations
            || check.iterations%control.chunk_iterations)
            throw std::invalid_argument("invalid saved model-h finishing history");
        last=check.iterations;
    }
    if(state.chunk) {
        const auto count=std::min(control.chunk_iterations,control.max_iterations-result.iterations);
        if(!control.accelerate || !state.chunk->completed || state.chunk->completed>=count)
            throw std::invalid_argument("invalid saved model-h active chunk");
        AcceleratedChunk validated(count,state.previous.size(),*state.chunk,
            acceleration_block(control),acceleration_history(control));
    }
}

inline void restore_iteration(TemperatureStateView fields,const ModelHIterationState& state) {
    const ArrayView<double> values[]{fields.a,fields.b,fields.solid};
    for(std::size_t i=0;i<3;++i)
        std::copy(state.temperature[i].begin(),state.temperature[i].end(),values[i].data);
}

}  // namespace tpmshx::model_h_common
