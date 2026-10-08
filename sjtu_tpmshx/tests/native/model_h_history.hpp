// Test-only observations in generated copies of the two model-h drivers.
// No solver call, branch decision, state write or production API is added.
#ifndef TPMSHX_TEST_MODEL_H_HISTORY_HPP
#define TPMSHX_TEST_MODEL_H_HISTORY_HPP
#include "tpmshx/model_h_2d.hpp"
#include "tpmshx/model_h_3d.hpp"
#include "tpmshx/thermal_c_api.h"
#include <algorithm>
#include <cmath>
#include <utility>
#include <vector>

namespace {
thread_local std::vector<std::vector<double>> model_h_trace;

// kind 0: completed step (position is its requested sweep count).
// kind 1/2/3: ordinary/trial/post-decision (position is charged iteration).
// Every state is copied while live. last_a/b are supplied only by the 2D driver.
void observe_model_h(int kind,std::size_t position,double change,
                     tpmshx::TemperatureStateView t,
                     const std::vector<double>& last_a={},
                     const std::vector<double>& last_b={}) {
    std::vector<double> row{static_cast<double>(kind),static_cast<double>(position),
                            change,static_cast<double>(t.a.size)};
    for (auto field:{t.a,t.b,t.solid}) row.insert(row.end(),field.data,field.data+field.size);
    row.insert(row.end(),last_a.begin(),last_a.end());
    row.insert(row.end(),last_b.begin(),last_b.end());
    model_h_trace.push_back(std::move(row));
}

[[maybe_unused]] void observe_model_h_carry(const std::array<std::vector<double>,3>& carry,
                                           double before) {
    double after=0.;
    for (const auto& field:carry) for (double value:field) after=std::max(after,std::abs(value));
    model_h_trace.push_back({4.,0.,before,after});
}
}

extern "C" TPMSHX_THERMAL_API std::size_t TPMSHX_THERMAL_CALL test_model_h_trace_size() {
    return model_h_trace.size();
}
extern "C" TPMSHX_THERMAL_API std::size_t TPMSHX_THERMAL_CALL test_model_h_trace_read(
    std::size_t index,double* values,std::size_t capacity) {
    if (index>=model_h_trace.size() || capacity<model_h_trace[index].size()) return 0;
    const auto& row=model_h_trace[index];
    std::copy(row.begin(),row.end(),values);
    return row.size();
}
#endif
