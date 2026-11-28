/* Internal XY interpolation. See ../../geometry/fields-sources.md. */
#ifndef TM1_XY_FITPACK_H
#define TM1_XY_FITPACK_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct xy_fitpack_owner xy_fitpack_owner;

enum xy_fitpack_status {
    XY_FITPACK_OK = 0,
    XY_FITPACK_INVALID_INPUT = 1,
    XY_FITPACK_ALLOCATION_FAILED = 2,
    XY_FITPACK_NUMERICAL_FAILURE = 3
};

typedef struct xy_fitpack_view {
    int degree_x;
    int degree_y;
    size_t knots_x_count;
    size_t knots_y_count;
    size_t coefficient_count;
    const double *knots_x;
    const double *knots_y;
    const double *coefficients;
} xy_fitpack_view;

/* Inputs are borrowed during this call. z[i * my + j] is C order. */
/* Invalid extents fail before array access. Success writes a new owner. */
/* The caller must release any prior owner before reusing its output slot. */
int xy_fitpack_create(const double *x, size_t mx,
                     const double *y, size_t my,
                     const double *z, size_t z_count,
                     int degree_x, int degree_y,
                     xy_fitpack_owner **output);

/* The view belongs to owner. Release invalidates every borrowed pointer. */
int xy_fitpack_get_view(const xy_fitpack_owner *owner, xy_fitpack_view *output);

/* Sample axes increase strictly. Coordinates stay within the fitted rectangle. */
/* output[i * my + j] is C order. Numerical failure invalidates output. */
/* Output must not overlap axes or owner arrays. Input errors leave it unchanged. */
int xy_fitpack_evaluate(const xy_fitpack_owner *owner,
                       const double *x, size_t mx,
                       const double *y, size_t my,
                       double *output, size_t output_count);

/* Release must not run during evaluation or reads through a borrowed view. */
void xy_fitpack_release(xy_fitpack_owner *owner);

#ifdef __cplusplus
}
#endif

#endif
