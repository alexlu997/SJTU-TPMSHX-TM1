/*
 * XY interpolation for the continuous field owner.
 * Numerical routines are derived from SciPy v1.18.1 dfitpack.c.
 * Copyright (c) 2001-2002 Enthought, Inc. 2003, SciPy Developers.
 * All rights reserved. See ../../licenses/scipy-LICENSE.txt for the license.
 * Changes: degree 1..3, s=0, first fit, default bounds, owned C interface.
 * Source details are in ../../geometry/fields-sources.md.
 */
#include "xy_fitpack.h"

#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>

#if defined(_MSC_VER)
#define XY_RESTRICT __restrict
#else
#define XY_RESTRICT restrict
#endif

/* BEGIN SCIPY NUMERICAL SUBSET */

/* SciPy v1.18.1 dfitpack.c:434-454. */
static void
fpback(double* a, double* z, const int n, const int k, double* c, const int nest)
{
    c[n - 1] = z[n - 1] / a[n - 1];
    if (n == 1) { return; }

    int k1 = k - 1;
    int i = n - 1;
    for (int j = 2; j <= n; j++) {
        double store = z[i - 1];
        int i1 = k1;
        if (j <= k1) { i1 = j - 1; }
        int m = i;
        for (int l = 1; l <= i1; l++) {
            m++;
            store = store - c[m - 1] * a[(i - 1) + l * nest];
        }
        c[i - 1] = store / a[i - 1];
        i--;
    }
}

/* SciPy v1.18.1 dfitpack.c:584-622. */
static void
fpbspl(const double* t, const int n, const int k, const double x, const int l, double* h)
{
    (void)n;  // Unused
    // subroutine fpbspl evaluates the (k+1) non-zero b-splines of degree k
    // at t(l) <= x < t(l+1) using the stable recurrence relation of de boor and cox.
    // Travis Oliphant  2007
    //    changed so that weighting of 0 is used when knots with multiplicity are present.
    //    Also, notice that l+k <= n and 1 <= l+1-k or else the routine will be
    //    accessing memory outside t.  Thus it is imperative that k <= l <= n-k
    //    but this is not checked.
    int li, lj;
    double f;
    double hh[19] = { 0.0 };

    h[0] = 1.0;
    for (int j = 1; j <= k; j++) {
        for (int i = 1; i <= j; i++)
        {
            hh[i - 1] = h[i - 1];
        }

        h[0] = 0.0;
        for (int i = 1; i <= j; i++)
        {
            li = l + i;
            lj  = li - j;
            if (t[li - 1] != t[lj - 1])
            {
                f = hh[i - 1] / (t[li - 1] - t[lj - 1]);
                h[i - 1] = h[i - 1] + f * (t[li - 1] - x);
                h[i] = f * (x - t[lj - 1]);
            }
            else {
                h[i] = 0.0;
            }
        }
    }
}

/* SciPy v1.18.1 dfitpack.c:504-581. */
static void
fpbisp(const double* tx, const int nx, const double* ty, const int ny, const double* c,
       const int kx, const int ky, const double* x, const int mx, const double* y, const int my,
       double* z, double* wx, double* wy, int* lx, int* ly)
{
    int kx1, ky1, l, l1, l2, nkx1, nky1, i1, m;
    double arg, sp, tb, te, h[6];

    kx1 = kx + 1;
    nkx1 = nx - kx1;
    tb = tx[kx1 - 1];
    te = tx[nkx1];
    l  = kx1;
    l1 = l + 1;

    for (int i = 1; i <= mx; i++) {
        arg = x[i - 1];
        if (arg < tb) { arg = tb; }
        if (arg > te) { arg = te; }

        while (!((arg < tx[l1 - 1]) || (l == nkx1))) {
            l = l1;
            l1 = l + 1;
        }

        fpbspl(tx, nx, kx, arg, l, h);
        lx[i - 1] = l - kx1;
        for (int j = 1; j <= kx1; j++) {
            wx[(i - 1) + (j - 1)*mx] = h[j - 1];
        }
    }

    ky1 = ky + 1;
    nky1 = ny - ky1;
    tb = ty[ky1 - 1];
    te = ty[nky1];
    l  = ky1;
    l1 = l + 1;

    for (int i = 1; i <= my; i++) {
        arg = y[i - 1];
        if (arg < tb) { arg = tb; }
        if (arg > te) { arg = te; }

        while (!((arg < ty[l1 - 1]) || (l == nky1))) {
            l = l1;
            l1 = l + 1;
        }

        fpbspl(ty, ny, ky, arg, l, h);
        ly[i - 1] = l - ky1;
        for (int j = 1; j <= ky1; j++) {
            wy[(i - 1) + (j - 1) * my] = h[j - 1];
        }
    }

    m = 0;
    for (int i = 1; i <= mx; i++) {
        l = lx[i - 1] * nky1;
        for (int basis = 1; basis <= kx1; basis++) {
            h[basis - 1] = wx[(i - 1) + (basis - 1) * mx];
        }
        for (int j = 1; j <= my; j++) {
            l1 = l + ly[j - 1];
            sp = 0.0;
            for (i1 = 1; i1 <= kx1; i1++) {
                l2 = l1;
                for (int j1 = 1; j1 <= ky1; j1++) {
                    l2++;
                    sp = sp + c[l2 - 1] * h[i1 - 1] * wy[(j - 1) + (j1 - 1) * my];
                }
                l1 += nky1;
            }
            m++;
            z[m - 1] = sp;
        }
    }
}

/* SciPy v1.18.1 dfitpack.c:2227-2245. */
static void
fpgivs(const double piv, double* ww, double* cos, double* sin)
{
    // Subroutine fpgivs calculates the parameters of a Givens transformation.

    double dd;
    const double one = 1.0;
    double store = fabs(piv);

    if (store >= *ww) {
        dd = store * sqrt(fma(*ww / piv, *ww / piv, one));
    } else {
        dd = *ww * sqrt(fma(piv / *ww, piv / *ww, one));
    }

    *cos = *ww / dd;
    *sin = piv / dd;
    *ww = dd;
}

/* SciPy v1.18.1 dfitpack.c:5817-5824. */
static void
fprota(const double c, const double s, double* XY_RESTRICT a, double* XY_RESTRICT b)
{
    // fprota applies a givens rotation to the pair (a,b).
    const double old_a = *a, old_b = *b;
    double temp = fma(c, old_a, s * (-old_b));
    *b          = fma(c, old_b, s * old_a);
    *a          = temp;
}

/* SciPy v1.18.1 dfitpack.c:2248-2573. */
static void
fpgrre_interpolate(const double *x, const int mx, const double *y, const int my,
                   const double *z, const int kx, const int ky,
                   const double *tx, const int nx, const double *ty, const int ny,
                   double *c, double *fp, double *fpx, double *fpy,
                   double *spx, double *spy, double *right, double *q,
                   double *ax, double *ay, int *nrx, int *nry)
{
    const int kx1 = kx + 1, kx2 = kx + 2;
    const int ky1 = ky + 1, ky2 = ky + 2;
    int ifsx = 0, ifsy = 0;
    const double half = 0.5;

    int i, ibandx, ibandy, ic, iq, irot, it, iz, i1, i2, j, k, k1, k2, l, l1, l2;
    int ncof, nk1x, nk1y, nrold, nroldx, nroldy, number, numx, numx1, numy, numy1;
    double arg, cos, fac, piv, sin, term;
    double h[7];

    nk1x = nx - kx1;
    nk1y = ny - ky1;

    // calculate the non-zero elements of matrix (spx) - observation matrix in x-direction
    if (ifsx == 0) {
        l = kx1;
        l1 = kx2;
        number = 0;
        for (it = 1; it <= mx; it++) {
            arg = x[it - 1];
            while (!((arg < tx[l1 - 1]) || (l == nk1x))) {
                l = l1;
                l1 = l + 1;
                number++;
            }
            fpbspl(tx, nx, kx, arg, l, h);
            for (i = 1; i <= kx1; i++) {
                spx[(it - 1) + (i- 1) * mx] = h[i - 1];
            }
            nrx[it - 1] = number;
        }
        ifsx = 1;
    }

    // calculate the non-zero elements of matrix (spy) - observation matrix in y-direction
    if (ifsy == 0) {
        l = ky1;
        l1 = ky2;
        number = 0;
        for (it = 1; it <= my; it++) {
            arg = y[it - 1];
            while (!((arg < ty[l1 - 1]) || (l == nk1y))) {
                l = l1;
                l1 = l + 1;
                number++;
            }
            fpbspl(ty, ny, ky, arg, l, h);
            for (i = 1; i <= ky1; i++) {
                spy[(it - 1) + (i- 1) * my] = h[i - 1];
            }
            nry[it - 1] = number;
        }
        ifsy = 1;
    }


    // reduce matrix (ax) to upper triangular form (rx) using givens rotations
    // initialization
    for (i = 0; i < my * nk1x; i++) {
        q[i] = 0.0;
    }
    for (i = 0; i < nk1x; i++) {
        for (j = 0; j < kx2; j++) {
            ax[i + j * nx] = 0.0;
        }
    }

    l = 0;
    nrold = 0;
    // ibandx denotes the bandwidth of the matrices (ax) and (rx).
    ibandx = kx1;

    for (it = 1; it <= mx; it++) {
        number = nrx[it - 1];

        while (1) {

            if (nrold == number) {
                h[ibandx - 1] = 0.0;
                for (j = 1; j <= kx1; j++) {
                    h[j - 1] = spx[(it - 1) + (j - 1) * mx];
                }
                // find the appropriate column of q.
                for (j = 1; j <= my; j++) {
                    l++;
                    right[j - 1] = z[l - 1];
                }
                irot = number;
            } else {
                nrold++;
                continue;
            }

            // rotate the new row of matrix (ax) into triangle.
            for (i = 1; i <= ibandx; i++) {
                irot++;
                piv = h[i - 1];
                if (piv == 0.0) { continue; }
                // calculate the parameters of the givens transformation.
                fpgivs(piv, &ax[irot - 1], &cos, &sin);
                // apply that transformation to the rows of matrix q.
                iq = (irot - 1) * my;
                for (j = 1; j <= my; j++) {
                    iq++;
                    fprota(cos, sin, &right[j - 1], &q[iq - 1]);
                }
                // apply that transformation to the columns of (ax).
                if (i == ibandx) { break; }
                i2 = 1;
                for (j = i + 1; j <= ibandx; j++) {
                    i2++;
                    fprota(cos, sin, &h[j - 1], &ax[(irot - 1) + (i2 - 1) * nx]);
                }
            }
            // 240
            if (nrold == number) { break; }
            nrold++;
        }
    }

    // reduce the matrix (ay) to upper triangular form (ry) using givens
    // rotations. apply the same transformations to the columns of matrix g
    // to obtain the (ny-ky-1) x (nx-kx-1) matrix h.
    // store matrix (ry) into (ay) and h into c.
    ncof = nk1x * nk1y;
    for (i = 0; i < ncof; i++) {
        c[i] = 0.0;
    }
    for (i = 0; i < nk1y; i++) {
        for (j = 0; j < ky2; j++) {
            ay[i + j * ny] = 0.0;
        }
    }

    nrold = 0;
    // ibandy denotes the bandwidth of the matrices (ay) and (ry).
    ibandy = ky1;

    for (it = 1; it <= my; it++) {
        number = nry[it - 1];

        while (1) {

            if (nrold == number) {
                h[ibandy - 1] = 0.0;
                for (j = 1; j <= ky1; j++) {
                    h[j - 1] = spy[(it - 1) + (j - 1) * my];
                }
                // find the appropriate row of g.
                l = it;
                for (j = 1; j <= nk1x; j++) {
                    right[j - 1] = q[l - 1];
                    l += my;
                }
                irot = number;
            } else {
                nrold++;
                continue;
            }

            // rotate the new row of matrix (ay) into triangle.
            for (i = 1; i <= ibandy; i++) {
                irot++;
                piv = h[i - 1];
                if (piv == 0.0) { continue; }
                // calculate the parameters of the givens transformation.
                fpgivs(piv, &ay[irot - 1], &cos, &sin);
                // apply that transformation to the rows of matrix g.
                ic = irot;
                for (j = 1; j <= nk1x; j++) {
                    fprota(cos, sin, &right[j - 1], &c[ic - 1]);
                    ic += nk1y;
                }
                // apply that transformation to the columns of (ay).
                if (i == ibandy) { break; }
                i2 = 1;
                for (j = i + 1; j <= ibandy; j++) {
                    i2++;
                    fprota(cos, sin, &h[j - 1], &ay[(irot - 1) + (i2 - 1) * ny]);
                }
            }
            // 390
            if (nrold == number) { break; }
            nrold++;
        }
    }

    // backward substitution to obtain the b-spline coefficients as the
    // solution of the linear system    (ry) c (rx)' = h.
    // first step: solve the system  (ry) (c1) = h.
    k = 1;
    for (i = 1; i <= nk1x; i++) {
        fpback(ay, &c[k - 1], nk1y, ibandy, &c[k - 1], ny);
        k += nk1y;
    }

    // second step: solve c(rx)' = (c1)
    k = 0;
    for (j = 1; j <= nk1y; j++) {
        k++;
        l = k;
        for (i = 1; i <= nk1x; i++) {
            right[i - 1] = c[l - 1];
            l += nk1y;
        }
        fpback(ax, right, nk1x, ibandx, right, nx);
        l = k;
        for (i = 1; i <= nk1x; i++) {
            c[l - 1] = right[i - 1];
            l += nk1y;
        }
    }

    // calculate the quantities
    //   res(i,j) = (z(i,j) - s(x(i),y(j)))**2 , i=1,2,..,mx;j=1,2,..,my
    //   fp = sumi=1,mx(sumj=1,my(res(i,j)))
    //   fpx(r) = sum''i(sumj=1,my(res(i,j))) , r=1,2,...,nx-2*kx-1
    //                 tx(r+kx) <= x(i) <= tx(r+kx+1)
    //   fpy(r) = sumi=1,mx(sum''j(res(i,j))) , r=1,2,...,ny-2*ky-1
    //                 ty(r+ky) <= y(j) <= ty(r+ky+1)
    *fp = 0.0;
    for (i = 0; i < nx; i++) {
        fpx[i] = 0.0;
    }
    for (i = 0; i < ny; i++) {
        fpy[i] = 0.0;
    }
    nk1y = ny - ky1;
    iz = 0;
    nroldx = 0;

    // main loop for the different grid points.
    for (i1 = 1; i1 <= mx; i1++) {
        numx = nrx[i1 - 1];
        numx1 = numx + 1;
        nroldy = 0;

        for (i2 = 1; i2 <= my; i2++) {
            numy = nry[i2 - 1];
            numy1 = numy + 1;
            iz++;

            // evaluate s(x,y) at the current grid point by making the sum of the
            // cross products of the non-zero b-splines at (x,y), multiplied with
            // the appropriate b-spline coefficients.
            term = 0.0;
            k1 = numx * nk1y + numy;
            for (l1 = 1; l1 <= kx1; l1++) {
                k2 = k1;
                fac = spx[(i1 - 1) + (l1 - 1) * mx];
                for (l2 = 1; l2 <= ky1; l2++) {
                    k2++;
                    term = term + fac * spy[(i2 - 1) + (l2 - 1) * my] * c[k2-1];
                }
                k1 += nk1y;
            }

            // calculate the squared residual at the current grid point.
            term = pow(z[iz - 1] - term, 2);

            // adjust the different parameters.
            *fp = *fp + term;
            fpx[numx1 - 1] = fpx[numx1 - 1] + term;
            fpy[numy1 - 1] = fpy[numy1 - 1] + term;
            fac = term * half;

            if (numy != nroldy) {
                fpy[numy1 - 1] = fpy[numy1 - 1] - fac;
                fpy[numy - 1]  = fpy[numy - 1]  + fac;
            }
            nroldy = numy;

            if (numx != nroldx) {
                fpx[numx1 - 1] = fpx[numx1 - 1] - fac;
                fpx[numx - 1]  = fpx[numx - 1]  + fac;
            }
        }
        nroldx = numx;
    }
}

/* END SCIPY NUMERICAL SUBSET */

struct xy_fitpack_owner {
    int kx, ky, nx, ny;
    size_t coefficient_count;
    double *tx, *ty, *coefficients;
};

static int count_product(size_t a, size_t b, size_t *output)
{
    if (b && a > SIZE_MAX / b) return 0;
    *output = a * b;
    return *output <= INT_MAX;
}

static int workspace_count(const size_t *parts, size_t n, size_t *output)
{
    size_t count = 0;
    for (size_t i = 0; i < n; ++i) {
        if (parts[i] > INT_MAX || count > SIZE_MAX - parts[i]) return 0;
        count += parts[i];
    }
    if (count > SIZE_MAX / sizeof(double)) return 0;
    *output = count;
    return 1;
}

static int finite_axis(const double *axis, size_t count)
{
    if (!axis || !count || count > INT_MAX) return 0;
    for (size_t i = 0; i < count; ++i) {
        if (!isfinite(axis[i]) || (i && axis[i - 1] >= axis[i])) return 0;
    }
    return 1;
}

static int finite_values(const double *values, size_t count)
{
    for (size_t i = 0; i < count; ++i) {
        if (!isfinite(values[i])) return 0;
    }
    return 1;
}

/* Preserve fpregr's interpolation-knot expressions and endpoint order. */
static void interpolation_knots(const double *axis, int m, int k, double *t)
{
    const int k1 = k + 1;
    const int n = m + k1;
    const int interior = m - k1;
    const int k3 = k / 2;
    int i = k1 + 1;
    int j = k3 + 2;
    if ((k3 * 2) == k) {
        for (int l = 1; l <= interior; ++l) {
            t[i - 1] = (axis[j - 1] + axis[j - 2]) * 0.5;
            i++;
            j++;
        }
    } else {
        for (int l = 1; l <= interior; ++l) {
            t[i - 1] = axis[j - 1];
            i++;
            j++;
        }
    }
    i = n;
    for (j = 1; j <= k1; ++j) {
        t[j - 1] = axis[0];
        t[i - 1] = axis[m - 1];
        i--;
    }
}

void xy_fitpack_release(xy_fitpack_owner *owner)
{
    if (!owner) return;
    free(owner->tx);
    free(owner->ty);
    free(owner->coefficients);
    free(owner);
}

int xy_fitpack_create(const double *x, size_t mx,
                     const double *y, size_t my,
                     const double *z, size_t z_count,
                     int degree_x, int degree_y,
                     xy_fitpack_owner **output)
{
    size_t coefficients, total, parts[8];
    if (!output || !x || !y || !z || degree_x < 1 || degree_x > 3 ||
        degree_y < 1 || degree_y > 3 ||
        mx <= (size_t)degree_x || my <= (size_t)degree_y ||
        mx > (size_t)(INT_MAX - degree_x - 1) ||
        my > (size_t)(INT_MAX - degree_y - 1) ||
        !count_product(mx, my, &coefficients) || z_count != coefficients)
        return XY_FITPACK_INVALID_INPUT;

    const size_t nx = mx + (size_t)degree_x + 1;
    const size_t ny = my + (size_t)degree_y + 1;
    if (!count_product(mx, (size_t)degree_x + 1, &parts[0]) ||
        !count_product(my, (size_t)degree_y + 1, &parts[1]) ||
        !count_product(nx, (size_t)degree_x + 2, &parts[4]) ||
        !count_product(ny, (size_t)degree_y + 2, &parts[5]))
        return XY_FITPACK_INVALID_INPUT;
    parts[2] = mx > my ? mx : my;
    parts[3] = coefficients;
    parts[6] = nx;
    parts[7] = ny;
    /* The final unused FITPACK cursor step can pass the coefficient extent. */
    if (coefficients > (size_t)INT_MAX - parts[2] ||
        !workspace_count(parts, 8, &total) || mx > SIZE_MAX - my ||
        mx + my > SIZE_MAX / sizeof(int)) return XY_FITPACK_INVALID_INPUT;
    if (!finite_axis(x, mx) || !finite_axis(y, my) || !finite_values(z, z_count))
        return XY_FITPACK_INVALID_INPUT;

    xy_fitpack_owner *owner = calloc(1, sizeof(*owner));
    if (!owner) return XY_FITPACK_ALLOCATION_FAILED;
    owner->kx = degree_x;
    owner->ky = degree_y;
    owner->nx = (int)nx;
    owner->ny = (int)ny;
    owner->coefficient_count = coefficients;
    owner->tx = malloc(nx * sizeof(double));
    owner->ty = malloc(ny * sizeof(double));
    owner->coefficients = calloc(coefficients, sizeof(double));
    double *work = calloc(total, sizeof(double));
    int *indices = calloc(mx + my, sizeof(int));
    if (!owner->tx || !owner->ty || !owner->coefficients || !work || !indices) {
        free(work);
        free(indices);
        xy_fitpack_release(owner);
        return XY_FITPACK_ALLOCATION_FAILED;
    }
    interpolation_knots(x, (int)mx, degree_x, owner->tx);
    interpolation_knots(y, (int)my, degree_y, owner->ty);

    double *spx = work;
    double *spy = spx + parts[0];
    double *right = spy + parts[1];
    double *q = right + parts[2];
    double *ax = q + parts[3];
    double *ay = ax + parts[4];
    double *fpx = ay + parts[5];
    double *fpy = fpx + parts[6];
    double residual;
    fpgrre_interpolate(x, (int)mx, y, (int)my, z,
        degree_x, degree_y, owner->tx, owner->nx, owner->ty, owner->ny,
        owner->coefficients, &residual, fpx, fpy,
        spx, spy, right, q, ax, ay, indices, indices + mx);
    free(work);
    free(indices);
    *output = owner;
    return XY_FITPACK_OK;
}

int xy_fitpack_get_view(const xy_fitpack_owner *owner, xy_fitpack_view *output)
{
    if (!owner || !output) return XY_FITPACK_INVALID_INPUT;
    const xy_fitpack_view view = {
        owner->kx, owner->ky, (size_t)owner->nx, (size_t)owner->ny,
        owner->coefficient_count, owner->tx, owner->ty, owner->coefficients
    };
    *output = view;
    return XY_FITPACK_OK;
}

int xy_fitpack_evaluate(const xy_fitpack_owner *owner,
                       const double *x, size_t mx,
                       const double *y, size_t my,
                       double *output, size_t output_count)
{
    size_t count, parts[2], total;
    if (!owner || !output || !x || !y || !mx || !my ||
        !count_product(mx, my, &count) || output_count != count ||
        !count_product(mx, (size_t)owner->kx + 1, &parts[0]) ||
        !count_product(my, (size_t)owner->ky + 1, &parts[1]) ||
        !workspace_count(parts, 2, &total) || mx > SIZE_MAX - my ||
        mx + my > SIZE_MAX / sizeof(int)) return XY_FITPACK_INVALID_INPUT;
    if (!finite_axis(x, mx) || !finite_axis(y, my) ||
        x[0] < owner->tx[owner->kx] || x[mx - 1] > owner->tx[owner->nx - owner->kx - 1] ||
        y[0] < owner->ty[owner->ky] || y[my - 1] > owner->ty[owner->ny - owner->ky - 1])
        return XY_FITPACK_INVALID_INPUT;

    double *work = malloc(total * sizeof(double));
    int *indices = malloc((mx + my) * sizeof(int));
    if (!work || !indices) {
        free(work);
        free(indices);
        return XY_FITPACK_ALLOCATION_FAILED;
    }
    fpbisp(owner->tx, owner->nx, owner->ty, owner->ny, owner->coefficients,
        owner->kx, owner->ky, x, (int)mx, y, (int)my,
        output, work, work + parts[0], indices, indices + mx);
    free(work);
    free(indices);
    return XY_FITPACK_OK;
}
