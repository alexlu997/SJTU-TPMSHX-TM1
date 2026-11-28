#pragma once
#include "tpmshx/simple_2d_c_api.h"
#include "tpmshx/simple_2d.hpp"
#include <cstdio>

namespace tpmshx {
inline tpmshx_simple_2d_result_v1 simple_2d_c_view(const Simple2DResult& r,std::optional<double> target) {
tpmshx_simple_2d_result_v1 result{};
result.stop = static_cast<uint32_t>(r.stop); result.converged = r.converged;
result.post_closure_measured = r.post_closure_measured; result.post_closure_certified = r.post_closure_certified;
result.iterations = r.iterations; result.pressure_clip_hits = r.pressure_clip_hits;
result.legacy_residual = r.legacy_residual; result.momentum.maximum = r.momentum.maximum;
for (std::size_t i = 0; i < 3; ++i) {
    result.momentum.numerator[i] = r.momentum.numerator[i];
    result.momentum.denominator[i] = r.momentum.denominator[i];
    result.momentum.component[i] = r.momentum.component[i];
}
result.mass = {r.mass.local_residual,r.mass.mass_in,r.mass.mass_out,r.mass.global_residual,
               r.mass.backflow_fraction,r.mass.counted_cells};
result.have_massflux_target = target.has_value();
result.massflux_target = target.value_or(std::numeric_limits<double>::quiet_NaN());
result.pressure_success = r.linear.success; result.pressure_superlu_info = r.linear.superlu_info;
result.pressure_relative_residual = r.linear.relative_residual;
result.pressure_pin_maximum = r.linear.pin_max_abs;
std::snprintf(result.pressure_exit,sizeof(result.pressure_exit),"%s",r.linear.exit.c_str());
std::snprintf(result.pressure_detail,sizeof(result.pressure_detail),"%s",r.linear.detail.c_str());
return result;
}
} // namespace tpmshx
