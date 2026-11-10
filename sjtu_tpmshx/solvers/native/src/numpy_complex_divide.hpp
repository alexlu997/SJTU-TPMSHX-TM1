#pragma once

#include <cmath>
#include <complex>

namespace tpmshx::detail {

#if defined(__APPLE__) && defined(__aarch64__)
// The locked macOS arm64 CPython and NumPy quotients fuse these expressions.
inline constexpr bool contract_complex_quotient=true;
#else
inline constexpr bool contract_complex_quotient=false;
#endif

// NumPy 2.5.4 complex divide uses one reciprocal in its scalar loop.
template<class Real> std::complex<Real> numpy_complex_divide(std::complex<Real> a,std::complex<Real> b) {
    const Real ar=a.real(),ai=a.imag(),br=b.real(),bi=b.imag();
    const Real abs_br=std::abs(br),abs_bi=std::abs(bi);
    if (abs_br>=abs_bi) {
        if (abs_br==Real{0} && abs_bi==Real{0}) return {ar/abs_br,ai/abs_bi};
        const Real ratio=bi/br;
        const Real denominator=contract_complex_quotient?std::fma(bi,ratio,br):br+bi*ratio;
        const Real scale=Real{1}/denominator;
        const Real real=contract_complex_quotient?std::fma(ai,ratio,ar):ar+ai*ratio;
        const Real imaginary=contract_complex_quotient?std::fma(-ar,ratio,ai):ai-ar*ratio;
        return {real*scale,imaginary*scale};
    }
    const Real ratio=br/bi;
    const Real denominator=contract_complex_quotient?std::fma(br,ratio,bi):bi+br*ratio;
    const Real scale=Real{1}/denominator;
    const Real real=contract_complex_quotient?std::fma(ar,ratio,ai):ar*ratio+ai;
    const Real imaginary=contract_complex_quotient?std::fma(ai,ratio,-ar):ai*ratio-ar;
    return {real*scale,imaginary*scale};
}

}  // namespace tpmshx::detail
