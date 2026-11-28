#ifndef TPMSHX_RUN_STATE_C_API_H
#define TPMSHX_RUN_STATE_C_API_H
#include "tpmshx/thermal_c_api.h"
#ifdef __cplusplus
extern "C" {
#endif

enum {
    TPMSHX_RUN_STATE_F64=0,TPMSHX_RUN_STATE_U64=1,TPMSHX_RUN_STATE_I64=2,
    TPMSHX_RUN_STATE_U8=3,TPMSHX_RUN_STATE_UTF8=4
};
typedef struct {
    const char* name;
    uint32_t type;
    const void* data;
    size_t count;
} tpmshx_run_state_field_v1;
typedef struct {
    const tpmshx_run_state_field_v1* fields;
    size_t count;
    void* owner;
} tpmshx_run_state_v1;

/* Release an independent snapshot. Repeated release is valid. */
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_run_state_release_v1(tpmshx_run_state_v1*);
#ifdef __cplusplus
}
#endif
#endif
