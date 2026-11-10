#include "tpmshx/result_arithmetic.hpp"

#include <array>
#include <cstdint>
#include <iostream>

int main() {
    using namespace tpmshx::result;
    std::array<std::uint64_t,2> integers{UINT64_C(9007199254740993),UINT64_MAX};
    const std::array<std::size_t,1> shape{2};
    const std::array<std::ptrdiff_t,1> strides{8};
    RawArray raw{integers.data(),sizeof(integers),0,TPMSHX_RESULT_U64,TPMSHX_RESULT_NUMPY_ARRAY,
        TPMSHX_RESULT_NATIVE_ENDIAN,0,1,shape.data(),strides.data()};
    Array values(raw);
    if (values.at(0).unsigned_value!=integers[0] || values.at(1).unsigned_value!=integers[1]) return 1;
    if (arithmetic::python_float_sum({1e16,1.,-1e16})!=1.) return 2;
    const auto scalar=pack_scalar(values.at(1));
    if (read_scalar(scalar).unsigned_value!=UINT64_MAX) return 3;
    std::cout<<"PASS: independent result C++ caller and exact integer transport\n";
    return 0;
}
