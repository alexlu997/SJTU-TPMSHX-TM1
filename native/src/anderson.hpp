#pragma once
#include "tpmshx/anderson_state.hpp"
#include <Eigen/Dense>
#include <algorithm>
#include <cmath>
#include <deque>
#include <limits>
#include <stdexcept>
#include <utility>
#ifdef __APPLE__
#include "anderson_lapack.hpp"
#endif

namespace tpmshx::detail {
// Type-II Anderson uses the caller's sample limit.
// Keep the existing platform-specific SVD and least-squares operations.
struct Anderson {
    std::deque<Eigen::VectorXd> x, r;
    std::size_t history_limit;
    double condition_limit;
    explicit Anderson(std::size_t history=6,double condition=1e10)
        : history_limit(history),condition_limit(condition) {}
    AndersonState snapshot() const {
        AndersonState state;state.history_limit=history_limit;state.condition_limit=condition_limit;
        for (const auto& value:x) state.x.emplace_back(value.data(),value.data()+value.size());
        for (const auto& value:r) state.r.emplace_back(value.data(),value.data()+value.size());
        return state;
    }
    void restore(const AndersonState& state) {
        if (!std::isfinite(state.condition_limit) || state.condition_limit<=0.
            || state.x.size()!=state.r.size() || state.x.size()>state.history_limit)
            throw std::invalid_argument("invalid saved Anderson history");
        Anderson restored(state.history_limit,state.condition_limit);
        const auto size=state.x.empty()?0:state.x.front().size();
        if (size>static_cast<std::size_t>(std::numeric_limits<Eigen::Index>::max()))
            throw std::invalid_argument("saved Anderson extent is too large");
        for (std::size_t i=0;i<state.x.size();++i) {
            if (!size || state.x[i].size()!=size || state.r[i].size()!=size)
                throw std::invalid_argument("saved Anderson extents differ");
            const Eigen::Map<const Eigen::VectorXd> previous(state.x[i].data(),static_cast<Eigen::Index>(size));
            const Eigen::Map<const Eigen::VectorXd> residual(state.r[i].data(),static_cast<Eigen::Index>(size));
            if (!previous.allFinite() || !residual.allFinite())
                throw std::invalid_argument("nonfinite saved Anderson sample");
            restored.x.push_back(previous);restored.r.push_back(residual);
        }
        *this=std::move(restored);
    }
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
}  // namespace tpmshx::detail
