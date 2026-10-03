#include "superlu_hooks.h"

#include <limits.h>
#include <setjmp.h>
#include <stdint.h>

_Static_assert(sizeof(int_t) == sizeof(int), "qualified SuperLU uses 32-bit indices");

typedef union Allocation Allocation;
union Allocation {
    max_align_t alignment;
    struct { Allocation* next; size_t bytes; } value;
};

typedef struct {
    jmp_buf jump;
    int armed, status, rowwise;
    Allocation* blocks;
    size_t live_blocks, live_bytes, peak_bytes, attempts;
    const tpmshx_superlu_test_control* test;
    tpmshx_superlu_result* output;
} Context;

#if defined(_MSC_VER)
#define TPMSHX_THREAD_LOCAL __declspec(thread)
#else
#define TPMSHX_THREAD_LOCAL _Thread_local
#endif
static TPMSHX_THREAD_LOCAL Context* active;

static void message(Context* context, const char* text, int line, const char* file) {
    const int size = snprintf(context->output->message, sizeof(context->output->message),
                              "%s at line %d in file %s", text, line, file);
    context->output->message_truncated = size < 0 || (size_t)size >= sizeof(context->output->message);
}

void tpmshx_superlu_abort_at(const char* text, int line, const char* file) {
    Context* context = active;
    /* Only our protected C caller may enter the private SuperLU API. */
    if (!context || !context->armed) abort();
    if (context->status == TPMSHX_SUPERLU_OK) context->status = TPMSHX_SUPERLU_ABORTED;
    message(context, text, line, file);
    longjmp(context->jump, 1);
}

void tpmshx_superlu_abort(const char* text) {
    tpmshx_superlu_abort_at(text, 0, "SuperLU");
}

void* tpmshx_superlu_malloc(size_t size) {
    Context* context = active;
    Allocation* block;
    if (!context || !context->armed) abort();
    ++context->attempts;
    if ((context->test && context->test->fail_allocation == context->attempts)
        || size > SIZE_MAX-sizeof(Allocation)) {
        context->status = TPMSHX_SUPERLU_ALLOCATION;
        tpmshx_superlu_abort("SuperLU allocation failed");
    }
    block = (Allocation*)malloc(sizeof(Allocation)+size);
    if (!block) {
        context->status = TPMSHX_SUPERLU_ALLOCATION;
        tpmshx_superlu_abort("SuperLU allocation failed");
    }
    block->value.bytes = sizeof(Allocation)+size;
    block->value.next = context->blocks;
    context->blocks = block;
    ++context->live_blocks;
    context->live_bytes += block->value.bytes;
    if (context->live_bytes > context->peak_bytes) context->peak_bytes = context->live_bytes;
    return block+1;
}

void tpmshx_superlu_free(void* pointer) {
    Context* context = active;
    Allocation** link;
    if (!pointer) return;
    if (!context || !context->armed) abort();
    for (link = &context->blocks; *link; link = &(*link)->value.next) {
        Allocation* block = *link;
        if ((void*)(block+1) != pointer) continue;
        *link = block->value.next;
        --context->live_blocks;
        context->live_bytes -= block->value.bytes;
        free(block);
        return;
    }
    tpmshx_superlu_abort("SuperLU attempted to free an unowned or already freed pointer");
}

static void release(Context* context) {
    while (context->blocks) {
        Allocation* block = context->blocks;
        context->blocks = block->value.next;
        --context->live_blocks;
        context->live_bytes -= block->value.bytes;
        free(block);
    }
}

/* Context lives in the outer C frame. This function's unchanged context
 * pointer is safe after longjmp; modified automatic solver descriptors are
 * never inspected on the failure return. No C++ destructor is bypassed. */
static int protected_solve(Context* context, int n, int nnz,
    const int* colptr, const int* rowind, double* values, double* x, int* perm_c, int* perm_r) {
    if (setjmp(context->jump)) return context->status;
    context->armed = 1;
    {
        NCformat column_store = {nnz, values, (int*)rowind, (int*)colptr};
        NRformat row_store = {nnz, values, (int*)rowind, (int*)colptr};
        DNformat rhs_store = {n, x};
        SuperMatrix matrix = {context->rowwise ? SLU_NR : SLU_NC, SLU_D, SLU_GE, n, n,
            context->rowwise ? (void*)&row_store : (void*)&column_store};
        SuperMatrix rhs = {SLU_DN, SLU_D, SLU_GE, n, 1, &rhs_store};
        SuperMatrix lower = {0}, upper = {0};
        superlu_options_t options;
        SuperLUStat_t statistics = {0};
        int_t info = 0;
        set_default_options(&options);
        options.ColPerm = COLAMD;
        options.DiagPivotThresh = 1.;
        options.IterRefine = NOREFINE;
        options.PrintStat = NO;
        StatInit(&statistics);
        if (context->test && context->test->abort_message) {
            if (context->test->abort_file)
                tpmshx_superlu_abort_at(context->test->abort_message, 1, context->test->abort_file);
            else ABORT(context->test->abort_message);
        }
        dgssv(&options, &matrix, perm_c, perm_r, &lower, &upper, &rhs, &statistics, &info);
        context->output->info = (int)info;
        StatFree(&statistics);
        if (lower.Store) Destroy_SuperNode_Matrix(&lower);
        if (upper.Store) Destroy_CompCol_Matrix(&upper);
    }
    return context->status;
}

static int solve_sparse(int rowwise,
    int n, int nnz, const int* colptr, const int* rowind, double* values,
    double* x, int* perm_c, int* perm_r,
    const tpmshx_superlu_test_control* control, tpmshx_superlu_result* result) {
    Context context = {0};
    int status;
    if (!result) return TPMSHX_SUPERLU_INVALID_ARGUMENT;
    memset(result, 0, sizeof(*result));
    if (active) {
        snprintf(result->message, sizeof(result->message), "SuperLU solve is not reentrant on one thread");
        return TPMSHX_SUPERLU_REENTRANT;
    }
    if (n <= 0 || n == INT_MAX || nnz <= 0 || !colptr || !rowind || !values || !x || !perm_c || !perm_r
        || colptr[0] != 0 || colptr[n] != nnz) {
        snprintf(result->message, sizeof(result->message), "invalid SuperLU sparse arguments");
        return TPMSHX_SUPERLU_INVALID_ARGUMENT;
    }
    context.test = control;
    context.output = result;
    context.rowwise = rowwise;
    active = &context;
    status = protected_solve(&context, n, nnz, colptr, rowind, values, x, perm_c, perm_r);
    release(&context);
    context.armed = 0;
    active = NULL;
    result->allocation_attempts = context.attempts;
    result->peak_bytes = context.peak_bytes;
    result->outstanding_blocks = context.live_blocks;
    result->outstanding_bytes = context.live_bytes;
    return status;
}

int tpmshx_superlu_solve_csc(
    int n, int nnz, const int* colptr, const int* rowind, double* values,
    double* x, int* perm_c, int* perm_r, tpmshx_superlu_result* result) {
    return solve_sparse(0, n, nnz, colptr, rowind, values, x, perm_c, perm_r, NULL, result);
}

int tpmshx_superlu_solve_csr(
    int n, int nnz, const int* rowptr, const int* colind, double* values,
    double* x, int* perm_c, int* perm_r, tpmshx_superlu_result* result) {
    return solve_sparse(1, n, nnz, rowptr, colind, values, x, perm_c, perm_r, NULL, result);
}

int tpmshx_superlu_test_solve_csc(
    int n, int nnz, const int* colptr, const int* rowind, double* values,
    double* x, int* perm_c, int* perm_r,
    const tpmshx_superlu_test_control* control, tpmshx_superlu_result* result) {
    return solve_sparse(0, n, nnz, colptr, rowind, values, x, perm_c, perm_r, control, result);
}

int tpmshx_superlu_test_solve_csr(
    int n, int nnz, const int* rowptr, const int* colind, double* values,
    double* x, int* perm_c, int* perm_r,
    const tpmshx_superlu_test_control* control, tpmshx_superlu_result* result) {
    return solve_sparse(1, n, nnz, rowptr, colind, values, x, perm_c, perm_r, control, result);
}
