#pragma once

#include "tpmshx/result_core.hpp"

#include <vector>

namespace tpmshx::result::arithmetic {

// Temporary numerical arrays retain compact dtype storage. Number is a point.
struct Tensor {
    std::uint32_t dtype{}, origin{TPMSHX_RESULT_NUMPY_ARRAY};
    std::vector<std::size_t> shape;
    std::vector<std::ptrdiff_t> strides;
    std::vector<unsigned char> bytes;
    Tensor(std::vector<std::size_t> shape, std::uint32_t dtype,
           std::uint32_t origin=TPMSHX_RESULT_NUMPY_ARRAY, bool fortran=false);
    RawArray raw() const;
    Array array() const {return Array(raw());}
    std::size_t size() const;
    void put(std::size_t logical_c_index, const Number& value);
};

Number python_float(double value);
Number python_int(std::int64_t value);
Number scalar_result(Number value);
std::uint32_t promote_dtype(std::uint32_t first, std::uint32_t second);
Number cast(const Number&, std::uint32_t dtype, std::uint32_t origin, Diagnostics&);
Tensor cast(const Array&, std::uint32_t dtype, Diagnostics&);
double to_float(const Number&);
Tensor scalar(const Number&);
Tensor copy(const Array&, bool force_c=false);

Number add(const Number&,const Number&,Diagnostics&);
Number subtract(const Number&,const Number&,Diagnostics&);
Number multiply(const Number&,const Number&,Diagnostics&);
Number divide(const Number&,const Number&,Diagnostics&);
Number negative(const Number&,Diagnostics&);
Number absolute(const Number&,Diagnostics&);
Number square(const Number&,Diagnostics&);
Number power_two(const Number&,Diagnostics&);
Number square_root(const Number&,Diagnostics&);
Number maximum(const Number&,const Number&,Diagnostics&);
Number minimum(const Number&,const Number&,Diagnostics&);
bool less(const Number&,const Number&,Diagnostics&);
bool less_equal(const Number&,const Number&,Diagnostics&);
bool equal(const Number&,const Number&,Diagnostics&);

Tensor add(const Array&,const Array&,Diagnostics&);
Tensor subtract(const Array&,const Array&,Diagnostics&);
Tensor multiply(const Array&,const Array&,Diagnostics&);
Tensor divide(const Array&,const Array&,Diagnostics&);
Tensor negative(const Array&,Diagnostics&);
Tensor absolute(const Array&,Diagnostics&);
Tensor square(const Array&,Diagnostics&);
Tensor power_two(const Array&,Diagnostics&);
Tensor square_root(const Array&,Diagnostics&);
Tensor maximum(const Array&,const Array&,Diagnostics&);
Tensor minimum(const Array&,const Array&,Diagnostics&);
Tensor difference(const Array&,std::size_t axis,Diagnostics&);

Number sum(const Array&,Diagnostics&);
Number mean(const Array&,Diagnostics&);
Number variance(const Array&,Diagnostics&);
Number standard_deviation(const Array&,Diagnostics&);
Number maximum(const Array&,Diagnostics&);
Number minimum(const Array&,Diagnostics&);
double sum_as_float(const Array&,Diagnostics&);
double python_float_sum(const std::vector<double>&);

}  // namespace tpmshx::result::arithmetic
