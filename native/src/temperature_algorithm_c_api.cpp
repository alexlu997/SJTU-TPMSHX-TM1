#include "tpmshx/temperature_driver_c_api.h"

extern "C" const char* TPMSHX_THERMAL_CALL tpmshx_temperature_algorithm_v1(uint32_t scheme) {
    switch (scheme) {
    case TPMSHX_TEMPERATURE_CC_2D:
        return "shared_fv_cc2d_tminmod_guarded_line_v1";
    case TPMSHX_TEMPERATURE_CC_3D:
        return "shared_fv_cc3d_tminmod_guarded_line_v1";
    case TPMSHX_TEMPERATURE_STAGGERED_3D:
        return "shared_fv_staggered_tminmod_picard_v1";
    default:
        return nullptr;
    }
}
