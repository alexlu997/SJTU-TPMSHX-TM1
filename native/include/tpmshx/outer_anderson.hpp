#pragma once

#include "tpmshx/anderson_state.hpp"
#include "tpmshx/finite_volume.hpp"

#include <limits>
#include <memory>
#include <vector>

namespace tpmshx {

struct OuterAndersonStats {
    std::size_t applied=0,rejected=0,resets=0;
    std::vector<double> residuals;
};
struct OuterAndersonState {
    AndersonState accelerator;
    double trust=5.,residual_min=std::numeric_limits<double>::infinity();
    int patience=3,stale=0;
    bool initialized=false;
    std::vector<std::size_t> sizes;
    std::vector<double> scales;
    OuterAndersonStats statistics;
};
struct OuterAndersonStep {
    std::vector<std::vector<double>> blocks;
    bool applied;
};

// Original opt-in outer property map. Immutable contiguous blocks can have
// different lengths; preserve their order/length across calls. Scales are
// fixed from the first current-state blocks. Original m+1 samples, SVD
// condition gate, running-minimum/patience reset, trust region and physical
// positivity checks are unchanged. The Picard fallback is not repaired or
// clipped, so upstream nonfinite/nonpositive evidence remains observable.
// Each instance owns its histories and is not concurrently callable.
class OuterAnderson {
public:
    explicit OuterAnderson(int m=3,double trust=5.0,int patience=3,double cond_max=1e10);
    explicit OuterAnderson(const OuterAndersonState&);
    OuterAndersonState snapshot() const;
    ~OuterAnderson();
    OuterAnderson(const OuterAnderson&)=delete;
    OuterAnderson& operator=(const OuterAnderson&)=delete;
    OuterAndersonStep step(const std::vector<ArrayView<const double>>& current,
                          const std::vector<ArrayView<const double>>& image,
                          double alpha);
    const OuterAndersonStats& stats() const;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace tpmshx
