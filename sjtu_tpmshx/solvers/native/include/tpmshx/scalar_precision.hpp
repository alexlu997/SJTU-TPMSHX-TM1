#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>

namespace tpmshx::geometry::detail {

inline void require_precision(std::uint32_t precision) {
    if (precision!=16 && precision!=32 && precision!=64)
        throw std::invalid_argument("geometry scalar precision must be 16, 32 or 64");
}

inline double round_scalar(double value, std::uint32_t precision) {
    if (precision==64) return value;
    if (precision==32) return static_cast<float>(value);
    require_precision(precision);
    if (!std::isfinite(value) || value==0.) return value;
    // Round one scalar to binary16, with ties to an even significand.
    int exponent=0;
    const double magnitude=std::abs(value);
    std::frexp(magnitude,&exponent);
    if (exponent>16) return std::copysign(std::numeric_limits<double>::infinity(),value);
    const double step=std::ldexp(1.,std::max(-24,exponent-11));
    const double scaled=magnitude/step;
    double integral=std::floor(scaled);
    const double remainder=scaled-integral;
    if (remainder>.5 || (remainder==.5 && std::fmod(integral,2.)!=0.)) ++integral;
    const double rounded=integral*step;
    return std::copysign(rounded>=65536. ? std::numeric_limits<double>::infinity() : rounded,value);
}

inline double multiply(double first, double second, std::uint32_t precision) {
    if (precision==64) return first*second;
    const float left=static_cast<float>(round_scalar(first,precision));
    const float right=static_cast<float>(round_scalar(second,precision));
    return round_scalar(left*right,precision);
}

inline double divide(double first, double second, std::uint32_t precision) {
    if (precision==64) return first/second;
    const float left=static_cast<float>(round_scalar(first,precision));
    const float right=static_cast<float>(round_scalar(second,precision));
    return round_scalar(left/right,precision);
}

}  // namespace tpmshx::geometry::detail
