#ifndef TPMSHX_FULL_2D_RUN_C_API_H
#define TPMSHX_FULL_2D_RUN_C_API_H
#include "tpmshx/full_2d_c_api.h"
#include "tpmshx/run_state_c_api.h"
#ifdef __cplusplus
extern "C" {
#endif

/* Phases of a saved 2D stage run. */
enum {
    TPMSHX_FULL2D_CREATED=0,TPMSHX_FULL2D_OUTER_BOUNDARY=1,TPMSHX_FULL2D_READY=2,
    TPMSHX_FULL2D_COMPLETED=3,TPMSHX_FULL2D_CANCELLED=4,TPMSHX_FULL2D_FAILED=5,
    TPMSHX_FULL2D_FLOW=6,TPMSHX_FULL2D_THERMAL=7,TPMSHX_FULL2D_REFINEMENT=8
};

#ifdef __cplusplus
}
#endif
#endif
