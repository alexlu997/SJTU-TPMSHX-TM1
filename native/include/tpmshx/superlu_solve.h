#ifndef TPMSHX_SUPERLU_SOLVE_H
#define TPMSHX_SUPERLU_SOLVE_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

enum tpmshx_superlu_status {
    TPMSHX_SUPERLU_OK = 0,
    TPMSHX_SUPERLU_ALLOCATION = 1,
    TPMSHX_SUPERLU_ABORTED = 2,
    TPMSHX_SUPERLU_INVALID_ARGUMENT = 3,
    TPMSHX_SUPERLU_REENTRANT = 4
};

typedef struct tpmshx_superlu_result {
    int info;  /* Original SuperLU info; only authoritative after status OK. */
    size_t allocation_attempts;
    size_t peak_bytes;  /* Live payload plus allocator bookkeeping. */
    size_t outstanding_blocks, outstanding_bytes;
    int message_truncated;
    char message[512];
} tpmshx_superlu_result;

/* One non-reentrant solve per calling thread; separate threads are isolated.
 * CSC arrays, solution/RHS and permutations are borrowed, never freed here.
 * The caller provides valid extents: colptr[n+1], rowind/values[nnz], x/perms[n].
 * x may be partially modified after any failed solve and must be discarded.
 * Status OK preserves native info (0 success, 1..n singular, >n allocation).
 * All library allocations are released before every normal/error return.
 * No C++ frame, callback or object exists inside the setjmp/longjmp region.
 */
int tpmshx_superlu_solve_csc(
    int n, int nnz, const int* colptr, const int* rowind, double* values,
    double* x, int* perm_c, int* perm_r, tpmshx_superlu_result* result);

// Preserve SciPy spsolve(CSR)'s native SLU_NR route: factor A^T and solve
// transposed, retaining the caller's storage/order and rounding trajectory.
int tpmshx_superlu_solve_csr(
    int n, int nnz, const int* rowptr, const int* colind, double* values,
    double* x, int* perm_c, int* perm_r, tpmshx_superlu_result* result);

#ifdef __cplusplus
}
#endif
#endif
