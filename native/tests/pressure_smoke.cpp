#include "tpmshx/pressure_candidate.hpp"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using tpmshx::PressureCandidate;
using tpmshx::PressureControl;
using tpmshx::PressureResult;
using tpmshx::PressureSystem;

std::string quoted(const std::string& text) {
    std::string result = "\"";
    for (const char value : text) {
        if (value == '"' || value == '\\') { result += '\\'; result += value; }
        else if (value == '\n') result += "\\n";
        else if (value == '\r') result += "\\r";
        else if (value == '\t') result += "\\t";
        else result += value;
    }
    return result+'"';
}

void number(double value) {
    if (std::isfinite(value)) std::cout << value;
    else std::cout << "null";
}

void output(const PressureResult& result) {
    std::cout << std::setprecision(17)
        << "{\"status\":" << quoted(result.success ? "solved" : "linear_failure")
        << ",\"method\":" << quoted(result.method)
        << ",\"exit\":" << quoted(result.exit)
        << ",\"amg_exit\":" << quoted(result.amg_exit)
        << ",\"rebuild_reason\":" << quoted(result.rebuild_reason)
        << ",\"detail\":" << quoted(result.detail)
        << ",\"iterations\":" << result.iterations
        << ",\"rebuild_count\":" << result.rebuild_count
        << ",\"hierarchy_bytes\":" << result.hierarchy_bytes
        << ",\"superlu_info\":" << result.superlu_info
        << ",\"rhs_scale\":"; number(result.rhs_scale);
    std::cout << ",\"relative_residual\":"; number(result.relative_residual);
    std::cout << ",\"absolute_residual\":"; number(result.absolute_residual);
    std::cout << ",\"iterative_relative_residual\":"; number(result.iterative_relative_residual);
    std::cout << ",\"pin_max_abs\":"; number(result.pin_max_abs);
    std::cout << ",\"diagonal_drift\":"; number(result.diagonal_drift);
    std::cout << ",\"build_seconds\":"; number(result.build_seconds);
    std::cout << ",\"solve_seconds\":"; number(result.solve_seconds);
    std::cout << ",\"x\":[";
    for (std::size_t i = 0; i < result.x.size(); ++i) {
        if (i) std::cout << ',';
        number(result.x[i]);
    }
    std::cout << "]}" << std::endl;
}

std::string token() {
    std::string value;
    if (!(std::cin >> value)) throw std::invalid_argument("truncated pressure request");
    return value;
}

int integer() {
    const auto value = token();
    std::size_t end = 0;
    const auto parsed = std::stoll(value,&end);
    if (end != value.size() || parsed < std::numeric_limits<int>::min()
        || parsed > std::numeric_limits<int>::max())
        throw std::invalid_argument("pressure integer is outside 32-bit range");
    return static_cast<int>(parsed);
}

double real() {
    const auto value = token();
    std::size_t end = 0;
    const double parsed = std::stod(value,&end);
    if (end != value.size()) throw std::invalid_argument("invalid pressure number");
    return parsed;
}

int stream() {
    PressureCandidate candidate;
    std::string tag;
    while (std::cin >> tag) {
        // Text is intentionally test-only: version, dim, N, nnz, rtol,
        // force-rebuild, drift-threshold; then ptr/col/value/rhs/pin arrays.
        PressureSystem matrix;
        PressureControl control;
        try {
            if (tag != "TM1_PRESSURE_V1") throw std::invalid_argument("unsupported pressure input version");
            control.dimension = integer();
            const int n = integer(), nnz = integer();
            control.relative_tolerance = real();
            const int force = integer();
            control.diagonal_drift_threshold = real();
            if (n <= 0 || nnz <= 0 || (force != 0 && force != 1))
                throw std::invalid_argument("invalid pressure request extents or rebuild flag");
            control.force_rebuild = force != 0;
            matrix.row_offsets.resize(static_cast<std::size_t>(n)+1);
            matrix.columns.resize(nnz); matrix.values.resize(nnz);
            matrix.rhs.resize(n); matrix.pin_mask.resize(n);
            for (auto& value : matrix.row_offsets) value = integer();
            for (auto& value : matrix.columns) value = integer();
            for (auto& value : matrix.values) value = real();
            for (auto& value : matrix.rhs) value = real();
            for (auto& value : matrix.pin_mask) {
                const int parsed = integer();
                if (parsed != 0 && parsed != 1) throw std::invalid_argument("invalid pressure pin mask");
                value = static_cast<unsigned char>(parsed);
            }
        } catch (const std::bad_alloc& error) {
            std::cout << "{\"status\":\"allocation_failure\",\"detail\":" << quoted(error.what()) << "}" << std::endl;
            return 3;
        } catch (const std::exception& error) {
            std::cout << "{\"status\":\"invalid_input\",\"detail\":" << quoted(error.what()) << "}" << std::endl;
            return 2;  // A malformed stream cannot be resynchronized safely.
        }
        try {
            output(candidate.solve(matrix,control));
        } catch (const std::invalid_argument& error) {
            std::cout << "{\"status\":\"invalid_input\",\"detail\":" << quoted(error.what()) << "}" << std::endl;
        } catch (const std::bad_alloc& error) {
            std::cout << "{\"status\":\"allocation_failure\",\"detail\":" << quoted(error.what()) << "}" << std::endl;
        } catch (const std::exception& error) {
            // No blanket numerical fallback: unknown exceptions are failures.
            std::cout << "{\"status\":\"backend_error\",\"detail\":" << quoted(error.what()) << "}" << std::endl;
        }
    }
    return 0;
}

PressureSystem tridiagonal(int n, std::vector<double>& expected) {
    PressureSystem matrix;
    matrix.row_offsets.push_back(0);
    matrix.rhs.resize(n); matrix.pin_mask.assign(n,0); matrix.pin_mask[0] = 1;
    expected.resize(n);
    for (int i = 0; i < n; ++i) expected[i] = .125*(i%17);
    for (int i = 0; i < n; ++i) {
        if (i > 0) { matrix.columns.push_back(i-1); matrix.values.push_back(-1.); }
        matrix.columns.push_back(i); matrix.values.push_back(i == 0 ? 1. : 4.);
        if (i > 0 && i+1 < n) { matrix.columns.push_back(i+1); matrix.values.push_back(-1.); }
        matrix.row_offsets.push_back(static_cast<int>(matrix.values.size()));
        for (int k = matrix.row_offsets[i]; k < matrix.row_offsets[i+1]; ++k)
            matrix.rhs[i] += matrix.values[k]*expected[matrix.columns[k]];
    }
    return matrix;
}

int smoke() {
    PressureCandidate solver;
    // Independent, nonsymmetric three-row problem: x=(0,2,-1).
    PressureSystem direct{{0,1,4,6},{0,0,1,2,1,2},{1.,-1.,4.,-1.,-2.,5.},
                          {0.,9.,-9.},{1,0,0}};
    const auto small = solver.solve(direct,{2,1e-7,false,.05});
    if (!small.success || small.method != "superlu_colamd"
        || std::abs(small.x[0]) > 1e-12 || std::abs(small.x[1]-2.) > 1e-12
        || std::abs(small.x[2]+1.) > 1e-12) return 1;
    std::vector<double> expected;
    auto large = tridiagonal(2001,expected);
    auto iterated = solver.solve(large);
    if (!iterated.success || iterated.method != "pyamg_classical_bicgstab"
        || iterated.rebuild_reason != "cold" || iterated.relative_residual > 1e-7) return 2;
    for (std::size_t i = 0; i < expected.size(); ++i)
        if (std::abs(iterated.x[i]-expected[i]) > 1e-7) return 3;
    for (auto& value : large.rhs) value *= 1e-30;
    const auto tiny = solver.solve(large);
    if (!tiny.success || tiny.method != "pyamg_classical_bicgstab"
        || tiny.rebuild_count != 1 || tiny.relative_residual > 1e-7) return 4;
    for (std::size_t i = 0; i < expected.size(); ++i)
        if (std::abs(tiny.x[i]/1e-30-expected[i]) > 1e-7) return 5;
    std::cout << "{\"status\":\"passed\",\"checks\":[\"analytical_lu\",\"amg_above_2000\",\"tiny_rhs_original_residual\",\"hierarchy_reuse\"]}" << std::endl;
    return 0;
}
}  // namespace

int main(int argc, char** argv) {
    if (argc == 2 && std::string(argv[1]) == "--stream") return stream();
    if (argc != 1) {
        std::cerr << "usage: pressure_smoke [--stream]" << std::endl;
        return 2;
    }
    try { return smoke(); }
    catch (const std::exception& error) {
        std::cerr << "pressure smoke: " << error.what() << std::endl;
        return 3;
    }
}
