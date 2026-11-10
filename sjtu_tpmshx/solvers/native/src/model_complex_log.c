/* NumPy calls the system C complex log on macOS. */
#include <complex.h>

void tpmshx_model_complex_log(double real,double imaginary,double* result) {
    const double complex value=CMPLX(real,imaginary);
    const double complex logarithm=clog(value);
    result[0]=creal(logarithm);
    result[1]=cimag(logarithm);
}
