#pragma once

#include "tpmshx/result_core.hpp"

#include <vector>

namespace tpmshx::result::arithmetic {

// Temporary values use contiguous C-order binary64 storage.
struct Tensor {
    std::vector<std::size_t> shape;
    std::vector<double> values;
    Kind kind{Kind::numpy_array};
    explicit Tensor(std::vector<std::size_t> shape = {}, Kind kind = Kind::numpy_array);
    RawArray raw() const {return {values.data(), shape.size(), shape.data()};}
    Array array() const {return Array(raw(), kind);}
    std::size_t size() const {return values.size();}
};

Number python_float(double value);
Number numpy_scalar(Number value);
Tensor scalar(const Number&);
Tensor copy(const Array&);

Number add(const Number&,const Number&,Diagnostics&);
Number subtract(const Number&,const Number&,Diagnostics&);
Number multiply(const Number&,const Number&,Diagnostics&);
Number divide(const Number&,const Number&,Diagnostics&);
Number absolute(const Number&);
Number square_root(const Number&,Diagnostics&);
bool less(const Number&,const Number&);
bool less_equal(const Number&,const Number&);

Tensor add(const Array&,const Array&,Diagnostics&);
Tensor subtract(const Array&,const Array&,Diagnostics&);
Tensor multiply(const Array&,const Array&,Diagnostics&);
Tensor divide(const Array&,const Array&,Diagnostics&);
Tensor maximum(const Array&,const Array&,Diagnostics&);
Tensor negative(const Array&);
Tensor absolute(const Array&);
Tensor square(const Array&,Diagnostics&);
Tensor power_two(const Array&,Diagnostics&);
Tensor square_root(const Array&,Diagnostics&);
Tensor difference(const Array&,std::size_t axis,Diagnostics&);

Number sum(const Array&,Diagnostics&);
Number mean(const Array&,Diagnostics&);
Number standard_deviation(const Array&,Diagnostics&);
Number maximum(const Array&);
Number minimum(const Array&);
double sum_as_float(const Array&,Diagnostics&);
double python_float_sum(const std::vector<double>&);

}  // namespace tpmshx::result::arithmetic
