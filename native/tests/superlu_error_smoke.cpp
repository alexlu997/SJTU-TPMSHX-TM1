#include "superlu_hooks.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

struct System {
    int n = 81;
    std::vector<int> columns, rows, perm_c, perm_r;
    std::vector<double> values, rhs, expected;
    explicit System(bool rowwise) : perm_c(n), perm_r(n), rhs(n, 0.), expected(n) {
        for (int i = 1; i < n; ++i) expected[i] = std::sin(.17 * i);
        // An actual nonsymmetric 9x9 pressure-like stencil, one unit pin.
        // Independently materialize canonical CSC or CSR for the SAME matrix.
        for (int outer = 0; outer < n; ++outer) {
            columns.push_back(static_cast<int>(rows.size()));
            for (int inner = 0; inner < n; ++inner) {
                const int r = rowwise ? outer : inner, c = rowwise ? inner : outer;
                double value = 0.;
                if (r == 0) value = c == 0 ? 1. : 0.;
                else if (r == c) value = 5.;
                else if (c == r - 1 && r % 9 != 0) value = -.7;
                else if (c == r + 1 && r % 9 != 8) value = -1.3;
                else if (c == r - 9) value = -.8;
                else if (c == r + 9) value = -1.2;
                if (value != 0.) {
                    rows.push_back(rowwise ? c : r);
                    values.push_back(value);
                    rhs[r] += value * expected[c];
                }
            }
        }
        columns.push_back(static_cast<int>(rows.size()));
    }
};

struct Observation {
    int status = -1;
    tpmshx_superlu_result result{};
    double maximum_error = 0., relative_residual = 0.;
};

void clean(const tpmshx_superlu_result& result) {
    require(result.outstanding_blocks == 0, "SuperLU left outstanding blocks");
    require(result.outstanding_bytes == 0, "SuperLU left outstanding bytes");
    require(std::memchr(result.message, '\0', sizeof(result.message)) != nullptr,
            "SuperLU error message is not NUL terminated");
}

Observation solve(bool rowwise, const tpmshx_superlu_test_control* control = nullptr) {
    System system(rowwise);
    const auto original_values = system.values;
    const auto original_rhs = system.rhs;
    Observation observation;
    const auto test_solve = rowwise ? tpmshx_superlu_test_solve_csr : tpmshx_superlu_test_solve_csc;
    const auto regular_solve = rowwise ? tpmshx_superlu_solve_csr : tpmshx_superlu_solve_csc;
    observation.status = control
        ? test_solve(
            system.n, static_cast<int>(system.values.size()), system.columns.data(),
            system.rows.data(), system.values.data(), system.rhs.data(),
            system.perm_c.data(), system.perm_r.data(), control, &observation.result)
        : regular_solve(
            system.n, static_cast<int>(system.values.size()), system.columns.data(),
            system.rows.data(), system.values.data(), system.rhs.data(),
            system.perm_c.data(), system.perm_r.data(), &observation.result);
    clean(observation.result);
    if (observation.status == TPMSHX_SUPERLU_OK && observation.result.info == 0) {
        std::vector<double> residual(system.n, 0.);
        for (int c = 0; c < system.n; ++c) {
            require(std::isfinite(system.rhs[c]), "SuperLU returned a nonfinite solution");
            observation.maximum_error = std::max(observation.maximum_error,
                std::abs(system.rhs[c] - system.expected[c]));
            for (int k = system.columns[c]; k < system.columns[c + 1]; ++k) {
                const int row = rowwise ? c : system.rows[k], col = rowwise ? system.rows[k] : c;
                residual[row] += original_values[k] * system.rhs[col];
            }
        }
        double r2 = 0., b2 = 0.;
        for (int r = 0; r < system.n; ++r) {
            r2 += std::pow(residual[r] - original_rhs[r], 2);
            b2 += std::pow(original_rhs[r], 2);
        }
        observation.relative_residual = std::sqrt(r2 / b2);
        require(observation.maximum_error <= 1e-12, "SuperLU known solution error exceeds gate");
        require(observation.relative_residual <= 1e-12, "SuperLU original residual exceeds gate");
    }
    // Borrowed caller buffers must remain owned and writable after failures.
    std::fill(system.values.begin(), system.values.end(), 17.);
    std::fill(system.rhs.begin(), system.rhs.end(), -23.);
    return observation;
}

Observation success(bool rowwise) {
    auto observation = solve(rowwise);
    require(observation.status == TPMSHX_SUPERLU_OK && observation.result.info == 0,
            "subsequent normal SuperLU solve did not recover");
    require(observation.result.allocation_attempts > 0 && observation.result.peak_bytes > 0,
            "normal SuperLU solve bypassed allocation ledger");
    return observation;
}

void allocations(bool rowwise) {
    const auto baseline = success(rowwise);
    const auto count = baseline.result.allocation_attempts;
    for (std::size_t ordinal = 1; ordinal <= count; ++ordinal) {
        tpmshx_superlu_test_control control{ordinal, nullptr, nullptr};
        const auto failed = solve(rowwise, &control);
        require(failed.status == TPMSHX_SUPERLU_ALLOCATION,
                "real SuperLU allocation fault did not return allocation status");
        require(failed.result.allocation_attempts == ordinal,
                "allocation failure ordinal was not reached exactly");
        require(std::strstr(failed.result.message, "allocation failed") != nullptr,
                "allocation failure lost its diagnostic");
        require(failed.result.message_truncated == 0, "short allocation message was truncated");
        if (ordinal > 1) require(failed.result.peak_bytes > 0, "allocation ledger lost prior allocations");
        const auto recovered = success(rowwise);
        require(recovered.result.allocation_attempts == count,
                "failed call contaminated following allocation state");
    }
    tpmshx_superlu_test_control beyond{count + 1, nullptr, nullptr};
    const auto unaffected = solve(rowwise, &beyond);
    require(unaffected.status == TPMSHX_SUPERLU_OK && unaffected.result.info == 0,
            "fault after final allocation changed a normal solve");
    std::cout << "{\"format\":\"" << (rowwise ? "csr" : "csc")
              << "\",\"case\":\"allocations\",\"status\":\"passed\",\"failpoints\":" << count
              << ",\"recovered\":" << count << ",\"peak_bytes\":" << baseline.result.peak_bytes
              << ",\"maximum_error\":" << baseline.maximum_error
              << ",\"relative_residual\":" << baseline.relative_residual
              << ",\"outstanding_blocks\":0,\"outstanding_bytes\":0}\n";
}

void aborts(bool rowwise) {
    const std::string long_message(4096, 'M'), long_file(4096, 'F');
    const tpmshx_superlu_test_control controls[] = {
        {0, long_message.c_str(), nullptr},  // Actual replaced vendor ABORT macro.
        {0, "forced abort", long_file.c_str()},
        {0, "forced abort", "fault-test.c"},
    };
    std::size_t truncated = 0;
    for (const auto& control : controls) {
        const auto failed = solve(rowwise, &control);
        require(failed.status == TPMSHX_SUPERLU_ABORTED, "ABORT did not return to the C boundary");
        require(failed.result.allocation_attempts > 0 && failed.result.peak_bytes > 0,
                "ABORT test did not release already allocated solver state");
        const bool expect_truncated = control.abort_message == long_message.c_str()
            || control.abort_file == long_file.c_str();
        require((failed.result.message_truncated != 0) == expect_truncated,
                "ABORT truncation flag is incorrect");
        if (expect_truncated) {
            ++truncated;
            require(std::strlen(failed.result.message) == sizeof(failed.result.message) - 1,
                    "long ABORT diagnostic was not bounded at buffer capacity");
        } else {
            require(std::strstr(failed.result.message, "forced abort at line 1 in file fault-test.c") != nullptr,
                    "ABORT lost the message/file/line context");
        }
        success(rowwise);
    }
    std::cout << "{\"format\":\"" << (rowwise ? "csr" : "csc")
              << "\",\"case\":\"aborts\",\"status\":\"passed\",\"aborts\":3,\"truncated\":"
              << truncated << ",\"recovered\":3,\"outstanding_blocks\":0,\"outstanding_bytes\":0}\n";
}

void singular(bool rowwise) {
    int columns[] = {0, 1, 3, 5}, rows[] = {0, 1, 2, 1, 2};
    double values[] = {1., 1., 1., 1., 1.}, rhs[] = {0., 1., 2.};
    int perm_c[3] = {0}, perm_r[3] = {0};
    tpmshx_superlu_result result{};
    const auto regular_solve = rowwise ? tpmshx_superlu_solve_csr : tpmshx_superlu_solve_csc;
    const int status = regular_solve(3, 5, columns, rows, values, rhs,
                                               perm_c, perm_r, &result);
    clean(result);
    require(status == TPMSHX_SUPERLU_OK && result.info > 0 && result.info <= 3,
            "native singular info was lost or reclassified");
    require(result.allocation_attempts > 0, "singular test bypassed actual SuperLU");
    success(rowwise);
    std::cout << "{\"format\":\"" << (rowwise ? "csr" : "csc")
              << "\",\"case\":\"singular\",\"status\":\"passed\",\"superlu_info\":" << result.info
              << ",\"recovered\":1,\"outstanding_blocks\":0,\"outstanding_bytes\":0}\n";
}

void concurrent(bool rowwise) {
    const auto count = success(rowwise).result.allocation_attempts;
    constexpr int rounds = 40;
    std::atomic<int> arrived{0}, successes{0}, faults{0};
    std::string errors[2];
    std::thread workers[2];
    for (int worker = 0; worker < 2; ++worker) {
        workers[worker] = std::thread([&, worker] {
            for (int round = 0; round < rounds; ++round) {
                arrived.fetch_add(1, std::memory_order_acq_rel);
                while (arrived.load(std::memory_order_acquire) < 2 * (round + 1))
                    std::this_thread::yield();
                try {
                    // Each round overlaps one failure call with one healthy call;
                    // alternate which thread fails to check TLS reset/recovery.
                    if (worker == round % 2) {
                        const std::size_t ordinal = 1 + (static_cast<std::size_t>(round) * 7) % count;
                        tpmshx_superlu_test_control control{ordinal, nullptr, nullptr};
                        const auto failed = solve(rowwise, &control);
                        require(failed.status == TPMSHX_SUPERLU_ALLOCATION
                                && failed.result.allocation_attempts == ordinal,
                                "one thread's fault injection leaked into another context");
                        ++faults;
                    } else {
                        success(rowwise);
                        ++successes;
                    }
                } catch (const std::exception& error) {
                    // Continue rendezvous rounds so a failed peer cannot deadlock.
                    if (errors[worker].empty()) errors[worker] = error.what();
                }
            }
            try { success(rowwise); } catch (const std::exception& error) { errors[worker] = error.what(); }
        });
    }
    for (auto& worker : workers) worker.join();
    require(errors[0].empty() && errors[1].empty(), "concurrent SuperLU boundary or recovery failed");
    require(successes == rounds && faults == rounds, "concurrent results are incomplete");
    success(rowwise);
    std::cout << "{\"format\":\"" << (rowwise ? "csr" : "csc")
              << "\",\"case\":\"concurrent\",\"status\":\"passed\",\"threads\":2,\"rounds\":"
              << rounds << ",\"successes\":" << successes << ",\"faults\":" << faults
              << ",\"outstanding_blocks\":0,\"outstanding_bytes\":0}\n";
}

}  // namespace

int main(int argc, char** argv) {
    try {
        require((argc == 3 || argc == 5) && std::string(argv[1]) == "--case",
                "usage: superlu_error_smoke --case NAME [--format csc|csr]");
        const std::string format = argc == 5 ? argv[4] : "csc";
        require((argc == 3 || std::string(argv[3]) == "--format") && (format == "csc" || format == "csr"),
                "unknown SuperLU input format");
        const bool rowwise = format == "csr";
        std::cout << std::setprecision(17);
        const std::string name(argv[2]);
        if (name == "allocations") allocations(rowwise);
        else if (name == "aborts") aborts(rowwise);
        else if (name == "singular") singular(rowwise);
        else if (name == "concurrent") concurrent(rowwise);
        else throw std::invalid_argument("unknown SuperLU qualification case");
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
