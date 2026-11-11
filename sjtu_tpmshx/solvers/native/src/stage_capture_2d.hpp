#pragma once
#include "tpmshx/stage_run_c_api.h"
#include <memory>

namespace tpmshx::stages {
class Capture2D;
Capture2D* capture_2d(const tpmshx_preparation_case_2d_v1&,
    tpmshx_full_2d_result_v2&,const tpmshx_full_2d_config_v2&,const char* result_id,
    const tpmshx_preparation_case_2d_v2* uniform=nullptr,bool inlet_recorded=true,
    const uint32_t* range_captured=nullptr);
tpmshx_stage_run_result_2d_v1 stage_view(Capture2D&);
void release_capture_2d(Capture2D*) noexcept;
}  // namespace tpmshx::stages
