#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <string>
#include <utility>
#include <vector>

namespace tpmshx {

// The last actual pre-floor local Nu evaluation, not a new closure evaluation.
struct NuObservation {
    bool available=false;
    std::size_t cells=0,floor_cells=0;
    double raw_min=0.,raw_max=0.,re_min=0.,re_max=0.,pr_min=0.,pr_max=0.;
    double temperature_min=0.,temperature_max=0.,pressure=0.;
};

// One original warning source/shape/context. Counts describe one worst
// snapshot; extrema span snapshots. No full field or per-iteration history.
struct RangeObservation {
    std::string view,model,topology,stage,layout;
    std::size_t side;
    std::vector<std::size_t> shape;
    std::array<double,2> bounds;
    bool have_finite=false;
    double minimum=0.,maximum=0.;
    std::size_t minimum_index=0,maximum_index=0,low=0,high=0,size=0,nonfinite=0;
};

inline void observe_range_value(RangeObservation& record,double value,std::size_t index) {
    ++record.size;
    if (!std::isfinite(value)) { ++record.nonfinite; return; }
    if (!record.have_finite || value<record.minimum) { record.minimum=value; record.minimum_index=index; }
    if (!record.have_finite || value>record.maximum) { record.maximum=value; record.maximum_index=index; }
    record.have_finite=true;
    record.low+=value<record.bounds[0]; record.high+=value>record.bounds[1];
}

inline void merge_range_observation(std::vector<RangeObservation>& ledger,RangeObservation sample) {
    if (!sample.size) return;
    for (auto& old:ledger) {
        if (old.view!=sample.view || old.model!=sample.model || old.topology!=sample.topology ||
            old.side!=sample.side || old.stage!=sample.stage || old.layout!=sample.layout || old.shape!=sample.shape) continue;
        // Match RangeRecord.merged: equal fractions keep the first snapshot,
        // extrema use strict inequalities, nonfinite counts are never summed.
        if (sample.have_finite) {
            if (!old.have_finite || sample.minimum<old.minimum) {
                old.minimum=sample.minimum; old.minimum_index=sample.minimum_index;
            }
            if (!old.have_finite || sample.maximum>old.maximum) {
                old.maximum=sample.maximum; old.maximum_index=sample.maximum_index;
            }
            old.have_finite=true;
        }
        if (sample.low+sample.high>old.low+old.high) {
            old.low=sample.low; old.high=sample.high; old.size=sample.size;
        }
        old.nonfinite=std::max(old.nonfinite,sample.nonfinite);
        return;
    }
    ledger.push_back(std::move(sample));
}

template<class Values>
inline void observe_range(std::vector<RangeObservation>& ledger,RangeObservation sample,const Values& values) {
    for (std::size_t i=0;i<values.size;++i) observe_range_value(sample,values[i],i);
    merge_range_observation(ledger,std::move(sample));
}

} // namespace tpmshx
