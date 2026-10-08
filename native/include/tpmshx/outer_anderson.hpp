#pragma once

#include "tpmshx/finite_volume.hpp"

#include <memory>
#include <vector>

namespace tpmshx {

struct OuterAndersonStats {
    std::size_t applied=0,rejected=0,resets=0;
    std::vector<double> residuals;
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
