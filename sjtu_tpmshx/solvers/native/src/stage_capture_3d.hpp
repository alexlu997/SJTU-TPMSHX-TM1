#pragma once
#include "tpmshx/stage_run_3d_c_api.h"

namespace tpmshx::stages {
class Capture3D;
Capture3D* capture_3d(const tpmshx_stage_saved_case_3d_v1&,
    tpmshx_full3d_result_v1&,const tpmshx_full3d_control_v1&,const char* result_id);
tpmshx_stage_run_result_3d_v1 stage_view(Capture3D&);
void release_capture_3d(Capture3D*) noexcept;
}  // namespace tpmshx::stages
