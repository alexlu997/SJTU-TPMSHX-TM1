#ifndef TPMSHX_TEMPERATURE_DRIVER_C_API_H
#define TPMSHX_TEMPERATURE_DRIVER_C_API_H
#include "tpmshx/thermal_c_api.h"
#ifdef __cplusplus
extern "C" {
#endif

enum tpmshx_temperature_scheme {
    TPMSHX_TEMPERATURE_CC_2D = 0,
    TPMSHX_TEMPERATURE_CC_3D = 1,
    TPMSHX_TEMPERATURE_STAGGERED_3D = 2
};
/* Numerical recipe implemented by this library for a temperature scheme.
 * Returns immutable NUL-terminated static storage; never free or modify it.
 * Unknown schemes return NULL. The identity is not a qualification certificate
 * and does not select an algorithm.
 */
TPMSHX_THERMAL_API const char* TPMSHX_THERMAL_CALL tpmshx_temperature_algorithm_v1(uint32_t scheme);
#ifdef __cplusplus
}
#endif
#endif
