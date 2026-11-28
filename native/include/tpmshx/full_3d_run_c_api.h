#ifndef TPMSHX_FULL_3D_RUN_C_API_H
#define TPMSHX_FULL_3D_RUN_C_API_H
#include "tpmshx/full_3d_c_api.h"
#include "tpmshx/run_state_c_api.h"
#ifdef __cplusplus
extern "C" {
#endif

/* Phases of a saved 3D stage run. */
enum {
    TPMSHX_FULL3D_CREATED=0,TPMSHX_FULL3D_OUTER_BOUNDARY=1,TPMSHX_FULL3D_READY=2,
    TPMSHX_FULL3D_COMPLETED=3,TPMSHX_FULL3D_CANCELLED=4,TPMSHX_FULL3D_FAILED=5,
    TPMSHX_FULL3D_INITIAL_A=6,TPMSHX_FULL3D_INITIAL_B=7,TPMSHX_FULL3D_THERMAL=8,
    TPMSHX_FULL3D_POST_A=9,TPMSHX_FULL3D_POST_B=10
};

#ifdef __cplusplus
}
#endif
#endif
