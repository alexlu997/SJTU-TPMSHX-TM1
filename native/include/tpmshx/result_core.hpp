#pragma once

#include "tpmshx/result_c_api.h"

#include <cfenv>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace tpmshx::result {

using RawArray = tpmshx_result_array_v2;
using RawLabels = tpmshx_result_labels_v1;
using Diagnostics = tpmshx_result_diagnostics_v1;

// The original expressions mix Python floats, NumPy scalars from reductions
// and NumPy arrays. All three hold binary64 values; the kind selects the
// division and floating-point notice rules of the original operation.
enum class Kind : std::uint8_t {python_float, numpy_scalar, numpy_array};

struct Number {
    double value{};
    Kind kind{Kind::python_float};
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

std::size_t element_count(std::size_t rank, const std::size_t* shape);
void append_event(Diagnostics& diagnostics, std::uint32_t flags, std::uint32_t operation, bool scalar);

// A checked borrowed float64 view. Element reads use logical C order.
// A borrowed C view is a NumPy array; temporary values keep their own kind.
class Array {
public:
    explicit Array(const RawArray& input, Kind kind = Kind::numpy_array);
    const RawArray& raw() const {return raw_;}
    std::size_t size() const {return count_;}
    std::size_t rank() const {return raw_.rank;}
    Kind kind() const {return kind_;}
    std::vector<std::size_t> shape() const;
    double at(std::size_t index) const;
    Number number(std::size_t index) const {return {at(index), kind_};}
private:
    RawArray raw_;
    std::size_t count_{};
    Kind kind_{Kind::numpy_array};
};

// A checked borrowed int32 label view.
class Labels {
public:
    explicit Labels(const RawLabels& input);
    const RawLabels& raw() const {return raw_;}
    std::size_t size() const {return count_;}
    std::int32_t at(std::size_t index) const;
private:
    RawLabels raw_;
    std::size_t count_{};
};

}  // namespace tpmshx::result
