#pragma once

#include "tpmshx/property_sampling.hpp"
#include "tpmshx/property_sampling_c_api.h"
#include <vector>

inline void append_property_samples(std::vector<tpmshx_property_sample_v1>& out,
                                    const std::vector<tpmshx::PropertySample>& samples) {
    for(const auto& sample:samples)
        out.push_back({static_cast<uint32_t>(sample.side),sample.outer_index,
            sample.stage,sample.quantity,sample.provider,sample.temperature,
            sample.pressure,sample.operation});
}
