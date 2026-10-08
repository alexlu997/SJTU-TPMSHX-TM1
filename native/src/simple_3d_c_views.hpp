#pragma once
#include "tpmshx/simple_3d.hpp"
#include "tpmshx/simple_3d_c_api.h"
#include <algorithm>
#include <cstring>

namespace tpmshx {
inline tpmshx_simple_3d_result_v1 simple_3d_c_view(const Simple3DResult& r) {
    tpmshx_simple_3d_result_v1 result{};
    result.stop=static_cast<uint32_t>(r.stop);result.converged=r.converged;
    result.post_closure_measured=r.post_closure_measured;result.post_closure_certified=r.post_closure_certified;
    result.iterations=r.iterations;result.pressure_clip_hits=r.pressure_clip_hits;result.post_closure_rejections=r.post_closure_rejections;
    result.legacy_residual=r.legacy_residual;result.legacy_reference=r.legacy_reference;result.momentum.maximum=r.momentum.maximum;
    for(std::size_t i=0;i<3;++i) {
        result.momentum.numerator[i]=r.momentum.numerator[i];result.momentum.denominator[i]=r.momentum.denominator[i];result.momentum.component[i]=r.momentum.component[i];
    }
    result.mass={r.mass.local_residual,r.mass.mass_in,r.mass.mass_out,r.mass.global_residual,r.mass.backflow_fraction,r.mass.counted_cells};
    auto& p=result.pressure;const auto& q=r.linear;
    p.success=q.success;p.iterations=q.iterations;p.rebuild_count=q.rebuild_count;p.hierarchy_bytes=q.hierarchy_bytes;p.superlu_info=q.superlu_info;
    p.rhs_scale=q.rhs_scale;p.relative_residual=q.relative_residual;p.absolute_residual=q.absolute_residual;p.iterative_relative_residual=q.iterative_relative_residual;
    p.pin_max_abs=q.pin_max_abs;p.diagonal_drift=q.diagonal_drift;p.build_seconds=q.build_seconds;p.solve_seconds=q.solve_seconds;
    const auto copy=[](char* out,std::size_t capacity,const std::string& text) {
        const auto n=std::min(capacity-1,text.size());std::memcpy(out,text.data(),n);out[n]='\0';
    };
    copy(p.method,sizeof p.method,q.method);copy(p.exit,sizeof p.exit,q.exit);copy(p.amg_exit,sizeof p.amg_exit,q.amg_exit);
    copy(p.rebuild_reason,sizeof p.rebuild_reason,q.rebuild_reason);copy(p.detail,sizeof p.detail,q.detail);
    return result;
}
}
