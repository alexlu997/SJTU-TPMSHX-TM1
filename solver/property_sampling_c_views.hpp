#pragma once

#include "tpmshx/property_sampling.hpp"
#include "tpmshx/property_sampling_c_api.h"
#include <vector>

inline void append_property_samples(std::vector<tpmshx_property_sample_v1>& out,
                                    const std::vector<tpmshx::PropertySample>& samples) {
    for(const auto& sample:samples)
        out.push_back({static_cast<uint32_t>(sample.side),sample.outer_index,
            sample.stage.c_str(),sample.quantity.c_str(),sample.provider.c_str(),sample.temperature?sample.temperature->c_str():nullptr,
            sample.pressure?sample.pressure->c_str():nullptr,sample.operation.c_str()});
}
