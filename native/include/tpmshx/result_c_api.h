#ifndef TPMSHX_RESULT_C_API_H
#define TPMSHX_RESULT_C_API_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#  if defined(TPMSHX_RESULT_BUILD_SHARED)
#    define TPMSHX_RESULT_API __declspec(dllexport)
#  elif defined(TPMSHX_RESULT_USE_SHARED)
#    define TPMSHX_RESULT_API __declspec(dllimport)
#  else
#    define TPMSHX_RESULT_API
#  endif
#  define TPMSHX_RESULT_CALL __cdecl
#else
#  define TPMSHX_RESULT_API __attribute__((visibility("default")))
#  define TPMSHX_RESULT_CALL
#endif

#define TPMSHX_RESULT_ABI_VERSION 3u
#define TPMSHX_RESULT_FP_EVENT_COUNT 64u

enum tpmshx_result_status_v1 {
    TPMSHX_RESULT_OK = 0, TPMSHX_RESULT_INVALID = 1,
    TPMSHX_RESULT_ALLOCATION = 2, TPMSHX_RESULT_RUNTIME = 3,
    TPMSHX_RESULT_NUMERIC = 4
};
enum tpmshx_result_python_cause_v1 {
    TPMSHX_RESULT_NO_CAUSE = 0, TPMSHX_RESULT_ZERO_DIVISION = 1,
    TPMSHX_RESULT_OVERFLOW = 2, TPMSHX_RESULT_VALUE_ERROR = 3,
    TPMSHX_RESULT_TYPE_ERROR = 4, TPMSHX_RESULT_INDEX_ERROR = 5
};
enum tpmshx_result_operation_v1 {
    TPMSHX_RESULT_ADD = 1, TPMSHX_RESULT_SUBTRACT = 2,
    TPMSHX_RESULT_MULTIPLY = 3, TPMSHX_RESULT_DIVIDE = 4,
    TPMSHX_RESULT_POWER = 5, TPMSHX_RESULT_LOG = 6,
    TPMSHX_RESULT_EXP = 7, TPMSHX_RESULT_CAST = 8,
    TPMSHX_RESULT_LOG10 = 9, TPMSHX_RESULT_SQRT = 10,
    TPMSHX_RESULT_REDUCE = 11, TPMSHX_RESULT_ABSOLUTE = 12,
    TPMSHX_RESULT_MAXIMUM = 13, TPMSHX_RESULT_MINIMUM = 14,
    TPMSHX_RESULT_SQUARE = 15
};

/* A view borrows contiguous C-order binary64 values for one call.
 * The shape has rank entries. NULL data is valid only for an empty view.
 * A double argument uses the Python float rules; a view of any rank uses
 * the NumPy float64 array rules. Values can be NaN or infinite.
 */
typedef struct {
    const double* data;
    size_t rank;
    const size_t* shape;
} tpmshx_result_array_v2;
/* Zone labels borrow contiguous C-order int32 values with the same rules. */
typedef struct {
    const int32_t* data;
    size_t rank;
    const size_t* shape;
} tpmshx_result_labels_v1;

/* flags use NumPy's divide/overflow/underflow/invalid bits: 1/2/4/8.
 * Events preserve operation order. Failure diagnostics can publish these events
 * before the terminal cause. Numerical output buffers stay unchanged on failure.
 * scalar is 1 when the operation used a NumPy scalar produced by a reduction.
 */
typedef struct {
    uint32_t flags, operation, scalar, reserved;
} tpmshx_result_fp_event_v1;
typedef struct {
    uint32_t python_cause, event_count;
    int32_t error_number;
    uint32_t reserved;
    tpmshx_result_fp_event_v1 events[TPMSHX_RESULT_FP_EVENT_COUNT];
} tpmshx_result_diagnostics_v1;

#ifdef __cplusplus
extern "C" {
#endif

/* Borrowed inputs may alias. Output, diagnostic and error storage must be
 * disjoint from each other and from all borrowed data and metadata.
 * Calls need nonempty bounded error storage. No C++ exception crosses this ABI.
 */
TPMSHX_RESULT_API uint32_t TPMSHX_RESULT_CALL tpmshx_result_abi_version_v1(void);

#ifdef __cplusplus
}
#endif
#endif
