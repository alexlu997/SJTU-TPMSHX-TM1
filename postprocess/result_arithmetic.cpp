#include "tpmshx/result_arithmetic.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <string>

namespace tpmshx::result::arithmetic {
namespace {

bool strong(Kind kind) {return kind != Kind::python_float;}
Kind result_kind(Kind first, Kind second) {
    if (first == Kind::numpy_array || second == Kind::numpy_array) return Kind::numpy_array;
    return strong(first) || strong(second) ? Kind::numpy_scalar : Kind::python_float;
}
std::uint32_t fp_flags() {
    const int value = std::fetestexcept(FE_ALL_EXCEPT);
    return ((value & FE_DIVBYZERO) ? 1u : 0u) | ((value & FE_OVERFLOW) ? 2u : 0u)
        | ((value & FE_UNDERFLOW) ? 4u : 0u) | ((value & FE_INVALID) ? 8u : 0u);
}
double real_binary(double a, double b, std::uint32_t op) {
    // Keep the FP operation inside the feclearexcept/fetestexcept window.
    const volatile double x = a, y = b;
    switch (op) {
    case TPMSHX_RESULT_ADD: return x + y;
    case TPMSHX_RESULT_SUBTRACT: return x - y;
    case TPMSHX_RESULT_MULTIPLY: return x * y;
    default: return x / y;
    }
}
// Python float division raises before its quotient; NumPy values do not.
void python_division(Kind first, Kind second, std::uint32_t op, double divisor) {
    if (op == TPMSHX_RESULT_DIVIDE && !strong(first) && !strong(second) && divisor == 0.)
        throw NumericError(TPMSHX_RESULT_ZERO_DIVISION, "float division by zero");
}
Number binary(const Number& left, const Number& right, Diagnostics& d, std::uint32_t op) {
    const auto kind = result_kind(left.kind, right.kind);
    python_division(left.kind, right.kind, op, right.value);
    std::feclearexcept(FE_ALL_EXCEPT);
    const volatile double value = real_binary(left.value, right.value, op);
    const Number out{value, kind};
    if (strong(left.kind) || strong(right.kind)) append_event(d, fp_flags(), op, kind != Kind::numpy_array);
    return out;
}
std::string shape_text(const Array& value) {
    std::string out = "(";
    for (std::size_t j = 0; j < value.rank(); ++j) {if (j) out += ","; out += std::to_string(value.raw().shape[j]);}
    if (value.rank() == 1) out += ",";
    return out + ")";
}
std::vector<std::size_t> broadcast(const Array& a, const Array& b) {
    const auto rank = std::max(a.rank(), b.rank());
    std::vector<std::size_t> out(rank, 1);
    for (std::size_t i = 0; i < rank; ++i) {
        const auto x = i < rank - a.rank() ? 1 : a.raw().shape[i - (rank - a.rank())];
        const auto y = i < rank - b.rank() ? 1 : b.raw().shape[i - (rank - b.rank())];
        if (x != y && x != 1 && y != 1)
            throw NumericError(TPMSHX_RESULT_VALUE_ERROR,
                "operands could not be broadcast together with shapes " + shape_text(a) + " " + shape_text(b) + " ");
        out[i] = x == 1 ? y : x;
    }
    return out;
}
std::size_t operand_index(const Array& a, std::size_t index, const std::vector<std::size_t>& shape) {
    std::size_t flat = 0, multiplier = 1;
    for (std::size_t k = 0; k < shape.size(); ++k) {
        const auto axis = shape.size() - 1 - k, coordinate = shape[axis] ? index % shape[axis] : 0;
        index = shape[axis] ? index / shape[axis] : 0;
        if (k < a.rank()) {
            const auto n = a.raw().shape[a.rank() - 1 - k];
            flat += (n == 1 ? 0 : coordinate) * multiplier; multiplier *= n;
        }
    }
    return flat;
}
// One event covers all elements of an array operation, as in one NumPy ufunc call.
void publish(Diagnostics& d, std::uint32_t flags, std::uint32_t op, Kind kind) {
    append_event(d, flags, op, kind != Kind::numpy_array);
}
template<class Operation> Tensor apply(const Array& a, const Array& b, Diagnostics& d, std::uint32_t op,
                                      Operation operation, bool notices = true) {
    const auto shape = broadcast(a, b);
    Tensor out(shape, result_kind(a.kind(), b.kind()));
    const bool enabled = notices && (strong(a.kind()) || strong(b.kind()));
    if (!strong(a.kind()) && !strong(b.kind()))
        for (std::size_t i = 0; i < out.size(); ++i)
            python_division(a.kind(), b.kind(), op, b.at(operand_index(b, i, shape)));
    std::feclearexcept(FE_ALL_EXCEPT);
    for (std::size_t i = 0; i < out.size(); ++i) {
        const volatile double x = a.at(operand_index(a, i, shape));
        const volatile double y = b.at(operand_index(b, i, shape));
        const volatile double value = operation(x, y);
        out.values[i] = value;
    }
    if (enabled) publish(d, fp_flags(), op, out.kind);
    return out;
}
template<class Operation> Tensor apply(const Array& a, Diagnostics& d, std::uint32_t op, Operation operation) {
    Tensor out(a.shape(), a.kind());
    std::feclearexcept(FE_ALL_EXCEPT);
    for (std::size_t i = 0; i < a.size(); ++i) {
        const volatile double x = a.at(i);
        const volatile double value = operation(x);
        out.values[i] = value;
    }
    if (strong(a.kind())) publish(d, fp_flags(), op, out.kind);
    return out;
}
// Comparisons use quiet predicates: NumPy maximum reports no invalid notice for NaN.
double maximum_value(double x, double y) {return std::isnan(x) || std::isless(y, x) ? x : y;}
double minimum_value(double x, double y) {return std::isnan(x) || std::isless(x, y) ? x : y;}
template<class Getter> double pairwise(Getter get, std::size_t offset, std::size_t count) {
    if (count < 8) {double out = -0.; for (std::size_t i = 0; i < count; ++i) out += get(offset + i); return out;}
    if (count > 128) {
        const auto middle = (count / 2) / 8 * 8;
        return pairwise(get, offset, middle) + pairwise(get, offset + middle, count - middle);
    }
    std::array<double, 8> partial;
    for (std::size_t j = 0; j < 8; ++j) partial[j] = get(offset + j);
    std::size_t i = 8;
    for (; i + 8 <= count; i += 8) for (std::size_t j = 0; j < 8; ++j) partial[j] += get(offset + i + j);
    auto out = ((partial[0] + partial[1]) + (partial[2] + partial[3])) + ((partial[4] + partial[5]) + (partial[6] + partial[7]));
    for (; i < count; ++i) out += get(offset + i);
    return out;
}
Number count_value(std::size_t count) {return {static_cast<double>(count), Kind::numpy_scalar};}
}  // namespace

Tensor::Tensor(std::vector<std::size_t> sizes, Kind source):shape(std::move(sizes)), kind(source) {
    values.resize(element_count(shape.size(), shape.data()));
}
Number python_float(double value) {return {value, Kind::python_float};}
Number numpy_scalar(Number value) {if (value.kind == Kind::numpy_array) value.kind = Kind::numpy_scalar; return value;}
Tensor scalar(const Number& value) {Tensor out({}, value.kind); out.values[0] = value.value; return out;}
Tensor copy(const Array& a) {
    Tensor out(a.shape(), a.kind());
    for (std::size_t i = 0; i < a.size(); ++i) out.values[i] = a.at(i);
    return out;
}
Number add(const Number& a, const Number& b, Diagnostics& d) {return binary(a, b, d, TPMSHX_RESULT_ADD);}
Number subtract(const Number& a, const Number& b, Diagnostics& d) {return binary(a, b, d, TPMSHX_RESULT_SUBTRACT);}
Number multiply(const Number& a, const Number& b, Diagnostics& d) {return binary(a, b, d, TPMSHX_RESULT_MULTIPLY);}
Number divide(const Number& a, const Number& b, Diagnostics& d) {return binary(a, b, d, TPMSHX_RESULT_DIVIDE);}
Number absolute(const Number& a) {return {std::fabs(a.value), a.kind};}
Number square_root(const Number& a, Diagnostics& d) {
    std::feclearexcept(FE_ALL_EXCEPT);
    const volatile double x = a.value;
    const volatile double value = std::sqrt(x);
    const Number out{value, a.kind};
    if (strong(a.kind)) append_event(d, fp_flags(), TPMSHX_RESULT_SQRT, a.kind != Kind::numpy_array);
    return out;
}
bool less(const Number& a, const Number& b) {return std::isless(a.value, b.value);}
bool less_equal(const Number& a, const Number& b) {return std::islessequal(a.value, b.value);}

Tensor add(const Array& a, const Array& b, Diagnostics& d) {return apply(a, b, d, TPMSHX_RESULT_ADD, [](double x, double y) {return x + y;});}
Tensor subtract(const Array& a, const Array& b, Diagnostics& d) {return apply(a, b, d, TPMSHX_RESULT_SUBTRACT, [](double x, double y) {return x - y;});}
Tensor multiply(const Array& a, const Array& b, Diagnostics& d) {return apply(a, b, d, TPMSHX_RESULT_MULTIPLY, [](double x, double y) {return x * y;});}
Tensor divide(const Array& a, const Array& b, Diagnostics& d) {return apply(a, b, d, TPMSHX_RESULT_DIVIDE, [](double x, double y) {return x / y;});}
Tensor maximum(const Array& a, const Array& b, Diagnostics& d) {return apply(a, b, d, TPMSHX_RESULT_MAXIMUM, maximum_value, false);}
Tensor negative(const Array& a) {Tensor out(a.shape(), a.kind()); for (std::size_t i = 0; i < a.size(); ++i) out.values[i] = -a.at(i); return out;}
Tensor absolute(const Array& a) {Tensor out(a.shape(), a.kind()); for (std::size_t i = 0; i < a.size(); ++i) out.values[i] = std::fabs(a.at(i)); return out;}
Tensor square(const Array& a, Diagnostics& d) {return apply(a, d, TPMSHX_RESULT_SQUARE, [](double x) {return x * x;});}
Tensor power_two(const Array& a, Diagnostics& d) {
    return apply(a, d, a.kind() == Kind::numpy_scalar ? TPMSHX_RESULT_POWER : TPMSHX_RESULT_SQUARE, [](double x) {return x * x;});
}
Tensor square_root(const Array& a, Diagnostics& d) {return apply(a, d, TPMSHX_RESULT_SQRT, [](double x) {return std::sqrt(x);});}
Tensor difference(const Array& a, std::size_t axis, Diagnostics& d) {
    if (axis >= a.rank()) throw NumericError(TPMSHX_RESULT_INDEX_ERROR, "axis is out of bounds");
    auto shape = a.shape(); if (shape[axis]) --shape[axis];
    Tensor out(shape);
    std::size_t trailing = 1; for (std::size_t j = axis + 1; j < shape.size(); ++j) trailing *= shape[j];
    std::feclearexcept(FE_ALL_EXCEPT);
    for (std::size_t i = 0; i < out.size(); ++i) {
        const auto inner = i % trailing, position = (i / trailing) % shape[axis], outer = i / (trailing * shape[axis]);
        const auto first = (outer * a.raw().shape[axis] + position) * trailing + inner;
        const volatile double hi = a.at(first + trailing), lo = a.at(first);
        const volatile double value = hi - lo;
        out.values[i] = value;
    }
    publish(d, fp_flags(), TPMSHX_RESULT_SUBTRACT, Kind::numpy_array);
    return out;
}

// NumPy 2.5.4 loops_utils.h.src pairwise summation of binary64 values.
Number sum(const Array& a, Diagnostics& d) {
    std::feclearexcept(FE_ALL_EXCEPT);
    const volatile double total = 0. + pairwise([&](std::size_t i) {return a.at(i);}, 0, a.size());
    publish(d, fp_flags(), TPMSHX_RESULT_REDUCE, Kind::numpy_array);
    return {total, Kind::numpy_scalar};
}
double sum_as_float(const Array& a, Diagnostics& d) {return sum(a, d).value;}
Number mean(const Array& a, Diagnostics& d) {return divide(sum(a, d), count_value(a.size()), d);}
Number standard_deviation(const Array& a, Diagnostics& d) {
    auto total = sum(a, d); total.kind = Kind::numpy_array;
    const auto center = scalar(divide(total, count_value(a.size()), d));
    const auto differences = subtract(a, center.array(), d);
    const auto squared = square(differences.array(), d);
    const auto variance = divide(sum(squared.array(), d), count_value(a.size()), d);
    return square_root(variance, d);
}
Number maximum(const Array& a) {
    if (!a.size()) throw NumericError(TPMSHX_RESULT_VALUE_ERROR, "zero-size array to reduction operation maximum which has no identity");
    double out = a.at(0); for (std::size_t i = 1; i < a.size(); ++i) out = maximum_value(out, a.at(i));
    return {out, Kind::numpy_scalar};
}
Number minimum(const Array& a) {
    if (!a.size()) throw NumericError(TPMSHX_RESULT_VALUE_ERROR, "zero-size array to reduction operation minimum which has no identity");
    double out = a.at(0); for (std::size_t i = 1; i < a.size(); ++i) out = minimum_value(out, a.at(i));
    return {out, Kind::numpy_scalar};
}

// Copyright (c) 2001-2024 Python Software Foundation; All Rights Reserved.
// Adapted from CPython 3.13.2 bltinmodule.c; the retained Python license applies.
double python_float_sum(const std::vector<double>& values) {
    if (values.empty()) return 0.;
    double total = 0. + values[0], correction = 0.;
    for (std::size_t i = 1; i < values.size(); ++i) {
        const auto x = values[i], next = total + x;
        if (std::fabs(total) >= std::fabs(x)) correction += (total - next) + x;
        else correction += (x - next) + total;
        total = next;
    }
    if (correction != 0. && std::isfinite(correction)) total += correction;
    return total;
}

}  // namespace tpmshx::result::arithmetic
