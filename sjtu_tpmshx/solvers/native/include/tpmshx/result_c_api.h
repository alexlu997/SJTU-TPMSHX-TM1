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

#define TPMSHX_RESULT_ABI_VERSION 1u
#define TPMSHX_RESULT_FP_EVENT_COUNT 64u

enum tpmshx_result_status_v1 {
    TPMSHX_RESULT_OK = 0, TPMSHX_RESULT_INVALID = 1,
    TPMSHX_RESULT_ALLOCATION = 2, TPMSHX_RESULT_RUNTIME = 3,
    TPMSHX_RESULT_NUMERIC = 4
};
enum tpmshx_result_dtype_v1 {
    TPMSHX_RESULT_BOOL = 1,
    TPMSHX_RESULT_I8 = 2, TPMSHX_RESULT_U8 = 3,
    TPMSHX_RESULT_I16 = 4, TPMSHX_RESULT_U16 = 5,
    TPMSHX_RESULT_I32 = 6, TPMSHX_RESULT_U32 = 7,
    TPMSHX_RESULT_I64 = 8, TPMSHX_RESULT_U64 = 9,
    TPMSHX_RESULT_F16 = 10, TPMSHX_RESULT_F32 = 11,
    TPMSHX_RESULT_F64 = 12, TPMSHX_RESULT_LONG_DOUBLE = 13,
    TPMSHX_RESULT_C64 = 14, TPMSHX_RESULT_C128 = 15,
    TPMSHX_RESULT_COMPLEX_LONG_DOUBLE = 16
};
enum tpmshx_result_origin_v1 {
    TPMSHX_RESULT_PYTHON_FLOAT = 0, TPMSHX_RESULT_NUMPY_SCALAR = 1,
    TPMSHX_RESULT_NUMPY_ARRAY = 2, TPMSHX_RESULT_PYTHON_INT = 3,
    TPMSHX_RESULT_PYTHON_BOOL = 4, TPMSHX_RESULT_PYTHON_COMPLEX = 5
};
enum tpmshx_result_byte_order_v1 {
    TPMSHX_RESULT_NATIVE_ENDIAN = 0, TPMSHX_RESULT_LITTLE_ENDIAN = 1,
    TPMSHX_RESULT_BIG_ENDIAN = 2
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

/* Origins describe the source Python operation. Byte order applies to each
 * real component. Scalar payloads hold one value in the declared dtype.
 */
typedef struct {
    uint32_t dtype, origin, byte_order, reserved;
    unsigned char data[32];
} tpmshx_result_scalar_v1;

/* data starts at the lowest borrowed byte; offset selects logical element zero.
 * Shape and signed byte strides describe logical C indexing, including views.
 * Empty arrays may use NULL data. Metadata stays alive for the complete call.
 */
typedef struct {
    const void* data;
    size_t bytes, offset;
    uint32_t dtype, origin, byte_order, reserved;
    size_t rank;
    const size_t* shape;
    const ptrdiff_t* strides;
} tpmshx_result_array_v1;

/* flags use NumPy's divide/overflow/underflow/invalid bits: 1/2/4/8.
 * Events preserve operation order. Failure diagnostics can publish these events
 * before the terminal cause. Numerical output buffers stay unchanged on failure.
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
typedef struct {
    uint32_t long_double_size, long_double_digits, long_double_max_exponent, reserved;
} tpmshx_result_platform_v1;

#ifdef __cplusplus
extern "C" {
#endif

/* Borrowed inputs may alias. Output, diagnostic and error storage must be
 * disjoint from each other and from all borrowed data and metadata.
 * Calls need nonempty bounded error storage. No C++ exception crosses this ABI.
 */
TPMSHX_RESULT_API uint32_t TPMSHX_RESULT_CALL tpmshx_result_abi_version_v1(void);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_platform_info_v1(
    tpmshx_result_platform_v1* output, char* error, size_t error_capacity);

#ifdef __cplusplus
}
#endif
#endif
