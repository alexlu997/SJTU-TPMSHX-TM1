#ifndef TPMSHX_CLOSURE_EVIDENCE_C_API_H
#define TPMSHX_CLOSURE_EVIDENCE_C_API_H
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t available;
    size_t cells,floor_cells;
    double raw_min,raw_max,re_min,re_max,pr_min,pr_max,temperature_min,temperature_max,pressure;
} tpmshx_nu_observation_v1;

typedef struct {
    const char *view,*model,*topology,*stage,*layout;
    uint32_t side,ndim,have_finite;
    size_t shape[3],minimum_index,maximum_index,low,high,size,nonfinite;
    double lower,upper,minimum,maximum;
} tpmshx_range_observation_v1;
#endif
