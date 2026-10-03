#include "tpmshx/outer_anderson.hpp"
#include "model_h_common.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace tpmshx {
struct OuterAnderson::Impl {
    model_h_common::Anderson accelerator;
    double trust,residual_min=std::numeric_limits<double>::infinity();
    int patience,stale=0;
    bool initialized=false;
    std::vector<std::size_t> sizes;
    std::vector<double> scales;
    OuterAndersonStats statistics;

    Impl(int m,double trust_,int patience_,double cond_max)
        : accelerator(history_limit(m),cond_max),trust(trust_),patience(patience_) {}
    static std::size_t history_limit(int m) {
        if(m< -1) throw std::invalid_argument("maxlen must be non-negative");
        return m<0 ? 0 : static_cast<std::size_t>(m)+1;
    }
    void init(const std::vector<ArrayView<const double>>& blocks) {
        for(const auto block:blocks) {
            sizes.push_back(block.size);
            double sum=0;
            for(std::size_t i=0;i<block.size;++i) sum+=std::abs(block[i]);
            const double scale=sum/static_cast<double>(block.size);
            scales.push_back(std::isfinite(scale) && scale>0 ? scale : 1.0);
        }
        initialized=true;
    }
    Eigen::VectorXd flat(const std::vector<ArrayView<const double>>& blocks) const {
        std::size_t total=0;
        for(std::size_t b=0;b<blocks.size();++b) total+=sizes[b];
        Eigen::VectorXd result(static_cast<Eigen::Index>(total));
        std::size_t offset=0;
        for(std::size_t b=0;b<blocks.size();++b) {
            for(std::size_t i=0;i<sizes[b];++i) result[static_cast<Eigen::Index>(offset+i)]=blocks[b][i]/scales[b];
            offset+=sizes[b];
        }
        return result;
    }
    std::vector<std::vector<double>> unflat(const Eigen::VectorXd& values) const {
        std::vector<std::vector<double>> blocks;
        std::size_t offset=0;
        for(std::size_t b=0;b<sizes.size();++b) {
            blocks.emplace_back(sizes[b]);
            for(std::size_t i=0;i<sizes[b];++i)
                blocks.back()[i]=values[static_cast<Eigen::Index>(offset+i)]*scales[b];
            offset+=sizes[b];
        }
        return blocks;
    }
};

OuterAnderson::OuterAnderson(int m,double trust,int patience,double cond_max)
    : impl_(std::make_unique<Impl>(m,trust,patience,cond_max)) {}
OuterAnderson::~OuterAnderson()=default;
const OuterAndersonStats& OuterAnderson::stats() const { return impl_->statistics; }

OuterAndersonStep OuterAnderson::step(
    const std::vector<ArrayView<const double>>& current,
    const std::vector<ArrayView<const double>>& image,double alpha) {
    auto& p=*impl_;
    if(current.empty() || current.size()!=image.size())
        throw std::invalid_argument("outer Anderson requires matching nonempty block lists");
    if(p.initialized && current.size()!=p.sizes.size())
        throw std::invalid_argument("outer Anderson block count changed");
    std::size_t total=0;
    for(std::size_t b=0;b<current.size();++b) {
        if(!current[b].size || !current[b].data || !image[b].data || current[b].size!=image[b].size ||
            (p.initialized && current[b].size!=p.sizes[b]) ||
            current[b].size>static_cast<std::size_t>(std::numeric_limits<Eigen::Index>::max())-total)
            throw std::invalid_argument("outer Anderson block extent changed or is invalid");
        total+=current[b].size;
    }
    if(!p.initialized) p.init(current);
    const Eigen::VectorXd x=p.flat(current),g=p.flat(image);
    const Eigen::VectorXd picard=alpha*g+(1.0-alpha)*x;
    const double residual=(g-x).norm();
    p.statistics.residuals.push_back(residual);
    if(residual<p.residual_min-1e-14) { p.residual_min=residual; p.stale=0; }
    else {
        ++p.stale;
        if(p.stale>=p.patience) {
            p.accelerator.reset(); p.residual_min=residual; p.stale=0;
            ++p.statistics.resets;
            return {p.unflat(picard),false};
        }
    }
    p.accelerator.push(x,g);
    Eigen::VectorXd candidate;
    if(!p.accelerator.candidate(g,candidate)) return {p.unflat(picard),false};
    if(!candidate.allFinite() || (candidate-x).norm()>p.trust*std::max(residual,1e-30)) {
        ++p.statistics.rejected;
        return {p.unflat(picard),false};
    }
    auto blocks=p.unflat(candidate);
    for(const auto& block:blocks) {
        for(double value:block) if(!std::isfinite(value) || value<=0) {
            ++p.statistics.rejected;
            return {p.unflat(picard),false};
        }
    }
    ++p.statistics.applied;
    return {std::move(blocks),true};
}
}  // namespace tpmshx
