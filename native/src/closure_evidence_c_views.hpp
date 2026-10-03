#pragma once
#include "tpmshx/closure_evidence.hpp"
#include "tpmshx/closure_evidence_c_api.h"
#include <stdexcept>

namespace tpmshx {
inline tpmshx_nu_observation_v1 nu_observation_view(const NuObservation& n) {
    return {static_cast<uint32_t>(n.available),n.cells,n.floor_cells,n.raw_min,n.raw_max,n.re_min,n.re_max,
            n.pr_min,n.pr_max,n.temperature_min,n.temperature_max,n.pressure};
}
inline tpmshx_range_observation_v1 range_observation_view(const RangeObservation& r) {
    if (r.shape.size()>3) throw std::invalid_argument("closure range evidence supports at most three axes");
    tpmshx_range_observation_v1 v{};
    v.view=r.view.c_str(); v.model=r.model.c_str(); v.topology=r.topology.c_str();
    v.stage=r.stage.c_str(); v.layout=r.layout.c_str();
    v.side=static_cast<uint32_t>(r.side); v.ndim=static_cast<uint32_t>(r.shape.size()); v.have_finite=r.have_finite;
    std::copy(r.shape.begin(),r.shape.end(),v.shape);
    v.minimum_index=r.minimum_index; v.maximum_index=r.maximum_index;
    v.low=r.low; v.high=r.high; v.size=r.size; v.nonfinite=r.nonfinite;
    v.lower=r.bounds[0]; v.upper=r.bounds[1]; v.minimum=r.minimum; v.maximum=r.maximum;
    return v;
}
} // namespace tpmshx
