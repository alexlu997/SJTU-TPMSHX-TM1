#ifndef TPMSHX_SUPERLU_HOOKS_H
#define TPMSHX_SUPERLU_HOOKS_H

/* Private build header: preincluded in every compiled SuperLU C unit. */
#include <tpmshx_superlu_config.h>
#include "tpmshx/superlu_solve.h"

#ifdef __cplusplus
extern "C" {
#endif
void* tpmshx_superlu_malloc(size_t size);
void tpmshx_superlu_free(void* pointer);
void tpmshx_superlu_abort(const char* message);
void tpmshx_superlu_abort_at(const char* message, int line, const char* file);

/* Qualification entry point only; no environment/global fail switches. */
typedef struct tpmshx_superlu_test_control {
    size_t fail_allocation;  /* 1-based USER_MALLOC call; zero disables. */
    const char* abort_message;
    const char* abort_file;  /* NULL exercises the ABORT macro itself. */
} tpmshx_superlu_test_control;
int tpmshx_superlu_test_solve_csc(
    int n, int nnz, const int* colptr, const int* rowind, double* values,
    double* x, int* perm_c, int* perm_r,
    const tpmshx_superlu_test_control* control, tpmshx_superlu_result* result);
int tpmshx_superlu_test_solve_csr(
    int n, int nnz, const int* rowptr, const int* colind, double* values,
    double* x, int* perm_c, int* perm_r,
    const tpmshx_superlu_test_control* control, tpmshx_superlu_result* result);
#ifdef __cplusplus
}
#endif

#define USER_MALLOC tpmshx_superlu_malloc
#define USER_FREE tpmshx_superlu_free
#define USER_ABORT tpmshx_superlu_abort
#include <slu_ddefs.h>
#ifdef TPMSHX_SUPERLU_ACCELERATE
/* The locked macOS SciPy wheel uses Accelerate's macOS 13.3+ LP64 symbols.
 * Keep SuperLU's declarations while selecting that exact system BLAS ABI.
 * No Apple headers with conflicting Fortran declarations enter vendor units.
 */
extern __typeof__(dgemm_) dgemm_ __asm__("_dgemm$NEWLAPACK");
extern __typeof__(dgemv_) dgemv_ __asm__("_dgemv$NEWLAPACK");
extern __typeof__(dtrsm_) dtrsm_ __asm__("_dtrsm$NEWLAPACK");
extern __typeof__(dtrsv_) dtrsv_ __asm__("_dtrsv$NEWLAPACK");
#endif
/* Upstream ABORT uses sprintf into 256 bytes before calling USER_ABORT.
 * Its guarded definition has now been consumed; replace it without changing
 * vendor files. Formatting occurs only in our bounded C error handler. */
#undef ABORT
#define ABORT(message) tpmshx_superlu_abort_at((message), __LINE__, __FILE__)

#endif
