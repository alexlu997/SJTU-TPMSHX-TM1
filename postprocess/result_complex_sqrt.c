/* NumPy calls the system C complex square root on macOS. */
#include <complex.h>

void tpmshx_result_complex_sqrt_f32(float real,float imaginary,float* result) {
    const float complex value=csqrtf(CMPLXF(real,imaginary));
    result[0]=crealf(value);result[1]=cimagf(value);
}

void tpmshx_result_complex_sqrt_f64(double real,double imaginary,double* result) {
    const double complex value=csqrt(CMPLX(real,imaginary));
    result[0]=creal(value);result[1]=cimag(value);
}

void tpmshx_result_complex_sqrt_long_double(long double real,long double imaginary,long double* result) {
    const long double complex value=csqrtl(CMPLXL(real,imaginary));
    result[0]=creall(value);result[1]=cimagl(value);
}
