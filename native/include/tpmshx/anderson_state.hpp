#pragma once

#include <cstddef>
#include <vector>

namespace tpmshx {
struct AndersonState {
    std::size_t history_limit=6;
    double condition_limit=1e10;
    std::vector<std::vector<double>> x,r;
};
}  // namespace tpmshx
