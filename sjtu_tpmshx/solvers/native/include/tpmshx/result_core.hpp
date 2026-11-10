#pragma once

#include "tpmshx/result_c_api.h"

#include <cfenv>
#include <complex>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>

namespace tpmshx::result {

using RawArray = tpmshx_result_array_v1;
using RawScalar = tpmshx_result_scalar_v1;
using Diagnostics = tpmshx_result_diagnostics_v1;

// A point keeps exact integer storage. Floating components use their dtype's
// rounding before storage; long double preserves the platform's wider values.
struct Number {
    std::uint32_t dtype{}, origin{};
    std::int64_t signed_value{};
    std::uint64_t unsigned_value{};
    long double real{}, imaginary{};
};

class NumericError : public std::runtime_error {
public:
    NumericError(std::uint32_t cause_value, std::string message, std::int32_t error_value = 0)
        :std::runtime_error(std::move(message)), cause(cause_value), error_number(error_value) {}
    std::uint32_t cause;
    std::int32_t error_number;
};

class FloatingEnvironment {
public:
    FloatingEnvironment() {std::fegetenv(&saved_);}
    ~FloatingEnvironment() {std::fesetenv(&saved_);}
    FloatingEnvironment(const FloatingEnvironment&) = delete;
    FloatingEnvironment& operator=(const FloatingEnvironment&) = delete;
private:
    std::fenv_t saved_;
};

std::size_t item_size(std::uint32_t dtype);
bool integer_type(std::uint32_t dtype);
bool signed_type(std::uint32_t dtype);
bool complex_type(std::uint32_t dtype);
Number read_number(const void* data, std::uint32_t dtype, std::uint32_t byte_order, std::uint32_t origin);
Number read_scalar(const RawScalar& value);
RawScalar pack_scalar(const Number& value);
void store_number(void* destination, const Number& value);
void copy_number(const void* source, std::uint32_t source_order, void* destination,
                 std::uint32_t destination_order, std::uint32_t dtype);
long double real_value(const Number& value);
bool finite(const Number& value);
bool zero(const Number& value);
long double round_real(long double value, std::uint32_t dtype);
Number floating(long double value, std::uint32_t dtype, std::uint32_t origin);
Number complex_number(long double real, long double imaginary, std::uint32_t dtype, std::uint32_t origin);
Number signed_bits(std::uint64_t value, std::uint32_t dtype, std::uint32_t origin);
Number unsigned_bits(std::uint64_t value, std::uint32_t dtype, std::uint32_t origin);
void append_event(Diagnostics& diagnostics, std::uint32_t flags, std::uint32_t operation, bool scalar);

// Element reads retain the array origin. A scalar index/slice changes origin
// only at the source operation that performs that selection.
class Array {
public:
    explicit Array(const RawArray& input);
    const RawArray& raw() const {return raw_;}
    std::size_t size() const {return count_;}
    Number at(std::size_t logical_c_index) const;
    const unsigned char* address(std::size_t logical_c_index) const;
private:
    RawArray raw_;
    std::size_t count_{};
};

}  // namespace tpmshx::result
