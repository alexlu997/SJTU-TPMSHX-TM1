#include "tpmshx/result_arithmetic.hpp"

#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>

int main() {
    using namespace tpmshx::result;
    std::array<double, 2> doubles{1.25, -3.5};
    const std::array<std::size_t, 1> shape{2};
    RawArray raw{doubles.data(), 1, shape.data()};
    Array values(raw);
    if (values.size() != 2 || values.at(0) != doubles[0] || values.at(1) != doubles[1]) return 1;
    if (arithmetic::python_float_sum({1e16, 1., -1e16}) != 1.) return 2;
    std::array<std::int32_t, 2> label_values{0, 2};
    RawLabels raw_labels{label_values.data(), 1, shape.data()};
    Labels labels(raw_labels);
    if (labels.size() != 2 || labels.at(0) != 0 || labels.at(1) != 2) return 3;
    try {
        RawArray bad{nullptr, 1, shape.data()};
        Array rejected(bad);
        (void)rejected;
        return 4;
    } catch (const std::invalid_argument&) {
    }
    try {
        RawLabels bad{nullptr, 1, shape.data()};
        Labels rejected(bad);
        (void)rejected;
        return 5;
    } catch (const std::invalid_argument&) {
    }
    std::cout << "PASS: independent result C++ caller for float64 arrays and int32 labels\n";
    return 0;
}
