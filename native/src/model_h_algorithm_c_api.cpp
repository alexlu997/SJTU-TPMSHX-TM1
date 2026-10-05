#include "tpmshx/model_h_c_api.h"

extern "C" const char* TPMSHX_THERMAL_CALL tpmshx_model_h_algorithm_v1(uint32_t dimension) {
    switch (dimension) {
        case 2: return "shared_fv_model_h_2d_defect_v1";
        case 3: return "shared_fv_model_h_3d_compensated_v1";
        default: return nullptr;
    }
}
