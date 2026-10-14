#ifndef TPMSHX_PROPERTY_SAMPLING_C_API_H
#define TPMSHX_PROPERTY_SAMPLING_C_API_H

#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t side;
    int64_t outer_index;
    const char* stage;
    const char* quantity;
    const char* provider;
    const char* temperature;
    const char* pressure;
    const char* operation;
} tpmshx_property_sample_v1;

typedef struct {
    const tpmshx_property_sample_v1* records;
    size_t count;
} tpmshx_property_sampling_v1;

#endif
