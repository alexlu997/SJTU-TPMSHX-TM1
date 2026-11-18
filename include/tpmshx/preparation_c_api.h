#ifndef TPMSHX_PREPARATION_C_API_H
#define TPMSHX_PREPARATION_C_API_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#  if defined(TPMSHX_PREPARATION_BUILD_SHARED)
#    define TPMSHX_PREPARATION_API __declspec(dllexport)
#  elif defined(TPMSHX_PREPARATION_USE_SHARED)
#    define TPMSHX_PREPARATION_API __declspec(dllimport)
#  else
#    define TPMSHX_PREPARATION_API
#  endif
#  define TPMSHX_PREPARATION_CALL __cdecl
#else
#  if defined(__GNUC__) || defined(__clang__)
#    define TPMSHX_PREPARATION_API __attribute__((visibility("default")))
#  else
#    define TPMSHX_PREPARATION_API
#  endif
#  define TPMSHX_PREPARATION_CALL
#endif

#define TPMSHX_PREPARATION_ABI_VERSION 1u
#define TPMSHX_PREPARATION_FP_EVENT_COUNT 32u

enum tpmshx_preparation_status_v1 {
    TPMSHX_PREPARATION_OK = 0, TPMSHX_PREPARATION_INVALID = 1,
    TPMSHX_PREPARATION_ALLOCATION = 2, TPMSHX_PREPARATION_RUNTIME = 3,
    TPMSHX_PREPARATION_WATER_STATE = 10, TPMSHX_PREPARATION_CO2_STATE = 11,
    TPMSHX_PREPARATION_SCO2_STATE = 12
};

enum tpmshx_preparation_python_cause_v1 {
    TPMSHX_PREPARATION_NO_PYTHON_CAUSE = 0,
    TPMSHX_PREPARATION_ZERO_DIVISION = 1, TPMSHX_PREPARATION_OVERFLOW = 2,
    TPMSHX_PREPARATION_VALUE_ERROR = 3, TPMSHX_PREPARATION_TYPE_ERROR = 4
};

/* Failure diagnostics can publish ordered FP events before a terminal cause.
 * They are error data, separate from the unchanged numerical output buffers.
 */
typedef struct {
    uint32_t python_cause, event_count;
    uint32_t events[TPMSHX_PREPARATION_FP_EVENT_COUNT];
} tpmshx_preparation_fp_failure_v1;

#ifdef __cplusplus
extern "C" {
#endif

/* Counts use elements. Borrowed buffers need valid aligned storage and exact
 * extents. Empty buffers may be NULL. Read-only inputs may alias. Outputs and
 * error storage must not overlap any other buffer. Failure preserves numerical
 * outputs and writes a bounded error to valid, disjoint error storage.
 * Each call needs a nonempty error buffer. No C++ exception crosses this ABI.
 * A context must be released by its creating library after its last call.
 */
TPMSHX_PREPARATION_API uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_abi_version_v1(void);

#ifdef __cplusplus
}
#endif
#endif
