#pragma once

#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <vector>

namespace tpmshx {

// Names refer to the state consumed by an operation, not its returned field.
struct PropertySample {
    std::size_t side;
    const char* stage;
    const char* quantity;
    const char* provider;
    const char* temperature;
    const char* pressure;
    const char* operation;
    std::int64_t outer_index = -1;
};

inline void record_property_samples(std::vector<PropertySample>& out, std::size_t side,
        std::int64_t outer, const char* stage, const char* provider,
        const char* temperature, const char* pressure, const char* operation,
        std::initializer_list<const char*> quantities) {
    for (const auto* quantity : quantities)
        out.push_back({side,stage,quantity,provider,temperature,pressure,operation,outer});
}

} // namespace tpmshx
