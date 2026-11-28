#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <vector>

namespace tpmshx::detail {

// Keep the first position when several values share an extremum.
template<class Sample,class Read>
Sample collect_range(std::size_t size,Read read,double lower,double upper) {
    Sample sample{};
    sample.size=size;
    for (std::size_t index=0;index<size;++index) {
        const double value=read(index);
        if (!std::isfinite(value)) {++sample.nonfinite;continue;}
        if (!sample.have_finite || value<sample.minimum) {sample.minimum=value;sample.minimum_index=index;}
        if (!sample.have_finite || value>sample.maximum) {sample.maximum=value;sample.maximum_index=index;}
        sample.have_finite=true;
        sample.low+=value<lower;
        sample.high+=value>upper;
    }
    return sample;
}

// Keep the scalar sequence's extrema, first notices, and final observation.
template<class Read>
std::vector<std::size_t> scalar_range_samples(std::size_t size,Read read,double lower,double upper) {
    if (!size) return {};
    std::vector<std::size_t> selected{0,size-1};
    bool have_finite=false;
    double minimum=0.,maximum=0.;
    std::size_t minimum_index=0,maximum_index=0;
    for (std::size_t index=0;index<size;++index) {
        const double value=read(index);
        if (!std::isfinite(value)) continue;
        if (!have_finite || value<minimum) {minimum=value;minimum_index=index;}
        if (!have_finite || value>maximum) {maximum=value;maximum_index=index;}
        have_finite=true;
    }
    if (have_finite) {
        selected.push_back(minimum_index);
        selected.push_back(maximum_index);
    }
    bool first_nonfinite=true,first_below=true,first_above=true,first_violation=true;
    for (std::size_t index=0;index<size;++index) {
        const double value=read(index);
        const bool finite=std::isfinite(value),below=value<lower,above=value>upper;
        if (first_nonfinite && !finite) {selected.push_back(index);first_nonfinite=false;}
        if (first_below && below) {selected.push_back(index);first_below=false;}
        if (first_above && above) {selected.push_back(index);first_above=false;}
        if (first_violation && finite && (below || above)) {
            selected.push_back(index);first_violation=false;
        }
    }
    std::sort(selected.begin(),selected.end());
    selected.erase(std::unique(selected.begin(),selected.end()),selected.end());
    return selected;
}

}  // namespace tpmshx::detail
